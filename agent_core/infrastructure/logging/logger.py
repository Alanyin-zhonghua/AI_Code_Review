# -*- coding: utf-8 -*-
"""结构化日志模块。

提供 JSON 格式的结构化日志，支持脱敏功能。
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict
from agent_core.config.settings import settings


class JsonFormatter(logging.Formatter):
    """JSON 格式化器，支持敏感信息脱敏。"""
    
    # 敏感信息正则表达式
    SENSITIVE_PATTERNS = [
        (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s]+)', re.I), r'\1***REDACTED***'),
        (re.compile(r'(bearer\s+)([a-zA-Z0-9_-]+)', re.I), r'\1***REDACTED***'),
        (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\'\s]+)', re.I), r'\1***REDACTED***'),
        (re.compile(r'(token["\']?\s*[:=]\s*["\']?)([^"\'\s]+)', re.I), r'\1***REDACTED***'),
    ]
    
    def __init__(self, redact_content: bool = False, max_content_length: int = 1000):
        super().__init__()
        self.redact_content = redact_content
        self.max_content_length = max_content_length
    
    def _redact_sensitive(self, text: str) -> str:
        """脱敏敏感信息。"""
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
    
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        
        # 脱敏处理
        msg = self._redact_sensitive(msg)
        
        # 截断过长内容
        if self.redact_content and len(msg) > self.max_content_length:
            msg = msg[:self.max_content_length] + f"... (truncated, total {len(msg)} chars)"
        
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "msg": msg,
        }
        
        # 添加额外字段
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            # 脱敏 extra 中的敏感信息
            for k, v in extra.items():
                if isinstance(v, str):
                    extra[k] = self._redact_sensitive(v)
            payload.update(extra)
        
        return json.dumps(payload, ensure_ascii=False)


def setup_logger() -> logging.Logger:
    """设置结构化日志记录器。"""
    logger = logging.getLogger("agent_core")
    logger.setLevel(logging.INFO)
    
    # 确保日志目录存在
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 文件处理器
    fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(JsonFormatter(
        redact_content=settings.log_redact_content,
        max_content_length=1000
    ))
    
    logger.addHandler(fh)
    
    # 控制台处理器（可选）
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)  # 控制台只显示警告和错误
        ch.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(ch)
    
    return logger


logger = setup_logger()
