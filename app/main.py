"""FastAPI 应用入口。

启动：python -m uvicorn app.main:app --reload --port 8000
文档：http://127.0.0.1:8000/docs
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("app")

settings = get_settings()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期钩子：启动前 / 关闭后各执行一次。

    后续步骤会在这里初始化：向量库连接、SQLite 建表、MCP 客户端等。
    """
    logger.info("启动 %s v%s (debug=%s)", settings.app_name, settings.app_version, settings.debug)
    yield
    logger.info("服务已关闭")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agent + RAG + MCP 智能助手平台",
    lifespan=lifespan,
    docs_url=None,   # 关闭默认 /docs：它依赖外网 CDN 加载 Swagger UI，国内会白屏
    redoc_url=None,  # 同理关闭 /redoc（以后需要时再本地化引入）
)

# 跨域配置：浏览器前端（Vue 开发服务器 :5173）访问本服务时需要
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 业务接口统一挂载在 /api 前缀下
app.include_router(api_router, prefix="/api")

# 静态资源目录：Swagger UI 的 JS/CSS 已本地化到 app/static/（来源见 docs/01 常见问题）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/docs", include_in_schema=False)
def custom_docs():
    """接口文档页：用本地静态资源渲染 Swagger UI。

    FastAPI 默认从 cdn.jsdelivr.net 加载 swagger-ui 资源，国内网络不稳定时会白屏；
    改为本地文件后：离线可用、加载更快、不受 CDN 波动影响。
    """
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{settings.app_name} - API 文档",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon.png",
    )


@app.get("/", summary="根路径", tags=["meta"])
def root():
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}
