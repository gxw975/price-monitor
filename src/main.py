"""Price Monitor API Server

FastAPI application serving the price monitor backend API.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.alerts import router as alerts_router
from api.auth import router as auth_router
from api.cron import router as cron_router
from api.dashboard import router as dashboard_router
from api.diagnostics import router as diagnostics_router
from api.import_export import router as import_export_router
from api.keywords import router as keywords_router
from api.logs import router as logs_router
from api.notifications import router as notifications_router
from api.product_keywords import router as product_keywords_router
from api.products import router as products_router
from api.push import router as push_router
from api.service import router as service_router
from api.settings import router as settings_router
from api.users import router as users_router
from services.auth_service import decode_token

logger = logging.getLogger("main")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

app = FastAPI(
    title="电商低价监控系统 API",
    version="1.0.0",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SKIP_AUTH_PATHS = {"/api/auth/login", "/api/health", "/api/docs", "/openapi.json"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in SKIP_AUTH_PATHS or not request.url.path.startswith("/api/"):
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "未提供认证凭证"},
        )

    token = auth_header[7:]
    payload = decode_token(token)
    if payload is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "认证凭证无效或已过期"},
        )

    request.state.user = payload
    return await call_next(request)


WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
OPLOG_SKIP_PATHS = {"/api/notifications/count", "/api/auth/login", "/api/health", "/api/docs"}


@app.middleware("http")
async def operation_log_middleware(request: Request, call_next):
    response = await call_next(request)

    if not request.url.path.startswith("/api/"):
        return response
    if request.method not in WRITE_METHODS:
        return response
    if request.url.path in OPLOG_SKIP_PATHS:
        return response
    if not hasattr(request.state, "user"):
        return response

    user = request.state.user
    path = request.url.path
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")

    action_map: dict[tuple[str, str], str] = {
        ("POST", "/api/alerts/mark-read"): "标记预警已读",
        ("POST", "/api/alerts/mark-processed"): "标记预警已处理",
        ("POST", "/api/alerts/batch-delete"): "批量删除预警",
        ("POST", "/api/keywords/create"): "创建关键词",
        ("PUT", "/api/keywords"): "更新关键词",
        ("DELETE", "/api/keywords"): "删除关键词",
        ("POST", "/api/keywords/batch-toggle"): "批量切换关键词",
        ("POST", "/api/product-keywords/batch-bind"): "批量绑定关键词",
        ("PUT", "/api/product-keywords/by-product"): "设置商品关键词",
        ("POST", "/api/import/products"): "导入商品",
        ("POST", "/api/import/keywords"): "导入关键词",
        ("POST", "/api/users/create"): "创建用户",
        ("PUT", "/api/users"): "更新用户",
        ("DELETE", "/api/users"): "删除用户",
        ("POST", "/api/users/change-password"): "修改密码",
        ("PUT", "/api/settings"): "修改系统设置",
        ("POST", "/api/service/restart"): "重启服务",
        ("POST", "/api/service/stop"): "停止服务",
        ("POST", "/api/service/start"): "启动服务",
        ("POST", "/api/push/test"): "测试推送",
        ("POST", "/api/diagnostics/maintenance"): "维护操作",
    }

    action_label = "API 操作"
    for (method, prefix), label in action_map.items():
        if request.method == method and path.startswith(prefix):
            action_label = label
            break

    try:
        from api.logs import _write_log
        _write_log(
            user_id=user["user_id"],
            username=user["username"],
            action=action_label,
            target="",
            method=request.method,
            path=path,
            ip=ip,
            details="",
        )
    except Exception:
        pass

    return response


app.include_router(auth_router)
app.include_router(alerts_router)
app.include_router(cron_router)
app.include_router(dashboard_router)
app.include_router(diagnostics_router)
app.include_router(import_export_router)
app.include_router(keywords_router)
app.include_router(logs_router)
app.include_router(notifications_router)
app.include_router(product_keywords_router)
app.include_router(products_router)
app.include_router(push_router)
app.include_router(service_router)
app.include_router(settings_router)
app.include_router(users_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=3001, reload=True)
