"""LLM 服务：把「调用大模型」封装成一个函数，隔离具体服务商的细节。

- 配置了 LLM_API_KEY：调用真实模型（OpenAI 兼容协议，DeepSeek/通义/智谱等均可）
- 未配置：进入演示(Mock)模式，本地模拟流式输出，方便先把整条链路跑通

第 3 步起：支持传入 context（知识库检索到的"参考资料"），
有资料时切换为 RAG 系统提示词，要求模型标注引用编号 [1][2]...
"""
import asyncio
import logging
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas.chat import ChatMessage

logger = logging.getLogger("app.llm")

# 系统提示词（无知识库资料时）
SYSTEM_PROMPT = "你是一个耐心、严谨的智能助手，请用简洁清晰的中文回答。"

# 系统提示词（有知识库资料时）：资料以 [编号] 注入，回答里也要用 [编号] 标注出处
RAG_SYSTEM_PROMPT = (
    "你是知识库问答助手，请严格依据「参考资料」回答用户问题：\n"
    "1. 用 [编号] 标注引用的资料（如 [1]、[2]），编号与参考资料一一对应；\n"
    "2. 如果参考资料不足以回答，请明确说明「知识库中没有相关内容」，再基于你自己的知识谨慎补充；\n"
    "3. 不要编造参考资料里不存在的细节。"
)

# Mock 模式模拟"逐字输出"的速度（秒/字），仅演示用。
# 注意：必须大于 Windows 单调时钟精度（约 0.0156s）——asyncio 会把"到期时刻在
# 当前时间 + 时钟精度以内"的定时器提前触发（CPython base_events._run_once 的
# end_time 优化）。在事件循环持续繁忙的场景（如 SSE 流式路径）里，0.015s 的
# sleep 会被瞬间"提前唤醒"，导致 mock 4ms 吐完整段；0.02s 可保证跨过一个时钟 tick。
MOCK_CHAR_DELAY = 0.02


def is_mock_mode() -> bool:
    """未配置 API Key 时进入演示模式。"""
    return not get_settings().llm_api_key


def create_llm() -> ChatOpenAI:
    """按配置创建模型客户端。base_url 一换就能切换服务商。"""
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        temperature=0.3,
        timeout=120,
        stream_usage=True,  # 让流末尾的响应块带上 token 用量（计量用）
    )


def _build_messages(
    message: str, history: list[ChatMessage] | None, context: str = ""
) -> list[BaseMessage]:
    """把「系统提示词 + 历史消息 + 本轮问题」组装成模型需要的消息列表。

    context 非空时：系统提示词切换为 RAG 版本，并把资料块拼在后面。
    多轮对话就是把历史消息按顺序排好一起发过去（模型本身无记忆）。
    """
    if context:
        system = f"{RAG_SYSTEM_PROMPT}\n\n===== 参考资料 =====\n{context}\n===== 参考资料结束 ====="
    else:
        system = SYSTEM_PROMPT
    messages: list[BaseMessage] = [SystemMessage(content=system)]
    for h in history or []:
        if h.role == "user":
            messages.append(HumanMessage(content=h.content))
        else:
            messages.append(AIMessage(content=h.content))
    messages.append(HumanMessage(content=message))
    return messages


async def stream_reply(
    message: str, history: list[ChatMessage] | None = None, context: str = ""
) -> AsyncIterator[dict]:
    """流式生成回复，逐个事件产出。

    事件（dict）：
      {"type": "delta", "content": "..."}                             增量文本
      {"type": "usage", "prompt_tokens": n, "completion_tokens": n}   用量统计
    """
    if is_mock_mode():
        async for event in _mock_stream(message):
            yield event
        return

    llm = create_llm()
    messages = _build_messages(message, history, context)
    usage = None
    async for chunk in llm.astream(messages):
        text = chunk.content
        if isinstance(text, str) and text:
            yield {"type": "delta", "content": text}
        if chunk.usage_metadata:
            usage = chunk.usage_metadata
    yield {
        "type": "usage",
        "prompt_tokens": (usage or {}).get("input_tokens", 0),
        "completion_tokens": (usage or {}).get("output_tokens", 0),
    }


async def _mock_stream(message: str) -> AsyncIterator[dict]:
    """演示模式：本地逐字输出一段说明文本（不调用任何网络）。"""
    text = (
        "【演示模式】还没检测到 LLM_API_KEY，当前是本地模拟的流式输出。"
        f"你刚才说：「{message}」。"
        "把项目根目录 .env 里 LLM_API_KEY= 后面填上你的 Key 并重启服务，"
        "这里就会变成真实大模型的回答。"
    )
    for ch in text:
        yield {"type": "delta", "content": ch}
        await asyncio.sleep(MOCK_CHAR_DELAY)
    yield {"type": "usage", "prompt_tokens": 0, "completion_tokens": 0}
