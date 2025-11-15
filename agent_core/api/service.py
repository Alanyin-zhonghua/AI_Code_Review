"""对外 API 服务模块。

提供简化的函数接口供上层应用调用。
"""

from typing import Optional, Dict, Any

from agent_core.config.settings import settings
from agent_core.domain.conversation import ConversationStore
from agent_core.agents.ide_helper_agent import IDEHelperAgent
from agent_core.infrastructure.storage.json_store import JsonConversationStore
from agent_core.infrastructure.logging.logger import logger
from agent_core.providers import create_provider


_store: Optional[ConversationStore] = None
# key: (provider, model, enable_tools)
_agents: dict[tuple[str, str, bool], IDEHelperAgent] = {}


def _get_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = JsonConversationStore(root=settings.storage_root)
    return _store


def get_agent(
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    enable_tools: bool = True,
) -> IDEHelperAgent:
    """获取指定 Provider/模型的 Agent（按需创建并缓存）。

    enable_tools=True 时创建带工具调用能力的 Agent，
    enable_tools=False 则创建纯对话 Agent（用于流式输出等场景）。
    """

    provider_key = (provider_name or getattr(settings, "default_provider", "glm")).lower()
    model_key = model_name or getattr(settings, "default_model", "ide-chat")
    cache_key = (provider_key, model_key, enable_tools)
    agent = _agents.get(cache_key)
    if agent:
        return agent

    provider_client = create_provider(provider_key)
    agent = IDEHelperAgent(
        store=_get_store(),
        provider_client=provider_client,
        tool_executor=None,
        temperature=0.3,
        enable_tools=enable_tools,
        model_name=model_key,
    )
    _agents[cache_key] = agent
    return agent


def get_default_agent() -> IDEHelperAgent:
    """兼容旧接口：获取默认 Provider/模型的 Agent。"""

    return get_agent(enable_tools=True)


def run_ide_chat(
    user_input: str,
    conversation_id: Optional[str] = None,
    focus_message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """运行 IDE 聊天对话。
    
    Args:
        user_input: 用户输入内容
        conversation_id: 会话ID（可选，不提供则创建新会话）
        focus_message_id: 焦点消息ID（可选，用于分叉对话）
        meta: 消息元数据（可选）
        provider_name: 使用的 Provider（可选，默认读取配置）
        model_name: 使用的逻辑模型名（可选，默认读取配置）
    
    Returns:
        包含会话ID、用户消息、助手消息和使用统计的字典
    
    Raises:
        各种 domain.exceptions 中定义的异常
    """
    try:
        agent = get_agent(provider_name, model_name, enable_tools=True)
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


def stream_ide_chat(
    user_input: str,
    conversation_id: Optional[str] = None,
    focus_message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    stream_granularity: str = "chunk",
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
):
    """以流式方式运行 IDE 聊天对话，yield 增量事件字典。

    Args:
        stream_granularity: "chunk"（默认）使用 Provider 原始增量，
            "char" 会把增量拆成单字符事件，方便前端模拟“打字机”效果。
        provider_name: 使用的 Provider（可选）
        model_name: 使用的逻辑模型名（可选）
    """

    # 流式模式暂不支持工具调用，这里使用不带工具的 Agent，
    # 保证前端仍然可以获得流式文本输出。
    # 流式模式现在也支持工具调用：这里使用带工具能力的 Agent，
    # Agent 会先内部完成工具调用闭环，再以流式方式返回最终回答。
    agent = get_agent(provider_name, model_name, enable_tools=True)
    stream = agent.chat_stream(
        user_input=user_input,
        conversation_id=conversation_id,
        focus_message_id=focus_message_id,
        **(meta or {}),
    )
    for event in stream:
        if event.kind == "status":
            # 新增：将 Agent 的状态事件直接透传给前端，便于可视化工具调用过程。
            yield {
                "type": "status",
                "conversation_id": event.conversation.id,
                "user_message_id": event.user_message.id,
                "assistant_message_id": event.assistant_message_id,
                "delta": event.delta_text or "",
            }
        elif event.kind == "delta":
            delta_text = event.delta_text or ""
            chunk_payload = event.chunk.raw if event.chunk and event.chunk.raw else None
            if stream_granularity == "char" and delta_text:
                for idx, ch in enumerate(delta_text):
                    yield {
                        "type": "delta",
                        "conversation_id": event.conversation.id,
                        "user_message_id": event.user_message.id,
                        "assistant_message_id": event.assistant_message_id,
                        "delta": ch,
                        "chunk": chunk_payload if idx == 0 else None,
                    }
            else:
                yield {
                    "type": "delta",
                    "conversation_id": event.conversation.id,
                    "user_message_id": event.user_message.id,
                    "assistant_message_id": event.assistant_message_id,
                    "delta": delta_text,
                    "chunk": chunk_payload,
                }
        else:
            assistant = event.assistant_record
            yield {
                "type": "final",
                "conversation_id": event.conversation.id,
                "user_message_id": event.user_message.id,
                "assistant_message": {
                    "id": assistant.id if assistant else event.assistant_message_id,
                    "content": assistant.content if assistant else "",
                    "created_at": assistant.created_at.isoformat() if assistant else None,
                },
                "usage": (assistant.meta.get("usage") if assistant else None) or None,
            }


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


def delete_conversation(conversation_id: str) -> None:
    """删除指定会话及其所有消息。"""
    agent = get_default_agent()
    agent._engine._store.delete_conversation(conversation_id)
