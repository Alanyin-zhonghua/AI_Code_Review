import tempfile
from pathlib import Path
from agent_core.agents.base_agent import AgentEngine, AgentConfig
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.domain.models import (
    ChatResult,
    ChatChoice,
    ChatMessage,
    ChatStreamChunk,
    ChatStreamChoice,
)


class FakeProvider:
    name = "fake"
    def chat(self, req):
        msg = ChatMessage(role="assistant", content="done")
        return ChatResult(provider="fake", model="ide-chat", choices=[ChatChoice(index=0, message=msg)], usage=None, raw={})

    def chat_stream(self, req):
        delta = ChatStreamChunk(
            provider="fake",
            model="ide-chat",
            choices=[
                ChatStreamChoice(
                    index=0,
                    delta=ChatMessage(role="assistant", content="done"),
                    finish_reason="stop",
                )
            ],
            usage=None,
            raw={},
        )
        yield delta


def test_agent_run_step():
    with tempfile.TemporaryDirectory() as d:
        store = JsonConversationStore(root=Path(d) / ".storage")
        agent = AgentEngine(store=store, provider_client=FakeProvider(), tool_executor=None, config=AgentConfig(agent_type="ide-helper", provider="fake", model="ide-chat"))
        conv, user_rec, assistant_rec = agent.run_step(conversation_id=None, user_input="hello", meta={})
        assert conv.id
        assert user_rec.role == "user"
        assert assistant_rec.content == "done"


def test_agent_run_step_stream():
    with tempfile.TemporaryDirectory() as d:
        store = JsonConversationStore(root=Path(d) / ".storage")
        agent = AgentEngine(
            store=store,
            provider_client=FakeProvider(),
            tool_executor=None,
            config=AgentConfig(agent_type="ide-helper", provider="fake", model="ide-chat"),
        )
        events = list(agent.run_step_stream(conversation_id=None, user_input="hello", meta={}))
        assert [e.kind for e in events] == ["delta", "final"]
        final_event = events[-1]
        assert final_event.assistant_record is not None
        assert final_event.assistant_record.content == "done"
