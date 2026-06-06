"""页面状态验证器

在每个操作步骤前验证页面是否符合预期，防止盲操作。
使用 xdotool 窗口标题 + PIL 截图像素分析（零CDP）。

验证策略:
1. 窗口标题检查 (快速, xdotool getwindowname)
2. 截图区域像素分析 (PIL.ImageGrab, 检查特定区域颜色/亮度)
3. 验证码特征检测 (标题关键词 + 截图特征)

用法:
    from services.page_verifier import PageVerifier
    pv = PageVerifier()
    pv.assert_search_page(keyword)   # 确认在搜索结果页
    pv.assert_dts_panel_open()       # 确认DTS面板已打开
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any

logger = logging.getLogger("page_verifier")

DISPLAY = os.environ.get("DISPLAY", ":0")
XAUTH = os.environ.get(
    "XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
)

# 验证码特征关键词（窗口标题匹配）
CAPTCHA_TITLE_KEYWORDS = [
    "验证码", "验证", "captcha", "安全验证",
    "滑动", "punish", "slider", "异常",
]

# 淘宝页面标题特征
PAGE_SIGNATURES = {
    "taobao_home": ["淘宝", "taobao.com"],
    "search": ["淘宝搜索", "搜索"],  # + keyword
    "login": ["登录", "login"],
    "my_taobao": ["我的淘宝", "个人中心"],
    "item_detail": ["item.taobao.com", "detail.tmall.com"],
    "dts": ["店透视", "diantoushi", "市场分析"],
    "captcha": CAPTCHA_TITLE_KEYWORDS,
}


def _xdotool_env() -> dict:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH
    return env


def _xd(*args) -> str:
    r = subprocess.run(
        ["xdotool"] + list(args),
        env=_xdotool_env(), capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


class PageVerifier:
    """页面状态验证器 — 每一步都确认页面正确后再操作"""

    def __init__(self):
        self._last_screenshot = None
        self._screenshot_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "logs", "screenshots"
        )
        os.makedirs(self._screenshot_dir, exist_ok=True)

    # ═══════════════════════════════════════════════════════════════
    # 窗口信息
    # ═══════════════════════════════════════════════════════════════

    def _find_chrome_wid(self) -> str | None:
        """查找真正的Chrome浏览器窗口（排除10x10隐藏辅助窗口）。"""
        # 优先按名称搜索"淘宝"
        result = _xd("search", "--name", "淘宝")
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids:
            return wids[0]
        # 按class搜索，选最大窗口
        result = _xd("search", "--class", "google-chrome")
        wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
        if wids and len(wids) > 1:
            best_wid = None
            best_area = 0
            for wid in wids:
                try:
                    geo = _xd("getwindowgeometry", "--shell", wid)
                    w = h = 0
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
            if best_wid and best_area > 10000:
                return best_wid
        if wids:
            return wids[0]
        for name in ["Google Chrome"]:
            result = _xd("search", "--name", name)
            wids = [w.strip() for w in result.split("\n") if w.strip().isdigit()]
            if wids:
                return wids[0]
        return None

    def get_title(self) -> str:
        """获取当前Chrome窗口标题"""
        wid = self._find_chrome_wid()
        if not wid:
            return ""
        try:
            return _xd("getwindowname", wid)
        except Exception:
            return ""

    def get_geometry(self) -> dict[str, int]:
        """获取窗口几何信息"""
        wid = self._find_chrome_wid()
        if not wid:
            return {"x": 0, "y": 0, "w": 1280, "h": 800}
        try:
            geo = _xd("getwindowgeometry", "--shell", wid)
            result = {}
            for line in geo.split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    try:
                        result[k.lower()] = int(v)
                    except ValueError:
                        pass
            return result
        except Exception:
            return {"x": 0, "y": 0, "w": 1280, "h": 800}

    # ═══════════════════════════════════════════════════════════════
    # 截图分析
    # ═══════════════════════════════════════════════════════════════

    _screenshot_failed = False  # 类级标记，避免重复日志

    def _take_screenshot(self) -> Any | None:
        """使用 PIL.ImageGrab 截取全屏。失败时静默降级。"""
        if PageVerifier._screenshot_failed:
            return None
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            self._last_screenshot = img
            return img
        except Exception as e:
            PageVerifier._screenshot_failed = True
            logger.debug("截图不可用 (PIL.ImageGrab): %s", e)
            return None

    def _save_debug_screenshot(self, name: str) -> str:
        """保存截图用于调试。失败时静默降级。"""
        if PageVerifier._screenshot_failed:
            return ""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self._screenshot_dir, f"{name}_{ts}.png")
            img.save(path)
            logger.info("[截图] 已保存: %s", path)
            return path
        except Exception:
            PageVerifier._screenshot_failed = True
            return ""

    def _check_region_color(self, x: int, y: int, w: int, h: int,
                             expected_dominant: tuple | None = None,
                             min_brightness: int = 0) -> dict:
        """检查截图指定区域的颜色特征。

        Args:
            x, y: 区域左上角坐标
            w, h: 区域宽高
            expected_dominant: 期望的主色调 (R, G, B) 范围
            min_brightness: 最低亮度

        Returns:
            {"match": bool, "avg_rgb": (r,g,b), "brightness": float}
        """
        img = self._take_screenshot()
        if img is None:
            return {"match": False, "error": "screenshot failed"}

        try:
            region = img.crop((x, y, x + w, y + h))
            pixels = list(region.getdata())
            if not pixels:
                return {"match": False, "error": "empty region"}

            # 计算平均颜色
            avg_r = sum(p[0] for p in pixels) // len(pixels)
            avg_g = sum(p[1] for p in pixels) // len(pixels)
            avg_b = sum(p[2] for p in pixels) // len(pixels)
            brightness = (avg_r + avg_g + avg_b) / 3

            result = {
                "avg_rgb": (avg_r, avg_g, avg_b),
                "brightness": brightness,
                "pixel_count": len(pixels),
            }

            if min_brightness > 0:
                result["match"] = brightness >= min_brightness
            elif expected_dominant:
                dr, dg, db = expected_dominant
                result["match"] = (
                    abs(avg_r - dr) < 40 and
                    abs(avg_g - dg) < 40 and
                    abs(avg_b - db) < 40
                )
            else:
                result["match"] = True

            return result

        except Exception as e:
            return {"match": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # 验证码检测
    # ═══════════════════════════════════════════════════════════════

    def has_captcha(self) -> bool:
        """检测是否有滑块验证码（多维度检测）。

        检测维度:
        1. 窗口标题是否包含验证码关键词
        2. 截图页面中央下方是否有滑块特征色（橙色/蓝色）
        """
        # ── 维度1: 标题检测 ──
        title = self.get_title().lower()
        for kw in CAPTCHA_TITLE_KEYWORDS:
            if kw.lower() in title:
                logger.warning("[页面验证] 标题检测到验证码: %s", title)
                return True

        # ── 维度2: 截图分析滑块区域（页面中央偏下） ──
        # 淘宝滑块验证通常出现在视口中央，有橙色滑块按钮
        geo = self.get_geometry()
        wx, wy = geo.get("x", 0), geo.get("y", 0)
        ww, wh = geo.get("w", 1280), geo.get("h", 800)

        # 滑块区域大约在页面中央 1/3 到 2/3 处
        slider_region_y = wy + wh // 3
        slider_region_h = wh // 3

        try:
            result = self._check_region_color(
                wx + ww // 4,
                slider_region_y,
                ww // 2,
                slider_region_h,
                min_brightness=30,
            )
            if result.get("match"):
                # 亮度足够 — 可能有弹窗
                # 进一步检查是否有橙色滑块 (淘宝滑块按钮橙色: ~255, 140, 0)
                img = self._take_screenshot()
                if img:
                    slider_check = img.crop((
                        wx + ww // 3,
                        slider_region_y + slider_region_h // 2,
                        wx + ww * 2 // 3,
                        slider_region_y + slider_region_h,
                    ))
                    orange_count = 0
                    for p in slider_check.getdata():
                        r, g, b = p[0], p[1], p[2]
                        if r > 200 and 80 < g < 180 and b < 100:
                            orange_count += 1
                    if orange_count > 50:
                        logger.warning(
                            "[页面验证] 截图检测到橙色滑块区域 (%d个橙色像素)",
                            orange_count
                        )
                        return True
        except Exception as e:
            logger.debug("[页面验证] 截图分析异常: %s", e)

        return False

    # ═══════════════════════════════════════════════════════════════
    # 页面断言
    # ═══════════════════════════════════════════════════════════════

    def assert_page(self, expected_type: str, keyword: str = "",
                    step_name: str = "") -> bool:
        """断言当前页面类型符合预期。

        不符合预期时: 记录警告 + 保存截图 + 返回 False

        Args:
            expected_type: 期望的页面类型 (search/login/dts/item_detail/...)
            keyword: 搜索关键词（用于 search 页面验证）
            step_name: 步骤名称

        Returns:
            True 如果页面符合预期
        """
        title = self.get_title()

        signatures = PAGE_SIGNATURES.get(expected_type, [])
        matched = False

        for sig in signatures:
            if sig.lower() in title.lower():
                matched = True
                break

        # 特殊处理: search 页面需要关键词也在标题中
        if expected_type == "search" and keyword:
            if keyword not in title and "搜索" not in title:
                matched = False

        if matched:
            logger.debug("[页面验证] ✅ %s: 页面正确 (title=%s)", step_name, title[:80])
            return True

        # ── 页面异常 ──
        logger.warning(
            "[页面验证] ⚠️ %s: 页面不符合预期! 期望=%s, 实际标题=%s",
            step_name, expected_type, title[:100]
        )

        # 先检查是否因为验证码
        if self.has_captcha():
            logger.error("[页面验证] ❌ %s: 页面被验证码拦截!", step_name)

        # 保存截图用于后续分析
        self._save_debug_screenshot(f"page_mismatch_{step_name}")

        return False

    def assert_no_captcha(self, step_name: str = "") -> tuple[bool, bool]:
        """断言当前页面没有验证码。

        Returns:
            (页面正常, 有验证码)
            - (True, False): 无验证码，正常
            - (False, True): 检测到验证码
            - (False, False): 其他异常
        """
        if self.has_captcha():
            logger.warning("[页面验证] ⚠️ %s: 检测到滑块验证码!", step_name)
            self._save_debug_screenshot(f"captcha_detected_{step_name}")
            return False, True
        return True, False

    # ═══════════════════════════════════════════════════════════════
    # 快捷断言
    # ═══════════════════════════════════════════════════════════════

    def verify_before_action(self, step_name: str,
                              expected_page: str = "",
                              keyword: str = "") -> dict:
        """每个操作前的综合验证。

        验证维度:
        1. Chrome窗口是否存在
        2. 是否有滑块验证码（有则立即需要处理）
        3. 页面是否符合预期类型

        Returns:
            {
                "ok": bool,          # 可以继续操作
                "has_captcha": bool, # 需要先处理验证码
                "page_ok": bool,     # 页面符合预期
                "title": str,        # 当前标题
                "warnings": [str],   # 警告信息
            }
        """
        result = {
            "ok": True,
            "has_captcha": False,
            "page_ok": True,
            "title": "",
            "warnings": [],
        }

        # 1. Chrome窗口检查
        wid = self._find_chrome_wid()
        if not wid:
            result["ok"] = False
            result["warnings"].append("Chrome窗口不存在")
            logger.error("[页面验证] ❌ %s: Chrome窗口不存在!", step_name)
            return result

        result["title"] = self.get_title()

        # 2. 验证码检查（最高优先级）
        page_ok, has_captcha = self.assert_no_captcha(step_name)
        if has_captcha:
            result["has_captcha"] = True
            result["ok"] = False
            result["warnings"].append(f"检测到滑块验证码 (title={result['title'][:80]})")

        # 3. 页面类型检查
        if expected_page:
            page_match = self.assert_page(expected_page, keyword, step_name)
            if not page_match:
                result["page_ok"] = False
                if not has_captcha:  # 不是验证码导致的不匹配
                    result["warnings"].append(
                        f"页面类型不匹配: 期望={expected_page}, "
                        f"实际title={result['title'][:80]}"
                    )

        if result["warnings"]:
            logger.warning("[页面验证] %s: %s", step_name,
                          "; ".join(result["warnings"]))

        result["ok"] = not result["has_captcha"] and result["page_ok"]
        return result
