"""Kimi Provider 适配器。

本模块负责：

1. 接收统一的 ChatRequest。
2. 将其转换为 Moonshot/Kimi 的 HTTP API 请求格式。
3. 调用 HTTP 接口并处理网络/API 异常。
4. 将响应 JSON 解析为统一的 ChatResult / ChatMessage 结构（含工具调用）。

换句话说，这里就是“不同厂商 JSON ⇄ 项目内部统一模型”的核心转换层，
后续接入其他 Provider 时，可以参考此文件的结构实现对应的 Client。
"""

import httpx
import json
from typing import Any, Dict, List, Iterable

from agent_core.domain.models import (
    ChatRequest,
    ChatResult,
    ChatMessage,
    ChatChoice,
    ChatUsage,
    ChatStreamChunk,
    ChatStreamChoice,
)
from agent_core.domain.exceptions import NetworkError, ApiError, RateLimitError, ValidationError
from agent_core.providers.registry import KIMI_CONFIG, ModelConfig
from agent_core.tools.definitions import ToolDef, ToolCall


class KimiClient:
    """Kimi 提供方客户端实现。

    - name: Provider 名称（供日志/调试使用）。
    - chat: 对外统一调用入口，返回 ChatResult。
    """

    name = "kimi"

    def __init__(self, settings):
        # Settings 里包含 base_url、api_key、超时等配置
        self._settings = settings

    def chat(self, req: ChatRequest) -> ChatResult:
        """执行一次非流式对话调用。

        步骤：
        1. 读取模型配置（logical model -> provider model）。
        2. 构造 HTTP 请求 payload。
        3. 发送请求并捕获网络错误/限流/服务端错误。
        4. 使用统一的解析函数构造 ChatResult。
        """

        if not getattr(self._settings, "kimi_api_key", None):
            # 配置缺失走 ValidationError，方便上层统一处理
            raise ValidationError(code="MISSING_API_KEY", message="KIMI_API_KEY not set")
        model_cfg = KIMI_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg)
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "kimi_base_url", None) or KIMI_CONFIG.base_url
                resp = client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.kimi_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as e:
            # 网络错误：DNS 失败、连接超时等
            raise NetworkError(code="NETWORK_ERROR", message=str(e))
        if resp.status_code == 429:
            # 限流错误交给上层做重试/退避
            raise RateLimitError(code="RATE_LIMIT", message="Kimi rate limit")
        if resp.status_code >= 400:
            # 其他 HTTP 错误统一包装为 ApiError
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
        data = resp.json()
        return self._parse_response(data, req)

    def chat_stream(self, req: ChatRequest) -> Iterable[ChatStreamChunk]:
        """执行一次流式对话调用，逐步 yield ChatStreamChunk。"""

        if not getattr(self._settings, "kimi_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="KIMI_API_KEY not set")
        model_cfg = KIMI_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg)
        payload["stream"] = True
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "kimi_base_url", None) or KIMI_CONFIG.base_url
                with client.stream(
                    "POST",
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.kimi_api_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code == 429:
                        raise RateLimitError(code="RATE_LIMIT", message="Kimi rate limit")
                    if resp.status_code >= 400:
                        raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        data_str = line
                        if data_str.startswith("data:"):
                            data_str = data_str[5:].strip()
                        else:
                            data_str = data_str.strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            payload_chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        chunk = self._parse_stream_chunk(payload_chunk, req)
                        yield chunk
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))

    def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig) -> dict:
        """将 ChatRequest 转成 Kimi 所需的请求 JSON。"""

        msgs = [self._message_to_payload(m) for m in req.messages]
        payload = {
            "model": model_cfg.provider_model,
            "messages": msgs,
            "temperature": req.temperature or model_cfg.default_temperature,
            "max_tokens": req.max_tokens or model_cfg.max_tokens,
            "top_p": req.top_p,
        }
        # 工具调用：如果请求中携带了工具定义，则按 Moonshot 规范转换
        if req.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in req.tools]
            payload["tool_choice"] = req.tool_choice
        return payload

    def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
        """将 Kimi 的原始响应 JSON 解析为统一的 ChatResult。"""

        choices: list[ChatChoice] = []
        for i, ch in enumerate(data.get("choices", [])):
            msg = ch.get("message") or {}
            cm = self._build_chat_message(msg)
            choices.append(ChatChoice(index=i, message=cm, finish_reason=ch.get("finish_reason")))
        usage_raw = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return ChatResult(provider="kimi", model=req.model, choices=choices, usage=usage, raw=data)

    def _serialize_tool(self, tool: ToolDef) -> Dict[str, Any]:
        """把内部的 ToolDef 转成 Moonshot/Kimi 的 function tool 描述。"""

        properties: Dict[str, Any] = {}
        required: List[str] = []
        for name, param in tool.params.items():
            properties[name] = param.schema or {"type": "string"}
            if param.description:
                properties[name] = {
                    **properties[name],
                    "description": param.description,
                }
            if param.required:
                required.append(name)
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _build_chat_message(self, payload: Dict[str, Any]) -> ChatMessage:
        """将单条厂商 message 转换为 ChatMessage。

        同时负责把 tool_calls 字段解析为统一的 ToolCall 列表，
        方便 AgentEngine 后续执行工具循环。
        """

        tool_calls_raw = payload.get("tool_calls") or []
        tool_calls: List[ToolCall] = []
        for idx, call in enumerate(tool_calls_raw):
            func = call.get("function") or {}
            name = func.get("name") or call.get("name") or ""
            arguments = self._parse_arguments(func.get("arguments"))
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or f"tool_call_{idx}",
                    name=name,
                    arguments=arguments,
                )
            )

        # Moonshot 在部分模型上仍会返回旧版 function_call 字段
        function_call = payload.get("function_call")
        if function_call:
            tool_calls.append(
                ToolCall(
                    id=function_call.get("id") or "function_call",
                    name=function_call.get("name") or "",
                    arguments=self._parse_arguments(function_call.get("arguments")),
                )
            )
        return ChatMessage(
            role=payload.get("role") or "assistant",
            content=payload.get("content") or "",
            tool_calls=tool_calls or None,
            tool_call_id=payload.get("tool_call_id"),
        )

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        """解析工具调用的 arguments 字段。

        Moonshot/Kimi 会把 arguments 作为 JSON 字符串返回，这里做一层
        json.loads 尝试，失败时保留原始字符串到 `_raw`，避免信息丢失。
        """

        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
        return {}

    def _parse_stream_chunk(self, data: dict, req: ChatRequest) -> ChatStreamChunk:
        """解析流式响应中的单条增量。"""

        choices: list[ChatStreamChoice] = []
        for i, ch in enumerate(data.get("choices", [])):
            delta_payload = ch.get("delta") or {}
            delta_msg = self._build_chat_message(delta_payload)
            choices.append(
                ChatStreamChoice(
                    index=ch.get("index", i),
                    delta=delta_msg,
                    finish_reason=ch.get("finish_reason"),
                )
            )
        usage_raw = data.get("usage") or {}
        usage = None
        if usage_raw:
            usage = ChatUsage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            )
        return ChatStreamChunk(
            provider="kimi",
            model=req.model,
            choices=choices,
            usage=usage,
            raw=data,
        )

    def _message_to_payload(self, message: ChatMessage) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": message.role}
        if message.content:
            payload["content"] = message.content
        if message.tool_calls:
            serialized_calls = []
            for call in message.tool_calls:
                serialized_calls.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                )
            payload["tool_calls"] = serialized_calls
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload
