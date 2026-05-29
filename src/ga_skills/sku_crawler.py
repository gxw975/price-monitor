"""淘宝商品 SKU 抓取技能

通过 OpenCLI 控制真实 Chrome 浏览器，访问商品详情页，
识别并点击每个 SKU 选项，抓取 SKU 名称、价格、图片链接，
自动计算单件价格。

用法:
    python sku_crawler.py <product_id> <url>
    示例: python sku_crawler.py 123456 https://item.taobao.com/item.htm?id=123456
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger("sku_crawler")

SESSION_PREFIX = "sku_crawl"
OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
OPENCLI_TIMEOUT = 30
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")
SLEEP_MIN = 1.0
SLEEP_MAX = 3.0
FLOW_TIMEOUT_MINUTES = 10
MAX_SKU_COUNT = 50
SKU_SELECTORS = [
    ".sku-item",
    ".tb-prop",
    '[class*="sku-item"]',
    '[class*="tb-prop"]',
    ".J_TSaleProp",
    '[data-sku-id]',
    ".sku-line .sku-keys .sku-item",
    ".tb-sku li",
]
PRICE_SELECTORS = [
    "#J_StrPrice .tb-rmb-num",
    ".tb-rmb-num",
    ".tm-price",
    ".tm-promo-price .tm-price",
    '[class*="Price"]',
]


class CrawlError(Exception):
    """SKU 抓取过程错误"""


class TimeoutError(Exception):
    """流程超时"""


def _run_opencli(args: Sequence[str], timeout: int = OPENCLI_TIMEOUT) -> subprocess.CompletedProcess[str]:
    cmd = [OPENCLI_BIN, "--profile", OPENCLI_PROFILE] + list(args)
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
        raise CrawlError(msg)

    if result.stdout.strip():
        logger.debug("命令输出: %s", result.stdout.strip()[:200])
    return result


def _sleep_random(min_sec: float = SLEEP_MIN, max_sec: float = SLEEP_MAX) -> None:
    duration = random.uniform(min_sec, max_sec)
    time.sleep(duration)


def _cleanup_session(session: str) -> None:
    try:
        _run_opencli(["browser", session, "close"], timeout=15)
        logger.info("已关闭浏览器会话: %s", session)
    except Exception:
        logger.warning("关闭会话失败: %s，可能已自动清理", session)


def _signal_handler(signum: int, frame: Any) -> None:
    logger.warning("收到信号 %d，正在退出...", signum)
    raise KeyboardInterrupt()


def _extract_unit_info(sku_name: str) -> tuple[int, str]:
    """从 SKU 名称中提取数量信息，计算系数。

    例如:
      "2件装" → (2, "件装")
      "3个装" → (3, "个装")
      "买1送1" → (2, "买送")
      "买一送二" → (3, "买送")
      "5瓶装" → (5, "瓶装")
      "两件套" → (2, "套")
      "双支装" → (2, "支装")
    """
    cn_num_map: dict[str, int] = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }

    patterns: list[tuple[str, int | None, str]] = [
        (r"(\d+)\s*件装", 0, "件装"),
        (r"(\d+)\s*个装", 0, "个装"),
        (r"(\d+)\s*瓶装", 0, "瓶装"),
        (r"(\d+)\s*只装", 0, "只装"),
        (r"(\d+)\s*支装", 0, "支装"),
        (r"(\d+)\s*袋装", 0, "袋装"),
        (r"(\d+)\s*包装", 0, "件"),
        (r"(\d+)\s*片装", 0, "片装"),
        (r"(\d+)\s*套装", 0, "套"),
        (r"(\d+)\s*联装", 0, "联装"),
        (r"(\d+)\s*盒装", 0, "盒装"),
        (r"买\s*(\d+)\s*送\s*(\d+)", None, "买送"),
        (r"买\s*一\s*送\s*一", None, "买送"),
        (r"买\s*一\s*送\s*二", None, "买送"),
        (r"买\s*一\s*送\s*([一二三四五六七八九十])", None, "买送"),
        (r"买\s*([一二三四五六七八九十])\s*送\s*([一二三四五六七八九十])", None, "买送"),
        (r"([一二三四五六七八九十两])\s*件套", None, "套"),
        (r"([一二三四五六七八九十两])\s*双支", None, "支装"),
        (r"([一二三四五六七八九十两])\s*支装", None, "支装"),
        (r"双支装", None, "支装"),
        (r"两件装", None, "件装"),
        (r"三件装", None, "件装"),
        (r"(\d+)\s*件", 0, "件"),
    ]

    for pattern, default_idx, kind_tag in patterns:
        m = re.search(pattern, sku_name)
        if not m:
            continue

        groups = m.groups()

        if pattern == r"买\s*一\s*送\s*一":
            return 2, kind_tag
        if pattern == r"买\s*一\s*送\s*二":
            return 3, kind_tag
        if pattern == r"双支装":
            return 2, kind_tag
        if pattern == r"两件装":
            return 2, kind_tag
        if pattern == r"三件装":
            return 3, kind_tag
        if pattern == r"买\s*一\s*送\s*([一二三四五六七八九十])":
            send_val = cn_num_map.get(groups[0], 1)
            return 1 + send_val, kind_tag
        if pattern == r"买\s*([一二三四五六七八九十])\s*送\s*([一二三四五六七八九十])":
            buy = cn_num_map.get(groups[0], 1)
            send = cn_num_map.get(groups[1], 1)
            return buy + send, kind_tag
        if pattern == r"([一二三四五六七八九十两])\s*件套":
            val = cn_num_map.get(groups[0], 1)
            return val, kind_tag
        if pattern == r"([一二三四五六七八九十两])\s*双支":
            val = cn_num_map.get(groups[0], 1)
            return val, kind_tag
        if pattern == r"([一二三四五六七八九十两])\s*支装":
            val = cn_num_map.get(groups[0], 1)
            return val, kind_tag
        if pattern == r"买\s*(\d+)\s*送\s*(\d+)":
            buy = int(groups[0])
            send = int(groups[1])
            return buy + send, kind_tag
        if default_idx is not None:
            return int(groups[default_idx]), kind_tag

    return 1, ""


def _calc_unit_price(sku_price: float, sku_name: str) -> float:
    """根据 SKU 名称中的数量信息计算单件价格。"""
    qty, _ = _extract_unit_info(sku_name)
    if qty > 1:
        return round(sku_price / qty, 2)
    return sku_price


def _parse_price_text(text: str) -> float:
    """从文本中提取价格数字。"""
    text = text.strip()
    text = re.sub(r"[¥￥\s,，\n]", "", text)
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return 0.0


def _find_sku_elements(session: str, timeout: int = 30) -> list[dict[str, str]]:
    """使用 JS 查找页面上所有 SKU 元素，返回 [{text, selector}] 列表。

    使用多个选择器依次尝试，确保覆盖淘宝不同版本的 SKU 布局。
    已点击过的 SKU 通过 data-sku-crawled 属性标记跳过。
    """
    logger.info("识别 SKU 元素...")

    eval_js = """
    (function() {
        var selectors = %s;
        var results = [];
        var found = {};
        for (var i = 0; i < selectors.length; i++) {
            var els = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < els.length; j++) {
                var el = els[j];
                if (el.getAttribute('data-sku-crawled')) continue;
                var text = (el.textContent || el.innerText || '').trim();
                if (!text || text.length > 80) continue;
                var key = text.substring(0, 30);
                if (found[key]) continue;
                found[key] = true;
                var img = el.querySelector('img');
                var imgSrc = img ? (img.src || img.getAttribute('data-src') || '') : '';
                results.push({
                    text: text,
                    img: imgSrc,
                    selector: selectors[i] + ':nth-child(' + (j + 1) + ')'
                });
            }
        }
        return JSON.stringify(results);
    })();
    """ % json.dumps(SKU_SELECTORS)

    try:
        result = _run_opencli(["browser", session, "eval", eval_js], timeout=timeout)
        data = json.loads(result.stdout.strip())
        logger.info("识别到 %d 个 SKU 选项", len(data))
        return data
    except (json.JSONDecodeError, TimeoutError) as e:
        logger.warning("SKU 识别失败: %s", e)
        return []


def _click_sku(session: str, sku_text: str, sku_selector: str) -> bool:
    """点击单个 SKU 选项。

    使用 eval 执行 JS 来精准点击，并标记为已处理。
    """
    click_js = f"""
    (function() {{
        var sel = {json.dumps(sku_selector)};
        var el = document.querySelector(sel);
        if (el) {{
            el.setAttribute('data-sku-crawled', '1');
            el.click();
            return 'clicked';
        }}
        return 'not_found';
    }})();
    """

    try:
        result = _run_opencli(["browser", session, "eval", click_js], timeout=10)
        return "clicked" in result.stdout
    except Exception:
        logger.warning("SKU 点击失败: %s", sku_text[:30])
        return False


def _get_current_price(session: str) -> float:
    """获取当前页面显示的价格。"""
    eval_js = """
    (function() {
        var selectors = %s;
        for (var i = 0; i < selectors.length; i++) {
            var el = document.querySelector(selectors[i]);
            if (el && el.textContent) {
                var text = el.textContent.trim();
                if (/[\\d]/.test(text)) return text;
            }
        }
        var all = document.body.innerText || '';
        var m = all.match(/[¥￥]\\s*(\\d+(?:\\.\\d+)?)/);
        if (m) return m[0];
        return '0';
    })();
    """ % json.dumps(PRICE_SELECTORS)

    try:
        result = _run_opencli(["browser", session, "eval", eval_js], timeout=10)
        return _parse_price_text(result.stdout.strip())
    except Exception:
        return 0.0


def _get_current_sku_name(session: str) -> str:
    """获取当前已选中的 SKU 名称。"""
    eval_js = """
    (function() {
        var sel = document.querySelector('.tb-selected .sku-name, .sku-item.selected .sku-name, [class*="selected"] .sku-name');
        if (sel && sel.textContent) return sel.textContent.trim();
        var selected = document.querySelector('.tb-selected, .sku-item.selected, [class*="selected"]');
        if (selected && selected.textContent) return selected.textContent.trim();
        return '';
    })();
    """
    try:
        result = _run_opencli(["browser", session, "eval", eval_js], timeout=10)
        return result.stdout.strip()
    except Exception:
        return ""


def _get_current_sku_image(session: str) -> str:
    """获取当前 SKU 对应的图片 URL。"""
    eval_js = """
    (function() {
        var img = document.querySelector('.tb-selected img, .sku-item.selected img');
        if (img) return img.src || img.getAttribute('data-src') || '';
        var mainImg = document.querySelector('#J_ImgBooth, .tb-main-pic img, .gallery-pic img');
        if (mainImg) return mainImg.src || mainImg.getAttribute('data-src') || '';
        return '';
    })();
    """
    try:
        result = _run_opencli(["browser", session, "eval", eval_js], timeout=10)
        return result.stdout.strip()
    except Exception:
        return ""


def crawl_skus(product_id: str, url: str) -> list[dict[str, object]]:
    """抓取指定商品的所有 SKU 信息。

    Args:
        product_id: 商品 ID
        url: 商品详情页链接

    Returns:
        [{"sku_name": "...", "sku_price": 99.0, "unit_price": 49.5, "sku_image_url": "..."}]
    """
    product_id = str(product_id).strip()
    url = str(url).strip()

    if not product_id or not url:
        logger.error("product_id 和 url 参数不能为空")
        return []

    logger.info("=" * 60)
    logger.info("开始 SKU 抓取: product_id=%s", product_id)
    logger.info("商品链接: %s", url)
    logger.info("=" * 60)

    session = f"{SESSION_PREFIX}_{product_id}_{int(time.time())}"
    start_time = time.time()
    sku_results: list[dict[str, object]] = []

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        _run_opencli(["browser", session, "tab", "new"])
        logger.info("[1/6] 已创建浏览器标签页: %s", session)
        _sleep_random()

        _run_opencli(["browser", session, "open", url])
        logger.info("[2/6] 已打开商品链接")
        _sleep_random()

        _run_opencli(["browser", session, "wait", "time", "3"])
        _sleep_random(2.0, 4.0)

        _run_opencli(["browser", session, "scroll", "down"])
        _sleep_random()
        _run_opencli(["browser", session, "scroll", "down"])
        _sleep_random(2.0, 3.0)
        logger.info("[3/6] 已滚动页面到 SKU 区域")

        sku_elements = _find_sku_elements(session)
        if not sku_elements:
            logger.warning("[4/6] 未找到 SKU 元素，尝试无 SKU 单品模式")

            price = _get_current_price(session)
            sku_name = _get_current_sku_name(session) or "默认"
            sku_image = _get_current_sku_image(session)

            if price > 0:
                unit_price = _calc_unit_price(price, sku_name)
                sku_results.append({
                    "sku_name": sku_name,
                    "sku_price": price,
                    "unit_price": unit_price,
                    "sku_image_url": sku_image,
                })
                logger.info("单品模式: %s | ¥%.2f (单件 ¥%.2f)", sku_name, price, unit_price)
            else:
                logger.error("无法获取商品价格")

            _cleanup_session(session)
            return sku_results

        logger.info("[4/6] 开始逐个点击 %d 个 SKU 选项", len(sku_elements))

        for idx, sku_el in enumerate(sku_elements[:MAX_SKU_COUNT], 1):
            elapsed = time.time() - start_time
            if elapsed > FLOW_TIMEOUT_MINUTES * 60:
                logger.warning("流程超时 (%d 分钟)，已处理 %d/%d",
                               FLOW_TIMEOUT_MINUTES, idx - 1, len(sku_elements))
                break

            sku_text = sku_el.get("text", "")
            sku_selector = sku_el.get("selector", "")
            logger.info("  [%d/%d] %s", idx, len(sku_elements), sku_text[:50])

            clicked = _click_sku(session, sku_text, sku_selector)
            if not clicked:
                logger.warning("  点击失败，跳过")
                continue

            _sleep_random(1.5, 2.5)

            price = _get_current_price(session)
            sku_name = _get_current_sku_name(session) or sku_text
            sku_image = _get_current_sku_image(session)
            unit_price = _calc_unit_price(price, sku_name)

            if price <= 0:
                logger.warning("  价格获取失败 (¥%.2f)，跳过", price)
                continue

            sku_results.append({
                "sku_name": sku_name,
                "sku_price": round(price, 2),
                "unit_price": unit_price,
                "sku_image_url": sku_image,
            })
            logger.info("  ✓ %s | ¥%.2f (单件 ¥%.2f)", sku_name[:40], price, unit_price)

        logger.info("[5/6] SKU 抓取完成，共获取 %d 条", len(sku_results))

        _cleanup_session(session)
        logger.info("[6/6] 已关闭浏览器标签页")

    except KeyboardInterrupt:
        logger.warning("用户中断")
        _cleanup_session(session)
    except TimeoutError as e:
        logger.error("超时: %s", e)
        _cleanup_session(session)
    except CrawlError as e:
        logger.error("OpenCLI 错误: %s", e)
        _cleanup_session(session)
    except Exception:
        logger.exception("SKU 抓取未预期的异常")
        _cleanup_session(session)

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("SKU 抓取完成 (耗时 %.1f 秒): %d 条", elapsed, len(sku_results))
    logger.info("=" * 60)

    return sku_results


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python sku_crawler.py <product_id> <url>")
        print("示例: python sku_crawler.py 123456 https://item.taobao.com/item.htm?id=123456")
        sys.exit(1)

    product_id = sys.argv[1]
    url = sys.argv[2]

    results = crawl_skus(product_id, url)
    print(json.dumps(results, ensure_ascii=False, indent=2))

    if results:
        print(f"\nSUCCESS: 抓取到 {len(results)} 个 SKU")
    else:
        print("\nFAILED: 未抓取到 SKU 信息")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
