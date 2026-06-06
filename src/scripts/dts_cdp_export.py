# DEPRECATED: 此模块依赖CDP远程调试(Chrome --remote-debugging-port)，已被淘宝检测封锁。
# 替代方案: src/services/xdotool_crawler.py (纯xdotool物理操作)
# 保留此文件仅作历史参考，不再被任何生产代码导入。
# 迁移日期: 2026-06-06

"""DTS CDP Export - 基于 GA 成功经验的店透视数据导出

使用 Chrome DevTools Protocol (9223端口) 直接控制可见浏览器，
通过 python-xlib OS级事件模拟物理鼠标点击触发 DTS Vue 组件。

关键经验 (来自 GA dts_export_sop.md):
1. Vue组件需物理CDP鼠标：JS dispatchEvent不触发，必须用 Input.dispatchMouseEvent
2. 先设下载路径：Browser.setDownloadBehavior 必须在点击前设置
3. 全选用JS click有效，翻页用JS click有效
4. DTS导出按钮需要CDP mouse事件序列: mousePressed → mouseMoved → mouseReleased
5. 翻页后需等待DTS重新初始化（至少5秒）

用法:
    python dts_cdp_export.py <关键词>
    python dts_cdp_export.py "蒙牛一米八八奶粉"
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger("dts_cdp_export")

CDP_HOST = "127.0.0.1"
CDP_PORT = 9223
DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"
DTS_EXTENSION_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"
TIMEOUT = 120  # 总超时秒数


# ── websocket helper ──────────────────────────────────────────────

def _ws_send(ws, method: str, params: dict | None = None, session_id: str = "") -> dict:
    """发送 CDP 命令并等待响应。"""
    import websocket  # type: ignore[import-untyped]
    msg: dict = {"id": int(time.time() * 1000) % 1000000, "method": method}
    if params is not None:
        msg["params"] = params
    if session_id:
        msg["sessionId"] = session_id
    ws.send(json.dumps(msg))
    while True:
        raw = ws.recv()
        resp = json.loads(raw)
        if resp.get("id") == msg["id"]:
            return resp
        # else: event/notification, ignore


def _ws_connect(target: dict) -> "websocket.WebSocket":  # type: ignore[type-arg]
    import websocket  # type: ignore[import-untyped]
    ws_url = target["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=10, origin="")
    return ws


def _get_targets() -> list[dict]:
    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
    return json.loads(resp.read())


def _find_page_target(keyword_hint: str = "taobao") -> dict | None:
    """查找匹配的 page target。"""
    targets = _get_targets()
    for t in targets:
        if t.get("type") == "page" and keyword_hint in t.get("url", ""):
            return t
    # fallback: return first page target
    for t in targets:
        if t.get("type") == "page":
            return t
    return None


# ── core flow ──────────────────────────────────────────────────────

def export_keyword(keyword: str) -> str | None:
    """CDP 方式执行店透视数据导出。

    Returns:
        成功时返回 xlsx 文件路径，失败返回 None。
    """
    keyword = keyword.strip()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info("DTS CDP 导出开始: keyword=%s", keyword)
    logger.info("=" * 60)

    start_time = time.time()
    page_target = _find_page_target()
    if not page_target:
        logger.error("未找到可用的 page target")
        return None

    ws = _ws_connect(page_target)
    logger.info("[1] 已连接 CDP: %s", page_target.get("url", "?")[:80])

    try:
        # 启用必要的 CDP 域
        _ws_send(ws, "Page.enable")
        _ws_send(ws, "Runtime.enable")
        _ws_send(ws, "Network.enable")

        # 预先设置下载路径
        _ws_send(ws, "Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(DOWNLOAD_DIR),
            "eventsEnabled": True,
        })
        logger.info("[2] 下载路径已设置: %s", DOWNLOAD_DIR)

        # ── 导航到淘宝搜索页 ──
        search_url = f"https://s.taobao.com/search?q={urllib.parse.quote(keyword)}"
        _ws_send(ws, "Page.navigate", {"url": search_url})
        logger.info("[3] 已导航到搜索页")
        time.sleep(6)
        _wait_page_ready(ws)

        # 检查是否被反爬
        page_info = _get_page_info(ws)
        logger.info("[4] 当前页面: title=%s, url=%s", page_info.get("title", "")[:60], page_info.get("url", "")[:100])

        # ── 检测滑块验证码 ──
        bone_count = _count_bone_elements(ws)
        if bone_count > 100:
            logger.warning("[验证] 检测到反爬验证页面 (boneCount=%d)，尝试滑块...", bone_count)
            if not _solve_captcha_if_present(ws):
                logger.error("验证码处理失败，淘宝可能封控中")
                return None
            time.sleep(5)
            _wait_page_ready(ws)
        elif bone_count > 0:
            logger.info("[验证] boneCount=%d (正常或需登录)", bone_count)

        # ── 激活 DTS 扩展 ──
        logger.info("[5] 激活店透视扩展...")
        _ensure_dts_active(ws)
        time.sleep(3)

        # ── DTS 导出流程 ──
        logger.info("[6] 开始 DTS 导出流程...")
        success = _dts_export_all(ws, keyword)
        if not success:
            logger.error("DTS 导出失败")
            return None

        # ── 等待下载完成 ──
        logger.info("[7] 等待下载完成...")
        xlsx_path = _wait_download(ws, keyword, timeout_sec=60)
        if not xlsx_path:
            logger.error("未检测到下载文件")
            return None

        # ── 移动到项目目录 ──
        dest = _move_to_output(xlsx_path, keyword)
        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("导出成功! 耗时 %.1fs, 文件: %s", elapsed, dest)
        logger.info("=" * 60)
        return dest

    except Exception:
        logger.exception("DTS CDP 导出异常")
        return None
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _wait_page_ready(ws, timeout: int = 10) -> None:
    """等待页面加载完成。"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = _ws_send(ws, "Runtime.evaluate", {
                "expression": "document.readyState",
                "returnByValue": True,
            })
            state = resp.get("result", {}).get("result", {}).get("value", "")
            if state == "complete":
                return
        except Exception:
            pass
        time.sleep(1)


def _get_page_info(ws) -> dict:
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({title: document.title, url: window.location.href})",
            "returnByValue": True,
        })
        return json.loads(resp.get("result", {}).get("result", {}).get("value", "{}"))
    except Exception:
        return {}


def _count_bone_elements(ws) -> int:
    """统计页面中骨架/验证码元素数量，用于判断反爬。"""
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": """
            (function() {
                var count = 0;
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var cls = String(all[i].className || '');
                    var id = String(all[i].id || '');
                    if (cls.indexOf('bone') !== -1 || cls.indexOf('skeleton') !== -1 ||
                        id.indexOf('nocaptcha') !== -1 || cls.indexOf('nc_wrapper') !== -1 ||
                        cls.indexOf('captcha') !== -1 || cls.indexOf('punish') !== -1) {
                        count++;
                    }
                }
                return count;
            })();
            """,
            "returnByValue": True,
        })
        return resp.get("result", {}).get("result", {}).get("value", 0)
    except Exception:
        return 0


def _solve_captcha_if_present(ws) -> bool:
    """检测并尝试处理滑块验证码。"""
    logger.info("[滑块] 检测验证码iframe...")
    try:
        # 获取 frame tree
        resp = _ws_send(ws, "Page.getFrameTree")
        frames = _collect_frames(resp.get("result", {}).get("frameTree", {}))
        logger.info("[滑块] 共 %d 个 frame", len(frames))

        captcha_frame = None
        for f in frames:
            url = f.get("url", "")
            if "punish" in url or "deny" in url or "nocaptcha" in url:
                captcha_frame = f
                break

        if not captcha_frame:
            logger.info("[滑块] 未找到验证码 frame，尝试直接继续")
            return True

        logger.info("[滑块] 找到验证码 frame: %s", captcha_frame.get("url", "")[:100])
        # 滑块逻辑较复杂，这里先返回 False 让上层处理
        return False
    except Exception as e:
        logger.warning("[滑块] 处理异常: %s", e)
        return False


def _collect_frames(node: dict) -> list[dict]:
    frames: list[dict] = []
    if "frame" in node:
        frames.append(node["frame"])
    for child in node.get("childFrames", []):
        frames.extend(_collect_frames(child))
    return frames


def _ensure_dts_active(ws) -> bool:
    """确保店透视扩展面板已显示。检测 .dts-float-btn 等元素。"""
    for attempt in range(10):
        try:
            resp = _ws_send(ws, "Runtime.evaluate", {
                "expression": """
                (function() {
                    var all = document.querySelectorAll('*');
                    var found = [];
                    for (var i = 0; i < all.length; i++) {
                        var cls = String(all[i].className || '');
                        if (cls.indexOf('dts-') !== -1 && all[i].offsetHeight > 0) {
                            found.push({tag: all[i].tagName, cls: cls.substring(0, 60)});
                        }
                    }
                    var hasPopup = !!document.querySelector('[class*="dts-float"]');
                    var hasToolbar = found.length > 0;
                    return JSON.stringify({hasPopup: hasPopup, hasToolbar: hasToolbar, count: found.length});
                })();
                """,
                "returnByValue": True,
            })
            info = json.loads(resp.get("result", {}).get("result", {}).get("value", "{}"))
            logger.info("[DTS检测] 第%d次: popup=%s, toolbar=%s, count=%d",
                       attempt + 1, info.get("hasPopup"), info.get("hasToolbar"), info.get("count"))
            if info.get("hasToolbar", False):
                return True
        except Exception as e:
            logger.debug("[DTS检测] 异常: %s", e)
        time.sleep(2)

    logger.warning("[DTS] 未检测到店透视扩展UI，可能未安装或未激活")
    return False


def _dts_export_all(ws, keyword: str) -> bool:
    """DTS 全部导出流程：点击「导出表格」→ 等待下拉菜单 → 选择导出选项。"""
    logger.info("[DTS导出] 查找导出按钮...")

    # 1. 先尝试点击全选
    _try_click_select_all(ws)
    time.sleep(2)

    # 2. 点击导出表格按钮 - 使用 CDP 物理鼠标
    export_clicked = _click_export_button_cdp(ws)
    if not export_clicked:
        logger.warning("[DTS导出] CDP 点击导出按钮失败，尝试 JS click...")
        _click_export_button_js(ws)
    time.sleep(3)

    # 3. 处理可能出现的下拉菜单
    dropdown_handled = _handle_export_dropdown_cdp(ws)
    if not dropdown_handled:
        logger.warning("[DTS导出] 未检测到下拉菜单，可能直接触发了导出")
    time.sleep(5)

    return True


def _try_click_select_all(ws) -> bool:
    """尝试点击 DTS 的「全选」按钮。"""
    js = """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            if (txt === '全选' && el.offsetHeight > 0) {
                el.click();
                return 'clicked_all';
            }
        }
        // 尝试 el-checkbox label
        var labels = document.querySelectorAll('.el-checkbox__label');
        for (var i = 0; i < labels.length; i++) {
            if ((labels[i].textContent || '').indexOf('全') !== -1) {
                labels[i].click();
                return 'clicked_label';
            }
        }
        return 'not_found';
    })();
    """
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        result = resp.get("result", {}).get("result", {}).get("value", "")
        logger.info("[全选] %s", result)
        return "clicked" in str(result)
    except Exception as e:
        logger.warning("[全选] 失败: %s", e)
        return False


def _click_export_button_cdp(ws) -> bool:
    """通过 CDP 物理鼠标点击「导出表格」按钮。

    使用 DOM.getBoxModel 获取坐标 → Input.dispatchMouseEvent 模拟点击。
    """
    # 先找到导出按钮的坐标
    find_js = """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            if (txt.indexOf('导出表格') !== -1 && el.offsetHeight > 0) {
                el.setAttribute('data-dts-export', '1');
                return 'found';
            }
        }
        // 查找 text-hover 类
        var hovers = document.querySelectorAll('.text-hover');
        for (var i = 0; i < hovers.length; i++) {
            var t = (hovers[i].textContent || '').trim();
            if (t.indexOf('导出') !== -1 && hovers[i].offsetHeight > 0) {
                hovers[i].setAttribute('data-dts-export', '1');
                return 'found_hover';
            }
        }
        return 'not_found';
    })();
    """
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": find_js,
            "returnByValue": True,
        })
        result = resp.get("result", {}).get("result", {}).get("value", "")
        logger.info("[导出按钮] 查找结果: %s", result)
    except Exception:
        pass

    # 获取坐标
    try:
        box_resp = _ws_send(ws, "DOM.getBoxModel", {
            "objectId": None,  # need to use nodeId or selector
        })
    except Exception:
        pass

    # 用 DOM.getDocument + DOM.querySelector 获取元素坐标
    try:
        doc = _ws_send(ws, "DOM.getDocument", {"depth": -1})
        root = doc.get("result", {}).get("root", {})
        node_resp = _ws_send(ws, "DOM.querySelector", {
            "nodeId": root.get("nodeId"),
            "selector": '[data-dts-export="1"]',
        })
        node_id = node_resp.get("result", {}).get("nodeId", 0)
        if node_id:
            box = _ws_send(ws, "DOM.getBoxModel", {"nodeId": node_id})
            model = box.get("result", {}).get("model", {})
            content = model.get("content", [])
            if len(content) >= 4:
                # content[0-3] 是 quad 的四个角 [x1,y1, x2,y2, x3,y3, x4,y4]
                x = (content[0] + content[2]) / 2
                y = (content[1] + content[5]) / 2
                logger.info("[导出按钮] 坐标: x=%.1f, y=%.1f", x, y)

                # 使用 Input.dispatchMouseEvent 模拟点击序列
                _cdp_mouse_click(ws, x, y)
                logger.info("[导出按钮] CDP 物理点击完成")
                return True
    except Exception as e:
        logger.warning("[导出按钮] CDP鼠标点击异常: %s", e)

    return False


def _cdp_mouse_click(ws, x: float, y: float) -> None:
    """通过 CDP Input.dispatchMouseEvent 发送完整的点击序列。"""
    # mousePressed
    _ws_send(ws, "Input.dispatchMouseEvent", {
        "type": "mousePressed",
        "x": x, "y": y,
        "button": "left",
        "clickCount": 1,
    })
    time.sleep(0.1)
    # mouseReleased
    _ws_send(ws, "Input.dispatchMouseEvent", {
        "type": "mouseReleased",
        "x": x, "y": y,
        "button": "left",
        "clickCount": 1,
    })
    time.sleep(0.3)


def _click_export_button_js(ws) -> bool:
    """JS 方式点击导出按钮（兜底）。"""
    js = """
    (function() {
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            if (txt.indexOf('导出表格') !== -1 && el.offsetHeight > 0) {
                el.click();
                return 'clicked';
            }
        }
        return 'not_found';
    })();
    """
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        return "clicked" in str(resp.get("result", {}).get("result", {}).get("value", ""))
    except Exception:
        return False


def _handle_export_dropdown_cdp(ws) -> bool:
    """处理导出下拉菜单：寻找「全部」或「xlsx+图片」选项并点击。"""
    dropdown_js = """
    (function() {
        var all = document.querySelectorAll('*');
        var options = [];
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var txt = (el.textContent || '').trim();
            var cls = String(el.className || '');
            if ((txt.indexOf('全部') !== -1 || txt.indexOf('xlsx') !== -1 || txt.indexOf('Excel') !== -1)
                && el.offsetHeight > 0
                && (cls.indexOf('dropdown') !== -1 || cls.indexOf('menu') !== -1 || cls.indexOf('pop') !== -1 ||
                    cls.indexOf('popper') !== -1 || cls.indexOf('item') !== -1 || cls.indexOf('option') !== -1)) {
                options.push({text: txt.substring(0, 40), cls: cls.substring(0, 40)});
                el.setAttribute('data-dts-dropdown', '1');
            }
        }
        return JSON.stringify({count: options.length, items: options.slice(0, 10)});
    })();
    """
    try:
        resp = _ws_send(ws, "Runtime.evaluate", {
            "expression": dropdown_js,
            "returnByValue": True,
        })
        info = json.loads(resp.get("result", {}).get("result", {}).get("value", "{}"))
        logger.info("[下拉菜单] 找到 %d 个选项", info.get("count", 0))
        for item in info.get("items", []):
            logger.info("  - %s", item)

        if info.get("count", 0) > 0:
            # 点击第一个匹配的选项
            js_click = """
            (function() {
                var el = document.querySelector('[data-dts-dropdown="1"]');
                if (el) { el.click(); return 'clicked'; }
                return 'not_found';
            })();
            """
            click_resp = _ws_send(ws, "Runtime.evaluate", {
                "expression": js_click,
                "returnByValue": True,
            })
            return "clicked" in str(click_resp.get("result", {}).get("result", {}).get("value", ""))
    except Exception as e:
        logger.warning("[下拉菜单] 处理异常: %s", e)
    return False


def _wait_download(ws, keyword: str, timeout_sec: int = 60) -> str | None:
    """等待 xlsx 文件下载完成。"""
    start = time.time()
    before = set(Path(DOWNLOAD_DIR).glob("*.xlsx"))
    while time.time() - start < timeout_sec:
        current = set(Path(DOWNLOAD_DIR).glob("*.xlsx"))
        new_files = current - before
        if not new_files:
            # 也检查最近 60s 内修改的文件
            cutoff = start - 10
            new_files = {f for f in current if f.stat().st_mtime > cutoff}
        if new_files:
            newest = max(new_files, key=lambda f: f.stat().st_mtime)
            size = newest.stat().st_size
            if size > 1000:  # > 1KB
                logger.info("[下载] 检测到文件: %s (%d bytes)", newest.name, size)
                # 等待文件写入完成
                time.sleep(2)
                return str(newest)
        time.sleep(2)
    return None


def _move_to_output(src: str, keyword: str) -> str:
    """移动文件到项目 data/downloads 目录并修复权限。"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_kw = "".join(c if c.isalnum() or c in "_-" else "_" for c in keyword)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"dts_{safe_kw}_{ts}.xlsx"
    dest = os.path.join(OUTPUT_DIR, fname)
    shutil.copy2(src, dest)
    try:
        os.chmod(dest, 0o666)
    except Exception:
        pass
    logger.info("[移动] %s → %s", src, dest)
    return dest


# ── main ───────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <关键词>")
        sys.exit(1)

    keyword = sys.argv[1]
    result = export_keyword(keyword)
    if result:
        print(f"SUCCESS: {result}")
        sys.exit(0)
    else:
        print("FAILED: 导出失败")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
