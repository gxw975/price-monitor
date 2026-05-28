"""淘宝扫码登录 API

通过 OpenCLI 控制 Chrome 浏览器，管理淘宝账号扫码登录。
支持：启动登录页、获取二维码截图、检测登录状态、检测账号封禁。
权限：仅 admin / manager 可操作。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.taobao")

OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")
SESSION = "taobao_login"
OPENCLI_TIMEOUT = 30

LOGIN_URL = "https://login.taobao.com/member/login.jhtml?style=mini&from=taobao"

router = APIRouter(prefix="/api/taobao", tags=["taobao"])


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _run_opencli(args: list[str], timeout: int = OPENCLI_TIMEOUT, binary: bool = False) -> subprocess.CompletedProcess[Any]:
    cmd = ["opencli", "--profile", OPENCLI_PROFILE] + args
    logger.debug("opencli: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=not binary, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.strip() if not binary and result.stderr else ""
        logger.warning("opencli 失败: exit=%d stderr=%s", result.returncode, stderr[:200])
    return result


def _session_exists() -> bool:
    try:
        result = _run_opencli(["browser", SESSION, "status"], timeout=10)
        if result.returncode == 0 and "RUNNING" in (result.stdout or ""):
            return True
        return "not exist" not in (result.stderr or "").lower() and result.returncode == 0
    except Exception:
        return False


def _close_session() -> None:
    try:
        _run_opencli(["browser", SESSION, "close"], timeout=15)
    except Exception:
        pass


def _take_screenshot() -> str | None:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        result = _run_opencli([
            "browser", SESSION, "screenshot",
            "--output", tmp_path,
        ], timeout=20)
        if result.returncode == 0 and os.path.getsize(tmp_path) > 100:
            with open(tmp_path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        return None
    except Exception as e:
        logger.warning("截图失败: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _eval_js(js_code: str, timeout: int = 15) -> str:
    result = _run_opencli(["browser", SESSION, "eval", js_code], timeout=timeout)
    if result.returncode != 0:
        raise Exception(result.stderr or "eval failed")
    return (result.stdout or "").strip()


@router.post("/start-login")
def start_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    try:
        _close_session()
        time.sleep(1)
    except Exception:
        pass

    try:
        result = _run_opencli(["browser", SESSION, "tab", "new"], timeout=15)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="无法创建浏览器会话")

        _run_opencli(["browser", SESSION, "open", LOGIN_URL], timeout=20)
        time.sleep(4)

        qrcode_base64 = _take_screenshot()
        if not qrcode_base64:
            raise HTTPException(status_code=500, detail="截图失败，请重试")

        logger.info("淘宝登录页已打开 by %s", current_user["username"])
        return {
            "success": True,
            "session": SESSION,
            "qrcode": f"data:image/png;base64,{qrcode_base64}",
            "status": "waiting",
            "message": "请使用淘宝APP扫描二维码登录",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("启动淘宝登录失败")
        raise HTTPException(status_code=500, detail=f"启动登录失败: {e}")


@router.get("/qrcode")
def get_qrcode(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    if not _session_exists():
        raise HTTPException(status_code=400, detail="登录会话已过期，请重新点击刷新登录")

    try:
        qrcode_base64 = _take_screenshot()
        if not qrcode_base64:
            raise HTTPException(status_code=500, detail="截图失败")

        return {
            "qrcode": f"data:image/png;base64,{qrcode_base64}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取二维码失败")
        raise HTTPException(status_code=500, detail=f"获取二维码失败: {e}")


@router.get("/check-login")
def check_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    if not _session_exists():
        return {"logged_in": False, "banned": False, "username": "", "status": "expired", "message": "登录会话已过期，请重新刷新登录"}

    try:
        check_js = """
        (function() {
            var url = window.location.href;
            var body = document.body.innerText || '';
            var banned = body.includes('已被限制') || body.includes('账号已被') || body.includes('冻结') ||
                        body.includes('违规') || body.includes('无法登录') || body.includes('安全风险');

            var userEl = document.querySelector('.site-nav-user .site-nav-login-info-nick') ||
                         document.querySelector('.J_SiteNavLogin .site-nav-menu-hd .menu-hd-text') ||
                         document.querySelector('[data-spm="duserinfo"]') ||
                         document.querySelector('.tb-wangwang') ||
                         document.querySelector('.site-nav-bd .nickname');

            var username = userEl ? userEl.textContent.trim() : '';
            var loggedIn = !url.includes('login.taobao.com') || !!username || !!userEl;

            return JSON.stringify({
                url: url,
                loggedIn: loggedIn,
                banned: banned,
                username: username,
                hasUserEl: !!userEl
            });
        })()
        """
        result_str = _eval_js(check_js, timeout=15)
        data = json.loads(result_str)

        if data.get("banned"):
            return {
                "logged_in": False,
                "banned": True,
                "username": data.get("username", ""),
                "status": "banned",
                "message": "⚠ 该淘宝账号已被限制登录，请更换其他账号扫码",
            }

        if data.get("loggedIn") and data.get("username"):
            return {
                "logged_in": True,
                "banned": False,
                "username": data["username"],
                "status": "logged_in",
                "message": f"✅ 登录成功！当前账号：{data['username']}",
            }

        if data.get("loggedIn") and not data.get("username"):
            return {
                "logged_in": True,
                "banned": False,
                "username": "",
                "status": "logged_in_partial",
                "message": "✅ 已登录淘宝（未识别到用户名）",
            }

        return {
            "logged_in": False,
            "banned": False,
            "username": "",
            "status": "waiting",
            "message": "等待扫码中...",
        }

    except Exception as e:
        logger.warning("检测登录状态失败: %s", e)
        return {
            "logged_in": False,
            "banned": False,
            "username": "",
            "status": "error",
            "message": f"检测失败: {e}",
        }


@router.get("/status")
def login_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    session_active = _session_exists()
    if not session_active:
        return {"status": "no_session", "logged_in": False, "message": "无活跃登录会话"}

    try:
        status_js = """
        (function() {
            var url = window.location.href;
            var userEl = document.querySelector('.site-nav-user .site-nav-login-info-nick') ||
                         document.querySelector('.J_SiteNavLogin .site-nav-menu-hd .menu-hd-text') ||
                         document.querySelector('[data-spm="duserinfo"]') ||
                         document.querySelector('.site-nav-bd .nickname');
            var username = userEl ? userEl.textContent.trim() : '';

            var banned = (document.body.innerText || '').includes('已被限制') ||
                        (document.body.innerText || '').includes('冻结');

            return JSON.stringify({
                url: url,
                loggedIn: !url.includes('login.taobao.com') || !!username,
                username: username,
                banned: banned
            });
        })()
        """
        data = json.loads(_eval_js(status_js, timeout=10))

        return {
            "status": "active",
            "session": SESSION,
            "logged_in": data.get("loggedIn", False),
            "banned": data.get("banned", False),
            "username": data.get("username", ""),
            "current_url": data.get("url", ""),
        }
    except Exception as e:
        return {
            "status": "active",
            "session": SESSION,
            "logged_in": False,
            "message": f"检测状态时出错: {e}",
        }
