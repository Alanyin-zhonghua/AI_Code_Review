import tempfile
from pathlib import Path
from agent_core.tools.executor import ToolExecutor, default_tools
from agent_core.tools.definitions import ToolCall


def test_tools_basic_read_list_search_propose():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = root / "a.txt"
        f.write_text("hello\nworld\nline3", encoding="utf-8")
        te = ToolExecutor(default_tools())
        rc = te.execute(ToolCall(id="1", name="read_file", arguments={"path": str(f)}))
        assert "hello" in rc.content
        lc = te.execute(ToolCall(id="2", name="list_files", arguments={"directory": str(root), "pattern": "*.txt"}))
        assert "a.txt" in lc.content
        sc = te.execute(ToolCall(id="3", name="search_code", arguments={"directory": str(root), "query": "world", "max_results": 5}))
        assert "world" in sc.content
        pc = te.execute(ToolCall(id="4", name="propose_edit", arguments={"path": str(f), "range": [2, 2], "new_content": "planet"}))
        assert "@@ -2,1 +2,1" in pc.content