"""Agent 冒烟测试：SSE 事件流（step 工具轨迹 + citations + delta + done）。

用法（先启动服务）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_agent.py
"""
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"

CASES = [
    ("知识库检索", "星尘科技的年假是多少天？需要提前多久申请？"),
    ("计算器工具", "（1234*7+6）/2 等于多少？"),
    ("多工具组合", "帮我算一下：星尘科技年假上限天数 乘以 3，再减去 5 等于多少？（先查知识库）"),
]


def run_case(title: str, question: str) -> None:
    print("=" * 70)
    print(f"【{title}】 {question}")
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
                        print(f"  {stamp}  [工具结果] {d['name']} -> {d['summary'][:80]}")
                elif event == "citations":
                    items = json.loads(data)["items"]
                    print(f"  {stamp}  [引用] {len(items)} 条：{items[0]['filename']} 得分 {items[0]['score']}")
                elif event == "done":
                    print(f"  {stamp}  [完成] {data}")
                else:
                    print(f"  {stamp}  [{event}] {data[:120]}")
    print()
    print("最终回答：", "".join(parts))
    print()


if __name__ == "__main__":
    for t, q in CASES:
        run_case(t, q)
