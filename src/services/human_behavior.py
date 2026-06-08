# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取功能
"""真人操作行为模拟

提供自然的鼠标轨迹、随机滚动、带抖动的延迟等真人行为模拟工具。
纯xdotool实现，不依赖任何自动化框架。

用法:
    from services.human_behavior import HumanBehavior
    hb = HumanBehavior()
    hb.natural_click(500, 300)
"""

from __future__ import annotations

import logging
import math
import os
import random
import subprocess
import time

logger = logging.getLogger("human_behavior")

DISPLAY = os.environ.get("DISPLAY", ":0")
XAUTH = os.environ.get(
    "XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
)

# ── xdotool 环境变量 ──
def _xdotool_env() -> dict:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH
    return env


def _run_xdotool(args: list[str], timeout: int = 10) -> str:
    """执行xdotool命令并返回stdout"""
    env = _xdotool_env()
    r = subprocess.run(
        ["xdotool"] + args,
        env=env, capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip()


class HumanBehavior:
    """真人操作行为模拟器"""

    def __init__(self, display: str = ":0"):
        self.display = display
        self._last_position = (None, None)

    # ── 延迟 ─────────────────────────────────────────────

    def human_delay(self, base: float, jitter: float = 0.3) -> None:
        """带随机抖动的延时。

        Args:
            base: 基础延迟时间（秒）
            jitter: 抖动系数 (0-1)，实际延迟 = base * (1 ± jitter)
        """
        delay = base * (1 + (random.random() - 0.5) * 2 * jitter)
        time.sleep(max(0.05, delay))

    def think_delay(self) -> None:
        """模拟人类思考停顿 (0.5-2.0秒)"""
        time.sleep(0.5 + random.random() * 1.5)

    def browse_delay(self) -> None:
        """模拟浏览停顿 (2-5秒)"""
        time.sleep(2 + random.random() * 3)

    # ── 鼠标操作 ─────────────────────────────────────────

    def move_to(self, x: int, y: int, human_like: bool = True) -> None:
        """移动鼠标到指定坐标。

        Args:
            x, y: 目标屏幕坐标
            human_like: 是否模拟人类轨迹（多段折线 vs 直线）
        """
        if human_like and self._last_position[0] is not None:
            # 从上次位置到目标位置，生成 3-5 个中间点
            lx, ly = self._last_position
            steps = random.randint(3, 5)
            for i in range(1, steps + 1):
                p = i / steps
                mx = int(lx + (x - lx) * p + random.randint(-20, 20))
                my = int(ly + (y - ly) * p + random.randint(-10, 10))
                _run_xdotool(["mousemove", str(mx), str(my)])
                time.sleep(0.02 + random.random() * 0.03)
        else:
            _run_xdotool(["mousemove", str(x), str(y)])
            time.sleep(0.05)

        self._last_position = (x, y)

    def click(self, x: int | None = None, y: int | None = None,
              button: int = 1) -> None:
        """鼠标点击。

        Args:
            x, y: 目标坐标（None则使用当前位置）
            button: 鼠标按键 (1=左键, 2=中键, 3=右键)
        """
        if x is not None and y is not None:
            self.move_to(x, y)
        time.sleep(0.1 + random.random() * 0.2)
        _run_xdotool(["click", str(button)])
        time.sleep(0.2 + random.random() * 0.3)

    def natural_click(self, x: int, y: int, button: int = 1) -> None:
        """自然点击——先移动到目标周围，略停顿后再精准点击"""
        # 先移动到目标附近
        near_x = x + random.randint(-30, 30)
        near_y = y + random.randint(-15, 15)
        self.move_to(near_x, near_y)
        time.sleep(0.15 + random.random() * 0.3)

        # 再精准移动到目标
        self.move_to(x, y)
        time.sleep(0.08 + random.random() * 0.15)

        # 点击
        _run_xdotool(["click", str(button)])
        time.sleep(0.2 + random.random() * 0.3)
        self._last_position = (x, y)

    def double_click(self, x: int, y: int) -> None:
        """双击"""
        self.move_to(x, y)
        time.sleep(0.1)
        _run_xdotool(["click", "1"])
        time.sleep(0.08 + random.random() * 0.1)
        _run_xdotool(["click", "1"])
        time.sleep(0.3)

    # ── 键盘操作 ─────────────────────────────────────────

    def type_text(self, text: str, delay_ms: int = 50) -> None:
        """逐字输入文本（模拟真人打字）。

        Args:
            text: 要输入的文本
            delay_ms: 每个字符间的延迟（毫秒）
        """
        env = _xdotool_env()
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", str(delay_ms), text],
            env=env, capture_output=True, timeout=30,
        )

    def paste_chinese(self, text: str) -> None:
        """通过剪贴板粘贴中文文本（xdotool type不支持中文）。

        Args:
            text: 要粘贴的中文文本
        """
        env = _xdotool_env()
        # 先写入剪贴板
        p = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env,
        )
        p.communicate(input=text.encode("utf-8"), timeout=10)
        time.sleep(0.3)

        # Ctrl+V 粘贴
        _run_xdotool(["key", "ctrl+v"])
        time.sleep(0.5)

    def key_press(self, key: str) -> None:
        """按下单个键。

        Args:
            key: 键名 (Return, Escape, Tab, ctrl+l, alt+F4 等)
        """
        _run_xdotool(["key", key])
        time.sleep(0.3 + random.random() * 0.2)

    # ── 滚动 ─────────────────────────────────────────────

    def scroll_down(self, clicks: int = 3) -> None:
        """向下滚动（模拟鼠标滚轮）。

        Args:
            clicks: 滚轮点击次数（每次 = 1 格）
        """
        for _ in range(clicks):
            _run_xdotool(["click", "5"])  # Button 5 = scroll down
            time.sleep(0.05 + random.random() * 0.08)

    def scroll_up(self, clicks: int = 3) -> None:
        """向上滚动"""
        for _ in range(clicks):
            _run_xdotool(["click", "4"])  # Button 4 = scroll up
            time.sleep(0.05 + random.random() * 0.08)

    def random_scroll(self) -> None:
        """随机滚动（模拟浏览行为）"""
        direction = random.choice(["down", "down", "down", "up"])
        amount = random.randint(1, 8)
        if direction == "down":
            self.scroll_down(amount)
        else:
            self.scroll_up(amount)

    # ── 综合行为 ─────────────────────────────────────────

    def browse_randomly(self, duration: float = 3.0) -> None:
        """随机浏览行为：移动鼠标 + 偶尔滚动

        Args:
            duration: 持续时长（秒）
        """
        start = time.time()
        while time.time() - start < duration:
            action = random.random()
            if action < 0.4:
                # 随机滚动
                self.random_scroll()
            elif action < 0.8:
                # 随机移动鼠标
                dx = random.randint(-200, 200)
                dy = random.randint(-100, 100)
                if self._last_position[0] is not None:
                    nx = max(0, self._last_position[0] + dx)
                    ny = max(0, self._last_position[1] + dy)
                    self.move_to(nx, ny)
            else:
                time.sleep(0.5 + random.random())
