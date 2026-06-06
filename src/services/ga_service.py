"""抓取编排服务

整合纯xdotool物理操作爬虫，提供:
1. 关键词搜索 + DTS店透视导出 + Excel解析 + 入库 (完整流程)
2. SKU 抓取 (待重新设计 — 暂不可用)
3. DTS 导出 (独立步骤，用于兜底)

架构变更 (2026-06):
- 彻底移除 CDP (Chrome DevTools Protocol) 依赖
- 彻底移除 TagUI RPA 依赖
- 改为纯 xdotool 物理操作 + python-xlib 滑块求解
- 数据来源: DTS 店透视 Excel 导出 (唯一通道)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("ga_service")

# ── 新爬虫（纯xdotool） ──
try:
    from services.xdotool_crawler import XdotoolCrawler, get_crawler
    _xdotool_available = True
except ImportError:
    _xdotool_available = False
    logger.warning("xdotool 爬虫不可用")

# ── DTS 解析器 ──
try:
    from services.dts_parser import DtsDataParser, parse_dts_export
    _parser_available = True
except ImportError:
    _parser_available = False
    logger.warning("DTS 解析器不可用")

# ── 商品入库 ──
try:
    from services.product_service import insert_search_results
    _product_service_available = True
except ImportError:
    _product_service_available = False
    logger.warning("商品入库服务不可用")


def run_diantoushi_export(keyword: str) -> str | None:
    """执行淘宝店透视数据导出。

    使用纯 xdotool 物理操作（无 CDP），从搜索结果页触发 DTS 扩展导出。

    Args:
        keyword: 搜索关键词

    Returns:
        成功时返回导出文件路径，失败时返回 None
    """
    if not keyword or not keyword.strip():
        logger.error("关键词不能为空")
        return None

    keyword = keyword.strip()
    logger.info("[DTS导出] 触发店透视导出: keyword=%s", keyword)

    if not _xdotool_available:
        logger.error("[DTS导出] xdotool爬虫不可用")
        return None

    try:
        crawler = get_crawler()
        result = crawler.run_dts_export(keyword)
        if result:
            logger.info("[DTS导出] 成功: %s", result)
        else:
            logger.warning("[DTS导出] 失败")
        return result
    except Exception:
        logger.exception("[DTS导出] 异常")
        return None


def run_sku_crawl(product_id: str, url: str) -> list[dict[str, Any]]:
    """执行淘宝商品 SKU 抓取。

    ⚠️ 待重新设计: SKU 抓取依赖CDP直接操作SKU选择器，
    当前纯xdotool方案无法精确操作页面SKU元素。
    临时方案: 从 DTS 导出数据中获取价格信息替代。

    Args:
        product_id: 商品 ID
        url: 商品详情页链接

    Returns:
        SKU 信息列表（当前返回空列表）
    """
    if not product_id or not url:
        logger.error("product_id 和 url 不能为空")
        return []

    logger.warning(
        "[SKU抓取] SKU抓取功能待重新设计 (纯xdotool方案暂不支持SKU级操作)"
    )
    logger.info(
        "[SKU抓取] product_id=%s — 将依赖DTS导出获取价格数据", product_id
    )

    # TODO: 重新设计 SKU 抓取逻辑
    # 方案1: 通过 xdotool 逐个点击 SKU 选择器，截图识别价格
    # 方案2: 用 DTS 导出替代 SKU 抓取（一揽子获取所有商品价格）
    # 方案3: 使用 GA (Generic Agent) 视觉能力操作 SKU 面板
    return []


def crawl_keyword_products(keyword: str) -> int:
    """搜索关键词并通过DTS导出获取商品数据自动入库。

    新流程（无CDP）:
    1. 确保Chrome运行（无--remote-debugging-port）
    2. 搜索关键词
    3. DTS店透视导出Excel
    4. 解析Excel提取商品数据
    5. 入库

    Args:
        keyword: 搜索关键词

    Returns:
        入库的商品数量
    """
    if not keyword or not keyword.strip():
        logger.error("关键词不能为空")
        return 0

    keyword = keyword.strip()
    logger.info("[关键词搜索] 开始: %s", keyword)

    if not _xdotool_available:
        logger.error("[关键词搜索] xdotool爬虫不可用")
        return 0

    if not _parser_available:
        logger.error("[关键词搜索] DTS解析器不可用")
        return 0

    if not _product_service_available:
        logger.error("[关键词搜索] 商品入库服务不可用")
        return 0

    try:
        # ── 执行完整抓取流程 ──
        crawler = get_crawler()
        result = crawler.crawl_keyword(keyword)

        if not result:
            logger.warning("[关键词搜索] 抓取失败: 未获取到结果")
            return 0

        products = result.get("products", [])
        if not products:
            logger.warning("[关键词搜索] 抓取结果为空: 没有商品数据")
            return 0

        logger.info(
            "[关键词搜索] 抓取了 %d 个商品, 开始入库...", len(products)
        )

        # ── 入库 ──
        count = insert_search_results(keyword, products)
        logger.info("[关键词搜索] 入库完成: %d 个商品", count)
        return count

    except Exception:
        logger.exception("[关键词搜索] 异常")
        return 0
