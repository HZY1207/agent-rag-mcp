"""会话与消息持久化（SQLite，零额外依赖）。

设计说明：
- 用标准库 sqlite3：会话数据量小、单机部署够用（要上多实例时再换 PostgreSQL/Redis）；
- 连接单例 + 线程锁：FastAPI 的同步调用可能落在不同线程（check_same_thread=False），
  再用一把锁把写入串行化，避免并发写冲突；
- 时间统一存 ISO 8601 字符串（可读、可直接排序）；
- WAL 模式：读写并发更好（SQLite 的标准实践）。

表结构：
  sessions(id, title, created_at, updated_at)
  messages(id, session_id, role, content, citations, created_at)
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.schemas.chat import ChatMessage

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db_path = Path(get_settings().session_db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(db_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions(
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages(
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                citations  TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            """
        )
        _conn.commit()
    return _conn


# ---------------- 会话 ----------------


def create_session(title: str = "新会话") -> dict:
    sid = uuid.uuid4().hex[:12]
    now = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES(?,?,?,?)",
            (sid, title, now, now),
        )
        conn.commit()
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "message_count": 0}


def ensure_session(session_id: str, title: str = "新会话") -> dict:
    """会话不存在就创建（幂等）。让带 session_id 的对话接口更宽容。"""
    if get_session(session_id):
        return get_session(session_id)
    now = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO sessions(id, title, created_at, updated_at) VALUES(?,?,?,?)",
            (session_id, title, now, now),
        )
        conn.commit()
    return get_session(session_id)


def list_sessions() -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def rename_session(session_id: str, title: str) -> bool:
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), session_id)
        )
        conn.commit()
    return cur.rowcount > 0


def delete_session(session_id: str) -> bool:
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
    return cur.rowcount > 0


# ---------------- 消息 ----------------


def get_messages(session_id: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT role, content, citations, created_at FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        item = dict(r)
        if item.get("citations"):
            item["citations"] = json.loads(item["citations"])
        out.append(item)
    return out


def add_message(session_id: str, role: str, content: str, citations: list | None = None) -> None:
    now = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages(session_id, role, content, citations, created_at) VALUES(?,?,?,?,?)",
            (
                session_id,
                role,
                content,
                json.dumps(citations, ensure_ascii=False) if citations else None,
                now,
            ),
        )
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        conn.commit()


def auto_title(session_id: str, first_message: str) -> None:
    """用首条消息生成会话标题（截断 20 字符）。"""
    title = " ".join(first_message.split())[:20] or "新会话"
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), session_id))
        conn.commit()


# ---------------- 对话接口的公共脚手架 ----------------


def prepare_session_chat(session_id: str, message: str, recent: int = 20) -> list[ChatMessage]:
    """带会话的一次对话开始前：确保会话存在 → 读历史 → 记录本轮用户消息。

    返回模型需要的「历史消息列表」（不含本轮消息；最近 recent 条，控制 token）。
    会话不存在会自动创建；首条消息自动生成会话标题。
    """
    ensure_session(session_id)
    stored = get_messages(session_id)
    history = [
        ChatMessage(role=m["role"], content=m["content"])
        for m in stored[-recent:]
        if m["role"] in ("user", "assistant")
    ]
    if not stored:
        auto_title(session_id, message)
    add_message(session_id, "user", message)
    return history


def finish_session_chat(session_id: str, reply: str, citations: list | None = None) -> None:
    """回答生成完后：把助手回复（含引用）写入会话。"""
    if reply:
        add_message(session_id, "assistant", reply, citations)
