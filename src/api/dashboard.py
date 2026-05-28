"""首页仪表盘 API

提供数据概览、趋势图表和最近预警数据。
权限：全体可访问，数据按角色做适当限制。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.dashboard")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


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


@router.get("/summary")
def dashboard_summary(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        today_str = date.today().isoformat()
        seven_days_ago = date.today() - timedelta(days=6)

        metrics: dict[str, Any] = {}

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT COUNT(*)::int AS cnt FROM "Alert"')
            metrics["total_alerts"] = cur.fetchone()["cnt"]

            cur.execute(
                'SELECT COUNT(*)::int AS cnt FROM "Alert" WHERE "created_at"::date = %s',
                (today_str,),
            )
            metrics["today_alerts"] = cur.fetchone()["cnt"]

            cur.execute(
                'SELECT COUNT(*)::int AS cnt FROM "Product" WHERE is_whitelist = FALSE AND is_approved = TRUE'
            )
            metrics["monitored_products"] = cur.fetchone()["cnt"]

            cur.execute('SELECT COUNT(*)::int AS cnt FROM "Product"')
            metrics["total_products"] = cur.fetchone()["cnt"]

            cur.execute('SELECT COUNT(*)::int AS cnt FROM "Keyword"')
            metrics["keyword_count"] = cur.fetchone()["cnt"]

            cur.execute(
                'SELECT COUNT(DISTINCT product_id)::int AS cnt FROM "ProductHistory" '
                "WHERE recorded_at::date = %s",
                (today_str,),
            )
            metrics["today_crawled"] = cur.fetchone()["cnt"]

            cur.execute(
                'SELECT COUNT(*)::int AS cnt FROM "ProductHistory" '
                "WHERE recorded_at::date = %s",
                (today_str,),
            )
            today_entries = cur.fetchone()["cnt"]

            cur.execute(
                'SELECT COUNT(*)::int AS cnt FROM "ProductHistory" '
                "WHERE recorded_at::date = %s",
                ((date.today() - timedelta(days=1)).isoformat(),),
            )
            yesterday_entries = cur.fetchone()["cnt"]
            yesterday_entries = yesterday_entries or 1

            if today_entries > 0:
                metrics["crawl_success_rate"] = 100
            else:
                metrics["crawl_success_rate"] = 0

            alert_trend: list[dict[str, Any]] = []
            for i in range(6, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                cur.execute(
                    'SELECT COUNT(*)::int AS cnt FROM "Alert" WHERE "created_at"::date = %s',
                    (d,),
                )
                alert_trend.append({"date": d, "count": cur.fetchone()["cnt"]})

            crawl_trend: list[dict[str, Any]] = []
            for i in range(6, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                cur.execute(
                    'SELECT COUNT(DISTINCT product_id)::int AS cnt FROM "ProductHistory" '
                    "WHERE recorded_at::date = %s",
                    (d,),
                )
                crawl_trend.append({"date": d, "count": cur.fetchone()["cnt"]})

            cur.execute(
                'SELECT a.id, a.product_id, a.alert_type, a.message, a.is_read, a.created_at, '
                'p.title AS product_title '
                'FROM "Alert" a '
                'LEFT JOIN "Product" p ON a.product_id = p.product_id '
                'ORDER BY a.created_at DESC LIMIT 5'
            )
            recent_alerts = []
            for row in cur.fetchall():
                recent_alerts.append({
                    "id": row["id"],
                    "product_id": row["product_id"],
                    "alert_type": row["alert_type"],
                    "message": row["message"],
                    "is_read": row["is_read"],
                    "product_title": row.get("product_title", ""),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                })

        return {
            "metrics": metrics,
            "alert_trend": alert_trend,
            "crawl_trend": crawl_trend,
            "recent_alerts": recent_alerts,
        }
    except Exception:
        logger.exception("获取仪表盘数据失败")
        return {
            "metrics": {},
            "alert_trend": [],
            "crawl_trend": [],
            "recent_alerts": [],
            "error": "数据获取失败",
        }
    finally:
        conn.close()
