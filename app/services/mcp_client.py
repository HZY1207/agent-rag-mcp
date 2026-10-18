"""MCP 客户端管理器（第 5 步）：连接外部 MCP Server，把它们的工具接进平台。

MCP（Model Context Protocol）可以理解为"AI 工具界的 USB-C"：
客户端按统一的 JSON-RPC 协议问服务器——你有哪些工具？（list_tools）
调用某个工具。（call_tool）；传输方式支持 stdio（拉子进程，最常用）与 HTTP。

实现要点：
- 常驻连接：启动时按 mcp_servers.json 拉起各服务器子进程并握手，
  之后调用工具直接复用会话（每次现拉子进程要多花 0.3~1s）；
- 专用任务持有连接：stdio_client / ClientSession 基于 anyio 的 cancel scope，
  必须"在同一个任务里进入/退出"——所以连接统一放在后台常驻任务 _run 里
  （用 AsyncExitStack 管住），业务请求只管调用工具；
- 容错：任何服务器连不上都只记警告，不阻塞平台启动；
- 协议转换：把 MCP 工具转成 LangChain 工具（名字加 mcp_<服务器>_ 前缀），
  Agent 即可"即插即用"地调用外部工具。
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.core.config import get_settings

logger = logging.getLogger("app.mcp")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class MCPClientManager:
    """所有 MCP 服务器连接的常驻管理器（进程内单例：mcp_manager）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, list[dict]] = {}
        self._configs: dict[str, dict] = {}
        self._runner: asyncio.Task | None = None
        self._shutdown: asyncio.Event | None = None
        self._ready: asyncio.Event | None = None

    # ---------------- 生命周期 ----------------

    async def start(self) -> None:
        """读取配置并建立全部连接（在常驻任务里完成，见 _run）。"""
        path = Path(get_settings().mcp_config_path)
        if not path.exists():
            logger.warning("MCP 配置不存在：%s（跳过 MCP 初始化）", path)
            return
        config = json.loads(path.read_text(encoding="utf-8"))
        self._configs = {
            k: v for k, v in (config.get("servers") or {}).items() if v.get("enabled", True)
        }
        self._shutdown = asyncio.Event()
        self._ready = asyncio.Event()
        self._runner = asyncio.create_task(self._run(), name="mcp-manager")
        await self._ready.wait()  # 等连接阶段结束再返回，启动日志才有序

    async def stop(self) -> None:
        if self._shutdown:
            self._shutdown.set()
        if self._runner:
            await self._runner
            self._runner = None

    async def _run(self) -> None:
        """常驻任务：持有所有连接的 enter/exit（cancel scope 必须同任务）。"""
        try:
            async with AsyncExitStack() as stack:
                for name, cfg in self._configs.items():
                    try:
                        await self._connect(stack, name, cfg)
                    except Exception as exc:
                        logger.warning("MCP 服务器 %s 连接失败：%s", name, exc)
                if self._ready:
                    self._ready.set()
                assert self._shutdown is not None
                await self._shutdown.wait()
        finally:
            self._sessions.clear()
            self._tools.clear()
            if self._ready:
                self._ready.set()  # 防呆：连接阶段异常时也别让 start() 卡住

    async def _connect(self, stack: AsyncExitStack, name: str, cfg: dict) -> None:
        command = cfg.get("command", "python")
        if command in ("python", "python3"):
            command = sys.executable  # 用当前 venv 的解释器，依赖才找得到
        args = [
            str((PROJECT_ROOT / str(a)).resolve()) if str(a).endswith(".py") else str(a)
            for a in (cfg.get("args") or [])
        ]
        env = {**os.environ, **(cfg.get("env") or {})}
        params = StdioServerParameters(command=command, args=args, env=env)
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools_resp = await session.list_tools()
        self._sessions[name] = session
        self._tools[name] = [self._tool_to_dict(t) for t in tools_resp.tools]
        logger.info(
            "MCP 服务器 %s 已连接（%d 个工具：%s）",
            name,
            len(self._tools[name]),
            ", ".join(t["name"] for t in self._tools[name]),
        )

    @staticmethod
    def _tool_to_dict(t: Any) -> dict:
        schema = getattr(t, "inputSchema", None)
        if schema is None:
            schema = getattr(t, "input_schema", None)
        return {
            "name": t.name,
            "description": t.description or "",
            "input_schema": schema or {},
        }

    # ---------------- 查询与调用 ----------------

    def describe(self) -> list[dict]:
        """接口用：列出所有配置的服务器、连接状态与工具清单。"""
        out = []
        for name, cfg in self._configs.items():
            out.append(
                {
                    "name": name,
                    "description": cfg.get("description", ""),
                    "connected": name in self._sessions,
                    "agent_tools": bool(cfg.get("agent_tools")),
                    "tools": self._tools.get(name, []),
                }
            )
        return out

    async def call_tool(self, server: str, tool: str, args: dict) -> str:
        """调用指定服务器的一个工具，统一返回字符串结果。"""
        session = self._sessions.get(server)
        if not session:
            return f"错误：MCP 服务器 {server} 未连接"
        try:
            result = await session.call_tool(tool, args or {})
        except Exception as exc:
            return f"错误：调用 {server}/{tool} 失败：{exc}"
        texts = [b.text for b in (result.content or []) if getattr(b, "text", None) is not None]
        text = "\n".join(texts)
        if not text:
            structured = getattr(result, "structured_content", None)
            if structured is None:
                structured = getattr(result, "structuredContent", None)
            if structured:
                text = json.dumps(structured, ensure_ascii=False)
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            return f"工具执行出错：{text or '（无详情）'}"
        return text or "（工具无返回内容）"

    # ---------------- 给 Agent 的工具转换 ----------------

    def make_langchain_tools(self) -> list:
        """把 agent_tools=true 的服务器工具转成 LangChain 工具，供 Agent 直接调用。"""
        from langchain_core.tools import StructuredTool

        tools = []
        for server, cfg in self._configs.items():
            if not cfg.get("agent_tools") or server not in self._sessions:
                continue
            for t in self._tools.get(server, []):
                tools.append(
                    StructuredTool.from_function(
                        coroutine=self._make_caller(server, t["name"]),
                        name=f"mcp_{server}_{t['name']}",
                        description=f"[MCP·{server}] {t['description'] or t['name']}",
                        args_schema=self._build_args_schema(server, t),
                    )
                )
        return tools

    @staticmethod
    def _make_caller(server: str, tool: str):
        async def _call(**kwargs) -> str:
            return await mcp_manager.call_tool(server, tool, kwargs)

        return _call

    @staticmethod
    def _build_args_schema(server: str, t: dict):
        """把 MCP 工具的 JSON Schema 转成 pydantic 模型（LangChain 靠它生成工具参数）。"""
        from pydantic import Field, create_model

        schema = t.get("input_schema") or {}
        props: dict = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        fields: dict[str, tuple] = {}
        for pname, ps in props.items():
            ptype = _JSON_TYPE_MAP.get((ps or {}).get("type", "string"), str)
            desc = (ps or {}).get("description", "")
            if pname in required:
                fields[pname] = (ptype, Field(..., description=desc))
            else:
                fields[pname] = (ptype | None, Field(default=None, description=desc))
        if not fields:
            return None
        return create_model(f"MCP_{server}_{t['name']}_args", **fields)


mcp_manager = MCPClientManager()
