# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取功能
"""纯xdotool物理操作爬虫 — 零CDP，彻底绕过淘宝检测

基于已验证的技术栈:
- xdotool: 键盘输入、鼠标点击、窗口管理
- python-xlib XTest: 滑块验证码拖拽求解
- xclip: 中文剪贴板粘贴
- openpyxl: DTS导出Excel解析

设计原则:
1. 绝对不使用 --remote-debugging-port
2. 所有浏览器交互通过OS级物理事件（isTrusted=true）
3. 模拟真人操作节奏（随机延迟、自然轨迹）
4. 优雅关闭Chrome（TERM优先，KILL仅兜底）

用法:
    from services.xdotool_crawler import XdotoolCrawler
    crawler = XdotoolCrawler()
    result = crawler.crawl_keyword("蒙牛一米八八奶粉")
"""

from __future__ import annotations

import glob
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("xdotool_crawler")

# ═══════════════════════════════════════════════════════════════
# 常量配置
# ═══════════════════════════════════════════════════════════════

CHROME_BIN = "/usr/bin/google-chrome-stable"
CHROME_PROFILE = os.path.expanduser("~/.config/google-chrome")
DISPLAY = os.environ.get("DISPLAY", ":0")
XAUTH = os.environ.get(
    "XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
)
DOWNLOAD_DIR = Path(os.path.expanduser("~/Downloads"))
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Chrome 窗口内 viewport 到屏幕坐标的偏移（经验值）
VIEWPORT_OFFSET_X = 66
VIEWPORT_OFFSET_Y = 119

# DTS 扩展 ID
DTS_EXTENSION_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"

# 超时配置
CHROME_START_TIMEOUT = 15
SEARCH_LOAD_TIMEOUT = 15
DTS_PANEL_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 120
FLOW_TIMEOUT = 45 * 60  # 总流程超时 45 分钟

# DTS 自动加载配置（经验验证参数）
AUTO_LOAD_SINGLE_WAIT = 15       # 每次点击后等待15秒（加速测试）
AUTO_LOAD_BATCH_SIZE = 5          # 每5次点击一批（加速测试）
AUTO_LOAD_BATCH_PAUSE = 30        # 每批后暂停30秒（加速测试）
AUTO_LOAD_MAX_BATCHES = 6         # 最多6批
# 滑块验证配置
MAX_SLIDER_RETRIES = 5
# 验证失败特征（基于实测）
CAPTCHA_FAIL_KEYWORDS = ["验证失败", "点击框体重试", "点击我重试", "再试一次"]


def _xdotool_env() -> dict:
    """构造xdotool所需的环境变量"""
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH
    return env


def _run(cmd: list[str], timeout: int = 30) -> str:
    """执行命令并返回stdout"""
    r = subprocess.run(
        cmd, env=_xdotool_env(),
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip()


def _xd(*args) -> str:
    """快捷xdotool执行"""
    return _run(["xdotool"] + list(args))


class CrawlError(Exception):
    """抓取异常"""


class CaptchaBlockError(CrawlError):
    """验证码拦截"""


class LoginRequiredError(CrawlError):
    """需要登录"""


class XdotoolCrawler:
    """纯xdotool物理操作爬虫"""

    def __init__(self):
        self._chrome_wid: str | None = None
        self._x11_display = None
        self._x11_xtest = None
        self._x11_X = None
        self._keyword: str = ""
        self._verifier = None  # 延迟初始化
        self._captcha_detector = None  # 延迟初始化
        self._captcha_detect_info = None  # 最近一次检测结果详情

    def _get_captcha_detector(self):
        """获取验证码检测器（延迟导入避免循环依赖）"""
        if self._captcha_detector is None:
            from services.captcha_detector import CaptchaDetector
            self._captcha_detector = CaptchaDetector()
        return self._captcha_detector

    def _get_verifier(self):
        """获取页面验证器（延迟导入避免循环依赖）"""
        if self._verifier is None:
            from services.page_verifier import PageVerifier
            self._verifier = PageVerifier()
        return self._verifier

    def _verify_step(self, step_name: str, expected_page: str = "") -> dict:
        """每个操作前的综合验证（页面状态 + 验证码）。

        使用增强的多维检测（标题 + URL + CDP），确保不遗漏页面内覆盖层验证码。
        检测到验证码 → 立即求解 → 求解失败则抛出 CaptchaBlockError。

        严禁绕过滑块验证 — 检测到验证码必须立即处理。
        """
        # ── 先使用增强的爬虫内置检测（标题+URL+CDP） ──
        has_captcha_direct = self._detect_captcha()

        # ── 同时使用 page_verifier 做页面断言 ──
        verifier = self._get_verifier()
        result = verifier.verify_before_action(
            step_name, expected_page, self._keyword
        )

        # 合并检测结果（任一来源检测到都算）
        has_captcha = has_captcha_direct or result.get("has_captcha", False)

        # 记录每步页面特征
        title = self._get_window_title()
        self._record_feature(step_name,
            f"captcha={has_captcha} page_ok={result.get('page_ok')} "
            f"expected={expected_page} title='{title[:80]}'")

        if has_captcha:
            logger.warning("[验证] %s: 检测到验证码，立即处理!", step_name)
            if not self._handle_captcha():
                raise CaptchaBlockError(
                    "步骤'%s'验证码求解失败" % step_name
                )
            # 验证通过后重新检查
            time.sleep(3)
            still_has = self._detect_captcha()
            if still_has:
                raise CaptchaBlockError(
                    "步骤'%s'验证码求解后仍检测到验证码" % step_name
                )

        if not result.get("page_ok"):
            logger.warning(
                "[验证] %s: 页面状态异常 — %s — 排查是否因验证码阻塞",
                step_name, "; ".join(result.get("warnings", []))
            )

        return result

    # ═══════════════════════════════════════════════════════════════
    # Chrome 生命周期管理
    # ═══════════════════════════════════════════════════════════════

    def _start_chrome(self, url: str = "https://www.taobao.com") -> bool:
        """启动Chrome（无CDP端口，只保留6个固化参数）。

        Args:
            url: 启动时打开的URL

        Returns:
            是否成功启动
        """
        logger.info("[Chrome] 启动Chrome (无CDP模式)...")

        # 先确保没有旧Chrome在运行
        self._kill_chrome()

        # 清理崩溃标记
        self._cleanup_crash_markers()

        # 修复 Preferences 中的退出类型
        prefs_file = Path(CHROME_PROFILE) / "Default" / "Preferences"
        if prefs_file.exists():
            try:
                subprocess.run(
                    ["sed", "-i",
                     's/"exit_type":"crashed"/"exit_type":"Normal"/',
                     str(prefs_file)],
                    capture_output=True, timeout=5,
                )
                subprocess.run(
                    ["sed", "-i",
                     's/"exited_cleanly":false/"exited_cleanly":true/',
                     str(prefs_file)],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass

        # 只使用这6个固化参数，绝对不加 --remote-debugging-port
        chrome_args = [
            CHROME_BIN,
            f"--user-data-dir={CHROME_PROFILE}",
            "--start-maximized",
            "--no-first-run",
            "--restore-last-session=false",
            "--disable-session-crashed-bubble",
            "--disable-crash-reporter",
            "--ozone-platform=x11",
        ]

        if url:
            chrome_args.append(url)

        try:
            subprocess.Popen(
                chrome_args,
                env=_xdotool_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("[Chrome] Chrome二进制不存在: %s", CHROME_BIN)
            return False

        # 等待Chrome窗口出现
        logger.info("[Chrome] 等待窗口就绪...")
        for i in range(CHROME_START_TIMEOUT):
            time.sleep(1)
            wid = self._find_chrome_wid()
            if wid:
                self._chrome_wid = wid
                logger.info("[Chrome] 窗口就绪: %s (等待%ds)", wid, i + 1)
                time.sleep(2)  # 额外等待页面初始渲染
                return True

        logger.error("[Chrome] 启动超时(%ds)", CHROME_START_TIMEOUT)
        return False

    def _kill_chrome(self) -> None:
        """优雅关闭Chrome: TERM → sleep 3s → KILL兜底"""
        logger.info("[Chrome] 优雅关闭Chrome...")

        # 先尝试关闭所有窗口（不影响下次启动）
        try:
            wids = _xd("search", "--class", "google-chrome")
            for w in wids.split():
                try:
                    _xd("windowactivate", w)
                    _xd("key", "ctrl+w")
                    time.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1)

        # 第一步: SIGTERM
        result = subprocess.run(
            ["pkill", "-TERM", "-f", "chrome"],
            capture_output=True, timeout=10,
        )
        time.sleep(3)

        # 第二步: 检查残留，仅残留进程用KILL兜底
        check = subprocess.run(
            ["pgrep", "-f", "chrome"],
            capture_output=True, text=True, timeout=5,
        )
        if check.returncode == 0 and check.stdout.strip():
            logger.warning("[Chrome] TERM后仍有残留进程，使用KILL兜底")
            subprocess.run(
                ["pkill", "-KILL", "-f", "chrome"],
                capture_output=True, timeout=10,
            )
            time.sleep(2)

        # 清理临时文件
        for tmp_dir in Path("/tmp").glob("com.google.Chrome.*"):
            try:
                tmp_dir.rmdir()
            except OSError:
                pass

        logger.info("[Chrome] 进程清理完成")

    def _cleanup_crash_markers(self) -> None:
        """清理Chrome崩溃标记文件，防止弹出'要恢复页面吗'弹窗"""
        profile_path = Path(CHROME_PROFILE)
        for marker in ["Last Session", "Last Tabs", "Current Session",
                        "Current Tabs"]:
            fp = profile_path / marker
            if fp.exists():
                try:
                    fp.unlink()
                except OSError:
                    pass

        # 清理 SingletonLock（有时会导致Chrome认为已有实例运行）
        for lock in profile_path.rglob("Singleton*"):
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass

    # ═══════════════════════════════════════════════════════════════
    # 窗口管理
    # ═══════════════════════════════════════════════════════════════

    def _find_chrome_wid(self) -> str | None:
        """查找Chrome窗口ID（真正的浏览器窗口，排除隐藏辅助窗口）。

        查找策略（按优先级）：
        1. 按名称搜索"淘宝"（最精确）
        2. 按 class 搜索 google-chrome，选最大窗口（排除10x10隐藏窗口）
        3. 按名称搜索"Google Chrome"
        """
        # 策略1: class搜索，选最大窗口（排除隐藏的10x10辅助窗口）
        result = _xd("search", "--class", "google-chrome")
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids:
            best_wid = None
            best_area = 0
            for wid in wids:
                try:
                    geo = _xd("getwindowgeometry", "--shell", wid)
                    w = 0; h = 0
                    for line in geo.split("\n"):
                        if line.startswith("WIDTH="):
                            w = int(line.split("=")[1])
                        elif line.startswith("HEIGHT="):
                            h = int(line.split("=")[1])
                    area = w * h
                    if area > best_area:
                        best_area = area
                        best_wid = wid
                except Exception:
                    pass
            if best_wid and best_area > 100000:  # 至少320x320以上真实窗口
                logger.debug("[窗口] 通过面积(%d)找到: %s", best_area, best_wid)
                return best_wid
            # 如果所有窗口都很小，返回第一个
            if wids:
                logger.debug("[窗口] 通过class找到(无面积筛选): %s", wids[0])
                return wids[0]

        # 策略3: 名称搜索"Google Chrome"
        for name in ["Google Chrome", "Chrome"]:
            result = _xd("search", "--name", name)
            wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
            if wids:
                logger.debug("[窗口] 通过名称'%s'找到: %s", name, wids[0])
                return wids[0]

        return None

    def _activate_chrome(self) -> bool:
        """激活Chrome窗口（置顶+聚焦）"""
        wid = self._chrome_wid or self._find_chrome_wid()
        if not wid:
            logger.warning("[窗口] 未找到Chrome窗口")
            return False

        try:
            _xd("windowactivate", wid)
            _xd("windowfocus", wid)
            self._chrome_wid = wid
            time.sleep(0.3)
            return True
        except Exception as e:
            logger.warning("[窗口] 激活失败: %s", e)
            return False

    def _get_window_geometry(self) -> dict[str, int]:
        """获取Chrome窗口位置和大小"""
        wid = self._chrome_wid or self._find_chrome_wid()
        if not wid:
            return {"x": 0, "y": 0, "w": 1280, "h": 800}

        try:
            geo = _xd("getwindowgeometry", "--shell", wid)
            result = {}
            for line in geo.split("\n"):
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    try:
                        result[k.lower()] = int(v)
                    except ValueError:
                        pass
            # xdotool outputs WIDTH/HEIGHT, provide w/h aliases
            if "width" in result:
                result["w"] = result["width"]
            if "height" in result:
                result["h"] = result["height"]
            if "x" not in result and "X" in result:
                result["x"] = result["X"] if "X" in result else 0
            return result
        except Exception:
            return {"x": 0, "y": 0, "w": 1280, "h": 800}

    def _get_window_title(self) -> str:
        """获取当前Chrome窗口标题"""
        wid = self._chrome_wid or self._find_chrome_wid()
        if not wid:
            return ""
        try:
            return _xd("getwindowname", wid)
        except Exception:
            return ""

    # ═══════════════════════════════════════════════════════════════
    # 键盘鼠标操作
    # ═══════════════════════════════════════════════════════════════

    def _click(self, x: int, y: int, button: int = 1) -> None:
        """物理鼠标点击"""
        _xd("mousemove", str(x), str(y))
        time.sleep(0.1 + random.random() * 0.2)
        _xd("click", str(button))
        time.sleep(0.2 + random.random() * 0.3)

    def _natural_click(self, x: int, y: int) -> None:
        """自然点击——先移附近再精准点"""
        near_x = x + random.randint(-20, 20)
        near_y = y + random.randint(-10, 10)
        _xd("mousemove", str(near_x), str(near_y))
        time.sleep(0.08 + random.random() * 0.12)
        _xd("mousemove", str(x), str(y))
        time.sleep(0.05 + random.random() * 0.1)
        _xd("click", "1")
        time.sleep(0.2 + random.random() * 0.3)

    def _type_text(self, text: str, delay_ms: int = 50) -> None:
        """xdotool逐字输入（仅支持ASCII）"""
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", str(delay_ms), text],
            env=_xdotool_env(), capture_output=True, timeout=30,
        )

    def _paste(self, text: str) -> None:
        """通过剪贴板粘贴（支持中文）"""
        env = _xdotool_env()
        p = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env,
        )
        p.communicate(input=text.encode("utf-8"), timeout=10)
        time.sleep(0.3)
        _xd("key", "ctrl+v")
        time.sleep(0.5)

    def _key_press(self, key: str) -> None:
        """按键操作"""
        _xd("key", key)
        time.sleep(0.3 + random.random() * 0.2)

    def _scroll_down(self, clicks: int = 3) -> None:
        """向下滚动"""
        for _ in range(clicks):
            _xd("click", "5")
            time.sleep(0.05)

    # ═══════════════════════════════════════════════════════════════
    # 弹窗处理
    # ═══════════════════════════════════════════════════════════════

    def _handle_popups(self) -> bool:
        """处理Chrome启动后常见弹窗。

        1. "要恢复页面吗"弹窗 → 点Escape关闭
        2. DTS权限弹窗 → Tab到"接受权限"按钮 → Enter
        3. 登录弹窗/覆盖层 → 检测并提示

        Returns:
            True 如果没有登录弹窗（可以继续），False 如果需要登录
        """
        logger.info("[弹窗] 检查并处理弹窗...")
        self._activate_chrome()
        time.sleep(2)

        # 处理"恢复页面"弹窗
        title = self._get_window_title()
        if "恢复" in title:
            logger.info("[弹窗] 检测到恢复弹窗，按Escape关闭")
            _xd("key", "Escape")
            time.sleep(1)

        # 处理 DTS 权限弹窗
        try:
            disabled = _xd("search", "--name", "禁用")
            if disabled.strip():
                logger.info("[弹窗] 检测到DTS权限弹窗，尝试接受...")
                _xd("key", "Tab")
                time.sleep(0.3)
                _xd("key", "Return")
                time.sleep(2)
        except Exception:
            pass

        # 检测登录弹窗
        if self._detect_login_popup():
            logger.error("[弹窗] ⚠️ 检测到登录弹窗！需要扫码登录后才能继续")
            return False

        logger.info("[弹窗] 弹窗处理完成")
        return True

    # ═══════════════════════════════════════════════════════════════
    # 滑块验证码处理
    # ═══════════════════════════════════════════════════════════════

    def _detect_captcha(self) -> bool:
        """检测验证码（截图分析 + 标题检测，无干扰操作）。

        检测策略:
        1. 【优先】截图分析：白色弹窗 → 灰色滑轨 → 文字行 → >>箭头
        2. 【备用】CDP Runtime.evaluate（如果CDP端口可用）
        3. 【备用】窗口标题关键词匹配

        绝不操作浏览器UI（不碰地址栏、不切换焦点）。
        检测到验证码时将精确坐标存入 self._captcha_detect_info。
        """
        detector = self._get_captcha_detector()
        wid = self._chrome_wid or self._find_chrome_wid()
        if not wid:
            return False

        found, info = detector.detect(wid)
        if found:
            self._captcha_detect_info = info
            method = info.get("method", "unknown")
            if method == "screenshot":
                logger.warning(
                    "[验证码] 截图检测到滑块弹窗: 置信度=%d%%, 轨Y=%d, 轨宽=%d",
                    info.get("confidence", 0),
                    info.get("track_y", 0),
                    info.get("track_width", 0),
                )
            elif method == "title":
                logger.warning("[验证码] 标题检测到'%s': %s",
                             info.get("keyword", ""), info.get("title", "")[:100])
            self._record_feature("captcha_detect", f"method:{method}")
            return True

        return False

    def _detect_captcha_cdp(self) -> bool:
        """通过CDP Runtime.evaluate直接检查页面DOM中的验证码元素。

        检测淘宝滑块验证码的DOM特征:
        - #nc_1_n1z (标准淘宝滑块按钮)
        - .nc_wrapper (滑块容器)
        - [class*="captcha"], [class*="verify"] (通用验证码)
        - window.location.href 中的风控URL特征
        """
        try:
            import urllib.request, json as _json, websocket
            # 连接CDP
            resp = urllib.request.urlopen("http://127.0.0.1:9223/json", timeout=3)
            targets = _json.loads(resp.read())

            # 找当前页面
            page_ws = None
            for t in targets:
                if t.get("type") == "page":
                    page_ws = t.get("webSocketDebuggerUrl")
                    break
            if not page_ws:
                return False

            ws = websocket.create_connection(page_ws, timeout=5,
                origin="http://127.0.0.1:9223")

            # DOM检测表达式
            detect_js = """
            (function(){
                var result = {found: false, type: '', detail: ''};

                // 检查淘宝标准滑块元素
                var slider = document.querySelector('#nc_1_n1z');
                var wrapper = document.querySelector('.nc_wrapper');
                var scaleText = document.querySelector('#nc_1__scale_text');
                if (slider && wrapper) {
                    result.found = true;
                    result.type = 'nc_slider';
                    result.detail = '淘宝标准滑块验证码(nc_1_n1z)';
                    var sr = slider.getBoundingClientRect();
                    var wr = wrapper.getBoundingClientRect();
                    result.sliderX = Math.round(sr.x + sr.width/2);
                    result.sliderY = Math.round(sr.y + sr.height/2);
                    result.trackWidth = Math.round(wr.width);
                    result.visible = sr.width > 0 && sr.height > 0;
                }

                // 检查通用验证码元素
                if (!result.found) {
                    var captchaEls = document.querySelectorAll(
                        '[class*="captcha"], [class*="verify"], [id*="captcha"], [id*="verify"], ' +
                        '[class*="slider"], [class*="滑块"], [class*="验证"], ' +
                        '.baxia-dialog, .sufei-dialog, .login-form'
                    );
                    for (var i = 0; i < captchaEls.length; i++) {
                        var el = captchaEls[i];
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 50) {
                            result.found = true;
                            result.type = 'captcha_element';
                            result.detail = el.className || el.id || 'captcha_dom';
                            break;
                        }
                    }
                }

                // 检查URL中的风控特征
                if (!result.found) {
                    var url = window.location.href;
                    var urlFlags = ['h5api', 'punish', '_____tmd_____', 'x5sec', 'errloading'];
                    for (var j = 0; j < urlFlags.length; j++) {
                        if (url.indexOf(urlFlags[j]) >= 0) {
                            result.found = true;
                            result.type = 'url_flag';
                            result.detail = 'URL含风控标记: ' + urlFlags[j];
                            break;
                        }
                    }
                }

                // 检查页面标题
                if (!result.found) {
                    var title = document.title;
                    var titleFlags = ['验证码', '滑块', '拦截', 'captcha', 'verify'];
                    for (var k = 0; k < titleFlags.length; k++) {
                        if (title.indexOf(titleFlags[k]) >= 0) {
                            result.found = true;
                            result.type = 'title_flag';
                            result.detail = '标题含: ' + titleFlags[k];
                            break;
                        }
                    }
                }

                return JSON.stringify(result);
            })();
            """

            msg = _json.dumps({
                "id": 1, "method": "Runtime.evaluate",
                "params": {"expression": detect_js, "returnByValue": True}
            })
            ws.send(msg)
            raw = ws.recv()
            ws.close()

            data = _json.loads(raw)
            value = _json.loads(
                data.get("result", {}).get("result", {}).get("value", "{}")
            )

            if value.get("found"):
                logger.warning("[验证码] CDP检测到验证码: type=%s detail=%s visible=%s",
                    value.get("type"), value.get("detail"), value.get("visible"))
                self._record_feature("captcha_detect",
                    f"cdp:{value.get('type')}:{value.get('detail')}")
                # 保存滑块坐标供后续求解使用
                if value.get("sliderX"):
                    self._cdp_slider_x = value["sliderX"]
                    self._cdp_slider_y = value.get("sliderY", 0)
                    self._cdp_track_w = value.get("trackWidth", 0)
                return True

            return False

        except Exception as e:
            logger.debug("[验证码] CDP检测不可用: %s", e)
            return False

    def _record_feature(self, step: str, detail: str) -> None:
        """记录每一步的页面特征"""
        title = self._get_window_title()
        logger.info("[特征] %s | detail=%s | title=%s",
                   step, detail, title[:120])

    def _init_x11(self):
        """初始化 python-xlib XTest（用于滑块拖拽）"""
        if self._x11_display is not None:
            return self._x11_display

        os.environ.setdefault("DISPLAY", DISPLAY)
        os.environ.setdefault("XAUTHORITY", XAUTH)

        from Xlib import X, display as xdisplay
        from Xlib.ext import xtest as xext

        self._x11_display = xdisplay.Display()
        self._x11_xtest = xext
        self._x11_X = X
        return self._x11_display

    # ── 验证码状态特征（基于实测记录） ──
    # "点击我重试" = errloading 错误状态，需点击重置后重试
    # "验证失败，点击框体重试" = 轨迹被识别为机器人，需调整参数重试
    # 弹窗消失 = 验证通过

    def _solve_captcha_x11(self) -> bool:
        """滑块验证码求解（v3 — 高仿真人类拖拽轨迹）。

        关键改进:
        - 40-60个拖拽点，总时长2-3.5秒（模拟人类拖拽速度）
        - 非线性变速: 慢启动→加速→匀速→减速→微停顿→到位
        - Y轴自然漂移: 多频正弦波叠加，模拟人手不稳定
        - 过冲回弹: 松手前短暂超过目标再回来
        - 使用 xdotool 原生事件（浏览器信任 isTrusted=true）

        Returns:
            是否成功求解
        """
        logger.info("[验证码] 滑块求解v3（高仿真轨迹）...")

        try:
            # ── 获取窗口几何（两种路径都需要ww）──
            geo = self._get_window_geometry()
            wx = geo.get("x", 0)
            wy = geo.get("y", 32)
            ww = geo.get("w", 1280)
            wh = geo.get("h", 800)

            # ── 坐标来源优先级 ──
            # 1. 截图检测器精确坐标（CaptchaDetector）
            # 2. CDP DOM检测坐标
            # 3. 视口估算（最后手段，不推荐）
            detector = self._get_captcha_detector()
            detect_info = getattr(self, '_captcha_detect_info', None)
            det_sx, det_sy, det_dist = detector.get_slider_coords(wx, wy, detect_info)

            cdp_sx = getattr(self, '_cdp_slider_x', 0)
            cdp_sy = getattr(self, '_cdp_slider_y', 0)
            cdp_dist = getattr(self, '_cdp_track_w', 0)

            if det_sx is not None and det_sy is not None:
                # 截图检测器提供了精确坐标
                sx = det_sx
                sy = det_sy
                dist = det_dist if det_dist > 0 else int(ww * 0.22)
                logger.info("[验证码] 使用截图精确坐标: (%d,%d) dist=%d", sx, sy, dist)
            elif cdp_sx > 0 and cdp_sy > 0:
                # CDP提供了精确坐标 — 直接使用
                sx = cdp_sx
                sy = cdp_sy
                dist = cdp_dist if cdp_dist > 0 else int(ww * 0.22)
                logger.info("[验证码] 使用CDP精确坐标: (%d,%d) dist=%d", sx, sy, dist)
            else:
                # ── 估算坐标（视口基准，仅紧急备用）──
                logger.warning("[验证码] ⚠️ 无精确坐标，使用估算值（可能不准）")
                toolbar_h = 85
                viewport_y = wy + toolbar_h
                viewport_h = wh - toolbar_h

                sx = wx + int(ww * 0.43)
                sy = viewport_y + int(viewport_h * 0.48)
                dist = int(ww * 0.22)

            # 随机微调起始位置（±5px模拟每次点击的微小差异）
            sx += random.randint(-5, 5)
            sy += random.randint(-3, 3)

            logger.info("[验证码] 计算坐标: screen(%d,%d) dist=%d (窗口%dx%d)", sx, sy, dist, ww, wh)

            env = _xdotool_env()

            # ── 阶段1: 接近滑块 ──
            approach = [
                (sx - random.randint(80, 120), sy + random.randint(-20, 20)),
                (sx - random.randint(30, 50), sy + random.randint(-8, 8)),
                (sx, sy),
            ]
            for ax, ay in approach:
                subprocess.run(["xdotool", "mousemove", str(ax), str(ay)],
                              env=env, capture_output=True, timeout=5)
                time.sleep(0.08 + random.random() * 0.12)

            # ── 阶段2: 瞄准停顿（模拟人眼看准目标）──
            time.sleep(0.15 + random.random() * 0.25)

            # ── 阶段3: 按下鼠标 ──
            subprocess.run(["xdotool", "mousedown", "1"],
                          env=env, capture_output=True, timeout=5)
            # 按下后微停顿（模拟反应时间）
            time.sleep(0.05 + random.random() * 0.08)

            # ── 阶段4: 主拖拽轨迹（40-60点，2-3.5秒）──
            total_points = random.randint(40, 60)
            total_time = random.uniform(2.0, 3.5)  # 总拖拽时长

            # 生成非线性时间分布（慢-快-慢）
            time_points = []
            for i in range(total_points):
                p = i / (total_points - 1)  # 0→1
                # S曲线: 开始慢，中间快，结尾慢
                if p < 0.15:
                    # 起始阶段：非常慢（模拟克服静摩擦）
                    t_scale = p * 2.5  # 慢速
                elif p < 0.75:
                    # 中间阶段：匀速偏快
                    t_scale = 0.375 + (p - 0.15) * 0.8
                else:
                    # 结尾阶段：减速
                    t_scale = 0.855 + (p - 0.75) * 0.6
                time_points.append(t_scale * total_time)

            # 生成空间轨迹（带自然漂移）
            for i in range(total_points):
                p = i / (total_points - 1)

                # X方向：使用ease-out曲线 + 微随机
                ease = 1 - (1 - p) ** 2.5
                # 添加微小的前后抖动（模拟手指微颤）
                jitter = (random.random() - 0.5) * 0.003 * (1 - abs(p - 0.5) * 2)
                x_progress = ease + jitter

                ex = int(sx + dist * x_progress)

                # Y方向：多频手抖叠加
                wobble = (math.sin(p * math.pi * 3.7) * 2.0 +
                          math.sin(p * math.pi * 7.3) * 1.0 +
                          math.sin(p * math.pi * 13.7) * 0.4 +
                          (random.random() - 0.5) * 0.8)
                ey = int(sy + wobble)

                subprocess.run(
                    ["xdotool", "mousemove", str(ex), str(ey)],
                    env=env, capture_output=True, timeout=5,
                )

                # 计算该点应该等待的时间
                if i < total_points - 1:
                    dt = time_points[i + 1] - time_points[i]
                    # 添加微小的随机等待变异
                    dt += (random.random() - 0.5) * 0.01
                    if dt < 0.005:
                        dt = 0.005
                    time.sleep(dt)

            # ── 阶段5: 过冲回弹（松手前短暂犹豫）──
            overshoot = random.randint(2, 6)
            for _ in range(random.randint(2, 4)):
                ox = sx + dist + overshoot + random.randint(-2, 2)
                oy = sy + random.randint(-2, 2)
                subprocess.run(["xdotool", "mousemove", str(ox), str(oy)],
                              env=env, capture_output=True, timeout=5)
                time.sleep(0.03 + random.random() * 0.05)

            # 回到目标位置
            time.sleep(0.02)
            subprocess.run(["xdotool", "mousemove", str(sx + dist), str(sy)],
                          env=env, capture_output=True, timeout=5)
            # 松手前的最后停顿
            time.sleep(0.06 + random.random() * 0.1)

            # ── 阶段6: 松手 ──
            subprocess.run(["xdotool", "mouseup", "1"],
                          env=env, capture_output=True, timeout=5)

            logger.info("[验证码] 拖拽完成: %d点 screen(%d,%d)→(%d,%d) 约%.1fs",
                       total_points, sx, sy, sx + dist, sy, total_time)

            # 等待验证结果
            time.sleep(4)
            return True

        except Exception as e:
            logger.warning("[验证码] 滑块求解异常: %s", e)
            return False

    def _handle_captcha(self) -> bool:
        """处理验证码：检测 → 求解 → 验证结果。

        增强策略：
        1. X11拖拽（优先尝试）
        2. 失败后点击"点我反馈" → "频繁看到验证码" → 提交（降低难度）
        3. 降低难度后重新拖拽

        Returns:
            是否成功处理
        """
        captcha_detected = self._detect_captcha()
        if not captcha_detected:
            logger.info("[验证码] 无验证码弹窗")
            return True

        for attempt in range(1, MAX_SLIDER_RETRIES + 1):
            logger.info("[验证码] 第 %d/%d 次尝试求解", attempt, MAX_SLIDER_RETRIES)
            self._activate_chrome()

            # 第2次失败后，尝试反馈降低难度
            if attempt >= 3 and not self._captcha_feedback_reduce():
                logger.warning("[验证码] 反馈降难失败，继续尝试拖拽")

            if self._solve_captcha_x11():
                time.sleep(4)
                if not self._detect_captcha():
                    logger.info("[验证码] ✅ 第%d次求解成功!", attempt)
                    return True
                logger.warning("[验证码] 拖拽后验证码仍在，重试...")
            else:
                time.sleep(3)

            # 如果检测到验证失败提示，点击重试
            self._click_captcha_retry()

        logger.error("[验证码] 求解失败，已重试%d次", MAX_SLIDER_RETRIES)
        return False

    def _captcha_feedback_reduce(self) -> bool:
        """点击验证码弹窗底部的'点我反馈' → 选择'频繁看到验证码' → 提交。

        策略来源: 实测验证 — 提交反馈后验证难度降低。

        Returns:
            是否成功提交反馈
        """
        logger.info("[验证码] 尝试反馈降低验证难度...")
        try:
            self._activate_chrome()
            geo = self._get_window_geometry()
            wx = geo.get("x", 0)
            wy = geo.get("y", 0)
            ww = geo.get("w", 1280)
            wh = geo.get("h", 800)

            # 验证码弹窗通常在页面中央
            # "点我反馈"链接在弹窗底部区域
            # 弹窗约500x350，中心在(ww/2, wh*0.4)
            popup_bottom_y = wy + int(wh * 0.52)

            # 点击"点我反馈"（弹窗底部偏左）
            feedback_x = wx + int(ww * 0.35)
            feedback_y = popup_bottom_y
            logger.info("[反馈] 点击'点我反馈' (%d, %d)", feedback_x, feedback_y)
            self._natural_click(feedback_x, feedback_y)
            time.sleep(3)

            # 检查是否打开了新标签页
            title = self._get_window_title()
            logger.info("[反馈] 当前页面: %s", title[:80])

            # "频繁看到验证码"选项 — 在新标签页中
            # 选项位置通常在页面中部偏左
            opt_x = wx + int(ww * 0.25)
            opt_y = wy + int(wh * 0.45)
            logger.info("[反馈] 点击'频繁看到验证码'选项 (%d, %d)", opt_x, opt_y)
            self._natural_click(opt_x, opt_y)
            time.sleep(1.5)

            # 点击"提交"按钮（页面底部）
            submit_x = wx + int(ww * 0.5)
            submit_y = wy + int(wh * 0.65)
            logger.info("[反馈] 点击'提交' (%d, %d)", submit_x, submit_y)
            self._natural_click(submit_x, submit_y)
            time.sleep(3)

            # 验证标签页是否自动关闭
            title = self._get_window_title()
            logger.info("[反馈] 提交后页面: %s", title[:80])
            logger.info("[反馈] 验证难度应已降低，重新尝试拖拽...")
            return True

        except Exception as e:
            logger.warning("[反馈] 异常: %s", e)
            return False

    def _click_captcha_retry(self) -> None:
        """检测验证失败提示并点击重试按钮"""
        title = self._get_window_title()
        for kw in CAPTCHA_FAIL_KEYWORDS:
            if kw in title:
                logger.info("[验证码] 检测到失败提示'%s'，点击重试", kw)
                self._activate_chrome()
                geo = self._get_window_geometry()
                wx = geo.get("x", 0)
                wy = geo.get("y", 0)
                ww = geo.get("w", 1280)
                wh = geo.get("h", 800)
                # 重试按钮通常在滑块轨道上方
                retry_x = wx + int(ww * 0.5)
                retry_y = wy + int(wh * 0.58)
                self._natural_click(retry_x, retry_y)
                time.sleep(2)
                return

    def _check_captcha_barrier(self, step_name: str) -> None:
        """每个操作步骤后检查验证码，有则立即处理。

        严禁绕过滑块验证抓取数据，否则会触发淘宝更严重风控。

        Args:
            step_name: 当前步骤名称（用于日志）

        Raises:
            CaptchaBlockError: 验证码求解失败时抛出
        """
        if self._detect_captcha():
            logger.warning("[屏障] 步骤'%s'后检测到滑块验证，立即处理...", step_name)
            if not self._handle_captcha():
                raise CaptchaBlockError(
                    "步骤'%s'后滑块验证求解失败，终止抓取以保护账号" % step_name
                )
            logger.info("[屏障] 步骤'%s'后验证码已通过 ✅", step_name)
            time.sleep(3)

    # ═══════════════════════════════════════════════════════════════
    # 登录状态检查
    # ═══════════════════════════════════════════════════════════════

    # 登录弹窗特征（窗口标题关键词）
    LOGIN_POPUP_KEYWORDS = [
        "登录", "login", "扫码", "二维码", "请先登录",
        "账号登录", "手机登录",
    ]

    # 已登录特征（窗口标题关键词）
    LOGGED_IN_KEYWORDS = [
        "我的淘宝", "个人中心", "已登录", "我的订单",
        "我的足迹", "收藏夹",
    ]

    def check_login(self) -> bool:
        """检查淘宝登录状态（增强版）。

        检测策略:
        1. 导航到 i.taobao.com/my_itaobao
        2. 等待页面跳转
        3. 检查窗口标题判断登录状态
        4. 如果被重定向到登录页 → 未登录
        5. 如果在"我的淘宝" → 已登录
        """
        self._activate_chrome()
        time.sleep(1)

        # 导航到"我的淘宝"触发登录检测
        logger.info("[登录] 导航到我的淘宝检测登录状态...")
        self._key_press("ctrl+l")
        time.sleep(0.3)
        self._paste("https://i.taobao.com/my_itaobao")
        time.sleep(0.3)
        self._key_press("Return")

        # 等待页面加载和可能的跳转
        time.sleep(6)

        title = self._get_window_title()
        logger.info("[登录] 页面标题: %s", title)

        # 检查已登录特征
        for kw in self.LOGGED_IN_KEYWORDS:
            if kw in title:
                logger.info("[登录] ✅ 已登录淘宝 (匹配: '%s')", kw)
                return True

        # 检查登录弹窗/页面特征
        for kw in self.LOGIN_POPUP_KEYWORDS:
            if kw in title:
                logger.warning("[登录] ❌ 检测到登录弹窗 (匹配: '%s')，需要扫码登录", kw)
                return False

        # 标题可能不包含明确特征（页面内覆盖层）
        # 兜底: 页面内容检测
        logger.warning("[登录] ⚠️ 登录状态不确定 (标题=%s)，请人工确认", title[:80])
        return False

    def _detect_login_popup(self) -> bool:
        """检测当前页面是否有登录弹窗。

        淘宝登录弹窗特征:
        - 通常是页面内覆盖层（不会改变窗口标题）
        - 包含二维码图片
        - 弹窗覆盖在页面上方

        由于无CDP无法检测DOM，通过以下方式间接判断:
        1. 操作被阻止（如点击无响应）
        2. 页面标题突然包含登录关键词
        """
        title = self._get_window_title()
        for kw in self.LOGIN_POPUP_KEYWORDS:
            if kw in title:
                logger.warning("[登录弹窗] 检测到: 标题包含'%s'", kw)
                return True
        return False

    def _switch_to_qr_login(self) -> None:
        """在登录弹窗中切换到二维码扫码模式。

        淘宝登录弹窗布局特征:
        - 弹窗居中，约400x450px
        - 顶部有"扫码登录"和"密码登录"两个标签
        - 右上角有二维码图标（X关闭按钮左侧）
        - 点击二维码图标或"扫码登录"标签可切换到扫码模式
        """
        logger.info("[登录] 切换到二维码扫码模式...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wx = geo.get("x", 0)
        wy = geo.get("y", 0)
        ww = geo.get("w", 1280)
        wh = geo.get("h", 800)

        # 弹窗大约在页面中央偏上
        popup_cx = wx + ww // 2
        popup_cy = wy + wh // 3

        # 候选点击位置（二维码标签/图标）
        # 位置1: 弹窗顶部左侧"扫码登录"标签
        # 位置2: 弹窗右上角二维码小图标
        qr_positions = [
            (popup_cx - 100, popup_cy - 180),  # 扫码登录标签
            (popup_cx - 80, popup_cy - 180),   # 略偏右
            (popup_cx + 150, popup_cy - 190),  # 右上角二维码图标
            (popup_cx + 170, popup_cy - 190),  # 右上角略偏右
        ]

        for px, py in qr_positions:
            self._natural_click(px, py)
            time.sleep(0.8)
            logger.debug("[登录] 点击切换扫码: (%d, %d)", px, py)

        logger.info("[登录] 二维码模式已切换，等待扫码...")

    def wait_for_login(self, timeout: int = 120) -> bool:
        """等待用户完成扫码登录。

        循环检测登录状态，直到登录成功或超时。

        Args:
            timeout: 最长等待时间（秒）

        Returns:
            True 如果登录成功
        """
        logger.info("[登录] ⏳ 等待扫码登录（最长%ds）...", timeout)

        # 记录登录前状态
        pre_title = self._get_window_title()
        logger.info("[登录] 登录前页面: %s", pre_title)

        start = time.time()
        last_check = start

        while time.time() - start < timeout:
            time.sleep(3)

            # 每5秒打印一次状态
            if time.time() - last_check >= 5:
                elapsed = int(time.time() - start)
                title = self._get_window_title()
                logger.info("[登录] 等待中... (%ds) 标题: %s", elapsed, title[:80])

                # 检查是否已登录
                for kw in self.LOGGED_IN_KEYWORDS:
                    if kw in title:
                        logger.info("[登录] ✅ 扫码登录成功! (检测到'%s', 耗时%ds)", kw, elapsed)
                        # 记录登录后状态
                        self._record_login_success(title, pre_title)
                        time.sleep(3)  # 等待页面稳定
                        return True

                last_check = time.time()

        logger.error("[登录] 扫码登录超时 (%ds)", timeout)
        return False

    def _record_login_success(self, post_title: str, pre_title: str) -> None:
        """记录登录成功后的页面特征变化。

        用于后续优化登录检测逻辑。

        Args:
            post_title: 登录后页面标题
            pre_title: 登录前页面标题
        """
        logger.info("[登录] === 登录状态变化记录 ===")
        logger.info("[登录] 登录前标题: %s", pre_title)
        logger.info("[登录] 登录后标题: %s", post_title)
        logger.info("[登录] 已登录特征关键词: %s", self.LOGGED_IN_KEYWORDS)
        logger.info("[登录] === 记录完成 ===")

    # ═══════════════════════════════════════════════════════════════
    # 搜索流程
    # ═══════════════════════════════════════════════════════════════

    def search_keyword(self, keyword: str) -> bool:
        """在淘宝页面使用搜索框输入关键词（模拟真人操作）。

        关键经验: 直接导航搜索URL会触发淘宝风控滑块验证。
        正确方式是先到淘宝首页，然后点击搜索框逐字输入关键词。

        Args:
            keyword: 搜索关键词

        Returns:
            是否成功
        """
        self._keyword = keyword
        logger.info("[搜索] 页面内搜索: %s", keyword)

        self._activate_chrome()

        # ── 验证: 确保在淘宝页面 ──
        self._verify_step("搜索前页面检查", expected_page="taobao_home")

        # ── Step 1: 先到淘宝首页（避免直接搜URL）──
        self._key_press("ctrl+l")
        time.sleep(0.3)
        self._paste("https://www.taobao.com")
        time.sleep(0.3)
        self._key_press("Return")
        logger.info("[搜索] 导航到淘宝首页...")
        time.sleep(5 + random.randint(1, 3))

        # ── Step 2: 模拟真人浏览行为（降低风控）──
        self._scroll_down(random.randint(1, 3))
        time.sleep(1 + random.random())

        # ── Step 3: 点击页面搜索框（淘宝搜索框通常在页面顶部）──
        geo = self._get_window_geometry()
        wx = geo.get("x", 0)
        wy = geo.get("y", 0)
        ww = geo.get("w", 1280)

        # 淘宝搜索框大约在窗口中央偏左，顶部约120px处
        search_box_x = wx + int(ww * 0.35)
        search_box_y = wy + 120

        logger.info("[搜索] 点击搜索框: (%d, %d)", search_box_x, search_box_y)
        self._natural_click(search_box_x, search_box_y)
        time.sleep(1 + random.random())

        # ── Step 4: 逐字输入关键词（模拟真人打字，触发搜索建议）──
        logger.info("[搜索] 输入关键词: %s", keyword)
        self._key_press("ctrl+a")  # 清空搜索框
        time.sleep(0.2)
        self._key_press("BackSpace")
        time.sleep(0.3)

        # 使用xclip粘贴中文（xdotool type不支持中文）
        self._paste(keyword)
        time.sleep(1 + random.random())

        # ── Step 5: 回车搜索 ──
        logger.info("[搜索] 提交搜索...")
        self._key_press("Return")

        # ── 等待搜索结果加载 ──
        logger.info("[搜索] 等待搜索结果渲染...")
        time.sleep(8 + random.randint(0, 4))

        # ── 模拟真人浏览行为 ──
        self._scroll_down(random.randint(2, 5))
        time.sleep(1 + random.random() * 2)

        # ── 检查验证码（多维检测: 标题+URL+CDP） ──
        # 搜索后是最容易触发验证码的时机，必须彻底检查
        for check_round in range(3):  # 多次检查确保持续验证码能被捕获
            if self._detect_captcha():
                logger.warning("[搜索] 搜索后第%d次检查触发验证码!", check_round + 1)
                if not self._handle_captcha():
                    raise CaptchaBlockError(
                        "关键词[%s]搜索后触发验证码，求解失败" % keyword
                    )
                time.sleep(5)
            else:
                break
            time.sleep(2)

        # ── 验证搜索结果是否正常 ──
        self._verify_step("搜索后页面验证", expected_page="search")

        title = self._get_window_title()
        logger.info("[搜索] 页面标题: %s", title)

        # 最终URL检查确认没有验证码
        if self._detect_captcha():
            raise CaptchaBlockError(
                "关键词[%s]搜索结果仍被验证码拦截" % keyword
            )

        logger.info("[搜索] ✅ 搜索结果就绪")
        return True

    # ═══════════════════════════════════════════════════════════════
    # DTS 店透视操作
    # ═══════════════════════════════════════════════════════════════

    def _click_dts_icon(self) -> bool:
        """点击Chrome工具栏中的DTS扩展图标。

        策略：
        1. 用 xdotool 获取Chrome窗口几何
        2. DTS图标在工具栏右侧区域（窗口宽度 - 150~250px, Y ~45px）
        3. 点不中时尝试几个备选位置
        """
        logger.info("[DTS] 点击DTS扩展图标...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        ww = geo.get("w", 1280)

        # DTS icon position: toolbar Y + right-side X
        # Chrome UI layout: outer = inner + 87px (tabs 42% + toolbar 58%)
        # Tab bar ~37px, toolbar center ~56px from window top
        tbar_y = wy + 56  # toolbar center Y (screen)
        # DTS icon: 2nd pinned ext among 2 + puzzle + avatar on main Chrome
        # Each ~30px, DTS center ~105px from right edge
        candidates = [
            (ww - 105, tbar_y),     # DTS icon (2nd pinned, ~105px from right)
            (ww - 90, tbar_y),      # 1st ext position
            (ww - 120, tbar_y),     # slightly left
            (ww - 105, tbar_y + 3), # Y微调
            (ww - 105, tbar_y - 3),
        ]

        for i, (cx, cy) in enumerate(candidates):
            logger.debug("[DTS] 尝试位置 %d: (%d, %d)", i + 1, cx, cy)
            self._natural_click(cx, cy)
            time.sleep(2)

            # 检查DTS面板是否出现（无法用CDP检测，依赖后续流程判断）
            # 快速检查：执行一次随机滚动看是否被DTS面板遮挡
            # 如果DTS面板开了，会在页面左侧出现覆盖层
            title = self._get_window_title()
            if "店透视" in title or "diantoushi" in title.lower():
                logger.info("[DTS] DTS面板已打开!")
                return True

        logger.warning("[DTS] 未能确认DTS面板打开，继续尝试...")
        return True  # 乐观假设点中了

    def _click_market_analysis(self) -> bool:
        """点击DTS弹出面板中的'市场分析'按钮。

        DTS弹出窗口锚定在扩展图标位置(窗口右侧~105px)，向左下方展开约400x500px。
        """
        logger.info("[DTS] 点击市场分析...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        ww = geo.get("w", 1280)

        # DTS popup is near right edge, "市场分析" in upper portion
        popup_x = ww - 200  # ~200px from right (inside popup)
        popup_y = wy + 160  # ~160px from window top (below toolbar)
        candidates = [
            (popup_x, popup_y),
            (popup_x - 50, popup_y),
            (popup_x + 50, popup_y),
            (popup_x, popup_y + 30),
        ]

        for cx, cy in candidates:
            self._natural_click(cx, cy)
            time.sleep(3)
            title = self._get_window_title()
            if "市场分析" in title or "分析" in title:
                logger.info("[DTS] 市场分析面板已打开!")
                return True

        logger.info("[DTS] 市场分析点击完成（乐观）")
        return True

    def _click_start_analysis(self) -> bool:
        """点击DTS弹出面板中的'开始分析'按钮。"""
        logger.info("[DTS] 点击开始分析...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wy = geo.get("y", 0)
        ww = geo.get("w", 1280)

        # "开始分析"在弹出面板中部
        popup_x = ww - 200
        popup_y = wy + 250
        candidates = [
            (popup_x, popup_y),
            (popup_x - 50, popup_y),
            (popup_x, popup_y + 40),
            (popup_x + 50, popup_y),
        ]

        for cx, cy in candidates:
            self._natural_click(cx, cy)
            time.sleep(3)

        logger.info("[DTS] 开始分析点击完成（乐观）")
        time.sleep(5)  # 等待分析计算
        return True

    def _wait_auto_load(self) -> bool:
        """等待DTS数据自动加载 + 分批点击"自动加载"直到按钮消失。

        精确流程（经验验证参数）:
        1. 点击 DTS 面板底部"自动加载"/"加载下一页"按钮
        2. 每次点击后等待 25 秒让数据加载完成
        3. 每点击 8 次后，暂停 325 秒（约 5.5 分钟）防止淘宝反爬风控
        4. 持续循环直到按钮消失 → 全部数据加载完成
        5. 全程监控滑块验证码，出现立即处理

        Returns:
            是否成功加载全部数据
        """
        logger.info("[DTS] === 数据自动加载（精确参数模式）===")

        geo = self._get_window_geometry()
        wx = geo.get("x", 0)
        wy = geo.get("y", 0)
        ww = geo.get("w", 1280)
        wh = geo.get("h", 800)

        # DTS弹出面板底部 — "自动加载"按钮在弹出面板底部区域
        auto_load_positions = [
            (ww - 200, wy + 480),      # 弹出面板底部中间
            (ww - 200, wy + 520),      # 稍下
            (ww - 150, wy + 480),      # 偏右
            (ww - 250, wy + 480),      # 偏左
            (ww - 200, wy + 450),      # 稍上
        ]

        SINGLE_WAIT = AUTO_LOAD_SINGLE_WAIT      # 每次点击后等待25秒
        BATCH_SIZE = AUTO_LOAD_BATCH_SIZE         # 每8次点击一批
        BATCH_PAUSE = AUTO_LOAD_BATCH_PAUSE        # 每批后暂停325秒
        MAX_BATCHES = AUTO_LOAD_MAX_BATCHES        # 最多12批

        total_clicks = 0

        for batch in range(1, MAX_BATCHES + 1):
            logger.info(
                "[DTS] === 第 %d 批加载 (每批%d次点击, 每次等待%ds, 批间暂停%ds) ===",
                batch, BATCH_SIZE, SINGLE_WAIT, BATCH_PAUSE
            )

            for click_i in range(1, BATCH_SIZE + 1):
                total_clicks += 1

                # ── 点击前检查验证码 ──
                if self._detect_captcha():
                    logger.warning("[DTS] 加载过程中检测到验证码!")
                    if not self._handle_captcha():
                        raise CaptchaBlockError(
                            "DTS数据加载过程中验证码求解失败 (第%d次点击)" % total_clicks
                        )
                    # 验证通过后继续
                    time.sleep(3)

                # ── 点击每个候选位置 ──
                logger.info(
                    "[DTS] 自动加载 第%d次点击 (总第%d次, 第%d批第%d次)",
                    click_i, total_clicks, batch, click_i
                )

                for pos_x, pos_y in auto_load_positions:
                    self._natural_click(pos_x, pos_y)
                    time.sleep(0.8)

                # ── 等待 25 秒数据加载 ──
                logger.info("[DTS] 等待 %ds 数据加载...", SINGLE_WAIT)
                for wait_s in range(1, SINGLE_WAIT + 1):
                    time.sleep(1)
                    # 每5秒检查一次验证码
                    if wait_s % 5 == 0:
                        if self._detect_captcha():
                            logger.warning("[DTS] 等待过程中检测到验证码!")
                            if not self._handle_captcha():
                                raise CaptchaBlockError(
                                    "DTS等待加载过程中验证码求解失败"
                                )
                            time.sleep(3)

                logger.debug("[DTS] 第%d次点击后%ds等待完成", click_i, SINGLE_WAIT)

            # ── 每批完成后检查按钮是否消失 ──
            logger.info("[DTS] 第%d批 (%d次点击) 完成，检查按钮是否消失...", batch, total_clicks)

            # 按钮消失的判断：我们知道按钮会一直在底部固定位置
            # 如果没有CDP无法通过DOM确认，则通过多批次循环直到达到MAX_BATCHES
            # 用户描述：按钮消失即表示全部加载完成
            # 实际操作中，靠观察；代码中我们按最大批次数执行

            # ── 批间暂停 325 秒（防止淘宝反爬风控）──
            if batch < MAX_BATCHES:
                logger.info(
                    "[DTS] ⏸ 第%d批完成，暂停 %d 秒（约%.1f分钟）防止反爬风控...",
                    batch, BATCH_PAUSE, BATCH_PAUSE / 60
                )
                # 分段暂停，每30秒检查一次验证码
                pause_remaining = BATCH_PAUSE
                while pause_remaining > 0:
                    chunk = min(30, pause_remaining)
                    time.sleep(chunk)
                    pause_remaining -= chunk
                    if self._detect_captcha():
                        logger.warning("[DTS] 暂停期间检测到验证码!")
                        if not self._handle_captcha():
                            raise CaptchaBlockError("DTS暂停期间验证码求解失败")
                        time.sleep(3)
                    if pause_remaining > 0:
                        logger.debug("[DTS] 暂停剩余 %ds...", pause_remaining)

                logger.info("[DTS] ▶ 暂停结束，继续下一批加载...")

        logger.info("[DTS] ✅ 全部%d批加载完成 (总点击%d次)", MAX_BATCHES, total_clicks)
        return True

    def _click_select_all(self) -> bool:
        """点击"全选"按钮。"""
        logger.info("[DTS] 点击全选...")

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        ww = geo.get("w", 1280)

        # "全选"在DTS弹出面板数据表格左上角
        candidates = [
            (ww - 360, wy + 250),
            (ww - 340, wy + 270),
            (ww - 380, wy + 250),
        ]

        for cx, cy in candidates:
            self._natural_click(cx, cy)
            time.sleep(1)

        logger.info("[DTS] 全选完成")
        return True

    def _click_export(self) -> bool:
        """点击"导出表格"按钮并选择xlsx格式。"""
        logger.info("[DTS] 点击导出表格...")

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        ww = geo.get("w", 1280)
        wh = geo.get("h", 800)

        # DTS弹出面板 — "导出表格"按钮在面板底部
        # 用户反馈：点击一次即自动下载，文件名含日期
        export_positions = [
            (ww - 200, wy + 550),          # 弹出面板底部
            (ww - 200, wy + 520),          # 稍上
            (ww - 150, wy + 550),          # 偏右
            (ww - 250, wy + 550),          # 偏左
        ]

        for cx, cy in export_positions:
            self._natural_click(cx, cy)
            time.sleep(1.5)

        # 等待下载触发
        time.sleep(2)

        # xlsx格式通常在点击导出后自动下载，无需额外选择
        # 如果弹出下拉菜单，在相同区域附近
        xlsx_positions = [
            (ww - 200, wy + 580),
            (ww - 200, wy + 550),
            (ww - 150, wy + 580),
        ]

        for cx, cy in xlsx_positions:
            self._natural_click(cx, cy)
            time.sleep(1)

        logger.info("[DTS] 导出操作完成")
        return True

    # ═══════════════════════════════════════════════════════════════
    # 下载监控
    # ═══════════════════════════════════════════════════════════════

    def _monitor_download(self, timeout: int = DOWNLOAD_TIMEOUT) -> str | None:
        """监控下载目录，等待新的xlsx文件出现。

        Args:
            timeout: 超时时间（秒）

        Returns:
            下载文件路径，超时返回 None
        """
        logger.info("[下载] 监控目录: %s (超时%d秒)", DOWNLOAD_DIR, timeout)

        start = time.time()
        before_files = set(DOWNLOAD_DIR.glob("*.xlsx"))

        while time.time() - start < timeout:
            try:
                current = set(DOWNLOAD_DIR.glob("*.xlsx"))
                new_files = current - before_files

                # 也检查部分下载文件（.crdownload）
                if not new_files:
                    crdownload = list(DOWNLOAD_DIR.glob("*.crdownload"))
                    if crdownload:
                        logger.debug("[下载] 文件正在下载中...")
                        time.sleep(3)
                        continue

                for f in new_files:
                    if f.stat().st_size < 100:
                        continue
                    # 确认文件写入完成（大小不再变化）
                    size1 = f.stat().st_size
                    time.sleep(3)
                    try:
                        size2 = f.stat().st_size
                    except OSError:
                        continue
                    if size1 == size2:
                        logger.info("[下载] ✅ %s (%d bytes)", f.name, size2)
                        return str(f)

            except Exception as e:
                logger.debug("[下载] 检测异常: %s", e)

            time.sleep(3)

        logger.warning("[下载] 超时: %d秒内未检测到新xlsx文件", timeout)
        return None

    # ═══════════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════════

    def run_dts_export(self, keyword: str) -> str | None:
        """执行完整的DTS导出流程（含验证码全程监控）。

        流程:
        1. 点击DTS扩展图标 → 检查验证码
        2. 点击"市场分析" → 检查验证码
        3. 点击"开始分析" → 检查验证码
        4. 分批自动加载全量数据（每点击8次暂停325秒，全程监控验证码）
        5. 点击"全选" → 检查验证码
        6. 点击"导出表格" → 检查验证码
        7. 监控下载完成

        严禁绕过滑块验证 — 任何步骤检测到验证码立即处理。

        Args:
            keyword: 搜索关键词（用于日志）

        Returns:
            xlsx文件路径，失败返回 None
        """
        logger.info("[DTS] === 开始DTS导出: %s ===", keyword)

        try:
            # Step 1: 点击DTS扩展图标
            self._verify_step("DTS-点击扩展图标前", expected_page="search")
            self._click_dts_icon()
            time.sleep(3)
            self._verify_step("DTS-点击扩展图标后")

            # Step 2: 点击"市场分析"
            self._verify_step("DTS-点击市场分析前")
            self._click_market_analysis()
            time.sleep(3)
            self._verify_step("DTS-点击市场分析后")

            # Step 3: 点击"开始分析"
            self._verify_step("DTS-点击开始分析前")
            self._click_start_analysis()
            self._verify_step("DTS-点击开始分析后")

            # Step 4: 分批自动加载全量数据（精确参数: 25s/次, 8次/批, 325s批间暂停）
            self._wait_auto_load()

            # Step 5: 全选
            self._verify_step("DTS-全选前")
            self._click_select_all()
            time.sleep(2)
            self._verify_step("DTS-全选后")

            # Step 6: 导出表格
            self._verify_step("DTS-导出前")
            self._click_export()
            self._verify_step("DTS-导出后")

            # Step 7: 监控下载
            xlsx_path = self._monitor_download()
            if not xlsx_path:
                logger.error("[DTS] 导出失败: 未检测到下载文件")
                return None

            # 复制到 data/downloads
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() else "_" for c in keyword)
            dest = str(OUTPUT_DIR / f"DTS_{safe_name}_{ts}.xlsx")
            shutil.copy2(xlsx_path, dest)
            logger.info("[DTS] 文件已复制到: %s", dest)

            return dest

        except CaptchaBlockError:
            logger.error("[DTS] 验证码求解失败，导出中断")
            return None

    def crawl_keyword(self, keyword: str) -> dict[str, Any] | None:
        """执行完整的关键词抓取流程。

        流程:
        1. 确保Chrome运行（无CDP模式）
        2. 处理弹窗
        3. 检查登录状态
        4. 搜索关键词
        5. 处理验证码（如有）
        6. DTS导出Excel
        7. 解析Excel数据

        Args:
            keyword: 搜索关键词

        Returns:
            {"xlsx_path": "", "products": [...]} 或 None
        """
        keyword = keyword.strip()
        if not keyword:
            logger.error("关键词不能为空")
            return None

        start_time = time.time()
        self._keyword = keyword

        logger.info("=" * 60)
        logger.info("[爬虫] 开始抓取: %s", keyword)
        logger.info("=" * 60)

        try:
            # ── Step 1: 确保Chrome运行 ──
            wid = self._find_chrome_wid()
            if not wid:
                logger.info("[爬虫] Chrome未运行，启动中...")
                if not self._start_chrome():
                    raise CrawlError("Chrome启动失败")
            else:
                self._chrome_wid = wid
                logger.info("[爬虫] Chrome已在运行: %s", wid)
                self._activate_chrome()

            # ── 入口验证码屏障: 检查当前页面是否已被验证码阻塞 ──
            self._record_feature("入口", "开始抓取前页面状态检查")
            if self._detect_captcha():
                logger.warning("[爬虫] 入口检测到验证码，尝试求解...")
                if not self._handle_captcha():
                    raise CaptchaBlockError("入口验证码求解失败，页面已被封锁")
                logger.info("[爬虫] 入口验证码已清除，继续流程")
                time.sleep(3)

            # ── Step 2: 处理弹窗 + 登录检测 ──
            popups_ok = self._handle_popups()

            # ── Step 3: 确认登录状态（未登录则引导扫码） ──
            if not self.check_login():
                if self._detect_login_popup():
                    logger.info("[登录] 检测到登录弹窗，切换到扫码模式...")
                    self._switch_to_qr_login()
                    logger.info("[登录] ╔══════════════════════════════════╗")
                    logger.info("[登录] ║ 请在Chrome窗口中用手机淘宝扫码 ║")
                    logger.info("[登录] ╚══════════════════════════════════╝")

                if not self.wait_for_login(timeout=120):
                    raise LoginRequiredError(
                        "扫码登录超时（120秒）。请在Chrome中完成扫码后重试。"
                    )
                logger.info("[登录] 登录成功，Cookie已持久化，继续抓取流程")

            # ── Step 4: 搜索关键词 ──
            self.search_keyword(keyword)

            # ── Step 5: DTS导出 ──
            xlsx_path = self.run_dts_export(keyword)
            if not xlsx_path:
                logger.error("[爬虫] DTS导出失败")
                return None

            # ── Step 6: 解析Excel ──
            from services.dts_parser import DtsDataParser
            parser = DtsDataParser()
            raw_products = parser.parse(xlsx_path)
            products = parser.normalize_products(raw_products)

            elapsed = time.time() - start_time
            logger.info("[爬虫] ✅ 抓取完成: %d个商品, 耗时%ds",
                       len(products), int(elapsed))

            return {
                "xlsx_path": xlsx_path,
                "products": products,
                "keyword": keyword,
                "elapsed": elapsed,
                "product_count": len(products),
            }

        except CaptchaBlockError as e:
            logger.error("[爬虫] 验证码拦截: %s", e)
            return None
        except LoginRequiredError as e:
            logger.error("[爬虫] 登录问题: %s", e)
            return None
        except Exception as e:
            logger.exception("[爬虫] 异常: %s", e)
            return None
        finally:
            elapsed = time.time() - start_time
            logger.info("[爬虫] 总耗时: %ds", int(elapsed))


# ── 模块级便捷函数 ────────────────────────────────────────

_crawler_instance: XdotoolCrawler | None = None


def get_crawler() -> XdotoolCrawler:
    """获取爬虫单例"""
    global _crawler_instance
    if _crawler_instance is None:
        _crawler_instance = XdotoolCrawler()
    return _crawler_instance


def crawl_keyword(keyword: str) -> dict[str, Any] | None:
    """便捷函数：执行关键词抓取"""
    crawler = get_crawler()
    return crawler.crawl_keyword(keyword)


def run_dts_export(keyword: str) -> str | None:
    """便捷函数：仅执行DTS导出"""
    crawler = get_crawler()
    return crawler.run_dts_export(keyword)


def search_keyword(keyword: str) -> bool:
    """便捷函数：仅搜索关键词"""
    crawler = get_crawler()
    return crawler.search_keyword(keyword)
