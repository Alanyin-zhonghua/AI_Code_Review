from dataclasses import dataclass
from typing import Dict


@dataclass
class ModelConfig:
    logical_name: str
    provider_model: str
    max_tokens: int
    default_temperature: float


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    models: Dict[str, ModelConfig]


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