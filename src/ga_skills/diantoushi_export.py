"""淘宝店透视数据导出技能

通过 OpenCLI 控制真实 Chrome 浏览器，在淘宝搜索结果页触发店透视插件或直接提取商品数据。
支持两种模式：店透视扩展导出（优先）+ 直接页面数据提取（兜底）。

用法:
    python diantoushi_export.py <关键词>
    示例: python diantoushi_export.py 蓝牙耳机
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import random
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("diantoushi_export")

SESSION_NAME = "diantoushi_export"
CHROME_DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")
DOWNLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
OPENCLI_TIMEOUT = 30
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")
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
    cmd = [OPENCLI_BIN, "--profile", OPENCLI_PROFILE] + args
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
    """打开淘宝搜索结果页。

    直接使用搜索URL访问（淘宝已登录，不触发反爬重定向）。
    """
    from urllib.parse import quote
    url = f"https://s.taobao.com/search?q={quote(keyword)}"
    logger.info("[搜索] 打开搜索: %s", url[:80])
    _run_opencli(["browser", SESSION_NAME, "open", url])
    _sleep_random(3.0, 5.0)
    _run_opencli(["browser", SESSION_NAME, "wait", "time", "8"], timeout=20)
    _sleep_random(3.0, 5.0)


def _scroll_page() -> None:
    _run_opencli(["browser", SESSION_NAME, "scroll", "down"])
    _sleep_random(1.0, 2.0)
    _run_opencli(["browser", SESSION_NAME, "scroll", "down"])


def _trigger_extension_via_eval() -> bool:
    eval_js = """
    (function() {
        var selectors = [
            '[class*="diantoushi"]',
            '[id*="diantoushi"]',
            '.dts-float-btn',
            '.diantoushi-entry',
            '.dts-icon',
            '[class*="dts-"]'
        ];
        for (var s = 0; s < selectors.length; s++) {
            var btn = document.querySelector(selectors[s]);
            if (btn) { btn.click(); return 'clicked:' + selectors[s]; }
        }
        var all = document.querySelectorAll('div,span,button,a,img');
        for (var i = 0; i < all.length; i++) {
            var cls = String(all[i].className || '');
            var txt = (all[i].textContent || '');
            if ((cls.indexOf('diantoushi') !== -1 || cls.indexOf('dts-') !== -1 || cls.indexOf('dts_') !== -1) && all[i].offsetHeight > 0) {
                all[i].click(); return 'clicked:scan';
            }
            if (txt.indexOf('店透视') !== -1 && all[i].offsetHeight > 0) {
                all[i].click(); return 'clicked:text';
            }
        }
        return 'not_found:' + selectors.join(',');
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    stdout = result.stdout.strip()
    if "clicked" in stdout:
        logger.info("触发店透视成功: %s", stdout[:120])
        return True
    logger.warning("未找到店透视UI入口: %s", stdout[:200])
    return False


def _click_extension_via_browser_action() -> bool:
    try:
        _run_opencli(["browser", SESSION_NAME, "click"], timeout=15)
        return True
    except Exception:
        return False


def _scan_page_for_extension_ui() -> dict[str, Any]:
    eval_js = """
    (function() {
        var all = document.querySelectorAll('*');
        var results = [];
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var cls = String(all[i].className || '');
            var txt = (all[i].textContent || '').trim().substring(0, 50);
            if (cls.indexOf('diantoushi') !== -1 || cls.indexOf('dts-') !== -1 || cls.indexOf('dts_') !== -1) {
                results.push({tag: el.tagName, cls: cls.substring(0, 60), text: txt, visible: el.offsetHeight > 0});
            }
            if (txt.indexOf('店透视') !== -1 || txt.indexOf('市场分析') !== -1 || txt.indexOf('导出全部') !== -1) {
                results.push({tag: el.tagName, cls: cls.substring(0, 60), text: txt, visible: el.offsetHeight > 0});
            }
            if (results.length >= 30) break;
        }
        return JSON.stringify({count: results.length, items: results.slice(0, 20)});
    })();
    """
    result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
    data_str = result.stdout.strip()
    if data_str:
        try:
            import json
            data = json.loads(data_str)
            if data.get("count", 0) > 0:
                logger.info("扫描到 %d 个店透视UI元素", data["count"])
                for item in data.get("items", [])[:5]:
                    logger.info("  %s class=%s text=%s visible=%s", item.get("tag"), item.get("cls",""), item.get("text",""), item.get("visible"))
            else:
                logger.warning("页面未检测到任何店透视相关元素")
            return data
        except json.JSONDecodeError:
            logger.warning("扫描结果JSON解析失败: %s", data_str[:200])
    return {"count": 0, "items": []}


def _clear_page_blockers() -> int:
    """为覆盖店透视工具栏的遮挡层设置 pointer-events: none。

    Taobao 反爬会在页面上覆盖 iframe（punish/deny），阻止自动化点击。
    不从 DOM 移除元素（可能破坏扩展逻辑），而是通过 CSS 禁用其鼠标事件。
    """
    cleared = 0
    clear_js = (
        "(function() {"
        " var n = 0;"
        " var iframes = document.querySelectorAll('iframe');"
        " for (var i = 0; i < iframes.length; i++) {"
        "  var src = iframes[i].src || '';"
        "  if (src.indexOf('diantoushi') === -1 && src.indexOf('io.html') === -1) {"
        "   iframes[i].style.setProperty('pointer-events', 'none', 'important');"
        "   iframes[i].style.setProperty('opacity', '0.01', 'important');"
        "   n++;"
        "  }"
        " }"
        " var blockers = document.querySelectorAll('[class*=\"MIDDLEWARE\"], [class*=\"deny\"], [class*=\"punish\"]');"
        " for (var i = 0; i < blockers.length; i++) {"
        "  blockers[i].style.setProperty('pointer-events', 'none', 'important');"
        "  n++;"
        " }"
        " return n;"
        "})()"
    )
    try:
        result = _run_opencli(["browser", SESSION_NAME, "eval", clear_js], timeout=10)
        cleared = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        logger.info("[去遮挡] 禁用了 %d 个遮挡元素的鼠标事件", cleared)
    except Exception as e:
        logger.warning("[去遮挡] 处理失败: %s", e)
    return cleared


def _click_market_analysis() -> bool:
    """点击店透视面板中的「市场分析」入口。

    使用 OpenCLI 原生 click 命令（CDP Input.dispatchMouseEvent），
    确保产生 isTrusted 事件被店透视扩展正确识别。
    """
    _clear_page_blockers()
    _sleep_random(0.5, 1.0)

    try:
        result = _run_opencli(["browser", SESSION_NAME, "click", "--nth", "0", ".item-box"], timeout=15)
        stdout = result.stdout.strip()
        click_data = json.loads(stdout) if stdout else {}
        if click_data.get("clicked"):
            logger.info("点击市场分析成功 (OpenCLI native click)")
            return True
    except Exception as e:
        logger.warning("OpenCLI click .item-box 失败: %s", e)

    try:
        result = _run_opencli(["browser", SESSION_NAME, "click", "--nth", "0", ".itemToolsBox"], timeout=15)
        stdout = result.stdout.strip()
        click_data = json.loads(stdout) if stdout else {}
        if click_data.get("clicked"):
            logger.info("点击市场分析成功 (via .itemToolsBox)")
            return True
    except Exception as e:
        logger.warning("OpenCLI click .itemToolsBox 失败: %s", e)

    logger.warning("所有方式都无法点击'市场分析'入口")
    return False


def _wait_for_market_analysis_panel(timeout_sec: int = 60) -> bool:
    """等待店透视市场分析面板加载完成。

    必须检测到「开始分析」按钮才算面板就绪（不能只靠「导出表格」）。
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            result = _run_opencli(["browser", SESSION_NAME, "eval", (
                "(function() {"
                " var b = document.body.textContent || '';"
                " var hasStart = b.indexOf('开始分析') !== -1;"
                " var hasSort = b.indexOf('综合排序') !== -1 || b.indexOf('销量排序') !== -1;"
                " return JSON.stringify({"
                "  hasStart: hasStart, hasSort: hasSort, len: b.length"
                " });"
                "})()"
            )], timeout=15)
            info = json.loads(result.stdout.strip())
            logger.info("[分析面板] 状态: start=%s sort=%s len=%d",
                       info.get("hasStart"), info.get("hasSort"), info.get("len"))
            if info.get("hasStart") or info.get("hasSort"):
                logger.info("[分析面板] 检测到分析页面已加载")
                _sleep_random(2.0, 4.0)
                return True
        except Exception as e:
            logger.debug("[分析面板] 检测异常: %s", e)
        _sleep_random(2.0, 3.0)
    logger.warning("[分析面板] 超时未检测到分析页面 (%ds)", timeout_sec)
    return False


def _wait_for_data_ready(max_attempts: int = MAX_POLL_ATTEMPTS, interval: int = POLL_INTERVAL) -> bool:
    """等待店透视数据就绪，检测「导出表格」按钮出现。"""
    for i in range(max_attempts):
        eval_js = """
        (function() {
            var all = document.querySelectorAll('*');
            for (var j = 0; j < all.length; j++) {
                var txt = (all[j].textContent || '').trim();
                if (txt === '导出表格' || txt.indexOf('XLSX') !== -1) {
                    return 'ready:' + txt;
                }
            }
            var hasTable = !!document.querySelector('table, [class*="table"], [class*="data"]');
            var hasPage = !!document.querySelector('[class*="pagination"], [class*="page"], .el-pager');
            return 'waiting:' + (hasTable ? 'has_table' : 'no_table') + ':' + (hasPage ? 'has_page' : 'no_page') + ':attempt_' + (i + 1);
        })();
        """
        try:
            result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=15)
            stdout = result.stdout.strip()
            if "ready" in stdout:
                logger.info("检测到导出按钮就绪 (第%d次): %s", i + 1, stdout[:100])
                return True
            logger.debug("等待数据加载 第%d次: %s", i + 1, stdout[:100])
        except Exception:
            pass
        time.sleep(interval)
    logger.warning("超时未检测到'导出表格'按钮 (已等待 %ds)", max_attempts * interval)
    return False


def _click_export_button() -> bool:
    """点击「导出表格」按钮，在下拉菜单中选「xlsx+图片链接」。

    店透视导出流程：右上角「导出表格」→ 下拉菜单 → 「导出表格 xlsx+图片链接」。
    """
    _click_export_dropdown()
    _sleep_random(1.0, 2.0)
    return _click_xlsx_download_option()


def _click_export_dropdown() -> Optional[str]:
    """查找并点击店透视面板中的「导出表格」按钮。"""
    export_js = """
    (function() {
        var all = document.querySelectorAll('button, a, span, div, [class*="btn"], [class*="export"]');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            if (txt === '导出表格') {
                if (el.offsetHeight > 0) {
                    el.click();
                    return 'clicked_export';
                }
            }
        }
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            var cls = String(el.className || '');
            if ((txt.indexOf('导出') !== -1 || cls.indexOf('export') !== -1) && el.offsetHeight > 0) {
                el.click();
                return 'clicked_export_alt';
            }
        }
        return 'not_found';
    })();
    """
    try:
        result = _run_opencli(["browser", SESSION_NAME, "eval", export_js], timeout=10)
        stdout = result.stdout.strip()
        if stdout.startswith("clicked_export"):
            logger.info("点击导出表格按钮成功")
            return "clicked"
        logger.warning("未找到'导出表格'按钮")
        return None
    except Exception as e:
        logger.warning("查找导出按钮失败: %s", e)
        return None


def _click_xlsx_download_option() -> bool:
    """点击下拉菜单中的「导出表格 xlsx+图片链接」选项。"""
    eval_js = """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim().toLowerCase();
            if ((txt.indexOf('xlsx') !== -1 || txt.indexOf('excel') !== -1) && txt.indexOf('图片') !== -1) {
                if (el.offsetHeight > 0 || getComputedStyle(el).display !== 'none') {
                    el.click();
                    return 'clicked_xlsx_pic';
                }
            }
        }
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim().toLowerCase();
            if (txt.indexOf('xlsx') !== -1 || txt.indexOf('excel') !== -1) {
                if (el.offsetHeight > 0 || getComputedStyle(el).display !== 'none') {
                    el.click();
                    return 'clicked_xlsx';
                }
            }
        }
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim().toLowerCase();
            if (txt.indexOf('导出') !== -1 && txt.indexOf('图片') !== -1) {
                if (el.offsetHeight > 0 || getComputedStyle(el).display !== 'none') {
                    el.click();
                    return 'clicked_export_pic';
                }
            }
        }
        return 'not_found';
    })();
    """
    try:
        result = _run_opencli(["browser", SESSION_NAME, "eval", eval_js], timeout=10)
        stdout = result.stdout.strip()
        if "clicked" in stdout:
            logger.info("点击 xlsx+图片链接 下载选项成功")
            return True
    except Exception:
        pass
    logger.warning("未找到 xlsx+图片链接 下载选项")
    return False


def _wait_for_all_pages_loaded(max_wait_seconds: int = 180) -> bool:
    """等待店透视市场分析加载完所有分页数据，自动翻页。"""
    start_time = time.time()
    eval_pagination = (
        "(function() {"
        " var pagers = document.querySelectorAll('[class*=\"pagination\"], [class*=\"page\"], .el-pager');"
        " for (var i = 0; i < pagers.length; i++) {"
        "  var el = pagers[i];"
        "  if (el.offsetHeight <= 0) continue;"
        "  var nums = el.querySelectorAll('.number, li, button, span');"
        "  var pages = [];"
        "  for (var j = 0; j < nums.length; j++) {"
        "   var n = parseInt(nums[j].textContent); if (!isNaN(n)) pages.push(n);"
        "  }"
        "  var maxPage = pages.length > 0 ? Math.max.apply(null, pages) : 0;"
        "  var activeEl = el.querySelector('.active, [class*=\"active\"]');"
        "  var cur = activeEl ? parseInt(activeEl.textContent) || 1 : 1;"
        "  var nextBtn = el.querySelector('.btn-next, [class*=\"next\"], .el-icon-arrow-right');"
        "  var nextDisabled = nextBtn ? (nextBtn.className.indexOf('disabled') !== -1 || nextBtn.disabled) : true;"
        "  return JSON.stringify({cur: cur, max: maxPage, nextDisabled: nextDisabled});"
        " }"
        " return JSON.stringify({cur: 1, max: 1, nextDisabled: true});"
        "})()"
    )
    eval_click_next = (
        "(function() {"
        " var next = document.querySelector('.btn-next:not(.disabled), [class*=\"pagination\"] [class*=\"next\"]:not([class*=\"disabled\"])');"
        " if (next && next.offsetHeight > 0) { next.click(); }"
        "})()"
    )

    while time.time() - start_time < max_wait_seconds:
        try:
            result = _run_opencli(["browser", SESSION_NAME, "eval", eval_pagination], timeout=15)
            info = json.loads(result.stdout.strip())
            if info.get("nextDisabled", True) and info.get("cur", 1) >= info.get("max", 1):
                logger.info("[分页] 所有%d页已加载完成", info.get("max", 1))
                return True
            if not info.get("nextDisabled", True):
                _run_opencli(["browser", SESSION_NAME, "eval", eval_click_next])
                _sleep_random(2.0, 3.0)
            else:
                _sleep_random(2.0)
        except Exception:
            _sleep_random(1.0)
    logger.warning("[分页] 超时未完成所有页的加载")
    return False


def _monitor_download(expected_keyword: str = "", timeout_sec: int = 120) -> Optional[str]:
    """监控 Chrome 下载目录，等待新 xlsx 文件出现。

    店透视导出的文件名格式：{排序}TOP{数量}-市场数据分析-{关键词}_{日期}.xlsx
    """
    start = time.time()
    before_files = set(CHROME_DOWNLOAD_DIR.glob("*.xlsx"))
    while time.time() - start < timeout_sec:
        try:
            current_files = set(CHROME_DOWNLOAD_DIR.glob("*.xlsx"))
            new_files = current_files - before_files
            if not new_files:
                new_files = {f for f in CHROME_DOWNLOAD_DIR.glob("*市场数据分析*.xlsx")
                            if time.time() - f.stat().st_mtime < timeout_sec}
            if new_files:
                newest = max(new_files, key=lambda f: f.stat().st_mtime)
                if newest.stat().st_size > 100:
                    logger.info("[下载监控] 检测到文件: %s (%d bytes)", newest.name, newest.stat().st_size)
                    return str(newest)
        except Exception as e:
            logger.debug("[下载监控] 检测异常: %s", e)
        time.sleep(2)
    logger.warning("[下载监控] 超时未检测到下载文件 (%ds)", timeout_sec)
    return None


def _rename_and_move(downloaded_path: str, keyword: str) -> str:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    dest = os.path.join(DOWNLOAD_DIR, os.path.basename(downloaded_path))
    shutil.move(downloaded_path, dest)
    os.chmod(dest, 0o664)
    return dest


def _check_taobao_login() -> bool:
    """检查当前 Chrome 是否已登录淘宝。"""
    try:
        _run_opencli(["browser", SESSION_NAME, "open", "https://i.taobao.com/my_itaobao"], timeout=20)
        _sleep_random(8.0, 10.0)
        result = _run_opencli(["browser", SESSION_NAME, "eval", """
        (function() {
            var url = window.location.href;
            var body = (document.body.textContent || '');
            var isLoginPage = url.indexOf('login.taobao.com') !== -1;
            var hasLoginText = body.indexOf('密码登录') !== -1 || body.indexOf('短信登录') !== -1;
            var hasNickname = body.indexOf('giftboy') !== -1;
            if (isLoginPage || hasLoginText) return 'not_logged_in';
            if (hasNickname) return 'logged_in';
            return 'unknown';
        })()
        """], timeout=10)
        stdout = result.stdout.strip().strip("'\"") if result.stdout else ""
        is_logged_in = stdout == "logged_in"
        logger.info("[登录检测] 淘宝登录状态: %s (raw=%s)", "已登录" if is_logged_in else "未登录", stdout)
        return is_logged_in
    except Exception as e:
        logger.warning("[登录检测] 检查失败: %s", e)
        return False


_DIANTOUSHI_API_URL = "https://diantoushi.com/user/login"


def _ensure_dts_login() -> bool:
    """确保店透视扩展已登录。

    通过 CDP 检查扩展的 chrome.storage.local 中是否有有效 token，
    如果没有则调用店透视 API 登录并注入 token。

    Returns:
        True if login successful or already logged in.
    """
    import websocket

    extension_id = "ppgdlgnehnajbbngnohepfigdmjbdpfb"
    account = os.environ.get("DIANTOUSHI_ACCOUNT", "18627759568")
    password = os.environ.get("DIANTOUSHI_PASSWORD", "791123")

    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9222/json")
        targets = json.loads(resp.read())
    except Exception as e:
        logger.error("[DTS登录] 无法连接 CDP: %s", e)
        return False

    sw_target = next(
        (t for t in targets if t.get("type") == "service_worker" and extension_id in t.get("url", "")),
        None,
    )
    if not sw_target:
        has_taobao_page = any("taobao" in t.get("url", "") for t in targets if t.get("type") == "page")
        if not has_taobao_page:
            logger.info("[DTS登录] SW 未找到，尝试打开页面激活扩展")
            _run_opencli(["browser", SESSION_NAME, "open", "https://www.taobao.com"], timeout=20)
            time.sleep(8)
            try:
                resp = urllib.request.urlopen("http://127.0.0.1:9222/json")
                targets = json.loads(resp.read())
            except Exception:
                pass
            sw_target = next(
                (t for t in targets if t.get("type") == "service_worker" and extension_id in t.get("url", "")),
                None,
            )
    if not sw_target:
        logger.error("[DTS登录] 店透视 Service Worker 未找到")
        return False

    ws_url = sw_target["webSocketDebuggerUrl"]
    try:
        ws = websocket.create_connection(ws_url, timeout=10, origin="")
    except Exception as e:
        logger.error("[DTS登录] 连接 SW 失败: %s", e)
        return False

    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": """new Promise(function(resolve){
                    chrome.storage.local.get(['token','online'], function(data){
                        resolve(JSON.stringify(data));
                    });
                })""",
                "returnByValue": True,
                "awaitPromise": True,
            },
        }))
        raw = json.loads(ws.recv())
        val = raw.get("result", {}).get("result", {}).get("value", "{}")
        storage = json.loads(val)
        existing_token = storage.get("token", "")

        if existing_token and storage.get("online"):
            logger.info("[DTS登录] 已有有效 token，跳过登录")
            return True

        logger.info("[DTS登录] 无有效 token，开始登录...")

        login_data = urllib.parse.urlencode({"mobile": account, "password": password}).encode()
        req = urllib.request.Request(_DIANTOUSHI_API_URL, data=login_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as r:
            login_resp = json.loads(r.read().decode())

        if login_resp.get("status") != 0:
            logger.error("[DTS登录] API 登录失败: %s", login_resp.get("message"))
            return False

        token = login_resp["extData"]["token"]
        logger.info("[DTS登录] API 登录成功, token=%s...", token[:10])

        ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": f"""new Promise(function(resolve){{
                    chrome.storage.local.set({{
                        token: '{token}',
                        user: JSON.stringify({{mobile:'{account}',id:{login_resp['extData'].get('id', 0)}}}),
                        online: true
                    }}, function(){{
                        resolve('token_set');
                    }});
                }})""",
                "returnByValue": True,
                "awaitPromise": True,
            },
        }))
        ws.recv()
        logger.info("[DTS登录] Token 已注入 chrome.storage.local")
        return True

    except Exception as e:
        logger.error("[DTS登录] 登录流程异常: %s", e)
        return False
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _extract_products_from_page(keyword: str, skip_page1_nav: bool = False) -> Optional[str]:
    """直接从淘宝搜索结果页提取商品数据，生成 CSV 文件。

    不依赖店透视扩展，直接通过 JS 提取搜索结果的商品标题、价格、销量等信息。
    """
    logger.info("[直接提取] 开始从搜索结果页提取商品数据, skip_page1=%s", skip_page1_nav)

    extract_js = """
    (function() {
        var items = [];
        var cards = document.querySelectorAll('[class*="Card--doubleCardWrapper"]');
        if (cards.length === 0) {
            cards = document.querySelectorAll('.doubleCardWrapper--');
        }
        if (cards.length === 0) {
            var allDivs = document.querySelectorAll('div');
            for (var i = 0; i < allDivs.length; i++) {
                var cls = String(allDivs[i].className || '');
                if (cls.indexOf('Card--') !== -1 && cls.indexOf('Wrapper') !== -1) {
                    cards = [allDivs[i]];
                    break;
                }
            }
        }
        if (cards.length === 0) {
            return JSON.stringify({error: 'no_cards', count: 0, items: []});
        }

        var card = cards[0];
        var wrappers = card.querySelectorAll('[class*="Content--"]');

        for (var i = 0; i < wrappers.length; i++) {
            var w = wrappers[i];
            try {
                var titleEl = w.querySelector('[class*="Title--"]');
                var priceEl = w.querySelector('[class*="Price--"]');
                var salesEl = w.querySelector('[class*="sales--"], [class*="Sales--"], [class*="realSales--"]');
                var shopEl = w.querySelector('[class*="ShopInfo--"], [class*="shopName--"]');
                var linkEl = w.querySelector('a[href*="item.taobao.com"]');

                var title = titleEl ? (titleEl.textContent || '').trim() : '';
                var price = priceEl ? (priceEl.textContent || '').trim().replace(/[^0-9.]/g, '') : '';
                var sales = salesEl ? (salesEl.textContent || '').trim().replace(/[^0-9万+]/g, '') : '';
                var shop = shopEl ? (shopEl.textContent || '').trim() : '';
                var link = linkEl ? linkEl.href : '';

                if (title) {
                    items.push({
                        title: title,
                        price: price || '0',
                        sales: sales || '0',
                        shop: shop,
                        link: link
                    });
                }
            } catch(e) {}
            if (items.length >= 60) break;
        }

        return JSON.stringify({error: null, count: items.length, items: items});
    })();
    """

    all_items: list[dict] = []
    if skip_page1_nav:
        try:
            result = _run_opencli(["browser", SESSION_NAME, "eval", extract_js], timeout=20)
            data = json.loads(result.stdout.strip())
            page_items = data.get("items", [])
            logger.info("[直接提取] 当前页获取到 %d 个商品", len(page_items))
            all_items.extend(page_items)
        except Exception as e:
            logger.warning("[直接提取] 当前页提取失败: %s", e)

    start_page = 2 if skip_page1_nav else 1
    for page in range(start_page, 4):
        page_url = f"https://s.taobao.com/search?page={page}&q={keyword}"
        _run_opencli(["browser", SESSION_NAME, "open", page_url])
        _sleep_random(2.0, 4.0)
        _run_opencli(["browser", SESSION_NAME, "wait", "time", "3"])
        _sleep_random(1.0, 2.0)

        try:
            result = _run_opencli(["browser", SESSION_NAME, "eval", extract_js], timeout=20)
            data = json.loads(result.stdout.strip())
            page_items = data.get("items", [])
            logger.info("[直接提取] 第%d页获取到 %d 个商品", page, len(page_items))
            all_items.extend(page_items)
        except Exception as e:
            logger.warning("[直接提取] 第%d页提取失败: %s", page, e)

        if len(all_items) >= 60:
            break

    if not all_items:
        logger.error("[直接提取] 未提取到任何商品数据")
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    safe_keyword = "".join(c if c.isalnum() or c in "_-" else "_" for c in keyword)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(DOWNLOAD_DIR, f"taobao_{safe_keyword}_{timestamp}.csv")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["商品标题", "价格", "销量", "店铺", "链接"])
        for item in all_items:
            writer.writerow([
                item.get("title", ""),
                item.get("price", "0"),
                item.get("sales", "0"),
                item.get("shop", ""),
                item.get("link", ""),
            ])

    os.chmod(csv_path, 0o664)
    logger.info("[直接提取] 成功导出 %d 个商品到 %s", len(all_items), csv_path)
    return csv_path


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

        if not _check_taobao_login():
            msg = "淘宝未登录！请在后台管理「系统设置 → 淘宝登录」中扫码登录后重试"
            logger.error(msg)
            _cleanup_session()
            print(f"FAILED: {msg}")
            return None

        logger.info("[2.5/11] 确保店透视扩展已登录")
        if not _ensure_dts_login():
            logger.warning("[DTS登录] 店透视登录失败，市场分析可能无法获取数据")

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
            logger.warning("JS触发店透视失败，尝试 browser action 方式...")
            _click_extension_via_browser_action()
        _sleep_random(2.0, 3.0)
        logger.info("[6.5/11] 扫描店透视UI元素")
        scan_result = _scan_page_for_extension_ui()
        if scan_result.get("count", 0) == 0:
            logger.warning("未检测到店透视扩展UI，可能扩展未加载或页面不兼容")
            logger.warning("请确认Chrome已安装店透视扩展 (ID: ppgdlgnehnajbbngnohepfigdmjbdpfb)")
        _sleep_random(1.0, 2.0)

        logger.info("[7/11] 点击市场分析")
        clicked = _click_market_analysis()
        if not clicked:
            logger.warning("自动点击'市场分析'失败，继续尝试...")
        _sleep_random(8.0, 12.0)

        logger.info("[7.5/11] 等待市场分析面板加载")
        _wait_for_market_analysis_panel(timeout_sec=60)

        logger.info("[8/11] 等待分析页加载 + 加载所有分页")
        _wait_for_all_pages_loaded(max_wait_seconds=300)

        logger.info("[9/11] 点击导出表格 → xlsx+图片链接")
        exported = _click_export_button()
        if not exported:
            raise ExportError("导出按钮点击失败: 未找到'导出表格 → xlsx+图片链接'")

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

    except ExportError as e:
        logger.error("导出流程错误: %s", e)
        logger.info("页面仍保留搜索结果，尝试直接提取商品数据...")
        fallback_result = _extract_products_from_page(keyword, skip_page1_nav=True)
        _cleanup_session()
        if fallback_result:
            print(f"SUCCESS: {fallback_result}")
            return fallback_result
    except OpenCLIError as e:
        logger.error("OpenCLI 错误: %s", e)
        _cleanup_session()
    except TimeoutError as e:
        logger.error("超时: %s", e)
        _cleanup_session()
    except KeyboardInterrupt:
        logger.warning("用户中断")
        _cleanup_session()
    except Exception:
        logger.exception("导出流程未预期的异常")
        _cleanup_session()
    finally:
        elapsed = time.time() - start
        if elapsed > FLOW_TIMEOUT_MINUTES * 60:
            logger.warning("流程超过 %d 分钟限制", FLOW_TIMEOUT_MINUTES)

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
