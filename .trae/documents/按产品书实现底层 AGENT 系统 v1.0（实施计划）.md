# 目标与范围
- 按《agent_product_book_v_0.md》落地可运行的底层 AGENT 内核：domain、providers（仅 Kimi）、agents、infrastructure/storage、config、prompts、api、tests。
- 场景：单用户本地 IDE 助手与代码审查；JSON 持久化；非流式对话；Git 树结构会话；只读工具。

## 技术与依赖
- Python 3.11+（Windows）。
- 依赖：`httpx`、`pydantic`、`pytest`；尽量使用标准库。
- 配置加载：`.env`（键：`KIMI_API_KEY`、可选 `AGENT_LOG_REDACT_CONTENT=true`）。
- 网络：禁用系统代理（`trust_env=false`），国内端点。

## 目录与模块（按产品书）
- `agent_core/config/settings.py`：`Settings` 统一配置对象。
- `agent_core/domain/models.py`：`ChatMessage/ChatRequest/ChatResult` 等数据模型。
- `agent_core/domain/conversation.py`：`Conversation/MessageRecord/ConversationStore(Protocol)`。
- `agent_core/domain/exceptions.py`：统一异常模型。
- `agent_core/infrastructure/storage/json_store.py`：JSON 会话存储实现（安全写）。
- `agent_core/infrastructure/logging/logger.py`：结构化 JSON 行日志。
- `agent_core/providers/base.py`：`ProviderClient` 协议。
- `agent_core/providers/registry.py`：`KIMI_CONFIG` 模型映射。
- `agent_core/providers/kimi_client.py`：Kimi 非流式对话实现。
- `agent_core/tools/definitions.py` 与 `executor.py`：工具数据结构与执行器（先实现 `read_file`）。
- `agent_core/agents/base_agent.py`：`AgentEngine.run_step` 打通调用链（含上下文裁剪）。
- `agent_core/prompts/zh/ide_helper_system.md`：系统提示词文件加载。
- `agent_core/api/service.py`：对外 `run_ide_chat(...)` 函数。
- `agent_core/tests/`：四个核心测试文件。

## 实施里程碑
### M1：项目骨架与配置
1. 创建目录与空文件，按书中结构落地。
2. 完成 `Settings` 与 `.env` 加载，暴露全局 `settings`。

### M2：领域模型与会话协议
1. 编写 `models.py`（dataclasses）。
2. 编写 `conversation.py`：`Conversation/MessageRecord` 与 `ConversationStore(Protocol)`。
3. 编写 `exceptions.py`。

### M3：持久化存储（JSON）
1. `JsonConversationStore`：创建会话、追加消息、列出消息、获取消息。
2. 使用 `pathlib.Path` 与安全写（临时文件 + `os.replace`）。
3. IO 异常统一转业务异常。

### M4：Provider 接入（Kimi）
1. `registry.py` 配置 `KIMI_CONFIG`。
2. `KimiClient.chat(req)`：构建 payload，禁用代理，异常与限流处理，解析为 `ChatResult`。

### M5：工具框架
1. 定义 `ToolParam/ToolDef/ToolCall/ToolResult`。
2. `ToolExecutor`：缓存与执行；实现 `read_file`（只读，路径校验）。

### M6：Agent 引擎
1. `AgentEngine`：构建路径（回溯与反转）、裁剪最近 20 条、加载系统提示词、调用 Provider。
2. 将 user/assistant 消息写回存储并返回结构。

### M7：对外接口与提示词
1. `prompts` 加载函数；添加中文系统提示词文件。
2. `api/service.py`：单例 `get_default_agent()` 与 `run_ide_chat(...)`。

### M8：测试与验证
1. `test_json_store.py`：创建/写入/读取与异常路径。
2. `test_kimi_client.py`：Mock `httpx.Client.post` 覆盖正常与 429/4xx。
3. `test_conversation.py`：模型存在性与基本属性断言。
4. `test_agent_flow.py`：Fake Provider 验证路径裁剪与写回。

## 验收标准
- `pytest -q agent_core/tests` 全部通过。
- 设置真实 `KIMI_API_KEY` 后能成功调用一次，或在无密钥时 Fake Provider 测试通过。
- `.storage` 目录结构符合规范，日志为 JSON 行且可选脱敏。

## 安全与合规
- 不记录明文密钥；脱敏可开启。
- 工具只读与路径越权防护；不允许 `..` 与绝对路径。
- 禁用系统代理变量；所有请求国内网络。

## 后续扩展
- 工具扩展：`list_files`、`search_code`、`propose_edit`（生成补丁）。
- Agent 工具循环与限流重试（最多 5 轮）。
- `sqlite_store.py` 占位接口与 TODO。

## 执行与交付
- 我将按上述里程碑依次实现并自测，最后提交使用示例与测试报告。请确认后我立即开始实施。