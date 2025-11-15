"""State definition for LangGraph agent."""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """State shared across LangGraph nodes."""

    messages: List[Dict[str, str]]
    plan: Optional[str]
    tool_results: List[Dict[str, str]]
    pending_tool: Optional[Dict[str, object]]
    final_response: Optional[str]
    done: bool
    provider: str
    model: str
