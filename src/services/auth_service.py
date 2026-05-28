"""认证与授权服务

提供 JWT token 生成/验证、密码哈希、角色权限校验。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

load_dotenv()
logger = logging.getLogger("auth_service")

JWT_SECRET = os.getenv("JWT_SECRET", "price-monitor-jwt-secret-2026")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
JWT_ALGORITHM = "HS256"

ROLES = {"admin", "manager", "staff"}
ROLE_HIERARCHY: dict[str, set[str]] = {
    "admin": {"admin", "manager", "staff"},
    "manager": {"manager", "staff"},
    "staff": {"staff"},
}

security_scheme = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, username: str, role: str, openclaw_agent_id: str = "") -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "openclaw_agent_id": openclaw_agent_id or "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("Token 已过期")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Token 无效")
        return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭证无效或已过期",
        )

    return {
        "user_id": payload["user_id"],
        "username": payload["username"],
        "role": payload["role"],
    }


def require_role(*allowed_roles: str):
    allowed = set(allowed_roles)

    async def checker(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_role = current_user.get("role", "")
        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色: {', '.join(allowed)}",
            )
        return current_user

    return checker
