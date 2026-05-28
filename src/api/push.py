"""推送测试 API

提供多渠道推送测试功能。
权限：admin/manager 可发送测试，全体可查看推送配置。
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
from services.push_service import _get_push_config as read_push_config
from services.push_service import send_test_message
from services.push_service import send_test_personal_wechat

load_dotenv()
logger = logging.getLogger("api.push")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/push", tags=["push"])


class TestPushRequest(BaseModel):
    channel: str
    webhook_url: str


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


@router.get("/config")
def push_config_info(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return read_push_config()


@router.post("/test")
def test_push(
    body: TestPushRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    if body.channel not in ("feishu", "wechat"):
        raise HTTPException(status_code=400, detail="不支持的推送渠道，支持: feishu, wechat")

    if not body.webhook_url:
        raise HTTPException(status_code=400, detail="Webhook 地址不能为空")

    result = send_test_message(body.channel, body.webhook_url)

    if result["success"]:
        logger.info("推送测试成功: channel=%s by %s", body.channel, current_user["username"])
    else:
        logger.warning("推送测试失败: channel=%s by %s: %s", body.channel, current_user["username"], result["message"])
    return result


@router.post("/test-personal")
def test_personal_wechat(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    agent_id = current_user.get("openclaw_agent_id", "")
    if not agent_id:
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    'SELECT openclaw_agent_id FROM "User" WHERE id = %s',
                    (current_user["user_id"],),
                )
                row = cur.fetchone()
                if row and row.get("openclaw_agent_id"):
                    agent_id = row["openclaw_agent_id"]
        except Exception:
            pass
        finally:
            conn.close()

    result = send_test_personal_wechat(agent_id)
    if result["success"]:
        logger.info("个人微信推送测试成功 by %s (agent=%s)", current_user["username"], agent_id)
    else:
        logger.warning("个人微信推送测试失败 by %s: %s", current_user["username"], result["message"])
    return result


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
