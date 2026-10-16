"""知识库相关的请求模型。"""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """向量检索请求（调试用，方便直接观察相似度分数）。"""

    query: str = Field(min_length=1, max_length=2000, description="检索词/问题")
    top_k: int = Field(default=3, ge=1, le=20, description="返回条数")
