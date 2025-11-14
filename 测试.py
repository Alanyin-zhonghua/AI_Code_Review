import os
import zai
from zai import ZhipuAiClient
from zai.types.chat.chat_completion import Completion
from dotenv import load_dotenv

# 加载.env文件中的环境变量
load_dotenv()

# 从环境变量获取API密钥
api_key = os.getenv("bigmodel_API_KEY")

if not api_key:
    raise RuntimeError(
        "API 密钥未设置。。"
    )

# 初始化客户端
client = ZhipuAiClient(api_key=api_key)

# 创建聊天完成请求（非流式）
response = client.chat.completions.create(
    model="glm-4.6",
    messages=[
        {
            "role": "system",
            "content": "你是一个有用的AI助手。"
        },
        {
            "role": "user",
            "content": "你好，请介绍一下自己。"
        }
    ],
    temperature=0.6,
    stream=False  # 明确指定为非流式响应
)

# 类型断言，告诉类型检查器这是Completion对象
completion_response: Completion = response  # type: ignore

# 获取回复
print(completion_response.choices[0].message.content)