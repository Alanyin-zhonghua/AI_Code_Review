from typing import Optional, Dict, Any
from agent_core.config.settings import settings
from agent_core.domain.conversation import ConversationStore
from agent_core.providers.kimi_client import KimiClient
from agent_core.agents.base_agent import AgentEngine, AgentConfig
from agent_core.infrastructure.storage.json_store import JsonConversationStore


_store: ConversationStore | None = None
_agent: AgentEngine | None = None


def get_default_agent() -> AgentEngine:
    global _store, _agent
    if _store is None:
        _store = JsonConversationStore(root=settings.storage_root)
    if _agent is None:
        provider = KimiClient(settings)
        cfg = AgentConfig(agent_type="ide-helper", provider="kimi", model="ide-chat")
        _agent = AgentEngine(store=_store, provider_client=provider, tool_executor=None, config=cfg)
    return _agent


def run_ide_chat(
    user_input: str,
    conversation_id: Optional[str] = None,
    focus_message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    agent = get_default_agent()
    conv, user_rec, assistant_rec = agent.run_step(
        conversation_id=conversation_id,
        user_input=user_input,
        meta=meta or {},
        focus_message_id=focus_message_id,
    )
    return {
        "conversation_id": conv.id,
        "user_message": {"id": user_rec.id, "content": user_rec.content},
        "assistant_message": {"id": assistant_rec.id, "content": assistant_rec.content},
        "usage": assistant_rec.meta.get("usage"),
    }