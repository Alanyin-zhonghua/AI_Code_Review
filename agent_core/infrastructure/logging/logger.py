import json
import logging
from pathlib import Path
from datetime import datetime
from agent_core.config.settings import settings


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("agent_core")
    logger.setLevel(logging.INFO)
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    fh.setLevel(logging.INFO)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            msg = record.getMessage()
            if settings.log_redact_content:
                msg = (msg or "")[:64]
            payload = {
                "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname,
                "name": record.name,
                "msg": msg,
            }
            extra = getattr(record, "extra", None)
            if isinstance(extra, dict):
                payload.update(extra)
            return json.dumps(payload, ensure_ascii=False)

    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)
    return logger


logger = setup_logger()