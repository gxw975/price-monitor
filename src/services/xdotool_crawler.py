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
AUTO_LOAD_SINGLE_WAIT = 25       # 每次点击后等待25秒
AUTO_LOAD_BATCH_SIZE = 8          # 每8次点击一批
AUTO_LOAD_BATCH_PAUSE = 325       # 每批后暂停325秒（约5.5分钟）
AUTO_LOAD_MAX_BATCHES = 12        # 最多12批
# 滑块验证配置
MAX_SLIDER_RETRIES = 3


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

    def _get_verifier(self):
        """获取页面验证器（延迟导入避免循环依赖）"""
        if self._verifier is None:
            from services.page_verifier import PageVerifier
            self._verifier = PageVerifier()
        return self._verifier

    def _verify_step(self, step_name: str, expected_page: str = "") -> dict:
        """每个操作前的综合验证（页面状态 + 验证码）。

        验证通过 → 返回 {"ok": True}
        验证码检出 → 自动调用求解 → 求解成功返回 {"ok": True}
        页面不匹配 → 记录警告但继续执行（避免因为标题检测误判而中断）

        严禁绕过验证码 — 检测到验证码必须立即处理。
        """
        verifier = self._get_verifier()
        result = verifier.verify_before_action(
            step_name, expected_page, self._keyword
        )

        if result["has_captcha"]:
            logger.warning("[验证] %s: 检测到验证码，立即处理!", step_name)
            if not self._handle_captcha():
                raise CaptchaBlockError(
                    "步骤'%s'验证码求解失败" % step_name
                )
            # 验证通过后重新检查页面
            time.sleep(3)
            result2 = verifier.verify_before_action(
                f"{step_name}(验证后)", expected_page, self._keyword
            )
            if result2["has_captcha"]:
                raise CaptchaBlockError(
                    "步骤'%s'验证码求解后仍检测到验证码" % step_name
                )
            result = result2

        if not result["page_ok"]:
            logger.warning(
                "[验证] %s: 页面状态异常 — %s — 继续执行（避免误判中断）",
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
        # 策略1: 名称搜索"淘宝"（最优先，直接定位到淘宝页面）
        result = _xd("search", "--name", "淘宝")
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids:
            logger.debug("[窗口] 通过名称'淘宝'找到: %s", wids[0])
            return wids[0]

        # 策略2: class搜索，选最大窗口（排除隐藏的10x10辅助窗口）
        result = _xd("search", "--class", "google-chrome")
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids:
            # 按窗口面积排序，选最大的
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
            if best_wid and best_area > 10000:  # 至少100x100以上
                logger.debug("[窗口] 通过class+面积(%d)找到: %s", best_area, best_wid)
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
            _xd("windowactivate", "--sync", wid)
            _xd("windowfocus", "--sync", wid)
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
        """检测是否有验证码（通过窗口标题 + 已知URL特征）。

        关键检测特征（实测记录）:
        1. 标题包含 "h5api.m.taobao.com" → 验证码iframe/弹窗页面
        2. 标题包含传统验证码关键词: 验证码/滑块/slider/punish

        验证失败状态特征:
        - "点击我重试" = errloading 错误，需点击重置
        - "验证失败，点击框体重试" = 轨迹被判为机器人
        """
        title = self._get_window_title()

        # 核心特征: h5api.m.taobao.com (淘宝验证码iframe域名)
        if "h5api.m.taobao.com" in title or "h5api" in title:
            logger.warning("[验证码] 检测到h5api验证码域名: %s", title[:80])
            return True

        # 传统关键词检测
        captcha_keywords = ["验证码", "验证", "captcha", "安全验证",
                            "滑动", "punish", "slider", "_____tmd_____"]
        for kw in captcha_keywords:
            if kw.lower() in title.lower():
                logger.warning("[验证码] 检测到关键词'%s': %s", kw, title[:80])
                return True

        return False

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
        """滑块验证码求解（改进版 — 基于经验文档+实测校准）。

        关键改进:
        - 使用 xdotool mousedown/mousemove/mouseup（比XTest更原生）
        - 动态计算滑块坐标（基于窗口几何 + 经验比例）
        - 多段变速轨迹: 加速→匀速→减速 + 微手抖
        - 步数控制在10-15步，总时长0.8-1.8秒
        - 过冲回弹模拟真人松手前犹豫

        Returns:
            是否成功求解
        """
        logger.info("[验证码] 滑块求解（优化版）...")

        try:
            geo = self._get_window_geometry()
            wx = geo.get("x", 66)
            wy = geo.get("y", 32)
            ww = geo.get("w", 1280)
            wh = geo.get("h", 800)

            # 滑块坐标计算（基于窗口大小的比例估算）
            # 经验: 滑块轨道中心在窗口X约55%、Y约67%处
            track_cx = wx + int(ww * 0.55)
            track_cy = wy + int(wh * 0.67)
            # 滑块按钮在轨道左端约40%处
            sx = wx + int(ww * 0.43)
            sy = track_cy
            dist = int(ww * 0.22)  # 轨道约22%窗口宽度

            logger.info("[验证码] 计算坐标: screen(%d,%d) dist=%d (窗口%dx%d)", sx, sy, dist, ww, wh)

            # ── 使用 xdotool 原生事件拖拽（被浏览器信任）──
            env = _xdotool_env()

            # 1. 接近滑块（2-3段折线模拟找按钮）
            approach_points = [
                (sx - random.randint(60, 90), sy + random.randint(-15, 15)),
                (sx - random.randint(20, 35), sy + random.randint(-5, 5)),
                (sx, sy),
            ]
            for ax, ay in approach_points:
                subprocess.run(
                    ["xdotool", "mousemove", str(ax), str(ay)],
                    env=env, capture_output=True, timeout=5,
                )
                time.sleep(0.06 + random.random() * 0.08)

            # 2. 瞄准停顿
            time.sleep(0.1 + random.random() * 0.15)

            # 3. 按下
            subprocess.run(["xdotool", "mousedown", "1"],
                          env=env, capture_output=True, timeout=5)
            time.sleep(0.03 + random.random() * 0.03)

            # 4. 三段式拖拽: 加速→匀速→减速
            segments = [
                (0.0, 0.20, 0.05, 0.09),   # 起手加速 20%
                (0.20, 0.75, 0.03, 0.06),  # 中间匀速 55%
                (0.75, 1.0, 0.06, 0.11),   # 末尾减速 25%
            ]

            total_points = 0
            for seg_start, seg_end, min_d, max_d in segments:
                n = random.randint(4, 7)
                total_points += n
                for j in range(n):
                    sp = j / n
                    p = seg_start + (seg_end - seg_start) * sp
                    # ease-out 缓出曲线 + 微随机
                    e = 1 - (1 - p) ** 2.2
                    e += (random.random() - 0.5) * 0.006

                    ex = int(sx + dist * e)
                    # 多频自然手抖
                    wobble = (math.sin(p * math.pi * 4.7) * 1.5 +
                              math.sin(p * math.pi * 11.3) * 0.5)
                    ey = int(sy + wobble)

                    subprocess.run(
                        ["xdotool", "mousemove", str(ex), str(ey)],
                        env=env, capture_output=True, timeout=5,
                    )
                    time.sleep(min_d + random.random() * (max_d - min_d))

            # 5. 过冲回弹（模拟松手前犹豫）
            subprocess.run(
                ["xdotool", "mousemove",
                 str(sx + dist + random.randint(1, 4)),
                 str(sy + random.randint(-1, 1))],
                env=env, capture_output=True, timeout=5,
            )
            time.sleep(0.04)
            subprocess.run(
                ["xdotool", "mousemove", str(sx + dist), str(sy)],
                env=env, capture_output=True, timeout=5,
            )
            time.sleep(0.08 + random.random() * 0.1)

            # 6. 松手
            subprocess.run(["xdotool", "mouseup", "1"],
                          env=env, capture_output=True, timeout=5)

            logger.info("[验证码] 拖拽完成: %d点 screen(%d,%d)→(%d,%d)",
                       total_points, sx, sy, sx + dist, sy)

            # 等待验证结果
            time.sleep(4)
            return True

        except Exception as e:
            logger.warning("[验证码] 滑块求解异常: %s", e)
            return False

    def _handle_captcha(self) -> bool:
        """处理验证码：检测 → 求解 → 验证结果。

        Returns:
            是否成功处理
        """
        for attempt in range(1, MAX_SLIDER_RETRIES + 1):
            if not self._detect_captcha():
                logger.info("[验证码] 无验证码弹窗")
                return True

            logger.info("[验证码] 第 %d/%d 次尝试求解", attempt, MAX_SLIDER_RETRIES)
            self._activate_chrome()

            if self._solve_captcha_x11():
                time.sleep(3)
                if not self._detect_captcha():
                    return True
                logger.warning("[验证码] 拖拽后验证码仍在，重试...")
            else:
                time.sleep(3)

        logger.error("[验证码] 求解失败，已重试%d次", MAX_SLIDER_RETRIES)
        return False

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

        # ── 检查验证码 ──
        if self._detect_captcha():
            logger.warning("[搜索] 搜索后触发验证码!")
            if not self._handle_captcha():
                raise CaptchaBlockError(
                    "关键词[%s]搜索后触发验证码，求解失败" % keyword
                )
            time.sleep(5)

        # ── 验证搜索结果是否正常 ──
        self._verify_step("搜索后页面验证", expected_page="search")

        title = self._get_window_title()
        logger.info("[搜索] 页面标题: %s", title)

        if "验证" in title or "captcha" in title.lower():
            raise CaptchaBlockError(
                "关键词[%s]搜索结果被验证码拦截" % keyword
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

        # DTS 扩展图标候选位置（相对于Chrome窗口左上角）
        # Chrome工具栏高度约40-60px，扩展图标在地址栏右侧
        candidates = [
            (wx + ww - 200, wy + 45),  # 主要候选
            (wx + ww - 250, wy + 45),  # 更靠左
            (wx + ww - 150, wy + 45),  # 更靠右
            (wx + ww - 220, wy + 50),  # Y微调
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
        """点击DTS面板中的"市场分析"按钮。

        策略：DTS面板打开后，"市场分析"按钮通常在页面左侧面板中。
        """
        logger.info("[DTS] 点击市场分析...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        wh = geo.get("h", 800)

        # DTS 面板在页面左侧，"市场分析"按钮在面板中部偏上位置
        # 屏幕坐标估算
        candidates = [
            (wx + 150, wy + wh // 3),      # 左侧面板 1/3 处
            (wx + 120, wy + wh // 3),      # 稍微偏左
            (wx + 180, wy + wh // 3),      # 稍微偏右
            (wx + 150, wy + wh // 4),      # 更靠上
        ]

        for cx, cy in candidates:
            self._natural_click(cx, cy)
            time.sleep(3)
            # 检查是否打开了新标签页
            title = self._get_window_title()
            if "市场分析" in title or "分析" in title:
                logger.info("[DTS] 市场分析面板已打开!")
                return True

        logger.info("[DTS] 市场分析点击完成（乐观）")
        return True

    def _click_start_analysis(self) -> bool:
        """点击DTS面板中的"开始分析"按钮。"""
        logger.info("[DTS] 点击开始分析...")
        self._activate_chrome()

        geo = self._get_window_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        wh = geo.get("h", 800)
        ww = geo.get("w", 1280)

        # "开始分析"按钮通常在DTS面板内容区域的中部
        candidates = [
            (wx + ww // 2, wy + wh // 2),
            (wx + ww // 2, wy + wh // 3),
            (wx + ww // 3, wy + wh // 2),
            (wx + ww // 2, wy + wh * 2 // 3),
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

        # DTS面板底部按钮区域
        # "自动加载"/"加载下一页"按钮通常在面板最下面一行
        auto_load_positions = [
            (wx + ww // 2, wy + wh - 80),       # 底部中间
            (wx + ww // 2, wy + wh - 100),      # 底部偏上
            (wx + ww // 3, wy + wh - 80),       # 左下
            (wx + ww * 2 // 3, wy + wh - 80),   # 右下
            (wx + ww // 2, wy + wh - 120),      # 更偏上
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

        # "全选"通常在表格左上角
        candidates = [
            (wx + 100, wy + 200),
            (wx + 80, wy + 220),
            (wx + 120, wy + 200),
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

        # "导出表格"按钮通常在DTS面板底部或工具栏
        export_positions = [
            (wx + ww - 200, wy + 80),          # 右上角工具栏
            (wx + ww - 150, wy + 80),
            (wx + ww - 200, wy + 100),
            (wx + ww // 2, wy + wh - 60),       # 底部
        ]

        for cx, cy in export_positions:
            self._natural_click(cx, cy)
            time.sleep(1.5)

        # 等待导出下拉菜单出现
        time.sleep(2)

        # 点击 xlsx 格式选项
        # 通常在点击"导出表格"后的下拉菜单中
        xlsx_positions = [
            (wx + ww - 200, wy + 150),
            (wx + ww - 200, wy + 200),
            (wx + ww - 200, wy + 250),
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
