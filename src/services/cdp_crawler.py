"""CDP 抓取服务 - 基于 GA 成功经验的 Chrome DevTools Protocol 数据采集

核心改进 (vs OpenCLI 方式):
1. 直接通过 CDP WebSocket 控制 Chrome (9223端口  — 带DTS扩展+登录态)
2. 使用 Input.dispatchMouseEvent 模拟物理鼠标点击 (DTS Vue组件必需)
3. 使用 Runtime.evaluate 注入 JS 提取数据 (更快更可靠)
4. 支持新旧淘宝页面结构 (hashed CSS class + data-vid)
5. Browser.setDownloadBehavior 预先配置下载路径

用法:
    from services.cdp_crawler import CdpCrawler
    crawler = CdpCrawler()
    products = crawler.scrape_product_page(product_url)
    crawler.export_dts_search(keyword)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("cdp_crawler")

CDP_HOST = "127.0.0.1"
CDP_PORT = 9223
DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")

# 淘宝 SKU 选择器 (新版本 hashed class)
SKU_VALUE_SELECTORS = [
    '[class*="valueItem--"]',
    '[data-vid]',
    '.sku-item',
    '.tb-prop li[data-value]',
    '[class*="skuItem"]',
]
PRICE_SELECTORS = [
    '[class*="Price--"]',
    '.tb-rmb-num',
    '.tm-price',
    '[class*="priceText"]',
]
TITLE_SELECTORS = [
    '[class*="Title--"]',
    'h1',
    '[class*="ProductName"]',
]


class CdpError(Exception):
    """CDP 操作错误"""


class CdpCrawler:
    """CDP 浏览器抓取器 - 封装 Chrome DevTools Protocol 操作为 Python API"""

    def __init__(self, port: int = CDP_PORT):
        self._port = port
        self._ws = None

    # ── connection management ─────────────────────────────────────

    def _get_targets(self) -> list[dict[str, Any]]:
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{self._port}/json")
        return json.loads(resp.read())

    def connect_page(self, url_hint: str = "") -> None:
        """连接到匹配 URL 的 page target。

        查找优先级:
        1. url_hint 精确匹配的页面（用于连接已由 OpenCLI 打开的页面）
        2. about:blank（干净页面，用于新导航）
        3. taobao.com 首页

        关键：连接已打开的页面时不需要 navigate，避免触发验证码。
        """
        import websocket  # type: ignore[import-untyped]

        targets = self._get_targets()
        target = None

        # Priority 1: exact url_hint match (for reconnecting to OpenCLI-opened pages)
        if url_hint:
            for t in targets:
                if t.get("type") == "page" and url_hint in t.get("url", ""):
                    if "验证码" not in t.get("title", "") and "punish" not in t.get("title", ""):
                        target = t
                        logger.info("CDP 精确匹配: %s", t.get("url", "")[:80])
                        break
            # If URL hint matched a page but it's captcha, log warning
            if not target:
                for t in targets:
                    if t.get("type") == "page" and url_hint in t.get("url", ""):
                        logger.warning("目标页面被封控: %s", t.get("title", ""))

        # Priority 2: about:blank (fallback)
        if not target:
            for t in targets:
                if t.get("type") == "page" and "about:blank" in t.get("url", ""):
                    target = t
                    logger.info("CDP 连接 about:blank")
                    break

        # Priority 3: taobao.com homepage
        if not target:
            for t in targets:
                if t.get("type") == "page" and t.get("url", "").rstrip("/") == "https://www.taobao.com":
                    if "验证码" not in t.get("title", ""):
                        target = t
                        logger.info("CDP 连接 taobao.com 首页")
                        break

        if not target:
            raise CdpError("未找到可用的 Chrome page target")

        self._ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=15, origin=""
        )

        self._cmd("Page.enable")
        self._cmd("Runtime.enable")

    def disconnect(self) -> None:
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _cmd(self, method: str, params: dict | None = None, session_id: str = "") -> dict:
        """发送 CDP 命令并等待响应。"""
        if not self._ws:
            raise CdpError("未连接到 CDP")
        msg: dict = {"id": int(time.time() * 1000) % 1000000, "method": method}
        if params is not None:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        self._ws.send(json.dumps(msg))
        while True:
            raw = self._ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == msg["id"]:
                if "error" in resp:
                    raise CdpError(f"CDP error: {resp['error']}")
                return resp

    def eval(self, js: str) -> Any:
        """在页面执行 JS 并返回结果。"""
        resp = self._cmd("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        return resp.get("result", {}).get("result", {}).get("value")

    # ── navigation ────────────────────────────────────────────────

    def navigate(self, url: str) -> None:
        self._cmd("Page.navigate", {"url": url})
        time.sleep(3)
        self.wait_ready()

    def wait_ready(self, timeout: int = 10) -> None:
        start = time.time()
        while time.time() - start < timeout:
            try:
                state = self.eval("document.readyState")
                if state == "complete":
                    return
            except Exception:
                pass
            time.sleep(1)

    def scroll(self, y: int = 600) -> None:
        self.eval(f"window.scrollTo(0, {y})")
        time.sleep(1.5)

    def set_download_path(self, path: str) -> None:
        self._cmd("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": path,
            "eventsEnabled": True,
        })

    # ── SKU scraping ──────────────────────────────────────────────

    def scrape_product(self) -> dict[str, Any]:
        """从当前产品详情页提取完整商品信息。

        Returns:
            {
                "product_id": "889777175933",
                "title": "...",
                "shop_name": "...",
                "image_url": "...",
                "url": "...",
                "skus": [{"name": "...", "price": 140.0, "original_price": 160.0}]
            }
        """
        # 提取基本信息
        info_js = """
        (function() {
            var url = window.location.href;
            var idMatch = url.match(/id=(\\d+)/);
            var title = document.title.replace(/[-—\\s]*(淘宝网|天猫).*$/, '').trim();

            // 找店铺名
            var shop = '';
            var shopEl = document.querySelector('[class*="shopName"], [class*="ShopName"], [class*="seller"]');
            if (shopEl) shop = (shopEl.textContent || '').trim();

            // 找主图
            var img = document.querySelector('#J_ImgBooth') || document.querySelector('[class*="mainPic"] img, img[src*="img.alicdn.com"]');
            var imgUrl = img ? (img.src || '') : '';

            return JSON.stringify({
                product_id: idMatch ? idMatch[1] : '',
                title: title.substring(0, 200),
                shop: shop.substring(0, 80),
                image: imgUrl,
                url: url
            });
        })();
        """
        info = json.loads(str(self.eval(info_js)))
        product: dict[str, Any] = {
            "product_id": info.get("product_id", ""),
            "title": info.get("title", ""),
            "shop_name": info.get("shop", ""),
            "image_url": info.get("image", ""),
            "url": info.get("url", ""),
        }

        # 滚动到 SKU 区域
        self.scroll(800)

        # 查找 SKU 变体
        variants_js = """
        (function() {
            var skus = [];
            for (var s = 0; s < %s.length; s++) {
                var items = document.querySelectorAll(%s[s]);
                for (var i = 0; i < items.length; i++) {
                    var el = items[i];
                    var vid = el.getAttribute('data-vid');
                    var disabled = el.getAttribute('data-disabled') === 'true';
                    if (!vid || disabled) continue;
                    var nameEl = el.querySelector('span, [class*="Text"]');
                    var name = nameEl ? (nameEl.textContent || '').trim() : (el.textContent || '').trim();
                    skus.push({vid: vid, name: name.substring(0, 80)});
                }
                if (skus.length > 0) break;
            }
            return JSON.stringify(skus);
        })();
        """ % (json.dumps(SKU_VALUE_SELECTORS), json.dumps(SKU_VALUE_SELECTORS))
        variants = json.loads(str(self.eval(variants_js)))

        # 逐个点击获取价格 - 使用 CDP 物理鼠标事件 (GA SOP: Vue组件必须用CDP mouse)
        sku_results: list[dict[str, Any]] = []
        for v in variants[:20]:
            # 方法1: CDP Input.dispatchMouseEvent 物理点击
            try:
                self._cdp_click_element(f'[data-vid="{v["vid"]}"]')
            except Exception as e:
                logger.debug("CDP 物理点击失败，降级到 JS click: %s", e)
                self.eval(f"""
                (function() {{
                    var el = document.querySelector('[data-vid="{v['vid']}"]');
                    if (el) {{ el.click(); }}
                }})();
                """)
            time.sleep(1.5)

            price_js = """
            (function() {
                var area = document.querySelector('[class*="Price--"]');
                if (area) {
                    var txt = (area.textContent || '').trim();
                    var matches = txt.match(/[¥￥]\\s*\\d+(?:\\.\\d+)?/g) || [];
                    return JSON.stringify(matches.slice(0, 3));
                }
                return '[]';
            })();
            """
            prices = json.loads(str(self.eval(price_js)))

            current = 0.0
            original = 0.0
            for p in prices:
                val = float(p.replace('¥', '').replace('￥', '').strip())
                if current == 0:
                    current = val
                elif val != current:
                    original = val

            qty = self._extract_qty(v["name"])
            unit = round(current / qty, 2) if current > 0 and qty > 0 else current

            sku_results.append({
                "sku_name": v["name"],
                "sku_price": current,
                "original_price": original if original != current else current,
                "unit_price": unit,
            })

        product["skus"] = sku_results
        return product

    def _cdp_click_element(self, css_selector: str) -> bool:
        """通过 CDP Input.dispatchMouseEvent 物理点击元素。

        GA SOP 关键: Vue/React 组件必须用物理 CDP 鼠标事件，
        JS dispatchEvent/click() 不会触发响应式事件处理器。

        Returns:
            是否成功点击
        """
        try:
            # 获取 DOM nodeId
            doc = self._cmd("DOM.getDocument", {"depth": -1})
            root_node_id = doc.get("result", {}).get("root", {}).get("nodeId", 0)
            if not root_node_id:
                return False

            query_resp = self._cmd("DOM.querySelector", {
                "nodeId": root_node_id,
                "selector": css_selector,
            })
            node_id = query_resp.get("result", {}).get("nodeId", 0)
            if not node_id:
                logger.debug("CDP click: 未找到元素 %s", css_selector)
                return False

            # 获取元素坐标
            box_resp = self._cmd("DOM.getBoxModel", {"nodeId": node_id})
            model = box_resp.get("result", {}).get("model", {})
            content = model.get("content", [])
            if len(content) < 4:
                return False

            # content = [x1,y1, x2,y2, x3,y3, x4,y4] (四个角的坐标)
            x = (content[0] + content[2] + content[4] + content[6]) / 4
            y = (content[1] + content[3] + content[5] + content[7]) / 4

            logger.debug("CDP click: %s at (%.1f, %.1f)", css_selector, x, y)

            # 发送完整的鼠标点击序列
            self._cmd("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x, "y": y,
                "button": "left",
                "clickCount": 1,
            })
            time.sleep(0.05)
            self._cmd("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x, "y": y,
                "button": "left",
                "clickCount": 1,
            })
            return True
        except Exception as e:
            logger.debug("CDP click 异常: %s", e)
            return False

    @staticmethod
    def _extract_qty(name: str) -> int:
        m = re.search(r'(\d+)\s*(袋|罐|瓶|盒|个|件|支|包)', name)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d+)\s*(袋装|罐装)', name)
        if m:
            return int(m.group(1))
        return 1

    # ── search page scraping ──────────────────────────────────────

    def search_and_extract_products(self, keyword: str, max_results: int = 20) -> list[dict[str, Any]]:
        """从搜索结果页提取商品列表。

        直接解析搜索结果页面的商品卡片。
        """
        url = f"https://s.taobao.com/search?q={urllib.parse.quote(keyword)}"
        self.navigate(url)
        time.sleep(5)
        self.wait_ready(timeout=15)

        # 滚动触发懒加载
        for y in [500, 1000, 1500]:
            self.scroll(y)

        extract_js = f"""
        (function() {{
            var results = [];
            // 淘宝新搜索结果卡片
            var cards = document.querySelectorAll('[class*="Card--doubleCardWrapper"]');
            if (cards.length === 0) {{
                cards = document.querySelectorAll('.doubleCardWrapper--');
            }}
            if (cards.length === 0) {{
                return JSON.stringify({{error: 'no_cards', count: 0}});
            }}

            var card = cards[0];
            var wrappers = card.querySelectorAll('[class*="Content--"]');
            var max = Math.min(wrappers.length, {max_results});

            for (var i = 0; i < max; i++) {{
                var w = wrappers[i];
                var titleEl = w.querySelector('[class*="Title--"]');
                var priceEl = w.querySelector('[class*="Price--"]');
                var salesEl = w.querySelector('[class*="sales--"], [class*="Sales--"], [class*="realSales--"]');
                var shopEl = w.querySelector('[class*="ShopInfo--"], [class*="shopName--"]');
                var linkEl = w.querySelector('a[href*="item.taobao.com"]');

                var title = titleEl ? (titleEl.textContent || '').trim() : '';
                var priceText = priceEl ? (priceEl.textContent || '').trim() : '';
                var priceMatch = priceText.match(/(\\d+(?:\\.\\d+)?)/);
                var price = priceMatch ? parseFloat(priceMatch[1]) : 0;
                var sales = salesEl ? (salesEl.textContent || '').trim() : '';
                var shop = shopEl ? (shopEl.textContent || '').trim() : '';
                var link = linkEl ? linkEl.href : '';

                if (title) {{
                    var idMatch = link.match(/id=(\\d+)/);
                    results.push({{
                        product_id: idMatch ? idMatch[1] : '',
                        title: title,
                        price: price,
                        sales_text: sales,
                        shop: shop,
                        url: link
                    }});
                }}
            }}
            return JSON.stringify({{count: results.length, items: results}});
        }})();
        """
        data = json.loads(str(self.eval(extract_js)))
        items = data.get("items", [])
        logger.info("搜索结果提取: %d 个商品", len(items))
        return items

    def check_login(self) -> bool:
        """检查淘宝是否已登录。"""
        self.navigate("https://i.taobao.com/my_itaobao")
        time.sleep(5)
        result = self.eval("""
        (function() {
            var url = window.location.href;
            var body = (document.body?.textContent || '');
            if (url.indexOf('login.taobao.com') !== -1 || body.indexOf('密码登录') !== -1) {
                return 'not_logged_in';
            }
            return 'logged_in';
        })();
        """)
        return str(result) == "logged_in"

    def check_bot_detection(self) -> dict[str, Any]:
        """检测页面反爬状态。

        Returns:
            {"is_blocked": bool, "block_type": str, ...}
        """
        result = self.eval("""
        (function() {
            var body = document.body?.innerText || '';
            var title = document.title || '';

            // Captcha signs
            var hasVerificationText = body.indexOf('请拖动下方滑块') !== -1 ||
                                      body.indexOf('验证码') !== -1 ||
                                      title.indexOf('验证码') !== -1;
            var hasRetryText = body.indexOf('重试') !== -1;
            var hasPunish = !!document.querySelector('#baxia-punish');

            // Captcha elements (only visible ones)
            var captchaEls = document.querySelectorAll('#nocaptcha, [class*="nc_wrapper"]');
            var captchaVisible = false;
            for (var i = 0; i < captchaEls.length; i++) {
                if (captchaEls[i].offsetHeight > 0) { captchaVisible = true; break; }
            }

            // Bone/skeleton count (loading placeholders = bot detection)
            var bones = document.querySelectorAll('[class*="bone"], [class*="skeleton"]').length;

            // Loading state
            var loading = body.indexOf('加载中') !== -1;

            // Result cards
            var cards = document.querySelectorAll('[class*="Card--"]').length;

            // Determine block type
            var blockType = 'none';
            if (hasVerificationText || hasPunish || captchaVisible) {
                blockType = 'captcha';  // Slider captcha
            } else if (bones > 100 && loading && cards === 0) {
                blockType = 'skeleton';  // Skeleton screen (silent bot block)
            }

            return JSON.stringify({
                blockType: blockType,
                bones: bones,
                captcha: captchaVisible,
                loading: loading,
                cards: cards,
                hasVerificationText: hasVerificationText,
                hasRetryText: hasRetryText,
                hasPunish: hasPunish,
                bodyLen: body.length
            });
        })();
        """)
        info = json.loads(str(result))
        return {
            "is_blocked": info.get("blockType") != "none",
            "block_type": info.get("blockType", "none"),
            "bone_count": info.get("bones", 0),
            "has_captcha": info.get("captcha", False),
            "is_loading": info.get("loading", False),
            "has_results": info.get("cards", 0) > 0,
            "details": info,
        }

    def recover_from_captcha(self, target_url: str) -> bool:
        """验证码恢复：关闭当前 tab，通过真实浏览器重开。

        使用 OpenCLI 控制真实 Chrome 窗口导航到目标 URL，
        绕过 CDP navigate 触发的反爬检测。

        Returns:
            True 如果恢复成功（页面可正常访问）
        """
        import subprocess

        OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
        OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")
        session = f"recover_{int(time.time())}"

        logger.info("验证码恢复: 通过 OpenCLI 重开页面 %s", target_url[:80])

        try:
            # Close current captcha page via CDP
            try:
                self._cmd("Page.close")
                logger.info("已关闭验证码页面")
            except Exception:
                pass

            # Open new tab via OpenCLI
            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "tab", "new"],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(1)

            # Navigate to URL via OpenCLI (real browser, no captcha!)
            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "open", target_url],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(3)

            # Wait for page load
            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "wait", "time", "5"],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(3)

            # Scroll to trigger content load
            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "scroll", "down"],
                capture_output=True, text=True, timeout=15,
            )
            time.sleep(1)

            # Cleanup OpenCLI session (keep tab open)
            try:
                subprocess.run(
                    [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                     "browser", session, "close"],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

            # Reconnect CDP to the newly opened page
            self.disconnect()
            time.sleep(2)
            self.connect_page(url_hint="item.taobao.com")

            # Verify recovery
            detection = self.check_bot_detection()
            if detection["is_blocked"]:
                logger.warning("恢复后仍被封控: type=%s", detection["block_type"])
                return False

            logger.info("验证码恢复成功，页面可正常访问")
            return True

        except Exception as e:
            logger.error("验证码恢复失败: %s", e)
            return False
