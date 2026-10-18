"""会话相关的请求模型。"""
from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", max_length=50, description="会话标题")


class SessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=50, description="新标题")
