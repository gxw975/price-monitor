# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取功能
"""验证码检测模块 — 截图分析 + 标题检测

检测策略（按优先级）：
1. 窗口标题关键词匹配（拦截标签页）
2. 截图分析：白色弹窗 → 灰色滑轨 → 文字行 → >>箭头

用法:
    from services.captcha_detector import CaptchaDetector
    detector = CaptchaDetector()
    found, info = detector.detect(wid)
    if found:
        coords = detector.get_slider_coords(win_x, win_y, info)
"""

import struct, subprocess, os, logging, json, time
from datetime import datetime
from typing import Optional

logger = logging.getLogger("captcha_detector")

DISPLAY = os.environ.get("DISPLAY", ":0")
XAUTH = os.environ.get("XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3")

# ── 验证码特征常量（基于实测记录）──
CAPTCHA_TITLE_KEYWORDS = [
    "验证码", "验证", "captcha", "安全验证",
    "滑动", "滑块", "punish", "slider", "拦截",
    "_____tmd_____", "h5api", "异常流量", "频繁访问",
]

# 淘宝滑块验证码的可视特征
SLIDER_FEATURES = {
    "hint_text": "请按住滑块，拖动到最右边",
    "slider_marker": ">>",
    "button_color": "同滑轨灰色",
    "track_appearance": "灰色水平条，宽200-400px",
    "modal_appearance": "白色弹窗，页面中央",
}


class CaptchaDetector:
    """验证码检测器"""

    def __init__(self):
        self._last_result = None

    def _env(self):
        e = os.environ.copy()
        e["DISPLAY"] = DISPLAY
        e["XAUTHORITY"] = XAUTH
        return e

    def _xd(self, *args):
        return subprocess.run(
            ["xdotool"] + list(args), env=self._env(),
            capture_output=True, text=True, timeout=10
        ).stdout.strip()

    def _take_screenshot(self, wid: str):
        """截取窗口，返回 (raw_bytes, W, H, bpl, pix_start)"""
        xwd_path = "/tmp/captcha_detect.xwd"
        subprocess.run(["xwd", "-id", wid, "-out", xwd_path],
                       env=self._env(), capture_output=True, timeout=10)
        with open(xwd_path, 'rb') as f:
            raw = f.read()

        def u32(off):
            return struct.unpack_from('>I', raw, off)[0]

        W = u32(16)
        H = u32(20)
        bpl = u32(48)
        num_colors = u32(72)
        pix_start = u32(0) + num_colors * 12
        return raw, W, H, bpl, pix_start

    @staticmethod
    def _rgb(raw, bpl, pix_start, x, y):
        """BGRA → RGB"""
        off = pix_start + y * bpl + x * 4
        return (raw[off + 2], raw[off + 1], raw[off])

    @staticmethod
    def _is_gray(r, g, b, tolerance=15):
        return abs(r - g) < tolerance and abs(g - b) < tolerance

    @staticmethod
    def _is_white(r, g, b):
        return r > 245 and g > 245 and b > 245

    @staticmethod
    def _is_dark(r, g, b):
        return r < 60 and g < 60 and b < 60

    # ═══════════════════════════════════════════
    # 维度1: 标题检测
    # ═══════════════════════════════════════════

    def detect_by_title(self, wid: str):
        """检测窗口标题是否包含验证码关键词（拦截标签页）"""
        title = self._xd("getwindowname", wid)
        title_lower = title.lower()
        for kw in CAPTCHA_TITLE_KEYWORDS:
            if kw.lower() in title_lower:
                logger.warning("[验证码检测] 标题关键词'%s': %s", kw, title[:100])
                return True, kw, title
        return False, None, title

    # ═══════════════════════════════════════════
    # 维度2: 截图分析
    # ═══════════════════════════════════════════

    def detect_in_page(self, raw, W, H, bpl, pix_start):
        """截图分析：检测页面内嵌滑块弹窗

        检测链路: 白色弹窗 → 灰色滑轨 → 文字行 → >>箭头
        """
        # ── A. 找大面积白色矩形（弹窗）──
        white_rows = {}
        for y in range(50, H - 50, 3):
            white_runs = []
            rs = None
            for x in range(50, W - 50, 3):
                r, g, b = self._rgb(raw, bpl, pix_start, x, y)
                if self._is_white(r, g, b):
                    if rs is None:
                        rs = x
                else:
                    if rs is not None and x - rs > 200:
                        white_runs.append((rs, x, x - rs))
                    rs = None
            if rs is not None and (W - 50) - rs > 200:
                white_runs.append((rs, W - 50, (W - 50) - rs))
            if white_runs:
                white_rows[y] = white_runs

        if not white_rows:
            return False, {"reason": "no_large_white_area"}

        # 聚类白色行
        ys = sorted(white_rows.keys())
        white_regions = []
        cs = ys[0]
        cp = ys[0]
        for y in ys[1:]:
            if y - cp > 5:
                if cp - cs > 30:
                    white_regions.append((cs, cp))
                cs = y
            cp = y
        if cp - cs > 30:
            white_regions.append((cs, cp))

        logger.debug("[验证码检测] 白色区域: %d 个", len(white_regions))

        # ── B/C/D. 在每个白色区域内搜索滑块特征 ──
        for wy1, wy2 in white_regions:
            if wy1 < H * 0.10 or wy2 > H * 0.90:
                continue  # 排除顶部导航栏和底部

            # B. 搜索水平灰色滑轨
            best_gray = None
            for y in range(wy1 + 20, wy2 - 10, 1):
                gray_runs = []
                gs = None
                for x in range(50, W - 50, 3):
                    r, g, b = self._rgb(raw, bpl, pix_start, x, y)
                    if self._is_gray(r, g, b, 12) and 170 < r < 245:
                        if gs is None:
                            gs = x
                    else:
                        if gs is not None and x - gs > 100:
                            gray_runs.append((gs, x, x - gs))
                        gs = None
                if gs is not None and (W - 50) - gs > 100:
                    gray_runs.append((gs, W - 50, (W - 50) - gs))
                for gx1, gx2, gw in gray_runs:
                    if best_gray is None or gw > best_gray[3]:
                        best_gray = (y, gx1, gx2, gw)

            if best_gray is None:
                continue

            track_y, tx1, tx2, track_w = best_gray

            # 滑轨宽度合理性检查
            if track_w < 120 or track_w > 600:
                continue

            # C. 轨上方文字检测
            text_found = False
            for ty in range(track_y - 35, track_y - 5, 1):
                dark = sum(1 for tx in range(tx1, tx2, 4)
                          if self._is_dark(*self._rgb(raw, bpl, pix_start, tx, ty)))
                total = (tx2 - tx1) // 4
                if total > 0 and dark / total > 0.04:
                    text_found = True
                    break

            # D. 轨左端>>箭头检测
            chevron_found = False
            for cy in range(track_y - 4, track_y + 4):
                dark = sum(1 for cx in range(tx1 + 2, tx1 + 30, 2)
                          if self._is_dark(*self._rgb(raw, bpl, pix_start, cx, cy)))
                if dark >= 3:
                    chevron_found = True
                    break

            # 综合置信度
            confidence = 0
            if text_found: confidence += 40
            if chevron_found: confidence += 30
            if 150 < track_w < 500: confidence += 30

            logger.debug(
                "[验证码检测] 候选: Y=%d 轨宽=%d 文字=%s 箭头=%s 置信度=%d%%",
                track_y, track_w, text_found, chevron_found, confidence
            )

            if confidence >= 50:
                return True, {
                    "track_y": track_y,
                    "track_x1": tx1,
                    "track_x2": tx2,
                    "track_width": track_w,
                    "white_region": (wy1, wy2),
                    "text_found": text_found,
                    "chevron_found": chevron_found,
                    "confidence": confidence,
                }

        return False, {"reason": "no_slider_pattern"}

    # ═══════════════════════════════════════════
    # 综合检测入口
    # ═══════════════════════════════════════════

    def detect(self, wid: Optional[str] = None) -> tuple:
        """检测当前页面是否有验证码

        Args:
            wid: Chrome窗口ID，为None则自动查找

        Returns:
            (found: bool, info: dict)
        """
        if wid is None:
            wids = self._xd("search", "--onlyvisible", "--class", "chrome").split()
            wid = wids[0] if wids else None
        if not wid:
            return False, {"reason": "no_chrome_window"}

        # 维度1: 标题
        found, kw, title = self.detect_by_title(wid)
        if found:
            self._last_result = {
                "method": "title",
                "keyword": kw,
                "title": title,
                "window_id": wid,
                "timestamp": datetime.now().isoformat(),
            }
            return True, self._last_result

        # 维度2: 截图分析
        try:
            raw, W, H, bpl, ps = self._take_screenshot(wid)
        except Exception as e:
            logger.warning("[验证码检测] 截图失败: %s", e)
            return False, {"reason": f"screenshot_failed: {e}"}

        found, info = self.detect_in_page(raw, W, H, bpl, ps)
        info["method"] = "screenshot"
        info["title"] = title
        info["window_id"] = wid
        info["window_size"] = f"{W}x{H}"
        info["timestamp"] = datetime.now().isoformat()

        self._last_result = info
        return found, info

    def get_slider_coords(self, win_x: int, win_y: int, info: dict = None):
        """从检测结果计算滑块屏幕坐标

        Returns:
            (screen_x, screen_y, drag_distance) 或 (None, None, None)
        """
        if info is None:
            info = self._last_result
        if info is None or info.get("method") != "screenshot":
            return None, None, None

        track_y = info.get("track_y")
        track_x1 = info.get("track_x1")
        track_w = info.get("track_width")
        if not all([track_y, track_x1, track_w]):
            return None, None, None

        screen_x = win_x + track_x1 + 12  # 滑块在轨左端偏右约12px
        screen_y = win_y + track_y
        drag_dist = track_w - 24  # 拖到轨右端，留余量

        return screen_x, screen_y, drag_dist
