from agent_core.flows import runner as runner_module
from agent_core.flows import graph as graph_module
from agent_core.flows.tools_interface import ToolManager


class DummyToolManager(ToolManager):
    def __init__(self):
        super().__init__(workspace_root=".")

    def run(self, name, arguments):
        return {"ok": True, "content": f"ran {name} with {arguments}"}


def test_run_agent_smoke(monkeypatch):
    responses = iter([
        "先阅读指定文件",  # planner
        '{"action": "tool", "tool_name": "read_file", "tool_args": {"path": "README.md"}}',
        '{"action": "final", "response": "文件主要介绍项目结构"}',
    ])

    def fake_call_llm(messages, prompt, provider, model):
        try:
            return next(responses)
        except StopIteration:
            return "done"

    monkeypatch.setattr(graph_module, "_call_llm", fake_call_llm)
    tm = DummyToolManager()
    runner_module._tool_manager = tm
    runner_module._graph = graph_module.build_graph(tm)
    reply = runner_module.run_agent("读取 README 并总结")
    assert "文件" in reply
