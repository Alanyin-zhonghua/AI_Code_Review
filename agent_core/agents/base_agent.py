"""Agent 引擎核心模块。

实现对话路径构建、上下文裁剪、调用 provider、处理工具调用等核心逻辑。
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any, Iterable, Literal
from uuid import uuid4
from datetime import datetime, timezone
import time
import logging

from agent_core.domain.conversation import ConversationStore, MessageRecord, Conversation
from agent_core.domain.models import ChatMessage, ChatRequest, ChatResult, ChatStreamChunk, ChatUsage
from agent_core.tools.executor import ToolExecutor
from agent_core.tools.definitions import ToolDef
from agent_core.providers.base import ProviderClient
from agent_core.prompts import load_system_prompt
from agent_core.infrastructure.logging.logger import logger
from agent_core.config.settings import settings


@dataclass
class AgentConfig:
    agent_type: str
    provider: str
    model: str
    enable_tools: bool = False
    max_tool_rounds: int = 20  # 最大工具调用轮次（硬上限由上层控制）
    temperature: float = 0.3  # 生成温度


@dataclass
class AgentStreamEvent:
    """AgentEngine 产生的流式事件。

    kind:
        - "delta": 正常的内容增量（回答的一部分）。
        - "final": 本轮回答结束事件，携带最终 MessageRecord。
        - "status": 工具调用/规划等过程中的状态信息，仅用于前端可视化。
    """

    kind: Literal["delta", "final", "status"]
    conversation: Conversation
    user_message: MessageRecord
    assistant_message_id: str
    chunk: Optional[ChatStreamChunk] = None
    delta_text: Optional[str] = None
    assistant_record: Optional[MessageRecord] = None


class AgentEngine:
    def __init__(
        self,
        store: ConversationStore,
        provider_client: ProviderClient,
        tool_executor: Optional[ToolExecutor] = None,
        tool_defs: Optional[List[ToolDef]] = None,
        config: Optional[AgentConfig] = None,
    ):
        self._store = store
        self._provider_client = provider_client
        self._tool_executor = tool_executor
        self._tool_defs = tool_defs
        self._config = config or AgentConfig(agent_type="ide-helper", provider=provider_client.name, model="ide-chat")

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
        trace_id = f"tr-{uuid4().hex}"
        log_ctx: Dict[str, Any] = {
            "trace_id": trace_id,
            "agent_type": self._config.agent_type,
        }
        
        # 1. 获取或创建会话
        meta_with_model = dict(meta)
        meta_with_model.setdefault("provider", self._config.provider)
        meta_with_model.setdefault("model", self._config.model)
        if not conversation_id:
            conv = self._store.create_conversation(self._config.agent_type, meta_with_model)
            log_ctx["conversation_id"] = conv.id
            self._log(logging.INFO, "Created new conversation", log_ctx)
        else:
            conv = self._store.get_conversation(conversation_id)
            log_ctx["conversation_id"] = conv.id
        
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
            self._log(
                logging.INFO,
                "Truncated context",
                log_ctx,
                max_context=max_context,
                trimmed=len(path) - max_context,
            )
        
        # 5. 构造消息列表
        system_prompt = load_system_prompt(self._config.agent_type)
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for mr in path:
            chat_messages.append(ChatMessage(role=mr.role, content=mr.content, meta=mr.meta))
        chat_messages.append(ChatMessage(role="user", content=user_input, meta=meta_with_model))
        
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
            meta=meta_with_model,
        )
        self._store.add_message(user_rec)
        self._log(
            logging.INFO,
            "Stored user message",
            log_ctx,
            message_id=user_rec.id,
            depth=user_rec.depth,
        )
        
        # 处理工具调用循环
        if self._config.enable_tools and self._tool_executor:
            assistant_rec = self._run_with_tools(conv, chat_messages, user_rec, log_ctx)
        else:
            assistant_rec = self._run_simple(conv, chat_messages, user_rec, log_ctx)
        
        elapsed = time.time() - start_time
        self._log(
            logging.INFO,
            "Completed agent step",
            log_ctx,
            elapsed_seconds=round(elapsed, 2),
            user_message_id=user_rec.id,
            assistant_message_id=assistant_rec.id,
        )
        
        return conv, user_rec, assistant_rec

    def run_step_stream(
        self,
        conversation_id: Optional[str],
        user_input: str,
        meta: dict,
        focus_message_id: Optional[str] = None,
    ) -> Iterable[AgentStreamEvent]:
        """执行一次流式对话步骤。

        当 enable_tools=True 且配置了 ToolExecutor 时，将先通过非流式
        模式完成工具调用闭环，然后使用 chat_stream 仅生成最终答案，
        这样既保留自动工具调用，又能在前端看到流式输出。
        """

        start_time = time.time()
        trace_id = f"tr-{uuid4().hex}"
        log_ctx: Dict[str, Any] = {
            "trace_id": trace_id,
            "agent_type": self._config.agent_type,
        }

        meta_with_model = dict(meta)
        meta_with_model.setdefault("provider", self._config.provider)
        meta_with_model.setdefault("model", self._config.model)

        if not conversation_id:
            conv = self._store.create_conversation(self._config.agent_type, meta_with_model)
            log_ctx["conversation_id"] = conv.id
            self._log(logging.INFO, "Created new conversation", log_ctx)
        else:
            conv = self._store.get_conversation(conversation_id)
            log_ctx["conversation_id"] = conv.id

        leaf = None
        if focus_message_id:
            leaf = self._store.get_message(focus_message_id)
        else:
            msgs = self._store.list_messages(conv.id)
            leaf = msgs[-1] if msgs else None

        path = self._build_path(leaf)
        max_context = getattr(settings, 'max_context_messages', 20)
        if len(path) > max_context:
            path = path[-max_context:]
            self._log(
                logging.INFO,
                "Truncated context",
                log_ctx,
                max_context=max_context,
                trimmed=len(path) - max_context,
            )

        system_prompt = load_system_prompt(self._config.agent_type)
        chat_messages = [ChatMessage(role="system", content=system_prompt)]
        for mr in path:
            chat_messages.append(ChatMessage(role=mr.role, content=mr.content, meta=mr.meta))
        chat_messages.append(ChatMessage(role="user", content=user_input, meta=meta_with_model))

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
            meta=meta_with_model,
        )
        self._store.add_message(user_rec)
        self._log(
            logging.INFO,
            "Stored user message",
            log_ctx,
            message_id=user_rec.id,
            depth=user_rec.depth,
        )

        # 工具模式：复用 _run_with_tools 完成工具调用闭环，然后在本地模拟流式输出。
        # 这样不会额外增加一次 chat_stream 调用，避免对 API 造成翻倍压力。
        if self._config.enable_tools and self._tool_executor:
            # 新增：在流式模式下，对工具调用过程发出 "status" 事件，便于前端可视化。
            for event in self._run_with_tools_stream(conv, chat_messages, user_rec, log_ctx):
                if event.kind == "final":
                    final_event = event
                yield event

            elapsed = time.time() - start_time
            assistant_id = final_event.assistant_message_id if final_event else None
            self._log(
                logging.INFO,
                "Completed agent step",
                log_ctx,
                elapsed_seconds=round(elapsed, 2),
                user_message_id=user_rec.id,
                assistant_message_id=assistant_id,
            )
            return

        # 非工具模式：直接使用 Provider 的流式接口
        final_event: Optional[AgentStreamEvent] = None
        for event in self._run_stream_simple(conv, chat_messages, user_rec, log_ctx):
            if event.kind == "final":
                final_event = event
            yield event

        elapsed = time.time() - start_time
        assistant_id = final_event.assistant_message_id if final_event else None
        self._log(
            logging.INFO,
            "Completed agent step",
            log_ctx,
            elapsed_seconds=round(elapsed, 2),
            user_message_id=user_rec.id,
            assistant_message_id=assistant_id,
        )
    
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
        log_ctx: Dict[str, Any],
    ) -> MessageRecord:
        """简单模式：不使用工具，直接调用 provider。"""
        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=chat_messages,
            temperature=self._config.temperature,
        )
        
        self._log(
            logging.INFO,
            "Calling provider",
            log_ctx,
            provider=self._config.provider,
            model=self._config.model,
            message_count=len(chat_messages),
        )
        
        result: ChatResult = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        
        usage_meta = {}
        if result.usage:
            usage_meta = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }
            self._log(logging.INFO, "Token usage", log_ctx, **usage_meta)
        
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
        self._log(
            logging.INFO,
            "Stored assistant message",
            log_ctx,
            message_id=assistant_rec.id,
            depth=assistant_rec.depth,
        )
        return assistant_rec

    def _run_with_tools_stream(
        self,
        conv: Conversation,
        chat_messages: List[ChatMessage],
        parent: MessageRecord,
        log_ctx: Dict[str, Any],
    ) -> Iterable[AgentStreamEvent]:
        """工具模式（流式）：带状态事件的多轮工具调用循环。

        - 在每轮工具决策/执行时发出 kind="status" 事件，便于前端可视化模型“在工作”。
        - 最终回答生成后，以本地字符串切片方式发出 kind="delta" 事件，模拟流式输出。
        """

        if not self._tool_defs:
            logger.warning("Tool mode enabled but no tool definitions available; fallback to simple stream")
            for event in self._run_stream_simple(conv, chat_messages, parent, log_ctx):
                yield event
            return

        current_messages = list(chat_messages)
        current_parent = parent
        max_rounds = self._config.max_tool_rounds
        tool_defs = self._tool_defs or []

        for round_num in range(1, max_rounds + 1):
            yield AgentStreamEvent(
                kind="status",
                conversation=conv,
                user_message=parent,
                assistant_message_id="",
                delta_text=f"[系统] 正在进行第 {round_num} 轮工具决策...",
            )

            req = ChatRequest(
                provider=self._config.provider,
                model=self._config.model,
                messages=current_messages,
                temperature=self._config.temperature,
                tools=tool_defs,
                tool_choice="auto",
            )

            result: ChatResult = self._provider_client.chat(req)
            assistant_msg = result.choices[0].message

            # 没有工具调用，视为最终回答
            if not assistant_msg.tool_calls:
                usage_meta = self._usage_meta_from_usage(result.usage)
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
                self._log(
                    logging.INFO,
                    "Stored assistant message",
                    log_ctx,
                    message_id=assistant_rec.id,
                    depth=assistant_rec.depth,
                )

                # 本地模拟流式输出
                content = assistant_rec.content or ""
                chunk_size = getattr(settings, "stream_chunk_size", 32)
                for i in range(0, len(content), chunk_size):
                    delta_text = content[i : i + chunk_size]
                    if not delta_text:
                        continue
                    yield AgentStreamEvent(
                        kind="delta",
                        conversation=conv,
                        user_message=parent,
                        assistant_message_id=assistant_rec.id,
                        delta_text=delta_text,
                    )

                yield AgentStreamEvent(
                    kind="final",
                    conversation=conv,
                    user_message=parent,
                    assistant_message_id=assistant_rec.id,
                    assistant_record=assistant_rec,
                )
                return

            # 有工具调用，发出状态事件并执行工具
            tool_names = ", ".join(call.name for call in assistant_msg.tool_calls)
            yield AgentStreamEvent(
                kind="status",
                conversation=conv,
                user_message=parent,
                assistant_message_id="",
                delta_text=f"[系统] 模型决定调用工具: {tool_names}",
            )

            current_messages.append(assistant_msg)

            for tool_call in assistant_msg.tool_calls:
                yield AgentStreamEvent(
                    kind="status",
                    conversation=conv,
                    user_message=parent,
                    assistant_message_id="",
                    delta_text=f"[工具] 正在调用 {tool_call.name} 参数: {tool_call.arguments}",
                )
                try:
                    if self._tool_executor is None:
                        raise RuntimeError("Tool executor not configured")
                    tool_result = self._tool_executor.execute(tool_call)
                    result_msg = ChatMessage(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(result_msg)
                    preview = (tool_result.content[:120] + "...") if len(tool_result.content or "") > 120 else tool_result.content
                    yield AgentStreamEvent(
                        kind="status",
                        conversation=conv,
                        user_message=parent,
                        assistant_message_id="",
                        delta_text=f"[工具] {tool_call.name} 执行完成，结果预览: {preview}",
                    )
                except Exception as e:
                    error_msg = ChatMessage(
                        role="tool",
                        content=f"Error: {str(e)}",
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(error_msg)
                    yield AgentStreamEvent(
                        kind="status",
                        conversation=conv,
                        user_message=parent,
                        assistant_message_id="",
                        delta_text=f"[工具] {tool_call.name} 执行失败: {e}",
                    )

        # 超过最大轮数仍未得到最终回答
        yield AgentStreamEvent(
            kind="status",
            conversation=conv,
            user_message=parent,
            assistant_message_id="",
            delta_text=f"[系统] 已达到最大工具轮数 {max_rounds}，将直接让模型给出总结回答。",
        )

        final_hint = (
            "你已经完成所有必要的工具调用。"
            "现在请用简明的中文总结你在代码和配置中发现的问题与风险，"
            "如果没有明显错误，也要明确说明检查范围和结论。"
            "不要再说“让我检查”或继续提出计划，直接给出结论和建议。"
        )
        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=current_messages
            + [ChatMessage(role="system", content=final_hint)],
            temperature=self._config.temperature,
            tool_choice="none",
        )
        result = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        usage_meta = self._usage_meta_from_usage(result.usage)
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
                "usage": usage_meta,
            },
        )
        self._store.add_message(assistant_rec)

        content = assistant_rec.content or ""
        chunk_size = getattr(settings, "stream_chunk_size", 32)
        for i in range(0, len(content), chunk_size):
            delta_text = content[i : i + chunk_size]
            if not delta_text:
                continue
            yield AgentStreamEvent(
                kind="delta",
                conversation=conv,
                user_message=parent,
                assistant_message_id=assistant_rec.id,
                delta_text=delta_text,
            )

        yield AgentStreamEvent(
            kind="final",
            conversation=conv,
            user_message=parent,
            assistant_message_id=assistant_rec.id,
            assistant_record=assistant_rec,
        )
    
    def _run_with_tools(
        self,
        conv: Conversation,
        chat_messages: List[ChatMessage],
        parent: MessageRecord,
        log_ctx: Dict[str, Any],
    ) -> MessageRecord:
        """工具模式：支持多轮工具调用循环。
        
        实现流程：
        1. 调用 provider
        2. 如果有 tool_calls，执行工具并将结果追加到消息列表
        3. 重复步骤 1-2，最多 max_tool_rounds 轮
        4. 返回最终的助手消息
        """
        if not self._tool_defs:
            logger.warning("Tool mode enabled but no tool definitions available; fallback to simple run")
            return self._run_simple(conv, chat_messages, parent, log_ctx)

        current_messages = list(chat_messages)
        current_parent = parent
        max_rounds = self._config.max_tool_rounds
        tool_defs = self._tool_defs or []
        
        for round_num in range(1, max_rounds + 1):
            self._log(
                logging.INFO,
                "Tool round",
                log_ctx,
                round=round_num,
                max_rounds=max_rounds,
            )
            
            req = ChatRequest(
                provider=self._config.provider,
                model=self._config.model,
                messages=current_messages,
                temperature=self._config.temperature,
                tools=tool_defs,
                tool_choice="auto",
            )
            
            result: ChatResult = self._provider_client.chat(req)
            assistant_msg = result.choices[0].message
            
            # 检查是否有工具调用
            if not assistant_msg.tool_calls:
                usage_meta = self._usage_meta_from_usage(result.usage)
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
                self._log(
                    logging.INFO,
                    "Stored assistant message",
                    log_ctx,
                    message_id=assistant_rec.id,
                    depth=assistant_rec.depth,
                )
                return assistant_rec

            self._log(
                logging.INFO,
                "Executing tool calls",
                log_ctx,
                call_count=len(assistant_msg.tool_calls),
            )
            current_messages.append(assistant_msg)
            
            for tool_call in assistant_msg.tool_calls:
                try:
                    if self._tool_executor is None:
                        raise RuntimeError("Tool executor not configured")
                    self._log(
                        logging.INFO,
                        "Tool call received",
                        log_ctx,
                        tool_name=tool_call.name,
                        tool_call_id=tool_call.id,
                        tool_args=tool_call.arguments,
                    )
                    tool_result = self._tool_executor.execute(tool_call)
                    self._log(
                        logging.INFO,
                        "Tool execution finished",
                        log_ctx,
                        tool_call_id=tool_call.id,
                        result_preview=(tool_result.content[:200] if tool_result.content else ""),
                    )
                    result_msg = ChatMessage(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(result_msg)
                except Exception as e:
                    self._log(
                        logging.ERROR,
                        "Tool execution failed",
                        log_ctx,
                        tool_call_id=tool_call.id,
                        error=str(e),
                    )
                    error_msg = ChatMessage(
                        role="tool",
                        content=f"Error: {str(e)}",
                        tool_call_id=tool_call.id,
                    )
                    current_messages.append(error_msg)

        self._log(
            logging.WARNING,
            "Reached max tool rounds",
            log_ctx,
            max_rounds=max_rounds,
        )
        final_hint = (
            "你已经完成所有必要的工具调用。"
            "现在请用简明的中文总结你在代码和配置中发现的问题与风险，"
            "如果没有明显错误，也要明确说明检查范围和结论。"
            "不要再说“让我检查”或继续提出计划，直接给出结论和建议。"
        )
        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=current_messages + [
                ChatMessage(role="system", content=final_hint)
            ],
            temperature=self._config.temperature,
            tool_choice="none",
        )
        result = self._provider_client.chat(req)
        assistant_msg = result.choices[0].message
        usage_meta = self._usage_meta_from_usage(result.usage)
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
                "usage": usage_meta,
            },
        )
        self._store.add_message(assistant_rec)
        self._log(
            logging.INFO,
            "Stored assistant message",
            log_ctx,
            message_id=assistant_rec.id,
            depth=assistant_rec.depth,
        )
        return assistant_rec

    @staticmethod
    def _usage_meta_from_usage(usage: Optional[ChatUsage]) -> Dict[str, Any]:
        if not usage:
            return {}
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    def _run_stream_simple(
        self,
        conv: Conversation,
        chat_messages: List[ChatMessage],
        parent: MessageRecord,
        log_ctx: Dict[str, Any],
    ) -> Iterable[AgentStreamEvent]:
        """流式模式：不使用工具，直接调用 provider 的流式接口。"""

        req = ChatRequest(
            provider=self._config.provider,
            model=self._config.model,
            messages=chat_messages,
            temperature=self._config.temperature,
        )

        self._log(
            logging.INFO,
            "Calling provider (stream)",
            log_ctx,
            provider=self._config.provider,
            model=self._config.model,
            message_count=len(chat_messages),
        )

        stream = self._provider_client.chat_stream(req)
        assistant_id = f"m-{uuid4().hex}"
        pieces: List[str] = []
        usage_meta: Dict[str, Any] = {}

        for chunk in stream:
            delta_text = ""
            if chunk.choices:
                delta_msg = chunk.choices[0].delta
                delta_text = delta_msg.content or ""
                if delta_text:
                    pieces.append(delta_text)
            if chunk.usage:
                usage_meta = self._usage_meta_from_usage(chunk.usage)
                self._log(logging.INFO, "Token usage", log_ctx, **usage_meta)
            yield AgentStreamEvent(
                kind="delta",
                conversation=conv,
                user_message=parent,
                assistant_message_id=assistant_id,
                chunk=chunk,
                delta_text=delta_text,
            )

        content = "".join(pieces)
        now = datetime.now(timezone.utc)
        assistant_rec = MessageRecord(
            id=assistant_id,
            conversation_id=conv.id,
            role="assistant",
            content=content,
            parent_id=parent.id,
            depth=parent.depth + 1,
            version=1,
            created_at=now,
            meta={
                "provider": self._config.provider,
                "usage": usage_meta,
            },
        )
        self._store.add_message(assistant_rec)
        self._log(
            logging.INFO,
            "Stored assistant message",
            log_ctx,
            message_id=assistant_rec.id,
            depth=assistant_rec.depth,
        )
        yield AgentStreamEvent(
            kind="final",
            conversation=conv,
            user_message=parent,
            assistant_message_id=assistant_rec.id,
            assistant_record=assistant_rec,
        )

    @staticmethod
    def _log(level: int, message: str, log_ctx: Dict[str, Any], **fields: Any) -> None:
        payload = dict(log_ctx)
        payload.update(fields)
        logger.log(level, message, extra={"extra": payload})
