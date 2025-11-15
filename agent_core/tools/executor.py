from typing import Callable, Dict, Any, List, Optional, Union
from pathlib import Path
import fnmatch
import json

from agent_core.config.settings import settings
from .definitions import ToolCall, ToolResult, ToolDef, ToolParam


ToolFunc = Callable[[Dict[str, Any]], str]
MAX_LIST_RESULTS = 500
MAX_SEARCH_RESULTS = 200


class ToolExecutor:
    def __init__(self, tools: Dict[str, ToolFunc]):
        self._tools = tools
        self._cache: Dict[tuple, str] = {}

    def execute(self, call: ToolCall) -> ToolResult:
        key = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
        if key in self._cache:
            result = self._cache[key]
        else:
            func = self._tools.get(call.name)
            if not func:
                result = "Tool not registered"
            else:
                result = func(call.arguments)
            self._cache[key] = result
        return ToolResult(call_id=call.id, content=result)


def _coerce_root(root: Optional[Union[str, Path]]) -> Optional[Path]:
    if root is None:
        raw_root = getattr(settings, "workspace_root", None)
        if raw_root:
            root = raw_root
    if root is None:
        return None
    return Path(root).expanduser().resolve()


def _resolve_path(raw: str, root: Optional[Path], allow_absolute: bool) -> Optional[Path]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        candidate = Path(text).expanduser()
    except Exception:
        return None
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if root and _is_within_root(resolved, root):
            return resolved
        return resolved if allow_absolute and not root else None
    base = root or Path.cwd()
    try:
        resolved = (base / candidate).resolve()
    except Exception:
        return None
    if root and not _is_within_root(resolved, root):
        return None
    return resolved


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _format_relative(path: Path, root: Optional[Path]) -> str:
    if root:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            pass
    return str(path)


def _make_read_file_tool(root: Optional[Path], allow_absolute: bool) -> ToolFunc:
    def _run(args: Dict[str, Any]) -> str:
        path = _resolve_path(str(args.get("path") or ""), root, allow_absolute)
        if not path or not path.exists() or not path.is_file():
            return "invalid path"
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return str(exc)

    return _run


def _make_list_files_tool(root: Optional[Path], allow_absolute: bool) -> ToolFunc:
    def _run(args: Dict[str, Any]) -> str:
        directory = str(args.get("directory") or ".")
        pattern = str(args.get("pattern") or "*").strip() or "*"
        base = _resolve_path(directory, root, allow_absolute) or root
        if base is None or not base.exists():
            return "invalid directory"
        items: List[str] = []
        try:
            for path in base.rglob("*"):
                if path.is_file() and fnmatch.fnmatch(path.name, pattern):
                    items.append(_format_relative(path, root))
                    if len(items) >= MAX_LIST_RESULTS:
                        items.append("... truncated ...")
                        break
        except Exception as exc:
            return str(exc)
        return "\n".join(items)

    return _run


def _make_search_code_tool(root: Optional[Path], allow_absolute: bool) -> ToolFunc:
    def _run(args: Dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        directory = str(args.get("directory") or ".")
        raw_limit = args.get("max_results")
        try:
            limit = int(raw_limit) if raw_limit is not None else 50
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        if not query:
            return "empty query"
        base = _resolve_path(directory, root, allow_absolute) or root
        if base is None or not base.exists():
            return "invalid directory"
        results: List[str] = []
        try:
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for line_no, line in enumerate(content.splitlines(), start=1):
                    if query in line:
                        display = _format_relative(path, root)
                        results.append(f"{display}:{line_no}: {line.strip()}")
                        if len(results) >= limit:
                            return "\n".join(results)
        except Exception as exc:
            return str(exc)
        return "\n".join(results)

    return _run


def _make_propose_edit_tool(root: Optional[Path], allow_absolute: bool) -> ToolFunc:
    def _run(args: Dict[str, Any]) -> str:
        path = _resolve_path(str(args.get("path") or ""), root, allow_absolute)
        rng = args.get("range")
        new_content = str(args.get("new_content") or "")
        if not path:
            return "invalid path"
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            return "invalid range"
        start, end = int(rng[0]), int(rng[1])
        try:
            original = path.read_text(encoding="utf-8")
        except Exception as exc:
            return str(exc)
        lines = original.splitlines()
        if start < 1 or end < start or end > len(lines) + 1:
            return "range out of bounds"
        old_segment = "\n".join(lines[start - 1:end])
        display_path = _format_relative(path, root)
        header = [
            f"--- a/{display_path}",
            f"+++ b/{display_path}",
            f"@@ -{start},{max(0, end - start + 1)} +{start},{len(new_content.splitlines())}",
        ]
        body: List[str] = [f"-{line}" for line in old_segment.splitlines()]
        body.extend(f"+{line}" for line in new_content.splitlines())
        return "\n".join(header + body)

    return _run


def default_tools(
    workspace_root: Optional[Union[str, Path]] = None,
    allow_absolute: Optional[bool] = None,
) -> Dict[str, ToolFunc]:
    root = _coerce_root(workspace_root)
    allow_abs = settings.allow_tool_absolute_path if allow_absolute is None else allow_absolute
    return {
        "read_file": _make_read_file_tool(root, allow_abs),
        "list_files": _make_list_files_tool(root, allow_abs),
        "search_code": _make_search_code_tool(root, allow_abs),
        "propose_edit": _make_propose_edit_tool(root, allow_abs),
    }


def default_tool_defs() -> List[ToolDef]:
    return [
        ToolDef(
            name="read_file",
            description="读取项目中的只读文件内容",
            params={
                "path": ToolParam(
                    name="path",
                    description="相对项目根目录的文件路径",
                    required=True,
                    schema={"type": "string"},
                )
            },
        ),
        ToolDef(
            name="list_files",
            description="列出目录下的文件列表",
            params={
                "directory": ToolParam(
                    name="directory",
                    description="起始目录，默认为项目根目录",
                    required=False,
                    schema={"type": "string"},
                ),
                "pattern": ToolParam(
                    name="pattern",
                    description="可选的文件名通配符，如 *.py",
                    required=False,
                    schema={"type": "string"},
                ),
            },
        ),
        ToolDef(
            name="search_code",
            description="在代码中搜索指定文本片段",
            params={
                "directory": ToolParam(
                    name="directory",
                    description="搜索目录，默认为项目根目录",
                    required=False,
                    schema={"type": "string"},
                ),
                "query": ToolParam(
                    name="query",
                    description="需要匹配的文本",
                    required=True,
                    schema={"type": "string"},
                ),
                "max_results": ToolParam(
                    name="max_results",
                    description="最大返回条数，默认 50",
                    required=False,
                    schema={"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
                ),
            },
        ),
        ToolDef(
            name="propose_edit",
            description="根据选区生成补丁建议（只读）",
            params={
                "path": ToolParam(
                    name="path",
                    description="需要修改的文件路径",
                    required=True,
                    schema={"type": "string"},
                ),
                "range": ToolParam(
                    name="range",
                    description="修改的行范围，如 [10, 20]",
                    required=True,
                    schema={
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                ),
                "new_content": ToolParam(
                    name="new_content",
                    description="建议替换的文本内容",
                    required=True,
                    schema={"type": "string"},
                ),
            },
        ),
    ]
