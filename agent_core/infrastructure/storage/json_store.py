import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List
from uuid import uuid4

from agent_core.config.settings import settings
from agent_core.domain.conversation import ConversationStore, Conversation, MessageRecord
from agent_core.domain.exceptions import BusinessError


class JsonConversationStore(ConversationStore):
    def __init__(self, root: str | Path | None = None):
        self._root = Path(root or settings.storage_root).resolve()
        self._conv_root = self._root / "conversations"
        self._conv_root.mkdir(parents=True, exist_ok=True)

    def create_conversation(self, agent_type: str, meta: Dict[str, Any]) -> Conversation:
        cid = f"c-{uuid4().hex}"
        cdir = self._conv_root / cid
        cdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        meta_copy = dict(meta)
        title = meta_copy.pop("title", meta_copy.get("projectRoot", ""))
        conv = Conversation(id=cid, title=title, agent_type=agent_type, created_at=now, updated_at=now, meta=meta_copy)
        self._write_meta(cdir, conv)
        return conv

    def get_conversation(self, conversation_id: str) -> Conversation:
        cdir = self._conv_root / conversation_id
        meta_path = cdir / "meta.json"
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise BusinessError(code="STORE_READ_ERROR", message=str(e))
        return Conversation(
            id=data["id"],
            title=data.get("title") or "",
            agent_type=data["agent_type"],
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
            meta=data.get("meta") or {},
        )

    def list_conversations(self) -> List[Conversation]:
        items: List[Conversation] = []
        for cdir in sorted(self._conv_root.glob("*/")):
            meta_path = cdir / "meta.json"
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    items.append(
                        Conversation(
                            id=data["id"],
                            title=data.get("title") or "",
                            agent_type=data["agent_type"],
                            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
                            meta=data.get("meta") or {},
                        )
                    )
                except Exception:
                    continue
        return items

    def add_message(self, message: MessageRecord) -> None:
        cdir = self._conv_root / message.conversation_id
        msgs_path = cdir / "messages.jsonl"
        try:
            payload = asdict(message)
            payload["created_at"] = message.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            line = json.dumps(payload, ensure_ascii=False)
            with msgs_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            conv = self.get_conversation(message.conversation_id)
            conv.updated_at = datetime.now(timezone.utc)
            meta_provider = message.meta.get("provider")
            meta_model = message.meta.get("model")
            if meta_provider:
                conv.meta["provider"] = meta_provider
            if meta_model:
                conv.meta["model"] = meta_model
            self._write_meta(cdir, conv)
        except BusinessError:
            raise
        except Exception as e:
            raise BusinessError(code="STORE_WRITE_ERROR", message=str(e))

    def get_message(self, message_id: str) -> MessageRecord:
        for cdir in self._conv_root.glob("*/"):
            msgs_path = cdir / "messages.jsonl"
            if not msgs_path.exists():
                continue
            for line in msgs_path.read_text(encoding="utf-8").splitlines():
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if data.get("id") == message_id:
                    return self._to_message(data)
        raise BusinessError(code="MESSAGE_NOT_FOUND", message=message_id)

    def list_messages(self, conversation_id: str) -> List[MessageRecord]:
        cdir = self._conv_root / conversation_id
        msgs_path = cdir / "messages.jsonl"
        items: List[MessageRecord] = []
        if not msgs_path.exists():
            return items
        for line in msgs_path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                items.append(self._to_message(data))
            except Exception:
                continue
        items.sort(key=lambda m: m.created_at)
        return items

    def delete_conversation(self, conversation_id: str) -> None:
        cdir = self._conv_root / conversation_id
        if not cdir.exists():
            raise BusinessError(code="CONVERSATION_NOT_FOUND", message=conversation_id)
        try:
            shutil.rmtree(cdir)
        except Exception as e:
            raise BusinessError(code="STORE_DELETE_ERROR", message=str(e))

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """更新会话标题。"""
        conv = self.get_conversation(conversation_id)
        conv.title = title
        conv.updated_at = datetime.now(timezone.utc)
        cdir = self._conv_root / conversation_id
        self._write_meta(cdir, conv)

    def _write_meta(self, cdir: Path, conv: Conversation) -> None:
        meta_path = cdir / "meta.json"
        tmp_path = cdir / f"meta.{uuid4().hex}.json.tmp"
        obj = {
            "id": conv.id,
            "title": conv.title,
            "agent_type": conv.agent_type,
            "created_at": conv.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "updated_at": conv.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "meta": conv.meta,
        }
        try:
            tmp_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, meta_path)
        except Exception as e:
            raise BusinessError(code="STORE_WRITE_ERROR", message=str(e))

    def _to_message(self, data: Dict[str, Any]) -> MessageRecord:
        return MessageRecord(
            id=data["id"],
            conversation_id=data["conversation_id"],
            role=data["role"],
            content=data.get("content") or "",
            parent_id=data.get("parent_id"),
            depth=int(data.get("depth", 0)),
            version=int(data.get("version", 1)),
            created_at=datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00")),
            meta=data.get("meta") or {},
        )
