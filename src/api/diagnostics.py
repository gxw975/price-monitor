"""故障排查与健康检查 API

提供系统健康检测、日志查看、一键维护操作。
权限：全员可查看状态和日志，admin/manager 可执行维护操作。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.diagnostics")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"
LOG_DIR = "/home/lab-admin/price-monitor/logs"

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

SUPERVISOR_CONF = "/home/lab-admin/price-monitor/supervisor.conf"
SUPERVISOR_CTL = f"sudo supervisorctl -c {SUPERVISOR_CONF}"
BACKUP_DIR = "/home/lab-admin/price-monitor/backups"


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _parse_db_url(url: str) -> tuple[str, str]:
    from urllib.parse import parse_qs, urlparse, urlunparse

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    return clean, schema


def _get_conn() -> Any:
    clean, schema = _parse_db_url(DATABASE_URL)
    conn = psycopg2.connect(clean, connect_timeout=5)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


@router.get("/health")
def health_check(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # 1. 服务状态检查
    svc_status = _check_service_status()
    checks.append(svc_status)

    # 2. 数据库检查
    db_status = _check_database()
    checks.append(db_status)

    # 3. 定时任务检查
    cron_status = _check_cron()
    checks.append(cron_status)

    # 4. 推送渠道检查
    push_status = _check_push_channels()
    checks.append(push_status)

    all_ok = all(c["status"] == "ok" for c in checks)
    issues = [c["detail"] for c in checks if c["status"] != "ok"]

    return {
        "overall": "ok" if all_ok else "degraded",
        "checked_at": datetime.now().isoformat(),
        "issues": issues,
        "items": checks,
    }


def _check_service_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            f"{SUPERVISOR_CTL} status",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        output = result.stdout
        running_count = 0
        total = 2
        for prog in ["fastapi-backend", "nextjs-frontend"]:
            if f"{prog} " in output and "RUNNING" in output:
                running_count += 1

        if running_count == total:
            return {"name": "服务状态", "status": "ok", "detail": f"{running_count}/{total} 个服务运行中"}
        elif running_count > 0:
            return {"name": "服务状态", "status": "warning", "detail": f"{running_count}/{total} 个服务运行中，部分异常"}
        else:
            return {"name": "服务状态", "status": "error", "detail": "所有服务已停止"}
    except Exception as e:
        return {"name": "服务状态", "status": "error", "detail": f"无法检测: {str(e)}"}


def _check_database() -> dict[str, Any]:
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SELECT COUNT(*) FROM \"Product\"")
            product_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM \"Alert\"")
            alert_count = cur.fetchone()[0]
        conn.close()
        return {
            "name": "数据库",
            "status": "ok",
            "detail": f"连接正常 (商品: {product_count}, 预警: {alert_count})",
        }
    except Exception as e:
        return {"name": "数据库", "status": "error", "detail": f"连接失败: {str(e)}"}


def _check_cron() -> dict[str, Any]:
    try:
        result = subprocess.run(
            "crontab -l 2>/dev/null",
            shell=True, capture_output=True, text=True, timeout=5,
        )
        marker = "电商低价监控系统"
        if marker in result.stdout:
            lines = result.stdout.count("\n")
            crawl_patterns = [p for p in ["run_sku_crawl.py", "check_alerts.py", "pg_dump"] if p in result.stdout]
            return {
                "name": "定时任务",
                "status": "ok",
                "detail": f"配置正常 (已配置 {len(crawl_patterns)} 个任务, crontab共 {lines} 行)",
            }
        else:
            return {"name": "定时任务", "status": "warning", "detail": "未检测到监控系统定时任务"}
    except Exception as e:
        return {"name": "定时任务", "status": "warning", "detail": f"无法检测: {str(e)}"}


def _check_push_channels() -> dict[str, Any]:
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM "SystemConfig" ORDER BY id LIMIT 1')
            row = cur.fetchone()
        conn.close()

        if not row:
            return {"name": "推送渠道", "status": "warning", "detail": "系统配置未初始化"}

        enabled = json.loads(row.get("push_enabled_channels", '["feishu"]'))
        details = []
        if "feishu" in enabled:
            wh = row.get("feishu_webhook")
            details.append(f"飞书: {'已配置' if wh else '未配置Webhook'}")
        if "wechat" in enabled:
            wh = row.get("wechat_webhook")
            details.append(f"微信: {'已配置' if wh else '未配置Webhook'}")

        if not enabled:
            return {"name": "推送渠道", "status": "warning", "detail": "没有启用任何推送渠道"}
        return {"name": "推送渠道", "status": "ok", "detail": "; ".join(details) if details else "配置正常"}
    except Exception as e:
        return {"name": "推送渠道", "status": "warning", "detail": f"无法检测: {str(e)}"}


@router.get("/logs")
def read_logs(
    file: str = Query("crawl", description="日志文件名: crawl, alert, backup"),
    lines: int = Query(50, ge=10, le=500),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    log_files = {
        "crawl": f"{LOG_DIR}/crawl.log",
        "alert": f"{LOG_DIR}/alert.log",
        "backend": f"{LOG_DIR}/fastapi-backend.log",
        "frontend": f"{LOG_DIR}/nextjs-frontend.log",
    }

    if file not in log_files:
        raise HTTPException(status_code=400, detail=f"未知日志文件，可选: {', '.join(log_files.keys())}")

    path = log_files[file]
    if not os.path.exists(path):
        return {"file": file, "lines": [], "total_lines": 0, "message": "日志文件不存在", "exists": False}

    try:
        result = subprocess.run(
            f"tail -n {lines} {path}",
            shell=True, capture_output=True, text=True, timeout=5,
        )
        log_lines = result.stdout.split("\n")
        log_lines = [l for l in log_lines if l.strip()]
        total = int(subprocess.run(
            f"wc -l < {path}",
            shell=True, capture_output=True, text=True, timeout=3,
        ).stdout.strip() or "0")

        return {
            "file": file,
            "exists": True,
            "total_lines": total,
            "showing": min(lines, len(log_lines)),
            "lines": log_lines,
        }
    except Exception as e:
        logger.exception("读取日志失败: %s", file)
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")


@router.post("/maintenance/restart")
def maintenance_restart(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    result = subprocess.run(
        f"{SUPERVISOR_CTL} restart all",
        shell=True, capture_output=True, text=True, timeout=30,
    )
    logger.info("一键重启服务 by %s", current_user["username"])
    return {
        "success": result.returncode == 0,
        "message": "服务已重启" if result.returncode == 0 else f"重启失败: {result.stderr}",
    }


@router.post("/maintenance/clean-logs")
def maintenance_clean_logs(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    clean_result = subprocess.run(
        f"find {LOG_DIR} -type f -mtime +7 -delete 2>&1 && echo 'OK'",
        shell=True, capture_output=True, text=True, timeout=10,
    )

    sizes = subprocess.run(
        f"du -sh {LOG_DIR} 2>/dev/null | awk '{{print $1}}'",
        shell=True, capture_output=True, text=True, timeout=5,
    )

    logger.info("一键清理日志 by %s, 目录剩余: %s", current_user["username"], sizes.stdout.strip())
    return {
        "success": "OK" in clean_result.stdout,
        "message": "已清理 7 天前的日志",
        "log_dir_size": sizes.stdout.strip(),
    }


@router.post("/maintenance/backup")
def maintenance_backup(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
    filepath = f"{BACKUP_DIR}/{filename}"

    result = subprocess.run(
        f"pg_dump -U postgres -d openclaw -n price_monitor -F c -f {filepath} 2>&1",
        shell=True, capture_output=True, text=True, timeout=60,
    )

    success = result.returncode == 0
    if success and os.path.exists(filepath):
        size = os.path.getsize(filepath)
        logger.info("手动备份数据库 by %s: %s (%.1f MB)", current_user["username"], filename, size / 1024 / 1024)
        return {
            "success": True,
            "message": f"备份成功: {filename}",
            "file": filename,
            "size_bytes": size,
        }
    else:
        return {"success": False, "message": f"备份失败: {result.stderr}"}


@router.post("/maintenance/test-all-channels")
def maintenance_test_all_channels(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    from services.push_service import _get_push_config, send_test_message

    config = _get_push_config()
    channels = config.get("enabled_channels", ["feishu"])
    results: dict[str, dict[str, Any]] = {}

    if "feishu" in channels:
        wh = config.get("feishu_webhook")
        if wh:
            ok = send_test_message("feishu", wh)
            results["feishu"] = {"success": ok, "message": "发送成功" if ok else "发送失败"}
        else:
            results["feishu"] = {"success": False, "message": "未配置 Webhook 地址"}

    if "wechat" in channels:
        wh = config.get("wechat_webhook")
        if wh:
            ok = send_test_message("wechat", wh)
            results["wechat"] = {"success": ok, "message": "发送成功" if ok else "发送失败"}
        else:
            results["wechat"] = {"success": False, "message": "未配置 Webhook 地址"}

    logger.info("一键测试所有推送渠道 by %s", current_user["username"])
    return {"results": results}
