from dataclasses import dataclass
from typing import Optional, List, Tuple
from uuid import uuid4
from datetime import datetime, timezone

from agent_core.domain.conversation import ConversationStore, MessageRecord, Conversation
from agent_core.domain.models import ChatMessage, ChatRequest, ChatResult
from agent_core.tools.executor import ToolExecutor
from agent_core.providers.kimi_client import KimiClient
from agent_core.prompts import load_system_prompt


@dataclass
class AgentConfig:
    agent_type: str
    provider: str
    model: str
    enable_tools: bool = False


class AgentEngine:
    def __init__(
        self,
        store: ConversationStore,
        provider_client: KimiClient,
        tool_executor: Optional[ToolExecutor] = None,
        config: Optional[AgentConfig] = None,
    ):
        self._store = store
        self._provider_client = provider_client
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(agent_type="ide-helper", provider="kimi", model="ide-chat")

    def run_step(
        self,
        conversation_id: Optional[str],
        user_input: str,
        meta: dict,
        focus_message_id: Optional[str] = None,
    ) -> Tuple[Conversation, MessageRecord, MessageRecord]:
        if not conversation_id:
            conv = self._store.create_conversation(self._config.agent_type, meta)
        else:
            conv = self._store.get_conversation(conversation_id)
        leaf = None
        if focus_message_id:
            leaf = self._store.get_message(focus_message_id)
        else:
            msgs = self._store.list_messages(conv.id)
            leaf = msgs[-1] if msgs else None
        path: List[MessageRecord] = []
        current = leaf
        while current is not None:
            path.append(current)
            if current.parent_id is None:
                break
            current = self._store.get_message(current.parent_id)
        path.reverse()
        if len(path) > 20:
            path = path[-20:]
        system_prompt = load_system_prompt(self._config.agent_type)
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for mr in path:
            chat_messages.append(ChatMessage(role=mr.role, content=mr.content, meta=mr.meta))
        chat_messages.append(ChatMessage(role="user", content=user_input, meta=meta))
        req = ChatRequest(provider=self._config.provider, model=self._config.model, messages=chat_messages, temperature=0.3)
        result: ChatResult = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        now = datetime.now(timezone.utc)
        user_rec = MessageRecord(
            id=f"m-{uuid4().hex}",
            conversation_id=conv.id,
            role="user",
            content=user_input,
            parent_id=leaf.id if leaf else None,
            depth=(leaf.depth + 1 if leaf else 0),
            version=1,
            created_at=now,
            meta=meta,
        )
        usage_meta = None
        if result.usage:
            usage_meta = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }
        assistant_rec = MessageRecord(
            id=f"m-{uuid4().hex}",
            conversation_id=conv.id,
            role="assistant",
            content=assistant_msg.content,
            parent_id=user_rec.id,
            depth=user_rec.depth + 1,
            version=1,
            created_at=now,
            meta={"provider": self._config.provider, "usage": usage_meta or {}},
        )
        self._store.add_message(user_rec)
        self._store.add_message(assistant_rec)
        return conv, user_rec, assistant_rec