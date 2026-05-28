"""操作日志 API

查询用户操作日志。
权限：admin 看全部，staff 只看自己的。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.logs")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/logs", tags=["logs"])


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


def _write_log(
    user_id: int,
    username: str,
    action: str,
    target: str = "",
    method: str = "",
    path: str = "",
    ip: str = "",
    details: str = "",
) -> None:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "OperationLog" (user_id, username, action, target, method, path, ip, details) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, username, action, target, method, path, ip, details),
            )
            conn.commit()
    except Exception:
        logger.exception("写入操作日志失败")
    finally:
        if conn:
            conn.close()


@router.get("/list")
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: int | None = Query(None),
    action: str | None = Query(None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions: list[str] = []
            params: list[Any] = []

            if current_user["role"] != "admin":
                conditions.append("user_id = %s")
                params.append(current_user["user_id"])

            if user_id and current_user["role"] == "admin":
                conditions.append("user_id = %s")
                params.append(user_id)
            if action:
                conditions.append("action = %s")
                params.append(action)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            cur.execute(
                f'SELECT COUNT(*) FROM "OperationLog" {where}',
                params,
            )
            total = cur.fetchone()["count"]

            offset = (page - 1) * page_size
            cur.execute(
                f'SELECT id, user_id, username, action, target, method, path, ip, details, created_at '
                f'FROM "OperationLog" {where} ORDER BY created_at DESC LIMIT %s OFFSET %s',
                params + [page_size, offset],
            )
            items: list[dict[str, Any]] = []
            for r in cur.fetchall():
                items.append({
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "username": r["username"],
                    "action": r["action"],
                    "target": r["target"],
                    "method": r["method"],
                    "path": r["path"],
                    "ip": r["ip"],
                    "details": r["details"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception:
        logger.exception("查询操作日志失败")
        raise HTTPException(status_code=500, detail="查询操作日志失败")
    finally:
        conn.close()
