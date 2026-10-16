"""对话接口冒烟测试（只用标准库，无额外依赖）。

用法（先启动服务，再执行）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_chat.py
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
QUESTION = "你好，做个自我介绍"


def _post(path: str, payload: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=120)


def test_sse() -> None:
    print("=" * 64)
    print("1) SSE 流式接口  POST /api/chat")
    print("=" * 64)
    t0 = time.perf_counter()
    shown = 0
    done_line = None
    got_error = False
    try:
        with _post("/api/chat", {"message": QUESTION}) as resp:
            print(f"HTTP {resp.status}   Content-Type: {resp.headers.get('Content-Type')}")
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\n")
                if not line:
                    continue
                stamp = time.perf_counter() - t0
                if line.startswith("event: error"):
                    got_error = True
                if '"latency_ms"' in line:
                    done_line = (stamp, line)
                    continue
                if shown < 12:
                    shown += 1
                    print(f"  +{stamp:5.2f}s  {line[:88]}")
    except Exception as exc:
        print(f"请求失败：{exc}")
        sys.exit(1)
    print("  ...（中间省略，实际是每生成一小段就来一帧）")
    if done_line:
        print(f"  +{done_line[0]:5.2f}s  {done_line[1][:140]}")
    if got_error:
        print("  [!] 收到了 error 事件，请根据上一条 data 内容排查")
    print()


def test_sync() -> None:
    print("=" * 64)
    print("2) 同步接口  POST /api/chat/sync（等全部生成完才返回）")
    print("=" * 64)
    t0 = time.perf_counter()
    try:
        with _post("/api/chat/sync", {"message": QUESTION}) as resp:
            body = json.load(resp)
    except Exception as exc:
        print(f"请求失败：{exc}")
        sys.exit(1)
    cost = (time.perf_counter() - t0) * 1000
    data = body.get("data") or {}
    print(f"用时 {cost:.0f} ms   code={body.get('code')}  message={body.get('message')}")
    reply = (data.get("reply") or "")[:80]
    print(f"reply 前 80 字：{reply}...")


if __name__ == "__main__":
    test_sse()
    test_sync()
