"""服务控制 API

管理 supervisor 下的 fastapi-backend 和 nextjs-frontend 服务。
权限：仅 admin/manager 可操作。
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

logger = logging.getLogger("api.service")

router = APIRouter(prefix="/api/service", tags=["service"])

SUPERVISOR_CONF = "/home/lab-admin/price-monitor/supervisor.conf"
SUPERVISOR_CTL = "sudo supervisorctl -c " + SUPERVISOR_CONF
PROGRAMS = ["fastapi-backend", "nextjs-frontend"]


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _run_supervisorctl(command: str) -> dict[str, Any]:
    result = subprocess.run(
        f"{SUPERVISOR_CTL} {command}",
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "exit_code": result.returncode,
    }


@router.get("/status")
def service_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    result = _run_supervisorctl("status")
    services: dict[str, dict[str, str]] = {}

    for line in result["stdout"].split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] in PROGRAMS:
            services[parts[0]] = {
                "status": parts[1],
                "details": " ".join(parts[2:]) if len(parts) > 2 else "",
            }

    for prog in PROGRAMS:
        if prog not in services:
            services[prog] = {"status": "UNKNOWN", "details": ""}

    return {"services": services, "raw_output": result["stdout"][:500]}


@router.post("/restart")
def restart_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    result = _run_supervisorctl("restart all")
    logger.info("服务已重启 by %s", current_user["username"])

    success = result["exit_code"] == 0
    return {"success": success, "message": result["stdout"] or result["stderr"]}


@router.post("/stop")
def stop_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    result = _run_supervisorctl("stop all")
    logger.info("服务已停止 by %s", current_user["username"])

    success = result["exit_code"] == 0
    return {"success": success, "message": result["stdout"] or result["stderr"]}


@router.post("/start")
def start_services(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    result = _run_supervisorctl("start all")
    logger.info("服务已启动 by %s", current_user["username"])

    success = result["exit_code"] == 0
    return {"success": success, "message": result["stdout"] or result["stderr"]}
