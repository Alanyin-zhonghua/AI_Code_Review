import tempfile
from pathlib import Path
from agent_core.agents.base_agent import AgentEngine, AgentConfig
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.domain.models import ChatResult, ChatChoice, ChatMessage


class FakeProvider:
    name = "fake"
    def chat(self, req):
        msg = ChatMessage(role="assistant", content="done")
        return ChatResult(provider="fake", model="ide-chat", choices=[ChatChoice(index=0, message=msg)], usage=None, raw={})


def test_agent_run_step():
    with tempfile.TemporaryDirectory() as d:
        store = JsonConversationStore(root=Path(d) / ".storage")
        agent = AgentEngine(store=store, provider_client=FakeProvider(), tool_executor=None, config=AgentConfig(agent_type="ide-helper", provider="fake", model="ide-chat"))
        conv, user_rec, assistant_rec = agent.run_step(conversation_id=None, user_input="hello", meta={})
        assert conv.id
        assert user_rec.role == "user"
        assert assistant_rec.content == "done"