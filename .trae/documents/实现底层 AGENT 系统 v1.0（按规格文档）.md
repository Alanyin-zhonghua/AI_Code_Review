# 目标与范围
- 按 `agent_product_book_v_0.md` 完整落地 v1.0 内核：domain、providers（仅 Kimi）、agents、infrastructure/storage、config、prompts、api、tests。
- 支持单用户、本地 IDE 助手场景，JSON 持久化，会话 Git 树结构，非流式对话，基础工具框架（先实现 read_file）。

## 技术选型与约束
- 语言/运行环境：Python 3.11，Windows。
- 依赖：`httpx`、`pydantic`、`pytest`；其余尽量走标准库。
- 配置：`.env` + `Settings`（不硬编码），禁用系统代理（`trust_env=False`）。
- 日志：JSON 行日志到 `logs/agent.log`，支持内容脱敏开关。

## 目录与文件
- 根目录：`agent_core/` 按文档 1 节结构创建所有模块与占位文件；`tests/` 提供 4 个核心测试文件。
- 关键文件：
  - `config/settings.py`：`Settings`（含 `kimi_api_key`、`http_timeout`、`storage_root` 等）。
  - `domain/models.py`：`ChatMessage / ChatRequest / ChatResult` 等；用 `dataclasses`。
  - `domain/conversation.py`：`Conversation / MessageRecord / ConversationStore(Protocol)`。
  - `domain/exceptions.py`：统一异常族。
  - `infrastructure/storage/json_store.py`：`JsonConversationStore`（`.storage/conversations/{id}` 结构，安全写）。
  - `providers/registry.py`：`KIMI_CONFIG` 与模型映射。
  - `providers/kimi_client.py`：`KimiClient.chat(req)` 调用 Moonshot（非流式）。
  - `tools/definitions.py`、`tools/executor.py`：Tool 数据结构与执行器；先接入 `read_file`。
  - `agents/base_agent.py`：`AgentEngine.run_step(...)` 打通完整链路（不含工具循环）。
  - `prompts/zh/ide_helper_system.md`：加载用系统提示词（文本由人类维护）。
  - `api/service.py`：`run_ide_chat(...)` 对外函数。

## 实施阶段
1. 配置与骨架
   - 建立目录与空文件；实现 `Settings`+`.env` 加载。
2. 领域层
   - 完成 models、conversation、exceptions；提供存取模型与协议。
3. 存储层
   - 实现 `JsonConversationStore`：创建会话、追加消息、列出消息；路径用 `pathlib`；安全写临时文件+`os.replace`；IO 异常转业务异常。
4. Provider 接入
   - 完成 `registry.py`；实现 `KimiClient.chat`：构建 payload、发起请求、错误与限流处理、解析为 `ChatResult`。
5. Agent 引擎
   - `AgentEngine`：路径构建与裁剪（最近 20 条）、加载系统提示词、调用 Provider、写回两条消息、返回结果。
6. 工具框架
   - 定义 Tool 结构与 `ToolExecutor`；实现 `read_file`（限制相对路径、禁止越权）。
7. 对外接口
   - `api/service.py` 暴露 `run_ide_chat`，含默认单例 store/agent。
8. 测试与验证
   - `tests/`：
     - `test_json_store.py`：创建/写入/读取验证与异常路径。
     - `test_kimi_client.py`：`httpx.Client.post` mock，覆盖正常与错误/429。
     - `test_conversation.py`：模型转换与协议一致性检查。
     - `test_agent_flow.py`：用 fake provider 验证路径裁剪与写回逻辑。

## 关键实现要点
- 会话树：`MessageRecord.parent_id/depth` 管理分叉；构建路径时回溯并反转；裁剪 `MAX_CONTEXT_MSGS=20`。
- Provider 抽象：`ProviderClient(Protocol)`；Agent 仅依赖协议与逻辑模型名。
- 安全写：消息落盘先写临时文件并原子替换；异常统一抛 `BusinessError` 子类。
- 网络：`httpx.Client(..., trust_env=False)`；`Authorization: Bearer ${kimi_api_key}`；国内网络。
- 日志：结构化 JSON；记录 trace/ids 与 token 用量（如有）；支持 `AGENT_LOG_REDACT_CONTENT` 开关。

## 安全与合规
- 不记录/输出明文密钥；敏感字段按开关脱敏或哈希。
- 工具路径校验：拒绝 `..` 与绝对路径；只读。
- 不使用系统代理变量；仅国内端点。

## 交付与验收
- 能在本地通过 `run_ide_chat(...)` 完成一次端到端调用（Provider 可用或用 mock）。
- 所有测试用例通过；日志生成正常；`.storage` 结构与消息 JSONL 符合规范。

## 后续扩展（占位）
- `sqlite_store.py` 接口骨架与 TODO。
- 工具循环（最多 5 轮）机制预留。
- 多 Provider 可扩展注册表机制保留。

## 开发准备
- 依赖管理：优先 `poetry`；可选 `pip + requirements.txt`。
- 最小依赖集合：`httpx`, `pydantic`, `pytest`；其余走标准库。

请确认以上计划后，我将开始按阶段实现、验证，并提供测试结果与使用示例。