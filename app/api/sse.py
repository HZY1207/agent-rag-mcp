"""SSE 帧格式化工具：chat 与 agent 两个流式路由共用。

SSE（Server-Sent Events）协议的最小帧格式：
    event: <事件名>\n
    data: <JSON 一行>\n
    \n                       ← 空行表示一帧结束
"""
import json


def sse_frame(event: str, data: dict) -> str:
    """把一条事件格式化成 SSE 帧。JSON 用 ensure_ascii=False 保留中文原文。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
