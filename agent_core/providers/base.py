from typing import Protocol
from agent_core.domain.models import ChatRequest, ChatResult


class ProviderClient(Protocol):
    name: str

    def chat(self, req: ChatRequest) -> ChatResult:
        ...