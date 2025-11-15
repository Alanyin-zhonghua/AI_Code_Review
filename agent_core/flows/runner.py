"""High-level entry point for LangGraph agent."""

from __future__ import annotations

from typing import Iterable, Optional

from agent_core.config.settings import settings
from agent_core.flows.state import AgentState
from agent_core.flows.graph import build_graph
from agent_core.flows.tools_interface import ToolManager

_tool_manager = ToolManager()
_graph = build_graph(_tool_manager)


def _initial_messages(user_message: str, history: Optional[Iterable[str]] = None):
    messages = []
    if history:
        for item in history:
            messages.append({"role": "user", "content": str(item)})
    messages.append({"role": "user", "content": user_message})
    return messages


def run_agent(
    user_message: str,
    *,
    history: Optional[Iterable[str]] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> str:
    """Execute LangGraph agent and return final response.

    Args:
        user_message: 用户输入
        history: 额外的用户上下文（简单字符串列表）
        provider_name: 指定 Provider
        model_name: 指定逻辑模型名
    """

    provider = provider_name or getattr(settings, "default_provider", "glm")
    model = model_name or getattr(settings, "default_model", "ide-chat")
    state: AgentState = {
        "messages": _initial_messages(user_message, history),
        "plan": None,
        "tool_results": [],
        "pending_tool": None,
        "final_response": None,
        "done": False,
        "provider": provider,
        "model": model,
    }
    result = _graph.invoke(state)
    return result.get("final_response") or ""


def set_workspace_root(path: str) -> None:
    """Update workspace root for tool manager & LangGraph."""

    global _tool_manager, _graph
    _tool_manager = ToolManager(path)
    _graph = build_graph(_tool_manager)
