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

    success = send_test_message(body.channel, body.webhook_url)

    if success:
        logger.info("推送测试成功: channel=%s by %s", body.channel, current_user["username"])
        return {"success": True, "message": f"{body.channel} 测试消息发送成功"}
    else:
        logger.warning("推送测试失败: channel=%s by %s", body.channel, current_user["username"])
        return {"success": False, "message": f"{body.channel} 测试消息发送失败，请检查Webhook地址"}
