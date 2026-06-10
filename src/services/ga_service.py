# 已废弃: 2026-06-08 系统改为手动Excel导入模式，不再使用自动抓取功能
"""抓取编排服务（已废弃）

整合纯xdotool物理操作爬虫，提供:
1. 关键词搜索 + DTS店透视导出 + Excel解析 + 入库 (完整流程)
2. SKU 抓取 (待重新设计 — 暂不可用)
3. DTS 导出 (独立步骤，用于兜底)

架构变更 (2026-06):
- 彻底移除 CDP (Chrome DevTools Protocol) 依赖
- 彻底移除 TagUI RPA 依赖
- 改为纯 xdotool 物理操作 + python-xlib 滑块求解
- 数据来源: DTS 店透视 Excel 导出 (唯一通道)

⚠️ 自 2026-06-08 起，本模块所有自动抓取功能已废弃，改为手动 Excel 导入模式。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("ga_service")

# ── 新爬虫（纯xdotool） ── 已废弃
# try:
#     from services.xdotool_crawler import XdotoolCrawler, get_crawler
#     _xdotool_available = True
# except ImportError:
#     _xdotool_available = False
#     logger.warning("xdotool 爬虫不可用")
_xdotool_available = False

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
    """【已废弃】不再支持自动抓取。请使用手动Excel导入。"""
    logger.warning("[DTS导出] 功能已废弃，请使用手动Excel导入")
    return None


def run_sku_crawl(product_id: str, url: str) -> list[dict[str, Any]]:
    """【已废弃】不再支持SKU抓取。"""
    logger.warning("[SKU抓取] 功能已废弃")
    return []


def crawl_keyword_products(keyword: str) -> int:
    """【已废弃】不再支持自动搜索抓取。请使用手动Excel导入。"""
    logger.warning("[关键词搜索] 功能已废弃，请使用手动Excel导入")
    return 0
