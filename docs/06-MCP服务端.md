# 06 · MCP 服务端（把知识库暴露为标准工具）

> 本步新增：`mcp_servers/knowledge_server.py`；`mcp_servers.json` 中新增 knowledge 服务器配置
> （`agent_tools: false`——只验证连通与协议，不把重复的检索工具注入 Agent）。

## 一、反向：让别的 AI 用我们的能力

第 5 步我们是客户端（用别人的工具）；这一步我们是**服务器**（把自己的能力给任何 MCP 客户端用）：

- Claude Desktop / Cursor 直接连上，就能查我们的知识库；
- 演示效果直观：**同一个知识库，一次建设，多处消费**。

暴露的三个工具：

| 工具 | 能力 |
|---|---|
| `search_knowledge` | 向量检索（返回片段 + 相似度分数） |
| `list_documents` | 已入库文档清单 |
| `ask_knowledge` | 完整 RAG 问答（答案 + 引用来源） |

## 二、实现：为什么是"薄封装 + HTTP"

```python
API = os.getenv("KNOWLEDGE_API", "http://127.0.0.1:8000")

@mcp.tool()
async def search_knowledge(query: str, top_k: int = 3) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API}/api/knowledge/search", json={...})
```

不直接 import 平台代码读 Qdrant 的原因：**Qdrant 本地模式对数据目录有文件锁**
——平台进程正锁着 `data/qdrant`，MCP 服务器是独立进程，直接打开会报
`Storage folder ... is already accessed by another instance`。
走 HTTP 复用平台进程：共享同一份数据、平台升级知识库 MCP 自动受益、MCP 服务器可独立重启。

这是常见的"API 网关式 MCP"模式。如果以后换成 Qdrant 服务端模式（Docker），
也可以改成直连，但"数据面收敛在平台进程"通常更好维护。

## 三、接入 Cursor / Claude Desktop

通用配置（`mcpServers` 格式）：

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "E:\\work\\ai-agent-mcp\\.venv\\Scripts\\python.exe",
      "args": ["E:\\work\\ai-agent-mcp\\mcp_servers\\knowledge_server.py"],
      "env": {
        "KNOWLEDGE_API": "http://127.0.0.1:8000"
      }
    }
  }
}
```

- Claude Desktop：写入 `claude_desktop_config.json`（设置 → 开发者 → 编辑配置）；
- Cursor：写入项目级或全局 MCP 配置；
- 前提：平台服务（uvicorn :8000）已启动且已上传文档；
- Windows 上路径用双反斜杠；务必写 `.venv` 里 python.exe 的绝对路径，避免用到系统 Python。

## 四、验证：自己接自己

本项目的 MCP 客户端（第 5 步）就配置了 knowledge 服务器，启动日志：

```
[已连接] knowledge
    - search_knowledge / list_documents / ask_knowledge
```

通过 MCP 协议直接调用（平台 → stdio → knowledge_server → HTTP → 平台检索接口）：

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/api/mcp/tools/call `
  -H "Content-Type: application/json" `
  -d "{\"server\":\"knowledge\",\"tool\":\"search_knowledge\",\"args\":{\"query\":\"年假有多少天\",\"top_k\":2}}"
```

返回带相似度分数的命中片段（0.5638）——**全链路打通**的证据。

## 五、自测题

1. 为什么 knowledge_server 不直接打开 Qdrant 目录？
2. 外部客户端（Cursor）使用这个服务器时，平台服务必须一直开着吗？为什么？
3. 如果要把"文档上传"也暴露成 MCP 工具，需要注意什么？（提示：写操作、文件体积、安全）
