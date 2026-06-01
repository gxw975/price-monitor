"""淘宝智能扫码登录 API

通过 CDP 直连控制 Chrome 浏览器，管理淘宝账号扫码登录。
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
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.taobao")

CDP_HOST = "127.0.0.1"
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
SESSION = "taobao_login"

TAOBAO_HOME = "https://www.taobao.com"
TAOBAO_LOGIN = "https://login.taobao.com"
TAOBAO_MY = "https://i.taobao.com/my_itaobao"
QR_EXPIRY_SECONDS = 120

router = APIRouter(prefix="/api/taobao", tags=["taobao"])

login_in_progress: bool = False


def _check_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


# ═══════════════════════════════════════════════════════════════
# CDP 直连工具函数（替代 OpenCLI）
# ═══════════════════════════════════════════════════════════════

def _cdp_connect(url_hint: str = "") -> websocket.WebSocket:
    """连接到 Chrome 页面，如果没有则创建一个。"""
    try:
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
        targets = json.loads(resp.read())
    except Exception:
        raise RuntimeError("无法连接到 Chrome，请确认浏览器已启动")

    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        # 创建新页面
        urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/new?about:blank", timeout=10)
        time.sleep(1)
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
        targets = json.loads(resp.read())
        pages = [t for t in targets if t.get("type") == "page"]

    target = None
    if url_hint:
        for p in pages:
            if url_hint in p.get("url", ""):
                target = p
                break

    if not target:
        for p in pages:
            if "about:blank" in p.get("url", ""):
                target = p
                break

    if not target:
        target = pages[0]

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15, origin="")
    logger.info("CDP 已连接: %s", target.get("url", "")[:80])
    return ws


def _cdp_send(ws: websocket.WebSocket, method: str, params: dict | None = None, timeout: int = 15) -> dict:
    """发送 CDP 命令并等待响应。"""
    msg_id = int(time.time() * 1000) % 1000000
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ws.recv()
        resp = json.loads(raw)
        if resp.get("id") == msg_id:
            if "error" in resp:
                raise RuntimeError(f"CDP error: {resp['error']}")
            return resp
    raise RuntimeError(f"CDP 命令超时: {method}")


def _cdp_safe_send(ws: websocket.WebSocket, method: str, params: dict | None = None, timeout: int = 10) -> dict | None:
    """发送 CDP 命令，失败返回 None。"""
    try:
        return _cdp_send(ws, method, params, timeout)
    except Exception as e:
        logger.warning("CDP 命令失败 %s: %s", method, e)
        return None


# ═══════════════════════════════════════════════════════════════
# 高层操作（CDP 实现）
# ═══════════════════════════════════════════════════════════════

def _ensure_page(url: str) -> websocket.WebSocket:
    """确保有可操作的页面，导航到指定 URL。"""
    ws = _cdp_connect()
    _cdp_send(ws, "Page.enable")
    _cdp_send(ws, "Runtime.enable")
    _cdp_send(ws, "Page.navigate", {"url": url})
    time.sleep(4)
    # 等页面加载
    for _ in range(5):
        try:
            r = _cdp_send(ws, "Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            if r.get("result", {}).get("result", {}).get("value") == "complete":
                break
        except Exception:
            pass
        time.sleep(1)
    return ws


def _eval_js(ws: websocket.WebSocket, js_code: str, timeout: int = 15) -> str:
    """执行 JS 并返回结果字符串。"""
    r = _cdp_send(ws, "Runtime.evaluate", {
        "expression": js_code,
        "returnByValue": True,
        "awaitPromise": True,
    }, timeout=timeout)
    return str(r.get("result", {}).get("result", {}).get("value", ""))


def _take_screenshot(ws: websocket.WebSocket) -> str | None:
    """通过 CDP Page.captureScreenshot 截图，返回 base64。"""
    try:
        r = _cdp_send(ws, "Page.captureScreenshot", {"format": "png"}, timeout=20)
        data = r.get("result", {}).get("data", "")
        if data:
            return data
        return None
    except Exception as e:
        logger.warning("CDP 截图失败: %s", e)
        return None


def _navigate(ws: websocket.WebSocket, url: str) -> None:
    """导航到指定 URL。"""
    _cdp_send(ws, "Page.navigate", {"url": url}, timeout=30)
    time.sleep(3)


def _wait(seconds: float) -> None:
    """等待指定秒数。"""
    time.sleep(seconds)


def _resize_viewport(ws: websocket.WebSocket, width: int = 1920, height: int = 1080) -> None:
    js = f"window.resizeTo({width},{height});"
    try:
        _eval_js(ws, js, timeout=5)
        logger.info("viewport 已设置为 %dx%d", width, height)
    except Exception as e:
        logger.warning("设置 viewport 失败: %s", e)


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
        return {
            "logged_in": False, "blocked": False, "blocked_reason": "",
            "username": "", "session_active": True,
            "status": "login_in_progress", "login_in_progress": True,
            "current_url": "", "checked_at": datetime.now().isoformat(),
        }

    ws = None
    try:
        ws = _cdp_connect()
        _navigate(ws, TAOBAO_HOME)
        _wait(2.5)

        result_str = _eval_js(ws, DETECT_JS, timeout=15)
        data: dict[str, Any] = json.loads(result_str)

        logged_in = bool(data.get("loggedIn") or data.get("logged_in"))
        blocked = bool(data.get("blocked"))
        username = str(data.get("username", "") or "")

        if blocked:
            return {
                "logged_in": False, "blocked": True,
                "blocked_reason": str(data.get("blockedReason", "")),
                "username": username, "session_active": True,
                "status": "blocked", "login_in_progress": False,
                "current_url": data.get("url", ""),
                "checked_at": datetime.now().isoformat(),
            }

        if logged_in:
            return {
                "logged_in": True, "blocked": False, "blocked_reason": "",
                "username": username, "session_active": True,
                "status": "logged_in", "login_in_progress": False,
                "current_url": data.get("url", ""),
                "checked_at": datetime.now().isoformat(),
            }

        return {
            "logged_in": False, "blocked": False, "blocked_reason": "",
            "username": "", "session_active": True,
            "status": "not_logged_in", "login_in_progress": False,
            "current_url": data.get("url", ""),
            "checked_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.exception("检测登录状态时异常")
        return {
            "logged_in": False, "blocked": False, "blocked_reason": "",
            "username": "", "session_active": False,
            "status": "detect_error", "login_in_progress": False,
            "current_url": "", "checked_at": datetime.now().isoformat(),
        }
    finally:
        if ws:
            try: ws.close()
            except: pass


@router.post("/login/start")
def start_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    ws = None
    try:
        ws = _ensure_page(TAOBAO_LOGIN)
        _wait(2.0)

        qrcode_base64 = _take_screenshot(ws)
        if not qrcode_base64:
            raise HTTPException(status_code=500, detail="页面截图失败，请重试")

        global login_in_progress
        login_in_progress = True

        logger.info("淘宝扫码登录已启动 by %s", current_user["username"])
        return {
            "success": True,
            "qrcode": f"data:image/png;base64,{qrcode_base64}",
            "expires_at": datetime.now().isoformat(),
            "expires_in": QR_EXPIRY_SECONDS,
            "status": "waiting_scan",
            "message": "请使用淘宝APP扫描二维码登录",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("打开淘宝登录页失败")
        raise HTTPException(status_code=500, detail=f"无法打开登录页面: {e}")
    finally:
        if ws:
            try: ws.close()
            except: pass


@router.post("/login/refresh")
def refresh_qrcode(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])

    ws = None
    try:
        ws = _ensure_page(TAOBAO_LOGIN)
        _wait(2.0)

        qrcode_base64 = _take_screenshot(ws)
        if not qrcode_base64:
            raise HTTPException(status_code=500, detail="页面截图失败，请重试")

        return {
            "success": True,
            "qrcode": f"data:image/png;base64,{qrcode_base64}",
            "expires_at": datetime.now().isoformat(),
            "expires_in": QR_EXPIRY_SECONDS,
            "message": "二维码已刷新",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("刷新登录页失败: %s", e)
        raise HTTPException(status_code=500, detail=f"刷新登录页失败: {e}")
    finally:
        if ws:
            try: ws.close()
            except: pass


@router.post("/login/confirm")
def confirm_login(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """确认扫码登录完成。"""
    _check_permission(current_user["role"])
    global login_in_progress

    ws = None
    try:
        ws = _cdp_connect()

        if login_in_progress:
            try:
                current_url = _eval_js(ws, "(function() { return window.location.href || ''; })()", timeout=5)
            except Exception:
                current_url = ""

            logger.info("confirm 轮询: URL=%s", current_url[:120] if current_url else "")
            is_still_login = "login.taobao.com" in (current_url or "") or "login.tmall.com" in (current_url or "")
            if is_still_login:
                return {
                    "logged_in": False, "blocked": False, "username": "",
                    "status": "waiting_scan", "message": "等待扫码中...",
                }

        # 导航到我的淘宝检测登录
        try:
            _navigate(ws, TAOBAO_MY); _wait(3.0)
        except Exception:
            _navigate(ws, TAOBAO_HOME); _wait(3.0)

        result_str = _eval_js(ws, DETECT_JS, timeout=15)
        data: dict[str, Any] = json.loads(result_str)

        if data.get("blocked"):
            login_in_progress = False
            return {
                "logged_in": False, "blocked": True,
                "blocked_reason": str(data.get("blockedReason", "")),
                "username": "", "status": "blocked",
                "message": f"⚠️ 该淘宝账号已被限制",
            }

        logged_in = bool(data.get("loggedIn") or data.get("logged_in"))
        username = str(data.get("username", "") or "")

        if logged_in:
            login_in_progress = False
            return {
                "logged_in": True, "blocked": False,
                "username": username, "status": "logged_in",
                "message": f"✅ 登录成功！{username}" if username else "✅ 已登录",
            }

        if data.get("isLoginPage"):
            return {
                "logged_in": False, "blocked": False, "username": "",
                "status": "waiting_scan", "message": "等待扫码中...",
            }

        return {
            "logged_in": False, "blocked": False, "username": "",
            "status": "unknown", "message": "无法确认登录状态，请重试",
        }

    except Exception as e:
        logger.exception("确认登录状态异常")
        return {
            "logged_in": False, "blocked": False, "username": "",
            "status": "error", "message": f"检测失败: {str(e)[:200]}",
        }
    finally:
        if ws:
            try: ws.close()
            except: pass


@router.post("/logout")
def logout(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_permission(current_user["role"])
    global login_in_progress
    login_in_progress = False

    ws = None
    try:
        ws = _cdp_connect()
        _navigate(ws, TAOBAO_HOME)
        _wait(2.0)

        _eval_js(ws, """
        (function() {
            var link = document.querySelector('a[href*="logout"]');
            if (link) { link.click(); return; }
            var menu = document.querySelector('.site-nav-user, .J_SiteNavLogin');
            if (menu) { menu.click(); }
        })()
        """, timeout=10)
        _wait(2.0)
    except Exception as e:
        logger.warning("页面登出操作失败: %s", e)
    finally:
        if ws:
            try: ws.close()
            except: pass

    logger.info("淘宝登出完成 by %s", current_user["username"])
    return {"success": True, "message": "已退出淘宝登录"}
