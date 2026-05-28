"""关键词管理 API

提供关键词的增删改查功能。
权限：主管(manager)和管理员(admin)能增删改查，员工(staff)仅可查看。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.keywords")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


class KeywordCreate(BaseModel):
    name: str
    platform: str = "taobao"


class KeywordUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    is_active: bool | None = None


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


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _keyword_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "is_active": row["is_active"],
        "created_by": row["created_by"],
        "created_by_name": row.get("created_by_name", ""),
        "product_count": int(row.get("product_count", 0) or 0),
        "crawled_today": int(row.get("crawled_today", 0) or 0),
        "last_crawl_time": row.get("last_crawl_time").isoformat() if row.get("last_crawl_time") else None,
        "created_at": row["createdAt"].isoformat() if row.get("createdAt") else None,
    }


@router.get("/list")
def list_keywords(
    is_active: bool | None = None,
    platform: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions: list[str] = []
            params: list[Any] = []

            if is_active is not None:
                conditions.append("k.is_active = %s")
                params.append(is_active)
            if platform:
                conditions.append("k.platform = %s")
                params.append(platform)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            cur.execute(
                'SELECT k.*, u.username AS created_by_name, '
                "COUNT(pk.product_id) AS product_count, "
                "MAX(ph.recorded_at) AS last_crawl_time, "
                "COUNT(DISTINCT CASE WHEN ph.recorded_at::date = CURRENT_DATE THEN pk.product_id END) AS crawled_today "
                'FROM "Keyword" k '
                'LEFT JOIN "User" u ON k.created_by = u.id '
                'LEFT JOIN "ProductKeyword" pk ON k.id = pk.keyword_id '
                'LEFT JOIN "ProductHistory" ph ON ph.product_id = pk.product_id '
                f"{where} "
                "GROUP BY k.id, u.username "
                "ORDER BY k.\"createdAt\" DESC",
                params,
            )
            items = [_keyword_to_dict(r) for r in cur.fetchall()]

        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询关键词列表失败")
        raise HTTPException(status_code=500, detail="查询关键词列表失败")
    finally:
        conn.close()


@router.post("/create")
def create_keyword(
    body: KeywordCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id FROM "Keyword" WHERE name = %s AND platform = %s',
                (body.name, body.platform),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="关键词已存在")

            cur.execute(
                'INSERT INTO "Keyword" (name, platform, created_by) '
                "VALUES (%s, %s, %s) RETURNING id",
                (body.name, body.platform, current_user["user_id"]),
            )
            keyword_id = cur.fetchone()["id"]
            conn.commit()

            cur.execute(
                'SELECT k.*, u.username AS created_by_name '
                'FROM "Keyword" k '
                'LEFT JOIN "User" u ON k.created_by = u.id '
                "WHERE k.id = %s",
                (keyword_id,),
            )
            row = cur.fetchone()
            if row:
                item = _keyword_to_dict(row)
        logger.info("关键词已创建: %s (by %s)", body.name, current_user["username"])
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception:
        logger.exception("创建关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="创建关键词失败")
    finally:
        conn.close()


@router.put("/{keyword_id}")
def update_keyword(
    keyword_id: int,
    body: KeywordUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT id FROM "Keyword" WHERE id = %s', (keyword_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="关键词不存在")

            updates: list[str] = []
            params: list[Any] = []

            if body.name is not None:
                updates.append("name = %s")
                params.append(body.name)
            if body.platform is not None:
                updates.append("platform = %s")
                params.append(body.platform)
            if body.is_active is not None:
                updates.append("is_active = %s")
                params.append(body.is_active)

            if updates:
                params.append(keyword_id)
                cur.execute(
                    f'UPDATE "Keyword" SET {", ".join(updates)} WHERE id = %s',
                    params,
                )
                conn.commit()

        logger.info("关键词已更新: id=%d (by %s)", keyword_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("更新关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="更新关键词失败")
    finally:
        conn.close()


@router.delete("/{keyword_id}")
def delete_keyword(
    keyword_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "ProductKeyword" WHERE keyword_id = %s', (keyword_id,))
            cur.execute('DELETE FROM "Keyword" WHERE id = %s', (keyword_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="关键词不存在")
            conn.commit()

        logger.info("关键词已删除: id=%d (by %s)", keyword_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除关键词失败")
    finally:
        conn.close()
