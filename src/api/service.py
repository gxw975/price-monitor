"""服务控制 API

通过端口检测管理 fastapi-backend (3001) 和 nextjs-frontend (3000) 服务。
权限：仅 admin/manager 可操作。
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

logger = logging.getLogger("api.service")

router = APIRouter(prefix="/api/service", tags=["service"])

PROGRAMS = {
    "fastapi-backend": {"port": 3001, "pattern": "uvicorn main:app"},
    "nextjs-frontend": {"port": 3000, "pattern": "next-server"},
}


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _check_port(port: int) -> bool:
    """检查端口是否在监听。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def _find_pid(pattern: str) -> int | None:
    """查找匹配进程的 PID。"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid.strip().isdigit():
                return int(pid.strip())
    except Exception:
        pass
    return None


@router.get("/status")
def service_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    services: dict[str, dict[str, str]] = {}
    for name, cfg in PROGRAMS.items():
        alive = _check_port(cfg["port"])
        services[name] = {
            "status": "RUNNING" if alive else "STOPPED",
            "port": str(cfg["port"]),
        }
    return {"services": services}


@router.post("/restart")
def restart_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    results = {}
    for name, cfg in PROGRAMS.items():
        pid = _find_pid(cfg["pattern"])
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
            except Exception:
                pass

        # 重启
        if name == "fastapi-backend":
            subprocess.Popen(
                [
                    "/home/lab-admin/price-monitor/.venv/bin/python3",
                    "-m", "uvicorn", "main:app",
                    "--host", "127.0.0.1", "--port", "3001",
                    "--app-dir", "/home/lab-admin/price-monitor/src",
                ],
                env={**os.environ, "PYTHONPATH": "/home/lab-admin/price-monitor/src"},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif name == "nextjs-frontend":
            subprocess.Popen(
                ["/home/lab-admin/price-monitor/node_modules/.bin/next", "start", "-p", "3000"],
                cwd="/home/lab-admin/price-monitor",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

        time.sleep(2)
        alive = _check_port(cfg["port"])
        results[name] = "RUNNING" if alive else "FAILED"

    logger.info("服务已重启 by %s: %s", current_user["username"], results)
    all_ok = all(v == "RUNNING" for v in results.values())
    return {"success": all_ok, "message": str(results)}


@router.post("/stop")
def stop_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    for name, cfg in PROGRAMS.items():
        pid = _find_pid(cfg["pattern"])
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    logger.info("服务已停止 by %s", current_user["username"])
    return {"success": True, "message": "服务已停止"}


@router.post("/start")
def start_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    result = restart_services(current_user)
    logger.info("服务已启动 by %s", current_user["username"])
    return result
