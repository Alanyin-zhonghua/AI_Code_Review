from agent_core.domain.models import ChatMessage
from agent_core.domain.conversation import Conversation, MessageRecord
from datetime import datetime, timezone


def test_models_exist():
    cm = ChatMessage(role="user", content="hi")
    assert cm.role == "user"
    now = datetime.now(timezone.utc)
    conv = Conversation(id="c1", title="t", agent_type="ide-helper", created_at=now, updated_at=now, meta={})
    assert conv.id == "c1"
    mr = MessageRecord(id="m1", conversation_id="c1", role="user", content="x", parent_id=None, depth=0, version=1, created_at=now, meta={})
    assert mr.depth == 0