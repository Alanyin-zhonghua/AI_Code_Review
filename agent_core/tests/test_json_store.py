import tempfile
from pathlib import Path
from datetime import datetime, timezone

from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.domain.conversation import MessageRecord


def test_json_store_create_and_messages():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / ".storage"
        store = JsonConversationStore(root=root)
        conv = store.create_conversation("ide-helper", {"projectRoot": "C:/proj"})
        now = datetime.now(timezone.utc)
        m1 = MessageRecord(
            id="m1",
            conversation_id=conv.id,
            role="system",
            content="sys",
            parent_id=None,
            depth=0,
            version=1,
            created_at=now,
            meta={},
        )
        store.add_message(m1)
        msgs = store.list_messages(conv.id)
        assert len(msgs) == 1
        assert msgs[0].id == "m1"