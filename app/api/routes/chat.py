"""对话接口（第 3 步起接入 RAG：检索知识库 → 注入提示词 → 带引用的回答）。

- POST /api/chat       流式（SSE）：命中知识库时先推 citations 事件，再流式推回答
- POST /api/chat/sync  同步：一次性返回完整 JSON（含 citations）

SSE 事件协议：
  event: citations  data: {"items": [{index, filename, page, score, snippet}, ...]}
  event: delta      data: {"content": "增量文本"}
  event: done       data: {"latency_ms": n, "prompt_tokens": n, "completion_tokens": n, "mock": bool}
  event: error      data: {"message": "错误信息"}
"""
import asyncio
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.sse import sse_frame
from app.schemas.chat import ChatRequest
from app.schemas.common import ApiResponse
from app.services import knowledge, llm, sessions
from app.services.cache import semantic_cache

logger = logging.getLogger("app.chat")

router = APIRouter(tags=["chat"])


_sse = sse_frame  # 帧格式统一定义在 app/api/sse.py（agent 路由共用）


async def _retrieve(message: str, use_kb: bool) -> tuple[str, list]:
    """检索知识库（CPU 密集，丢线程池）。返回 (prompt 资料块, 引用清单)。"""
    if not use_kb:
        return "", []
    try:
        return await asyncio.to_thread(knowledge.retrieve_context, message)
    except Exception:
        logger.exception("知识库检索失败，本轮按无资料回答")
        return "", []


def _is_cacheable(req: ChatRequest) -> bool:
    """只有"单轮、无会话"的问题才走语义缓存：带上下文时同一句话的答案可能不同。"""
    return req.session_id is None and not req.history


@router.post("/chat", summary="流式对话（SSE，带知识库引用）")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式对话：连接保持不断，模型每生成一点就推送一点。"""

    async def event_source():
        start = time.perf_counter()
        try:
            # 0) 会话模式（第 7 步）：从服务端读历史、记录本轮问题
            history = req.history
            if req.session_id:
                history = await asyncio.to_thread(
                    sessions.prepare_session_chat, req.session_id, req.message
                )
            # 0.5) 语义缓存（第 9 步）：单轮问题命中缓存则直接返回，省掉 LLM 调用
            cacheable = _is_cacheable(req) and not llm.is_mock_mode()
            if cacheable:
                cached = await asyncio.to_thread(semantic_cache.get, req.message)
                if cached:
                    if cached["citations"]:
                        yield _sse("citations", {"items": cached["citations"]})
                    yield _sse("delta", {"content": cached["answer"]})
                    yield _sse(
                        "done",
                        {
                            "latency_ms": round((time.perf_counter() - start) * 1000),
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "mock": False,
                            "cached": True,
                            "cache_score": round(cached["score"], 4),
                        },
                    )
                    return
            # 1) 检索知识库：命中资料时先推 citations 事件（前端可先渲染引用卡片）
            context, citations = await _retrieve(req.message, req.use_kb)
            if citations:
                yield _sse("citations", {"items": citations})
            # 2) 调用模型流式生成
            if llm.is_mock_mode():
                logger.warning("未配置 LLM_API_KEY：当前为演示(Mock)模式")
            parts: list[str] = []
            async for item in llm.stream_reply(req.message, history, context):
                if item["type"] == "delta":
                    parts.append(item["content"])
                    yield _sse("delta", {"content": item["content"]})
                elif item["type"] == "usage":
                    yield _sse(
                        "done",
                        {
                            "latency_ms": round((time.perf_counter() - start) * 1000),
                            "prompt_tokens": item.get("prompt_tokens", 0),
                            "completion_tokens": item.get("completion_tokens", 0),
                            "mock": llm.is_mock_mode(),
                            "cached": False,
                        },
                    )
            # 2.5) 写入语义缓存（仅单轮、非 Mock 模式）
            if cacheable and parts:
                await asyncio.to_thread(
                    semantic_cache.put, req.message, "".join(parts), citations
                )
            # 3) 会话模式：回答入库（含引用）
            if req.session_id:
                await asyncio.to_thread(
                    sessions.finish_session_chat, req.session_id, "".join(parts), citations
                )
        except asyncio.CancelledError:
            # 客户端主动断开（关页面/断网）：停止生成即可，不当作错误
            logger.info("客户端提前断开连接，已停止生成")
            raise
        except Exception as exc:  # 兜底：任何异常都转成 error 事件推给前端
            logger.exception("对话生成失败")
            yield _sse("error", {"message": f"生成失败：{exc}"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 提醒 Nginx 等反向代理不要缓冲 SSE（部署时用）
        },
    )


@router.post("/chat/sync", summary="同步对话（一次性返回，带知识库引用）")
async def chat_sync(req: ChatRequest) -> ApiResponse:
    """和 /chat 相同的能力，但等全部生成完才返回——用来对比流式的体验差异。"""
    start = time.perf_counter()
    try:
        history = req.history
        if req.session_id:
            history = await asyncio.to_thread(
                sessions.prepare_session_chat, req.session_id, req.message
            )
        # 语义缓存（第 9 步）：命中则跳过检索 + LLM
        cacheable = _is_cacheable(req) and not llm.is_mock_mode()
        if cacheable:
            cached = await asyncio.to_thread(semantic_cache.get, req.message)
            if cached:
                return ApiResponse.ok(
                    {
                        "reply": cached["answer"],
                        "citations": cached["citations"],
                        "latency_ms": round((time.perf_counter() - start) * 1000),
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "mock": False,
                        "cached": True,
                        "cache_score": round(cached["score"], 4),
                    }
                )
        context, citations = await _retrieve(req.message, req.use_kb)
        parts: list[str] = []
        usage: dict = {}
        async for item in llm.stream_reply(req.message, history, context):
            if item["type"] == "delta":
                parts.append(item["content"])
            elif item["type"] == "usage":
                usage = item
        if cacheable and parts:
            await asyncio.to_thread(
                semantic_cache.put, req.message, "".join(parts), citations
            )
        if req.session_id:
            await asyncio.to_thread(
                sessions.finish_session_chat, req.session_id, "".join(parts), citations
            )
        return ApiResponse.ok(
            {
                "reply": "".join(parts),
                "citations": citations,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "mock": llm.is_mock_mode(),
                "cached": False,
            }
        )
    except Exception as exc:
        logger.exception("对话生成失败")
        return ApiResponse.fail(5001, f"生成失败：{exc}")
