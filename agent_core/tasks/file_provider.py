"""File tool provider abstraction + local implementation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from .config import TaskConfig


class FileToolProvider(Protocol):
    """统一的文件工具接口，便于未来替换为 MCP 实现。"""

    def read_file(self, path: str) -> str:
        ...

    def list_files(self, pattern: Optional[str] = None, max_items: int = 200) -> List[str]:
        ...

    def search(self, query: str, *, directory: Optional[str] = None, max_results: int = 50) -> List[str]:
        ...

    def write_file_safe(self, path: str, new_content: str, *, reason: str, config: TaskConfig) -> Dict[str, str]:
        ...


@dataclass
class LocalFileToolProvider:
    """当前版本使用的本地文件工具实现。"""

    project_root: Path

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()
        self._backups = self.project_root / "traces" / "backups"

    # ---- helpers -------------------------------------------------

    def _resolve(self, raw: str) -> Path:
        base = Path(raw).expanduser()
        candidate = (self.project_root / base).resolve() if not base.is_absolute() else base.resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise PermissionError(f"path outside project root: {raw}") from exc
        return candidate

    # ---- read ops ------------------------------------------------

    def read_file(self, path: str) -> str:
        resolved = self._resolve(path)
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"file not found: {path}")
        return resolved.read_text(encoding="utf-8")

    def list_files(self, pattern: Optional[str] = None, max_items: int = 200) -> List[str]:
        from fnmatch import fnmatch

        matched: List[str] = []
        pat = pattern or "*"
        for file in self.project_root.rglob("*"):
            if not file.is_file():
                continue
            rel = str(file.relative_to(self.project_root))
            if fnmatch(file.name, pat):
                matched.append(rel)
                if len(matched) >= max_items:
                    break
        return matched

    def search(self, query: str, *, directory: Optional[str] = None, max_results: int = 50) -> List[str]:
        base = self._resolve(directory) if directory else self.project_root
        results: List[str] = []
        for file in base.rglob("*"):
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if query in line:
                    rel = file.relative_to(self.project_root)
                    results.append(f"{rel}:{line_no}: {line.strip()}")
                    if len(results) >= max_results:
                        return results
        return results

    # ---- writes --------------------------------------------------

    def write_file_safe(self, path: str, new_content: str, *, reason: str, config: TaskConfig) -> Dict[str, str]:
        resolved = self._resolve(path)
        rel = str(resolved.relative_to(self.project_root))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        backup_path = None
        if resolved.exists():
            backup_path = self._backups / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, backup_path)
        resolved.write_text(new_content, encoding="utf-8")
        info = {
            "status": "ok",
            "path": rel,
            "bytes_written": str(len(new_content.encode("utf-8"))),
            "reason": reason,
        }
        if backup_path:
            info["backup_path"] = str(backup_path.relative_to(self.project_root))
        return info
