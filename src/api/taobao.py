"""淘宝智能扫码登录 API

通过 OpenCLI 控制 Chrome 浏览器，管理淘宝账号扫码登录。
支持：自动状态检测、反爬封控识别、二维码刷新、登录确认、退出登录。
权限：仅 admin / manager 可操作。

端点：
  GET  /api/taobao/status        完整状态（登录态 + 封控态 + 用户名）
  POST /api/taobao/login/start   启动扫码登录（返回二维码 base64）
  POST /api/taobao/login/refresh 刷新二维码
  POST /api/taobao/login/confirm 确认登录完成
  POST /api/taobao/logout        退出登录
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.taobao")

OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")
OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
SESSION = "taobao_login"
OPENCLI_TIMEOUT = 30

TAOBAO_HOME = "https://www.taobao.com"
TAOBAO_LOGIN = "https://login.taobao.com"
TAOBAO_MY = "https://i.taobao.com/my_itaobao"
QR_EXPIRY_SECONDS = 120

router = APIRouter(prefix="/api/taobao", tags=["taobao"])

login_in_progress: bool = False


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _run_opencli(args: list[str], timeout: int = OPENCLI_TIMEOUT, binary: bool = False) -> subprocess.CompletedProcess[Any]:
    cmd = [OPENCLI_BIN, "--profile", OPENCLI_PROFILE] + args
    logger.info("opencli 执行: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=not binary, timeout=timeout)
        if result.returncode == 0:
            stdout_preview = (result.stdout or "")[:200]
            if stdout_preview:
                logger.info("opencli 成功: stdout=%s", stdout_preview)
            else:
                logger.info("opencli 成功: exit=0")
        else:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            logger.error("opencli 失败: exit=%d stderr=%s stdout=%s", result.returncode, stderr[:300], stdout[:300])
        return result
    except FileNotFoundError:
        logger.error("opencli 二进制不存在: %s", OPENCLI_BIN)
        raise RuntimeError(f"opencli 未安装，期望路径: {OPENCLI_BIN}")
    except subprocess.TimeoutExpired as e:
        logger.error("opencli 执行超时: %s", " ".join(cmd))
        raise RuntimeError(f"opencli 命令执行超时（{timeout}秒）: {' '.join(cmd)}")


def _session_exists() -> bool:
    try:
        result = _run_opencli(["browser", SESSION, "state"], timeout=10)
        if result.returncode == 0:
            return True
        stderr = (result.stderr or "").lower()
        return "not found" not in stderr and "no session" not in stderr and "unknown" not in stderr
    except Exception:
        return False


def _close_session() -> None:
    try:
        _run_opencli(["browser", SESSION, "close"], timeout=15)
        logger.info("浏览器会话已关闭: %s", SESSION)
    except Exception as e:
        logger.warning("关闭浏览器会话失败: %s", e)


def _take_screenshot() -> str | None:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    tmp_path = tmp.name
    try:
        result = _run_opencli(["browser", SESSION, "screenshot", tmp_path], timeout=20)
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
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(err[:300] or "eval 执行失败")
    return (result.stdout or "").strip()


def _navigate(url: str, timeout: int = 30) -> None:
    _run_opencli(["browser", SESSION, "open", url], timeout=timeout)


def _resize_viewport(width: int = 1920, height: int = 1080) -> None:
    js = f"window.resizeTo({width},{height});document.documentElement.style.minWidth='{width}px';"
    try:
        _eval_js(js, timeout=5)
        logger.info("viewport 已设置为 %dx%d", width, height)
    except Exception as e:
        logger.warning("设置 viewport 失败: %s", e)


def _ensure_page(url: str) -> None:
    """确保浏览器有可操作的页面。CDP 兜底创建 → opencli tab new → open。"""
    import requests
    try:
        pages_resp = requests.get("http://127.0.0.1:9222/json", timeout=5)
        pages = pages_resp.json()
        page_count = sum(1 for p in pages if p.get("type") == "page")
        if page_count == 0:
            logger.info("无浏览器窗口，CDP 创建兜底页面")
            requests.put("http://127.0.0.1:9222/json/new?about:blank", timeout=10)
            time.sleep(2)
    except Exception as e:
        logger.warning("CDP 页面检查失败: %s", e)

    _run_opencli(["browser", SESSION, "tab", "new"], timeout=15)
    _run_opencli(["browser", SESSION, "open", url], timeout=25)
    _resize_viewport()


def _wait(seconds: float) -> None:
    _run_opencli(["browser", SESSION, "wait", "time", str(int(seconds))], timeout=max(15, int(seconds) + 5))


DETECT_JS = """
(function() {
    var url = window.location.href || '';
    var bodyText = (document.body ? document.body.innerText : '') || '';
    var title = (document.title || '').toLowerCase();

    var blockedKeywords = ['已被限制', '账号已被', '冻结', '违规', '无法登录',
        '安全风险', '账号异常', '需验证', '请拖动滑块', '请完成安全验证',
        '验证码', '短信验证', '滑块验证', '手机验证'];
    var blocked = false;
    var blockedReason = '';
    for (var i = 0; i < blockedKeywords.length; i++) {
        if (bodyText.indexOf(blockedKeywords[i]) !== -1 || title.indexOf(blockedKeywords[i]) !== -1) {
            blocked = true;
            blockedReason = blockedKeywords[i];
            break;
        }
    }

    var isLoginPage = url.indexOf('login.taobao.com') !== -1 ||
                      url.indexOf('login.tmall.com') !== -1;

    var userSelectors = [
        '.site-nav-user .site-nav-login-info-nick',
        '.J_SiteNavLogin .site-nav-menu-hd .menu-hd-text',
        '[data-spm="duserinfo"]',
        '.site-nav-bd .nickname',
        '.J_UserMember .tnick',
        '.mytaobao-username',
        '.tb-header-username'
    ];
    var userEl = null;
    for (var j = 0; j < userSelectors.length; j++) {
        userEl = document.querySelector(userSelectors[j]);
        if (userEl && userEl.textContent.trim()) break;
    }
    var username = userEl ? userEl.textContent.trim().replace(/^hi[,\s]*/i, '').replace(/[\\s\\u00a0]+/g, '').trim() : '';

    var hasNavLogin = !!document.querySelector('.site-nav-login-info-nick') ||
                      !!document.querySelector('.J_SiteNavLogin');

    var loggedIn = !isLoginPage && (!!username || hasNavLogin);

    if (!loggedIn && !blocked && !isLoginPage) {
        var logoutLink = document.querySelector('a[href*="logout"]') ||
                         document.querySelector('a[href*="login.taobao.com/member/logout"]');
        if (logoutLink) loggedIn = true;
    }

    return JSON.stringify({
        url: url,
        title: document.title || '',
        isLoginPage: isLoginPage,
        loggedIn: loggedIn,
        blocked: blocked,
        blockedReason: blocked ? blockedReason : '',
        username: username,
        hasNavLogin: hasNavLogin
    });
})()
"""

LOGIN_PAGE_DETECT_JS = """
(function() {
    var url = window.location.href || '';
    var hasQR = !!document.querySelector('#J_QRCodeImg') ||
                !!document.querySelector('.qrcode-img') ||
                !!document.querySelector('img[src*="qr"]') ||
                !!document.querySelector('.icon-qr');
    var hasIframe = !!document.querySelector('iframe[id*="alibaba-login"]') ||
                    !!document.querySelector('iframe[src*="login"]');
    var qrExpired = false;
    var expireEl = document.querySelector('.qrcode-expired') ||
                   document.querySelector('[data-status="expired"]') ||
                   document.querySelector('.qrcode-tips');
    if (expireEl) {
        var tipsText = (expireEl.textContent || '').toLowerCase();
        qrExpired = tipsText.indexOf('已过期') !== -1 || tipsText.indexOf('expired') !== -1 ||
                    tipsText.indexOf('刷新') !== -1;
    }
    var hasRefreshBtn = !!document.querySelector('.qrcode-refresh') ||
                        !!document.querySelector('.J_QRCodeRefresh') ||
                        !!document.querySelector('[data-action="refresh"]');
    var bodyText = (document.body ? document.body.innerText : '') || '';
    var blocked = bodyText.indexOf('滑块') !== -1 || bodyText.indexOf('验证码') !== -1 ||
                  bodyText.indexOf('安全验证') !== -1 || bodyText.indexOf('异常') !== -1;
    return JSON.stringify({
        url: url,
        hasQR: hasQR,
        qrExpired: qrExpired,
        hasRefreshBtn: hasRefreshBtn,
        hasIframe: hasIframe,
        blocked: blocked
    });
})()
"""


@router.get("/status")
def login_status(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    global login_in_progress
    if login_in_progress:
        logger.info("登录流程进行中，status 接口跳过导航检测")
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

    session_active = _session_exists()
    if not session_active:
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "session_active": False,
            "status": "no_session",
            "login_in_progress": False,
            "current_url": "",
            "checked_at": datetime.now().isoformat(),
        }

    try:
        _navigate(TAOBAO_HOME, timeout=20)
        _wait(2.5)
    except Exception as e:
        logger.warning("导航到淘宝首页失败: %s", e)
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "session_active": True,
            "status": "navigate_error",
            "login_in_progress": False,
            "current_url": "",
            "checked_at": datetime.now().isoformat(),
        }

    try:
        result_str = _eval_js(DETECT_JS, timeout=15)
        data: dict[str, Any] = json.loads(result_str)

        logged_in = bool(data.get("loggedIn") or data.get("logged_in"))
        blocked = bool(data.get("blocked"))
        username = str(data.get("username", "") or "")

        if blocked:
            detail = str(data.get("blockedReason", "") or data.get("blocked_reason", ""))
            return {
                "logged_in": False,
                "blocked": True,
                "blocked_reason": detail,
                "username": username,
                "session_active": True,
                "status": "blocked",
                "login_in_progress": False,
                "current_url": data.get("url", ""),
                "checked_at": datetime.now().isoformat(),
            }

        if logged_in:
            return {
                "logged_in": True,
                "blocked": False,
                "blocked_reason": "",
                "username": username,
                "session_active": True,
                "status": "logged_in",
                "login_in_progress": False,
                "current_url": data.get("url", ""),
                "checked_at": datetime.now().isoformat(),
            }

        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "session_active": True,
            "status": "not_logged_in",
            "login_in_progress": False,
            "current_url": data.get("url", ""),
            "checked_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.exception("检测登录状态时异常")
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "session_active": True,
            "status": "detect_error",
            "login_in_progress": False,
            "current_url": "",
            "checked_at": datetime.now().isoformat(),
        }


@router.post("/login/start")
def start_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    try:
        _ensure_page(TAOBAO_LOGIN)
        _wait(4.0)
        logger.info("已打开淘宝登录页并创建会话: %s", SESSION)
    except Exception as e:
        logger.exception("打开淘宝登录页失败")
        raise HTTPException(status_code=500, detail=f"无法打开登录页面: {e}")

    qrcode_base64 = _take_screenshot()
    if not qrcode_base64:
        raise HTTPException(status_code=500, detail="页面截图失败，请重试")

    global login_in_progress
    login_in_progress = True

    expires_at = datetime.now().isoformat()
    logger.info("淘宝扫码登录已启动 by %s login_in_progress=True", current_user["username"])
    return {
        "success": True,
        "session": SESSION,
        "qrcode": f"data:image/png;base64,{qrcode_base64}",
        "expires_at": expires_at,
        "expires_in": QR_EXPIRY_SECONDS,
        "status": "waiting_scan",
        "message": "请使用淘宝APP扫描二维码登录",
    }


@router.post("/login/refresh")
def refresh_qrcode(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    if not _session_exists():
        raise HTTPException(status_code=400, detail="登录会话已过期，请重新启动登录")

    try:
        _ensure_page(TAOBAO_LOGIN)
        _wait(3.0)
        logger.info("已重新导航到登录页")
    except Exception as e:
        logger.error("刷新登录页失败: %s", e)
        raise HTTPException(status_code=500, detail=f"刷新登录页失败: {e}")

    qrcode_base64 = _take_screenshot()
    if not qrcode_base64:
        raise HTTPException(status_code=500, detail="页面截图失败，请重试")

    expires_at = datetime.now().isoformat()
    return {
        "success": True,
        "qrcode": f"data:image/png;base64,{qrcode_base64}",
        "expires_at": expires_at,
        "expires_in": QR_EXPIRY_SECONDS,
        "message": "二维码已刷新",
    }


@router.post("/login/confirm")
def confirm_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """确认扫码登录完成。

    当 login_in_progress 时，仅检查当前页面 URL 是否已离开登录页，
    而不主动导航（避免打断扫码流程）。
    当登录成功、被封控或会话过期时，清除 login_in_progress 标记。
    """
    _check_permission(current_user["role"])

    global login_in_progress

    if not _session_exists():
        login_in_progress = False
        return {
            "logged_in": False,
            "blocked": False,
            "username": "",
            "status": "expired",
            "message": "登录会话已过期，请重新启动登录",
        }

    if login_in_progress:
        page_url_js = "(function() { return window.location.href || ''; })()"
        try:
            current_url = _eval_js(page_url_js, timeout=5)
        except Exception:
            current_url = ""

        logger.info("confirm 轮询: 当前页面URL=%s login_in_progress=True", current_url[:120])

        is_still_login_page = "login.taobao.com" in current_url or "login.tmall.com" in current_url
        if is_still_login_page:
            return {
                "logged_in": False,
                "blocked": False,
                "blocked_reason": "",
                "username": "",
                "status": "waiting_scan",
                "message": "等待扫码中...",
            }

        logger.info("confirm: 已离开登录页，尝试检测登录状态, URL=%s", current_url[:120])

    try:
        _navigate(TAOBAO_MY, timeout=20)
        _wait(2.5)
    except Exception as e:
        logger.warning("导航到我的淘宝失败: %s", e)
        try:
            _navigate(TAOBAO_HOME, timeout=20)
            _wait(2.5)
        except Exception:
            pass

    try:
        result_str = _eval_js(DETECT_JS, timeout=15)
        data: dict[str, Any] = json.loads(result_str)

        blocked = bool(data.get("blocked"))
        if blocked:
            detail = str(data.get("blockedReason", "") or data.get("blocked_reason", ""))
            login_in_progress = False
            return {
                "logged_in": False,
                "blocked": True,
                "blocked_reason": detail,
                "username": "",
                "status": "blocked",
                "message": f"⚠️ 该淘宝账号已被限制（{detail}），请更换账号",
            }

        logged_in = bool(data.get("loggedIn") or data.get("logged_in"))
        username = str(data.get("username", "") or "")

        if logged_in and username:
            login_in_progress = False
            logger.info("淘宝登录确认成功: username=%s login_in_progress=False", username)
            return {
                "logged_in": True,
                "blocked": False,
                "blocked_reason": "",
                "username": username,
                "status": "logged_in",
                "message": f"✅ 登录成功！当前账号：{username}",
            }

        if logged_in and not username:
            login_in_progress = False
            logger.info("淘宝登录确认: 已登录但未识别到用户名")
            return {
                "logged_in": True,
                "blocked": False,
                "blocked_reason": "",
                "username": "",
                "status": "logged_in_partial",
                "message": "✅ 已登录淘宝（未识别到用户名）",
            }

        is_login_page = bool(data.get("isLoginPage"))
        if is_login_page:
            return {
                "logged_in": False,
                "blocked": False,
                "blocked_reason": "",
                "username": "",
                "status": "waiting_scan",
                "message": "等待扫码中...",
            }

        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "status": "unknown",
            "message": "无法确认登录状态，请重试",
        }

    except Exception as e:
        logger.exception("确认登录状态异常")
        return {
            "logged_in": False,
            "blocked": False,
            "blocked_reason": "",
            "username": "",
            "status": "error",
            "message": f"检测失败: {str(e)[:200]}",
        }


@router.post("/logout")
def logout(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    global login_in_progress
    login_in_progress = False

    if not _session_exists():
        logger.info("登出时发现会话不存在，视为已登出")
        return {
            "success": True,
            "message": "已退出登录（会话已关闭）",
        }

    try:
        _navigate(TAOBAO_HOME, timeout=15)
        _wait(2.0)

        logout_js = """
        (function() {
            var logoutLink = document.querySelector('a[href*="logout"]') ||
                             document.querySelector('a[href*="login.taobao.com/member/logout"]') ||
                             document.querySelector('.site-nav-logout');
            if (logoutLink) { logoutLink.click(); return 'clicked'; }
            var userMenu = document.querySelector('.site-nav-user') ||
                           document.querySelector('.J_SiteNavLogin');
            if (userMenu) { userMenu.click(); return 'menu_opened'; }
            return 'not_found';
        })()
        """
        action = _eval_js(logout_js, timeout=10)
        logger.info("登出操作: %s", action)
        if action and action.strip('"') in ("clicked", "menu_opened"):
            _wait(2.0)
    except Exception as e:
        logger.warning("页面登出操作失败: %s，将关闭会话", e)

    _close_session()
    logger.info("淘宝登出完成 by %s", current_user["username"])
    return {
        "success": True,
        "message": "已退出淘宝登录",
    }
