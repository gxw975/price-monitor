"""SKU 抓取和数据库存储服务

提供商品 SKU 数据的批量抓取、存储和查询功能。
通过 psycopg2 直接操作 PostgreSQL，调用 GA 技能 sku_crawler 执行浏览器抓取。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("sku_service")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

TAOBAO_ITEM_URL = "https://item.taobao.com/item.htm?id={product_id}"

SLEEP_BETWEEN_CRAWLS = 120
DEFAULT_BATCH_LIMIT = 10
SKU_CRAWL_TIMEOUT = 10 * 60
EXCLUDE_HOURS = 24


def _parse_db_url(url: str) -> tuple[str, str]:
    """解析 DATABASE_URL，分离 schema 参数。"""

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    return clean, schema


def _get_conn() -> Any:
    dsn, schema = _parse_db_url(DATABASE_URL)
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


def get_pending_sku_products(
    exclude_hours: int = EXCLUDE_HOURS,
) -> list[dict[str, str]]:
    """查询所有已审核通过且未加入白名单、最近 N 小时内未抓取过 SKU 的商品。

    Args:
        exclude_hours: 排除最近 N 小时内已抓取过 SKU 的商品，默认 24

    Returns:
        [{"product_id": "...", "title": "...", "url": "..."}]
    """
    conn: Any = None
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.product_id, p.title
                FROM price_monitor."Product" p
                WHERE p.is_approved = TRUE
                  AND p.is_whitelist = FALSE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM price_monitor."ProductSku" s
                      WHERE s.product_id = p.product_id
                        AND s.recorded_at > NOW() - INTERVAL '1 hour' * %s
                  )
                ORDER BY p.last_updated_at DESC
                """,
                (exclude_hours,),
            )
            rows = cur.fetchall()

        products: list[dict[str, str]] = []
        for row in rows:
            pid = row["product_id"]
            products.append({
                "product_id": pid,
                "title": row["title"],
                "url": TAOBAO_ITEM_URL.format(product_id=pid),
            })

        logger.info(
            "查询待抓取 SKU 商品: 共 %d 个 (排除 %d 小时内已抓取)",
            len(products),
            exclude_hours,
        )
        return products

    except psycopg2.Error:
        logger.exception("查询待抓取 SKU 商品失败")
        return []
    finally:
        if conn:
            conn.close()


def crawl_and_save_skus(product_id: str, url: str) -> int:
    """抓取单个商品的 SKU 信息并保存到数据库。

    Args:
        product_id: 商品 ID
        url: 商品详情页链接

    Returns:
        抓取到的 SKU 数量，失败返回 -1
    """
    if not product_id or not url:
        logger.error("product_id 和 url 参数不能为空")
        return -1

    logger.info("开始抓取 SKU: product_id=%s", product_id)

    try:
        from services.ga_service import run_sku_crawl

        skus = run_sku_crawl(product_id, url)
    except ImportError:
        logger.exception("导入 ga_service 失败")
        return -1
    except Exception:
        logger.exception("SKU 抓取异常: product_id=%s", product_id)
        return -1

    if not skus:
        logger.warning("SKU 抓取返回空: product_id=%s", product_id)
        return 0

    logger.info("抓取到 %d 个 SKU: product_id=%s", len(skus), product_id)

    conn: Any = None
    saved = 0
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM price_monitor."ProductSku" WHERE product_id = %s',
                    (product_id,),
                )
                deleted = cur.rowcount
                logger.debug("删除旧 SKU 记录: %d 条", deleted)

            with conn.cursor() as cur:
                for sku in skus:
                    cur.execute(
                        """
                        INSERT INTO price_monitor."ProductSku"
                            (product_id, sku_name, sku_price, unit_price, sku_image_url)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            product_id,
                            sku.get("sku_name", ""),
                            sku.get("sku_price", 0),
                            sku.get("unit_price", 0),
                            sku.get("sku_image_url", ""),
                        ),
                    )
                    saved += 1

        logger.info(
            "SKU 存储完成: product_id=%s, 删除旧 %d 条, 插入新 %d 条",
            product_id,
            deleted,
            saved,
        )
        return saved

    except psycopg2.Error:
        logger.exception("SKU 数据存储失败: product_id=%s", product_id)
        return -1
    finally:
        if conn:
            conn.close()


def batch_crawl_skus(limit: int = DEFAULT_BATCH_LIMIT) -> dict[str, int]:
    """批量抓取 SKU，每次最多处理 limit 个商品。

    每个商品抓取完成后等待 2 分钟以防反爬。

    Args:
        limit: 最多处理的商品数量，默认 10

    Returns:
        {"total": N, "success": N, "failed": N, "skipped": N}
    """
    logger.info("=" * 60)
    logger.info("开始批量 SKU 抓取: 最大数量=%d", limit)
    logger.info("=" * 60)

    products = get_pending_sku_products()

    if not products:
        logger.info("没有需要抓取 SKU 的商品")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    batch = products[:limit]
    total = len(batch)

    result = {"total": total, "success": 0, "failed": 0, "skipped": 0}

    for idx, product in enumerate(batch, 1):
        pid = product["product_id"]
        title = product["title"]
        url = product["url"]

        logger.info("=" * 40)
        logger.info("[%d/%d] 处理商品: %s - %s", idx, total, pid, title[:40])

        count = crawl_and_save_skus(pid, url)

        if count > 0:
            result["success"] += 1
            logger.info("商品 %s 抓取成功: %d 个 SKU", pid, count)
        elif count == 0:
            result["skipped"] += 1
            logger.info("商品 %s 无 SKU 数据", pid)
        else:
            result["failed"] += 1
            logger.error("商品 %s 抓取失败", pid)

        if idx < total:
            logger.info("等待 %d 秒后处理下一个...", SLEEP_BETWEEN_CRAWLS)
            time.sleep(SLEEP_BETWEEN_CRAWLS)

    logger.info("=" * 60)
    logger.info(
        "批量 SKU 抓取完成: 总计=%d, 成功=%d, 失败=%d, 跳过=%d",
        result["total"],
        result["success"],
        result["failed"],
        result["skipped"],
    )
    logger.info("=" * 60)

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = batch_crawl_skus(limit=3)
    print(f"\n结果: {result}")
