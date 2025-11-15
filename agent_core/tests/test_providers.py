from agent_core.providers import create_provider
from agent_core.providers.glm_client import GlmClient
from agent_core.providers.kimi_client import KimiClient


def test_create_provider_default(monkeypatch):
    class DummySettings:
        default_provider = "glm"
        glm_api_key = "g"
        http_timeout = 1.0
        glm_base_url = "https://open.bigmodel.cn/api/paas/v4"
        kimi_api_key = None

    monkeypatch.setattr("agent_core.providers.settings", DummySettings())
    provider = create_provider()
    assert isinstance(provider, GlmClient)


def test_create_provider_explicit(monkeypatch):
    class DummySettings:
        default_provider = "glm"
        kimi_api_key = "k"
        http_timeout = 1.0
        kimi_base_url = "https://api.moonshot.cn/v1"
        glm_api_key = None

    monkeypatch.setattr("agent_core.providers.settings", DummySettings())
    provider = create_provider("kimi")
    assert isinstance(provider, KimiClient)
