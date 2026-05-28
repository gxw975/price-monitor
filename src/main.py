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


app.include_router(auth_router)
app.include_router(alerts_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=3001, reload=True)
