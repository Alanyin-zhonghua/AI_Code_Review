from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ToolParam:
    name: str
    description: str
    required: bool
    schema: Dict[str, Any]


@dataclass
class ToolDef:
    name: str
    description: str
    params: Dict[str, ToolParam]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    content: str