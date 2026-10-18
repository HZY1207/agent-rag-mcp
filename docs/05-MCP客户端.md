# 05 · MCP 客户端（接入外部工具）

> 本步新增：`app/services/mcp_client.py`、`app/api/routes/mcp.py`、`app/schemas/mcp.py`、
> `mcp_servers.json`、`mcp_servers/demo_server.py`、`scripts/smoke_mcp.py`。
> 本步改动：`app/main.py`（lifespan 启停 MCP）、`app/services/agent.py`（MCP 工具注入 Agent）。

## 一、MCP 解决什么问题

没有 MCP 之前：每个 AI 应用要接 N 个工具，每个工具又要为 M 个模型/框架各写一遍适配 → N×M 的工作量。
MCP（Model Context Protocol）是开放协议，把"工具提供方"和"AI 应用"解耦：

```
没有 MCP：应用A×工具1、应用A×工具2、应用B×工具1……   (N×M)
有 MCP：  应用A ─┐                    ┌─ 工具1
          应用B ─┼── MCP 协议（标准）─┼─ 工具2        (N+M)
          应用C ─┘                    └─ 工具3
```

一句话：**MCP 是 AI 工具界的 USB-C。**

## 二、协议模型

- **Server（服务器）**：对外提供能力，三类——`tools`（可调用函数）/ `resources`（可读数据）/
  `prompts`（提示词模板）。本项目只对接 tools。
- **Client（客户端）**：发现并调用服务器能力。本平台就是客户端。
- **传输**：stdio（客户端拉起服务器子进程，管道通信，本地最常用）/ HTTP（远程）。

## 三、配置驱动：mcp_servers.json

```json
{
  "servers": {
    "demo": {
      "command": "python",
      "args": ["mcp_servers/demo_server.py"],
      "enabled": true,
      "agent_tools": true,
      "description": "演示工具服务器（时间 + samples 文件读取）"
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| `command` | 启动命令；本项目里 `python` 会自动替换成当前 venv 的解释器 |
| `args` | 参数；`.py` 路径自动解析成绝对路径（不依赖启动目录） |
| `env` | 追加环境变量（与系统环境合并，传入子进程） |
| `agent_tools` | 该服务器的工具是否注入 Agent 工具集 |

## 四、代码走读（两个关键设计）

### 4.1 常驻连接 + 专用任务持有

```python
self._runner = asyncio.create_task(self._run(), name="mcp-manager")
```

为什么不开一个连一个、每次调用现连？
- 每次拉子进程 + 握手要 0.3~1s，对话里每次工具调用都付这个成本不可接受；
- 但连接也不能随便建在请求处理函数里：`stdio_client` / `ClientSession` 底层基于 anyio 的
  **cancel scope**，规则是"哪个任务进入、哪个任务退出"。请求任务 A 进入、之后的请求任务 B 退出
  → `Attempted to exit cancel scope in a different task`。
- 解法：所有连接的 enter/exit 都放在同一个常驻任务 `_run` 里（`AsyncExitStack` 管生命周期），
  业务请求只调 `call_tool`。

### 4.2 JSON Schema → LangChain 工具

MCP 工具自带 JSON Schema（参数名/类型/必填/说明）。要让 LangChain 的工具调用正常工作，
需要把它转成 pydantic 模型：

```python
create_model(f"MCP_{server}_{tool}_args", **fields)   # fields 由 schema.properties 生成
StructuredTool.from_function(coroutine=_call, name=f"mcp_{server}_{tool}", args_schema=...)
```

命名加 `mcp_<server>_` 前缀，避免与本地工具（search_knowledge 等）重名。Agent 侧一行接入：

```python
tools.extend(mcp_manager.make_langchain_tools())
```

## 五、实测

```
[已连接] demo（agent_tools=True）
    - get_current_time / list_sample_files / read_text_file
[已连接] knowledge（agent_tools=False）
    - search_knowledge / list_documents / ask_knowledge
```

- 直接调用：`POST /api/mcp/tools/call {"server":"demo","tool":"get_current_time"}` → `2026-10-16T19:31:00`
- Agent 调用：问"看看 samples 目录里有哪些文件？"
  → 轨迹 `mcp_demo_list_sample_files({})` → 返回"星尘科技员工手册.md（1967 字节）"→ 2.19s 完成

## 六、接真实第三方 MCP Server

许多官方 server 用 npx 分发（需要 Node.js）。在 `mcp_servers.json` 里加：

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "E:\\work\\ai-agent-mcp\\samples"],
      "enabled": true,
      "agent_tools": true
    }
  }
}
```

然后 `POST /api/mcp/refresh` 热重连，无需重启平台。
（Windows 上 npx 可能需要写成 `npx.cmd`；装好 Node 后先在终端手动跑一次确认能启动。）

## 七、自测题

1. 用 N×M / N+M 解释 MCP 的价值。
2. 为什么 MCP 连接不能"每次请求现连现断"？两个原因分别是什么？
3. `agent_tools: false` 的服务器会出现在 `/api/mcp/servers` 里吗？它的工具会进 Agent 吗？
4. 如果两个服务器都有同名工具，本项目怎么避免冲突？
