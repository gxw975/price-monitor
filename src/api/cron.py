"""定时任务管理 API

读取/更新 crontab 中的电商监控系统定时任务。
crontab 中由标记行包裹的区域会被自动管理。
权限：仅 admin/manager 可更新。
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.cron")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/cron", tags=["cron"])

BEGIN_MARKER = "# ------------- 电商低价监控系统 定时任务 -------------"
END_MARKER_PREFIX = "# (cron section end)"


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


def _get_config() -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM "SystemConfig" ORDER BY id LIMIT 1')
            row = cur.fetchone()
            if not row:
                return {
                    "sku_crawl_interval": 120,
                    "crawl_schedule_type": "interval",
                    "crawl_fixed_times": None,
                    "check_alert_interval": 180,
                }
            return dict(row)
    finally:
        conn.close()


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _build_crawl_cron_expr(config: dict[str, Any]) -> str:
    schedule_type = config.get("crawl_schedule_type", "interval")
    interval = config.get("sku_crawl_interval", 120)

    if schedule_type == "fixed_time" and config.get("crawl_fixed_times"):
        times = config["crawl_fixed_times"].strip()
        hours = []
        for t in times.split(","):
            t = t.strip()
            if ":" in t:
                hour = t.split(":")[0]
                minutes = t.split(":")[1]
                hours.append(f"{minutes} {hour}")
            else:
                hours.append(f"0 {t}")
        hour_part = ",".join(hours)
    else:
        hours_interval = max(1, interval // 60)
        if interval < 60:
            hour_part = f"*/{interval} *"
        else:
            hour_part = f"0 */{hours_interval}"

    return f"0 */{max(1, interval // 60)} * * *" if interval >= 60 else f"*/{interval} * * * *"


@router.get("/current")
def get_cron_tasks(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    config = _get_config()
    crawl_interval = config.get("sku_crawl_interval", 120)
    alert_interval = config.get("check_alert_interval", 180)
    schedule_type = config.get("crawl_schedule_type", "interval")

    return {
        "sku_crawl_interval_minutes": crawl_interval,
        "check_alert_interval_minutes": alert_interval,
        "crawl_schedule_type": schedule_type,
        "crawl_fixed_times": config.get("crawl_fixed_times"),
        "crawl_daily_limit": config.get("crawl_daily_limit", 100),
    }


@router.post("/update")
def update_cron_tasks(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    config = _get_config()
    crawl_interval = config.get("sku_crawl_interval", 120)
    alert_interval = config.get("check_alert_interval", 180)
    schedule_type = config.get("crawl_schedule_type", "interval")
    fixed_times = config.get("crawl_fixed_times", "")
    project_root = "/home/lab-admin/price-monitor"
    python_bin = "./venv/bin/python"

    cfg = {
        "sku_crawl_interval": crawl_interval,
        "crawl_schedule_type": schedule_type,
        "crawl_fixed_times": fixed_times,
    }
    crawl_expr = _build_crawl_cron_expr(cfg)

    if alert_interval < 60:
        alert_expr = f"*/{alert_interval} * * * *"
    else:
        alert_h = max(1, alert_interval // 60)
        alert_expr = f"0 */{alert_h} * * *"

    new_lines = f"""
{BEGIN_MARKER}
# Auto-managed by 系统设置页面 - 请勿手动修改

# 1. SKU 抓取 ({schedule_type} mode)
{crawl_expr} cd {project_root} && {python_bin} src/scripts/run_sku_crawl.py >> logs/crawl.log 2>&1

# 2. 预警检测
{alert_expr} cd {project_root} && {python_bin} src/scripts/check_alerts.py >> logs/alert.log 2>&1

# 3. 每天 01:00：数据库备份
0 1 * * * cd {project_root} && /usr/bin/pg_dump -U postgres -d openclaw -n price_monitor -F c -f backups/$(date +\\%Y\\%m\\%d).dump >> logs/backup.log 2>&1

# 4. 每天 02:00：清理 7 天前日志
0 2 * * * cd {project_root} && find logs -type f -mtime +7 -delete
"""

    result = subprocess.run(
        "crontab -l 2>/dev/null",
        shell=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    current_crontab = result.stdout or ""

    if BEGIN_MARKER in current_crontab:
        before, _ = current_crontab.split(BEGIN_MARKER, 1)
        parts = current_crontab.split(BEGIN_MARKER, 1)
        after_marker = parts[1] if len(parts) > 1 else ""
        if "# (cron section end)" in after_marker:
            _, after = after_marker.rsplit("# (cron section end)", 1)
        else:
            section_end = after_marker.find("\n# ")
            if section_end == -1:
                after = ""
            else:
                section_start = after_marker.rfind("4. 每天")
                if section_start != -1:
                    line_end = after_marker.find("\n", section_start)
                    if line_end != -1:
                        after = after_marker[line_end:]
                    else:
                        after = ""
                else:
                    after = ""
        new_crontab = before.rstrip("\n") + "\n" + new_lines + "\n" + after.lstrip("\n")
    else:
        new_crontab = current_crontab.rstrip("\n") + "\n" + new_lines + "\n"

    proc = subprocess.run(
        "crontab -",
        shell=True,
        input=new_crontab,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if proc.returncode != 0:
        logger.error("crontab 更新失败: %s", proc.stderr)
        raise HTTPException(status_code=500, detail=f"crontab 更新失败: {proc.stderr}")

    logger.info(
        "定时任务已更新 by %s: crawl=%s alert=%smin",
        current_user["username"],
        schedule_type,
        alert_interval,
    )
    return {"success": True, "crawl_expression": crawl_expr, "alert_expression": alert_expr}
