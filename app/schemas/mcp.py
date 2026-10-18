"""MCP 相关的请求模型。"""
from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """调试用：直接调用某个 MCP 工具。"""

    server: str = Field(min_length=1, description="MCP 服务器名（GET /api/mcp/servers 可查）")
    tool: str = Field(min_length=1, description="工具名")
    args: dict = Field(default_factory=dict, description="工具参数（JSON 对象）")
