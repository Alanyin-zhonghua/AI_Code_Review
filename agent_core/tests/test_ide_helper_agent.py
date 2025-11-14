"""测试 IDE Helper Agent。"""

import tempfile
from pathlib import Path

from agent_core.agents.ide_helper_agent import IDEHelperAgent
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.domain.models import ChatResult, ChatChoice, ChatMessage


class FakeProvider:
    """模拟的 Provider。"""
    name = "fake"
    
    def chat(self, req):
        msg = ChatMessage(role="assistant", content="这是测试回复")
        return ChatResult(
            provider="fake",
            model="ide-chat",
            choices=[ChatChoice(index=0, message=msg)],
            usage=None,
            raw={}
        )


def test_ide_helper_agent_chat():
    """测试 IDE Helper Agent 的对话功能。"""
    with tempfile.TemporaryDirectory() as d:
        store = JsonConversationStore(root=Path(d) / ".storage")
        agent = IDEHelperAgent(
            store=store,
            provider_client=FakeProvider(),
            temperature=0.3,
        )
        
        # 第一次对话
        conv, user_msg, assistant_msg = agent.chat(
            user_input="帮我分析这段代码",
            file_path="test.py"
        )
        
        assert conv.id
        assert conv.agent_type == "ide-helper"
        assert user_msg.role == "user"
        assert user_msg.content == "帮我分析这段代码"
        assert user_msg.meta.get("file_path") == "test.py"
        assert assistant_msg.role == "assistant"
        assert assistant_msg.content == "这是测试回复"
        
        # 继续对话
        conv2, user_msg2, assistant_msg2 = agent.chat(
            user_input="详细说明一下",
            conversation_id=conv.id
        )
        
        assert conv2.id == conv.id
        assert user_msg2.parent_id == assistant_msg.id
        assert user_msg2.depth == assistant_msg.depth + 1


def test_ide_helper_agent_create_conversation():
    """测试创建会话功能。"""
    with tempfile.TemporaryDirectory() as d:
        store = JsonConversationStore(root=Path(d) / ".storage")
        agent = IDEHelperAgent(
            store=store,
            provider_client=FakeProvider(),
        )
        
        conv = agent.create_conversation(
            title="测试会话",
            project_root="/path/to/project"
        )
        
        assert conv.id
        assert conv.agent_type == "ide-helper"
        assert conv.meta.get("title") == "测试会话"
        assert conv.meta.get("project_root") == "/path/to/project"
