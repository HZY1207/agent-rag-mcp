"""知识库接口：上传 / 文档列表 / 向量检索（RAG 的"索引"与"检索"两个环节）。

重活（解析、向量化、读写向量库）全部通过 asyncio.to_thread 丢线程池，
避免阻塞事件循环——否则上传一个大文档会卡死所有并发请求。
"""
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile

from app.schemas.common import ApiResponse
from app.schemas.knowledge import SearchRequest
from app.services import knowledge

logger = logging.getLogger("app.knowledge")

router = APIRouter(tags=["knowledge"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB：防止误传超大文件拖垮内存
ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


@router.post("/knowledge/upload", summary="上传文档入库（解析→切片→向量化）")
async def upload_document(file: UploadFile) -> ApiResponse:
    filename = Path(file.filename or "unnamed").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return ApiResponse.fail(4001, f"不支持的文件类型 {suffix}（支持 txt / md / pdf）")

    data = await file.read()
    if len(data) == 0:
        return ApiResponse.fail(4002, "文件内容为空")
    if len(data) > MAX_FILE_SIZE:
        return ApiResponse.fail(4003, "文件超过 10MB 限制，请拆分后上传")

    try:
        result = await asyncio.to_thread(knowledge.ingest, filename, data)
    except Exception as exc:
        logger.exception("文档入库失败：%s", filename)
        return ApiResponse.fail(4004, f"入库失败：{exc}")
    return ApiResponse.ok(result)


@router.get("/knowledge/documents", summary="已入库文档列表")
async def list_documents() -> ApiResponse:
    return ApiResponse.ok(await asyncio.to_thread(knowledge.list_documents))


@router.post("/knowledge/search", summary="向量检索（看相似度分数，调试检索质量）")
async def search(req: SearchRequest) -> ApiResponse:
    hits = await asyncio.to_thread(knowledge.search, req.query, req.top_k)
    return ApiResponse.ok([h.__dict__ for h in hits])
