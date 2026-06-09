"""商品管理 API

提供商品详情查询、Excel导入、价格历史、关联关键词和预警记录。
权限：查看全员可访问，导入仅admin/manager。
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.products")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/products", tags=["商品管理"])


def _check_write_permission(role: str) -> None:
    """校验写入权限：仅管理员和主管可操作"""
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def require_write_permission(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """FastAPI 依赖：校验写入权限"""
    _check_write_permission(current_user["role"])
    return current_user


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


@router.get("/{product_id}")
def get_product_detail(
    product_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT product_id, title, main_image_url, shop_name, shop_type, '
                "shipping_area, is_approved, is_whitelist, created_at, last_updated_at, "
                'last_sku_crawled_at FROM "Product" WHERE product_id = %s',
                (product_id,),
            )
            product = cur.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="商品不存在")

            thirty_days_ago = date.today() - timedelta(days=29)
            cur.execute(
                "SELECT DATE(recorded_at) AS record_date, "
                "MIN(price) AS min_price, MAX(price) AS max_price, AVG(price) AS avg_price, "
                "COUNT(*) AS entries "
                'FROM "ProductHistory" '
                "WHERE product_id = %s AND recorded_at::date >= %s "
                "GROUP BY DATE(recorded_at) ORDER BY record_date",
                (product_id, thirty_days_ago),
            )
            price_history = []
            for r in cur.fetchall():
                price_history.append({
                    "date": r["record_date"].isoformat(),
                    "min_price": float(r["min_price"]),
                    "max_price": float(r["max_price"]),
                    "avg_price": float(r["avg_price"]),
                    "entries": r["entries"],
                })

            cur.execute(
                "SELECT k.id, k.name, k.platform, k.is_active "
                'FROM "Keyword" k '
                'JOIN "ProductKeyword" pk ON k.id = pk.keyword_id '
                "WHERE pk.product_id = %s ORDER BY k.name",
                (product_id,),
            )
            keywords = [dict(r) for r in cur.fetchall()]

            cur.execute(
                'SELECT id, alert_type, message, status, is_sent, is_read, created_at '
                'FROM "Alert" WHERE product_id = %s ORDER BY created_at DESC LIMIT 50',
                (product_id,),
            )
            alerts = []
            for r in cur.fetchall():
                alerts.append({
                    "id": r["id"],
                    "alert_type": r["alert_type"],
                    "message": r["message"],
                    "status": r["status"],
                    "is_sent": r["is_sent"],
                    "is_read": r["is_read"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                })

        return {
            "product": {
                "product_id": product["product_id"],
                "title": product["title"],
                "main_image_url": product["main_image_url"],
                "shop_name": product["shop_name"],
                "shop_type": product["shop_type"],
                "shipping_area": product["shipping_area"],
                "is_approved": product["is_approved"],
                "is_whitelist": product["is_whitelist"],
                "created_at": product["created_at"].isoformat() if product["created_at"] else None,
                "last_updated_at": product["last_updated_at"].isoformat() if product["last_updated_at"] else None,
                "last_sku_crawled_at": product["last_sku_crawled_at"].isoformat() if product.get("last_sku_crawled_at") else None,
            },
            "price_history": price_history,
            "keywords": keywords,
            "alerts": alerts,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("查询商品详情失败: %s", product_id)
        raise HTTPException(status_code=500, detail="查询商品详情失败")
    finally:
        conn.close()


@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    _auth: dict[str, Any] = Depends(require_write_permission),
) -> dict[str, Any]:
    """删除单个商品及其关联数据。权限：admin/manager"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "ProductHistory" WHERE product_id=%s', (product_id,))
            cur.execute('DELETE FROM "ProductSku" WHERE product_id=%s', (product_id,))
            cur.execute('DELETE FROM "ProductKeyword" WHERE product_id=%s', (product_id,))
            cur.execute('DELETE FROM "Alert" WHERE product_id=%s', (product_id,))
            cur.execute('DELETE FROM "Product" WHERE product_id=%s', (product_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="商品不存在")
            conn.commit()
        logger.info("删除商品: %s", product_id)
        return {"success": True}
    except HTTPException: raise
    except Exception:
        logger.exception("删除商品失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除失败")

