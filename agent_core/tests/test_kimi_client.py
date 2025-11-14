import types
from agent_core.providers.kimi_client import KimiClient
from agent_core.domain.models import ChatRequest, ChatMessage


class SettingsStub:
    kimi_api_key = "k"
    http_timeout = 1.0
    kimi_base_url = "https://api.moonshot.cn/v1"


def test_kimi_client_parse_and_errors(monkeypatch):
    kc = KimiClient(SettingsStub())
    req = ChatRequest(provider="kimi", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    class Resp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    class Client:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, *a, **kw):
            return Resp()

    monkeypatch.setattr("httpx.Client", Client)
    res = kc.chat(req)
    assert res.choices[0].message.content == "ok"