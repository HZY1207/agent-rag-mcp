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
from app.services import knowledge, llm

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


@router.post("/chat", summary="流式对话（SSE，带知识库引用）")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式对话：连接保持不断，模型每生成一点就推送一点。"""

    async def event_source():
        start = time.perf_counter()
        try:
            # 1) 检索知识库：命中资料时先推 citations 事件（前端可先渲染引用卡片）
            context, citations = await _retrieve(req.message, req.use_kb)
            if citations:
                yield _sse("citations", {"items": citations})
            # 2) 调用模型流式生成
            if llm.is_mock_mode():
                logger.warning("未配置 LLM_API_KEY：当前为演示(Mock)模式")
            async for item in llm.stream_reply(req.message, req.history, context):
                if item["type"] == "delta":
                    yield _sse("delta", {"content": item["content"]})
                elif item["type"] == "usage":
                    yield _sse(
                        "done",
                        {
                            "latency_ms": round((time.perf_counter() - start) * 1000),
                            "prompt_tokens": item.get("prompt_tokens", 0),
                            "completion_tokens": item.get("completion_tokens", 0),
                            "mock": llm.is_mock_mode(),
                        },
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
        context, citations = await _retrieve(req.message, req.use_kb)
        parts: list[str] = []
        usage: dict = {}
        async for item in llm.stream_reply(req.message, req.history, context):
            if item["type"] == "delta":
                parts.append(item["content"])
            elif item["type"] == "usage":
                usage = item
        return ApiResponse.ok(
            {
                "reply": "".join(parts),
                "citations": citations,
                "latency_ms": round((time.perf_counter() - start) * 1000),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "mock": llm.is_mock_mode(),
            }
        )
    except Exception as exc:
        logger.exception("对话生成失败")
        return ApiResponse.fail(5001, f"生成失败：{exc}")
