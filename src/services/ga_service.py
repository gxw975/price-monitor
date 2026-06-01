"""GenericAgent 技能调用服务

整合多种抓取方式:
1. CDP 直连 (Chrome 9222端口) - 最快最可靠, 用于 SKU 抓取
2. OpenCLI 命令行 - 用于浏览器会话管理
3. GA agentmain.py - 用于完整 DTS 导出流程
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ga_service")

GA_PYTHON = "/home/lab-admin/GenericAgent/.venv/bin/python"
GA_MAIN = "/home/lab-admin/GenericAgent/agentmain.py"
SKILLS_DIR = Path(__file__).resolve().parent.parent / "ga_skills"

# 导入 CDP 抓取器 (如果可用)
try:
    from services.cdp_crawler import CdpCrawler
    _cdp_available = True
except ImportError:
    _cdp_available = False
    logger.warning("CDP 抓取器不可用，将降级到 OpenCLI 方式")

# 导入 TagUI RPA 抓取器 (如果可用)
try:
    from services.tagui_crawler import crawl_keyword_rpa
    _tagui_available = True
except ImportError:
    _tagui_available = False
    logger.warning("TagUI RPA 抓取器不可用")


def run_diantoushi_export(keyword: str) -> Optional[str]:
    """执行淘宝店透视数据导出。

    优先使用 TagUI RPA (最稳定)，
    失败时降级到 DTS 脚本。

    Args:
        keyword: 搜索关键词

    Returns:
        成功时返回导出文件路径，失败时返回 None
    """
    if not keyword or not keyword.strip():
        logger.error("关键词不能为空")
        return None

    keyword = keyword.strip()
    logger.info("触发店透视导出: keyword=%s", keyword)

    # 优先使用 TagUI RPA (最稳定，支持滑块验证自动处理)
    if _tagui_available:
        logger.info("[优先] 使用 TagUI RPA 抓取: %s", keyword)
        try:
            result = crawl_keyword_rpa(keyword)
            if result:
                logger.info("TagUI RPA 导出成功: %s", result)
                return result
            logger.warning("TagUI RPA 导出失败，降级到 DTS 脚本")
        except Exception:
            logger.exception("TagUI RPA 异常，降级到 DTS 脚本")

    # 降级到 DTS 脚本
    diantoushi_script = SKILLS_DIR / "diantoushi_export.py"

    if not diantoushi_script.exists():
        logger.error("店透视导出脚本不存在: %s", diantoushi_script)
        return None

    fallback_cmd = [
        sys.executable,
        str(diantoushi_script),
        keyword,
    ]

    return _exec_and_parse([], fallback_cmd, keyword)


def run_sku_crawl(product_id: str, url: str) -> list[dict]:
    """执行淘宝商品 SKU 抓取。

    优先使用 CDP 直连方式 (更快更可靠)，
    失败时降级到 OpenCLI 脚本方式。

    Args:
        product_id: 商品 ID
        url: 商品详情页链接

    Returns:
        SKU 信息列表 [{"sku_name": "", "sku_price": 0.0, ...}]
    """
    if not product_id or not url:
        logger.error("product_id 和 url 不能为空")
        return []

    logger.info("触发 SKU 抓取: product_id=%s, url=%s", product_id, url)

    # ── 方式1: CDP 直连抓取 ──
    if _cdp_available:
        try:
            result = _crawl_skus_via_cdp(product_id, url)
            if result:
                logger.info("CDP SKU 抓取成功: %d 条", len(result))
                return result
        except Exception as e:
            logger.warning("CDP SKU 抓取失败，降级到 OpenCLI: %s", e)

    # ── 方式2: OpenCLI 脚本抓取 (兜底) ──
    return _crawl_skus_via_opencli(product_id, url)


def _crawl_skus_via_cdp(product_id: str, url: str) -> list[dict]:
    """通过 OpenCLI 导航到商品页 + CDP 提取 SKU 数据。

    关键经验: CDP Page.navigate 会触发淘宝反爬验证码，
    必须用 OpenCLI 控制真实浏览器导航，再用 CDP 提取数据。

    验证码处理: 如果 OpenCLI 导航的页面被封控，
    自动重新导航（最多3次），每次使用新的浏览器标签。
    """
    import subprocess

    OPENCLI_BIN = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/opencli"
    OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "zu4794g4")

    MAX_RETRIES = 3

    for attempt in range(1, MAX_RETRIES + 1):
        session = f"sku_cdp_{product_id}_{attempt}_{int(time.time())}"

        try:
            # 用 OpenCLI 在真实浏览器中打开新的商品页标签
            logger.info("OpenCLI 导航 [attempt=%d/%d]: url=%s", attempt, MAX_RETRIES, url[:80])

            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "tab", "new"],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(2)

            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "open", url],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(5)

            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "wait", "time", "5"],
                capture_output=True, text=True, timeout=30,
            )
            time.sleep(3)

            # 滚动页面以加载 SKU 区域
            subprocess.run(
                [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                 "browser", session, "scroll", "down"],
                capture_output=True, text=True, timeout=15,
            )
            time.sleep(2)

            # 释放 OpenCLI 会话（保持标签页打开）
            try:
                subprocess.run(
                    [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                     "browser", session, "close"],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

            # ── CDP 连接到刚打开的页面 ──
            crawler = CdpCrawler()
            try:
                crawler.connect_page(url_hint=f"id={product_id}")

                # 检查是否成功连接到目标页面
                detection = crawler.check_bot_detection()
                if detection["is_blocked"]:
                    logger.warning(
                        "[attempt=%d/%d] 页面被封控 (type=%s)，将重试...",
                        attempt, MAX_RETRIES, detection["block_type"]
                    )
                    # 关闭被封页面并重试
                    try:
                        crawler._cmd("Page.close")
                    except Exception:
                        pass
                    crawler.disconnect()
                    time.sleep(5)  # 等待后再试
                    continue

                # 检查页面是否有商品内容
                product = crawler.scrape_product()
                skus = product.get("skus", [])

                if not skus:
                    logger.warning(
                        "[attempt=%d/%d] 未找到SKU数据，页面可能未正常加载",
                        attempt, MAX_RETRIES
                    )
                    crawler.disconnect()
                    time.sleep(3)
                    continue

                # 成功！
                logger.info("SKU 抓取成功 (attempt=%d): %d 条", attempt, len(skus))
                return [
                    {
                        "sku_name": s["sku_name"],
                        "sku_price": s["sku_price"],
                        "unit_price": s.get("unit_price", s["sku_price"]),
                    }
                    for s in skus
                ]
            finally:
                try:
                    crawler.disconnect()
                except Exception:
                    pass

        except subprocess.TimeoutExpired:
            logger.warning("[attempt=%d/%d] OpenCLI 超时", attempt, MAX_RETRIES)
            time.sleep(5)
        except Exception as e:
            logger.warning("[attempt=%d/%d] CDP+OpenCLI 异常: %s", attempt, MAX_RETRIES, e)
            time.sleep(5)
        finally:
            try:
                subprocess.run(
                    [OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
                     "browser", session, "close"],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

    logger.error("SKU 抓取失败: 已重试 %d 次，页面持续被封控", MAX_RETRIES)
    return []


def _crawl_skus_via_opencli(product_id: str, url: str) -> list[dict]:
    """通过 OpenCLI 脚本抓取 SKU (兜底方案)。"""
    sku_script = SKILLS_DIR / "sku_crawler.py"

    if not sku_script.exists():
        logger.error("SKU 抓取脚本不存在: %s", sku_script)
        return []

    cmd = [sys.executable, str(sku_script), str(product_id), url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15 * 60,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )

        output = result.stdout.strip()
        lines = output.splitlines()
        json_start = -1
        json_end = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if json_start == -1 and (stripped.startswith("[") or stripped.startswith("{")):
                json_start = i
                if stripped in ("[]", "{}"):
                    json_end = i
                    break
            elif json_start != -1 and stripped == "]":
                json_end = i
                break

        if json_start != -1 and json_end != -1:
            json_text = "\n".join(lines[json_start:json_end + 1])
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                logger.exception("SKU JSON 解析失败")

        logger.error("SKU 抓取无有效输出: %s", result.stderr[:200] if result.stderr else "")
        return []
    except subprocess.TimeoutExpired:
        logger.error("SKU 抓取超时")
        return []
    except Exception:
        logger.exception("SKU 抓取异常")
        return []


def _quick_login_check(crawler: CdpCrawler) -> bool:
    """轻量登录检查：在当前页面检测，不触发导航避免反爬。"""
    try:
        result = crawler.eval("""
        (function() {
            var body = (document.body?.innerText || '');
            // 已登录标志：有用户名、有"我的淘宝"入口、有"已买到的宝贝"
            var hasMyTaobao = body.indexOf('我的淘宝') !== -1;
            var hasPurchased = body.indexOf('已买到的宝贝') !== -1;
            var hasNickname = !!document.querySelector('.site-nav-user .nickname, .site-nav-login-info-nick');
            // 未登录标志
            var hasLoginBtn = body.indexOf('请登录') !== -1 || body.indexOf('密码登录') !== -1;
            if (hasLoginBtn) return 'not_logged_in';
            if (hasMyTaobao || hasPurchased || hasNickname) return 'logged_in';
            return 'unknown';
        })();
        """)
        logged_in = str(result).strip().strip('"\'') == 'logged_in'
        logger.info("快速登录检查: %s", "已登录" if logged_in else "未登录或未知")
        return logged_in
    except Exception as e:
        logger.warning("快速登录检查异常: %s", e)
        return True  # 不确定时放行


def crawl_keyword_products(keyword: str) -> int:
    """通过 CDP 搜索关键词并提取商品列表自动入库。

    比 DTS 导出更轻量：直接在搜索结果页提取商品卡片数据。

    Args:
        keyword: 搜索关键词

    Returns:
        入库的商品数量
    """
    if not _cdp_available:
        logger.error("CDP 抓取器不可用")
        return 0

    crawler = CdpCrawler()
    try:
        crawler.connect_page(url_hint="taobao.com")

        # 轻量登录检查：在当前页面上检测（不触发导航，避免反爬）
        try:
            logged_in = _quick_login_check(crawler)
            if not logged_in:
                logger.warning("当前页面未检测到登录态，继续尝试搜索...")
        except Exception:
            logger.warning("登录检查异常，跳过检查继续搜索")

        # 搜索并提取
        products = crawler.search_and_extract_products(keyword, max_results=20)

        if not products:
            logger.warning("搜索结果为空")
            return 0

        # 入库
        from services.product_service import insert_search_results
        count = insert_search_results(keyword, products)
        logger.info("关键词搜索入库完成: %d 个商品", count)
        return count

    except Exception:
        logger.exception("CDP 关键词搜索失败")
        return 0
    finally:
        crawler.disconnect()


def _exec_and_parse(
    ga_cmd: list[str],
    fallback_cmd: list[str],
    keyword: str,
) -> Optional[str]:
    stdout = _exec_fallback(fallback_cmd, keyword)
    return _parse_output(stdout)


def _exec_fallback(cmd: list[str], keyword: str) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15 * 60,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("导出超时: keyword=%s", keyword)
        return ""
    except Exception:
        logger.exception("导出异常: keyword=%s", keyword)
        return ""


def _parse_output(stdout: str) -> Optional[str]:
    if not stdout:
        return None

    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("SUCCESS: "):
            path = line.replace("SUCCESS: ", "").strip()
            if os.path.exists(path):
                logger.info("导出成功: %s", path)
                return path

        if line.startswith("FAILED:"):
            logger.error("导出失败: %s", line)
            return None

    return None
