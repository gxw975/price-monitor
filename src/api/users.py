"""用户管理 API

提供用户 CRUD 和修改密码功能。
权限：admin 管理所有用户，全员可改自己的密码。
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
    get_current_user,
    hash_password,
    verify_password,
)

load_dotenv()
logger = logging.getLogger("api.users")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "staff"


class UpdateUserRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


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


def _require_admin(role: str) -> None:
    if role != "admin":
        raise HTTPException(status_code=403, detail="权限不足，仅管理员可以管理用户")


def _user_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "created_at": row["createdAt"].isoformat() if row.get("createdAt") else None,
    }


@router.get("/list")
def list_users(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id, username, role, "createdAt" FROM "User" ORDER BY "createdAt"',
            )
            items = [_user_to_dict(r) for r in cur.fetchall()]

        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询用户列表失败")
        raise HTTPException(status_code=500, detail="查询用户列表失败")
    finally:
        conn.close()


@router.post("/create")
def create_user(
    body: CreateUserRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user["role"])

    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    if body.role not in ("admin", "manager", "staff"):
        raise HTTPException(status_code=400, detail="无效的角色，可选: admin, manager, staff")

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id FROM "User" WHERE username = %s',
                (body.username,),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="用户名已存在")

            hashed = hash_password(body.password)
            cur.execute(
                'INSERT INTO "User" (username, password, role) VALUES (%s, %s, %s) RETURNING id, username, role, "createdAt"',
                (body.username, hashed, body.role),
            )
            row = cur.fetchone()
            conn.commit()

        logger.info("用户已创建: %s role=%s by %s", body.username, body.role, current_user["username"])
        return {"success": True, "item": _user_to_dict(row)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("创建用户失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="创建用户失败")
    finally:
        conn.close()


@router.put("/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT id FROM "User" WHERE id = %s', (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")

            updates: list[str] = []
            params: list[Any] = []

            if body.username is not None:
                cur.execute(
                    'SELECT id FROM "User" WHERE username = %s AND id != %s',
                    (body.username, user_id),
                )
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="用户名已存在")
                updates.append("username = %s")
                params.append(body.username)

            if body.password is not None:
                hashed = hash_password(body.password)
                updates.append("password = %s")
                params.append(hashed)

            if body.role is not None:
                if body.role not in ("admin", "manager", "staff"):
                    raise HTTPException(status_code=400, detail="无效的角色")
                updates.append("role = %s")
                params.append(body.role)

            if updates:
                params.append(user_id)
                cur.execute(
                    f'UPDATE "User" SET {", ".join(updates)} WHERE id = %s',
                    params,
                )
                conn.commit()

        logger.info("用户已更新: id=%d by %s", user_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("更新用户失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="更新用户失败")
    finally:
        conn.close()


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user["role"])

    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "Keyword" WHERE created_by = %s', (user_id,))
            cur.execute('DELETE FROM "User" WHERE id = %s', (user_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="用户不存在")
            conn.commit()

        logger.info("用户已删除: id=%d by %s", user_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除用户失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除用户失败")
    finally:
        conn.close()


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if not body.old_password or not body.new_password:
        raise HTTPException(status_code=400, detail="密码不能为空")

    if len(body.new_password) < 3:
        raise HTTPException(status_code=400, detail="新密码长度至少3位")

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT password FROM "User" WHERE id = %s',
                (current_user["user_id"],),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="用户不存在")

            if not verify_password(body.old_password, row["password"]):
                raise HTTPException(status_code=400, detail="原密码错误")

            hashed = hash_password(body.new_password)
            cur.execute(
                'UPDATE "User" SET password = %s WHERE id = %s',
                (hashed, current_user["user_id"]),
            )
            conn.commit()

        logger.info("密码已修改: user=%s", current_user["username"])
        return {"success": True, "message": "密码修改成功"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("修改密码失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="修改密码失败")
    finally:
        conn.close()
