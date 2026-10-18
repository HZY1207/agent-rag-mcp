"""MCP 链路冒烟测试：服务器/工具列表 → 直接调用工具 → Agent 使用 MCP 工具。

用法（先启动服务）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_mcp.py
"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


def list_servers() -> None:
    print("=" * 70)
    print("1) MCP 服务器列表  GET /api/mcp/servers")
    print("=" * 70)
    data = httpx.get(f"{BASE}/api/mcp/servers", timeout=30).json()["data"]
    for s in data:
        status = "已连接" if s["connected"] else "未连接"
        print(f"  [{status}] {s['name']}（agent_tools={s['agent_tools']}）{s['description']}")
        for t in s["tools"]:
            print(f"      - {t['name']}: {(t['description'] or '')[:56]}")
    print()


def call_tool(server: str, tool: str, args: dict) -> None:
    print("=" * 70)
    print(f"2) 直接调用  POST /api/mcp/tools/call  ->  {server}/{tool} {json.dumps(args, ensure_ascii=False)}")
    print("=" * 70)
    data = httpx.post(
        f"{BASE}/api/mcp/tools/call",
        json={"server": server, "tool": tool, "args": args},
        timeout=120,
    ).json()["data"]
    print("  返回：", data["result"][:320].replace("\n", " ⏎ "))
    print()


def agent_uses_mcp(question: str) -> None:
    print("=" * 70)
    print(f"3) Agent 使用 MCP 工具  question={question!r}")
    print("=" * 70)
    t0 = time.perf_counter()
    parts: list[str] = []
    with httpx.stream(
        "POST", f"{BASE}/api/agent/chat", json={"message": question}, timeout=180
    ) as resp:
        event = ""
        for line in resp.iter_lines():
            line = line.strip()
            if not line:
                continue
            stamp = f"+{time.perf_counter() - t0:5.2f}s"
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
                if event == "delta":
                    parts.append(json.loads(data)["content"])
                elif event == "step":
                    d = json.loads(data)
                    if d["phase"] == "tool_call":
                        print(f"  {stamp}  [调用工具] {d['name']}({json.dumps(d['args'], ensure_ascii=False)})")
                    else:
                        print(f"  {stamp}  [工具结果] {d['name']} -> {d['summary'][:90]}")
                elif event == "done":
                    print(f"  {stamp}  [完成] {data}")
    print()
    print("最终回答：", "".join(parts))
    print()


if __name__ == "__main__":
    list_servers()
    call_tool("demo", "get_current_time", {})
    call_tool("knowledge", "search_knowledge", {"query": "年假有多少天", "top_k": 2})
    agent_uses_mcp("帮我看看 samples 目录里有哪些文件？")
