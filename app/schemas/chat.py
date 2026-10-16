"""对话相关的请求模型。"""
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """一条历史消息。"""

    role: str = Field(pattern="^(user|assistant)$", description="角色：user / assistant")
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    """对话请求。"""

    message: str = Field(min_length=1, max_length=8000, description="用户本轮输入")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="历史消息列表（本步由客户端传入；第 7 步起改为服务端持久化）",
    )
