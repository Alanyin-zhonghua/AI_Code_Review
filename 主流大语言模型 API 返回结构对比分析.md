# 主流大语言模型 API 返回结构对比分析

## 概述

为了构建一个统一的 Agent 接口，理解不同大语言模型（LLM）API 的返回结构至关重要。目前，主流的中文 LLM 厂商，如 Kimi (Moonshot AI)、GLM (智谱 AI) 和 Deepseek (深度求索)，其 **Chat Completion** 接口（通常为 `/v1/chat/completions` 或 `/paas/v4/chat/completions`）的非流式（Non-Streaming）返回结构都高度兼容 **OpenAI** 的格式。

这种兼容性为构建统一接口提供了极大的便利，开发者可以基于 OpenAI 的标准结构进行封装，只需处理少数模型特有的扩展字段即可。

## 标准化 JSON 返回结构（基于 OpenAI 兼容格式）

以下是这三个模型共有的或遵循 OpenAI 标准的 JSON 核心结构：

| 字段名 | 类型 | 描述 | 来源模型 |
| :--- | :--- | :--- | :--- |
| `id` | string | 本次 API 请求的唯一标识符。 | Kimi, GLM, Deepseek |
| `object` | string | 对象的类型，非流式响应通常为 `"chat.completion"`。 | Kimi, Deepseek |
| `created` | integer | 创建响应时的 Unix 时间戳（秒）。 | Kimi, GLM, Deepseek |
| `model` | string | 用于生成响应的模型 ID。 | Kimi, GLM, Deepseek |
| `choices` | array | 包含模型生成结果的列表。 | Kimi, GLM, Deepseek |
| `choices[].index` | integer | 结果列表中的索引。 | Kimi, GLM, Deepseek |
| `choices[].message` | object | 模型的回复消息对象。 | Kimi, GLM, Deepseek |
| `choices[].message.role` | string | 消息的角色，通常为 `"assistant"`。 | Kimi, GLM, Deepseek |
| `choices[].message.content` | string | 模型生成的文本内容。 | Kimi, GLM, Deepseek |
| `choices[].finish_reason` | string | 模型停止生成的原因（如 `"stop"`, `"length"`, `"tool_calls"`）。 | Kimi, GLM, Deepseek |
| `usage` | object | 本次请求的 Token 使用情况统计。 | Kimi, GLM, Deepseek |
| `usage.prompt_tokens` | integer | 输入提示词消耗的 Token 数。 | Kimi, GLM, Deepseek |
| `usage.completion_tokens` | integer | 模型生成回复消耗的 Token 数。 | Kimi, GLM, Deepseek |
| `usage.total_tokens` | integer | 总消耗 Token 数 (`prompt_tokens` + `completion_tokens`)。 | Kimi, GLM, Deepseek |

## 模型特有字段及扩展

虽然核心结构一致，但各模型为了提供额外功能或信息，会添加一些特有字段。

### 1. Kimi (Moonshot AI) 特有字段 [1]

Kimi 的结构非常精简，主要是在 `usage` 字段中进行了扩展：

| 字段名 | 类型 | 描述 | 路径 |
| :--- | :--- | :--- | :--- |
| `usage.cached_tokens` | integer | 缓存命中的 Token 数量，用于支持自动缓存的模型。 | `usage` |

### 2. Deepseek (深度求索) 特有字段 [2]

Deepseek 的非流式返回结构与 OpenAI 标准高度一致，目前没有发现显著的非标准顶级字段。

### 3. GLM (智谱 AI) 特有字段 [3]

GLM 的返回结构包含较多扩展字段，以支持其多模态、联网搜索和工具调用等高级功能：

| 字段名 | 类型 | 描述 | 路径 |
| :--- | :--- | :--- | :--- |
| `request_id` | string | 智谱 AI 平台侧的请求 ID，用于追踪。 | 顶级字段 |
| `choices[].message.reasoning_content` | string | 模型在生成回复前的思考过程（如果启用）。 | `choices[].message` |
| `choices[].message.audio` | object | 多模态响应中的音频信息（如果启用）。 | `choices[].message` |
| `video_result` | array | 视频生成结果的 URL 列表（如果启用视频生成）。 | 顶级字段 |
| `web_search` | array | 联网搜索结果的详细信息（如果启用联网搜索）。 | 顶级字段 |
| `content_filter` | array | 内容安全过滤结果。 | 顶级字段 |
| `usage.prompt_tokens_details` | object | 提示词 Token 的详细信息，可能包含 `cached_tokens`。 | `usage` |

## 统一接口设计建议

基于上述分析，建议您的 Agent 接口设计遵循以下原则：

1.  **以 OpenAI 结构为基准：** 将所有模型的响应转换为一个内部标准结构，该结构应包含 OpenAI 格式的所有核心字段。
2.  **抽象 `message.content`：** 这是所有模型最核心的输出，应作为统一接口的主要返回内容。
3.  **统一 Token 统计：** 确保能从所有模型的 `usage` 字段中提取 `prompt_tokens`、`completion_tokens` 和 `total_tokens`。
4.  **处理扩展字段：**
    *   对于 Kimi 和 Deepseek，它们与 OpenAI 兼容性极高，可以直接映射。
    *   对于 GLM 等包含额外信息的模型，可以将 `web_search`、`video_result` 等信息作为可选的元数据（Metadata）字段，统一存储在 Agent 接口的响应中，供需要时使用。

## 原始 JSON 结构示例

为了方便参考，以下是各模型非流式 Chat Completion 接口的典型返回结构（已去除部分冗余或空值）：

### Kimi (Moonshot AI) 示例 [1]

```json
{
    "id": "cmpl-04ea926191a14749b7f2c7a48a68abc6",
    "object": "chat.completion",
    "created": 1698999496,
    "model": "kimi-k2-turbo-preview",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": " 你好，李雷！1+1等于2。如果你有其他问题，请随时提问！"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 19,
        "completion_tokens": 21,
        "total_tokens": 40,
        "cached_tokens": 10 
    }
}
```

### Deepseek (深度求索) 示例 [2]

Deepseek 的结构与 Kimi 类似，遵循 OpenAI 标准。

```json
{
    "id": "chatcmpl-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "deepseek-chat",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "你好！我是深度求索大模型，很高兴为您服务。"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 15,
        "total_tokens": 25
    }
}
```

### GLM (智谱 AI) 示例 [3]

GLM 的结构更复杂，包含更多扩展字段。

```json
{
  "id": "1234567890",
  "request_id": "req-1234567890abcdef",
  "created": 1700000000,
  "model": "glm-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！我是智谱清言大模型，很高兴为您服务。",
        "reasoning_content": "模型思考过程...",
        "tool_calls": [
          // Tool Call 结构
        ]
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 15,
    "total_tokens": 25,
    "prompt_tokens_details": {
      "cached_tokens": 5
    }
  },
  "video_result": [
    // 视频结果列表
  ],
  "web_search": [
    // 联网搜索结果列表
  ],
  "content_filter": [
    // 内容过滤结果
  ]
}
```

## 参考文献

[1] Moonshot AI 开放平台 - Kimi 大模型API 服务. *platform.moonshot.cn* [https://platform.moonshot.cn/docs/api/chat]
[2] DeepSeek API Docs - 对话补全. *api-docs.deepseek.com* [https://api-docs.deepseek.com/zh-cn/api/create-chat-completion]
[3] 智谱AI开放文档 - 对话补全. *zhipu-ef7018ed.mintlify.app* [https://zhipu-ef7018ed.mintlify.app/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8]
