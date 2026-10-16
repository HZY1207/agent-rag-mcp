"""健康检查接口。"""
from datetime import datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="健康检查")
def health() -> ApiResponse:
    settings = get_settings()
    return ApiResponse.ok(
        {
            "status": "up",
            "app": settings.app_name,
            "version": settings.app_version,
            "env": "dev" if settings.debug else "prod",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
    )
