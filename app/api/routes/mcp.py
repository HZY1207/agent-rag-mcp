"""MCP 状态与调试接口（第 5 步）。

- GET  /api/mcp/servers     看各服务器连接状态与工具清单
- POST /api/mcp/tools/call  直接调用某个 MCP 工具（调试用）
- POST /api/mcp/refresh     重连全部服务器（改完配置不用重启平台）
"""
from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.schemas.mcp import ToolCallRequest
from app.services.mcp_client import mcp_manager

router = APIRouter(tags=["mcp"])


@router.get("/mcp/servers", summary="MCP 服务器列表（连接状态 + 工具清单）")
async def list_servers() -> ApiResponse:
    return ApiResponse.ok(mcp_manager.describe())


@router.post("/mcp/tools/call", summary="调试：直接调用一个 MCP 工具")
async def call_tool(req: ToolCallRequest) -> ApiResponse:
    result = await mcp_manager.call_tool(req.server, req.tool, req.args)
    return ApiResponse.ok({"server": req.server, "tool": req.tool, "result": result})


@router.post("/mcp/refresh", summary="重连所有 MCP 服务器")
async def refresh() -> ApiResponse:
    await mcp_manager.stop()
    await mcp_manager.start()
    return ApiResponse.ok(mcp_manager.describe())
