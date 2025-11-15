"""Simple .env file manager for GUI configuration editing."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import MutableMapping


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def read_env_file() -> MutableMapping[str, str]:
    """Return key/value pairs from the .env file (order preserved)."""

    pairs: MutableMapping[str, str] = OrderedDict()
    if not ENV_FILE.exists():
        return pairs
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def write_env_file(data: MutableMapping[str, str]) -> None:
    """Persist the given key/value pairs back to the .env file."""

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in data.items():
        if not key:
            continue
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
