"""系统提示词加载工具。

当前仅支持 IDE 助手场景，按语言(locale) 从 prompts/zh 目录
读取对应的 system prompt 文本，用于构造 ChatMessage(role="system").
"""

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent


def load_system_prompt(agent_type: str, locale: str = "zh") -> str:
    """根据 Agent 类型和语言加载系统提示词文本。

    目前 agent_type 仅支持 "ide-helper"，如需支持更多类型可以
    在该函数中按需分发到不同的文件路径。
    """

    fname = PROMPTS_DIR / locale / "ide_helper_system.md"
    return fname.read_text(encoding="utf-8")
