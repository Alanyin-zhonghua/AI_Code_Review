"""IDE 助手 Agent 的专用包装。

提供面向 IDE 的便捷接口,自动配置特定的系统提示词和参数。
"""

from typing import Optional, Dict, Any, Tuple, Protocol, List

from agent_core.agents.base_agent import AgentEngine, AgentConfig
from agent_core.domain.conversation import ConversationStore, Conversation, MessageRecord
from agent_core.domain.models import ChatRequest, ChatResult
from agent_core.tools.executor import ToolExecutor, default_tools, default_tool_defs
from agent_core.tools.definitions import ToolDef
from agent_core.config.settings import settings


class ProviderClient(Protocol):
    """Provider 客户端协议。"""
    name: str
    
    def chat(self, req: ChatRequest) -> ChatResult:
        ...


class IDEHelperAgent:
    """IDE 助手 Agent 的便捷包装类。
    
    自动配置为 ide-helper 类型,使用优化的温度和上下文参数。
    """
    
    def __init__(
        self,
        store: ConversationStore,
        provider_client: ProviderClient,
        tool_executor: Optional[ToolExecutor] = None,
        tool_defs: Optional[List[ToolDef]] = None,
        temperature: float = 0.3,
        enable_tools: bool = False,
        model_name: Optional[str] = None,
    ):
        """初始化 IDE Helper Agent。
        
        Args:
            store: 会话存储实例
            provider_client: Provider 客户端实例
            tool_executor: 工具执行器（可选）
            temperature: 生成温度,默认 0.3（更确定性）
            enable_tools: 是否启用工具调用
        """
        if enable_tools and tool_executor is None:
            tool_executor = ToolExecutor(default_tools(settings.workspace_root))
        if tool_executor and tool_defs is None:
            tool_defs = default_tool_defs()

        provider_name = getattr(provider_client, "name", None) or getattr(settings, "default_provider", "glm")

        max_rounds = getattr(settings, "max_tool_rounds", 20)
        self._config = AgentConfig(
            agent_type="ide-helper",
            provider=provider_name,
            model=model_name or getattr(settings, "default_model", "ide-chat"),
            enable_tools=enable_tools,
            max_tool_rounds=max_rounds,
            temperature=temperature,
        )
        self._engine = AgentEngine(
            store=store,
            provider_client=provider_client,
            tool_executor=tool_executor,
            tool_defs=tool_defs,
            config=self._config,
        )
    
    def chat(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        focus_message_id: Optional[str] = None,
        file_path: Optional[str] = None,
        **meta
    ) -> Tuple[Conversation, MessageRecord, MessageRecord]:
        """发起对话。
        
        Args:
            user_input: 用户输入
            conversation_id: 会话ID（可选,不提供则创建新会话）
            focus_message_id: 焦点消息ID（用于分叉对话）
            file_path: 当前文件路径（可选）
            **meta: 其他元数据
        
        Returns:
            (会话, 用户消息, 助手消息) 的元组
        """
        # 构建元数据
        message_meta = dict(meta)
        if file_path:
            message_meta["file_path"] = file_path
        
        return self._engine.run_step(
            conversation_id=conversation_id,
            user_input=user_input,
            meta=message_meta,
            focus_message_id=focus_message_id,
        )

    def chat_stream(
        self,
        user_input: str,
        conversation_id: Optional[str] = None,
        focus_message_id: Optional[str] = None,
        file_path: Optional[str] = None,
        **meta,
    ):
        """以流式方式发起对话，返回事件迭代器。"""

        message_meta = dict(meta)
        if file_path:
            message_meta["file_path"] = file_path

        return self._engine.run_step_stream(
            conversation_id=conversation_id,
            user_input=user_input,
            meta=message_meta,
            focus_message_id=focus_message_id,
        )
    
    def create_conversation(self, title: str = "", **meta) -> Conversation:
        """创建新会话。
        
        Args:
            title: 会话标题（可选）
            **meta: 会话元数据
        
        Returns:
            新创建的会话对象
        """
        conv_meta = dict(meta)
        if title:
            conv_meta["title"] = title
        return self._engine._store.create_conversation(
            agent_type=self._config.agent_type,
            meta=conv_meta,
        )
