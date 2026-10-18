"""会话与记忆冒烟测试：创建 → 多轮对话（验证服务端记忆）→ 列表/详情/改名/删除。

用法（先启动服务）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_sessions.py
"""
import json

import httpx

BASE = "http://127.0.0.1:8000"


def agent_stream(session_id: str, message: str) -> str:
    """走 Agent SSE 接口发一条消息，返回完整回答。"""
    parts: list[str] = []
    with httpx.stream(
        "POST",
        f"{BASE}/api/agent/chat",
        json={"message": message, "session_id": session_id},
        timeout=180,
    ) as resp:
        event = ""
        for line in resp.iter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "delta":
                parts.append(json.loads(line.split(":", 1)[1].strip())["content"])
    return "".join(parts)


def main() -> None:
    # 1) 创建会话
    s = httpx.post(f"{BASE}/api/sessions", json={}, timeout=30).json()["data"]
    sid = s["id"]
    print(f"1) 创建会话：{sid}，标题={s['title']}")

    # 2) 两轮对话：第二轮的"它"依赖第一轮上下文（验证服务端记忆）
    a1 = agent_stream(sid, "星尘科技的年假有多少天？")
    print(f"\n2) 第 1 轮回答：{a1[:100]}")
    a2 = agent_stream(sid, "那它需要提前多久申请？")
    print(f"   第 2 轮回答：{a2[:140]}")
    ok = "3" in a2 or "三个工作日" in a2 or "3 个工作日" in a2
    print(f"   记忆验证（回答是否含『提前 3 个工作日』）：{'PASS' if ok else 'CHECK'}")

    # 3) 列表 / 详情
    sessions_list = httpx.get(f"{BASE}/api/sessions", timeout=30).json()["data"]
    print(f"\n3) 会话列表（前 3 条）：")
    for x in sessions_list[:3]:
        print(f"   - {x['id']} | {x['title']} | 消息数 {x['message_count']} | 更新于 {x['updated_at']}")
    detail = httpx.get(f"{BASE}/api/sessions/{sid}", timeout=30).json()["data"]
    print(f"   会话详情：{len(detail['messages'])} 条消息")
    for m in detail["messages"]:
        cite = f"（引用 {len(m['citations'])} 条）" if m.get("citations") else ""
        print(f"   [{m['role']:9s}] {m['content'][:60]}{cite}")

    # 4) 同步接口的会话模式（/api/chat/sync）
    s2 = httpx.post(f"{BASE}/api/sessions", json={"title": "同步会话测试"}, timeout=30).json()["data"]
    r = httpx.post(
        f"{BASE}/api/chat/sync",
        json={"message": "Wi-Fi 密码是什么？", "session_id": s2["id"]},
        timeout=120,
    ).json()["data"]
    print(f"\n4) /api/chat/sync 会话模式：reply={r['reply'][:60]!r}，引用 {len(r['citations'])} 条")
    d2 = httpx.get(f"{BASE}/api/sessions/{s2['id']}", timeout=30).json()["data"]
    print(f"   入库消息：{len(d2['messages'])} 条（应为 2）")

    # 5) 改名 / 删除
    r = httpx.patch(f"{BASE}/api/sessions/{sid}", json={"title": "年假咨询"}, timeout=30).json()
    print(f"\n5) 改名：{r['data']['title']}")
    r = httpx.delete(f"{BASE}/api/sessions/{sid}", timeout=30).json()
    print(f"   删除：{r['data']}")
    r = httpx.get(f"{BASE}/api/sessions/{sid}", timeout=30).json()
    print(f"   删除后查询：code={r['code']}, message={r['message']}")


if __name__ == "__main__":
    main()
