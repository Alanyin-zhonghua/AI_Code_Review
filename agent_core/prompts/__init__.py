from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent


def load_system_prompt(agent_type: str, locale: str = "zh") -> str:
    fname = PROMPTS_DIR / locale / "ide_helper_system.md"
    return fname.read_text(encoding="utf-8")