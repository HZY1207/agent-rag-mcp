"""简单限流（第 9 步）：滑动窗口，按 IP 限制请求频率。

实现说明：
- 滑动窗口用 deque 存每个 IP 最近的请求时间戳，窗口 60 秒；
- 单机内存实现，适合单实例部署；多实例要换 Redis（同样的滑动窗口逻辑）；
- 只统计 /api 下的请求；健康检查与 OPTIONS 预检不计入；
- 超过阈值返回 429 + 统一响应体（code=4290），并带 Retry-After 响应头。

局限：内存表随不同 IP 增长（做了简单防膨胀）；NAT 后多个用户共享 IP 会共享额度。
"""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

_WINDOW_SECONDS = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        path = request.url.path
        if (
            not settings.rate_limit_enabled
            or request.method == "OPTIONS"
            or not path.startswith("/api")
            or path == "/api/health"
        ):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[ip]
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= settings.rate_limit_per_minute:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - hits[0])))
            return JSONResponse(
                status_code=429,
                content={
                    "code": 4290,
                    "message": (
                        f"请求过于频繁（{settings.rate_limit_per_minute} 次/分钟），"
                        f"请 {retry_after} 秒后重试"
                    ),
                    "data": None,
                },
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        if len(self._hits) > 10000:  # 简单防膨胀：极端多 IP 时整体重置
            self._hits.clear()
        return await call_next(request)
