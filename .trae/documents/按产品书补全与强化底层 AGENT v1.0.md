````markdown
# 底层 AGENT 系统技术规格文档 v1.0  
> **用途：专供 AI 开发代理（如 Codex）据此自动实现代码。仅包含技术架构与实现指导，不包含业务/运营内容。**

---

## 0. 总体约束

1. **语言与运行环境**  
   - 编程语言：Python 3.11+  
   - 依赖管理：`poetry` 或 `pip` + `requirements.txt`（由上层工程自行决定）  
   - 操作系统：Windows

2. **使用场景**  
   - 单用户本地/个人项目使用，不存在多租户、多账号。  
   - 作为 IDE 内置 AI 助手和代码审查 Agent 的后端内核。

3. **模型与厂商**  
   - 仅接入：月之暗面（Moonshot）  
   - 模型固定：`kimi-k2-turbo-preview`  
   - 后续可能扩展其他模型；当前版本中抽象层必须为“多 provider 可扩展”设计，但只实现 Kimi。

4. **网络与代理**  
   - 默认不使用系统代理（如 Clash），HTTP 客户端需禁用 `HTTP_PROXY/HTTPS_PROXY` 等环境变量。  
   - 所有请求走国内网络。

5. **对话与上下文规则**  
   - 对话结构为 **Git 样式树**：每条消息有 `parent_id` 与 `depth`，可以从任意节点分叉。  
   - 每条消息具有 `version`，用于支持后续“编辑消息”的能力（当前实现中仅保留字段，不实现复杂版本管理）。  
   - 发给模型的上下文仅包含“当前路径上最近 20 条消息”（包括 system/user/assistant/tool）。  
   - 历史全部消息必须持久化保存（JSON / 未来 DB），用于回放和分叉。

6. **工具与文件操作**  
   - 支持 **只读工具**：如 `read_file` / `list_files` / `search_code`。  
   - 写操作采用 **安全写模式**：模型仅生成“修改建议/补丁”，实际写入由 IDE 或调用方确认后执行。

7. **日志**  
   - 必须为 **结构化日志**（JSON 行），包含：时间、级别、模块、trace_id、conversation_id、message_id、provider、耗时、token 数据等。  
   - 允许记录完整 prompt 与回复内容（本系统默认用于单人本地环境）；如环境变量 `AGENT_LOG_REDACT_CONTENT=true` 时需改为只记录前 N 字符 + 哈希。

8. **配置**  
   - 所有可变参数从 `.env` 或 `config.yaml` 中读取，不在代码中硬编码。  
   - 必须提供统一的 `Settings` 对象供各模块获取配置。

---

## 1. 目录结构与模块概览

建议项目根目录结构如下（AI 开发代理需按照该结构生成代码文件）：

```text
agent_core/
├── __init__.py
├── config/
│   ├── __init__.py
│   └── settings.py           # 读取 .env / config.yaml，暴露 Settings
├── domain/
│   ├── __init__.py
│   ├── models.py             # ChatMessage / ChatRequest / ChatResult 等统一数据模型
│   ├── conversation.py       # Conversation / Message / 会话树逻辑
│   └── exceptions.py         # 统一异常模型
├── infrastructure/
│   ├── __init__.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── json_store.py     # JSON 持久化实现 ConversationStore
│   │   └── sqlite_store.py   # 预留的 SQLite 实现（可仅放接口骨架）
│   └── logging/
│       ├── __init__.py
│       └── logger.py         # 结构化日志封装
├── providers/
│   ├── __init__.py
│   ├── base.py               # ProviderClient 协议、统一接口
│   ├── registry.py           # Provider & 模型配置（当前只含 kimi）
│   └── kimi_client.py        # 调用 kimi-k2-turbo-preview 的具体实现
├── tools/
│   ├── __init__.py
│   ├── definitions.py        # ToolDef / ToolCall / ToolResult 数据结构
│   └── executor.py           # ToolExecutor，含 read_file / list_files / search_code / propose_edit
├── agents/
│   ├── __init__.py
│   ├── base_agent.py         # Agent 引擎核心：对话路径构建、上下文裁剪、调用 provider、处理工具
│   └── ide_helper_agent.py   # 面向 IDE 助手的包装（可加载特定 system prompt）
├── prompts/
│   ├── __init__.py
│   └── zh/
│       └── ide_helper_system.md   # 系统提示词（固定文本，由人类编辑，不由 AI 修改源文件）
├── api/
│   ├── __init__.py
│   └── service.py            # 对外暴露的函数接口（非 HTTP）：如 run_ide_chat(...)
└── tests/
    ├── __init__.py
    ├── test_conversation.py
    ├── test_kimi_client.py
    ├── test_json_store.py
    └── test_agent_flow.py
```

AI 开发代理在实现代码时，应**优先保证 domain、providers、agents、infrastructure/storage 四个目录**按规范实现，其余模块（如 sqlite_store）可以保留占位实现与 TODO 注释。

---

## 2. 领域模型（domain）设计

### 2.1 ChatMessage / ChatRequest / ChatResult

在 `domain/models.py` 中定义统一数据结构，用 `dataclasses.dataclass` 或 `pydantic.BaseModel`（推荐 dataclass + 类型检查）。

#### 2.1.1 角色类型

```python
from dataclasses import dataclass, field
from typing import Literal, Optional, Any, Dict, List

Role = Literal["system", "user", "assistant", "tool", "tool_result"]
```

#### 2.1.2 ChatMessage

```python
@dataclass
class ChatMessage:
    role: Role
    content: str
    # 附加信息：如文件路径、选区位置、vendor、model、token 使用等
    meta: Dict[str, Any] = field(default_factory=dict)
    # 工具调用相关字段，仅当 role == "assistant" 时可能存在
    tool_calls: Optional[List["ToolCall"]] = None   # 引用 tools.definitions 中的 ToolCall
    tool_call_id: Optional[str] = None               # 当 role 为 tool/tool_result 时，标识对应调用
```

> 注意：`ToolCall` 类型需在运行时避免循环导入，可使用 `typing.TYPE_CHECKING` 或字符串注解。

#### 2.1.3 ChatRequest

```python
@dataclass
class ChatRequest:
    provider: str              # "kimi"
    model: str                 # 逻辑模型名，如 "ide-chat"
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: Optional[int] = None
    tools: Optional[List["ToolDef"]] = None    # 可选工具定义
    tool_choice: Literal["auto", "none", "required"] = "auto"
```

#### 2.1.4 ChatResult

```python
@dataclass
class ChatUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatChoice:
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


@dataclass
class ChatResult:
    provider: str
    model: str                 # 逻辑模型名
    choices: List[ChatChoice]
    usage: Optional[ChatUsage] = None
    raw: Optional[dict] = None # 厂商原始响应，用于调试/日志
```

### 2.2 Conversation / Message（会话树）

在 `domain/conversation.py` 中定义对话与消息结构，用于持久化存储。

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class Conversation:
    id: str
    title: str
    agent_type: str           # 如 "ide-helper"
    created_at: datetime
    updated_at: datetime
    meta: Dict[str, Any]


@dataclass
class MessageRecord:
    id: str
    conversation_id: str
    role: Role
    content: str
    parent_id: Optional[str]      # Git 树结构：指向上一条消息
    depth: int                    # 根节点 depth = 0，子节点 = parent.depth + 1
    version: int                  # 当前版本号，初始为 1
    created_at: datetime
    meta: Dict[str, Any]          # 如 {"filePath": "src/main.py", "model": "kimi-k2-turbo-preview"}
```

> 注意：`MessageRecord` 与 `ChatMessage` 语义相近但用于不同层：前者是**存储模型**，后者是**发给模型的消息模型**。AI 需要实现两者之间的转换函数。

### 2.3 ConversationStore 抽象接口

在 `domain/conversation.py` 中定义会话存储接口，供 JSON / SQLite 等实现：

```python
from typing import Protocol, Tuple


class ConversationStore(Protocol):
    """会话存储接口。所有上层代码只依赖此协议。"""

    def create_conversation(self, agent_type: str, meta: Dict[str, Any]) -> Conversation:
        ...

    def get_conversation(self, conversation_id: str) -> Conversation:
        ...

    def list_conversations(self) -> List[Conversation]:
        ...

    def add_message(self, message: MessageRecord) -> None:
        ...

    def get_message(self, message_id: str) -> MessageRecord:
        ...

    def list_messages(self, conversation_id: str) -> List[MessageRecord]:
        ...
```

AI 开发代理需在 `infrastructure/storage/json_store.py` 中提供一个实现类：`JsonConversationStore(ConversationStore)`。

### 2.4 统一异常模型

在 `domain/exceptions.py` 中定义异常基类与子类：

```python
class BusinessError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400, **extra):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra
        super().__init__(message)


class NetworkError(BusinessError):
    pass


class ApiError(BusinessError):
    pass


class RateLimitError(BusinessError):
    pass


class ValidationError(BusinessError):
    pass
```

异常主要用于：provider 调用失败、参数错误、存储层异常等；AI 实现时要在 providers & agents 中适当抛出这些异常。

---

## 3. 存储实现（infrastructure/storage）

### 3.1 JSON 存储格式

JSON 存储为当前主要实现，目录结构：

```text
.storage/
  conversations/
    {conversation_id}/
      meta.json
      messages.jsonl
```

#### 3.1.1 meta.json 示例

```json
{
  "id": "c-123",
  "title": "IDE 辅助会话",
  "agent_type": "ide-helper",
  "created_at": "2025-11-14T12:00:00Z",
  "updated_at": "2025-11-14T12:05:00Z",
  "meta": {
    "projectRoot": "/Users/you/project"
  }
}
```

#### 3.1.2 messages.jsonl 示例

每行一个 JSON 对象，表示一条 MessageRecord：

```json
{"id": "m1", "conversation_id": "c-123", "role": "system", "content": "你是...", "parent_id": null, "depth": 0, "version": 1, "created_at": "2025-11-14T12:00:00Z", "meta": {}}
{"id": "m2", "conversation_id": "c-123", "role": "user", "content": "帮我看下这段代码", "parent_id": "m1", "depth": 1, "version": 1, "created_at": "2025-11-14T12:01:00Z", "meta": {"filePath": "main.py"}}
{"id": "m3", "conversation_id": "c-123", "role": "assistant", "content": "这段代码...", "parent_id": "m2", "depth": 2, "version": 1, "created_at": "2025-11-14T12:01:03Z", "meta": {"provider": "kimi"}}
```

### 3.2 JsonConversationStore 实现要点

在 `json_store.py` 中实现 `ConversationStore`：

- `create_conversation(agent_type, meta)`：
  - 生成 `conversation_id`（使用 `uuid4()`）。  
  - 创建目录 `.storage/conversations/{conversation_id}`。  
  - 写入 `meta.json`。

- `add_message(message)`：
  - 将 `message` 转成 dict，再 `json.dumps` 写入 `messages.jsonl` 追加行。  
  - 更新 `meta.json` 中的 `updated_at`。

- `list_messages(conversation_id)`：
  - 打开 `messages.jsonl`，逐行解析为 `MessageRecord`。  
  - 返回列表（按 `created_at` 排序）。

AI 必须在实现时注意：

- 使用 `pathlib.Path` 操作路径。  
- 所有写操作需要捕获 IO 异常并转为 `BusinessError` 或子类。  
- 写文件时建议采用：写入临时文件 → `os.replace` 的方式，确保不会产生半写入状态。

---

## 4. Provider 接入（providers）—— Kimi

### 4.1 ProviderClient 协议

在 `providers/base.py` 中定义统一协议：

```python
from typing import Protocol
from domain.models import ChatRequest, ChatResult


class ProviderClient(Protocol):
    name: str

    def chat(self, req: ChatRequest) -> ChatResult:
        """执行一次非流式对话调用。异常使用 domain.exceptions 中定义的类型。"""
        ...
```

### 4.2 registry.py 中的 Kimi 配置

```python
from dataclasses import dataclass
from typing import Dict


@dataclass
class ModelConfig:
    logical_name: str          # 如 "ide-chat"
    provider_model: str        # "kimi-k2-turbo-preview"
    max_tokens: int
    default_temperature: float


@dataclass
class ProviderConfig:
    name: str                  # "kimi"
    base_url: str
    models: Dict[str, ModelConfig]


KIMI_CONFIG = ProviderConfig(
    name="kimi",
    base_url="https://api.moonshot.cn/v1",
    models={
        "ide-chat": ModelConfig(
            logical_name="ide-chat",
            provider_model="kimi-k2-turbo-preview",
            max_tokens=8192,
            default_temperature=0.7,
        )
    },
)
```

### 4.3 kimi_client.py 实现

- 使用 `httpx` or `requests`（推荐 httpx）。  
- 禁用系统代理：`trust_env=False`。  
- 从 `Settings` 读取 `KIMI_API_KEY` 等配置。

伪代码结构：

```python
import httpx
from domain.models import ChatRequest, ChatResult, ChatMessage, ChatChoice, ChatUsage
from domain.exceptions import NetworkError, ApiError, RateLimitError
from .registry import KIMI_CONFIG


class KimiClient:
    name = "kimi"

    def __init__(self, settings):
        self._settings = settings

    def chat(self, req: ChatRequest) -> ChatResult:
        model_cfg = KIMI_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg)

        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                resp = client.post(
                    f"{KIMI_CONFIG.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.kimi_api_key}",
                    },
                )
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e)) from e

        if resp.status_code == 429:
            # 在 Agent 层统一处理 RateLimit；此处只抛异常
            raise RateLimitError(code="RATE_LIMIT", message="Kimi rate limit")

        if resp.status_code >= 400:
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)

        data = resp.json()
        return self._parse_response(data, req)

    def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig) -> dict:
        msgs = [
            {"role": m.role, "content": m.content}
            for m in req.messages
        ]
        payload = {
            "model": model_cfg.provider_model,
            "messages": msgs,
            "temperature": req.temperature or model_cfg.default_temperature,
            "max_tokens": req.max_tokens or model_cfg.max_tokens,
        }
        # 如需工具能力，可在此处加入 tools/ tool_choice 适配
        return payload

    def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
        choices: list[ChatChoice] = []
        for i, ch in enumerate(data.get("choices", [])):
            msg = ch["message"]
            cm = ChatMessage(role=msg["role"], content=msg.get("content") or "")
            choices.append(ChatChoice(index=i, message=cm, finish_reason=ch.get("finish_reason")))

        usage_raw = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return ChatResult(
            provider="kimi",
            model=req.model,
            choices=choices,
            usage=usage,
            raw=data,
        )
```

> AI 实现时需根据 Moonshot/Kimi 的实际 API 字段微调字段名，但保持 ChatResult 接口不变。

---

## 5. 工具系统（tools）

### 5.1 数据结构定义（definitions.py）

```python
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class ToolParam:
    name: str
    description: str
    required: bool
    schema: Dict[str, Any]     # 简化版 JSON Schema


@dataclass
class ToolDef:
    name: str
    description: str
    params: Dict[str, ToolParam]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    content: str               # 文本结果；后续可扩展为结构化数据
```

### 5.2 ToolExecutor（executor.py）

ToolExecutor 负责执行工具逻辑，并提供简易缓存（可选）。

```python
from typing import Callable, Dict
from .definitions import ToolCall, ToolResult

ToolFunc = Callable[[Dict[str, Any]], str]


class ToolExecutor:
    def __init__(self, tools: Dict[str, ToolFunc]):
        self._tools = tools
        self._cache: Dict[tuple, str] = {}

    def execute(self, call: ToolCall) -> ToolResult:
        key = (call.name, tuple(sorted(call.arguments.items())))
        if key in self._cache:
            result = self._cache[key]
        else:
            func = self._tools.get(call.name)
            if not func:
                result = f"Tool {call.name} not registered"
            else:
                result = func(call.arguments)
            self._cache[key] = result
        return ToolResult(call_id=call.id, content=result)
```

### 5.3 必需工具实现建议

AI 需至少提供以下工具函数实现（具体代码可在 executor 模块或单独文件中）：

1. `read_file`  
   - 参数：`{"path": str}`，相对项目根目录。  
   - 行为：读取文本文件内容，返回字符串。  
   - 须限制路径，防止越权（不允许 `..` 跨目录）。

2. `list_files`  
   - 参数：`{"directory": str, "pattern": Optional[str]}`。  
   - 行为：列举目录下的文件，可支持简单通配符。  

3. `search_code`  
   - 参数：`{"query": str, "max_results": int}`。  
   - 行为：在项目中搜索包含 query 的文件行，返回简要匹配信息文本。

4. `propose_edit`  
   - 参数：`{"path": str, "range": [start_line, end_line], "new_content": str}`。  
   - 行为：**仅生成 patch 描述**（例如 unified diff），不直接写文件；真实写入由 IDE 或上层确认后再执行。

---

## 6. Agent 引擎（agents/base_agent.py）

### 6.1 职责

- 根据 `conversation_id` 和（可选）`focus_message_id` 决定对话路径。  
- 构造当前路径上的消息链（Git 树回溯 → 反转）。  
- 截取最近 20 条消息并加上 system prompt，构造 `ChatRequest`。  
- 调用 Kimi Provider，得到 `ChatResult`。  
- 将 user/assistant 消息写回 `ConversationStore`。  
- 处理工具调用（如启用工具）时执行“模型 → tool_calls → 工具执行 → 再模型”的循环，最多 5 轮。

### 6.2 关键函数签名

建议在 `base_agent.py` 中实现以下函数/类：

```python
from dataclasses import dataclass
from typing import Optional, List
from domain.conversation import ConversationStore, MessageRecord, Conversation
from domain.models import ChatMessage, ChatRequest, ChatResult
from tools.executor import ToolExecutor
from providers.kimi_client import KimiClient


@dataclass
class AgentConfig:
    agent_type: str                 # "ide-helper"
    provider: str                   # "kimi"
    model: str                      # "ide-chat"
    enable_tools: bool = False


class AgentEngine:
    def __init__(
        self,
        store: ConversationStore,
        provider_client: KimiClient,
        tool_executor: Optional[ToolExecutor] = None,
        config: Optional[AgentConfig] = None,
    ):
        ...

    def run_step(
        self,
        conversation_id: Optional[str],
        user_input: str,
        meta: dict,
        focus_message_id: Optional[str] = None,
    ) -> tuple[Conversation, MessageRecord, MessageRecord]:
        """执行一次 Agent 对话步骤。
        返回: (conversation, user_message_record, assistant_message_record)
        """
        ...
```

### 6.3 路径构建与裁剪逻辑

AI 需要实现：

1. 若 `conversation_id` 为空：
   - 调用 `store.create_conversation(agent_type, meta)` 创建新会话。

2. 确定“叶子节点”：
   - 若 `focus_message_id` 非空：以该消息为叶子。  
   - 否则：使用该会话中最新的消息（时间最大）。

3. 构造路径：

```python
def build_path(store: ConversationStore, leaf: MessageRecord) -> List[MessageRecord]:
    path: List[MessageRecord] = []
    current = leaf
    while current is not None:
        path.append(current)
        if current.parent_id is None:
            break
        current = store.get_message(current.parent_id)
    path.reverse()
    return path
```

4. 裁剪路径到最近 20 条：

```python
MAX_CONTEXT_MSGS = 20

if len(path) > MAX_CONTEXT_MSGS:
    path = path[-MAX_CONTEXT_MSGS:]
```

5. 将 `MessageRecord` 转为 `ChatMessage`，并在最前面插入最新的 system prompt：

```python
system_prompt = prompts.load_system_prompt(agent_type)
chat_messages = [ChatMessage(role="system", content=system_prompt)]
for mr in path:
    chat_messages.append(ChatMessage(role=mr.role, content=mr.content, meta=mr.meta))
chat_messages.append(ChatMessage(role="user", content=user_input, meta=meta))
```

6. 构造 `ChatRequest` 并调用 provider：

```python
req = ChatRequest(
    provider="kimi",
    model=self._config.model,
    messages=chat_messages,
    temperature=0.3,
)

result: ChatResult = self._provider_client.chat(req)
assistant_msg = result.choices[0].message
```

7. 将新消息写回存储：

```python
user_rec = MessageRecord(..., role="user", content=user_input, parent_id=leaf.id if leaf else None, depth=(leaf.depth + 1 if leaf else 0), version=1, ...)
assistant_rec = MessageRecord(..., role="assistant", content=assistant_msg.content, parent_id=user_rec.id, depth=user_rec.depth + 1, version=1, ...)

store.add_message(user_rec)
store.add_message(assistant_rec)
```

8. 返回结果供上层（IDE 插件等）显示。

### 6.4 工具循环（可选）

当 `enable_tools=True` 且模型支持工具调用时，AgentEngine 需要：

- 检查 `assistant_msg.tool_calls`：若存在，则执行工具，并将 `tool` / `tool_result` 消息追加到对话，再发起下一轮模型调用。  
- 限制最大循环次数为 5；超过时终止工具调用，要求模型给出总结性回答。

> 目前文档重点在对话与结构，工具调用循环可以保留 TODO 注释，由未来版本实现。

---

## 7. 配置与提示词加载（config & prompts）

### 7.1 Settings 对象

在 `config/settings.py` 中定义：

```python
from pydantic import BaseSettings


class Settings(BaseSettings):
    kimi_api_key: str
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    http_timeout: float = 30.0
    storage_root: str = ".storage"
    log_dir: str = "logs"
    log_redact_content: bool = False

    class Config:
        env_file = ".env"


settings = Settings()
```

所有模块通过依赖注入或从 `config.settings` 导入 `settings` 使用。

### 7.2 提示词加载

在 `prompts/__init__.py` 中实现：

```python
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


def load_system_prompt(agent_type: str, locale: str = "zh") -> str:
    # 当前仅实现 ide-helper
    fname = PROMPTS_DIR / locale / "ide_helper_system.md"
    return fname.read_text(encoding="utf-8")
```

> 提示词文本不由 AI 自动修改；如需更新，需人工编辑文件并提交 Git。

---

## 8. 日志实现（infrastructure/logging/logger.py）

AI 需提供一个简单的结构化日志封装，基于标准库 `logging`：

```python
import json
import logging
from pathlib import Path
from datetime import datetime
from config.settings import settings


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("agent_core")
    logger.setLevel(logging.INFO)
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    fh.setLevel(logging.INFO)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            }
            extra = getattr(record, "extra", None)
            if isinstance(extra, dict):
                payload.update(extra)
            return json.dumps(payload, ensure_ascii=False)

    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)
    return logger


logger = setup_logger()
```

使用示例：

```python
from infrastructure.logging.logger import logger

logger.info("provider request", extra={"extra": {"provider": "kimi", "conversation_id": cid}})
```

> 注意：标准库 logging 对 `extra` 的处理较特殊，上述示例仅为方向性，AI 在实现时可根据习惯调整，但必须保证输出为 JSON 行。

---

## 9. 对外接口（api/service.py）

为了方便 IDE 或其他上层集成，提供一个简单函数接口：

```python
from typing import Optional, Dict, Any
from domain.conversation import ConversationStore
from providers.kimi_client import KimiClient
from agents.base_agent import AgentEngine, AgentConfig
from infrastructure.storage.json_store import JsonConversationStore


_store: ConversationStore | None = None
_agent: AgentEngine | None = None


def get_default_agent() -> AgentEngine:
    global _store, _agent
    if _store is None:
        _store = JsonConversationStore(root=settings.storage_root)
    if _agent is None:
        provider = KimiClient(settings)
        cfg = AgentConfig(agent_type="ide-helper", provider="kimi", model="ide-chat")
        _agent = AgentEngine(store=_store, provider_client=provider, tool_executor=None, config=cfg)
    return _agent


def run_ide_chat(
    user_input: str,
    conversation_id: Optional[str] = None,
    focus_message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    agent = get_default_agent()
    conv, user_rec, assistant_rec = agent.run_step(
        conversation_id=conversation_id,
        user_input=user_input,
        meta=meta or {},
        focus_message_id=focus_message_id,
    )
    return {
        "conversation_id": conv.id,
        "user_message": {
            "id": user_rec.id,
            "content": user_rec.content,
        },
        "assistant_message": {
            "id": assistant_rec.id,
            "content": assistant_rec.content,
        },
    }
```

> 上层（IDE 插件）可以反复调用 `run_ide_chat`，传入 `conversation_id` 与可选的 `focus_message_id` 实现“从某节点分叉”。

---

## 10. AI 开发代理实现顺序建议

为便于 AI 自动实现，建议按以下顺序生成代码并逐步补全：

1. **config/settings.py**：实现 Settings 加载 `.env`。  
2. **domain/models.py**：实现 ChatMessage / ChatRequest / ChatResult。  
3. **domain/conversation.py**：实现 Conversation / MessageRecord / ConversationStore 协议。  
4. **domain/exceptions.py**：实现异常类。  
5. **infrastructure/storage/json_store.py**：实现 JsonConversationStore。  
6. **prompts/**：创建 `zh/ide_helper_system.md`，内容可由人类提供。  
7. **providers/registry.py & kimi_client.py**：实现 KimiClient。  
8. **tools/definitions.py & executor.py**：实现基础工具结构与简单执行器（可以先只实现 read_file）。  
9. **agents/base_agent.py**：实现 AgentEngine.run_step（不带工具循环，先打通基础链路）。  
10. **api/service.py**：实现 run_ide_chat 对外接口。  
11. **tests/**：为核心模块编写基础单元测试：
    - JsonConversationStore 创建/写入/读取。  
    - KimiClient.chat mock 测试。  
    - AgentEngine.run_step 使用 fake provider 测试路径与存储行为。

当上述步骤完成后，该系统即可作为一个可调用的底层 AGENT 内核，供 IDE、脚本、或其他上层系统直接集成。
````

