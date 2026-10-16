"""RAG 链路冒烟测试：上传示例文档 → 向量检索 → 带引用的流式问答。

用法（先启动服务）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\smoke_rag.py

说明：依赖 httpx（随项目依赖自带）。首次上传会触发向量模型下载（约几十 MB）。
"""
import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "星尘科技员工手册.md"


def upload() -> None:
    print("=" * 64)
    print("1) 上传文档入库  POST /api/knowledge/upload")
    print("=" * 64)
    t0 = time.perf_counter()
    resp = httpx.post(
        f"{BASE}/api/knowledge/upload",
        files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/markdown")},
        timeout=300,
    )
    body = resp.json()
    print(f"用时 {time.perf_counter() - t0:.1f}s  code={body['code']}")
    print(f"data = {json.dumps(body['data'], ensure_ascii=False)}")
    print()


def search(query: str) -> None:
    print("=" * 64)
    print(f"2) 向量检索  POST /api/knowledge/search  query={query!r}")
    print("=" * 64)
    resp = httpx.post(f"{BASE}/api/knowledge/search", json={"query": query, "top_k": 3}, timeout=120)
    data = resp.json()["data"]
    print(f"共 {len(data)} 条命中：")
    for hit in data:
        print(f"  score={hit['score']:<7} [{hit['filename']}] {hit['text'][:36]}...")
    print()


def chat(question: str) -> None:
    print("=" * 64)
    print(f"3) 带引用的流式问答  POST /api/chat  question={question!r}")
    print("=" * 64)
    t0 = time.perf_counter()
    answer_parts: list[str] = []
    with httpx.stream(
        "POST", f"{BASE}/api/chat", json={"message": question, "use_kb": True}, timeout=180
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
                if event == "citations":
                    print(f"  {stamp}  [citations] {data[:170]}")
                elif event == "delta":
                    answer_parts.append(json.loads(data)["content"])
                elif event == "done":
                    print(f"  {stamp}  [done] {data}")
                else:
                    print(f"  {stamp}  [{event}] {data[:170]}")
    print()
    print("模型回答：", "".join(answer_parts))
    print()


if __name__ == "__main__":
    if not SAMPLE.exists():
        raise SystemExit(f"示例文件不存在：{SAMPLE}")
    upload()
    search("年假有多少天")
    chat("星尘科技的年假是多少天？需要提前多久申请？")
    chat("出差补贴标准是多少？")  # 故意问手册里没有的，观察模型如何声明"不知道"
