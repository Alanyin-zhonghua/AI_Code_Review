from typing import Callable, Dict, Any, List
from pathlib import Path
import fnmatch
from .definitions import ToolCall, ToolResult
import json


ToolFunc = Callable[[Dict[str, Any]], str]


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


def _validate_path(p: str) -> bool:
    if not p:
        return False
    if ".." in p:
        return False
    return True


def _read_file_tool(args: Dict[str, Any]) -> str:
    p = str(args.get("path") or "").strip()
    if not _validate_path(p):
        return "invalid path"
    path = Path(p)
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return str(e)


def _list_files_tool(args: Dict[str, Any]) -> str:
    d = str(args.get("directory") or "").strip()
    pattern = str(args.get("pattern") or "").strip() or "*"
    if not _validate_path(d):
        return "invalid directory"
    base = Path(d)
    try:
        items: List[str] = []
        for p in base.glob("**/*"):
            if p.is_file():
                rel = str(p)
                if fnmatch.fnmatch(p.name, pattern):
                    items.append(rel)
        return "\n".join(items)
    except Exception as e:
        return str(e)


def _search_code_tool(args: Dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    d = str(args.get("directory") or ".").strip()
    max_results = int(args.get("max_results") or 50)
    if not query:
        return "empty query"
    if not _validate_path(d):
        return "invalid directory"
    base = Path(d)
    results: List[str] = []
    try:
        for p in base.glob("**/*"):
            if p.is_file():
                try:
                    for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                        if query in line:
                            results.append(f"{p}:{i}: {line.strip()}")
                            if len(results) >= max_results:
                                return "\n".join(results)
                except Exception:
                    continue
        return "\n".join(results)
    except Exception as e:
        return str(e)


def _propose_edit_tool(args: Dict[str, Any]) -> str:
    p = str(args.get("path") or "").strip()
    rng = args.get("range")
    new_content = str(args.get("new_content") or "")
    if not _validate_path(p):
        return "invalid path"
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        return "invalid range"
    start, end = int(rng[0]), int(rng[1])
    path = Path(p)
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        return str(e)
    lines = original.splitlines()
    if start < 1 or end < start or end > len(lines) + 1:
        return "range out of bounds"
    old_segment = "\n".join(lines[start - 1:end])
    header = [
        f"--- a/{p}",
        f"+++ b/{p}",
        f"@@ -{start},{max(0, end - start + 1)} +{start},{len(new_content.splitlines())}",
    ]
    body: List[str] = []
    for l in old_segment.splitlines():
        body.append(f"-{l}")
    for l in new_content.splitlines():
        body.append(f"+{l}")
    return "\n".join(header + body)


def default_tools() -> Dict[str, ToolFunc]:
    return {
        "read_file": _read_file_tool,
        "list_files": _list_files_tool,
        "search_code": _search_code_tool,
        "propose_edit": _propose_edit_tool,
    }