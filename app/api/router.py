"""路由聚合器：各模块的路由在这里统一挂载，main.py 只认识这一个入口。

后续步骤会陆续挂载：/chat（对话）、/documents（文档）、/sessions（会话）……
"""
from fastapi import APIRouter

from app.api.routes import chat, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
