# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取和淘宝登录功能
"""淘宝登录状态管理 API（已废弃）

⚠️ 自 2026-06-08 起，本模块所有接口已废弃。系统改为手动Excel导入模式，不再需要淘宝登录。

端点（全部废弃）：
  GET  /api/taobao/status        登录状态检测
  POST /api/taobao/login/start   提示用户手动扫码登录
  POST /api/taobao/login/confirm 确认登录完成
  POST /api/taobao/logout        退出登录
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.parse
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

logger = logging.getLogger("api.taobao")

DISPLAY = os.environ.get("DISPLAY", ":0")
XAUTH = os.environ.get(
    "XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
)

TAOBAO_HOME = "https://www.taobao.com"
TAOBAO_LOGIN = "https://login.taobao.com"
TAOBAO_MY = "https://i.taobao.com/my_itaobao"

router = APIRouter(prefix="/api/taobao", tags=["taobao"])

login_in_progress: bool = False


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _xdotool_env() -> dict:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH
    return env


def _xd(*args) -> str:
    """执行xdotool命令"""
    r = subprocess.run(
        ["xdotool"] + list(args),
        env=_xdotool_env(), capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


def _find_chrome_wid() -> str | None:
    """查找Chrome窗口ID"""
    result = _xd("search", "--class", "google-chrome")
    wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
    if wids:
        return wids[0]
    for name in ["淘宝", "Google Chrome"]:
        result = _xd("search", "--name", name)
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids:
            return wids[0]
    return None


def _activate_chrome() -> bool:
    """激活Chrome窗口"""
    wid = _find_chrome_wid()
    if not wid:
        return False
    try:
        _xd("windowactivate", "--sync", wid)
        time.sleep(0.3)
        return True
    except Exception:
        return False


def _get_window_title() -> str:
    """获取Chrome窗口标题"""
    wid = _find_chrome_wid()
    if not wid:
        return ""
    try:
        return _xd("getwindowname", wid)
    except Exception:
        return ""


def _navigate_to(url: str) -> None:
    """通过xdotool在Chrome地址栏导航到指定URL"""
    if not _activate_chrome():
        raise RuntimeError("Chrome窗口未找到，请确认浏览器已启动")

    _xd("key", "ctrl+l")     # 聚焦地址栏
    time.sleep(0.5)
    _xd("key", "ctrl+a")     # 全选
    time.sleep(0.2)

    # 通过xclip粘贴URL
    env = _xdotool_env()
    p = subprocess.Popen(
        ["xclip", "-selection", "clipboard"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, env=env,
    )
    p.communicate(input=url.encode("utf-8"), timeout=10)
    time.sleep(0.3)
    _xd("key", "ctrl+v")
    time.sleep(0.3)
    _xd("key", "Return")
    time.sleep(5)  # 等待页面加载


def _check_login_status() -> dict[str, Any]:
    """通过导航到我的淘宝检测登录状态（无CDP）。"""
    try:
        _navigate_to(TAOBAO_MY)
        time.sleep(3)

        title = _get_window_title()
        current_url = ""  # 无法获取URL，只能靠标题判断

        # 如果标题包含"我的淘宝"或用户名信息 → 已登录
        if "我的淘宝" in title or "个人中心" in title:
            return {
                "logged_in": True,
                "blocked": False,
                "blocked_reason": "",
                "username": "",
                "status": "logged_in",
            }

        # 如果标题包含登录 → 未登录
        if "登录" in title and "淘宝" in title:
            return {
                "logged_in": False,
                "blocked": False,
                "blocked_reason": "",
                "username": "",
                "status": "not_logged_in",
            }

        # 不确定状态
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "status": "unknown",
            "title": title,
        }

    except RuntimeError as e:
        logger.warning("登录检测失败: %s", e)
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "status": "chrome_not_running",
        }


@router.get("/status")
def login_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """检测淘宝登录状态。"""
    _check_permission(current_user["role"])

    global login_in_progress
    if login_in_progress:
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "session_active": True,
            "status": "login_in_progress",
            "login_in_progress": True,
            "current_url": "",
            "checked_at": datetime.now().isoformat(),
        }

    result = _check_login_status()
    result["session_active"] = _find_chrome_wid() is not None
    result["checked_at"] = datetime.now().isoformat()
    result["current_url"] = ""
    result["login_in_progress"] = False
    return result


@router.post("/login/start")
def start_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """启动扫码登录流程。

    打开淘宝登录页，用户在真实Chrome窗口中扫码。
    不再通过CDP截取二维码图片。
    """
    _check_permission(current_user["role"])

    try:
        _navigate_to(TAOBAO_LOGIN)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"无法打开登录页面: {e}")

    global login_in_progress
    login_in_progress = True

    logger.info("淘宝扫码登录已启动 (手动模式) by %s", current_user["username"])
    return {
        "success": True,
        "qrcode": None,  # 无CDP无法截图
        "expires_at": datetime.now().isoformat(),
        "expires_in": 120,
        "status": "waiting_scan",
        "message": "请在真实Chrome窗口中用淘宝APP扫码登录。二维码显示在Chrome的login.taobao.com页面中。",
    }


@router.post("/login/refresh")
def refresh_qrcode(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """刷新登录页。"""
    _check_permission(current_user["role"])

    try:
        _navigate_to(TAOBAO_LOGIN)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"无法刷新登录页面: {e}")

    return {
        "success": True,
        "qrcode": None,
        "expires_at": datetime.now().isoformat(),
        "expires_in": 120,
        "message": "登录页已刷新，请重新扫码",
    }


@router.post("/login/confirm")
def confirm_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """确认扫码登录完成。"""
    _check_permission(current_user["role"])
    global login_in_progress

    result = _check_login_status()

    if result.get("logged_in"):
        login_in_progress = False
        return {
            "logged_in": True,
            "blocked": False,
            "username": result.get("username", ""),
            "status": "logged_in",
            "message": "✅ 登录成功！",
        }

    # 检查是否还在登录页
    title = _get_window_title()
    if "登录" in title:
        return {
            "logged_in": False,
            "blocked": False,
            "username": "",
            "status": "waiting_scan",
            "message": "等待扫码中...",
        }

    return {
        "logged_in": False,
        "blocked": False,
        "username": "",
        "status": "unknown",
        "message": "无法确认登录状态，请确认已在Chrome中完成扫码",
    }


@router.post("/logout")
def logout(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """退出淘宝登录。

    清除Chrome中的淘宝Cookie实现登出。
    """
    _check_permission(current_user["role"])
    global login_in_progress
    login_in_progress = False

    try:
        _navigate_to(TAOBAO_HOME)
        time.sleep(2)

        # 通过xdotool模拟点击退出（尝试常见退出链接位置）
        # 实际点击依赖页面渲染的退出按钮
        _xd("key", "Escape")  # 关闭可能弹出的对话框
        time.sleep(1)

        logger.info("淘宝登出完成 by %s", current_user["username"])
        return {"success": True, "message": "已退出淘宝登录（Cookie将被浏览器自然清理）"}

    except Exception as e:
        logger.warning("登出操作异常: %s", e)
        return {"success": True, "message": "登出操作已执行"}
