"""RAG + Agent 端到端评测（第 10 步）。

指标：
- 检索 Hit@3 / MRR：top-3 切片中是否出现"证据关键词"，以及首次出现的位置
- 回答关键词覆盖率：期望关键词在最终回答中的占比（衡量生成是否完整）
- 拒答准确率：知识库外的问题，是否明确表示"不知道/没有相关资料"
- 计算准确率：计算器问题的最终数字是否正确
- 延迟：端到端 P50 / P95

用法（先启动服务；建议评测前重启服务，清空语义缓存）：
    .venv\\Scripts\\python.exe -X utf8 scripts\\evaluate.py
"""
import json
import statistics
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = ROOT / "eval" / "qa_set.json"
REPORT_FILE = ROOT / "eval" / "report.json"

REFUSAL_MARKERS = [
    "没有相关",
    "未提供",
    "无法",
    "不知道",
    "没有提到",
    "未提及",
    "没有找到",
    "知识库中没有",
    "无法回答",
    "不清楚",
    "未包含",
    "没有收录",
    "无法确定",
    "抱歉",
]


def api_post(path: str, payload: dict, timeout: float = 180) -> dict:
    resp = httpx.post(f"{BASE}{path}", json=payload, timeout=timeout)
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{path} 失败：{body}")
    return body["data"]


def agent_chat(question: str) -> dict:
    """调用 Agent SSE 接口，收集回答、引用、工具调用与统计。"""
    parts: list[str] = []
    citations: list[dict] = []
    tools: list[str] = []
    stats: dict = {}
    error = ""
    with httpx.stream(
        "POST", f"{BASE}/api/agent/chat", json={"message": question}, timeout=180
    ) as resp:
        event = ""
        for line in resp.iter_lines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                if event == "delta":
                    parts.append(payload.get("content", ""))
                elif event == "step" and payload.get("phase") == "tool_call":
                    tools.append(payload.get("name", ""))
                elif event == "citations":
                    citations = payload.get("items", [])
                elif event == "done":
                    stats = payload
                elif event == "error":
                    error = payload.get("message", "")
    return {
        "answer": "".join(parts).strip(),
        "citations": citations,
        "tools": tools,
        "stats": stats,
        "error": error,
    }


def retrieve(question: str, top_k: int = 3) -> list[dict]:
    return api_post("/api/knowledge/search", {"query": question, "top_k": top_k}, timeout=60)


def rank_of(hits: list[dict], evidence: list[str]) -> int:
    """第一个命中证据关键词的切片名次（从 1 开始；0 = 未命中）。"""
    for i, hit in enumerate(hits, start=1):
        text = hit.get("text", "")
        if any(keyword in text for keyword in evidence):
            return i
    return 0


def coverage(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    hit = sum(1 for keyword in keywords if keyword in answer)
    return hit / len(keywords)


def evaluate_item(item: dict) -> dict:
    question = item["question"]
    t0 = time.perf_counter()
    reply = agent_chat(question)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    answer = reply["answer"]

    row = {
        "id": item["id"],
        "type": item["type"],
        "question": question,
        "note": item.get("note", ""),
        "answer": answer[:600],
        "latency_ms": reply["stats"].get("latency_ms", elapsed_ms),
        "client_elapsed_ms": elapsed_ms,
        "cached": reply["stats"].get("cached", False),
        "tools": reply["tools"],
        "citation_count": len(reply["citations"]),
        "error": reply["error"],
    }

    if item["type"] == "kb":
        hits = retrieve(question)
        rank = rank_of(hits, item["evidence"])
        cov = coverage(answer, item["expected_keywords"])
        row.update(
            {
                "hit_at_3": rank > 0,
                "rank": rank,
                "coverage": round(cov, 3),
                "retrieval_scores": [h.get("score") for h in hits],
                "pass": bool(rank > 0 and cov == 1.0),
            }
        )
    elif item["type"] == "refusal":
        refused = any(marker in answer for marker in REFUSAL_MARKERS)
        row.update({"refused": refused, "pass": refused})
    else:  # calc
        expected = item["expected_keywords"][0]
        row.update({"expected": expected, "pass": expected in answer})

    row["pass"] = bool(row["pass"])
    return row


def main() -> None:
    items = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    rows: list[dict] = []
    print(f"评测集：{len(items)} 题（{EVAL_FILE}）")
    print("=" * 100)

    for i, item in enumerate(items, start=1):
        row = evaluate_item(item)
        rows.append(row)
        icon = "PASS" if row["pass"] else "FAIL"
        print(
            f"[{i:02d}/{len(items)}] {icon} {row['id']:<20} "
            f"{row['latency_ms']:>6} ms  工具 {len(row['tools'])}  引用 {row['citation_count']}"
        )
        print(f"       Q: {row['question']}")
        print(f"       A: {row['answer'][:120].replace(chr(10), ' ')}")

    kb = [r for r in rows if r["type"] == "kb"]
    refusals = [r for r in rows if r["type"] == "refusal"]
    calcs = [r for r in rows if r["type"] == "calc"]

    latencies = [r["latency_ms"] for r in rows]
    summary = {
        "total": len(rows),
        "kb_total": len(kb),
        "hit_at_3": round(sum(r["hit_at_3"] for r in kb) / len(kb), 4),
        "mrr": round(sum(1 / r["rank"] if r["rank"] else 0.0 for r in kb) / len(kb), 4),
        "keyword_coverage": round(statistics.mean(r["coverage"] for r in kb), 4),
        "full_keyword_match": round(sum(r["coverage"] == 1.0 for r in kb) / len(kb), 4),
        "citation_rate": round(sum(1 for r in kb if r["citation_count"] > 0) / len(kb), 4),
        "refusal_accuracy": round(sum(r["refused"] for r in refusals) / len(refusals), 4),
        "calc_accuracy": round(sum(r["pass"] for r in calcs) / len(calcs), 4),
        "latency_p50_ms": int(statistics.median(latencies)),
        "latency_p95_ms": int(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]),
        "avg_latency_ms": int(statistics.mean(latencies)),
    }

    print("=" * 100)
    print("汇总指标：")
    for key, value in summary.items():
        print(f"  {key:<22} {value}")

    REPORT_FILE.write_text(
        json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n报告已写入：{REPORT_FILE}")


if __name__ == "__main__":
    main()
