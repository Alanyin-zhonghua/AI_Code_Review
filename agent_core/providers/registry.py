"""Provider 与模型配置。

本模块将“逻辑模型名”与“具体厂商模型名”解耦：

- 逻辑名（logical_name）：在代码里使用的统一名称，例如 "ide-chat"。
- provider_model：厂商实际提供的模型 ID，例如 "kimi-k2-turbo-preview"。

上层只关心逻辑名，具体用哪个底层模型由这里集中配置，便于后续升级或切换。"""

from dataclasses import dataclass
from typing import Dict, Mapping


@dataclass
class ModelConfig:
    """单个逻辑模型的配置。"""

    logical_name: str
    provider_model: str
    max_tokens: int
    default_temperature: float


@dataclass
class ProviderConfig:
    """某个 Provider 的整体配置。"""

    name: str
    base_url: str
    models: Dict[str, ModelConfig]


# Kimi 配置
KIMI_CONFIG = ProviderConfig(
    name="kimi",
    base_url="https://api.moonshot.cn/v1",
    models={
        "ide-chat": ModelConfig(
            logical_name="ide-chat",
            provider_model="kimi-k2-turbo-preview",
            max_tokens=8192,
            default_temperature=0.7,
        )
    },
)

# GLM / BigModel 配置（默认使用 glm-4.6 作为 ide-chat 逻辑模型）
GLM_CONFIG = ProviderConfig(
    name="glm",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    models={
        "ide-chat": ModelConfig(
            logical_name="ide-chat",
            provider_model="glm-4.6",
            max_tokens=8192,
            default_temperature=0.7,
        )
    },
)


PROVIDER_REGISTRY: Mapping[str, ProviderConfig] = {
    "kimi": KIMI_CONFIG,
    "glm": GLM_CONFIG,
}


def get_provider_config(name: str) -> ProviderConfig:
    """根据名称获取 ProviderConfig，名称不区分大小写。"""

    key = name.lower()
    for k, cfg in PROVIDER_REGISTRY.items():
        if k.lower() == key:
            return cfg
    raise KeyError(f"Unknown provider: {name!r}")
