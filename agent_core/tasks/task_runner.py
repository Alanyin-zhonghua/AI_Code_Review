"""Task-level多轮 Agent 入口。"""

from __future__ import annotations

import json
from typing import Optional

from agent_core.config.settings import settings
from agent_core.domain.models import ChatMessage, ChatRequest
from agent_core.providers import create_provider
from agent_core.tools.definitions import ToolCall

from .config import TaskConfig, MAX_TASK_STEPS
from .file_provider import FileToolProvider, LocalFileToolProvider
from .tools import get_tool_spec, task_tool_defs
from .trace import TraceRecorder


def run_agent(
    user_input: str,
    config: TaskConfig,
    *,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> str:
    """执行一个带有工具闭环的任务。"""

    provider_key = provider_name or getattr(settings, "default_provider", "glm")
    model_key = model_name or getattr(settings, "default_model", "ide-chat")
    config.ensure_trace_id()
    file_provider = LocalFileToolProvider(config.root_path)
    trace = TraceRecorder(config)
    provider_client = create_provider(provider_key)

    system_prompt = _build_system_prompt(config)
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_input, meta={"task_mode": config.mode}),
    ]
    tool_defs = task_tool_defs()

    for step in range(config.max_steps_clamped):
        req = ChatRequest(
            provider=provider_key,
            model=model_key,
            messages=messages,
            temperature=0.3,
            tools=tool_defs,
            tool_choice="auto",
        )
        result = provider_client.chat(req)
        assistant_msg = result.choices[0].message
        messages.append(assistant_msg)
        summary = _summary(assistant_msg.content)
        trace.record_llm_step(step, has_tool_calls=bool(assistant_msg.tool_calls), summary=summary)

        if not assistant_msg.tool_calls:
            final_content = assistant_msg.content or ""
            trace.finalize("ok", final_content)
            return final_content

        for tool_call in assistant_msg.tool_calls:
            tool_response = _execute_tool_call(tool_call, config, file_provider, trace, step)
            messages.append(
                ChatMessage(
                    role="tool",
                    content=tool_response,
                    tool_call_id=tool_call.id,
                )
            )

    final_text = f"本次任务超过最大步骤限制（{config.max_steps_clamped}/{MAX_TASK_STEPS}），已自动停止。"
    trace.finalize("max_steps_exceeded", final_text)
    return final_text


def _execute_tool_call(
    call: ToolCall,
    config: TaskConfig,
    file_provider: FileToolProvider,
    trace: TraceRecorder,
    step: int,
) -> str:
    args = call.arguments or {}
    spec = get_tool_spec(call.name or "")
    if not spec:
        error = {
            "error": "UNKNOWN_TOOL",
            "message": f"Tool '{call.name}' not registered",
        }
        trace.record_tool_step(step, tool_name=call.name or "", args=args, result_summary=None, error=error)
        return json.dumps(error, ensure_ascii=False)

    if config.mode == "read_only" and spec.is_write:
        error = {
            "error": "WRITE_DISALLOWED_IN_READ_ONLY_MODE",
            "message": "当前任务处于 read_only 模式，禁止写入文件。",
        }
        trace.record_tool_step(step, tool_name=spec.name, args=args, result_summary=None, error=error)
        return json.dumps(error, ensure_ascii=False)

    try:
        raw = spec.handler(args, config, file_provider)
        if isinstance(raw, str):
            content = raw
        else:
            content = json.dumps(raw, ensure_ascii=False)
        trace.record_tool_step(step, tool_name=spec.name, args=args, result_summary=_summary(content))
        return content
    except Exception as exc:  # noqa: BLE001 - 需要把异常转换为工具错误
        error = {
            "error": "TOOL_EXECUTION_ERROR",
            "message": str(exc),
        }
        trace.record_tool_step(step, tool_name=spec.name, args=args, result_summary=None, error=error)
        return json.dumps(error, ensure_ascii=False)


def _build_system_prompt(config: TaskConfig) -> str:
    return (
        "你是一名经验丰富的本地代码助手。"
        "如果任务复杂，请先给出简要计划，再执行工具。"
        "每一轮回复都要评估是否已经完成任务，若已完成则停止调用工具并总结结论。"
        f"你的操作范围仅限于项目根目录: {config.project_root}。"
        "可以使用 read_file/list_project_files/search_in_files/write_file_safe 等工具。"
        "写操作只能在 safe_write 模式下执行，并确保说明修改原因。"
    )


def _summary(text: Optional[str], limit: int = 160) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."
