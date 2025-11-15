"""统一的对话与结果数据模型。

本模块定义了 Agent 内部在不同 Provider 之间共享的标准数据结构：

- ChatMessage: 一条对话消息（system/user/assistant/tool/...）。
- ChatRequest: 发给底层 LLM Provider 的完整请求。
- ChatResult: 从 Provider 解析后的统一响应结果。

所有 Provider 适配器（如 KimiClient）都必须只依赖这些模型，
并负责在各自的 API JSON 和这些模型之间做转换。
"""

from dataclasses import dataclass, field
from typing import Literal, Optional, Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    # 仅在类型检查时导入，避免运行时循环依赖
    from agent_core.tools.definitions import ToolCall, ToolDef


# LLM 消息角色类型（与 OpenAI / Moonshot 等厂商的 role 字段对应）
Role = Literal["system", "user", "assistant", "tool", "tool_result"]


@dataclass
class ChatMessage:
    """一条对话消息，既可用于请求，也可用于响应。

    - role: 消息角色，如 system/user/assistant。
    - content: 纯文本内容。
    - meta: 附加元数据（文件路径、行号、模型信息等），不直接发给 Provider，
      主要用于日志与上层 UI 展示。
    - tool_calls: 当 role 为 "assistant" 且模型触发工具调用时，
      这里保存模型发起的工具调用列表。
    - tool_call_id: 当 role 为 "tool"/"tool_result" 时，用于关联某一次工具调用。
    """

    role: Role
    content: str
    meta: Dict[str, Any] = field(default_factory=dict)
    tool_calls: Optional[List["ToolCall"]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ChatRequest:
    """一次完整的聊天请求。

    Agent 会将上下文裁剪后生成 ChatRequest，再交给具体 ProviderClient。
    Provider 适配层负责把本结构转换成各家 API 的 JSON 请求体。
    """

    provider: str  # 逻辑 Provider 名，如 "kimi"
    model: str  # 逻辑模型名，如 "ide-chat"（再由 registry 映射为真实模型名）
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: Optional[int] = None
    # 工具定义列表：当模型支持工具调用时，会通过 Provider 转成对应 schema
    tools: Optional[List["ToolDef"]] = None
    # 模型是否必须/禁止使用工具
    tool_choice: Literal["auto", "none", "required"] = "auto"


@dataclass
class ChatUsage:
    """Provider 返回的 token 统计信息（统一格式）。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatChoice:
    """单个候选回答（目前通常只用 index=0 的一条）。"""

    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


@dataclass
class ChatResult:
    """一次对话调用的最终结果。

    - provider: 逻辑 Provider 名（如 "kimi"）。
    - model: 逻辑模型名（如 "ide-chat"）。
    - choices: 一个或多个候选回答。
    - usage: 可选的 token 使用统计。
    - raw: 原始响应 JSON，用于调试或日志记录。
    """

    provider: str
    model: str
    choices: List[ChatChoice]
    usage: Optional[ChatUsage] = None
    raw: Optional[dict] = None


@dataclass
class ChatStreamChoice:
    """流式返回中的单个候选增量。"""

    index: int
    delta: ChatMessage
    finish_reason: Optional[str] = None


@dataclass
class ChatStreamChunk:
    """流式对话的增量结果，结构与 ChatResult 类似。

    每次流式回调由若干 choice 组成，choice.delta 代表本次增量内容。
    """

    provider: str
    model: str
    choices: List[ChatStreamChoice]
    usage: Optional[ChatUsage] = None
    raw: Optional[dict] = None
