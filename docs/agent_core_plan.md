# LangGraph Agent Integration Plan

## 1. 现状分析

- **LLM Provider 层**：目前只封装了 Kimi 与 GLM 客户端，通过 `agent_core/api/service.py` 的 `run_ide_chat` 暴露接口；工具调用能力由 `AgentEngine._run_with_tools` 负责，仍依赖模型在提示词中触发工具。
- **工具系统**：`agent_core/tools/executor.py` 提供 `read_file`/`list_files`/`search_code`/`propose_edit` 等只读工具，具有路径校验和缓存能力，但在 GUI 中需要手工输入参数，不够智能。
- **LangGraph**：项目里尚未使用，没有状态机/决策层，Agent 仅依赖单轮调用。

## 2. 状态设计

```python
class AgentState(TypedDict):
    messages: list[Dict[str, str]]   # 包含 role/content
    plan: str | None                 # 当前计划
    tool_results: list[dict]         # 历史工具调用结果
    pending_tool: dict | None        # agent_node 决定的下一次工具调用
    final_response: str | None       # 已生成的最终答复
    done: bool                       # 是否完成
    provider: str                    # 当前使用的 Provider
    model: str                       # 当前模型
```

messages 中将存储 user/assistant/tool 角色文本，方便随时转换为 ChatMessage 交给 Provider。

## 3. LangGraph 节点划分

1. **planner_node**（可选策略层）
   - 输入：`AgentState`
   - 作用：根据最新的用户消息/工具结果，请求 LLM 生成一段执行计划（字符串）。简版中可以直接总结用户需求。

2. **agent_node**（决策节点）
   - 作用：调用 LLM，请其在 JSON 中返回 `{"action": "tool"|"final", ...}`。
     - 当 action=tool 时，需包含 `tool_name`、`tool_args`、`thought`。
     - 当 action=final 时，包含最终回复文本。
   - 输出：
     - 若需调用工具，则在 state.pending_tool 中写入请求。
     - 若为 final，则设置 final_response、done。

3. **tool_node**（执行节点）
   - 作用：读取 state.pending_tool，调用工具封装（见第 4 节），写入执行结果、异常信息，并向 messages 附加 `role="tool"` 的消息。

4. **final_answer_node**
   - 作用：当 state.done 为 True 或 agent_node 直接给出回答时，整理 plan / tool_results / LLM 结果，输出用户可读回复，并结束流程。

图结构（文本形式）：

```
Start -> planner_node -> agent_node
agent_node --(tool)--> tool_node --> agent_node
agent_node --(final)--> final_answer_node --> END
```

## 4. 工具封装

在 `agent_core/flows/tools_interface.py` 中封装统一的 `ToolManager`：
- 初始化时复用 `ToolExecutor(default_tools(workspace_root))`。
- 暴露 `AVAILABLE_TOOLS`，每项含 name/description/parameters schema。
- 提供 `run_tool(name, args)`，内部完成参数解析、错误保护、安全写（对 write_file 采用临时文件 + rollback）。
- 所有异常都返回 `{"ok": False, "error": "..."}` 的结构，避免抛出。

## 5. LLM 调用方式

- 复用现有 Provider 客户端：借助 `create_provider()` 创建实例，构造 `ChatRequest`，发送 messages 列表。
- 为 planner/agent/final 节点准备专用 prompt，指导模型返回 JSON。
- 所有调用通过统一 helper `llm_complete(messages, system_prompt, provider_name, model_name)` 完成，方便日后替换。

## 6. 模块结构

```
agent_core/
  flows/
    __init__.py        # 导出 run_agent
    state.py           # AgentState 定义
    tools_interface.py # ToolManager 与工具 schema
    graph.py           # LangGraph 构建与节点实现
    runner.py          # run_agent 接口
```

`runner.run_agent(user_message, provider_name=None, model_name=None, history=None)`：
1. 构建 LangGraph（缓存 graph 对象）。
2. 初始化 State，messages 包含 user 输入，provider/model 来源于参数或默认配置。
3. 执行 graph.invoke(initial_state)，取返回的 final_response。

## 7. 示例与测试

- 在 `examples/lang_agent_demo.py` 编写简单示例，演示 run_agent 可以自动读取文件。
- （可选）添加 `tests/test_agent_smoke.py` 作为冒烟测试，Mock 工具执行结果。

该方案尽量复用现有 Provider/工具，并通过 LangGraph 提供明确的决策流程，后续 GUI 可以直接调用 `run_agent`，无需暴露底层工具表单。
