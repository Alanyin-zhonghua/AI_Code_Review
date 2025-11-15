# 多厂商Provider集成指南

本文档说明如何为Agent Core系统添加新的LLM Provider，特别是如何处理各厂商返回的JSON响应格式。

## 目录

1. [Provider架构概述](#provider架构概述)
2. [添加新Provider的步骤](#添加新provider的步骤)
3. [JSON解析核心要点](#json解析核心要点)
4. [常见厂商响应格式](#常见厂商响应格式)
5. [实现示例](#实现示例)
6. [测试指南](#测试指南)

## Provider架构概述

Agent Core系统采用适配器模式处理不同LLM Provider：

```
AgentEngine (统一业务逻辑)
    ↓
ProviderClient (统一接口)
    ↓
具体Provider实现 (KimiClient, OpenAIClient, ...)
```

### 核心接口

所有Provider必须实现<mcfile name="ProviderClient" path="z:\AI_Code_Review\agent_core\providers\base.py"></mcfile>协议：

```python
class ProviderClient(Protocol):
    """LLM Provider 客户端协议。"""
    name: str
    
    def chat(self, req: ChatRequest) -> ChatResult:
        ...
```

### 数据模型

- <mcfile name="ChatRequest" path="z:\AI_Code_Review\agent_core\domain\models.py"></mcfile>: 统一的请求格式
- <mcfile name="ChatResult" path="z:\AI_Code_Review\agent_core\domain\models.py"></mcfile>: 统一的响应格式
- <mcfile name="ChatMessage" path="z:\AI_Code_Review\agent_core\domain\models.py"></mcfile>: 统一的消息格式

## 添加新Provider的步骤

### 1. 创建Provider客户端文件

在`agent_core/providers/`目录下创建新文件，例如`openai_client.py`:

```python
"""OpenAI Provider 适配器。

本模块负责：
1. 接收统一的 ChatRequest。
2. 将其转换为 OpenAI API 请求格式。
3. 调用 HTTP 接口并处理网络/API 异常。
4. 将响应 JSON 解析为统一的 ChatResult / ChatMessage 结构。
"""

import httpx
import json
from typing import Any, Dict, List

from agent_core.domain.models import ChatRequest, ChatResult, ChatMessage, ChatChoice, ChatUsage
from agent_core.domain.exceptions import NetworkError, ApiError, RateLimitError, ValidationError
from agent_core.providers.registry import OPENAI_CONFIG, ModelConfig
from agent_core.tools.definitions import ToolDef, ToolCall


class OpenAIClient:
    """OpenAI 提供方客户端实现。"""
    
    name = "openai"
    
    def __init__(self, settings):
        self._settings = settings
    
    def chat(self, req: ChatRequest) -> ChatResult:
        """执行一次非流式对话调用。"""
        # 1. 验证配置
        if not getattr(self._settings, "openai_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="OPENAI_API_KEY not set")
        
        # 2. 获取模型配置
        model_cfg = OPENAI_CONFIG.models[req.model]
        
        # 3. 构建请求payload
        payload = self._build_payload(req, model_cfg)
        
        # 4. 发送HTTP请求
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "openai_base_url", None) or OPENAI_CONFIG.base_url
                resp = client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))
        
        # 5. 处理HTTP错误
        if resp.status_code == 429:
            raise RateLimitError(code="RATE_LIMIT", message="OpenAI rate limit")
        if resp.status_code >= 400:
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
        
        # 6. 解析响应
        data = resp.json()
        return self._parse_response(data, req)
    
    # 其他方法实现...
```

### 2. 实现请求转换

```python
def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig) -> dict:
    """将 ChatRequest 转成 OpenAI 所需的请求 JSON。"""
    msgs = [{"role": m.role, "content": m.content} for m in req.messages]
    payload = {
        "model": model_cfg.provider_model,
        "messages": msgs,
        "temperature": req.temperature or model_cfg.default_temperature,
        "max_tokens": req.max_tokens or model_cfg.max_tokens,
        "top_p": req.top_p,
    }
    
    # 工具调用转换
    if req.tools:
        payload["tools"] = [self._serialize_tool(tool) for tool in req.tools]
        payload["tool_choice"] = req.tool_choice
    
    return payload
```

### 3. 实现响应解析

这是最关键的部分，需要根据厂商API文档处理JSON响应：

```python
def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
    """将 OpenAI 的原始响应 JSON 解析为统一的 ChatResult。"""
    choices: list[ChatChoice] = []
    
    # 解析choices数组
    for i, ch in enumerate(data.get("choices", [])):
        msg = ch.get("message") or {}
        cm = self._build_chat_message(msg)
        choices.append(
            ChatChoice(
                index=i, 
                message=cm, 
                finish_reason=ch.get("finish_reason")
            )
        )
    
    # 解析使用统计
    usage_raw = data.get("usage") or {}
    usage = ChatUsage(
        prompt_tokens=usage_raw.get("prompt_tokens", 0),
        completion_tokens=usage_raw.get("completion_tokens", 0),
        total_tokens=usage_raw.get("total_tokens", 0),
    )
    
    return ChatResult(
        provider="openai", 
        model=req.model, 
        choices=choices, 
        usage=usage, 
        raw=data
    )
```

### 4. 实现消息解析

```python
def _build_chat_message(self, payload: Dict[str, Any]) -> ChatMessage:
    """将单条厂商 message 转换为 ChatMessage。"""
    tool_calls_raw = payload.get("tool_calls") or []
    tool_calls: List[ToolCall] = []
    
    # 解析工具调用
    for idx, call in enumerate(tool_calls_raw):
        func = call.get("function") or {}
        name = func.get("name") or call.get("name") or ""
        arguments = self._parse_arguments(func.get("arguments"))
        tool_calls.append(
            ToolCall(
                id=call.get("id") or f"tool_call_{idx}",
                name=name,
                arguments=arguments,
            )
        )
    
    return ChatMessage(
        role=payload.get("role") or "assistant",
        content=payload.get("content") or "",
        tool_calls=tool_calls or None,
        tool_call_id=payload.get("tool_call_id"),
    )
```

### 5. 实现工具调用参数解析

```python
@staticmethod
def _parse_arguments(raw: Any) -> Dict[str, Any]:
    """解析工具调用的 arguments 字段。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {}
```

### 6. 更新注册表

在`registry.py`中添加新Provider配置：

```python
OPENAI_CONFIG = ProviderConfig(
    name="openai",
    base_url="https://api.openai.com/v1",
    models={
        "ide-chat": ModelConfig(
            logical_name="ide-chat",
            provider_model="gpt-4-turbo-preview",
            max_tokens=4096,
            default_temperature=0.7,
        )
    },
)
```

### 7. 更新配置文件

在`settings.py`中添加新Provider的配置项：

```python
class PydanticSettings(BaseSettings):
    # 现有配置...
    
    # OpenAI配置
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API 密钥")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API 基础URL"
    )
```

## JSON解析核心要点

### 1. 字段映射策略

每个厂商的API响应格式可能不同，需要建立字段映射表：

| 通用字段 | Kimi字段 | OpenAI字段 | DeepSeek字段 | 处理方式 |
|---------|---------|-----------|------------|---------|
| 消息角色 | role | role | role | 直接映射 |
| 消息内容 | content | content | content | 直接映射 |
| 工具调用 | tool_calls | tool_calls | tool_calls | 需要解析 |
| 完成原因 | finish_reason | finish_reason | finish_reason | 直接映射 |
| 使用统计 | usage | usage | usage | 需要映射 |

### 2. 工具调用解析差异

不同厂商的工具调用格式可能有差异：

#### Kimi/Moonshot格式
```json
{
  "tool_calls": [
    {
      "id": "call_123",
      "function": {
        "name": "search_files",
        "arguments": "{\"query\": \"test\"}"
      }
    }
  ]
}
```

#### OpenAI格式
```json
{
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "search_files",
        "arguments": "{\"query\": \"test\"}"
      }
    }
  ]
}
```

#### DeepSeek格式
```json
{
  "tool_calls": [
    {
      "id": "call_123",
      "function": {
        "name": "search_files",
        "arguments": "{\"query\": \"test\"}"
      }
    }
  ]
}
```

### 3. 错误响应处理

不同厂商的错误响应格式可能不同：

```python
# Kimi错误格式
{
  "error": {
    "message": "Invalid request",
    "type": "invalid_request_error",
    "code": "invalid_api_key"
  }
}

# OpenAI错误格式
{
  "error": {
    "message": "Invalid request",
    "type": "invalid_request_error",
    "code": "invalid_api_key"
  }
}

# DeepSeek错误格式
{
  "error": {
    "message": "Invalid request",
    "type": "invalid_request_error",
    "code": null
  }
}
```

### 4. 参数解析注意事项

1. **字符串参数**：大多数厂商将工具调用参数作为JSON字符串返回
2. **数值参数**：某些厂商可能直接返回解析后的对象
3. **特殊字符**：注意处理转义字符和Unicode字符
4. **嵌套结构**：处理复杂的嵌套参数结构

## 常见厂商响应格式

### OpenAI响应格式

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "gpt-4-turbo-preview",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!",
        "tool_calls": [
          {
            "id": "call_123",
            "type": "function",
            "function": {
              "name": "search_files",
              "arguments": "{\"query\": \"test\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

### DeepSeek响应格式

```json
{
  "id": "123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "deepseek-chat",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!",
        "tool_calls": [
          {
            "id": "call_123",
            "function": {
              "name": "search_files",
              "arguments": "{\"query\": \"test\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

### Kimi/Moonshot响应格式

```json
{
  "id": "123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "kimi-k2-turbo-preview",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello!",
        "tool_calls": [
          {
            "id": "call_123",
            "function": {
              "name": "search_files",
              "arguments": "{\"query\": \"test\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

## 实现示例

### 完整的DeepSeek客户端实现

```python
"""DeepSeek Provider 适配器。"""

import httpx
import json
from typing import Any, Dict, List

from agent_core.domain.models import ChatRequest, ChatResult, ChatMessage, ChatChoice, ChatUsage
from agent_core.domain.exceptions import NetworkError, ApiError, RateLimitError, ValidationError
from agent_core.providers.registry import DEEPSEEK_CONFIG, ModelConfig
from agent_core.tools.definitions import ToolDef, ToolCall


class DeepSeekClient:
    """DeepSeek 提供方客户端实现。"""
    
    name = "deepseek"
    
    def __init__(self, settings):
        self._settings = settings
    
    def chat(self, req: ChatRequest) -> ChatResult:
        """执行一次非流式对话调用。"""
        if not getattr(self._settings, "deepseek_api_key", None):
            raise ValidationError(code="MISSING_API_KEY", message="DEEPSEEK_API_KEY not set")
        
        model_cfg = DEEPSEEK_CONFIG.models[req.model]
        payload = self._build_payload(req, model_cfg)
        
        try:
            with httpx.Client(timeout=self._settings.http_timeout, trust_env=False) as client:
                base = getattr(self._settings, "deepseek_base_url", None) or DEEPSEEK_CONFIG.base_url
                resp = client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.RequestError as e:
            raise NetworkError(code="NETWORK_ERROR", message=str(e))
        
        if resp.status_code == 429:
            raise RateLimitError(code="RATE_LIMIT", message="DeepSeek rate limit")
        if resp.status_code >= 400:
            raise ApiError(code="API_ERROR", message=resp.text, http_status=resp.status_code)
        
        data = resp.json()
        return self._parse_response(data, req)
    
    def _build_payload(self, req: ChatRequest, model_cfg: ModelConfig) -> dict:
        """将 ChatRequest 转成 DeepSeek 所需的请求 JSON。"""
        msgs = [{"role": m.role, "content": m.content} for m in req.messages]
        payload = {
            "model": model_cfg.provider_model,
            "messages": msgs,
            "temperature": req.temperature or model_cfg.default_temperature,
            "max_tokens": req.max_tokens or model_cfg.max_tokens,
            "top_p": req.top_p,
        }
        
        if req.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in req.tools]
            payload["tool_choice"] = req.tool_choice
        
        return payload
    
    def _parse_response(self, data: dict, req: ChatRequest) -> ChatResult:
        """将 DeepSeek 的原始响应 JSON 解析为统一的 ChatResult。"""
        choices: list[ChatChoice] = []
        
        for i, ch in enumerate(data.get("choices", [])):
            msg = ch.get("message") or {}
            cm = self._build_chat_message(msg)
            choices.append(
                ChatChoice(
                    index=i, 
                    message=cm, 
                    finish_reason=ch.get("finish_reason")
                )
            )
        
        usage_raw = data.get("usage") or {}
        usage = ChatUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        
        return ChatResult(
            provider="deepseek", 
            model=req.model, 
            choices=choices, 
            usage=usage, 
            raw=data
        )
    
    def _serialize_tool(self, tool: ToolDef) -> Dict[str, Any]:
        """把内部的 ToolDef 转成 DeepSeek 的 function tool 描述。"""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        
        for name, param in tool.params.items():
            properties[name] = param.schema or {"type": "string"}
            if param.description:
                properties[name] = {
                    **properties[name],
                    "description": param.description,
                }
            if param.required:
                required.append(name)
        
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
    
    def _build_chat_message(self, payload: Dict[str, Any]) -> ChatMessage:
        """将单条厂商 message 转换为 ChatMessage。"""
        tool_calls_raw = payload.get("tool_calls") or []
        tool_calls: List[ToolCall] = []
        
        for idx, call in enumerate(tool_calls_raw):
            func = call.get("function") or {}
            name = func.get("name") or call.get("name") or ""
            arguments = self._parse_arguments(func.get("arguments"))
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or f"tool_call_{idx}",
                    name=name,
                    arguments=arguments,
                )
            )
        
        return ChatMessage(
            role=payload.get("role") or "assistant",
            content=payload.get("content") or "",
            tool_calls=tool_calls or None,
            tool_call_id=payload.get("tool_call_id"),
        )
    
    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        """解析工具调用的 arguments 字段。"""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
        return {}
```

## 测试指南

### 1. 单元测试

为每个Provider创建单元测试，参考`test_kimi_client.py`：

```python
import pytest
from unittest.mock import Mock, patch
from agent_core.providers.deepseek_client import DeepSeekClient
from agent_core.domain.models import ChatRequest, ChatMessage


def test_deepseek_client_chat():
    """测试DeepSeek客户端聊天功能。"""
    # 设置模拟配置
    mock_settings = Mock()
    mock_settings.deepseek_api_key = "test-key"
    mock_settings.http_timeout = 30.0
    
    # 创建客户端
    client = DeepSeekClient(mock_settings)
    
    # 模拟请求
    request = ChatRequest(
        provider="deepseek",
        model="ide-chat",
        messages=[ChatMessage(role="user", content="Hello")]
    )
    
    # 模拟响应
    mock_response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hi there!"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }
    
    # 测试响应解析
    result = client._parse_response(mock_response, request)
    
    assert result.provider == "deepseek"
    assert result.model == "ide-chat"
    assert len(result.choices) == 1
    assert result.choices[0].message.content == "Hi there!"
    assert result.usage.total_tokens == 15
```

### 2. 集成测试

测试完整的请求-响应流程：

```python
def test_deepseek_client_integration():
    """测试DeepSeek客户端集成功能。"""
    # 使用真实API密钥进行测试（仅在CI环境中）
    # 或者使用mock服务器模拟API响应
    pass
```

### 3. 错误处理测试

测试各种错误场景：

```python
def test_deepseek_client_error_handling():
    """测试DeepSeek客户端错误处理。"""
    mock_settings = Mock()
    mock_settings.deepseek_api_key = None  # 模拟缺失API密钥
    
    client = DeepSeekClient(mock_settings)
    request = ChatRequest(
        provider="deepseek",
        model="ide-chat",
        messages=[ChatMessage(role="user", content="Hello")]
    )
    
    # 应该抛出ValidationError
    with pytest.raises(ValidationError):
        client.chat(request)
```

## 最佳实践

1. **防御性编程**：始终检查字段是否存在，提供默认值
2. **错误处理**：捕获并转换各种异常为统一的业务异常
3. **日志记录**：记录请求和响应以便调试
4. **配置管理**：将API密钥等敏感信息存储在配置中
5. **测试覆盖**：为每个方法编写单元测试和集成测试
6. **文档更新**：及时更新API文档和示例代码

通过遵循本指南，您可以轻松地为Agent Core系统添加新的LLM Provider，并确保与现有系统的无缝集成。