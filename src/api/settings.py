"""系统设置 API

读写 SystemConfig 表，提供前端可视化配置。
权限：admin/manager 可写，staff 只读。
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.settings")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SystemSettings(BaseModel):
    alert_price: float
    work_start_hour: int
    work_end_hour: int
    sales_growth_threshold: int
    alert_dedup_hours: int
    sku_crawl_limit: int
    sku_crawl_interval: int
    crawl_schedule_type: str
    crawl_fixed_times: str | None = None
    crawl_daily_limit: int
    check_alert_interval: int


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
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以修改")


def _get_or_create_config(cur: Any) -> dict[str, Any]:
    cur.execute('SELECT * FROM "SystemConfig" ORDER BY id LIMIT 1')
    row = cur.fetchone()
    if not row:
        cur.execute(
            'INSERT INTO "SystemConfig" (alert_price, work_start_hour, work_end_hour, '
            "sales_growth_threshold, alert_dedup_hours, crawl_schedule_type, "
            "crawl_daily_limit, check_alert_interval, sku_crawl_limit, sku_crawl_interval, updated_at) "
            "VALUES (100, 9, 18, 100, 24, 'interval', 100, 180, 10, 120, NOW()) RETURNING *"
        )
        row = cur.fetchone()
    return row


def _row_to_settings(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "alert_price": float(row["alert_price"]),
        "work_start_hour": row["work_start_hour"],
        "work_end_hour": row["work_end_hour"],
        "sales_growth_threshold": row["sales_growth_threshold"],
        "alert_dedup_hours": row.get("alert_dedup_hours", 24),
        "sku_crawl_limit": row["sku_crawl_limit"],
        "sku_crawl_interval": row["sku_crawl_interval"],
        "crawl_schedule_type": row.get("crawl_schedule_type", "interval"),
        "crawl_fixed_times": row.get("crawl_fixed_times", None),
        "crawl_daily_limit": row.get("crawl_daily_limit", 100),
        "check_alert_interval": row.get("check_alert_interval", 180),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.get("")
def get_settings(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = _get_or_create_config(cur)
            return _row_to_settings(row)
    except Exception:
        logger.exception("读取系统设置失败")
        raise HTTPException(status_code=500, detail="读取系统设置失败")
    finally:
        conn.close()


@router.put("")
def update_settings(
    body: SystemSettings,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _get_or_create_config(cur)

            cur.execute(
                'UPDATE "SystemConfig" SET '
                "alert_price = %s, work_start_hour = %s, work_end_hour = %s, "
                "sales_growth_threshold = %s, alert_dedup_hours = %s, "
                "sku_crawl_limit = %s, sku_crawl_interval = %s, "
                "crawl_schedule_type = %s, crawl_fixed_times = %s, "
                "crawl_daily_limit = %s, check_alert_interval = %s, "
                "updated_at = NOW() "
                "WHERE id = (SELECT id FROM \"SystemConfig\" ORDER BY id LIMIT 1)",
                (
                    Decimal(str(body.alert_price)),
                    body.work_start_hour,
                    body.work_end_hour,
                    body.sales_growth_threshold,
                    body.alert_dedup_hours,
                    body.sku_crawl_limit,
                    body.sku_crawl_interval,
                    body.crawl_schedule_type,
                    body.crawl_fixed_times,
                    body.crawl_daily_limit,
                    body.check_alert_interval,
                ),
            )
            conn.commit()

        logger.info("系统设置已更新 by %s", current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("更新系统设置失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="更新系统设置失败")
    finally:
        conn.close()
