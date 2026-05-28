"""消息交互 API

接收 OpenClaw agent 转发的用户消息，解析命令并执行，
结果通过 OpenClaw agent 发回用户的微信/飞书。
权限：按命令类型和用户角色区分。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

load_dotenv()
logger = logging.getLogger("api.messages")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

OPENCLAW_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/openclaw"
SUPERVISOR_CONF = "/home/lab-admin/price-monitor/supervisor.conf"
SUPERVISOR_CTL = f"sudo supervisorctl -c {SUPERVISOR_CONF}"
LOG_DIR = "/home/lab-admin/price-monitor/logs"

router = APIRouter(prefix="/api/messages", tags=["messages"])


class CommandRequest(BaseModel):
    message: str
    agent_id: str = ""


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


def _find_user_by_agent(agent_id: str) -> dict[str, Any] | None:
    if not agent_id:
        return None
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id, username, role, openclaw_agent_id FROM "User" '
                "WHERE openclaw_agent_id = %s LIMIT 1",
                (agent_id,),
            )
            return dict(cur.fetchone()) if cur.rowcount else None
    except Exception:
        return None
    finally:
        conn.close()


def _reply(agent_id: str, content: str) -> bool:
    if not agent_id:
        return False
    try:
        cmd = [OPENCLAW_BIN, "agent", "--agent", agent_id, "--message", content, "--deliver", "--json"]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        logger.exception("回复消息失败: agent=%s", agent_id)
        return False


def _parse_command(message: str) -> tuple[str, str]:
    msg = message.strip().lower()
    commands = [
        ("查看预警", "alerts"),
        ("预警", "alerts"),
        ("alerts", "alerts"),
        ("重启服务", "restart"),
        ("重启", "restart"),
        ("restart", "restart"),
        ("查看日志", "logs"),
        ("日志", "logs"),
        ("logs", "logs"),
        ("测试推送", "test_push"),
        ("test", "test_push"),
        ("test_push", "test_push"),
        ("服务状态", "status"),
        ("状态", "status"),
        ("status", "status"),
        ("帮助", "help"),
        ("help", "help"),
        ("命令", "help"),
        ("? ", "help"),
        ("？", "help"),
    ]
    for keyword, cmd in commands:
        if keyword in msg:
            return cmd, keyword
    return "help", ""


def _get_recent_alerts(limit: int = 5) -> str:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id, product_id, alert_type, message, status, created_at '
                'FROM "Alert" ORDER BY created_at DESC LIMIT %s',
                (limit,),
            )
            rows = cur.fetchall()
            if not rows:
                return "📋 暂无预警记录"
            lines = ["📋 最近预警列表:\n"]
            for r in rows:
                t = "🔴低价" if r["alert_type"] == "price" else "🟠销量"
                s = "✅" if r["status"] == "processed" else "⬜"
                ts = r["created_at"].strftime("%m-%d %H:%M") if r["created_at"] else "?"
                lines.append(f"  {t} {s} [{r['product_id']}] {r['message'][:60]} ({ts})")
            return "\n".join(lines)
    except Exception:
        return "❌ 查询预警失败"
    finally:
        conn.close()


def _get_recent_logs(lines: int = 15) -> str:
    log_files = [
        os.path.join(LOG_DIR, "monitor.log"),
        os.path.join(LOG_DIR, "crawl.log"),
        os.path.join(LOG_DIR, "alert.log"),
    ]
    result_parts: list[str] = ["📋 最近日志:\n"]
    for lf in log_files:
        if not os.path.exists(lf):
            continue
        try:
            out = subprocess.run(
                ["tail", f"-n{lines}", lf],
                capture_output=True, text=True, timeout=5,
            )
            if out.stdout.strip():
                fname = os.path.basename(lf)
                result_parts.append(f"--- {fname} ---")
                result_parts.append(out.stdout.strip()[-800:])
        except Exception:
            pass
    if len(result_parts) <= 1:
        return "📋 暂无日志内容"
    return "\n".join(result_parts)


def _get_service_status() -> str:
    try:
        out = subprocess.run(
            f"{SUPERVISOR_CTL} status",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        lines = ["📊 服务状态:\n"]
        for line in out.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            icon = "✅" if "RUNNING" in line else "❌"
            lines.append(f"  {icon} {line}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询服务状态失败: {e}"


def _do_restart_services() -> str:
    try:
        out = subprocess.run(
            f"{SUPERVISOR_CTL} restart all",
            shell=True, capture_output=True, text=True, timeout=30,
        )
        if out.returncode == 0:
            return "✅ 服务已重启\n" + out.stdout.strip()[:300]
        return "❌ 重启失败\n" + (out.stderr or out.stdout).strip()[:300]
    except Exception as e:
        return f"❌ 重启异常: {e}"


def _do_test_push(agent_id: str) -> str:
    now_str = datetime.now().strftime("%m-%d %H:%M")
    if _reply(agent_id, f"✅ price-monitor 连接测试成功\n测试时间: {now_str}"):
        return "✅ 测试消息已发送，请查看微信"
    return "❌ 测试消息发送失败"


def _get_help(role: str, agent_id: str) -> str:
    lines = [
        "📋 支持的命令:\n",
        "  查看预警  - 查看最近预警",
        "  服务状态  - 查看服务运行状态",
        "  查看日志  - 查看最近系统日志",
        "  测试推送  - 发送测试消息",
    ]
    if role in ("admin", "manager"):
        lines.append("  重启服务  - 重启系统服务")
    lines.append(f"\n当前 Agent: {agent_id or '未指定'}")
    lines.append(f"当前角色: {role}")
    return "\n".join(lines)


@router.post("/command")
def handle_command(body: CommandRequest) -> dict[str, Any]:
    message = body.message.strip()
    if not message:
        return {"success": False, "response": "请发送命令，输入「帮助」查看支持的命令"}

    agent_id = body.agent_id.strip()
    user_info = _find_user_by_agent(agent_id)

    cmd, keyword = _parse_command(message)
    role = user_info["role"] if user_info else "staff"
    username = user_info["username"] if user_info else agent_id or "unknown"

    logger.info("消息命令: user=%s role=%s agent=%s cmd=%s msg=%s",
                username, role, agent_id, cmd, message[:80])

    staff_forbidden = {"restart", "test_push"}

    if cmd in staff_forbidden and role == "staff":
        response = f"⛔ 权限不足\n命令「{keyword}」需要管理员或主管权限，你当前角色为：{role}"
        return {"success": False, "command": cmd, "response": response, "user_role": role}

    if cmd == "alerts":
        response = _get_recent_alerts()
    elif cmd == "logs":
        response = _get_recent_logs()
    elif cmd == "status":
        response = _get_service_status()
    elif cmd == "restart":
        response = _do_restart_services()
    elif cmd == "test_push":
        response = _do_test_push(agent_id)
    else:
        response = _get_help(role, agent_id)

    if agent_id and cmd != "test_push":
        _reply(agent_id, response)

    return {
        "success": True,
        "command": cmd,
        "response": response,
        "user_role": role,
        "username": username,
    }
