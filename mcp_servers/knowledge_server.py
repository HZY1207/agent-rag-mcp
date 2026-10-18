"""知识库 MCP Server（第 6 步）：把本平台的知识库能力暴露为标准 MCP 工具。

任何支持 MCP 的客户端（Claude Desktop / Cursor / 本平台自己的 MCP 客户端）
通过 stdio 连上本服务器后，可以直接调用：
  - search_knowledge   检索知识库（含相似度分数）
  - list_documents     列出已入库文档
  - ask_knowledge      对话式问答（返回答案 + 引用来源）

实现方式是"薄封装"：内部通过 HTTP 调用本平台的服务（FastAPI 需已启动）。
为什么走 HTTP 而不直接读 Qdrant？
  Qdrant 本地模式对数据目录有文件锁——平台进程正锁着 data/qdrant，
  第二个进程直接打开会报错；走 HTTP 复用平台进程，天然共享同一个知识库，
  也让 MCP Server 可以随时被独立重启，互不影响。

接入 Cursor / Claude Desktop 的配置示例见 docs/06-MCP服务端.md。
"""
import os

import httpx
from mcp.server.mcpserver import MCPServer

# 平台地址：可被客户端通过环境变量覆盖
API = os.getenv("KNOWLEDGE_API", "http://127.0.0.1:8000")

mcp = MCPServer("knowledge-base")

TIMEOUT = 120.0


@mcp.tool()
async def search_knowledge(query: str, top_k: int = 3) -> str:
    """检索企业知识库，返回最相关的资料片段（含相似度分数）。

    Args:
        query: 检索问题或关键词
        top_k: 返回片段数，默认 3
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{API}/api/knowledge/search", json={"query": query, "top_k": top_k}
        )
    hits = resp.json().get("data") or []
    if not hits:
        return "没有检索到相关内容（知识库可能为空）。"
    lines = []
    for i, h in enumerate(hits, start=1):
        lines.append(f"[{i}] {h['filename']}（相关度 {h['score']}）\n{h['text']}")
    return "\n\n---\n\n".join(lines)


@mcp.tool()
async def list_documents() -> str:
    """列出知识库中已入库的文档（文件名、切片数、doc_id）。"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{API}/api/knowledge/documents")
    docs = resp.json().get("data") or []
    if not docs:
        return "知识库为空。"
    return "\n".join(
        f"- {d['filename']}（{d['chunks']} 个切片，doc_id={d['doc_id']}）" for d in docs
    )


@mcp.tool()
async def ask_knowledge(question: str) -> str:
    """向知识库提问，返回基于资料的完整回答与引用来源（适合需要综合多个片段的提问）。"""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{API}/api/chat/sync", json={"message": question, "use_kb": True}
        )
    body = resp.json()
    data = body.get("data") or {}
    reply = data.get("reply")
    if not reply:
        return f"提问失败（code={body.get('code')}）：{body.get('message')}"
    lines = [reply]
    citations = data.get("citations") or []
    if citations:
        lines.append("")
        lines.append("引用来源：")
        for c in citations:
            lines.append(f"  [{c['index']}] {c['filename']}（相关度 {c['score']}）")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输
