"""每日定时 SKU 抓取入口

从 SystemConfig 读取配置，批量抓取已审核商品的 SKU 信息，
发送飞书通知并记录详细日志。

用法:
    python src/scripts/run_sku_crawl.py
    python src/scripts/run_sku_crawl.py --limit 5
    python src/scripts/run_sku_crawl.py --product-id 123456
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

DATABASE_URL = os.getenv("DATABASE_URL", "")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
_SCHEMA = "price_monitor"
ENV = os.getenv("ENV", "production")

DEFAULT_SKU_LIMIT = 10
DEFAULT_SKU_INTERVAL = 120


def _get_conn() -> Any:
    from urllib.parse import parse_qs, urlparse, urlunparse

    parsed = urlparse(DATABASE_URL)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    conn = psycopg2.connect(clean)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


def _setup_logging(date_str: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"sku_crawl_{date_str}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def _read_config() -> dict[str, Any]:
    conn: Any = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM "SystemConfig" ORDER BY id DESC LIMIT 1')
            row = cur.fetchone()
    except psycopg2.Error:
        logging.getLogger("run_sku_crawl").exception("读取 SystemConfig 失败")
        row = None
    finally:
        if conn:
            conn.close()

    config: dict[str, Any] = {
        "sku_crawl_limit": DEFAULT_SKU_LIMIT,
        "sku_crawl_interval": DEFAULT_SKU_INTERVAL,
    }
    if row:
        config["sku_crawl_limit"] = row.get("sku_crawl_limit", DEFAULT_SKU_LIMIT)
        config["sku_crawl_interval"] = row.get("sku_crawl_interval", DEFAULT_SKU_INTERVAL)

    return config


def _send_feishu_notification(result: dict[str, int], failed_list: list[str]) -> None:
    if not FEISHU_WEBHOOK_URL:
        logging.getLogger("run_sku_crawl").warning("FEISHU_WEBHOOK_URL 未配置，跳过通知")
        return

    env_tag = ""
    if ENV == "test":
        env_tag = " 【测试】"
    elif ENV == "staging":
        env_tag = " 【预发】"

    total = result["total"]
    success = result["success"]
    failed = result["failed"]
    skipped = result["skipped"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    status_color = "green" if failed == 0 else "red" if success == 0 else "yellow"

    failed_text = ""
    if failed_list:
        names = "\n".join(f"  • {pid}" for pid in failed_list[:5])
        extra = ""
        if len(failed_list) > 5:
            extra = f"\n  ... 还有 {len(failed_list) - 5} 个"
        failed_text = f"\n\n**失败商品:**\n{names}{extra}"

    card = {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": f"SKU 抓取报告{env_tag}", "tag": "plain_text"},
                "template": status_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**执行时间:** {now_str}\n"
                            f"**总计:** {total} 个商品\n"
                            f"**成功:** {success} 个\n"
                            f"**失败:** {failed} 个\n"
                            f"**跳过:** {skipped} 个（无 SKU 数据）"
                            f"{failed_text}"
                        ),
                    },
                },
                {
                    "tag": "hr",
                },
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": "电商低价监控系统 · SKU 抓取"}
                    ],
                },
            ],
        },
    }

    try:
        data = json.dumps(card).encode("utf-8")
        req = Request(
            FEISHU_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logging.getLogger("run_sku_crawl").info("飞书通知发送成功")
            else:
                logging.getLogger("run_sku_crawl").warning("飞书通知响应: %d", resp.status)
    except URLError:
        logging.getLogger("run_sku_crawl").exception("飞书通知发送失败")
    except Exception:
        logging.getLogger("run_sku_crawl").exception("飞书通知异常")


def run_single_product(product_id: str) -> dict[str, int]:
    logger = logging.getLogger("run_sku_crawl")
    logger.info("单商品 SKU 抓取模式: %s", product_id)

    from services.sku_service import crawl_and_save_skus, TAOBAO_ITEM_URL

    url = TAOBAO_ITEM_URL.format(product_id=product_id)
    count = crawl_and_save_skus(product_id, url)

    result: dict[str, int]
    if count > 0:
        result = {"total": 1, "success": 1, "failed": 0, "skipped": 0}
    elif count == 0:
        result = {"total": 1, "success": 0, "failed": 0, "skipped": 1}
    else:
        result = {"total": 1, "success": 0, "failed": 1, "skipped": 0}

    failed_list: list[str] = [product_id] if result["failed"] > 0 else []

    _send_feishu_notification(result, failed_list)
    return result


def run_sku_crawl(limit_override: int | None = None) -> dict[str, int]:
    logger = logging.getLogger("run_sku_crawl")
    logger.info("=" * 60)
    logger.info("每日 SKU 抓取任务启动")
    logger.info("=" * 60)

    config = _read_config()
    limit = limit_override if limit_override is not None else config["sku_crawl_limit"]

    logger.info(
        "配置: 最大抓取=%d, 间隔=%ds, 环境=%s",
        limit,
        config["sku_crawl_interval"],
        ENV,
    )

    from services.sku_service import (
        SLEEP_BETWEEN_CRAWLS,
        batch_crawl_skus,
    )

    # Use configured interval for SLEEP_BETWEEN_CRAWLS
    import services.sku_service as sksvc
    original_sleep = sksvc.SLEEP_BETWEEN_CRAWLS
    sksvc.SLEEP_BETWEEN_CRAWLS = config["sku_crawl_interval"]

    try:
        result = batch_crawl_skus(limit=limit)
    finally:
        sksvc.SLEEP_BETWEEN_CRAWLS = original_sleep

    failed_list: list[str] = []
    _send_feishu_notification(result, failed_list)

    logger.info("=" * 60)
    logger.info("每日 SKU 抓取任务结束")
    logger.info("=" * 60)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="每日定时 SKU 抓取入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_sku_crawl.py                      # 默认批量抓取
  python run_sku_crawl.py --limit 5            # 限制抓取5个商品
  python run_sku_crawl.py --product-id 123456  # 仅抓取指定商品
        """,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="本次抓取的最大商品数量，覆盖 SystemConfig 配置",
    )
    parser.add_argument(
        "--product-id",
        type=str,
        default=None,
        help="只抓取指定商品的 SKU（测试用）",
    )
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y%m%d")
    _setup_logging(date_str)

    logger = logging.getLogger("run_sku_crawl")

    start = time.time()

    try:
        if args.product_id:
            result = run_single_product(args.product_id)
        else:
            result = run_sku_crawl(limit_override=args.limit)

        elapsed = time.time() - start
        logger.info(
            "任务完成: 耗时 %.1f 秒, 成功=%d, 失败=%d, 跳过=%d",
            elapsed,
            result["success"],
            result["failed"],
            result["skipped"],
        )

    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(130)
    except Exception:
        logger.exception("任务执行异常")
        sys.exit(1)

    sys.exit(0 if result["failed"] == 0 else 1)


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    main()
