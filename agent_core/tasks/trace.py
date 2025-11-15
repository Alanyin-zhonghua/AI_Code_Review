"""任务 trace 记录器。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import TaskConfig


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceRecorder:
    """把单次任务的关键信息写入 JSON 文件，便于审计。"""

    def __init__(self, config: TaskConfig):
        self.config = config
        config.ensure_trace_id()
        traces_dir = config.root_path / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        self.path = traces_dir / f"{config.trace_id}.json"
        self.data: Dict[str, Any] = {
            "trace_id": config.trace_id,
            "mode": config.mode,
            "project_root": config.project_root,
            "max_steps": config.max_steps_clamped,
            "started_at": _utcnow(),
            "finished_at": None,
            "final_status": None,
            "final_reply_preview": None,
            "steps": [],
        }
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_llm_step(self, step: int, *, has_tool_calls: bool, summary: str) -> None:
        self.data["steps"].append(
            {
                "type": "llm",
                "step": step,
                "timestamp": _utcnow(),
                "has_tool_calls": has_tool_calls,
                "response_summary": summary,
            }
        )
        self._flush()

    def record_tool_step(
        self,
        step: int,
        *,
        tool_name: str,
        args: Dict[str, Any],
        result_summary: Optional[str] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "type": "tool",
            "step": step,
            "timestamp": _utcnow(),
            "tool_name": tool_name,
            "args": _trim_args(args),
            "result_summary": result_summary,
        }
        if error:
            entry["error"] = error
        self.data["steps"].append(entry)
        self._flush()

    def finalize(self, status: str, final_reply: str) -> None:
        self.data["finished_at"] = _utcnow()
        self.data["final_status"] = status
        self.data["final_reply_preview"] = (final_reply or "")[:400]
        self._flush()


def _trim_args(args: Dict[str, Any]) -> Dict[str, Any]:
    trimmed: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 200:
            trimmed[key] = value[:200] + "..."
        else:
            trimmed[key] = value
    return trimmed
