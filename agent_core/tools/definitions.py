"""工具数据结构定义。

这些 dataclass 描述了“工具调用”的 schema，既用于：
- 将可用工具列表暴露给 LLM（ToolDef / ToolParam）。
- 在 AgentEngine 中保存和执行模型触发的工具调用（ToolCall / ToolResult）。
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ToolParam:
    """单个工具参数的定义。"""

    name: str
    description: str
    required: bool
    schema: Dict[str, Any]


@dataclass
class ToolDef:
    """一个可供 LLM 调用的工具定义。"""

    name: str
    description: str
    params: Dict[str, ToolParam]


@dataclass
class ToolCall:
    """模型发起的一次工具调用请求。"""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """工具执行结果的封装（文本形式）。"""

    call_id: str
    content: str
