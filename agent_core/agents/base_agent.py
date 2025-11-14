"""Agent 引擎核心模块。

实现对话路径构建、上下文裁剪、调用 provider、处理工具调用等核心逻辑。
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple
from uuid import uuid4
from datetime import datetime, timezone
import time

from agent_core.domain.conversation import ConversationStore, MessageRecord, Conversation
from agent_core.domain.models import ChatMessage, ChatRequest, ChatResult
from agent_core.tools.executor import ToolExecutor
from agent_core.providers.kimi_client import KimiClient
from agent_core.prompts import load_system_prompt
from agent_core.infrastructure.logging.logger import logger
from agent_core.config.settings import settings


@dataclass
class AgentConfig:
    agent_type: str
    provider: str
    model: str
    enable_tools: bool = False
    max_tool_rounds: int = 5  # 最大工具调用轮次
    temperature: float = 0.3  # 生成温度


class AgentEngine:
    def __init__(
        self,
        store: ConversationStore,
        provider_client: KimiClient,
        tool_executor: Optional[ToolExecutor] = None,
        config: Optional[AgentConfig] = None,
    ):
        self._store = store
        self._provider_client = provider_client
        self._tool_executor = tool_executor
        self._config = config or AgentConfig(agent_type="ide-helper", provider="kimi", model="ide-chat")

    def run_step(
        self,
        conversation_id: Optional[str],
        user_input: str,
        meta: dict,
        focus_message_id: Optional[str] = None,
    ) -> Tuple[Conversation, MessageRecord, MessageRecord]:
        """执行一次 Agent 对话步骤。
        
        Args:
            conversation_id: 会话ID（可选）
            user_input: 用户输入
            meta: 消息元数据
            focus_message_id: 焦点消息ID（用于分叉对话）
        
        Returns:
            (会话, 用户消息记录, 助手消息记录) 的元组
        """
        start_time = time.time()
        
        # 1. 获取或创建会话
        if not conversation_id:
            conv = self._store.create_conversation(self._config.agent_type, meta)
            logger.info("Created new conversation", extra={"extra": {"conversation_id": conv.id}})
        else:
            conv = self._store.get_conversation(conversation_id)
        
        # 2. 确定对话路径的叶子节点
        leaf = None
        if focus_message_id:
            leaf = self._store.get_message(focus_message_id)
        else:
            msgs = self._store.list_messages(conv.id)
            leaf = msgs[-1] if msgs else None
        
        # 3. 构建路径（从叶子回溯到根）
        path = self._build_path(leaf)
        
        # 4. 裁剪到最大上下文长度
        max_context = getattr(settings, 'max_context_messages', 20)
        if len(path) > max_context:
            path = path[-max_context:]
            logger.info(f"Truncated context to {max_context} messages")
        
        # 5. 构造消息列表
        system_prompt = load_system_prompt(self._config.agent_type)
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for mr in path:
            chat_messages.append(ChatMessage(role=mr.role, content=mr.content, meta=mr.meta))
        chat_messages.append(ChatMessage(role="user", content=user_input, meta=meta))
        
        # 6. 调用 provider（支持工具调用循环）
        now = datetime.now(timezone.utc)
        user_rec = MessageRecord(
            id=f"m-{uuid4().hex}",
            conversation_id=conv.id,
            role="user",
            content=user_input,
            parent_id=leaf.id if leaf else None,
            depth=(leaf.depth + 1 if leaf else 0),
            version=1,
            created_at=now,
            meta=meta,
        )
        self._store.add_message(user_rec)
        
        # 处理工具调用循环
        if self._config.enable_tools and self._tool_executor:
            assistant_rec = self._run_with_tools(conv, chat_messages, user_rec)
        else:
            assistant_rec = self._run_simple(conv, chat_messages, user_rec)
        
        elapsed = time.time() - start_time
        logger.info(
            "Completed agent step",
            extra={"extra": {
                "conversation_id": conv.id,
                "elapsed_seconds": round(elapsed, 2),
                "user_message_id": user_rec.id,
                "assistant_message_id": assistant_rec.id,
            }}
        )
        
        return conv, user_rec, assistant_rec
    
    def _build_path(self, leaf: Optional[MessageRecord]) -> List[MessageRecord]:
        """构建从根到叶子的消息路径。"""
        path: List[MessageRecord] = []
        current = leaf
        while current is not None:
            path.append(current)
            if current.parent_id is None:
                break
            current = self._store.get_message(current.parent_id)
        path.reverse()
        return path
    
    def _run_simple(
        self,
        conv: Conversation,
        chat_messages: List[ChatMessage],
        parent: MessageRecord,
    ) -> MessageRecord:
        """简单模式：不使用工具，直接调用 provider。"""
        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=chat_messages,
            temperature=self._config.temperature,
        )
        
        logger.info("Calling provider", extra={"extra": {
            "provider": self._config.provider,
            "model": self._config.model,
            "message_count": len(chat_messages),
        }})
        
        result: ChatResult = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        
        usage_meta = {}
        if result.usage:
            usage_meta = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }
            logger.info("Token usage", extra={"extra": usage_meta})
        
        now = datetime.now(timezone.utc)
        assistant_rec = MessageRecord(
            id=f"m-{uuid4().hex}",
            conversation_id=conv.id,
            role="assistant",
            content=assistant_msg.content,
            parent_id=parent.id,
            depth=parent.depth + 1,
            version=1,
            created_at=now,
            meta={"provider": self._config.provider, "usage": usage_meta},
        )
        self._store.add_message(assistant_rec)
        return assistant_rec
    
    def _run_with_tools(
        self,
        conv: Conversation,
        chat_messages: List[ChatMessage],
        parent: MessageRecord,
    ) -> MessageRecord:
        """工具模式：支持多轮工具调用循环。
        
        实现流程：
        1. 调用 provider
        2. 如果有 tool_calls，执行工具并将结果追加到消息列表
        3. 重复步骤 1-2，最多 max_tool_rounds 轮
        4. 返回最终的助手消息
        """
        current_messages = list(chat_messages)
        current_parent = parent
        max_rounds = self._config.max_tool_rounds
        
        for round_num in range(1, max_rounds + 1):
            logger.info(f"Tool round {round_num}/{max_rounds}")
            
            req = ChatRequest(
                provider=self._config.provider,
                model=self._config.model,
                messages=current_messages,
                temperature=self._config.temperature,
                tools=None,  # TODO: 添加工具定义
                tool_choice="auto",
            )
            
            result: ChatResult = self._provider_client.chat(req)
            assistant_msg = result.choices[0].message
            
            # 检查是否有工具调用
            if not assistant_msg.tool_calls:
                # 没有工具调用，返回最终结果
                usage_meta = {}
                if result.usage:
                    usage_meta = {
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "total_tokens": result.usage.total_tokens,
                    }
                
                now = datetime.now(timezone.utc)
                assistant_rec = MessageRecord(
                    id=f"m-{uuid4().hex}",
                    conversation_id=conv.id,
                    role="assistant",
                    content=assistant_msg.content,
                    parent_id=current_parent.id,
                    depth=current_parent.depth + 1,
                    version=1,
                    created_at=now,
                    meta={
                        "provider": self._config.provider,
                        "usage": usage_meta,
                        "tool_rounds": round_num,
                    },
                )
                self._store.add_message(assistant_rec)
                return assistant_rec
            
            # 有工具调用，执行工具
            logger.info(f"Executing {len(assistant_msg.tool_calls)} tool calls")
            current_messages.append(assistant_msg)
            
            for tool_call in assistant_msg.tool_calls:
                try:
                    tool_result = self._tool_executor.execute(tool_call)
                    result_msg = ChatMessage(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(result_msg)
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    error_msg = ChatMessage(
                        role="tool",
                        content=f"Error: {str(e)}",
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(error_msg)
        
        # 达到最大轮次，强制要求模型给出总结
        logger.warning(f"Reached max tool rounds ({max_rounds}), forcing final response")
        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=current_messages + [
                ChatMessage(role="system", content="请基于以上工具调用结果，给出最终回答。")
            ],
            temperature=self._config.temperature,
            tool_choice="none",
        )
        
        result = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        
        now = datetime.now(timezone.utc)
        assistant_rec = MessageRecord(
            id=f"m-{uuid4().hex}",
            conversation_id=conv.id,
            role="assistant",
            content=assistant_msg.content,
            parent_id=current_parent.id,
            depth=current_parent.depth + 1,
            version=1,
            created_at=now,
            meta={
                "provider": self._config.provider,
                "tool_rounds": max_rounds,
                "forced_final": True,
            },
        )
        self._store.add_message(assistant_rec)
        return assistant_rec