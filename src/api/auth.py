"""认证 API

提供登录和当前用户信息接口。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth_service import (
    create_token,
    decode_token,
    get_current_user,
    verify_password,
)

load_dotenv()
logger = logging.getLogger("api.auth")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


class UserInfo(BaseModel):
    user_id: int
    username: str
    role: str


def _parse_db_url(url: str) -> tuple[str, str]:
    from urllib.parse import parse_qs, urlparse, urlunparse

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    return clean, schema


def _get_conn() -> Any:
    clean, schema = _parse_db_url(DATABASE_URL)
    conn = psycopg2.connect(clean)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id, username, password, role FROM "User" WHERE username = %s',
                (body.username,),
            )
            user = cur.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not verify_password(body.password, user["password"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        token = create_token(user["id"], user["username"], user["role"])
        logger.info("用户登录成功: %s (role=%s)", user["username"], user["role"])

        return LoginResponse(token=token, username=user["username"], role=user["role"])
    except HTTPException:
        raise
    except Exception:
        logger.exception("登录异常")
        raise HTTPException(status_code=500, detail="服务器内部错误")
    finally:
        conn.close()


@router.get("/me", response_model=UserInfo)
def me(current_user: dict[str, Any] = Depends(get_current_user)) -> UserInfo:
    return UserInfo(
        user_id=current_user["user_id"],
        username=current_user["username"],
        role=current_user["role"],
    )
