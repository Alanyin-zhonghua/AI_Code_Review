from agent_core.providers.glm_client import GlmClient
from agent_core.domain.models import ChatRequest, ChatMessage


class SettingsStub:
    glm_api_key = "g"
    http_timeout = 1.0
    glm_base_url = "https://open.bigmodel.cn/api/paas/v4"


def test_glm_client_basic(monkeypatch):
    gc = GlmClient(SettingsStub())
    req = ChatRequest(provider="glm", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    class Resp:
        status_code = 200

        def json(self):
            return {
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

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
    res = gc.chat(req)
    assert res.choices[0].message.content == "ok"


def test_glm_client_stream(monkeypatch):
    gc = GlmClient(SettingsStub())
    req = ChatRequest(provider="glm", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    stream_lines = [
        'data: {"choices": [{"index": 0, "delta": {"content": "a"}}]}',
        'data: {"choices": [{"index": 0, "delta": {"content": "b"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}',
        "data: [DONE]",
    ]

    class FakeResponse:
        status_code = 200

        def __init__(self, lines):
            self._lines = list(lines)

        def iter_lines(self):
            for line in self._lines:
                yield line

    class StreamContext:
        def __init__(self, response):
            self._response = response

        def __enter__(self):
            return self._response

        def __exit__(self, *args):
            return False

    class Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            raise AssertionError("post should not be called in stream test")

        def stream(self, *a, **kw):
            return StreamContext(FakeResponse(stream_lines))

    monkeypatch.setattr("httpx.Client", Client)
    chunks = list(gc.chat_stream(req))
    assert len(chunks) == 2
    assert chunks[0].choices[0].delta.content == "a"
    assert chunks[1].usage.total_tokens == 3
