"""TagUI RPA 淘宝关键词抓取服务

基于 TagUI RPA + CDP (Chrome DevTools Protocol) 实现淘宝关键词数据抓取。
核心改进：
1. TagUI 控制主工作流（导航、点击、输入）
2. CDP Input.dispatchMouseEvent 处理滑块验证（产生真实可信鼠标事件）
3. 完整的异常处理：滑块验证、封禁检测、加载失败重试
4. 原生Chrome图形界面，完全模拟真人操作

用法:
    from services.tagui_crawler import TaguiCrawler
    crawler = TaguiCrawler()
    result = crawler.crawl_keyword("纸巾")
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import math
import os
import random
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("tagui_crawler")

TAGUI_BIN = "/home/lab-admin/price-monitor/tools/tagui/src/tagui"
CHROME_BIN = "/usr/bin/google-chrome-stable"
CHROME_USER_DATA = "/home/lab-admin/.config/google-chrome-profile-manual"
CDP_HOST = "127.0.0.1"
CDP_PORT = 9223
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
DISPLAY = ":0"
DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")

DIANTOUSHI_ACCOUNT = os.environ.get("DIANTOUSHI_ACCOUNT", "18627759568")
DIANTOUSHI_PASSWORD = os.environ.get("DIANTOUSHI_PASSWORD", "791123")

MAX_SLIDER_RETRIES = 5
SLIDER_VERIFY_WAIT = 6
AUTO_LOAD_BATCH_SIZE = 8
AUTO_LOAD_INTERVAL = 30
AUTO_LOAD_PAUSE = 300
MAX_AUTO_LOAD_BATCHES = 6
FLOW_TIMEOUT = 45 * 60


class CrawlError(Exception):
    pass


class SliderVerifyError(CrawlError):
    pass


class AccountBannedError(CrawlError):
    pass


class TaguiCrawler:
    """TagUI RPA 淘宝关键词抓取器"""

    def __init__(self):
        self._ws = None
        self._msg_id = 1
        self._chrome_proc = None

    # ═══════════════════════════════════════════════════════════════
    # Chrome 生命周期管理
    # ═══════════════════════════════════════════════════════════════

    def _kill_chrome(self) -> None:
        """清理所有Chrome进程"""
        logger.info("[Chrome] 清理所有Chrome进程...")
        subprocess.run(["pkill", "-f", "chrome"], capture_output=True)
        subprocess.run(["pkill", "-f", "ensure-chrome"], capture_output=True)
        time.sleep(2)
        subprocess.run(["killall", "-9", "chrome"], capture_output=True)
        time.sleep(1)

        for tmp_dir in Path("/tmp").glob("com.google.Chrome.*"):
            try:
                tmp_dir.rmdir()
            except OSError:
                pass
        logger.info("[Chrome] 进程清理完成")

    def _start_chrome(self) -> subprocess.Popen:
        """启动原生Chrome浏览器（带CDP远程调试端口）"""
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE

        cmd = [
            CHROME_BIN,
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage",
            "--ozone-platform=x11",
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            f"--user-data-dir={CHROME_USER_DATA}",
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-allow-origins=*",
            "about:blank",
        ]

        logger.info("[Chrome] 启动Chrome (CDP端口: %d)", CDP_PORT)
        proc = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._chrome_proc = proc
        time.sleep(5)

        if proc.poll() is not None:
            raise CrawlError("Chrome启动失败")

        logger.info("[Chrome] Chrome已启动 (PID: %d)", proc.pid)
        return proc

    # ═══════════════════════════════════════════════════════════════
    # CDP 通信
    # ═══════════════════════════════════════════════════════════════

    def _cdp_connect(self, url_hint: str = "") -> Any:
        """通过CDP连接到Chrome页面"""
        import websocket

        for attempt in range(10):
            try:
                resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
                targets = json.loads(resp.read())
                page = None
                for t in targets:
                    if t.get("type") == "page":
                        if url_hint and url_hint in t.get("url", ""):
                            page = t
                            break
                        elif not url_hint:
                            # 优先选非登录页的taobao页面
                            u = t.get("url", "")
                            if "taobao.com" in u and "login." not in u:
                                page = t
                                break
                if not page and not url_hint:
                    # 退而求其次：任意taobao页面（含login页）
                    for t in targets:
                        if t.get("type") == "page" and "taobao.com" in t.get("url", ""):
                            page = t
                            break
                if not page and not url_hint:
                    # 最后退路：第一个页面
                    page = next((t for t in targets if t.get("type") == "page"), None)
                if not page:
                    time.sleep(2)
                    continue

                ws_url = page["webSocketDebuggerUrl"]
                ws = websocket.create_connection(ws_url, timeout=30)
                self._ws = ws
                self._msg_id = 1

                for domain in ("Page", "Runtime", "DOM"):
                    self._cdp_send(f"{domain}.enable")

                logger.info("[CDP] 已连接到: %s", page.get("url", "")[:80])
                return ws
            except Exception as e:
                logger.debug("[CDP] 连接尝试 %d 失败: %s", attempt + 1, e)
                time.sleep(3)

        raise CrawlError("无法连接到Chrome CDP")

    def _cdp_send(self, method: str, params: Optional[dict] = None) -> dict:
        """发送CDP命令并返回结果"""
        if not self._ws:
            raise CrawlError("CDP未连接")

        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        self._ws.send(json.dumps(msg))
        self._msg_id += 1

        while True:
            resp = json.loads(self._ws.recv())
            if resp.get("id") == self._msg_id - 1:
                if "error" in resp:
                    logger.warning("[CDP] 命令错误: %s", resp["error"])
                return resp
            if resp.get("method") == "Event.networkRequestWillBeSent":
                continue

    def _cdp_eval(self, expression: str, return_by_value: bool = True) -> Any:
        """执行JavaScript并返回结果"""
        resp = self._cdp_send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": True,
        })
        result = resp.get("result", {}).get("result", {})
        return result.get("value", "")

    def _cdp_navigate(self, url: str) -> None:
        """导航到指定URL"""
        self._cdp_send("Page.navigate", {"url": url})
        time.sleep(3)

    def _cdp_mouse_click(self, x: float, y: float) -> None:
        """使用CDP Input.dispatchMouseEvent执行真实鼠标点击"""
        self._cdp_send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        time.sleep(0.05)
        self._cdp_send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })

    def _cdp_drag_slider(self, start_x: float, start_y: float, distance: float) -> bool:
        """使用CDP Input.dispatchMouseEvent模拟真人拖动滑块

        模拟真人拖动特征：
        1. 非匀速（开始慢→中间快→结束慢）
        2. Y轴微小抖动
        3. 随机停顿
        4. 结束时微小过冲和回拉
        """
        import random as rng

        self._cdp_send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": start_x, "y": start_y,
            "button": "left", "clickCount": 1,
        })

        steps = [
            0.02, 0.05, 0.08, 0.12, 0.17, 0.23, 0.30,
            0.38, 0.46, 0.54, 0.62, 0.70, 0.77, 0.83,
            0.88, 0.92, 0.95, 0.97, 0.99, 1.02, 1.0,
        ]

        for ratio in steps:
            cx = start_x + distance * min(ratio, 1.0)
            cy = start_y + rng.uniform(-1.5, 1.5)
            self._cdp_send("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": cx, "y": cy,
            })
            base_delay = 0.03
            if ratio < 0.15:
                delay = base_delay + rng.uniform(0.02, 0.06)
            elif ratio > 0.9:
                delay = base_delay + rng.uniform(0.03, 0.08)
            else:
                delay = base_delay + rng.uniform(0.01, 0.03)
            time.sleep(delay)

        final_x = start_x + distance
        self._cdp_send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": final_x, "y": start_y,
            "button": "left", "clickCount": 1,
        })

        logger.info("[滑块] 拖动完成: (%.0f, %.0f) -> (%.0f, %.0f)", start_x, start_y, final_x, start_y)
        return True

    # ═══════════════════════════════════════════════════════════════
    # 滑块验证处理
    # ═══════════════════════════════════════════════════════════════

    def _detect_captcha(self) -> bool:
        """检测淘宝滑块验证弹窗（punish iframe可见性 + 页面文本兜底判据）

        主判据：主页面中src含'punish'的iframe存在且getBoundingClientRect()宽高>0。
        兜底判据：页面body文本包含'请拖动下方滑块'（iframe可能未加载但弹窗文字已出现）。
        """
        try:
            result = self._cdp_eval("""
            (function() {
                var frames = document.querySelectorAll('iframe');
                for (var i = 0; i < frames.length; i++) {
                    if ((frames[i].src || '').indexOf('punish') !== -1) {
                        var rect = frames[i].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            return 'captcha_visible';
                        }
                    }
                }
                var bodyText = document.body ? (document.body.innerText || '') : '';
                if (bodyText.indexOf('请拖动下方滑块') !== -1) return 'captcha_text';
                return 'none';
            })()
            """)

            if result in ("captcha_visible", "captcha_text"):
                logger.warning("[验证] 检测到淘宝滑块验证弹窗 (type=%s)", result)
                return True

            return False
        except Exception:
            return False

    def _detect_banned(self) -> bool:
        """检测账号封禁提示"""
        try:
            result = self._cdp_eval("""
            (function() {
                var text = document.body ? document.body.innerText : '';
                if (text.indexOf('近期访问行为存在异常') !== -1) return 'banned';
                if (text.indexOf('账号被限制') !== -1) return 'banned';
                if (text.indexOf('操作过于频繁') !== -1) return 'rate_limit';
                return 'ok';
            })()
            """)
            if result == 'banned':
                logger.error("[封禁] 检测到账号封禁提示")
                return True
            if result == 'rate_limit':
                logger.warning("[限流] 检测到操作频率限制")
            return False
        except Exception:
            return False

    def _dismiss_chrome_dialog(self) -> bool:
        """关闭Chrome偏好设置等弹窗"""
        try:
            result = self._cdp_eval("""
            (function() {
                var btns = document.querySelectorAll('button, [role="button"]');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].textContent || '').trim();
                    if (txt === '确定' || txt === 'OK' || txt === '知道了') {
                        btns[i].click();
                        return 'clicked: ' + txt;
                    }
                }
                return 'no_dialog';
            })()
            """)
            if result != 'no_dialog':
                logger.info("[弹窗] 关闭弹窗: %s", result)
                time.sleep(1)
                return True
            return False
        except Exception:
            return False

    def _os_type(self, text: str) -> None:
        """使用xdotool模拟真实键盘输入"""
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "50", text],
            env=env, capture_output=True, timeout=30,
        )

    def _os_enter(self) -> None:
        """使用xdotool模拟真实回车键"""
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE
        subprocess.run(
            ["xdotool", "key", "Return"],
            env=env, capture_output=True, timeout=10,
        )

    def _os_click(self, x: int, y: int) -> None:
        """使用xdotool模拟真实鼠标点击"""
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE
        subprocess.run(
            ["xdotool", "mousemove", str(x), str(y)],
            env=env, capture_output=True, timeout=10,
        )
        time.sleep(0.2)
        subprocess.run(
            ["xdotool", "click", "1"],
            env=env, capture_output=True, timeout=10,
        )

    def _os_activate_chrome(self) -> None:
        """激活Chrome窗口（非阻塞）"""
        try:
            # 先用 CDP bringToFront
            self._cdp_send("Page.bringToFront")
            time.sleep(0.5)
        except Exception:
            pass

        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", "淘宝"],
                env=env, capture_output=True, text=True, timeout=5,
            )
            window_ids = result.stdout.strip().split()
            if window_ids:
                subprocess.run(
                    ["xdotool", "windowactivate", window_ids[0]],
                    env=env, capture_output=True, timeout=5,
                )
                logger.info("[OS] 激活Chrome窗口: %s", window_ids[0])
                time.sleep(0.5)
        except Exception:
            logger.debug("[OS] 窗口激活失败，继续执行")

    _x11_display = None
    _x11_xtest = None
    _x11_X = None

    def _init_x11(self):
        """初始化 python-xlib display（已验证通过滑块验证）"""
        if self._x11_display is not None:
            return self._x11_display
        os.environ.setdefault("DISPLAY", DISPLAY)
        os.environ.setdefault("XAUTHORITY", XAUTH_FILE)
        from Xlib import X, display as xdisplay
        from Xlib.ext import xtest as xext
        self._x11_display = xdisplay.Display()
        self._x11_xtest = xext
        self._x11_X = X
        return self._x11_display

    def _x11_drag_slider(self, captcha: dict) -> None:
        """python-xlib滑块拖拽（280+点 / 3-5.5秒 / 正弦波抖动 — 对齐captcha_solver.py已验证算法）"""
        import math as _math
        disp = self._init_x11()
        xtest = self._x11_xtest
        X = self._x11_X

        def mov(x, y):
            xtest.fake_input(disp, X.MotionNotify, x=int(x), y=int(y))
            disp.sync()

        def click(button, down):
            xtest.fake_input(disp,
                X.ButtonPress if down else X.ButtonRelease, detail=button)
            disp.sync()

        sx = captcha.get("screen_x", 0)
        sy = captcha.get("screen_y", 0)
        dist = captcha.get("distance", 259) + random.randint(-3, 5)

        # 接近滑块
        ax = sx - random.randint(35, 55)
        ay = sy + random.randint(-10, 10)
        for i in range(14):
            p = (i + 1) / 14
            mov(int(ax + (sx - ax) * p),
                int(ay + (sy - ay) * p + _math.sin(i * 0.5) * 5))
            time.sleep(0.015 + random.random() * 0.02)

        # 悬停
        mov(sx, sy)
        time.sleep(0.25 + random.random() * 0.35)

        # 按下
        click(1, True)
        time.sleep(0.03)

        # 慢速拖拽：280+点，3-5.5秒，正弦波抖动
        pts = 280 + random.randint(40, 80)
        total_t = 3.0 + random.random() * 2.5
        for i in range(pts):
            p = i / pts
            if p < 0.08:
                e = (p / 0.08) ** 2 * 0.08
            elif p < 0.88:
                e = 0.08 + (p - 0.08) * 0.84
            else:
                r = (1 - p) / 0.12
                e = 1 - r * r * 0.12
            e += (random.random() - 0.5) * 0.005

            x = int(sx + dist * e)
            yj = (_math.sin(p * _math.pi * 3.1) * 2.5 +
                  _math.sin(p * _math.pi * 7.3) * 0.6 +
                  _math.sin(p * _math.pi * 13.7) * 0.3)
            if random.random() < 0.02:
                yj += (random.random() - 0.5) * 8
            y = int(sy + yj)
            mov(x, y)
            time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

        # 到达 + 过冲回弹
        mov(int(sx + dist), int(sy))
        time.sleep(0.05)
        mov(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
        time.sleep(0.04)
        mov(int(sx + dist), int(sy))
        time.sleep(0.05)

        # 松开前停留
        time.sleep(0.18 + random.random() * 0.25)
        click(1, False)

        logger.info("[X11] 拖拽完成: %d点/%.1fs dist=%d", pts, total_t, dist)

    def _switch_to_new_tab(self, url_hint: str = "") -> None:
        """切换到搜索结果的标签页（优先匹配title=\"淘宝搜索\"）"""
        try:
            resp = urllib.request.urlopen(
                f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5
            )
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]

            target = None

            if url_hint:
                for p in pages:
                    if "淘宝搜索" in (p.get("title") or ""):
                        target = p
                        logger.info("[标签页] 通过title=\"淘宝搜索\"找到: %s", p.get("url", "")[:80])
                        break
                if not target:
                    for p in pages:
                        if url_hint in p.get("url", ""):
                            target = p
                            logger.info("[标签页] 通过URL匹配找到: %s", p.get("url", "")[:80])
                            break

            if not target:
                logger.warning("[标签页] 未找到匹配标签页 (hint=%s), 已打开: %d 个页面", url_hint, len(pages))
                for i, p in enumerate(pages):
                    logger.warning("  [%d] title=\"%s\" url=%s", i, p.get("title", ""), p.get("url", "")[:80])
                return

            ws_url = target.get("webSocketDebuggerUrl", "")
            if not ws_url:
                return

            import websocket
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass

            ws = websocket.create_connection(ws_url, timeout=30)
            self._ws = ws
            self._msg_id = 1

            for domain in ("Page", "Runtime", "DOM"):
                self._cdp_send(f"{domain}.enable")

            self._maximize_window()
            logger.info("[标签页] 已切换到: %s", target.get("url", "")[:80])
        except Exception as e:
            logger.warning("[标签页] 切换失败: %s", e)

    def _maximize_window(self) -> None:
        """最大化浏览器窗口"""
        try:
            targets = json.loads(urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json").read())
            page_target = next((t for t in targets if t.get("type") == "page"), None)
            if not page_target:
                return

            ws_url = page_target["webSocketDebuggerUrl"]
            import websocket
            ws = websocket.create_connection(ws_url, timeout=5)
            ws.send(json.dumps({"id": 1, "method": "Browser.getWindowForTarget", "params": {"targetId": page_target.get("id")}}))
            resp = json.loads(ws.recv())
            window_id = resp.get("result", {}).get("windowId")
            ws.close()

            if window_id:
                self._cdp_send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "maximized"}
                })
                logger.info("[窗口] 已最大化 (windowId: %d)", window_id)
                time.sleep(2)
        except Exception as e:
            logger.debug("[窗口] 最大化失败: %s", e)

    def _handle_captcha(self) -> bool:
        """处理滑块验证（python-xlib物理拖拽 + page warmup + 焦点激活）

        经验文档方法 + 已验证：python-xlib OS级事件 + CDP精确定位 + 拟人化轨迹。
        每次拖拽参数随机变化，防止服务端模式检测。
        """
        self._maximize_window()

        # 页面预热：滚动 + 鼠标移动（激活事件监听）
        self._cdp_send("Page.bringToFront")
        self._cdp_eval("window.scrollBy(0, {})".format(random.randint(50, 150)))
        time.sleep(0.3)

        for attempt in range(MAX_SLIDER_RETRIES):
            logger.info("[滑块] 第 %d/%d 次尝试验证", attempt + 1, MAX_SLIDER_RETRIES)

            captcha_data = self._detect_captcha_with_position()
            if not captcha_data:
                logger.info("[滑块] 验证弹窗已消失，验证通过")
                return True

            if captcha_data.get("error") == "errloading":
                logger.info("[滑块] errloading状态，物理点击恢复...")
                self._click_errloading(captcha_data)
                time.sleep(2.5)
                continue

            try:
                dist = captcha_data.get("distance", 259)
                logger.info("[滑块] 拖拽: screen(%d,%d) dist=%d",
                           captcha_data.get("screen_x", 0),
                           captcha_data.get("screen_y", 0),
                           dist)
                self._x11_drag_slider(captcha_data)
                time.sleep(SLIDER_VERIFY_WAIT)

                if not self._detect_captcha():
                    logger.info("[滑块] ✅ 验证通过!")
                    return True

                logger.warning("[滑块] 拖拽后punish iframe仍在，重试...")
            except Exception as e:
                logger.warning("[滑块] 处理异常: %s", e)
                time.sleep(2)

        logger.error("[滑块] 验证失败，已达最大重试次数 %d", MAX_SLIDER_RETRIES)
        return False

    def _click_errloading(self, captcha_data: dict) -> None:
        """物理点击errloading恢复按钮（通过CDP contextId在iframe内查询位置）"""
        try:
            OX, OY = 66, 119

            # 重新进入iframe获取errloading坐标（需要contextId才能读到iframe内DOM）
            resp = self._cdp_send("Page.getFrameTree")
            frame_tree = resp.get("result", {}).get("frameTree", {})
            punish_fid = None
            def find_punish(node):
                nonlocal punish_fid
                for c in node.get("childFrames", []):
                    f = c.get("frame", {})
                    if "h5api.m.taobao.com" in f.get("url", "") and "punish" in f.get("url", ""):
                        punish_fid = f.get("id", "")
                        return
                    find_punish(c)
            find_punish(frame_tree)
            if not punish_fid:
                return

            iso = self._cdp_send("Page.createIsolatedWorld", {"frameId": punish_fid})
            err_ctx = iso.get("result", {}).get("executionContextId")
            if not err_ctx:
                return
            time.sleep(0.15)

            r = self._cdp_send("Runtime.evaluate", {
                "expression": """(function(){
                    var e = document.querySelector('.errloading');
                    if (!e) return JSON.stringify({found:false});
                    var rect = e.getBoundingClientRect();
                    return JSON.stringify({x:Math.round(rect.x+rect.width/2), y:Math.round(rect.y+rect.height/2)});
                })()""",
                "contextId": err_ctx,
                "returnByValue": True,
            })
            err_data = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
            if not err_data.get("found"):
                return

            # 获取iframe在主页面中的视口位置
            iframe_pos = self._cdp_eval("""(function(){
                var fs = document.querySelectorAll('iframe');
                for (var i=0; i<fs.length; i++) {
                    if ((fs[i].src||'').indexOf('h5api') !== -1) {
                        var r = fs[i].getBoundingClientRect();
                        return JSON.stringify({x:Math.round(r.x), y:Math.round(r.y)});
                    }
                }
                return JSON.stringify({found:false});
            })()""")
            ip = json.loads(iframe_pos) if isinstance(iframe_pos, str) else {"found": False}

            ex = int(ip.get("x", 397) + err_data["x"] + OX)
            ey = int(ip.get("y", 181) + err_data["y"] + OY)

            disp = self._init_x11()
            xtest = self._x11_xtest
            X = self._x11_X

            xtest.fake_input(disp, X.MotionNotify, x=ex, y=ey)
            disp.sync()
            time.sleep(0.1)
            xtest.fake_input(disp, X.ButtonPress, detail=1)
            disp.sync()
            time.sleep(0.05)
            xtest.fake_input(disp, X.ButtonRelease, detail=1)
            disp.sync()
            logger.info("[errloading] 物理点击完成: screen(%d,%d)", ex, ey)
        except Exception as e:
            logger.warning("[errloading] 点击失败: %s", e)

    def _check_captcha_barrier(self, step_name: str) -> None:
        """每步操作后自动检查是否有滑块验证弹窗，有则自动处理"""
        if self._detect_captcha():
            logger.warning("[屏障] 步骤「%s」后检测到滑块验证，自动处理...", step_name)
            success = self._handle_captcha()
            if success:
                logger.info("[屏障] 滑块验证处理成功")
            else:
                logger.error("[屏障] 滑块验证处理失败")

    def _detect_captcha_with_position(self) -> Optional[dict]:
        """检测滑块验证弹窗并返回精确屏幕坐标（CDP contextId方法）

        经验文档标准流程：
        1. Page.getFrameTree 找到 h5api.m.taobao.com/punish 的 frameId
        2. Page.createIsolatedWorld 获取 executionContextId
        3. Runtime.evaluate(contextId=xxx) 查询 iframe 内 #nc_1_n1z 滑块坐标
        4. 屏幕坐标 = iframe视口位置 + 滑块iframe内位置 + (ox=66, oy=119)
        
        返回值: {"found":True, "screen_x":int, "screen_y":int, "distance":int}
                {"found":True, "error":"errloading"}  // 验证失败需重试
                None  // 验证弹窗不存在 ≈ 已通过
        """
        OX, OY = 66, 119
        try:
            resp = self._cdp_send("Page.getFrameTree")
            frame_tree = resp.get("result", {}).get("frameTree", {})
            punish_fid = None
            def find_punish(node):
                nonlocal punish_fid
                for c in node.get("childFrames", []):
                    f = c.get("frame", {})
                    url = f.get("url", "")
                    if "h5api.m.taobao.com" in url and "punish" in url:
                        punish_fid = f.get("id", "")
                        return
                    find_punish(c)
            find_punish(frame_tree)
            if not punish_fid:
                return None

            iso = self._cdp_send("Page.createIsolatedWorld", {"frameId": punish_fid})
            ctx_id = iso.get("result", {}).get("executionContextId")
            if not ctx_id:
                logger.warning("[验证] 未能获取iframe执行上下文")
                return None
            time.sleep(0.2)

            resp = self._cdp_send("Runtime.evaluate", {
                "expression": """(function(){
                    var s = document.querySelector('[id*=\"nc_1_n1z\"]');
                    var t = document.querySelector('[id*=\"nc_1__scale_text\"]');
                    if (!s || !t) {
                        var w = document.querySelector('[id*=\"nc_1_wrapper\"]');
                        if (w && (w.innerHTML||'').indexOf('errloading') !== -1)
                            return JSON.stringify({found:true, error:'errloading'});
                        return JSON.stringify({found:false});
                    }
                    var sr = s.getBoundingClientRect();
                    var tr = t.getBoundingClientRect();
                    return JSON.stringify({
                        found: true,
                        slider_iframe_x: Math.round(sr.x + sr.width/2),
                        slider_iframe_y: Math.round(sr.y + sr.height/2),
                        distance: Math.round(tr.x + tr.width - sr.x - sr.width + 3)
                    });
                })()""",
                "contextId": ctx_id,
                "returnByValue": True,
            })
            result = resp.get("result", {}).get("result", {}).get("value", "{}")
            data = json.loads(result) if isinstance(result, str) else {"found": False}

            if data.get("error") == "errloading":
                return {"found": True, "error": "errloading"}
            if not data.get("found"):
                return None

            # 计算屏幕坐标
            iframe_pos = self._cdp_eval("""(function(){
                var fs = document.querySelectorAll('iframe');
                for (var i=0; i<fs.length; i++) {
                    if ((fs[i].src||'').indexOf('h5api') !== -1) {
                        var r = fs[i].getBoundingClientRect();
                        return JSON.stringify({x:Math.round(r.x), y:Math.round(r.y)});
                    }
                }
                return JSON.stringify({found:false});
            })()""")
            ip = json.loads(iframe_pos) if isinstance(iframe_pos, str) else {"found": False}

            screen_x = int(ip.get("x", 397) + data["slider_iframe_x"] + OX)
            screen_y = int(ip.get("y", 181) + data["slider_iframe_y"] + OY)
            distance = data["distance"]

            logger.info("[验证] 精确读取: iframe内=(%d,%d) screen=(%d,%d) dist=%d",
                       data["slider_iframe_x"], data["slider_iframe_y"],
                       screen_x, screen_y, distance)
            return {"found": True, "screen_x": screen_x, "screen_y": screen_y, "distance": distance}
        except Exception as e:
            logger.warning("[验证] _detect_captcha_with_position异常: %s", e)
            return None

    # ═══════════════════════════════════════════════════════════════
    # 店透视操作
    # ═══════════════════════════════════════════════════════════════

    def _ensure_dts_login(self) -> bool:
        """确保店透视扩展已登录"""
        try:
            resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
            targets = json.loads(resp.read())

            extension_id = "ppgdlgnehnajbbngnohepfigdmjbdpfb"
            sw_target = next(
                (t for t in targets if t.get("type") == "service_worker" and extension_id in t.get("url", "")),
                None,
            )
            if not sw_target:
                logger.warning("[DTS] 店透视扩展Service Worker未找到")
                return False

            import websocket
            ws_url = sw_target["webSocketDebuggerUrl"]
            ws = websocket.create_connection(ws_url, timeout=10, origin="")

            ws.send(json.dumps({
                "id": 1, "method": "Runtime.evaluate",
                "params": {
                    "expression": """new Promise(function(resolve){
                        chrome.storage.local.get(['token','online'], function(data){
                            resolve(JSON.stringify(data));
                        });
                    })""",
                    "returnByValue": True, "awaitPromise": True,
                },
            }))
            raw = json.loads(ws.recv())
            val = raw.get("result", {}).get("result", {}).get("value", "{}")
            storage = json.loads(val)
            ws.close()

            if storage.get("token") and storage.get("online"):
                logger.info("[DTS] 店透视已登录")
                return True

            logger.info("[DTS] 店透视未登录，开始登录...")
            login_data = urllib.parse.urlencode({
                "mobile": DIANTOUSHI_ACCOUNT,
                "password": DIANTOUSHI_PASSWORD,
            }).encode()
            req = urllib.request.Request(
                "https://diantoushi.com/user/login",
                data=login_data, method="POST",
            )
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read())

            if result.get("code") == 0 or result.get("status") == 0 or result.get("token"):
                token = result.get("token", "")
                if not token and result.get("extData"):
                    token = result["extData"].get("token", "")
                if token:
                    ws2 = websocket.create_connection(ws_url, timeout=10, origin="")
                    ws2.send(json.dumps({
                        "id": 1, "method": "Runtime.evaluate",
                        "params": {
                            "expression": f"""new Promise(function(resolve){{
                                chrome.storage.local.set({{token:'{token}',online:true}}, function(){{
                                    resolve('ok');
                                }});
                            }})""",
                            "returnByValue": True, "awaitPromise": True,
                        },
                    }))
                    ws2.recv()
                    ws2.close()
                    logger.info("[DTS] 店透视登录成功")
                    return True

            logger.warning("[DTS] 店透视登录失败: %s", result)
            return False

        except Exception as e:
            logger.warning("[DTS] 登录异常: %s", e)
            return False

    def _trigger_dts_extension(self) -> bool:
        """触发店透视扩展"""
        try:
            result = self._cdp_eval("""
            (function() {
                var ev = new CustomEvent('dts-search-trigger', {detail: {keyword: ''}});
                document.dispatchEvent(ev);
                var click = document.querySelector('[class*="dts-"], [class*="diantoushi"]');
                if (click) { click.click(); return 'clicked'; }
                return 'dispatched';
            })()
            """)
            logger.info("[DTS] 触发扩展: %s", result)
            return True
        except Exception as e:
            logger.warning("[DTS] 触发扩展失败: %s", e)
            return False

    def _get_viewport_offset(self) -> tuple:
        """获取viewport到屏幕坐标的偏移量"""
        try:
            result = self._cdp_eval("""
            (function() {
                var fl = (window.outerWidth - window.innerWidth) / 2;
                var to = window.outerHeight - window.innerHeight - fl;
                var ox = (window.screenLeft || 0) + fl;
                var oy = (window.screenTop || 0) + to;
                return JSON.stringify({ox: Math.round(ox), oy: Math.round(oy)});
            })()
            """)
            data = json.loads(result) if isinstance(result, str) else {}
            return data.get("ox", 66), data.get("oy", 119)
        except Exception:
            return 66, 119

    def _check_new_tabs_after_click(self) -> None:
        """检查点击后是否有新标签页打开"""
        try:
            resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            logger.info("[DTS] 当前标签页数量: %d", len(pages))
            for i, p in enumerate(pages):
                url = p.get("url", "")[:80]
                title = p.get("title", "")[:40]
                logger.info("[DTS]   [%d] title=\"%s\" url=%s", i, title, url)
        except Exception as e:
            logger.warning("[DTS] 检查标签页异常: %s", e)

    def _click_market_analysis(self) -> bool:
        """点击店透视市场分析入口（对齐 dts_full_export.py 成功经验）"""
        try:
            self._cdp_eval("""
            (function() {
                var floatBtn = document.querySelector('[class*="dts-float"], [class*="dtsFloat"]');
                if (floatBtn) floatBtn.click();
            })();
            """)
            time.sleep(2)

            dts_info = self._cdp_eval("""
            (function() {
                var el = document.querySelector('.itemToolsBox');
                if (!el) {
                    el = document.querySelector('[class*="itemToolsBox"]');
                }
                if (!el) return JSON.stringify({found: false, reason: 'no_itemToolsBox'});

                var children = el.querySelectorAll('div, span, a');
                for (var i = 0; i < children.length; i++) {
                    var txt = (children[i].textContent || '').trim();
                    if (txt === '市场分析') {
                        var cr = children[i].getBoundingClientRect();
                        return JSON.stringify({
                            found: true,
                            text: '市场分析',
                            x: Math.round(cr.x + cr.width/2),
                            y: Math.round(cr.y + cr.height/2),
                            inView: cr.y >= 0 && cr.y < window.innerHeight
                        });
                    }
                }
                return JSON.stringify({found: false, reason: 'no_child'});
            })()
            """)

            info = json.loads(dts_info) if isinstance(dts_info, str) else {"found": False}
            logger.info("[DTS] 市场分析按钮: %s", dts_info[:200] if dts_info else "null")

            if info.get("found") and info.get("inView"):
                self._cdp_mouse_click(info["x"], info["y"])
                logger.info("[DTS] CDP鼠标点击市场分析 @ (%d, %d)", info.get("x", 0), info.get("y", 0))
                time.sleep(1)
                ox, oy = self._get_viewport_offset()
                sx = info["x"] + ox
                sy = info["y"] + oy
                self._os_click(int(sx), int(sy))
                logger.info("[DTS] xdotool点击市场分析 @ screen(%d,%d)", int(sx), int(sy))
                time.sleep(3)
                self._check_new_tabs_after_click()
                return True

            if info.get("found"):
                logger.warning("[DTS] 按钮不可见(y=%d)，滚动并重新定位...", info.get("y", 0))
                self._cdp_eval("""
                (function() {
                    var el = document.querySelector('.itemToolsBox');
                    if (el) el.scrollIntoView({behavior: 'instant', block: 'nearest'});
                })()
                """)
                time.sleep(2)

                dts_info2 = self._cdp_eval("""
                (function() {
                    var el = document.querySelector('.itemToolsBox');
                    if (!el) el = document.querySelector('[class*="itemToolsBox"]');
                    if (!el) return JSON.stringify({found: false});

                    var children = el.querySelectorAll('div, span, a');
                    for (var i = 0; i < children.length; i++) {
                        var txt = (children[i].textContent || '').trim();
                        if (txt === '市场分析') {
                            var cr = children[i].getBoundingClientRect();
                            return JSON.stringify({
                                found: true, x: Math.round(cr.x + cr.width/2),
                                y: Math.round(cr.y + cr.height/2),
                                inView: cr.y >= 0 && cr.y < window.innerHeight
                            });
                        }
                    }
                    return JSON.stringify({found: false});
                })()
                """)
                info2 = json.loads(dts_info2) if isinstance(dts_info2, str) else {"found": False}
                if info2.get("found") and info2.get("inView"):
                    self._cdp_mouse_click(info2["x"], info2["y"])
                    logger.info("[DTS] 滚动后CDP点击 @ (%d, %d)", info2.get("x", 0), info2.get("y", 0))
                    time.sleep(1)
                    ox, oy = self._get_viewport_offset()
                    self._os_click(info2["x"] + ox, info2["y"] + oy)
                    logger.info("[DTS] xdotool点击 @ screen(%d,%d)", info2["x"] + ox, info2["y"] + oy)
                    time.sleep(3)
                    self._check_new_tabs_after_click()
                    return True
                logger.warning("[DTS] 滚动后仍不可见: %s", dts_info2[:200] if dts_info2 else "")
                return False

            logger.warning("[DTS] 未找到市场分析入口: %s", info)
            return False

        except Exception as e:
            logger.warning("[DTS] 点击市场分析异常: %s", e)
            return False

    def _click_select_all(self) -> bool:
        """点击全选按钮"""
        try:
            result = self._cdp_eval("""
            (function() {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var txt = (all[i].textContent || '').trim();
                    if (txt === '全选' && all[i].offsetHeight > 0) {
                        all[i].click();
                        return 'clicked';
                    }
                }
                return 'not_found';
            })()
            """)
            if result == 'clicked':
                logger.info("[DTS] 全选成功")
                return True
            logger.info("[DTS] 未找到全选按钮: %s", result)
            return False
        except Exception as e:
            logger.warning("[DTS] 全选异常: %s", e)
            return False

    def _clear_dts_cache(self) -> bool:
        """清理店透视缓存"""
        try:
            result = self._cdp_eval("""
            (function() {
                var btns = document.querySelectorAll('[class*="cache"], [class*="clear"]');
                for (var i = 0; i < btns.length; i++) {
                    var txt = (btns[i].textContent || '').trim();
                    if (txt.indexOf('清理缓存') !== -1 || txt.indexOf('清除缓存') !== -1) {
                        btns[i].click();
                        return 'clicked';
                    }
                }
                return 'not_found';
            })()
            """)
            if result == 'clicked':
                logger.info("[DTS] 清理缓存成功")
                time.sleep(3)
                return True
            return False
        except Exception:
            return False

    def _wait_auto_load(self) -> bool:
        """等待DTS面板加载 + 分批自动加载全部数据

        流程: 面板就绪 → 每批点击8次自动加载(每次等30s) → 暂停5分钟
              → 检测按钮是否消失 → 如是则全部加载完成 → 否则继续下一批
        """
        logger.info("[DTS] 等待DTS市场分析面板加载...")
        panel_loaded = False
        for i in range(30):
            time.sleep(2)
            status = self._cdp_eval("""
            (function() {
                var body = document.body ? (document.body.innerText || '') : '';
                return JSON.stringify({
                    len: body.length,
                    hasStart: body.indexOf('开始分析') !== -1,
                    hasSort: body.indexOf('综合排序') !== -1,
                    hasExport: body.indexOf('导出表格') !== -1
                });
            })()
            """)
            try:
                info = json.loads(status) if isinstance(status, str) else {}
            except json.JSONDecodeError:
                info = {}

            if info.get("hasStart") or info.get("hasSort"):
                logger.info("[DTS] 面板已加载! len=%d (第%d轮)", info.get("len", 0), i + 1)
                panel_loaded = True
                break
            if i % 5 == 0:
                logger.info("[DTS] 面板等待 %d/30 len=%d", i + 1, info.get("len", 0))

        if not panel_loaded:
            logger.warning("[DTS] DTS面板未加载")
            return False

        time.sleep(5)

        total_clicks = 0
        for batch in range(1, MAX_AUTO_LOAD_BATCHES + 1):
            logger.info("[DTS] === 第 %d/%d 批 (每批%d次点击) ===",
                       batch, MAX_AUTO_LOAD_BATCHES, AUTO_LOAD_BATCH_SIZE)

            for click_idx in range(1, AUTO_LOAD_BATCH_SIZE + 1):
                total_clicks += 1
                logger.info("[DTS] 自动加载 第%d次点击 (总第%d次)", click_idx, total_clicks)

                # 点击自动加载按钮（页面最下方左侧）
                result = self._cdp_eval("""
                (function() {
                    var all = document.querySelectorAll('button, [role="button"], div, span');
                    for (var i = 0; i < all.length; i++) {
                        var txt = (all[i].textContent || '').trim();
                        if ((txt.indexOf('自动加载') !== -1 || txt.indexOf('加载下一页') !== -1 || txt.indexOf('加载更多') !== -1 || txt.indexOf('上一页') !== -1) &&
                            all[i].offsetHeight > 0 && (!all[i].disabled) &&
                            (all[i].tagName === 'BUTTON' || all[i].getAttribute('role') === 'button')) {
                            all[i].scrollIntoView({behavior: 'instant', block: 'center'});
                            all[i].click();
                            return 'clicked:' + txt;
                        }
                    }
                    // 宽松匹配：任何包含这些关键词的元素
                    for (var j = 0; j < all.length; j++) {
                        var txt = (all[j].textContent || '').trim();
                        if ((txt.indexOf('自动加载') !== -1 || txt.indexOf('加载下一页') !== -1 || txt.indexOf('加载更多') !== -1) &&
                            all[j].offsetHeight > 0) {
                            all[j].click();
                            return 'clicked_loose:' + txt;
                        }
                    }
                    return 'not_found';
                })()
                """)
                logger.info("[DTS] 点击结果: %s", result)

                if result == 'not_found':
                    logger.info("[DTS] ✅ 自动加载按钮消失，全部数据加载完成！(总点击%d次)", total_clicks)
                    return True

                # 等待30秒让数据加载
                time.sleep(AUTO_LOAD_INTERVAL)

                # 每点击一次就检查面板中数据行数是否增长
                if click_idx % 4 == 0:
                    count_check = self._cdp_eval("""
                    (function() {
                        var rows = document.querySelectorAll('table tr, [class*="row"], [class*="Row"]');
                        return rows.length;
                    })()
                    """)
                    logger.info("[DTS] 当前数据行数: %s", count_check)

            # 每批8次点击后检查按钮是否还在
            check_after_batch = self._cdp_eval("""
            (function() {
                var all = document.querySelectorAll('button, [role="button"], div, span');
                for (var i = 0; i < all.length; i++) {
                    var txt = (all[i].textContent || '').trim();
                    if ((txt.indexOf('自动加载') !== -1 || txt.indexOf('加载下一页') !== -1) &&
                        all[i].offsetHeight > 0) {
                        return 'still_there';
                    }
                }
                return 'gone';
            })()
            """)

            if check_after_batch == 'gone':
                logger.info("[DTS] ✅ 第%d批后自动加载按钮消失，全部数据加载完成！(总点击%d次)", batch, total_clicks)
                return True

            if batch < MAX_AUTO_LOAD_BATCHES:
                logger.info("[DTS] ⏸ 第%d批完成，暂停%d分钟... (总点击%d次, 按钮仍在)",
                           batch, AUTO_LOAD_PAUSE // 60, total_clicks)
                time.sleep(AUTO_LOAD_PAUSE)
                logger.info("[DTS] ▶ 继续下一批...")

        logger.info("[DTS] 全部%d批完成 (总点击%d次)", MAX_AUTO_LOAD_BATCHES, total_clicks)
        return True

    def _click_export(self) -> bool:
        """点击导出表格 -> xlsx+图片链接"""
        try:
            trigger_clicked = self._cdp_eval("""
            (function() {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var txt = (all[i].textContent || '').trim();
                    if (txt.length < 30 && (txt.indexOf('导出表格') !== -1 || txt === '导出')) {
                        if (all[i].offsetHeight > 0) {
                            all[i].click();
                            return JSON.stringify({clicked:'export_trigger', tag:all[i].tagName, txt:txt});
                        }
                    }
                }
                var btns = document.querySelectorAll('button, [role="button"], [class*="export"], [class*="btn-export"]');
                for (var j = 0; j < btns.length; j++) {
                    var t = (btns[j].textContent || '').trim();
                    if (t.indexOf('导出') !== -1 && btns[j].offsetHeight > 0) {
                        btns[j].click();
                        return JSON.stringify({clicked:'export_btn', tag:btns[j].tagName, txt:t});
                    }
                }
                return JSON.stringify({clicked:'none'});
            })()
            """)
            logger.info("[DTS] 导出触发结果: %s", trigger_clicked[:100] if trigger_clicked else "null")
            time.sleep(3)

            result = self._cdp_eval("""
            (function() {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var txt = (all[i].textContent || '').trim().toLowerCase();
                    var cls = (all[i].className || '').toString().toLowerCase();
                    if ((txt.indexOf('xlsx') !== -1 && txt.indexOf('图片') !== -1) ||
                        txt === 'xlsx' || txt === 'csv' || txt === 'excel' ||
                        txt.indexOf('.xlsx') !== -1 || txt.indexOf('excel格式') !== -1 ||
                        txt.indexOf('下载表格') !== -1 || (txt.indexOf('xlsx') !== -1 && all[i].offsetHeight > 0 && all[i].offsetHeight < 60)) {
                        if (all[i].offsetHeight > 0 && all[i].offsetHeight < 80) {
                            all[i].click();
                            return JSON.stringify({clicked:'xlsx_option', tag:all[i].tagName, txt:(all[i].textContent||'').trim().slice(0,40)});
                        }
                    }
                }

                for (var j = 0; j < all.length; j++) {
                    var t = (all[j].textContent || '').trim();
                    if (t.length < 60 && t.indexOf('xlsx') !== -1 && all[j].offsetHeight > 0) {
                        all[j].click();
                        return JSON.stringify({clicked:'xlsx_text_match', tag:all[j].tagName, txt:t.slice(0,40)});
                    }
                    if ((t === '全部' || t.indexOf('全部导出') !== -1) && t.length < 20 && all[j].offsetHeight > 0) {
                        all[j].click();
                        return JSON.stringify({clicked:'all_option', tag:all[j].tagName, txt:t.slice(0,40)});
                    }
                }

                var menus = document.querySelectorAll('[class*=\"dropdown\"], [class*=\"popover\"], [class*=\"menu\"], [class*=\"popper\"], [class*=\"tooltip\"]');
                for (var k = 0; k < menus.length; k++) {
                    var mt = (menus[k].textContent || '').trim().toLowerCase();
                    if (mt.indexOf('xlsx') !== -1 || mt.indexOf('excel') !== -1) {
                        var children = menus[k].querySelectorAll('*');
                        for (var l = 0; l < children.length; l++) {
                            var ct = (children[l].textContent || '').trim().toLowerCase();
                            if ((ct.indexOf('xlsx') !== -1 && ct.length < 30) || ct === 'excel') {
                                if (children[l].offsetHeight > 0) {
                                    children[l].click();
                                    return JSON.stringify({clicked:'menu_xlsx', parent:menus[k].tagName, child:children[l].tagName, txt:ct.slice(0,40)});
                                }
                            }
                        }
                    }
                }

                return JSON.stringify({clicked:'none', totalElements:all.length});
            })()
            """)

            logger.info("[DTS] xlsx选项结果: %s", result[:200] if result else "null")

            if 'clicked' in str(result) and 'none' not in str(result):
                logger.info("[DTS] 点击导出xlsx成功")
                return True

            logger.warning("[DTS] 未找到xlsx导出选项")
            return False

        except Exception as e:
            logger.warning("[DTS] 导出操作异常: %s", e)
            return False

    def _monitor_download(self, timeout: int = 120) -> Optional[str]:
        """监控下载目录等待xlsx文件出现"""
        start = time.time()
        before_files = set(DOWNLOAD_DIR.glob("*.xlsx"))

        while time.time() - start < timeout:
            try:
                current = set(DOWNLOAD_DIR.glob("*.xlsx"))
                new_files = current - before_files
                if not new_files:
                    new_files = {f for f in DOWNLOAD_DIR.glob("*市场数据分析*.xlsx")
                                 if time.time() - f.stat().st_mtime < timeout}
                if new_files:
                    newest = max(new_files, key=lambda f: f.stat().st_mtime)
                    if newest.stat().st_size > 100:
                        logger.info("[下载] 检测到文件: %s (%d bytes)", newest.name, newest.stat().st_size)
                        return str(newest)
            except Exception:
                pass
            time.sleep(3)

        logger.warning("[下载] 超时未检测到文件 (%ds)", timeout)
        return None

    # ═══════════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════════

    def crawl_keyword(self, keyword: str) -> Optional[str]:
        """执行淘宝关键词抓取完整流程

        Args:
            keyword: 搜索关键词

        Returns:
            成功时返回导出的xlsx文件路径，失败返回None
        """
        if not keyword or not keyword.strip():
            logger.error("关键词不能为空")
            return None

        keyword = keyword.strip()
        start_time = time.time()

        logger.info("=" * 60)
        logger.info("[RPA] 开始抓取关键词: %s", keyword)
        logger.info("=" * 60)

        # 信号处理仅在主线程有效（uvicorn worker线程中会报ValueError跳过）
        _cleanup = None
        try:
            original_sigterm = signal.getsignal(signal.SIGTERM)
            original_sigint = signal.getsignal(signal.SIGINT)

            def _cleanup(signum=None, frame=None):
                logger.info("[RPA] 清理资源...")
                self._disconnect()
                if signum:
                    sys.exit(1)

            signal.signal(signal.SIGTERM, _cleanup)
            signal.signal(signal.SIGINT, _cleanup)
            logger.info("[RPA] 信号处理已注册")
        except ValueError:
            logger.info("[RPA] 非主线程，跳过信号注册（uvicorn worker）")

        try:
            # ── 仅连接已有Chrome，不启动新实例（避免profile冲突损坏）──
            chrome_ready = False
            for detect_try in range(5):
                try:
                    urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=3)
                    chrome_ready = True
                    logger.info("[Chrome] 端口%d已有Chrome在运行，直接连接", CDP_PORT)
                    break
                except Exception as e:
                    if detect_try == 0:
                        logger.info("[Chrome] 等待端口%d就绪...", CDP_PORT)
                    logger.warning("[Chrome] 检测%d次失败: %s", detect_try + 1, e)
                    time.sleep(2)

            if not chrome_ready:
                raise CrawlError(
                    "Chrome未运行(端口%d无响应)，请确认supervisor Chrome服务已启动" % CDP_PORT
                )

            ws = self._cdp_connect(url_hint="")
            if not ws:
                raise CrawlError("CDP连接失败，请确保Chrome已在端口%d上运行" % CDP_PORT)

            self._maximize_window()
            self._os_activate_chrome()

            # ── 登录态检测：不触发CDP导航，在现有页面上检测 ──
            logger.info("[1/10] 检测淘宝登录态...")
            login_check = self._cdp_eval("""
            (function() {
                var url = window.location.href || '';
                if (url.indexOf('taobao.com') === -1 && url.indexOf('tmall.com') === -1)
                    return 'not_on_taobao';

                // 方法1: 找用户名元素（多个备选选择器）
                var selectors = [
                    '.site-nav-user .site-nav-login-info-nick',
                    '.J_SiteNavLogin .site-nav-menu-hd .menu-hd-text',
                    '.site-nav-bd .nickname',
                    '.tb-header-username',
                    '.mytaobao-username'
                ];
                var nickname = '';
                for (var i = 0; i < selectors.length; i++) {
                    var el = document.querySelector(selectors[i]);
                    if (el) {
                        var t = (el.textContent || '').trim().replace(/^hi[\\s,]*/i, '');
                        if (t && t !== '\u767b\u5f55' && t !== '\u8bf7\u767b\u5f55' && t.length < 30) {
                            nickname = t;
                            break;
                        }
                    }
                }
                if (nickname) return 'logged_in:' + nickname;

                // 方法2: body文本关键词
                var bodyText = (document.body ? document.body.innerText : '') || '';
                if (bodyText.indexOf('\u8bf7\u767b\u5f55') !== -1) return 'not_logged_in';
                if (bodyText.indexOf('\u6211\u7684\u6dd8\u5b9d') !== -1) return 'logged_in:by_keyword';
                if (bodyText.indexOf('\u5df2\u4e70\u5230\u7684\u5b9d\u8d1d') !== -1) return 'logged_in:by_keyword';

                return 'unknown';
            })()
            """)

            if login_check == 'not_on_taobao' or login_check.startswith('not_'):
                # 不在淘宝页面，需要用真人方式导航
                logger.info("[1/10] 不在淘宝页面，使用地址栏真人方式导航...")
                self._os_activate_chrome()
                time.sleep(0.5)
                # Ctrl+L 聚焦地址栏
                subprocess.run(["xdotool", "key", "ctrl+l"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(0.3)
                subprocess.run(["xdotool", "key", "ctrl+a"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(0.1)
                # xdotool type requires older xdotool, use key for common chars
                self._os_type("https://www.taobao.com")
                time.sleep(0.3)
                subprocess.run(["xdotool", "key", "Return"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(6)
                for _ in range(3):
                    self._dismiss_chrome_dialog()
                    time.sleep(1)

            if not login_check.startswith('logged_in'):
                # 导航后重新检测（使用与上面相同的多种选择器）
                time.sleep(3)
                login_check2 = self._cdp_eval("""
                (function() {
                    var selectors = [
                        '.site-nav-user .site-nav-login-info-nick',
                        '.J_SiteNavLogin .site-nav-menu-hd .menu-hd-text',
                        '.site-nav-bd .nickname',
                        '.tb-header-username',
                        '.mytaobao-username'
                    ];
                    var nickname = '';
                    for (var i = 0; i < selectors.length; i++) {
                        var el = document.querySelector(selectors[i]);
                        if (el) {
                            var t = (el.textContent || '').trim().replace(/^hi[\\s,]*/i, '');
                            if (t && t !== '\u767b\u5f55' && t !== '\u8bf7\u767b\u5f55' && t.length < 30) {
                                nickname = t; break;
                            }
                        }
                    }
                    if (nickname) return 'logged_in:' + nickname;
                    var bodyText = (document.body ? document.body.innerText : '') || '';
                    if (bodyText.indexOf('\u6211\u7684\u6dd8\u5b9d') !== -1) return 'logged_in:by_keyword';
                    if (bodyText.indexOf('\u5df2\u4e70\u5230\u7684\u5b9d\u8d1d') !== -1) return 'logged_in:by_keyword';
                    return 'not_logged_in';
                })()
                """)
                if not login_check2.startswith('logged_in'):
                    logger.error("[登录] 淘宝未登录！请在后台管理「系统设置 → 淘宝登录」中扫码登录")
                    raise CrawlError("淘宝未登录，请扫码后再试")

                login_check = login_check2

            logger.info("[登录] 登录态确认: %s", login_check)

            # ── 检查当前页面是否有残留滑块验证（非本次操作产生的）──
            # 如果是旧页面残留的持久弹窗，slider位置不变，无法真正通过
            # 解决方案: 导航到淘宝首页用真人方式重置状态
            captcha_before_search = self._detect_captcha()
            if captcha_before_search:
                logger.warning("[验证] 当前页面有残留滑块验证，导航到淘宝首页重置...")
                self._os_activate_chrome()
                time.sleep(0.5)
                subprocess.run(["xdotool", "key", "ctrl+l"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(0.3)
                subprocess.run(["xdotool", "key", "ctrl+a"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(0.1)
                self._os_type("https://www.taobao.com")
                time.sleep(0.3)
                subprocess.run(["xdotool", "key", "Return"],
                    env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
                time.sleep(6)
                for _ in range(3):
                    self._dismiss_chrome_dialog()
                    time.sleep(1)

                # 导航后等待页面完全加载
                time.sleep(3)
                if self._detect_captcha():
                    logger.warning("[验证] 淘宝首页仍有滑块(罕见)，尝试求解一次...")
                    if not self._handle_captcha():
                        logger.info("[验证] 跳过残留滑块，直接继续流程")
                logger.info("[验证] 页面已重置到淘宝首页")

            if self._detect_banned():
                raise AccountBannedError("账号被封禁")

            logger.info("[2/10] 确保店透视扩展已登录")
            self._ensure_dts_login()

            logger.info("[3/10] 搜索关键词: %s", keyword)
            self._dismiss_chrome_dialog()

            self._os_activate_chrome()
            time.sleep(1)

            # 直接用xdotool真人方式打开新标签页并导航到搜索结果URL
            # 绕过淘宝搜索框的表单提交（form.submit触发反爬）
            search_url = f"https://s.taobao.com/search?q={urllib.parse.quote(keyword)}"
            logger.info("[3/10] 打开新标签页导航搜索: %s", search_url[:80])

            # Ctrl+T 新标签页
            subprocess.run(["xdotool", "key", "ctrl+t"],
                env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
            time.sleep(1.5)

            # Ctrl+L 聚焦地址栏 → 全选 → 输入URL → 回车
            subprocess.run(["xdotool", "key", "ctrl+l"],
                env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
            time.sleep(0.3)
            subprocess.run(["xdotool", "key", "ctrl+a"],
                env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
            time.sleep(0.1)
            self._os_type(search_url)
            time.sleep(0.3)
            subprocess.run(["xdotool", "key", "Return"],
                env={"DISPLAY": DISPLAY, "XAUTHORITY": XAUTH_FILE}, timeout=5)
            time.sleep(8)
            for _ in range(3):
                self._dismiss_chrome_dialog()
                time.sleep(1)

            self._switch_to_new_tab("s.taobao.com")

            if self._detect_captcha():
                logger.info("[3.5/10] 搜索触发滑块验证，开始处理...")
                if not self._handle_captcha():
                    raise SliderVerifyError("搜索后滑块验证失败")
                time.sleep(3)

            if self._detect_banned():
                raise AccountBannedError("搜索后检测到封禁")

            current_url = self._cdp_eval("window.location.href")
            logger.info("[4/10] 当前页面: %s", current_url[:100] if current_url else "unknown")

            if "s.taobao.com" not in (current_url or ""):
                logger.warning("[4/10] 未在搜索结果页，尝试再次切换标签页")
                time.sleep(3)
                self._switch_to_new_tab("s.taobao.com")
                current_url = self._cdp_eval("window.location.href")
                logger.info("[4/10] 重新切换后: %s", current_url[:100] if current_url else "unknown")

            if self._detect_captcha():
                logger.info("[4/10] 搜索结果页检测到滑块验证...")
                if not self._handle_captcha():
                    raise SliderVerifyError("搜索结果页滑块验证失败")
                time.sleep(3)

            logger.info("[5/10] 等待搜索结果加载")
            time.sleep(5)
            self._dismiss_chrome_dialog()
            self._check_captcha_barrier("搜索结果加载")

            for _ in range(3):
                self._cdp_eval("window.scrollBy(0, 500)")
                time.sleep(1)
                self._dismiss_chrome_dialog()

            logger.info("[6/10] 触发店透视扩展")
            self._dismiss_chrome_dialog()
            self._trigger_dts_extension()
            time.sleep(5)
            self._dismiss_chrome_dialog()
            self._check_captcha_barrier("触发店透视")

            logger.info("[7/10] 点击市场分析")
            self._dismiss_chrome_dialog()
            clicked = self._click_market_analysis()
            if not clicked:
                logger.warning("[7/10] 市场分析点击失败，尝试清理缓存重试")
                self._clear_dts_cache()
                time.sleep(3)
                self._dismiss_chrome_dialog()
                self._click_market_analysis()

            time.sleep(10)
            self._check_captcha_barrier("点击市场分析")

            logger.info("[8/10] 等待数据自动加载")
            self._wait_auto_load()

            if self._detect_captcha():
                if not self._handle_captcha():
                    raise SliderVerifyError("数据加载后滑块验证失败")

            logger.info("[8.5/10] 点击全选")
            self._click_select_all()
            time.sleep(2)

            logger.info("[9/10] 导出数据")
            export_clicked = self._click_export()
            if not export_clicked:
                logger.warning("[9/10] 导出按钮点击失败")

            logger.info("[10/10] 等待下载完成")
            download_file = self._monitor_download(timeout=180)

            if download_file:
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                import shutil
                dest = OUTPUT_DIR / Path(download_file).name
                shutil.copy2(download_file, dest)
                logger.info("[RPA] 文件已复制到: %s", dest)
                download_file = str(dest)

            elapsed = time.time() - start_time
            logger.info("=" * 60)
            logger.info("[RPA] 抓取完成 (耗时 %.1f 秒)", elapsed)
            logger.info("[RPA] 结果: %s", download_file or "无文件")
            logger.info("=" * 60)

            return download_file

        except AccountBannedError:
            logger.error("[RPA] 账号被封禁，立即停止")
            return None
        except SliderVerifyError as e:
            logger.error("[RPA] 滑块验证失败: %s", e)
            return None
        except CrawlError as e:
            logger.error("[RPA] 抓取错误: %s", e)
            return None
        except Exception:
            logger.exception("[RPA] 未预期的异常")
            return None
        finally:
            self._disconnect()
            if _cleanup is not None:
                try:
                    signal.signal(signal.SIGTERM, original_sigterm)
                    signal.signal(signal.SIGINT, original_sigint)
                except ValueError:
                    pass

    def _disconnect(self) -> None:
        """断开CDP连接（不关闭Chrome，保留页面状态便于调试）"""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None


def crawl_keyword_rpa(keyword: str) -> Optional[str]:
    """便捷函数：执行淘宝关键词抓取

    Args:
        keyword: 搜索关键词

    Returns:
        成功时返回导出的xlsx文件路径，失败返回None
    """
    crawler = TaguiCrawler()
    return crawler.crawl_keyword(keyword)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if len(sys.argv) < 2:
        print("用法: python tagui_crawler.py <关键词>")
        print("示例: python tagui_crawler.py 纸巾")
        sys.exit(1)

    kw = sys.argv[1]
    result = crawl_keyword_rpa(kw)
    if result:
        print(f"SUCCESS: {result}")
    else:
        print("FAILED")
        sys.exit(1)
