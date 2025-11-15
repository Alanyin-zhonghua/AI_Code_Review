"""Multi-scanner integration subsystem."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Protocol


@dataclass
class Issue:
    """统一的扫描结果数据结构。"""

    file: str
    line: int
    column: int
    severity: str
    rule_id: str
    source: str
    message: str
    language: str
    code_snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


class Scanner(Protocol):
    """扫描器接口定义。"""

    name: str

    def is_applicable(self, project_root: str) -> bool:
        ...

    def run(self, project_root: str) -> List[Issue]:
        ...


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _has_files(project_root: str, extensions: Iterable[str]) -> bool:
    root = Path(project_root)
    for ext in extensions:
        if any(root.rglob(f"*{ext}")):
            return True
    return False


class SemgrepScanner:
    name = "semgrep"

    def is_applicable(self, project_root: str) -> bool:
        return _command_exists("semgrep")

    def run(self, project_root: str) -> List[Issue]:
        cmd = ["semgrep", "--config", "p/owasp-top-ten", ".", "--json"]
        try:
            completed = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("semgrep 命令未安装") from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(f"semgrep 执行失败: {exc.stderr or exc.stdout}") from exc
        data = json.loads(completed.stdout or "{}")
        issues: List[Issue] = []
        for entry in data.get("results", []):
            extra = entry.get("extra", {})
            start = entry.get("start", {})
            issues.append(
                Issue(
                    file=entry.get("path", ""),
                    line=int(start.get("line") or 0),
                    column=int(start.get("col") or 0),
                    severity=str(extra.get("severity") or "").lower() or "info",
                    rule_id=str(entry.get("check_id") or ""),
                    source=self.name,
                    message=str(extra.get("message") or ""),
                    language=str(extra.get("engine_name") or extra.get("meta", {}).get("language") or ""),
                    code_snippet=str(extra.get("lines") or ""),
                )
            )
        return issues


class BanditScanner:
    name = "bandit"

    def is_applicable(self, project_root: str) -> bool:
        return _command_exists("bandit") and _has_files(project_root, [".py"])

    def run(self, project_root: str) -> List[Issue]:
        cmd = ["bandit", "-r", ".", "-f", "json"]
        try:
            completed = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("bandit 命令未安装") from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            raise RuntimeError(f"bandit 执行失败: {exc.stderr or exc.stdout}") from exc
        data = json.loads(completed.stdout or "{}")
        issues: List[Issue] = []
        for entry in data.get("results", []):
            issues.append(
                Issue(
                    file=str(entry.get("filename") or ""),
                    line=int(entry.get("line_number") or 0),
                    column=int(entry.get("col_offset") or 0),
                    severity=str(entry.get("issue_severity") or "LOW").lower(),
                    rule_id=str(entry.get("test_id") or ""),
                    source=self.name,
                    message=str(entry.get("issue_text") or ""),
                    language="python",
                    code_snippet=str(entry.get("code") or ""),
                )
            )
        return issues


class ESLintScanner:
    name = "eslint"

    def is_applicable(self, project_root: str) -> bool:
        return _command_exists("npx") and _has_files(project_root, [".js", ".jsx", ".ts", ".tsx"])

    def run(self, project_root: str) -> List[Issue]:
        cmd = ["npx", "eslint", ".", "-f", "json"]
        try:
            completed = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("需要安装 Node/npm (npx 命令未找到)") from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            raise RuntimeError(f"eslint 执行失败: {exc.stderr or exc.stdout}") from exc
        data = json.loads(completed.stdout or "[]")
        issues: List[Issue] = []
        severity_map = {1: "warning", 2: "error"}
        for file_entry in data:
            filename = file_entry.get("filePath") or file_entry.get("filePathRelative") or ""
            for msg in file_entry.get("messages", []):
                sev = severity_map.get(msg.get("severity"), "info")
                issues.append(
                    Issue(
                        file=filename,
                        line=int(msg.get("line") or 0),
                        column=int(msg.get("column") or 0),
                        severity=sev,
                        rule_id=str(msg.get("ruleId") or ""),
                        source=self.name,
                        message=str(msg.get("message") or ""),
                        language="javascript",
                        code_snippet=str(msg.get("source") or ""),
                    )
                )
        return issues


SCANNERS: List[Scanner] = [
    SemgrepScanner(),
    BanditScanner(),
    ESLintScanner(),
]


def run_all_scanners(project_root: str) -> List[Issue]:
    """依次运行所有适用的扫描器并合并结果。"""

    project_root = str(Path(project_root).expanduser().resolve())
    aggregated: List[Issue] = []
    for scanner in SCANNERS:
        if not scanner.is_applicable(project_root):
            continue
        try:
            aggregated.extend(scanner.run(project_root))
        except Exception as exc:
            aggregated.append(
                Issue(
                    file="",
                    line=0,
                    column=0,
                    severity="error",
                    rule_id="scanner_error",
                    source=scanner.name,
                    message=str(exc),
                    language="",
                    code_snippet="",
                )
            )
    return aggregated


__all__ = [
    "Issue",
    "Scanner",
    "SemgrepScanner",
    "BanditScanner",
    "ESLintScanner",
    "run_all_scanners",
]
