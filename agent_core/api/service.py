"""对外 API 服务模块。

提供简化的函数接口供上层应用调用。
"""

from typing import Optional, Dict, Any

from agent_core.config.settings import settings
from agent_core.domain.conversation import ConversationStore
from agent_core.providers.kimi_client import KimiClient
from agent_core.agents.ide_helper_agent import IDEHelperAgent
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.infrastructure.logging.logger import logger


_store: Optional[ConversationStore] = None
_agent: Optional[IDEHelperAgent] = None


def get_default_agent() -> IDEHelperAgent:
    """获取默认的 IDE Helper Agent 实例（单例）。"""
    global _store, _agent
    if _store is None:
        _store = JsonConversationStore(root=settings.storage_root)
    if _agent is None:
        provider = KimiClient(settings)
        _agent = IDEHelperAgent(
            store=_store,
            provider_client=provider,
            tool_executor=None,
            temperature=0.3,
            enable_tools=False,
        )
    return _agent


def run_ide_chat(
    user_input: str,
    conversation_id: Optional[str] = None,
    focus_message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """运行 IDE 聊天对话。
    
    Args:
        user_input: 用户输入内容
        conversation_id: 会话ID（可选，不提供则创建新会话）
        focus_message_id: 焦点消息ID（可选，用于分叉对话）
        meta: 消息元数据（可选）
    
    Returns:
        包含会话ID、用户消息、助手消息和使用统计的字典
    
    Raises:
        各种 domain.exceptions 中定义的异常
    """
    try:
        agent = get_default_agent()
        conv, user_rec, assistant_rec = agent.chat(
            user_input=user_input,
            conversation_id=conversation_id,
            focus_message_id=focus_message_id,
            **(meta or {})
        )
        
        return {
            "conversation_id": conv.id,
            "user_message": {
                "id": user_rec.id,
                "content": user_rec.content,
                "created_at": user_rec.created_at.isoformat(),
            },
            "assistant_message": {
                "id": assistant_rec.id,
                "content": assistant_rec.content,
                "created_at": assistant_rec.created_at.isoformat(),
            },
            "usage": assistant_rec.meta.get("usage"),
        }
    except Exception as e:
        logger.error(f"Chat failed: {e}", extra={"extra": {
            "conversation_id": conversation_id,
            "error": str(e),
        }})
        raise


def list_conversations() -> list[Dict[str, Any]]:
    """列出所有会话。
    
    Returns:
        会话列表，每项包含 id, title, agent_type, created_at, updated_at
    """
    agent = get_default_agent()
    convs = agent._engine._store.list_conversations()
    return [
        {
            "id": c.id,
            "title": c.title or c.meta.get("title", ""),
            "agent_type": c.agent_type,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "meta": c.meta,
        }
        for c in convs
    ]


def get_conversation_messages(conversation_id: str) -> list[Dict[str, Any]]:
    """获取会话的所有消息。
    
    Args:
        conversation_id: 会话ID
    
    Returns:
        消息列表
    """
    agent = get_default_agent()
    msgs = agent._engine._store.list_messages(conversation_id)
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "parent_id": m.parent_id,
            "depth": m.depth,
            "created_at": m.created_at.isoformat(),
            "meta": m.meta,
        }
        for m in msgs
    ]