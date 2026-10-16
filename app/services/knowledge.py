"""知识库服务（RAG 核心）：文档解析 → 切片 → 向量化 → 入库/检索。

概念速览（详见 docs/03 教学笔记）：
- Embedding 向量化：把文本变成一串数字（本模型：512 维），语义相近的文本向量也相近；
- Collection 集合：向量库里的"表"；每个 Point = 一个向量 + 一份 payload（附带元数据）；
- Chunk 切片：长文档先切成小段再向量化，让"检索粒度"变细、命中更准；
- 本文件里的函数都是【同步】的（CPU 密集），由路由层用 asyncio.to_thread 丢进
  线程池执行——这是 async 服务里跑重活的标准姿势，否则会卡死整个事件循环。
"""
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings

logger = logging.getLogger("app.knowledge")

# 必须在 fastembed/huggingface_hub 首次使用之前设置（模块导入时生效）
_settings = get_settings()
if _settings.hf_endpoint:
    os.environ.setdefault("HF_ENDPOINT", _settings.hf_endpoint)
# HF 新的 Xet 传输后端不走镜像站（会直连 cas-server.xethub.hf.co，报 401），
# 禁用后回退到普通 HTTP 下载，HF_ENDPOINT 镜像才能真正生效
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 中文友好的递归分隔符：按"段落 → 行 → 句号/问号/叹号 → 分号 → 逗号 → 字符"逐级切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

# 进程内单例：
# - Qdrant 本地模式对同一目录有文件锁，必须单例复用
# - 向量模型加载慢（首次还要下载），也必须复用
_embedder = None
_client: QdrantClient | None = None


def _get_embedder():
    """加载向量模型（首次运行会自动从 HuggingFace 下载，约几十 MB）。"""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        logger.info("正在加载向量模型 %s（首次运行会自动下载）...", _settings.embed_model)
        _embedder = TextEmbedding(model_name=_settings.embed_model)
        logger.info("向量模型 %s 就绪", _settings.embed_model)
    return _embedder


def _get_client() -> QdrantClient:
    """Qdrant 本地模式客户端：数据落在 qdrant_path 目录，零服务端、零 Docker。"""
    global _client
    if _client is None:
        Path(_settings.qdrant_path).mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=_settings.qdrant_path)
        logger.info("Qdrant 本地模式已就绪：%s", _settings.qdrant_path)
    return _client


def _ensure_collection() -> QdrantClient:
    """确保集合存在（用一次"试编码"拿到向量维度后建集合）。"""
    client = _get_client()
    if not client.collection_exists(_settings.kb_collection):
        probe = next(iter(_get_embedder().embed(["维度探测"])))
        client.create_collection(
            collection_name=_settings.kb_collection,
            vectors_config=VectorParams(size=len(probe), distance=Distance.COSINE),
        )
        logger.info("已创建向量集合 %s（维度 %d，距离度量 Cosine）", _settings.kb_collection, len(probe))
    return client


def _decode(data: bytes) -> str:
    """尽力解码文本文件：UTF-8（含 BOM）优先，其次 GBK。"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码（支持 UTF-8 / GBK）")


def _extract_pages(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """解析文件 → [(页码或 None, 文本), ...]；支持 txt / md / pdf。"""
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        return [(None, _decode(data))]
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pages: list[tuple[int | None, str]] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((i, text))
        return pages
    raise ValueError(f"暂不支持的文件类型：{suffix}（支持 .txt / .md / .pdf）")


def _split(pages: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    """把每页文本切成带重叠的片段（chunk）。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_settings.kb_chunk_size,
        chunk_overlap=_settings.kb_chunk_overlap,
        separators=SEPARATORS,
    )
    chunks: list[tuple[int | None, str]] = []
    for page, text in pages:
        for piece in splitter.split_text(text):
            piece = piece.strip()
            if piece:
                chunks.append((page, piece))
    return chunks


@dataclass
class Hit:
    """一条检索结果。"""

    doc_id: str
    filename: str
    page: int | None
    chunk_index: int
    score: float
    text: str


def ingest(filename: str, data: bytes) -> dict:
    """文档入库：解析 → 切片 → 批量向量化 → 写入 Qdrant。

    用文件内容的 sha1 前 12 位作为 doc_id（内容指纹）：
    同一份文件重复上传 = 同一个 doc_id → 先删旧切片再写新切片，天然幂等。
    """
    client = _ensure_collection()

    pages = _extract_pages(filename, data)
    chunks = _split(pages)
    if not chunks:
        raise ValueError("没有从文件中提取到可用文本")

    vectors = list(_get_embedder().embed([text for _, text in chunks]))  # 批量编码更快

    doc_id = hashlib.sha1(data).hexdigest()[:12]
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec.tolist(),
            payload={
                "doc_id": doc_id,
                "filename": filename,
                "page": page,
                "chunk_index": i,
                "text": text,
            },
        )
        for i, ((page, text), vec) in enumerate(zip(chunks, vectors))
    ]

    client.delete(
        collection_name=_settings.kb_collection,
        points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
    )
    client.upsert(collection_name=_settings.kb_collection, points=points)
    logger.info("入库完成：%s → %d 个切片（doc_id=%s）", filename, len(points), doc_id)
    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunks": len(points),
        "chars": sum(len(text) for _, text in chunks),
    }


def list_documents() -> list[dict]:
    """列出已入库文档（按 doc_id 聚合切片数）。"""
    client = _get_client()
    if not client.collection_exists(_settings.kb_collection):
        return []
    docs: dict[str, dict] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=_settings.kb_collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            payload = p.payload or {}
            did = str(payload.get("doc_id", "?"))
            item = docs.setdefault(
                did,
                {"doc_id": did, "filename": payload.get("filename", "?"), "chunks": 0, "pages": set()},
            )
            item["chunks"] += 1
            if payload.get("page"):
                item["pages"].add(payload["page"])
        if offset is None:
            break
    return [{**d, "pages": sorted(d["pages"])} for d in docs.values()]


def search(query: str, top_k: int | None = None) -> list[Hit]:
    """向量检索：问题 → 编码成向量 → 找最相似的 top_k 个切片。"""
    client = _get_client()
    if not client.collection_exists(_settings.kb_collection):
        return []
    query_vec = next(iter(_get_embedder().embed([query])))
    result = client.query_points(
        collection_name=_settings.kb_collection,
        query=query_vec.tolist(),
        limit=top_k or _settings.kb_top_k,
        with_payload=True,
    )
    hits: list[Hit] = []
    for p in result.points:
        payload = p.payload or {}
        hits.append(
            Hit(
                doc_id=str(payload.get("doc_id", "")),
                filename=str(payload.get("filename", "")),
                page=payload.get("page"),
                chunk_index=int(payload.get("chunk_index", 0)),
                score=round(float(p.score), 4),
                text=str(payload.get("text", "")),
            )
        )
    return hits


def retrieve_context(query: str) -> tuple[str, list[dict]]:
    """给对话用的检索：过滤低分结果，组装"参考资料"文本块 + 引用清单。

    返回 (context_block, citations)：
      - context_block 直接拼进 system 提示词，编号 [1][2]... 与 citations 一一对应；
      - citations 推给前端展示引用来源。
    知识库为空 / 分数不达标时返回空（不影响普通对话）。
    """
    try:
        hits = search(query)
    except Exception:  # 检索失败不应阻断对话（例如模型还没下载好）
        logger.exception("知识库检索失败，本轮按无资料回答")
        return "", []
    useful = [h for h in hits if h.score >= _settings.kb_score_threshold]
    if not useful:
        return "", []
    blocks: list[str] = []
    citations: list[dict] = []
    for i, h in enumerate(useful, start=1):
        loc = f"第 {h.page} 页" if h.page else "全文"
        blocks.append(f"[{i}] 来源：{h.filename}（{loc}）\n{h.text}")
        citations.append(
            {
                "index": i,
                "doc_id": h.doc_id,
                "filename": h.filename,
                "page": h.page,
                "score": h.score,
                "snippet": h.text[:120],
            }
        )
    return "\n\n".join(blocks), citations
