"""商品-关键词关联 API

提供商品与关键词的多对多关联管理。
权限：主管和管理员可管理关联，员工仅可查看。
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

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.product_keywords")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/product-keywords", tags=["product-keywords"])


class ProductKeywordBind(BaseModel):
    keyword_ids: list[int]


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


@router.get("/by-product/{product_id}")
def get_keywords_by_product(
    product_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT k.*, u.username AS created_by_name '
                'FROM "Keyword" k '
                'JOIN "ProductKeyword" pk ON k.id = pk.keyword_id '
                'LEFT JOIN "User" u ON k.created_by = u.id '
                "WHERE pk.product_id = %s "
                "ORDER BY k.\"createdAt\" DESC",
                (product_id,),
            )
            rows = cur.fetchall()

        keywords = []
        for r in rows:
            keywords.append({
                "id": r["id"],
                "name": r["name"],
                "platform": r["platform"],
                "is_active": r["is_active"],
                "created_by_name": r.get("created_by_name", ""),
                "created_at": r["createdAt"].isoformat() if r.get("createdAt") else None,
            })

        return {"items": keywords, "product_id": product_id, "total": len(keywords)}
    except Exception:
        logger.exception("查询商品关键词失败")
        raise HTTPException(status_code=500, detail="查询商品关键词失败")
    finally:
        conn.close()


class ProductKeywordBatchBind(BaseModel):
    product_ids: list[str]
    keyword_ids: list[int]


@router.post("/batch-bind")
def batch_bind_keywords(
    body: ProductKeywordBatchBind,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    if not body.product_ids:
        raise HTTPException(status_code=400, detail="product_ids 不能为空")
    if not body.keyword_ids:
        raise HTTPException(status_code=400, detail="keyword_ids 不能为空")

    conn = _get_conn()
    bound = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for kw_id in body.keyword_ids:
                    for pid in body.product_ids:
                        cur.execute(
                            'INSERT INTO "ProductKeyword" (keyword_id, product_id) '
                            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (kw_id, pid),
                        )
                        if cur.rowcount > 0:
                            bound += 1

            conn.commit()

        logger.info(
            "批量绑定关键词: products=%d keywords=%d bound=%d (by %s)",
            len(body.product_ids), len(body.keyword_ids), bound, current_user["username"],
        )
        return {"success": True, "bound": bound}
    except Exception:
        logger.exception("批量绑定关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="批量绑定关键词失败")
    finally:
        conn.close()


@router.put("/by-product/{product_id}")
def set_keywords_for_product(
    product_id: str,
    body: ProductKeywordBind,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT product_id FROM "Product" WHERE product_id = %s',
                    (product_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="商品不存在")

                cur.execute(
                    'DELETE FROM "ProductKeyword" WHERE product_id = %s',
                    (product_id,),
                )

                if body.keyword_ids:
                    for kw_id in body.keyword_ids:
                        cur.execute(
                            'INSERT INTO "ProductKeyword" (keyword_id, product_id) '
                            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (kw_id, product_id),
                        )

            conn.commit()

        logger.info(
            "商品关键词关联已更新: product_id=%s, keywords=%d (by %s)",
            product_id, len(body.keyword_ids), current_user["username"],
        )
        return {"success": True, "count": len(body.keyword_ids)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("设置商品关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="设置商品关键词失败")
    finally:
        conn.close()


@router.get("/by-keyword/{keyword_id}")
def get_products_by_keyword(
    keyword_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT p.product_id, p.title, p.shop_name, p.main_image_url '
                'FROM "Product" p '
                'JOIN "ProductKeyword" pk ON p.product_id = pk.product_id '
                "WHERE pk.keyword_id = %s "
                "ORDER BY p.last_updated_at DESC",
                (keyword_id,),
            )
            rows = cur.fetchall()
            items = [dict(r) for r in rows]

        return {"items": items, "keyword_id": keyword_id, "total": len(items)}
    except Exception:
        logger.exception("查询关键词商品失败")
        raise HTTPException(status_code=500, detail="查询关键词商品失败")
    finally:
        conn.close()


@router.get("/products")
def list_products(
    keyword: str | None = None,
    limit: int = 50,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if keyword:
                cur.execute(
                    'SELECT product_id, title, shop_name, main_image_url, is_approved '
                    'FROM "Product" '
                    "WHERE is_whitelist = FALSE AND (title ILIKE %s OR product_id ILIKE %s) "
                    "ORDER BY last_updated_at DESC LIMIT %s",
                    (f"%{keyword}%", f"%{keyword}%", limit),
                )
            else:
                cur.execute(
                    'SELECT product_id, title, shop_name, main_image_url, is_approved '
                    'FROM "Product" '
                    "WHERE is_whitelist = FALSE "
                    "ORDER BY last_updated_at DESC LIMIT %s",
                    (limit,),
                )
            items = [dict(r) for r in cur.fetchall()]

        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询商品列表失败")
        raise HTTPException(status_code=500, detail="查询商品列表失败")
    finally:
        conn.close()
