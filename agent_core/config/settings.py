"""配置管理模块。

支持从 .env、config.yaml 以及环境变量加载配置。
"""

import os
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


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


def _load_config_from_yaml() -> Dict[str, Any]:
    """从 config.yaml 加载配置（若存在）。"""
    candidates = []
    explicit = os.getenv("AGENT_CONFIG_FILE")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend([
        Path.cwd() / "config.yaml",
        Path(__file__).resolve().parents[2] / "config.yaml",
        Path(__file__).resolve().parents[1] / "config.yaml",
    ])

    seen: set[Path] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if path.exists():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    return data
                warnings.warn(f"Config file {path} is not a mapping, ignored")
        except Exception as exc:
            warnings.warn(f"Failed to read config file {path}: {exc}")
    return {}


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore
    from pydantic import Field, field_validator

    class PydanticSettings(BaseSettings):
        """配置设置（使用 Pydantic）。"""

        # ---- Provider 相关配置 ----
        default_provider: str = Field(
            default="glm",
            description="默认使用的 Provider 名称，例如 glm、kimi",
        )
        default_model: str = Field(
            default="ide-chat",
            description="逻辑模型名，由 registry 映射为具体厂商模型",
        )

        # Kimi
        kimi_api_key: Optional[str] = Field(default=None, description="Kimi API 密钥")
        kimi_base_url: str = Field(
            default="https://api.moonshot.cn/v1",
            description="Kimi API 基础URL"
        )
        # GLM / BigModel
        glm_api_key: Optional[str] = Field(default=None, description="GLM API 密钥")
        glm_base_url: str = Field(
            default="https://open.bigmodel.cn/api/paas/v4",
            description="GLM API 基础URL",
        )
        http_timeout: float = Field(default=30.0, ge=1.0, description="HTTP 超时时间（秒）")
        storage_root: str = Field(default=".storage", description="存储根目录")
        log_dir: str = Field(default="logs", description="日志目录")
        log_redact_content: bool = Field(default=False, description="是否脱敏日志内容")
        max_context_messages: int = Field(default=20, ge=1, le=100, description="最大上下文消息数")
        max_tool_rounds: int = Field(
            default=20,
            ge=1,
            le=20,
            description="单轮对话内工具调用最大轮数（硬上限 20）",
        )
        workspace_root: str = Field(
            default_factory=lambda: str(Path.cwd()),
            description="工具可访问的项目根目录",
        )
        allow_tool_absolute_path: bool = Field(
            default=False,
            description="是否允许工具访问任意绝对路径（默认禁止）",
        )

        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        @staticmethod
        def _config_source() -> Dict[str, Any]:
            return _load_config_from_yaml()

        @field_validator("kimi_api_key", "glm_api_key")
        @classmethod
        def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
            if v and len(v) < 10:
                raise ValueError("API key seems too short")
            return v

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ):
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                cls._config_source,
                file_secret_settings,
            )

    settings = PydanticSettings()

except ImportError:
    # Fallback: 不使用 Pydantic
    warnings.warn("Pydantic not available, using fallback settings")

    class FallbackSettings:
        """配置设置（Fallback 实现）。"""

        def __init__(self):
            _load_env_file()
            cfg = _load_config_from_yaml()

            # 通用 Provider 选择
            self.default_provider = os.getenv("DEFAULT_PROVIDER", cfg.get("default_provider", "glm"))
            self.default_model = os.getenv("DEFAULT_MODEL", cfg.get("default_model", "ide-chat"))

            # Kimi
            self.kimi_api_key = os.getenv("KIMI_API_KEY", cfg.get("kimi_api_key"))
            self.kimi_base_url = os.getenv("KIMI_BASE_URL", cfg.get("kimi_base_url", "https://api.moonshot.cn/v1"))

            # GLM / BigModel
            self.glm_api_key = os.getenv("GLM_API_KEY", cfg.get("glm_api_key"))
            self.glm_base_url = os.getenv(
                "GLM_BASE_URL",
                cfg.get("glm_base_url", "https://open.bigmodel.cn/api/paas/v4"),
            )

            self.http_timeout = self._as_float(
                os.getenv("HTTP_TIMEOUT", str(cfg.get("http_timeout", "30.0")))
            )
            self.storage_root = os.getenv("STORAGE_ROOT", cfg.get("storage_root", ".storage"))
            self.log_dir = os.getenv("LOG_DIR", cfg.get("log_dir", "logs"))
            self.log_redact_content = self._as_bool(
                os.getenv(
                    "AGENT_LOG_REDACT_CONTENT",
                    str(cfg.get("log_redact_content", "false")),
                )
            )
            self.max_context_messages = self._as_int(
                os.getenv("MAX_CONTEXT_MESSAGES", str(cfg.get("max_context_messages", 20)))
            )
            self.max_tool_rounds = self._as_int(
                os.getenv("MAX_TOOL_ROUNDS", str(cfg.get("max_tool_rounds", 20)))
            )
            self.workspace_root = os.getenv(
                "WORKSPACE_ROOT",
                cfg.get("workspace_root", str(Path.cwd())),
            )
            self.allow_tool_absolute_path = self._as_bool(
                os.getenv(
                    "ALLOW_TOOL_ABSOLUTE_PATH",
                    str(cfg.get("allow_tool_absolute_path", False)),
                )
            )

        @staticmethod
        def _as_float(value: str) -> float:
            try:
                v = float(value)
                if v < 1.0:
                    return 30.0
                return v
            except ValueError:
                return 30.0

        @staticmethod
        def _as_int(value: str) -> int:
            try:
                v = int(value)
                if v < 1:
                    return 20
                return v
            except ValueError:
                return 20

        @staticmethod
        def _as_bool(value: str | bool) -> bool:
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes"}

        def validate(self) -> None:
            """验证配置有效性。"""
            if self.kimi_api_key and len(self.kimi_api_key) < 10:
                warnings.warn("API key seems too short")
            if self.glm_api_key and len(self.glm_api_key) < 10:
                warnings.warn("GLM API key seems too short")

    settings = FallbackSettings()
    settings.validate()

# 类型别名，让外部代码可以使用 Settings 类型
Settings = type(settings)
