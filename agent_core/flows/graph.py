"""LangGraph construction and node implementations."""

from __future__ import annotations

import json
import ast
from typing import Dict, List

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_core.flows.state import AgentState
from agent_core.flows.tools_interface import ToolManager
from agent_core.providers import create_provider
from agent_core.domain.models import ChatMessage, ChatRequest
from agent_core.infrastructure.logging.logger import logger
from agent_core.infrastructure.logging.logger import logger

PLANNER_PROMPT = """你是 IDE 智能助手，请基于用户最新需求制定执行计划，输出简短中文计划。"""

DECISION_PROMPT = """你是 IDE 智能助手，请根据对话和工具结果，返回 JSON：
{"action": "tool" 或 "final", "thought": "...", "tool_name": "", "tool_args": {...}, "response": "最终回答"}
仅当 action 为 "final" 时填写 response。可用工具: {tools}
"""

FINAL_PROMPT = """根据以下上下文和工具结果，输出给用户的最终回答（中文）：
- 计划: {plan}
- 最近工具结果: {tool_results}
"""


def _convert_messages(msgs: List[Dict[str, str]]) -> List[ChatMessage]:
    return [ChatMessage(role=m.get("role", "user"), content=m.get("content", "")) for m in msgs]


def _call_llm(messages: List[Dict[str, str]], system_prompt: str, provider_name: str, model_name: str) -> str:
    try:
        provider = create_provider(provider_name)
        chat_messages = [ChatMessage(role="system", content=system_prompt)] + _convert_messages(messages)
        req = ChatRequest(provider=provider_name, model=model_name, messages=chat_messages)
        result = provider.chat(req)
        return result.choices[0].message.content
    except Exception as exc:  # pragma: no cover - defensive
        return f"[LLM 调用失败: {exc}]"


def planner_node(state: AgentState) -> AgentState:
    logger.info("planner_node.start", extra={"extra": {"provider": state["provider"], "model": state["model"]}})
    content = _call_llm(state["messages"], PLANNER_PROMPT, state["provider"], state["model"])
    plan = content.strip()
    state["plan"] = plan
    if plan:
        state["messages"].append({"role": "assistant", "content": f"[plan] {plan}"})
    logger.info("planner_node.end", extra={"extra": {"plan": plan}})
    return state


def agent_node(state: AgentState, tool_manager: ToolManager) -> AgentState:
    tools_text = tool_manager.available_tools_text()
    logger.info("agent_node.start", extra={"extra": {"messages": len(state["messages"])}})
    decision = _call_llm(state["messages"], DECISION_PROMPT.format(tools=tools_text), state["provider"], state["model"])
    try:
        payload = json.loads(decision)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(decision)
        except Exception:
            payload = {"action": "final", "response": decision}
    action = payload.get("action", "final")
    thought = payload.get("thought", "")
    if thought:
        state["messages"].append({"role": "assistant", "content": f"[thought] {thought}"})
    if action == "tool":
        state["pending_tool"] = {
            "name": payload.get("tool_name", ""),
            "arguments": payload.get("tool_args", {}),
        }
        logger.info("agent_node.tool_decision", extra={"extra": state["pending_tool"]})
    else:
        state["final_response"] = payload.get("response") or decision
        state["done"] = True
        logger.info("agent_node.final_decision")
    return state


def tool_node(state: AgentState, tool_manager: ToolManager) -> AgentState:
    pending = state.get("pending_tool")
    if not pending:
        state["tool_results"].append({"error": "no pending tool"})
        logger.warning("tool_node.no_pending_tool")
        return state
    logger.info("tool_node.execute", extra={"extra": pending})
    result = tool_manager.run(pending.get("name", ""), pending.get("arguments", {}))
    state.setdefault("tool_results", []).append(result)
    state["pending_tool"] = None
    if result.get("ok"):
        state["messages"].append({"role": "tool", "content": str(result.get("content"))})
    else:
        state["messages"].append({"role": "tool", "content": f"Tool error: {result.get('error')}"})
    logger.info("tool_node.result", extra={"extra": {"ok": result.get("ok")}})
    return state


def final_answer_node(state: AgentState) -> AgentState:
    if not state.get("final_response"):
        tool_summary = "\n".join([str(r) for r in state.get("tool_results", [])][-3:]) or "无"
        prompt = FINAL_PROMPT.format(plan=state.get("plan", ""), tool_results=tool_summary)
        state["final_response"] = _call_llm(state["messages"], prompt, state["provider"], state["model"])
    state["done"] = True
    state["messages"].append({"role": "assistant", "content": state["final_response"] or ""})
    return state


def agent_router(state: AgentState) -> str:
    if state.get("pending_tool"):
        return "tool"
    if state.get("done"):
        return "final"
    return "agent"


def build_graph(tool_manager: ToolManager) -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("planner", lambda s: planner_node(s))
    graph.add_node("agent", lambda s: agent_node(s, tool_manager))
    graph.add_node("tool", lambda s: tool_node(s, tool_manager))
    graph.add_node("final", final_answer_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "agent")
    graph.add_conditional_edges("agent", agent_router, {"tool": "tool", "final": "final", "agent": "agent"})
    graph.add_edge("tool", "agent")
    graph.add_edge("final", END)
    return graph.compile()
