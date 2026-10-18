"""配置中心：集中管理所有配置项。

来源优先级：环境变量 > .env 文件 > 下方默认值。
新增配置项时：在 Settings 里加字段 + 在 .env.example 里补一行说明。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置。字段名自动映射同名环境变量（大小写不敏感）。

    例如字段 llm_api_key 对应 .env 里的 LLM_API_KEY。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env 里出现未定义的变量时不报错
    )

    # ---- 应用 ----
    app_name: str = "AI Agent 智能助手平台"
    app_version: str = "0.1.0"
    debug: bool = True

    # ---- LLM（OpenAI 兼容接口；第 2 步起使用）----
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"  # 也可换成通义/智谱等兼容地址
    llm_model: str = "deepseek-chat"

    # ---- 存储（第 3 步起使用）----
    data_dir: str = "./data"              # 运行期数据目录（已 gitignore）
    qdrant_path: str = "./data/qdrant"    # Qdrant 本地模式持久化目录

    # ---- 知识库 / RAG（第 3 步起使用）----
    embed_model: str = "BAAI/bge-small-zh-v1.5"  # 本地向量模型（fastembed，支持中文）
    hf_endpoint: str = "https://hf-mirror.com"   # HuggingFace 下载镜像（海外网络可改 https://huggingface.co）
    kb_collection: str = "knowledge"             # Qdrant 集合名
    kb_chunk_size: int = 500                     # 切片长度（字符）
    kb_chunk_overlap: int = 50                   # 相邻切片重叠（字符）
    kb_top_k: int = 3                            # 每次检索返回的切片数
    kb_score_threshold: float = 0.43             # 相似度低于此值不注入（实测底噪 0.40 / 相关 0.46 的中间值）

    # ---- 向量库连接方式（第 9 步 Docker 部署用）----
    qdrant_url: str = ""           # 填了就走服务端模式（如 http://qdrant:6333）；留空 = 本地文件模式
    fastembed_cache_path: str = ""  # 向量模型缓存目录（Docker 里挂卷用）；留空 = 系统默认位置

    # ---- MCP（第 5 步起使用）----
    mcp_config_path: str = "./mcp_servers.json"  # MCP 服务器配置文件路径

    # ---- 会话存储（第 7 步起使用）----
    session_db: str = "./data/sessions.sqlite3"  # SQLite 会话数据库

    # ---- 语义缓存（第 9 步起使用）----
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.96       # 查询向量余弦相似度超过该值视为"同一个问题"
    semantic_cache_ttl: int = 3600               # 缓存有效期（秒）

    # ---- 限流（第 9 步起使用）----
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120             # 每 IP 每分钟请求上限（评测脚本等批量调用时注意）


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例：整个进程只解析一次 .env。"""
    return Settings()
