# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取功能
"""淘宝滑块验证码自动求解器

核心策略（按优先级）:
1. 关闭被封页面 → OpenCLI 打开新标签页（绕过验证码触发）
2. X11 XTest 真实鼠标拖拽求解（OS级事件，isTrusted=true）
3. CDP Input.dispatchMouseEvent 兜底（合成事件，低成功率）

关键修正:
- 使用 screen_x/screen_y（含视口偏移）而不是 viewport 坐标
- 拖拽前检查坐标是否有效（> 100 才可能是屏幕坐标）
- 最大化窗口确保滑块位置固定
"""

import ctypes
import ctypes.util
import json
import logging
import math
import os
import random
import subprocess
import time
import urllib.request
from typing import Any

logger = logging.getLogger("captcha_solver")

_display = None
_xlib = None

OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")


def _init_x11() -> tuple:
    """初始化 X11 + XTest"""
    global _display, _xlib
    if _display is not None:
        return _display, _xlib

    os.environ.setdefault("DISPLAY", ":0")
    _xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
    _display = _xlib.XOpenDisplay(None)
    if not _display:
        raise RuntimeError("Cannot open X11 display")
    return _display, _xlib


def detect_captcha() -> dict[str, Any] | None:
    """通过 CDP 只读检测验证码（不启用 Input 域）。
    Returns: None 或 {screen_x, screen_y, distance, ...}"""
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
        targets = json.loads(resp.read())

        captcha_target = None
        for t in targets:
            if t.get("type") == "page" and (
                "验证码" in t.get("title", "") or "punish" in t.get("url", "")
            ):
                captcha_target = t
                break
        if not captcha_target:
            return None

        import websocket
        ws = websocket.create_connection(
            captcha_target["webSocketDebuggerUrl"], timeout=10, origin=""
        )

        msg = {"id": 1, "method": "Runtime.evaluate", "params": {"expression": """
        (function() {
            var s = document.querySelector('#nc_1_n1z');
            var t = document.querySelector('#nc_1__scale_text');
            if (!s || !t) return JSON.stringify({found: false});
            var sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect();

            // Viewport-to-screen offset
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            var ox = (window.screenLeft || 0) + fl;
            var oy = (window.screenTop || 0) + to;

            return JSON.stringify({
                found: true,
                screen_x: Math.round(sr.x + sr.width/2 + ox),
                screen_y: Math.round(sr.y + sr.height/2 + oy),
                viewport_x: Math.round(sr.x + sr.width/2),
                viewport_y: Math.round(sr.y + sr.height/2),
                distance: Math.round(tr.x + tr.width - sr.x - sr.width + 3),
                offset_x: Math.round(ox), offset_y: Math.round(oy)
            });
        })();
        """, "returnByValue": True}}
        ws.send(json.dumps(msg))
        raw = ws.recv()
        data = json.loads(json.loads(raw).get("result", {}).get("result", {}).get("value", "{}"))
        ws.close()

        if data.get("found"):
            logger.info("验证码: screen=(%d,%d) dist=%d",
                       data["screen_x"], data["screen_y"], data["distance"])
            return data
        return None
    except Exception:
        logger.debug("验证码检测异常", exc_info=True)
        return None


def ensure_no_captcha(max_retries: int = 3) -> bool:
    """确保当前无验证码。失败则通过 OpenCLI 恢复。"""
    captcha = detect_captcha()
    if not captcha:
        return True

    for attempt in range(1, max_retries + 1):
        logger.info("验证码处理 (attempt=%d/%d)", attempt, max_retries)

        # Strategy A: Close + OpenCLI fresh tab
        if attempt <= 2:
            try:
                _close_captcha_pages()
                time.sleep(2)
                session = f"nocap_{int(time.time())}"
                subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                               "browser", session, "tab", "new"],
                               capture_output=True, text=True, timeout=30)
                subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                               "browser", session, "open", "https://www.taobao.com/"],
                               capture_output=True, text=True, timeout=30)
                time.sleep(5)
                subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                               "browser", session, "close"],
                               capture_output=True, text=True, timeout=10)
                time.sleep(3)
                if not detect_captcha():
                    logger.info("恢复成功 (attempt=%d)", attempt)
                    return True
            except Exception as e:
                logger.warning("Strategy A 失败: %s", e)

        # Strategy B: X11 real mouse drag
        if attempt >= 2 and captcha:
            try:
                _x11_drag_slider(captcha)
                time.sleep(4)
                if not detect_captcha():
                    logger.info("X11 拖拽成功 (attempt=%d)", attempt)
                    return True
            except Exception as e:
                logger.warning("Strategy B 失败: %s", e)

        time.sleep(2 ** attempt + random.uniform(1, 3))

    logger.error("验证码处理失败: %d 次重试", max_retries)
    return False


def _close_captcha_pages() -> None:
    try:
        import websocket
        resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
        for t in json.loads(resp.read()):
            if t.get("type") == "page" and ("验证码" in t.get("title", "") or "punish" in t.get("url", "")):
                ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                ws.send(json.dumps({"id": 1, "method": "Page.close"}))
                ws.recv(); ws.close()
    except Exception:
        pass


def _x11_drag_slider(captcha: dict) -> None:
    """使用 X11 XTest 执行真实鼠标拖拽滑块。

    captcha 必须包含 screen_x/screen_y（已调整视口偏移的屏幕坐标）。
    """
    disp, xlib = _init_x11()
    xtest = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))

    def mov(x, y):
        xtest.XTestFakeMotionEvent(disp, 0, int(x), int(y), 0)
        xlib.XSync(disp, 0)

    # Use screen coordinates if available, otherwise estimate offset
    sx = captcha.get("screen_x", 0)
    sy = captcha.get("screen_y", 0)
    dist = captcha.get("distance", 260) + random.randint(-3, 5)

    # If coordinates look like viewport coords (< 100 offset from edge), add offset
    if sx < 200 and "viewport_x" in captcha:
        sx += captcha.get("offset_x", 60)
        sy += captcha.get("offset_y", 148)

    logger.info("X11 drag: screen(%d,%d) dist=%d", sx, sy, dist)

    # Approach
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    for i in range(14):
        p = (i + 1) / 14
        mov(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
        time.sleep(0.015 + random.random() * 0.02)

    # Hover
    mov(sx, sy)
    time.sleep(0.25 + random.random() * 0.35)

    # Press
    xtest.XTestFakeButtonEvent(disp, 1, 1, 0); xlib.XSync(disp, 0)
    time.sleep(0.03)

    # Drag - 280+ points
    pts = 280 + random.randint(40, 80)
    total_t = 3.0 + random.random() * 2.5
    for i in range(pts):
        p = i / pts
        if p < 0.08: e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
        else: r = (1 - p) / 0.12; e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.005

        x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 +
              math.sin(p * math.pi * 7.3) * 0.6 +
              math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02: yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        mov(x, y)
        time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

    # Settle + overshoot
    mov(int(sx + dist), int(sy)); time.sleep(0.05)
    mov(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1))); time.sleep(0.04)
    mov(int(sx + dist), int(sy)); time.sleep(0.05)

    # Pre-release pause
    time.sleep(0.18 + random.random() * 0.25)
    xtest.XTestFakeButtonEvent(disp, 1, 0, 0); xlib.XSync(disp, 0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    c = detect_captcha()
    print(f"Captcha: {'YES' if c else 'NO'}")
    if c:
        print(f"  screen=({c['screen_x']},{c['screen_y']}) dist={c['distance']}")
