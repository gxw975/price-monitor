"""首页仪表盘 API

提供数据概览：核心指标卡片、最近预警、最近导入。
支持按平台筛选，权限：全体可访问。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Query

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
    platform: str | None = Query(None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """首页数据概览。platform 为空时统计全平台。"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # Platform filter helper
            mp_where = "WHERE mp.platform = %s" if platform else ""
            p_where = "AND p.platform = %s" if platform else ""
            a_where = "AND a.platform = %s" if platform else ""
            params_p = (platform,) if platform else ()
            params_a = (platform,) if platform else ()

            # ── Stat Cards ──
            cur.execute(
                f"""SELECT
                    (SELECT COUNT(*) FROM "MonitorProduct" mp {mp_where})::int AS monitor_product_count,
                    (SELECT COUNT(*) FROM "Product" p WHERE TRUE {p_where})::int AS total_products,
                    (SELECT COUNT(*) FROM "Product" p WHERE p.is_on_sale = TRUE {p_where})::int AS on_sale_count,
                    (SELECT COUNT(*) FROM "Alert" a WHERE a.is_handled = FALSE {a_where})::int AS unhandled_alerts,
                    (SELECT COUNT(*) FROM "Alert" a WHERE a.created_at::date = CURRENT_DATE {a_where})::int AS today_new_alerts""",
                params_p + params_p + params_p + params_a + params_a if platform else (),
            )
            stat_cards = dict(cur.fetchone() or {})

            # ── Latest 5 Alerts ──
            cur.execute(
                f"""SELECT a.id, a.product_id, a.alert_type, a.message, a.is_read, a.is_handled,
                          a.created_at, COALESCE(p.title, a.product_id) AS product_title
                FROM "Alert" a
                LEFT JOIN "Product" p ON a.product_id = p.product_id
                WHERE TRUE {a_where}
                ORDER BY a.created_at DESC LIMIT 5""",
                params_a,
            )
            latest_alerts = []
            for r in cur.fetchall():
                r = dict(r)
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
                latest_alerts.append(r)

            # ── Latest 3 Imports ──
            cur.execute(
                f"""SELECT ib.id, ib.file_name, ib.import_time, ib.valid_count, ib.total_count,
                          mp.name AS mp_name
                FROM "ImportBatch" ib
                JOIN "MonitorProduct" mp ON mp.id = ib.monitor_product_id
                {mp_where}
                ORDER BY ib.import_time DESC LIMIT 3""",
                (platform,) if platform else (),
            )
            latest_imports = []
            for r in cur.fetchall():
                r = dict(r)
                if r.get("import_time"):
                    r["import_time"] = r["import_time"].isoformat()
                latest_imports.append(r)

        return {
            "stat_cards": stat_cards,
            "latest_alerts": latest_alerts,
            "latest_imports": latest_imports,
        }

    except Exception:
        logger.exception("获取仪表盘数据失败")
        return {"stat_cards": {}, "latest_alerts": [], "latest_imports": []}
    finally:
        conn.close()
