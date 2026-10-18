"""语义缓存（第 9 步）：相似问题直接复用历史回答，省掉一次完整的 LLM 调用。

原理（三段式）：
1. 用与检索相同的向量模型把问题编码；
2. 与缓存中所有历史问题的向量算余弦相似度（向量已归一化 → 点积即余弦）；
3. 超过阈值（默认 0.96）视为"同一个问题"，直接返回缓存答案。

为什么阈值这么高：语义缓存宁可不命中，也不能答错——
"年假多少天"和"病假多少天"的向量相似度也可能有 0.9，但答案完全不同。
0.96 基本只放过"换个说法 / 多几个标点"的问法。

注意：这是进程内缓存，单实例有效、重启即失效；
多实例部署应换成 Redis（保持 get/put 接口不变即可平滑替换）。
"""
import logging
import threading
import time

import numpy as np

from app.core.config import get_settings
from app.services.knowledge import embed_query

logger = logging.getLogger("app.cache")

_MAX_ENTRIES = 500  # 容量上限：超出后淘汰最旧的条目


class SemanticCache:
    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    @staticmethod
    def _normalize(vector: list[float]) -> np.ndarray:
        v = np.asarray(vector, dtype=np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    def get(self, question: str) -> dict | None:
        """命中则返回 {"answer", "citations", "score"}，否则 None。"""
        settings = get_settings()
        if not settings.semantic_cache_enabled:
            return None
        now = time.time()
        with self._lock:
            # 惰性清理过期条目
            self._entries = [
                e for e in self._entries if now - e["ts"] < settings.semantic_cache_ttl
            ]
            entries = list(self._entries)
        if not entries:
            return None
        try:
            qvec = self._normalize(embed_query(question))
        except Exception:
            logger.exception("语义缓存：查询向量化失败")
            return None

        best, best_score = None, 0.0
        for entry in entries:
            score = float(np.dot(qvec, entry["vector"]))
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= settings.semantic_cache_threshold:
            logger.info("语义缓存命中（相似度 %.4f）：%s", best_score, question[:40])
            return {
                "answer": best["answer"],
                "citations": best["citations"],
                "score": best_score,
            }
        return None

    def put(self, question: str, answer: str, citations: list) -> None:
        settings = get_settings()
        if not settings.semantic_cache_enabled or not answer:
            return
        try:
            vector = self._normalize(embed_query(question))
        except Exception:
            logger.exception("语义缓存：写入向量化失败")
            return
        with self._lock:
            self._entries = [e for e in self._entries if e["question"] != question]
            self._entries.append(
                {
                    "vector": vector,
                    "question": question,
                    "answer": answer,
                    "citations": citations,
                    "ts": time.time(),
                }
            )
            if len(self._entries) > _MAX_ENTRIES:
                self._entries = self._entries[-_MAX_ENTRIES:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "enabled": get_settings().semantic_cache_enabled}


semantic_cache = SemanticCache()
