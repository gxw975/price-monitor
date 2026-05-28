"""商品详情 API

提供商品详情、价格历史、关联关键词和预警记录。
权限：全员可查看。
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
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

router = APIRouter(prefix="/api/products", tags=["products"])


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
