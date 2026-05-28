"""站内通知 API

提供给前端轮询的通知数量接口。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.notifications")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


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


@router.get("/count")
def notification_count(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT COUNT(*)::int AS cnt FROM "Alert" '
                "WHERE is_read = FALSE AND status = 'unprocessed'"
            )
            unread_alerts = cur.fetchone()["cnt"]

        return {
            "unread_alerts": unread_alerts,
            "total": unread_alerts,
        }
    except Exception:
        logger.exception("获取通知数失败")
        return {"unread_alerts": 0, "total": 0}
    finally:
        conn.close()
