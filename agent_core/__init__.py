"""Agent Core 顶层包。

该包提供 IDE 助手与代码审查 Agent 的核心实现，
包括配置加载、领域模型、Provider 适配、工具系统、
对话引擎、任务级自动化与持久化存储等能力。
"""

from agent_core.tasks import TaskConfig, run_agent

__all__ = ["TaskConfig", "run_agent"]
