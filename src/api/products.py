"""商品管理 API

提供商品详情查询、Excel导入、价格历史、关联关键词和预警记录。
权限：查看全员可访问，导入仅admin/manager。
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.auth_service import get_current_user


class BatchVerifyRequest(BaseModel):
    sku_ids: list[int]
    sku_category_id: int | None = None

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
    platform: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if platform:
                cur.execute(
                    'SELECT product_id, title, main_image_url, shop_name, shop_type, '
                    "shipping_area, is_approved, is_whitelist, created_at, last_updated_at, "
                    'last_sku_crawled_at, platform, price, sales_volume, image_url, seller_name, product_url '
                    'FROM "Product" WHERE product_id = %s AND platform = %s',
                    (product_id, platform),
                )
            else:
                cur.execute(
                    'SELECT product_id, title, main_image_url, shop_name, shop_type, '
                    "shipping_area, is_approved, is_whitelist, created_at, last_updated_at, "
                    'last_sku_crawled_at, platform, price, sales_volume, image_url, seller_name, product_url '
                    'FROM "Product" WHERE product_id = %s',
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


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可操作")


@router.post("/{product_id}/skus/batch-verify")
def batch_verify_skus(
    product_id: str,
    data: BatchVerifyRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """批量审核SKU分类"""
    _check_write_permission(current_user["role"])
    if not data.sku_ids:
        raise HTTPException(status_code=400, detail="未选择任何SKU")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            if data.sku_category_id:
                # 批量设置分类并标记为已审核
                cur.execute(
                    'UPDATE "ProductSku" SET sku_category_id=%s, is_verified=TRUE, updated_at=NOW() WHERE id=ANY(%s)',
                    (data.sku_category_id, data.sku_ids),
                )
            else:
                # 仅标记为已审核（保持现有分类不变）
                cur.execute(
                    'UPDATE "ProductSku" SET is_verified=TRUE, updated_at=NOW() WHERE id=ANY(%s)',
                    (data.sku_ids,),
                )
            affected = cur.rowcount
            conn.commit()
        logger.info("批量审核SKU: product=%s sku_ids=%s cat_id=%s affected=%d by %s",
                     product_id, data.sku_ids, data.sku_category_id, affected, current_user["username"])
        return {"code": 200, "msg": f"已审核 {affected} 个SKU", "affected": affected}
    except Exception:
        logger.exception("批量审核SKU失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="审核失败")
    finally:
        conn.close()


@router.post("/{product_id}/skus/{sku_id}/verify")
def verify_single_sku(
    product_id: str,
    sku_id: int,
    data: BatchVerifyRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """审核单个SKU分类"""
    _check_write_permission(current_user["role"])
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "ProductSku" SET sku_category_id=%s, is_verified=TRUE, updated_at=NOW() WHERE id=%s',
                (data.sku_category_id, sku_id),
            )
            conn.commit()
        logger.info("审核单个SKU: product=%s sku=%d cat=%s by %s",
                     product_id, sku_id, data.sku_category_id, current_user["username"])
        return {"code": 200, "msg": "审核成功"}
    except Exception:
        logger.exception("审核SKU失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="审核失败")
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


@router.get("/{product_id}/history/export")
def export_price_history(product_id: str):
    """导出单个商品的价格历史数据为Excel"""
    from io import BytesIO
    from openpyxl import Workbook
    from fastapi.responses import StreamingResponse

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT title FROM "Product" WHERE product_id=%s', (product_id,))
            p = cur.fetchone()
            title = p["title"] if p else product_id
            cur.execute(
                'SELECT price, sales_volume, recorded_at FROM "ProductHistory" WHERE product_id=%s ORDER BY recorded_at ASC',
                (product_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "价格历史"
    ws.append(["商品ID", "商品标题", "价格", "销量", "记录时间"])
    for r in rows:
        ws.append([product_id, title, float(r["price"]), r["sales_volume"], r["recorded_at"].isoformat() if r["recorded_at"] else ""])
    output = BytesIO()
    wb.save(output); output.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f"attachment; filename=history_{product_id}_{ts}.xlsx"})

