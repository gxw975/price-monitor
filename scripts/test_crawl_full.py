#!/usr/bin/env python3
"""端到端抓取测试脚本 — 纯xdotool物理操作

用法:
    DISPLAY=:0 XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.47UFP3 \
    PYTHONPATH=/home/lab-admin/price-monitor/src \
    python3 /home/lab-admin/price-monitor/scripts/test_crawl_full.py "关键词"

一次运行一个关键词的完整抓取流程（搜索+DTS导出+解析）。
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 确保环境变量
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("XAUTHORITY", "/run/user/1000/.mutter-Xwaylandauth.47UFP3")
os.environ.setdefault("OPENCLI_PROFILE", "zu4794g4")

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 配置日志
LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "test_crawl.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("test_crawl")


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <关键词>")
        sys.exit(1)

    keyword = sys.argv[1]
    start_time = time.time()

    logger.info("=" * 70)
    logger.info("端到端抓取测试开始")
    logger.info("关键词: %s", keyword)
    logger.info("时间: %s", datetime.now().isoformat())
    logger.info("=" * 70)

    try:
        from services.xdotool_crawler import XdotoolCrawler, CrawlError, CaptchaBlockError, LoginRequiredError

        crawler = XdotoolCrawler()

        # ── 检查Chrome是否运行 ──
        wid = crawler._find_chrome_wid()
        if wid:
            logger.info("Chrome已运行: %s", wid)
            crawler._chrome_wid = wid
        else:
            logger.info("Chrome未运行，启动中...")
            if not crawler._start_chrome():
                logger.error("Chrome启动失败")
                sys.exit(1)

        # ── 激活窗口 + 处理弹窗 ──
        crawler._activate_chrome()
        crawler._handle_popups()

        # ── 搜索关键词 ──
        logger.info("--- 阶段1: 搜索关键词 ---")
        crawler.search_keyword(keyword)

        # ── DTS导出 ──
        logger.info("--- 阶段2: DTS导出 ---")
        xlsx_path = crawler.run_dts_export(keyword)
        if not xlsx_path:
            logger.error("DTS导出失败")
            sys.exit(1)

        # ── 解析入库 ──
        logger.info("--- 阶段3: 解析入库 ---")
        from services.dts_parser import DtsDataParser
        parser = DtsDataParser()
        raw_products = parser.parse(xlsx_path)
        products = parser.normalize_products(raw_products)

        elapsed = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ 抓取完成!")
        logger.info("关键词: %s", keyword)
        logger.info("商品数: %d", len(products))
        logger.info("耗时: %d 秒 (%.1f 分钟)", int(elapsed), elapsed / 60)
        logger.info("Excel: %s", xlsx_path)
        logger.info("=" * 70)

        # 打印前10条商品
        logger.info("商品预览（前10条）:")
        for i, p in enumerate(products[:10], 1):
            logger.info("  %d. [%s] %s | ¥%s | 销量%s | %s",
                       i, p.get("product_id", ""),
                       p.get("title", "")[:50],
                       p.get("price", ""),
                       p.get("sales", ""),
                       p.get("shop", "")[:30])

        # 尝试入库
        try:
            from services.product_service import insert_search_results
            count = insert_search_results(keyword, products)
            logger.info("入库: %d 个商品", count)
        except Exception as e:
            logger.warning("入库失败（非致命）: %s", e)

        # 输出JSON结果供脚本解析
        import json
        result = {
            "success": True,
            "keyword": keyword,
            "product_count": len(products),
            "elapsed_seconds": int(elapsed),
            "xlsx_path": xlsx_path,
        }
        print("\n__RESULT__:" + json.dumps(result, ensure_ascii=False))

    except CaptchaBlockError as e:
        logger.error("验证码拦截: %s", e)
        print(f"\n__RESULT__:{{\"success\":false,\"error\":\"captcha_blocked\",\"keyword\":\"{keyword}\"}}")
        sys.exit(1)
    except LoginRequiredError as e:
        logger.error("需要登录: %s", e)
        print(f"\n__RESULT__:{{\"success\":false,\"error\":\"login_required\",\"keyword\":\"{keyword}\"}}")
        sys.exit(1)
    except CrawlError as e:
        logger.error("抓取异常: %s", e)
        print(f"\n__RESULT__:{{\"success\":false,\"error\":\"crawl_error\",\"keyword\":\"{keyword}\",\"detail\":\"{str(e)[:200]}\"}}")
        sys.exit(1)
    except Exception as e:
        logger.exception("未预期异常")
        print(f"\n__RESULT__:{{\"success\":false,\"error\":\"unknown\",\"keyword\":\"{keyword}\",\"detail\":\"{str(e)[:200]}\"}}")
        sys.exit(1)


if __name__ == "__main__":
    main()
