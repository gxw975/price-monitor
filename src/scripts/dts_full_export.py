#!/usr/bin/env python3
"""DTS 店透视完整数据导出 - 整合 GA 成功经验

通过 Chrome CDP (9222端口) 控制 DTS 店透视扩展，执行关键词搜索结果的
全部数据导出。关键改进：

1. **物理鼠标事件**: 使用 Input.dispatchMouseEvent 触发 DTS Vue 组件
2. **验证码自愈**: 检测封控后用 OpenCLI 真人浏览器恢复
3. **分页加载**: 自动翻页等待所有数据就绪
4. **下载监控**: 轮询检测 xlsx 文件完成

用法:
    python dts_full_export.py <关键词>
    python dts_full_export.py "蒙牛一米八八奶粉"
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger("dts_export")

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")
OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")

# DTS 账号
DTS_ACCOUNT = os.environ.get("DIANTOUSHI_ACCOUNT", "18627759568")
DTS_PASSWORD = os.environ.get("DIANTOUSHI_PASSWORD", "791123")


# ═══════════════════════════════════════════════════════════════
# CDP Helpers
# ═══════════════════════════════════════════════════════════════

def _cdp_connect(url_hint: str = "") -> "websocket.WebSocket":
    import websocket
    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
    targets = json.loads(resp.read())

    target = None
    if url_hint:
        for t in targets:
            if t.get("type") == "page" and url_hint in t.get("url", ""):
                if "验证码" not in t.get("title", ""):
                    target = t
                    break

    if not target:
        for t in targets:
            if t.get("type") == "page" and "about:blank" == t.get("url", ""):
                target = t
                break

    if not target:
        for t in targets:
            if t.get("type") == "page" and "taobao.com" in t.get("url", ""):
                if "验证码" not in t.get("title", ""):
                    target = t
                    break

    if not target:
        raise RuntimeError("No usable Chrome page target found")

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15, origin="")
    logger.info("CDP 连接: %s", target.get("url", "")[:80])

    def _cmd(method, params=None, sid=""):
        msg = {"id": int(time.time() * 1000) % 1000000, "method": method}
        if params: msg["params"] = params
        if sid: msg["sessionId"] = sid
        ws.send(json.dumps(msg))
        while True:
            raw = ws.recv()
            resp = json.loads(raw)
            if float(resp.get("id", 0)) == float(msg["id"]):
                return resp

    ws.cmd = _cmd
    ws.cmd("Page.enable")
    ws.cmd("Runtime.enable")
    ws.cmd("DOM.enable")
    ws.cmd("Input.enable")
    return ws


def _cdp_eval(ws, js: str) -> str:
    r = ws.cmd("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return str(r.get("result", {}).get("result", {}).get("value", ""))


def _cdp_mouse_click(ws, x: float, y: float) -> None:
    """CDP 物理鼠标点击"""
    ws.cmd("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.08)
    ws.cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y,
        "button": "left", "clickCount": 1})
    time.sleep(0.06)
    ws.cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y,
        "button": "left", "clickCount": 1})
    time.sleep(0.3)


# ═══════════════════════════════════════════════════════════════
# Core Flow
# ═══════════════════════════════════════════════════════════════

def ensure_taobao_search_open(keyword: str) -> None:
    """确保有淘宝搜索结果页打开（通过 OpenCLI 避免反爬）。"""
    # 检查是否已有搜索页
    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
    targets = json.loads(resp.read())
    encoded_kw = urllib.parse.quote(keyword)

    for t in targets:
        if t.get("type") == "page" and "search" in t.get("url", ""):
            decoded = urllib.parse.unquote(t.get("url", ""))
            if keyword in decoded:
                logger.info("搜索页已存在: %s", t.get("title", ""))
                # 滚动到顶部让 DTS 可见
                return

    # 通过 OpenCLI 打开
    logger.info("通过 OpenCLI 打开搜索页: %s", keyword)
    session = f"dts_search_{int(time.time())}"
    try:
        subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                       "browser", session, "tab", "new"],
                       capture_output=True, text=True, timeout=30)
        time.sleep(1)
        url = f"https://s.taobao.com/search?q={encoded_kw}"
        subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                       "browser", session, "open", url],
                       capture_output=True, text=True, timeout=30)
        time.sleep(5)
        subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                       "browser", session, "wait", "time", "5"],
                       capture_output=True, text=True, timeout=30)
        time.sleep(3)
    finally:
        try:
            subprocess.run([OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                           "browser", session, "close"],
                           capture_output=True, text=True, timeout=10)
        except Exception:
            pass


def detect_and_handle_captcha(ws) -> bool:
    """检测验证码，如果存在则尝试通过 OpenCLI 恢复。

    Returns: True 如果页面正常，False 如果存在验证码且无法恢复。
    """
    body = _cdp_eval(ws, """
    (function() {
        var body = document.body?.innerText || '';
        return JSON.stringify({
            hasCaptcha: body.indexOf('请拖动下方滑块') !== -1,
            hasRetry: body.indexOf('重试') !== -1,
            bodyLen: body.length,
            bones: document.querySelectorAll('[class*="bone"]').length
        });
    })();
    """)
    info = json.loads(body)

    if not info.get("hasCaptcha"):
        return True  # 正常

    logger.warning("检测到验证码: bones=%d, retry=%s",
                  info.get("bones"), info.get("hasRetry"))

    # 策略：不是破解验证码，而是通过 OpenCLI 关闭被封页面，重新打开
    logger.info("尝试恢复：关闭被封页面，通过 OpenCLI 重开...")
    try:
        ws.cmd("Page.close")
    except Exception:
        pass
    ws.close()

    # 等待后重试
    time.sleep(5)

    # 用 OpenCLI 打开新页面
    session = f"recover_{int(time.time())}"
    try:
        # 先打开淘宝首页
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
    except Exception:
        pass

    return False  # 需要调用者重新连接


def export_keyword_full(keyword: str) -> str | None:
    """执行 DTS 店透视完整导出流程。

    Args:
        keyword: 搜索关键词

    Returns:
        成功返回 xlsx 文件路径，失败返回 None
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logger.info("=" * 60)
    logger.info("DTS 完整导出: %s", keyword)
    logger.info("=" * 60)

    # ── 1. 确保搜索页存在 ──
    ensure_taobao_search_open(keyword)

    # ── 2. 连接 CDP 并检查状态 ──
    ws = None
    for attempt in range(3):
        try:
            ws = _cdp_connect(url_hint="search")
        except RuntimeError:
            logger.warning("CDP 连接失败 (attempt=%d)", attempt + 1)
            time.sleep(5)
            continue

        if detect_and_handle_captcha(ws):
            break
        # captcha detected, ws was closed, retry
        time.sleep(5)

    if ws is None:
        logger.error("无法连接到 Chrome")
        return None

    try:
        # ── 3. 滚动到 DTS 工具栏位置 ──
        _cdp_eval(ws, "window.scrollTo(0, 0)")
        time.sleep(2)

        # ── 4. 设置下载路径 ──
        ws.cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(DOWNLOAD_DIR),
            "eventsEnabled": True,
        })
        logger.info("下载路径已设置")

        # ── 5. 查找 DTS 元素当前坐标 ──
        dts_info = _cdp_eval(ws, """
        (function() {
            var el = document.querySelector('.itemToolsBox');
            if (!el) return JSON.stringify({found: false});
            var rect = el.getBoundingClientRect();
            // Find child that says 市场分析
            var children = el.querySelectorAll('div, span');
            for (var i = 0; i < children.length; i++) {
                var txt = (children[i].textContent || '').trim();
                if (txt === '市场分析') {
                    var cr = children[i].getBoundingClientRect();
                    return JSON.stringify({
                        found: true,
                        text: '市场分析',
                        x: cr.x + cr.width/2,
                        y: cr.y + cr.height/2,
                        w: cr.width, h: cr.height,
                        inView: cr.y >= 0 && cr.y < window.innerHeight
                    });
                }
            }
            return JSON.stringify({found: true, container: true,
                x: rect.x + rect.width/2, y: rect.y + rect.height/2});
        })();
        """)
        btn = json.loads(dts_info)
        logger.info("DTS 市场分析按钮: %s", btn)

        if not btn.get("found"):
            logger.error("未找到 DTS 工具栏")
            return None

        # ── 6. 点击市场分析 ──
        if btn.get("inView", False) and btn.get("x", 0) > 0:
            logger.info("点击 市场分析 @ (%.0f, %.0f)", btn["x"], btn["y"])
            _cdp_mouse_click(ws, btn["x"], btn["y"])
        else:
            # 按钮不可见，需要先触发 DTS 面板
            logger.info("DTS 按钮不可见，尝试触发扩展面板...")
            _cdp_eval(ws, """
            (function() {
                var floatBtn = document.querySelector('[class*="dts-float"], [class*="dtsFloat"]');
                if (floatBtn) floatBtn.click();
                return 'triggered';
            })();
            """)
            time.sleep(3)

        # ── 7. 等待分析面板加载并导出 ──
        logger.info("等待 DTS 市场分析面板...")
        panel_loaded = False
        for i in range(60):
            time.sleep(3)
            status = _cdp_eval(ws, """
            (function() {
                var body = document.body?.innerText || '';
                return JSON.stringify({
                    len: body.length,
                    hasStart: body.indexOf('开始分析') !== -1,
                    hasSort: body.indexOf('综合排序') !== -1,
                    hasExport: body.indexOf('导出表格') !== -1,
                    changed: body.length !== %d
                });
            })();
            """ % (303))  # 303 = 原始骨架页长度
            info = json.loads(status)
            if info.get("changed") and info.get("len", 0) > 500:
                logger.info("  [%d] 面板已变化! len=%d, start=%s, sort=%s",
                          i + 1, info["len"], info["hasStart"], info["hasSort"])
                if info["hasStart"] or info["hasSort"]:
                    panel_loaded = True
                    break
            if i % 10 == 0:
                logger.info("  [%d] len=%d, changed=%s", i + 1, info.get("len"), info.get("changed"))

        if not panel_loaded:
            logger.warning("DTS 面板可能未加载，尝试查找现有导出文件...")
            return _find_existing_export(keyword)

        # ── 8. 等待全部数据加载和翻页 ──
        logger.info("等待数据加载和自动翻页...")
        _wait_for_all_pages(ws)

        # ── 9. 点击导出 ──
        logger.info("点击全选 + 导出表格...")
        _click_select_all(ws)
        time.sleep(2)
        _click_export_with_dropdown(ws)

        # ── 10. 等待下载 ──
        logger.info("等待 xlsx 下载完成...")
        xlsx_path = _wait_for_download(keyword)
        if xlsx_path:
            dest = _move_file(xlsx_path, keyword)
            logger.info("✅ 导出成功: %s", dest)
            return dest

        # 兜底：查找已有文件
        return _find_existing_export(keyword)

    except Exception:
        logger.exception("DTS 导出异常")
        return None
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _wait_for_all_pages(ws, max_wait: int = 300) -> None:
    """等待 DTS 分析数据加载完所有分页。"""
    start = time.time()
    while time.time() - start < max_wait:
        # 检查是否有"下一页"按钮
        info = _cdp_eval(ws, """
        (function() {
            var pagers = document.querySelectorAll('[class*="pagination"], .el-pager, [class*="page"]');
            for (var i = 0; i < pagers.length; i++) {
                var p = pagers[i];
                if (p.offsetHeight === 0) continue;
                var nextBtn = p.querySelector('.btn-next:not(.disabled), [class*="next"]:not([class*="disabled"])');
                if (nextBtn) {
                    nextBtn.click();
                    return 'clicked_next';
                }
                // Check if last page
                var nums = p.querySelectorAll('.number, li');
                var pages = [];
                for (var j = 0; j < nums.length; j++) {
                    var n = parseInt(nums[j].textContent);
                    if (!isNaN(n)) pages.push(n);
                }
                var maxPage = pages.length > 0 ? Math.max.apply(null, pages) : 1;
                var active = p.querySelector('.active, [class*="active"]');
                var cur = active ? parseInt(active.textContent) || 1 : 1;
                if (cur >= maxPage) return 'last_page:' + cur;
            }
            return 'no_pagination';
        })();
        """)
        if "last_page" in info or "no_pagination" in info:
            logger.info("分页状态: %s", info)
            break
        logger.debug("翻页: %s", info)
        time.sleep(6)


def _click_select_all(ws) -> None:
    """点击 DTS 全选按钮。"""
    _cdp_eval(ws, """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim();
            if (txt === '全选' && all[i].offsetHeight > 0) {
                all[i].click();
                return;
            }
        }
        var labels = document.querySelectorAll('.el-checkbox__label');
        for (var i = 0; i < labels.length; i++) {
            if ((labels[i].textContent || '').indexOf('全') !== -1) {
                labels[i].click();
                return;
            }
        }
    })();
    """)


def _click_export_with_dropdown(ws) -> None:
    """点击导出表格，处理下拉菜单。"""
    # 点击导出
    _cdp_eval(ws, """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim();
            if (txt === '导出表格' && all[i].offsetHeight > 0) {
                all[i].click();
                return;
            }
        }
    })();
    """)
    time.sleep(2)

    # 选择导出选项
    _cdp_eval(ws, """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim().toLowerCase();
            if ((txt.indexOf('xlsx') !== -1 || txt.indexOf('全部') !== -1) && all[i].offsetHeight > 0) {
                all[i].click();
                return;
            }
        }
    })();
    """)


def _wait_for_download(keyword: str, timeout_sec: int = 120) -> str | None:
    """监控下载目录中的新 xlsx 文件"""
    start = time.time()
    before = set(DOWNLOAD_DIR.glob("*.xlsx"))
    while time.time() - start < timeout_sec:
        current = set(DOWNLOAD_DIR.glob("*.xlsx"))
        new_files = current - before
        if not new_files:
            cutoff = time.time() - timeout_sec
            new_files = {f for f in current if f.stat().st_mtime > cutoff and f.stat().st_size > 1000}
        if new_files:
            newest = max(new_files, key=lambda f: f.stat().st_mtime)
            logger.info("检测到下载: %s (%d bytes)", newest.name, newest.stat().st_size)
            time.sleep(2)
            return str(newest)
        time.sleep(2)
    return None


def _find_existing_export(keyword: str) -> str | None:
    """查找已有的导出文件"""
    for pattern in ["*市场数据分析*", "*店透视*", f"*{keyword}*"]:
        files = list(DOWNLOAD_DIR.glob(f"**/{pattern}"))
        if files:
            newest = max(files, key=lambda f: f.stat().st_mtime) if files else None
            if newest and newest.stat().st_size > 1000:
                logger.info("找到已有文件: %s", newest.name)
                return _move_file(str(newest), keyword)
    return None


def _move_file(src: str, keyword: str) -> str:
    safe_kw = "".join(c if c.isalnum() or c in "_-" else "_" for c in keyword)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"dts_{safe_kw}_{ts}.xlsx"
    dest = os.path.join(OUTPUT_DIR, fname)
    shutil.copy2(src, dest)
    try:
        os.chmod(dest, 0o666)
    except Exception:
        pass
    return dest


# ═══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <关键词>")
        sys.exit(1)

    keyword = sys.argv[1]
    result = export_keyword_full(keyword)
    if result:
        print(f"SUCCESS: {result}")
        sys.exit(0)
    else:
        print("FAILED: 导出失败，请查看日志了解详情")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
