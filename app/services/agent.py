"""Agent 服务（第 4 步）：基于 LangGraph 的 ReAct 智能体——模型自主决定"调不调工具、调几次"。

和固定流程的 /api/chat 对比：
- /api/chat（第 3 步）：检索 → 拼提示词 → 回答，步骤是写死的；
- /api/agent/chat（本步）：把「检索知识库 / 计算器 / 当前时间」包装成工具，
  模型自己在「思考 → 调用工具 → 观察结果 → 再思考」的循环里走，直到给出最终答案。

这就是 ReAct（Reason + Act）范式；Agent = 模型 + 工具 + 循环 三件套。

流式事件（dict，由路由层转成 SSE）：
  {"type": "step", "phase": "tool_call",   "name": ..., "args": {...}}
  {"type": "step", "phase": "tool_result", "name": ..., "summary": "..."}
  {"type": "delta", "content": "..."}    最终回答的增量文本
  {"type": "usage", "prompt_tokens": n, "completion_tokens": n}
"""
import ast
import asyncio
import logging
import operator
from collections.abc import AsyncIterator
from datetime import datetime

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import tool

from app.core.config import get_settings
from app.schemas.chat import ChatMessage
from app.services import knowledge
from app.services.llm import MOCK_CHAR_DELAY, create_llm, is_mock_mode
from app.services.mcp_client import mcp_manager

logger = logging.getLogger("app.agent")

AGENT_SYSTEM_PROMPT = (
    "你是「AI Agent 智能助手平台」的主控智能体，可以调用工具来完成任务。\n"
    "工作原则：\n"
    "1. 涉及公司/内部资料的事实问题，先用 search_knowledge 检索知识库，再基于结果回答；\n"
    "2. 引用知识库资料时用 [编号] 标注（编号与检索结果中的编号一致），不要编造资料里没有的内容；\n"
    "3. 需要计算用 calculator，需要当前日期时间用 get_current_time；\n"
    "4. 如果知识库/工具没有给出有用信息，如实说明；\n"
    "5. 调用工具前后不要输出任何过渡性文字（如 \"I'll search...\"、\"我先查一下\"），"
    "直接的文字输出只用于最终回答；\n"
    "6. 回答用简洁清晰的中文。"
)

# ---------------- 计算器的安全求值 ----------------

_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> float | int:
    """安全的算术表达式求值。

    绝不要对用户输入用内置 eval（可执行任意代码）——
    这里用 ast 解析成语法树，只放行「数字 + 基本运算符」的白名单节点。
    """
    if len(expr) > 100:
        raise ValueError("表达式过长")
    node = ast.parse(expr, mode="eval").body

    def _eval(n: ast.AST) -> float | int:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _ALLOWED_OPS:
            result = _ALLOWED_OPS[type(n.op)](_eval(n.left), _eval(n.right))
            if abs(result) > 1e15:
                raise ValueError("结果过大")
            return result
        if isinstance(n, ast.UnaryOp) and type(n.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(n.op)](_eval(n.operand))
        raise ValueError(f"不支持的表达式片段：{type(n).__name__}")

    return _eval(node)


# ---------------- 工具集 ----------------

def _make_tools(citations: list[dict], include_kb: bool = True) -> list:
    """构造本次请求的工具集。

    citations 是本轮请求的"引用收集器"：每次检索工具被调用，就把命中结果
    追加进去（编号全局递增，和工具返回给模型的编号一致），
    回答结束后由路由层统一推给前端。
    """

    tools: list = []

    if include_kb:

        @tool
        def search_knowledge(query: str, top_k: int = 3) -> str:
            """检索企业内部知识库（公司手册、制度文档等），返回最相关的资料片段。

            Args:
                query: 检索问题或关键词
                top_k: 返回的片段数量，默认 3
            """
            hits = knowledge.search(query, top_k)
            threshold = get_settings().kb_score_threshold
            useful = [h for h in hits if h.score >= threshold]
            if not useful:
                if hits:
                    return f"没有检索到足够相关的内容（最高分 {hits[0].score}，低于阈值 {threshold}）。"
                return "知识库为空，或没有检索到相关内容。"
            lines: list[str] = []
            for h in useful:
                idx = len(citations) + 1
                loc = f"第 {h.page} 页" if h.page else "全文"
                citations.append(
                    {
                        "index": idx,
                        "doc_id": h.doc_id,
                        "filename": h.filename,
                        "page": h.page,
                        "score": h.score,
                        "snippet": h.text[:120],
                    }
                )
                lines.append(f"[{idx}] 来源：{h.filename}（{loc}），相关度 {h.score}\n{h.text}")
            return "\n\n---\n\n".join(lines)

        tools.append(search_knowledge)

    @tool
    def calculator(expression: str) -> str:
        """计算一个数学表达式（支持 + - * / // % ** 和括号），例如 "(1234*7+6)/2"。"""
        try:
            return str(_safe_eval(expression))
        except Exception as exc:
            return f"计算出错：{exc}"

    @tool
    def get_current_time() -> str:
        """获取当前日期与时间（本地时区）。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

    tools.extend([calculator, get_current_time])
    return tools


# ---------------- 流式执行 ----------------

async def stream_agent_reply(
    message: str,
    history: list[ChatMessage] | None = None,
    citations: list | None = None,
    include_kb: bool = True,
) -> AsyncIterator[dict]:
    """跑一次 ReAct 循环，流式产出事件。

    citations：外部传入的列表，工具检索到的资料会被追加进去（out 参数模式）。
    """
    if is_mock_mode():
        async for ev in _mock_agent_stream(message):
            yield ev
        return

    citations = citations if citations is not None else []
    tools = _make_tools(citations, include_kb=include_kb)
    # MCP 外部工具（第 5 步）：mcp_servers.json 里 agent_tools=true 的服务器，工具即插即用
    tools.extend(mcp_manager.make_langchain_tools())
    graph = create_agent(create_llm(), tools, system_prompt=AGENT_SYSTEM_PROMPT, name="react_agent")

    messages: list[tuple[str, str]] = []
    for h in history or []:
        messages.append(("user" if h.role == "user" else "assistant", h.content))
    messages.append(("user", message))

    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    # LangGraph 多模式流式：
    # - messages：模型每产出一小块就推（用于打字机效果的增量文本）
    # - updates ：每个节点执行完推一次状态更新（用于捕捉工具调用/结果）
    async for mode, chunk in graph.astream(
        {"messages": messages},
        stream_mode=["messages", "updates"],
        config={"recursion_limit": 25},  # 防止模型陷入死循环：最多 25 个图步骤
    ):
        if mode == "messages":
            msg, _meta = chunk
            if isinstance(msg, AIMessageChunk) and isinstance(msg.content, str) and msg.content:
                yield {"type": "delta", "content": msg.content}
            continue

        # mode == "updates"
        for _node, update in (chunk or {}).items():
            for m in (update or {}).get("messages", []) or []:
                if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        yield {
                            "type": "step",
                            "phase": "tool_call",
                            "name": tc.get("name"),
                            "args": tc.get("args"),
                        }
                elif isinstance(m, ToolMessage):
                    summary = str(m.content)
                    if len(summary) > 160:
                        summary = summary[:160] + "…"
                    yield {"type": "step", "phase": "tool_result", "name": m.name, "summary": summary}
                if isinstance(m, AIMessage) and getattr(m, "usage_metadata", None):
                    u = m.usage_metadata
                    usage["prompt_tokens"] += u.get("input_tokens", 0)
                    usage["completion_tokens"] += u.get("output_tokens", 0)

    yield {"type": "usage", "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"]}


async def _mock_agent_stream(message: str) -> AsyncIterator[dict]:
    """演示模式：没有 Key 时模拟一段说明文本（真实 Agent 需要模型支持工具调用）。"""
    text = (
        "【演示模式】还没检测到 LLM_API_KEY。Agent 的工具调用需要真实大模型支持，"
        f"你刚才说：「{message}」。把 .env 里 LLM_API_KEY 填好并重启服务，"
        "这里就会变成 Agent 自主调用工具、流式输出思考轨迹的效果。"
    )
    for ch in text:
        yield {"type": "delta", "content": ch}
        await asyncio.sleep(MOCK_CHAR_DELAY)
    yield {"type": "usage", "prompt_tokens": 0, "completion_tokens": 0}
