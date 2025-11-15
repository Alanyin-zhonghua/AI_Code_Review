"""Tool definitions and handlers for TaskAgent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from agent_core.tools.definitions import ToolDef, ToolParam

from .config import TaskConfig
from .file_provider import FileToolProvider


ToolHandler = Callable[[Dict[str, Any], TaskConfig, FileToolProvider], Any]


@dataclass
class ToolSpec:
    name: str
    definition: ToolDef
    handler: ToolHandler
    is_write: bool = False


def _make_tool_defs() -> Dict[str, ToolSpec]:
    specs: Dict[str, ToolSpec] = {}

    def add(spec: ToolSpec) -> None:
        specs[spec.name] = spec

    add(
        ToolSpec(
            name="read_file",
            is_write=False,
            definition=ToolDef(
                name="read_file",
                description="读取项目内指定文件的完整内容",
                params={
                    "path": ToolParam(
                        name="path",
                        description="相对项目根目录的文件路径",
                        required=True,
                        schema={"type": "string"},
                    )
                },
            ),
            handler=lambda args, _cfg, provider: provider.read_file(str(args.get("path") or "")),
        )
    )

    def _list_handler(args: Dict[str, Any], _cfg: TaskConfig, provider: FileToolProvider) -> str:
        pattern = args.get("pattern")
        pattern = str(pattern) if pattern else None
        return json.dumps({"files": provider.list_files(pattern)}, ensure_ascii=False)

    add(
        ToolSpec(
            name="list_project_files",
            is_write=False,
            definition=ToolDef(
                name="list_project_files",
                description="列出项目内的文件，可选通配符",
                params={
                    "pattern": ToolParam(
                        name="pattern",
                        description="文件名通配符，如 *.py",
                        required=False,
                        schema={"type": "string"},
                    )
                },
            ),
            handler=_list_handler,
        )
    )

    def _search_handler(args: Dict[str, Any], _cfg: TaskConfig, provider: FileToolProvider) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        matches = provider.search(
            query,
            directory=str(args.get("directory") or "") or None,
            max_results=int(args.get("max_results") or 50),
        )
        return json.dumps({"results": matches}, ensure_ascii=False)

    add(
        ToolSpec(
            name="search_in_files",
            is_write=False,
            definition=ToolDef(
                name="search_in_files",
                description="在项目文件中搜索文本",
                params={
                    "query": ToolParam(
                        name="query",
                        description="需要匹配的文本",
                        required=True,
                        schema={"type": "string"},
                    ),
                    "directory": ToolParam(
                        name="directory",
                        description="可选的起始目录",
                        required=False,
                        schema={"type": "string"},
                    ),
                    "max_results": ToolParam(
                        name="max_results",
                        description="最大返回条数，默认50",
                        required=False,
                        schema={"type": "integer", "minimum": 1, "maximum": 200},
                    ),
                },
            ),
            handler=_search_handler,
        )
    )

    def _write_handler(args: Dict[str, Any], config: TaskConfig, provider: FileToolProvider) -> str:
        path = str(args.get("path") or "")
        content = str(args.get("new_content") or "")
        reason = str(args.get("reason") or "llm_request")
        info = provider.write_file_safe(path, content, reason=reason, config=config)
        return json.dumps(info, ensure_ascii=False)

    add(
        ToolSpec(
            name="write_file_safe",
            is_write=True,
            definition=ToolDef(
                name="write_file_safe",
                description="以安全方式写入文件，自动备份旧内容",
                params={
                    "path": ToolParam(
                        name="path",
                        description="需要写入的相对路径",
                        required=True,
                        schema={"type": "string"},
                    ),
                    "new_content": ToolParam(
                        name="new_content",
                        description="要写入的完整内容",
                        required=True,
                        schema={"type": "string"},
                    ),
                    "reason": ToolParam(
                        name="reason",
                        description="写入原因，将记录在 trace 中",
                        required=False,
                        schema={"type": "string"},
                    ),
                },
            ),
            handler=_write_handler,
        )
    )

    return specs


_TOOL_SPECS = _make_tool_defs()


def task_tool_defs() -> List[ToolDef]:
    return [spec.definition for spec in _TOOL_SPECS.values()]


def get_tool_spec(name: str) -> Optional[ToolSpec]:
    return _TOOL_SPECS.get(name)
