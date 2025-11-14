import os
from pathlib import Path

try:
    from pydantic import BaseSettings  # type: ignore

    class Settings(BaseSettings):

        kimi_api_key: str | None = None
        kimi_base_url: str = "https://api.moonshot.cn/v1"
        http_timeout: float = 30.0
        storage_root: str = ".storage"
        log_dir: str = "logs"
        log_redact_content: bool = False

        class Config:
            env_file = ".env"

    settings = Settings()
except Exception:
    def _load_env_file():
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[2] / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ]
        for p in candidates:
            try:
                if p.exists():
                    for line in p.read_text(encoding="utf-8").splitlines():
                        s = line.strip()
                        if not s or s.startswith("#") or "=" not in s:
                            continue
                        k, v = s.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and (k not in os.environ):
                            os.environ[k] = v
                    break
            except Exception:
                pass

    class Settings:
        def __init__(self):
            _load_env_file()
            self.kimi_api_key = os.getenv("KIMI_API_KEY")
            self.kimi_base_url = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
            self.http_timeout = float(os.getenv("HTTP_TIMEOUT", "30.0"))
            self.storage_root = os.getenv("STORAGE_ROOT", ".storage")
            self.log_dir = os.getenv("LOG_DIR", "logs")
            self.log_redact_content = os.getenv("AGENT_LOG_REDACT_CONTENT", "false").lower() == "true"

    settings = Settings()