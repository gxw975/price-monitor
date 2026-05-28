"""预警管理 API

提供预警列表查询、标记已读、统计和导出等功能。
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

load_dotenv()
logger = logging.getLogger("api.alerts")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


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


def _alert_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "alert_type": row["alert_type"],
        "message": row["message"],
        "status": row.get("status", "unprocessed"),
        "is_sent": row["is_sent"],
        "sent_at": row["sent_at"].isoformat() if row.get("sent_at") else None,
        "is_read": row["is_read"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@router.get("/list")
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    alert_type: str | None = Query(None),
    is_read: bool | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions: list[str] = []
            params: list[Any] = []

            if alert_type:
                conditions.append("a.alert_type = %s")
                params.append(alert_type)
            if is_read is not None:
                conditions.append("a.is_read = %s")
                params.append(is_read)
            if status:
                conditions.append("a.status = %s")
                params.append(status)
            if keyword:
                conditions.append("(a.message ILIKE %s OR a.product_id ILIKE %s OR p.title ILIKE %s)")
                params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            count_sql = f'SELECT COUNT(*) FROM "Alert" a {where}'
            cur.execute(count_sql, params)
            total = cur.fetchone()["count"]

            offset = (page - 1) * page_size
            data_sql = (
                'SELECT a.*, COALESCE(p.title, a.product_id) AS product_title '
                'FROM "Alert" a '
                'LEFT JOIN "Product" p ON a.product_id = p.product_id '
                f"{where} "
                "ORDER BY a.created_at DESC "
                "LIMIT %s OFFSET %s"
            )
            cur.execute(data_sql, params + [page_size, offset])
            items = [_alert_to_dict(r) for r in cur.fetchall()]

            unread_count_sql = 'SELECT COUNT(*) FROM "Alert" WHERE is_read = FALSE'
            cur.execute(unread_count_sql)
            unread_count = cur.fetchone()["count"]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "unread_count": unread_count,
        }
    except Exception:
        logger.exception("查询预警列表失败")
        raise HTTPException(status_code=500, detail="查询预警列表失败")
    finally:
        conn.close()


@router.post("/mark-read")
def mark_read(ids: list[int]) -> dict[str, Any]:
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f'UPDATE "Alert" SET is_read = TRUE WHERE id IN ({placeholders})',
                ids,
            )
            affected = cur.rowcount
            conn.commit()

        logger.info("标记已读: ids=%s, affected=%d", ids, affected)
        return {"success": True, "affected": affected}
    except Exception:
        logger.exception("标记已读失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="标记已读失败")
    finally:
        conn.close()


@router.post("/mark-processed")
def mark_processed(ids: list[int]) -> dict[str, Any]:
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f'UPDATE "Alert" SET status = %s WHERE id IN ({placeholders})',
                ["processed"] + ids,
            )
            affected = cur.rowcount
            conn.commit()

        logger.info("标记处理: ids=%s, affected=%d", ids, affected)
        return {"success": True, "affected": affected}
    except Exception:
        logger.exception("标记处理失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="标记处理失败")
    finally:
        conn.close()


@router.post("/batch-delete")
def batch_delete(ids: list[int]) -> dict[str, Any]:
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f'DELETE FROM "Alert" WHERE id IN ({placeholders})',
                ids,
            )
            affected = cur.rowcount
            conn.commit()

        logger.info("批量删除预警: ids=%s, affected=%d", ids, affected)
        return {"success": True, "affected": affected}
    except Exception:
        logger.exception("批量删除预警失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="批量删除预警失败")
    finally:
        conn.close()


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT COUNT(*) as total FROM "Alert"')
            total = cur.fetchone()["total"]

            cur.execute('SELECT COUNT(*) as unread FROM "Alert" WHERE is_read = FALSE')
            unread = cur.fetchone()["unread"]

            cur.execute(
                "SELECT alert_type, COUNT(*) as cnt FROM \"Alert\" GROUP BY alert_type "
                "ORDER BY cnt DESC"
            )
            by_type = {r["alert_type"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(
                "SELECT alert_type, COUNT(*) as cnt FROM \"Alert\" "
                "WHERE created_at >= NOW() - INTERVAL '7 days' "
                "GROUP BY alert_type ORDER BY cnt DESC"
            )
            recent_by_type = {r["alert_type"]: r["cnt"] for r in cur.fetchall()}

        return {
            "total": total,
            "unread": unread,
            "by_type": by_type,
            "recent_7d": recent_by_type,
        }
    except Exception:
        logger.exception("查询预警统计失败")
        raise HTTPException(status_code=500, detail="查询统计失败")
    finally:
        conn.close()


@router.post("/export")
def export_alerts(
    alert_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions: list[str] = []
            params: list[Any] = []

            if alert_type:
                conditions.append("a.alert_type = %s")
                params.append(alert_type)
            if date_from:
                conditions.append("a.created_at >= %s")
                params.append(date_from)
            if date_to:
                conditions.append("a.created_at <= %s")
                params.append(date_to)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            cur.execute(
                'SELECT a.*, COALESCE(p.title, a.product_id) AS product_title '
                'FROM "Alert" a '
                'LEFT JOIN "Product" p ON a.product_id = p.product_id '
                f"{where} ORDER BY a.created_at DESC LIMIT 5000",
                params,
            )
            rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "商品ID", "商品名称", "预警类型", "消息", "已发送", "已读", "创建时间"])

        type_labels = {"price": "价格预警", "sales": "销量预警"}
        for r in rows:
            writer.writerow([
                r["id"],
                r["product_id"],
                r.get("product_title", r["product_id"]),
                type_labels.get(r["alert_type"], r["alert_type"]),
                r["message"],
                "是" if r["is_sent"] else "否",
                "是" if r["is_read"] else "否",
                r["created_at"].isoformat() if r.get("created_at") else "",
            ])

        csv_content = output.getvalue()
        logger.info("导出预警: type=%s, count=%d", alert_type, len(rows))
        return {"csv": csv_content, "count": len(rows)}
    except Exception:
        logger.exception("导出预警失败")
        raise HTTPException(status_code=500, detail="导出失败")
    finally:
        conn.close()
