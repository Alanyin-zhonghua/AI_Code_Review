"""GLM / BigModel Provider 适配器。

接口风格与 OpenAI/Kimi 类似，均使用 chat/completions 端点：
- URL: {base_url}/chat/completions
- 认证: Authorization: Bearer <api_key>

具体字段以官方文档为准，本实现只依赖公共字段：model/messages/temperature/max_tokens/top_p/stream。
"""

import json
from typing import Any, Dict, Iterable, List

import httpx

from agent_core.config.settings import settings
from agent_core.domain.exceptions import ApiError, NetworkError, RateLimitError, ValidationError
from agent_core.domain.models import (
    ChatChoice,
    ChatMessage,
    ChatRequest,
    ChatResult,
    ChatStreamChunk,
    ChatStreamChoice,
    ChatUsage,
)
from agent_core.providers.registry import GLM_CONFIG, ModelConfig
from agent_core.tools.definitions import ToolCall, ToolDef


class GlmClient:
    """GLM / BigModel Provider 客户端实现。"""

    name = "glm"

    def __init__(self, cfg=settings):
        self._settings = cfg

    # ---- 非流式 ----

    def chat(self, req: ChatRequest) -> ChatResult:
        if not getattr(self._settings, "glm_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="GLM_API_KEY not set")
        model_cfg = GLM_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg, stream=False)
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "glm_base_url", None) or GLM_CONFIG.base_url
                resp = client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.glm_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))
        if resp.status_code == 429:
            raise RateLimitError(code="RATE_LIMIT", message="GLM rate limit")
        if resp.status_code >= 400:
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
        data = resp.json()
        return self._parse_response(data, req)

    # ---- 流式 ----

    def chat_stream(self, req: ChatRequest) -> Iterable[ChatStreamChunk]:
        if not getattr(self._settings, "glm_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="GLM_API_KEY not set")
        model_cfg = GLM_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg, stream=True)
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "glm_base_url", None) or GLM_CONFIG.base_url
                with client.stream(
                    "POST",
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.glm_api_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code == 429:
                        raise RateLimitError(code="RATE_LIMIT", message="GLM rate limit")
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
                        yield self._parse_stream_chunk(payload_chunk, req)
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))

    # ---- 辅助方法 ----

    def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig, stream: bool) -> dict:
        msgs = [self._message_to_payload(m) for m in req.messages]
        payload = {
            "model": model_cfg.provider_model,
            "messages": msgs,
            "temperature": req.temperature or model_cfg.default_temperature,
            "max_tokens": req.max_tokens or model_cfg.max_tokens,
            "top_p": req.top_p,
            "stream": stream,
        }
        if req.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in req.tools]
            payload["tool_choice"] = req.tool_choice
        return payload

    def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
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
        return ChatResult(provider="glm", model=req.model, choices=choices, usage=usage, raw=data)

    def _build_chat_message(self, payload: Dict[str, Any]) -> ChatMessage:
        """解析 GLM message，兼容 tool_calls/function_call。"""

        role = payload.get("role") or "assistant"
        content = payload.get("content") or ""
        tool_calls_raw = payload.get("tool_calls") or []
        tool_calls: List[ToolCall] = []
        for idx, call in enumerate(tool_calls_raw):
            func = call.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or f"tool_call_{idx}",
                    name=func.get("name") or call.get("name") or "",
                    arguments=self._parse_arguments(func.get("arguments")),
                )
            )

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
            role=role,
            content=content,
            tool_calls=tool_calls or None,
            tool_call_id=payload.get("tool_call_id"),
        )

    def _parse_stream_chunk(self, data: dict, req: ChatRequest) -> ChatStreamChunk:
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
            provider="glm",
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
            serialized = []
            for call in message.tool_calls:
                serialized.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                )
            payload["tool_calls"] = serialized
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    def _serialize_tool(self, tool: ToolDef) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for name, param in tool.params.items():
            schema = param.schema or {"type": "string"}
            if param.description:
                schema = {**schema, "description": param.description}
            properties[name] = schema
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

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
        return {}
