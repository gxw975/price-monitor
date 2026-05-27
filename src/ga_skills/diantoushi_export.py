"""淘宝店透视数据导出技能

通过 OpenCLI 控制真实 Chrome 浏览器，在淘宝搜索结果页触发店透视插件，
导出市场分析数据为 .xlsx 文件。

用法:
    python diantoushi_export.py <关键词>
    示例: python diantoushi_export.py 蓝牙耳机
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("diantoushi_export")

SESSION_NAME = "diantoushi_export"
DATA_DOWNLOADS = Path.home() / "Downloads"
DOWNLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
OPENCLI_TIMEOUT = 30
SLEEP_MIN = 1.0
SLEEP_MAX = 3.0
FLOW_TIMEOUT_MINUTES = 10
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL = 5


class TimeoutError(Exception):
    pass


class OpenCLIError(Exception):
    pass


class ExportError(Exception):
    pass


def _run_opencli(args: list[str], timeout: int = OPENCLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    cmd = ["opencli"] + args
    logger.debug("执行命令: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        msg = f"OpenCLI 命令超时 ({timeout}s): {' '.join(cmd)}"
        logger.error("OpenCLI 命令超时: %s", msg)
        raise TimeoutError(msg)
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        msg = f"OpenCLI 命令失败: exit={result.returncode}, 错误={stderr}"
        logger.error("OpenCLI 命令失败: %s", msg)
        raise OpenCLIError(msg)
    if result.stdout.strip():
        logger.debug("命令输出: %s", result.stdout.strip()[:200])
    return result


def _sleep_random(min_sec: float = SLEEP_MIN, max_sec: float = SLEEP_MAX) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def _cleanup_session() -> None:
    try:
        _run_opencli(["browser", SESSION_NAME, "close"], timeout=15)
    except Exception:
        pass


def _signal_handler(signum: int, frame: Any) -> None:
    logger.warning("收到信号 %d，强制清理", signum)
    _cleanup_session()
    sys.exit(1)


def _search_taobao(keyword: str) -> None:
    url = f"https://s.taobao.com/search?q={keyword}"
    _run_opencli(["browser", SESSION_NAME, "open", url])
    _sleep_random()
    _run_opencli(["browser", SESSION_NAME, "wait", "time", "3"])
    _sleep_random(2.0, 4.0)


def _scroll_page() -> None:
    _run_opencli(["browser", SESSION_NAME, "scroll", "down"])
    _sleep_random(1.0, 2.0)
    _run_opencli(["browser", SESSION_NAME, "scroll", "down"])


def _trigger_extension_via_eval() -> bool:
    eval_js = """
    (function() {
        var btn = document.querySelector('[class*="diantoushi"]');
        if (btn) { btn.click(); return 'clicked'; }
        return 'not_found';
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    return "clicked" in result.stdout


def _click_extension_via_browser_action() -> bool:
    try:
        _run_opencli(["browser", SESSION_NAME, "click"], timeout=15)
        return True
    except Exception:
        return False


def _scan_page_for_extension_ui() -> bool:
    eval_js = """
    (function() {
        var els = document.querySelectorAll('[class*="diantoushi"], [id*="diantoushi"], iframe');
        return JSON.stringify({count: els.length, tags: Array.from(els).map(e => e.tagName)});
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    data_str = result.stdout.strip()
    if data_str:
        import json
        data = json.loads(data_str)
        return data.get("count", 0) > 0
    return False


def _click_market_analysis() -> bool:
    eval_js = """
    (function() {
        var all = document.querySelectorAll('a, button, span, div');
        for (var i = 0; i < all.length; i++) {
            if (all[i].textContent && all[i].textContent.includes('市场分析')) {
                all[i].click();
                return 'clicked';
            }
        }
        return 'not_found';
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    return "clicked" in result.stdout


def _wait_for_data_ready() -> bool:
    for i in range(MAX_POLL_ATTEMPTS):
        eval_js = """
        (function() {
            var btn = document.querySelector('[class*="export"], [class*="导出"], button');
            if (btn && btn.textContent && btn.textContent.includes('导出全部')) {
                return 'ready';
            }
            return 'waiting';
        })();
        """
        result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
        if "ready" in result.stdout:
            return True
        time.sleep(POLL_INTERVAL)
    logger.warning("未检测到'导出全部'按钮")
    return False


def _click_export_button() -> bool:
    eval_js = """
    (function() {
        var all = document.querySelectorAll('button, a, [class*="btn"]');
        for (var i = 0; i < all.length; i++) {
            if (all[i].textContent && all[i].textContent.includes('导出全部')) {
                all[i].click();
                return 'clicked';
            }
        }
        return 'not_found';
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    return "clicked" in result.stdout


def _monitor_download(expected_prefix: str = "taobao", timeout_sec: int = 120) -> Optional[str]:
    start = time.time()
    while time.time() - start < timeout_sec:
        files = sorted(
            [f for f in Path(DATA_DOWNLOADS).glob(f"{expected_prefix}*.xlsx")
             if not f.name.endswith(".crdownload")],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if files:
            return str(files[0])
        time.sleep(2)
    return None


def _rename_and_move(downloaded_path: str, keyword: str) -> str:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    safe_keyword = "".join(c if c.isalnum() or c in "_-" else "_" for c in keyword)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    new_name = f"taobao_{safe_keyword}_{timestamp}.xlsx"
    dest = os.path.join(DOWNLOAD_DIR, new_name)
    shutil.move(downloaded_path, dest)
    os.chmod(dest, 0o664)
    return dest


def export(keyword: str) -> Optional[str]:
    """执行淘宝店透视数据导出全流程。"""
    if not keyword or not keyword.strip():
        logger.error("keyword 参数不能为空")
        return None

    keyword = keyword.strip()
    logger.info("========== 开始淘宝店透视数据导出 ==========")
    logger.info("关键词: %s", keyword)
    logger.info("会话名: %s", SESSION_NAME)

    start = time.time()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        logger.info("[1/11] 创建浏览器标签页")
        _run_opencli(["browser", SESSION_NAME, "tab", "new"])
        _sleep_random()

        logger.info("[2/11] 打开淘宝首页")
        _run_opencli(["browser", SESSION_NAME, "open", "https://www.taobao.com"])
        _sleep_random()
        _run_opencli(["browser", SESSION_NAME, "wait", "time", "3"])
        _sleep_random(2.0, 4.0)

        logger.info("[3/11] 搜索关键词")
        _search_taobao(keyword)

        logger.info("[4/11] 等待搜索结果加载")
        _run_opencli(["browser", SESSION_NAME, "wait", "time", "5"])
        _sleep_random(2.0, 4.0)

        logger.info("[5/11] 滚动页面")
        _scroll_page()

        logger.info("[6/11] 触发店透视扩展")
        triggered = _trigger_extension_via_eval()
        if not triggered:
            _click_extension_via_browser_action()
            _scan_page_for_extension_ui()
        _sleep_random(2.0, 3.0)

        logger.info("[7/11] 点击市场分析")
        clicked = _click_market_analysis()
        if not clicked:
            logger.warning("自动点击'市场分析'失败，继续尝试...")
        _sleep_random(2.0, 4.0)

        logger.info("[8/11] 等待数据加载")
        ready = _wait_for_data_ready()
        if not ready:
            logger.warning("未检测到'导出全部'按钮，尝试继续...")
        _sleep_random(1.0, 2.0)

        logger.info("[9/11] 点击导出全部")
        exported = _click_export_button()
        if not exported:
            raise ExportError("导出按钮点击失败")

        logger.info("[10/11] 监控下载完成")
        downloaded = _monitor_download()
        if not downloaded:
            raise ExportError("未检测到下载文件")

        logger.info("[11/11] 重命名并移动文件")
        result_path = _rename_and_move(downloaded, keyword)

        elapsed = time.time() - start
        logger.info("========== 导出完成 (耗时 %.1f 秒) ==========", elapsed)
        logger.info("文件路径: %s", result_path)

        print(f"SUCCESS: {result_path}")
        return result_path

    except OpenCLIError as e:
        logger.error("OpenCLI 错误: %s", e)
    except TimeoutError as e:
        logger.error("超时: %s", e)
    except ExportError as e:
        logger.error("导出流程错误: %s", e)
    except KeyboardInterrupt:
        logger.warning("用户中断")
    except Exception:
        logger.exception("导出流程未预期的异常")
    finally:
        elapsed = time.time() - start
        if elapsed > FLOW_TIMEOUT_MINUTES * 60:
            logger.warning("流程超过 %d 分钟限制", FLOW_TIMEOUT_MINUTES)
        _cleanup_session()

    print("FAILED: 导出失败，请查看日志了解详情")
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <关键词>")
        print(f"示例: python {sys.argv[0]} 蓝牙耳机")
        sys.exit(1)

    keyword = sys.argv[1]
    result = export(keyword)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
