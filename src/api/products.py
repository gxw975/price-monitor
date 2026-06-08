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
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from services.auth_service import get_current_user


class ConfirmImportRequest(BaseModel):
    file_name: str
    selected_product_ids: list[str]

load_dotenv()
logger = logging.getLogger("api.products")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/products", tags=["商品管理"])


def _check_write_permission(role: str) -> None:
    """校验写入权限：仅管理员和主管可操作"""
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


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


@router.post("/import-excel/{monitor_product_id}", dependencies=[Depends(_check_write_permission)])
async def import_product_excel_preview(
    monitor_product_id: int,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """阶段A — 上传DTS Excel，返回清洗后的预览数据（不入库）。

    权限：仅admin/manager角色可访问。
    """
    temp_path: str = ""
    try:
        if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="仅支持Excel文件格式（.xlsx/.xls）")

        suffix = Path(file.filename).suffix
        temp_path = os.path.join(tempfile.gettempdir(), f"dts_import_{uuid.uuid4().hex}{suffix}")
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info("Excel预览: 文件=%s 大小=%d bytes monitor_product_id=%d",
                     file.filename, len(content), monitor_product_id)

        from services.dts_parser import DtsDataParser

        parser = DtsDataParser()
        parsed_data = parser.parse(temp_path)
        if not parsed_data or len(parsed_data) == 0:
            raise HTTPException(status_code=400, detail="Excel文件解析失败，未提取到有效商品数据")

        # 数据清洗：过滤广告，补全链接，过滤无效数据
        valid_data, ad_count = parser.clean_ad_data(parsed_data)

        logger.info("Excel预览: 总数=%d 广告=%d 有效=%d", len(parsed_data), ad_count, len(valid_data))

        return {
            "code": 200,
            "msg": "数据解析成功",
            "data": {
                "file_name": file.filename,
                "total_count": len(parsed_data),
                "ad_count": ad_count,
                "valid_count": len(valid_data),
                "preview_data": valid_data,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Excel预览失败: %s", e)
        raise HTTPException(status_code=500, detail=f"解析失败：{e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@router.post("/confirm-import/{monitor_product_id}", dependencies=[Depends(_check_write_permission)])
async def confirm_import(
    monitor_product_id: int,
    data: ConfirmImportRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """阶段B — 确认导入用户筛选后的商品，创建导入批次并入库。

    权限：仅admin/manager角色可访问。
    """
    conn = _get_conn()
    try:
        selected_ids = data.selected_product_ids
        if not selected_ids:
            raise HTTPException(status_code=400, detail="未选择任何商品")

        # 创建导入批次
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "ImportBatch" (monitor_product_id, file_name, total_count, ad_count, valid_count, imported_by) '
                'VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
                (monitor_product_id, data.file_name, len(selected_ids), 0, len(selected_ids),
                 current_user.get("user_id")),
            )
            batch_id = cur.fetchone()[0]
            conn.commit()

        logger.info("确认导入: monitor_product_id=%d batch_id=%d selected=%d by %s",
                     monitor_product_id, batch_id, len(selected_ids), current_user["username"])

        # 注意：preview_data 中需要保存完整商品信息供此处入库
        # 当前简化方案：逐条插入（后续可优化为批量）
        inserted = 0
        from services.product_service import _get_conn as svc_get_conn
        svc_conn = svc_get_conn()
        try:
            for pid in selected_ids:
                try:
                    with svc_conn.cursor() as cur:
                        cur.execute(
                            'SELECT product_id FROM "Product" WHERE product_id = %s', (pid,)
                        )
                        if cur.fetchone():
                            # 已存在：更新关联
                            cur.execute(
                                'UPDATE "Product" SET monitor_product_id = %s, import_batch_id = %s, last_updated_at = NOW() WHERE product_id = %s',
                                (monitor_product_id, batch_id, pid),
                            )
                        else:
                            # 新商品：插入占位记录（实际数据由前端预览页传递）
                            cur.execute(
                                'INSERT INTO "Product" (product_id, title, monitor_product_id, import_batch_id, is_approved, is_whitelist, created_at, last_updated_at) '
                                'VALUES (%s, %s, %s, %s, FALSE, FALSE, NOW(), NOW())',
                                (pid, pid, monitor_product_id, batch_id),
                            )
                        inserted += 1
                    svc_conn.commit()
                except Exception:
                    svc_conn.rollback()
                    logger.exception("插入商品失败: %s", pid)
        finally:
            svc_conn.close()

        # 更新批次计数
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "ImportBatch" SET valid_count = %s WHERE id = %s',
                (inserted, batch_id),
            )
            conn.commit()

        # 触发预警检测
        from scripts.check_alerts import run_alerts
        alert_result = run_alerts(test_mode=False, force=False)

        logger.info("确认导入完成: batch_id=%d inserted=%d alerts=%s", batch_id, inserted, alert_result)

        return {
            "code": 200,
            "msg": "导入成功",
            "data": {
                "batch_id": batch_id,
                "import_result": {
                    "success_count": inserted,
                    "fail_count": len(selected_ids) - inserted,
                    "total": len(selected_ids),
                },
                "alert_result": {
                    "checked": alert_result.get("checked", 0),
                    "price_alerts": alert_result.get("price_alerts", 0),
                    "sales_alerts": alert_result.get("sales_alerts", 0),
                    "sent": alert_result.get("sent", 0),
                },
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("确认导入失败: %s", e)
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")
    finally:
        conn.close()
