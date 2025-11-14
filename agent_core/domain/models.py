from dataclasses import dataclass, field
from typing import Literal, Optional, Any, Dict, List


Role = Literal["system", "user", "assistant", "tool", "tool_result"]


@dataclass
class ChatMessage:
    role: Role
    content: str
    meta: Dict[str, Any] = field(default_factory=dict)
    tool_calls: Optional[List["ToolCall"]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ChatRequest:
    provider: str
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: Optional[int] = None
    tools: Optional[List["ToolDef"]] = None
    tool_choice: Literal["auto", "none", "required"] = "auto"


@dataclass
class ChatUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatChoice:
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


@dataclass
class ChatResult:
    provider: str
    model: str
    choices: List[ChatChoice]
    usage: Optional[ChatUsage] = None
    raw: Optional[dict] = None