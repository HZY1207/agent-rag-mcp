"""工程化冒烟（第 9 步）：语义缓存加速、前端托管、限流 429。

用法（先启动服务）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_engineering.py
"""
import time

import httpx

BASE = "http://127.0.0.1:8000"


def test_cache() -> None:
    print("=" * 66)
    print("1) 语义缓存：同一个问题同步问两次")
    print("=" * 66)
    payload = {"message": "VPN 账号怎么申请？", "use_kb": True}

    t0 = time.perf_counter()
    r1 = httpx.post(f"{BASE}/api/chat/sync", json=payload, timeout=180).json()["data"]
    t1 = time.perf_counter() - t0

    t0 = time.perf_counter()
    r2 = httpx.post(f"{BASE}/api/chat/sync", json=payload, timeout=180).json()["data"]
    t2 = time.perf_counter() - t0

    print(f"  第一次：{t1 * 1000:7.0f} ms   cached={r1.get('cached')}   引用 {len(r1['citations'])} 条")
    print(f"  第二次：{t2 * 1000:7.0f} ms   cached={r2.get('cached')}   cache_score={r2.get('cache_score')}")
    print(f"  加速比：{t1 / max(t2, 1e-6):.1f}x")
    same = r1["reply"] == r2["reply"]
    print(f"  两次回答一致：{'PASS' if same else 'DIFF'}")
    print(f"  缓存生效：{'PASS' if r2.get('cached') else 'FAIL'}")


def test_app_page() -> None:
    print("=" * 66)
    print("2) 生产构建托管：GET /app/")
    print("=" * 66)
    r = httpx.get(f"{BASE}/app/", timeout=30)
    ok = r.status_code == 200 and "AI Agent 智能助手平台" in r.text
    print(f"  HTTP {r.status_code}，页面标题命中：{'PASS' if ok else 'FAIL'}")


def test_rate_limit() -> None:
    print("=" * 66)
    print("3) 限流：快速请求 130 次 GET /api/sessions")
    print("=" * 66)
    codes: dict[int, int] = {}
    for _ in range(130):
        status = httpx.get(f"{BASE}/api/sessions", timeout=10).status_code
        codes[status] = codes.get(status, 0) + 1
    print(f"  状态码分布：{codes}")
    limited = codes.get(429, 0) > 0
    print(f"  出现 429：{'PASS' if limited else 'FAIL'}")
    if limited:
        r = httpx.get(f"{BASE}/api/sessions", timeout=10)
        print(f"  429 响应头 Retry-After={r.headers.get('Retry-After')}，body={r.json()}")


if __name__ == "__main__":
    test_cache()
    test_app_page()
    test_rate_limit()
