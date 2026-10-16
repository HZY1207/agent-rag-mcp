"""统一响应体：{code, message, data}。

所有普通 JSON 接口都返回这个结构，前端可以写一套统一处理逻辑。
注意：SSE 流式接口（如后续的 /api/chat）是例外，它逐条推送事件而不是一次性 JSON。
"""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0              # 0 表示成功；非 0 为业务错误码（后续统一定义）
    message: str = "ok"
    data: T | None = None

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, code: int, message: str) -> "ApiResponse":
        return cls(code=code, message=message, data=None)
