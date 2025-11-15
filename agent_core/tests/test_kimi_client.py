from agent_core.providers.kimi_client import KimiClient
from agent_core.domain.models import ChatRequest, ChatMessage
from agent_core.tools.definitions import ToolDef, ToolParam


class SettingsStub:
    kimi_api_key = "k"
    http_timeout = 1.0
    kimi_base_url = "https://api.moonshot.cn/v1"


def test_kimi_client_parse_basic(monkeypatch):
    kc = KimiClient(SettingsStub())
    req = ChatRequest(provider="kimi", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    class Resp:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
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
    res = kc.chat(req)
    assert res.choices[0].message.content == "ok"


def test_kimi_client_tools_payload(monkeypatch):
    kc = KimiClient(SettingsStub())
    tool = ToolDef(
        name="read_file",
        description="read file",
        params={
            "path": ToolParam(
                name="path",
                description="Path",
                required=True,
                schema={"type": "string"},
            )
        },
    )
    req = ChatRequest(
        provider="kimi",
        model="ide-chat",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[tool],
        tool_choice="required",
    )

    captured = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [], "usage": {}}

    class Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **_):
            captured["payload"] = json
            return Resp()

    monkeypatch.setattr("httpx.Client", Client)
    kc.chat(req)
    payload = captured["payload"]
    assert payload["tool_choice"] == "required"
    assert payload["tools"][0]["function"]["name"] == "read_file"


def test_kimi_client_parse_tool_calls(monkeypatch):
    kc = KimiClient(SettingsStub())
    req = ChatRequest(provider="kimi", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    class Resp:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tool123",
                                    "function": {
                                        "name": "search_code",
                                        "arguments": '{"query": "todo"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {},
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
    res = kc.chat(req)
    tc = res.choices[0].message.tool_calls[0]
    assert tc.name == "search_code"
    assert tc.arguments["query"] == "todo"


def test_kimi_client_chat_stream(monkeypatch):
    kc = KimiClient(SettingsStub())
    req = ChatRequest(provider="kimi", model="ide-chat", messages=[ChatMessage(role="user", content="hi")])

    stream_lines = [
        'data: {"choices": [{"index": 0, "delta": {"content": "hel"}}]}',
        'data: {"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}',
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
            # 未在流式测试中使用
            raise AssertionError("post should not be called in stream test")

        def stream(self, *a, **kw):
            return StreamContext(FakeResponse(stream_lines))

    monkeypatch.setattr("httpx.Client", Client)
    chunks = list(kc.chat_stream(req))
    assert len(chunks) == 2
    assert chunks[0].choices[0].delta.content == "hel"
    assert chunks[1].choices[0].delta.content == "lo"
    assert chunks[1].usage.total_tokens == 3
