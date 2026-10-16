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


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例：整个进程只解析一次 .env。"""
    return Settings()
