#!/usr/bin/env python3
"""执行3轮完整数据抓取测试 — 纯xdotool物理操作"""
import sys
import os
import time
import json
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.xdotool_crawler import XdotoolCrawler

LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT)
logger = logging.getLogger("crawl_tests")

TEST_KEYWORDS = [
    "一米八八儿童奶粉",
    "蒙牛一米八八营养棒",
    "蒙牛一米八八益生菌",
]

RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "test_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def run_test(keyword: str, round_num: int) -> dict:
    """执行一次完整抓取测试"""
    logger.info("=" * 70)
    logger.info(f"第{round_num}轮测试 — 关键词: {keyword}")
    logger.info("=" * 70)

    result = {
        "keyword": keyword,
        "round": round_num,
        "started_at": datetime.now().isoformat(),
        "success": False,
        "error": None,
        "steps": [],
        "captcha_encounters": 0,
        "products_found": 0,
    }

    crawler = XdotoolCrawler()
    start_time = time.time()

    try:
        crawl_result = crawler.crawl_keyword(keyword)
        elapsed = time.time() - start_time

        logger.info("[结果] 抓取完成: %s", crawl_result)
        result["success"] = True
        result["duration_seconds"] = round(elapsed, 1)
        result["result"] = crawl_result

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("[失败] %s: %s", keyword, e)
        result["success"] = False
        result["error"] = str(e)
        result["duration_seconds"] = round(elapsed, 1)

    result["finished_at"] = datetime.now().isoformat()
    return result


def main():
    logger.info("=" * 70)
    logger.info("开始3轮完整数据抓取测试")
    logger.info(f"关键词: {TEST_KEYWORDS}")
    logger.info("=" * 70)

    all_results = []

    for i, keyword in enumerate(TEST_KEYWORDS, 1):
        logger.info(f"\n\n{'#' * 70}")
        logger.info(f"# 测试 {i}/3: {keyword}")
        logger.info(f"{'#' * 70}\n")

        # 最多重试3次
        for attempt in range(1, 4):
            logger.info(f"[尝试 {attempt}/3] {keyword}")
            result = run_test(keyword, i)
            result["attempt"] = attempt

            if result["success"]:
                all_results.append(result)
                break
            else:
                logger.warning(f"[重试] {keyword} 第{attempt}次失败: {result['error']}")
                if attempt < 3:
                    wait = 30 * attempt
                    logger.info(f"  等待{wait}秒后重试...")
                    time.sleep(wait)

        if not result["success"]:
            all_results.append(result)
            logger.error(f"[放弃] {keyword} 3次尝试均失败")

        # 关键词间间隔
        if i < len(TEST_KEYWORDS):
            interval = 60
            logger.info(f"\n关键词间间隔 {interval}秒...")
            time.sleep(interval)

    # ─── 保存结果 ───
    report_path = RESULTS_DIR / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # ─── 输出总结 ───
    logger.info("\n\n" + "=" * 70)
    logger.info("测试完成 — 总结报告")
    logger.info("=" * 70)
    for r in all_results:
        status = "✅ 成功" if r["success"] else f"❌ 失败: {r.get('error','未知')}"
        logger.info(f"  [{r['round']}] {r['keyword']}: {status} "
                   f"(耗时{r.get('duration_seconds','?')}s)")
    logger.info(f"\n报告: {report_path}")


if __name__ == "__main__":
    main()
