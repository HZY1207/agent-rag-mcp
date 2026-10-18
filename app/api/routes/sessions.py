"""会话管理接口（第 7 步：会话与记忆持久化）。

会话数据落在 SQLite（data/sessions.sqlite3），带 session_id 调用对话接口时：
历史自动从库里取、问题与回答自动入库——多轮上下文不再依赖客户端来回传。
"""
from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.schemas.sessions import SessionCreate, SessionRename
from app.services import sessions

router = APIRouter(tags=["sessions"])


@router.post("/sessions", summary="创建会话")
async def create_session(req: SessionCreate) -> ApiResponse:
    return ApiResponse.ok(sessions.create_session(req.title))


@router.get("/sessions", summary="会话列表（按更新时间倒序）")
async def list_sessions() -> ApiResponse:
    return ApiResponse.ok(sessions.list_sessions())


@router.get("/sessions/{session_id}", summary="会话详情（含全部历史消息）")
async def session_detail(session_id: str) -> ApiResponse:
    info = sessions.get_session(session_id)
    if not info:
        return ApiResponse.fail(4040, "会话不存在")
    info["messages"] = sessions.get_messages(session_id)
    return ApiResponse.ok(info)


@router.patch("/sessions/{session_id}", summary="重命名会话")
async def rename_session(session_id: str, req: SessionRename) -> ApiResponse:
    if not sessions.rename_session(session_id, req.title):
        return ApiResponse.fail(4040, "会话不存在")
    return ApiResponse.ok(sessions.get_session(session_id))


@router.delete("/sessions/{session_id}", summary="删除会话（连同消息）")
async def delete_session(session_id: str) -> ApiResponse:
    if not sessions.delete_session(session_id):
        return ApiResponse.fail(4040, "会话不存在")
    return ApiResponse.ok({"deleted": session_id})
