#!/usr/bin/env python3
"""3个关键词搜索+店透视全量导出测试脚本

用法: PYTHONPATH=src .venv/bin/python scripts/run_three_keywords.py
"""

import os
import sys
import time
import logging
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("run_three_keywords")

KEYWORDS = [
    "\u8499\u725b\u4e00\u7c73\u516b\u516b\u5976\u7c89",
    "\u8499\u725b\u4e00\u7c73\u516b\u516b\u8425\u517b\u68d2",
    "\u8499\u725b\u4e00\u7c73\u516b\u516b\u76ca\u751f\u83cc",
]

OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")


def main():
    from services.tagui_crawler import TaguiCrawler

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = {}

    for idx, kw in enumerate(KEYWORDS):
        logger.info("")
        logger.info("#" * 60)
        logger.info("# [%d/3] 开始抓取: %s", idx + 1, kw)
        logger.info("#" * 60)
        logger.info("")

        crawler = TaguiCrawler()
        start = time.time()

        try:
            result = crawler.crawl_keyword(kw)
        except Exception as e:
            logger.exception("关键词 %s 抓取异常", kw)
            result = None

        elapsed = time.time() - start

        if result:
            dest = OUTPUT_DIR / f"\u8499\u725b_{kw}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            try:
                shutil.copy2(result, dest)
                logger.info("[%d/3] ✅ 成功: %s (耗时 %.0f 秒)", idx + 1, dest, elapsed)
                results[kw] = str(dest)
            except Exception:
                logger.info("[%d/3] ✅ 成功: %s (耗时 %.0f 秒, 复制失败)", idx + 1, result, elapsed)
                results[kw] = result
        else:
            logger.error("[%d/3] ❌ 失败: %s (耗时 %.0f 秒)", idx + 1, kw, elapsed)
            results[kw] = None

    logger.info("")
    logger.info("=" * 60)
    logger.info("全部完成!")
    logger.info("=" * 60)
    for kw, path in results.items():
        status = "✅ " + path if path else "❌ 失败"
        logger.info("  %s: %s", kw, status)

    return results


if __name__ == "__main__":
    main()
