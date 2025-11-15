"""Task-scoped configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4


TaskMode = Literal["read_only", "safe_write"]
MAX_TASK_STEPS = 20


@dataclass
class TaskConfig:
    """User-supplied settings for a single automated任务.

    Attributes:
        mode: 控制当前任务是否允许写文件。
        max_steps: 调用 LLM+工具可执行的最大轮数（<=20）。
        project_root: 当前项目根目录，所有文件操作都必须局限在这里。
        trace_id: 可选外部 trace 标识；为空时会自动生成。
    """

    mode: TaskMode
    max_steps: int
    project_root: str
    trace_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            self.max_steps = 1
        self.project_root = str(Path(self.project_root).expanduser().resolve())

    @property
    def max_steps_clamped(self) -> int:
        """Clamp步骤数量，防止超过硬上限。"""

        return min(self.max_steps, MAX_TASK_STEPS)

    def ensure_trace_id(self) -> str:
        """确保 trace_id 存在并返回。"""

        if not self.trace_id:
            self.trace_id = f"task-{uuid4().hex}"
        return self.trace_id

    @property
    def root_path(self) -> Path:
        return Path(self.project_root)
