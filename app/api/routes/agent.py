"""Agent 对话接口（第 4 步）：SSE 推流「工具调用轨迹 + 流式回答」。

相比 /api/chat 新增 step 事件，前端可以用它画出 Agent 的"思考时间线"：

  event: step       data: {"type":"step","phase":"tool_call","name":"search_knowledge","args":{...}}
  event: step       data: {"type":"step","phase":"tool_result","name":"search_knowledge","summary":"..."}
  event: citations  data: {"items": [...]}    工具检索到资料时推送（可能多次，每次是全量最新列表）
  event: delta      data: {"content": "增量文本"}
  event: done       data: {"latency_ms": n, "prompt_tokens": n, "completion_tokens": n, "tool_calls": n, "mock": bool}
  event: error      data: {"message": "..."}
"""
import asyncio
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.sse import sse_frame
from app.schemas.chat import ChatRequest
from app.services import agent, llm, sessions

logger = logging.getLogger("app.agent")

router = APIRouter(tags=["agent"])


@router.post("/agent/chat", summary="Agent 对话（SSE：工具调用轨迹 + 流式回答）")
async def agent_chat(req: ChatRequest) -> StreamingResponse:
    """智能体对话：模型自主决定调用哪些工具（知识库检索 / 计算器 / 时间）。"""

    async def event_source():
        start = time.perf_counter()
        try:
            # 1) 组装历史：带 session_id 时从服务端会话库读取并记录本轮问题
            history = req.history
            if req.session_id:
                history = await asyncio.to_thread(
                    sessions.prepare_session_chat, req.session_id, req.message
                )
            # 2) 跑 ReAct 循环，逐事件转发
            citations: list = []   # 引用收集器（被 generator 填充）
            sent = 0               # 已推送给前端的引用数
            parts: list[str] = []  # 回答全文（用于会话入库）
            tool_calls = 0
            async for item in agent.stream_agent_reply(
                req.message, history, citations, include_kb=req.use_kb
            ):
                if item["type"] == "delta":
                    parts.append(item["content"])
                    yield sse_frame("delta", {"content": item["content"]})
                elif item["type"] == "step":
                    if item.get("phase") == "tool_call":
                        tool_calls += 1
                    yield sse_frame("step", item)
                elif item["type"] == "usage":
                    if len(citations) > sent:  # 收尾前补一次引用（理论上不会触发，兜底）
                        yield sse_frame("citations", {"items": citations})
                        sent = len(citations)
                    yield sse_frame(
                        "done",
                        {
                            "latency_ms": round((time.perf_counter() - start) * 1000),
                            "prompt_tokens": item.get("prompt_tokens", 0),
                            "completion_tokens": item.get("completion_tokens", 0),
                            "tool_calls": tool_calls,
                            "mock": llm.is_mock_mode(),
                        },
                    )
                # 工具执行后引用列表会变长：有新增就推一次最新列表
                if len(citations) > sent and item["type"] != "usage":
                    yield sse_frame("citations", {"items": citations})
                    sent = len(citations)
            # 3) 回答入库（含引用）
            if req.session_id:
                await asyncio.to_thread(
                    sessions.finish_session_chat, req.session_id, "".join(parts), citations
                )
        except asyncio.CancelledError:
            logger.info("客户端提前断开，已停止 Agent 生成")
            raise
        except Exception as exc:
            logger.exception("Agent 生成失败")
            yield sse_frame("error", {"message": f"Agent 生成失败：{exc}"})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
