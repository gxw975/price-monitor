"""微信推送配置 API

提供 Server酱 SendKey 配置、启用/禁用、测试推送。
权限：仅 admin/manager。
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

load_dotenv()
logger = logging.getLogger("api.wechat")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/wechat", tags=["微信推送"])


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足")


def _get_conn() -> Any:
    from urllib.parse import parse_qs, urlparse, urlunparse
    parsed = urlparse(DATABASE_URL)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    conn = psycopg2.connect(clean)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


class WechatConfigUpdate(BaseModel):
    wechat_push_enabled: bool = False
    wechat_sendkey: str = ""


@router.get("/status")
def get_wechat_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取微信推送配置状态"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT wechat_push_enabled, wechat_sendkey FROM "SystemConfig" LIMIT 1')
            row = cur.fetchone()
        if row:
            return {
                "code": 200,
                "data": {
                    "enabled": row.get("wechat_push_enabled", False),
                    "sendkey_configured": bool(row.get("wechat_sendkey")),
                    "sendkey_masked": (row.get("wechat_sendkey") or "")[:8] + "***" if row.get("wechat_sendkey") else "",
                },
            }
        return {"code": 200, "data": {"enabled": False, "sendkey_configured": False, "sendkey_masked": ""}}
    except Exception:
        logger.exception("获取微信状态失败")
        raise HTTPException(status_code=500, detail="获取失败")
    finally:
        conn.close()


@router.put("/config", dependencies=[Depends(_check_write_permission)])
def update_wechat_config(
    body: WechatConfigUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """更新微信推送配置"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "SystemConfig" SET wechat_push_enabled=%s, wechat_sendkey=%s, updated_at=NOW()',
                (body.wechat_push_enabled, body.wechat_sendkey),
            )
            conn.commit()
        logger.info("微信配置更新: enabled=%s by %s", body.wechat_push_enabled, current_user["username"])
        return {"code": 200, "msg": "保存成功"}
    except Exception:
        logger.exception("更新微信配置失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="保存失败")
    finally:
        conn.close()


@router.post("/test", dependencies=[Depends(_check_write_permission)])
def send_test_message(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """发送微信测试消息"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT wechat_sendkey, wechat_push_enabled FROM "SystemConfig" LIMIT 1')
            row = cur.fetchone()
    finally:
        conn.close()

    if not row or not row.get("wechat_sendkey"):
        raise HTTPException(status_code=400, detail="SendKey 未配置，请先在 sct.ftqq.com 获取")

    from services.wechat_push_service import send_wechat_message

    ok, msg = send_wechat_message(
        row["wechat_sendkey"],
        "✅ 测试消息",
        "电商低价监控系统微信推送测试成功\n\n已绑定 Server酱 推送通道",
    )

    if not ok:
        raise HTTPException(status_code=500, detail=msg)

    return {"code": 200, "msg": "测试消息发送成功，请查看微信"}
