"""LLM Provider 集成层。

该包下的模块负责：
- 定义 Provider 抽象接口 (base)。
- 维护 Provider 与模型配置 (registry)。
- 提供各厂商的具体实现 (如 kimi_client、glm_client)。
"""

from typing import Literal, Optional

from agent_core.config.settings import settings
from agent_core.providers.base import ProviderClient
from agent_core.providers.kimi_client import KimiClient
from agent_core.providers.glm_client import GlmClient


def create_provider(name: Optional[str] = None) -> ProviderClient:
    """根据名称创建 Provider 实例，默认取配置中的 provider。"""

    provider_name = (name or getattr(settings, "default_provider", "glm")).lower()
    if provider_name == "kimi":
        return KimiClient(settings)
    return GlmClient(settings)


DefaultProviderName = Literal["glm", "kimi"]
