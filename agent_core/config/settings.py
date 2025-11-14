"""配置管理模块。

支持从 .env 文件和环境变量加载配置。
"""

import os
import warnings
from pathlib import Path
from typing import Optional


def _load_env_file() -> None:
    """加载 .env 文件到环境变量。"""
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
                return  # 成功加载后退出
        except Exception as e:
            warnings.warn(f"Failed to load {p}: {e}")


try:
    from pydantic_settings import BaseSettings  # type: ignore
    from pydantic import Field, field_validator

    class Settings(BaseSettings):
        """配置设置（使用 Pydantic）。"""

        kimi_api_key: Optional[str] = Field(default=None, description="Kimi API 密钥")
        kimi_base_url: str = Field(
            default="https://api.moonshot.cn/v1",
            description="Kimi API 基础URL"
        )
        http_timeout: float = Field(default=30.0, ge=1.0, description="HTTP 超时时间（秒）")
        storage_root: str = Field(default=".storage", description="存储根目录")
        log_dir: str = Field(default="logs", description="日志目录")
        log_redact_content: bool = Field(default=False, description="是否脱敏日志内容")
        max_context_messages: int = Field(default=20, ge=1, le=100, description="最大上下文消息数")

        @field_validator("kimi_api_key")
        @classmethod
        def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
            if v and len(v) < 10:
                raise ValueError("API key seems too short")
            return v

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = False

    settings = Settings()

except ImportError:
    # Fallback: 不使用 Pydantic
    warnings.warn("Pydantic not available, using fallback settings")
    
    class Settings:  # type: ignore
        """配置设置（Fallback 实现）。"""
        
        def __init__(self):
            _load_env_file()
            self.kimi_api_key = os.getenv("KIMI_API_KEY")
            self.kimi_base_url = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
            
            try:
                self.http_timeout = float(os.getenv("HTTP_TIMEOUT", "30.0"))
                if self.http_timeout < 1.0:
                    self.http_timeout = 30.0
            except ValueError:
                self.http_timeout = 30.0
            
            self.storage_root = os.getenv("STORAGE_ROOT", ".storage")
            self.log_dir = os.getenv("LOG_DIR", "logs")
            self.log_redact_content = os.getenv("AGENT_LOG_REDACT_CONTENT", "false").lower() == "true"
            
            try:
                self.max_context_messages = int(os.getenv("MAX_CONTEXT_MESSAGES", "20"))
                if self.max_context_messages < 1:
                    self.max_context_messages = 20
            except ValueError:
                self.max_context_messages = 20
        
        def validate(self) -> None:
            """验证配置有效性。"""
            if self.kimi_api_key and len(self.kimi_api_key) < 10:
                warnings.warn("API key seems too short")

    settings = Settings()
    settings.validate()