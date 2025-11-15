from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Protocol
from datetime import datetime
from .models import Role


@dataclass
class Conversation:
    id: str
    title: str
    agent_type: str
    created_at: datetime
    updated_at: datetime
    meta: Dict[str, Any]


@dataclass
class MessageRecord:
    id: str
    conversation_id: str
    role: Role
    content: str
    parent_id: Optional[str]
    depth: int
    version: int
    created_at: datetime
    meta: Dict[str, Any]


class ConversationStore(Protocol):
    def create_conversation(self, agent_type: str, meta: Dict[str, Any]) -> Conversation:
        ...

    def get_conversation(self, conversation_id: str) -> Conversation:
        ...

    def list_conversations(self) -> List[Conversation]:
        ...

    def add_message(self, message: MessageRecord) -> None:
        ...

    def get_message(self, message_id: str) -> MessageRecord:
        ...

    def list_messages(self, conversation_id: str) -> List[MessageRecord]:
        ...

    def delete_conversation(self, conversation_id: str) -> None:
        ...
