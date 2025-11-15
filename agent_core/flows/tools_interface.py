"""Wrapper around existing tool implementations for LangGraph usage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from agent_core.config.settings import settings
from agent_core.tools.executor import ToolExecutor, default_tools
from agent_core.tools.definitions import ToolCall


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: Dict[str, object]


class ToolManager:
    """Expose project tools with safe execution helpers."""

    def __init__(self, workspace_root: Optional[str] = None) -> None:
        self.workspace_root = Path(workspace_root or settings.workspace_root).resolve()
        self.executor = ToolExecutor(default_tools(self.workspace_root))
        self.schemas: Dict[str, ToolSchema] = {
            "read_file": ToolSchema(
                name="read_file",
                description="读取指定文件的内容，可选 start/end 行号",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径"},
                        "start": {"type": "integer", "minimum": 1},
                        "end": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                },
            ),
            "list_files": ToolSchema(
                name="list_files",
                description="列出目录下满足模式的文件",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "起始目录"},
                        "pattern": {"type": "string", "description": "glob 模式"},
                    },
                    "required": ["directory"],
                },
            ),
            "search_code": ToolSchema(
                name="search_code",
                description="在指定目录递归搜索包含关键字的文件",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string"},
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 20, "minimum": 1},
                    },
                    "required": ["directory", "query"],
                },
            ),
            "write_file": ToolSchema(
                name="write_file",
                description="以安全模式写入文件内容，支持覆盖或追加",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
                    },
                    "required": ["path", "content"],
                },
            ),
        }

    def run(self, name: str, arguments: Dict[str, object]) -> Dict[str, object]:
        """Execute tool and return structured result."""

        try:
            if name == "write_file":
                return self._write_file(arguments)
            if name not in self.schemas:
                return {"ok": False, "error": f"Unknown tool {name}"}
            res = self.executor.execute(ToolCall(id="runtime", name=name, arguments=arguments))
            return {"ok": True, "content": res.content}
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": str(exc)}

    def _write_file(self, arguments: Dict[str, object]) -> Dict[str, object]:
        path = Path(str(arguments.get("path", "")).strip())
        if not path:
            return {"ok": False, "error": "path is required"}
        if not path.is_absolute():
            path = (self.workspace_root / path).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return {"ok": False, "error": "path outside workspace"}
        content = str(arguments.get("content", ""))
        mode = str(arguments.get("mode", "overwrite")).lower()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            if mode == "append" and path.exists():
                tmp_path.write_text(path.read_text(encoding="utf-8") + content, encoding="utf-8")
            else:
                tmp_path.write_text(content, encoding="utf-8")
            if path.exists():
                backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            tmp_path.replace(path)
            return {"ok": True, "content": f"wrote {path}"}
        except Exception as exc:  # pragma: no cover
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return {"ok": False, "error": str(exc)}

    def available_tools_text(self) -> str:
        parts = []
        for schema in self.schemas.values():
            parts.append(f"- {schema.name}: {schema.description}")
        return "\n".join(parts)
