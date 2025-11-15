"""Provider 抽象接口。

上层 AgentEngine 不直接依赖具体厂商的 HTTP SDK，而是依赖此协议：

- 每个厂商实现一个 ProviderClient（如 KimiClient）。
- 负责：将 ChatRequest 转成具体 API 请求，并把响应 JSON 解析为 ChatResult。

这样可以在不改 Agent 代码的前提下接入更多厂商（OpenAI、DeepSeek 等）。
"""

from typing import Protocol, Iterable
from agent_core.domain.models import ChatRequest, ChatResult, ChatStreamChunk


class ProviderClient(Protocol):
    """LLM Provider 客户端协议。

    实现者需要提供：
    - name: Provider 名称，用于日志/统计。
    - chat(req): 执行一次非流式对话调用，返回统一的 ChatResult。
    """

    name: str

    def chat(self, req: ChatRequest) -> ChatResult:
        ...

    def chat_stream(self, req: ChatRequest) -> Iterable[ChatStreamChunk]:
        """执行一次流式对话调用，逐步产出增量。"""

        ...
