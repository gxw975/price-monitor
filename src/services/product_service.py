"""商品入库服务

处理从各种来源（DTS导出、CDP抓取、手动导入）的商品数据入库。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("product_service")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"


def _parse_db_url(url: str) -> tuple[str, str]:
    from urllib.parse import parse_qs, urlparse, urlunparse

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    schema = qs.get("schema", [_SCHEMA])[0]
    clean = urlunparse(parsed._replace(query=""))
    return clean, schema


def _get_conn() -> Any:
    clean, schema = _parse_db_url(DATABASE_URL)
    conn = psycopg2.connect(clean)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    return conn


def find_or_create_keyword(name: str, platform: str = "taobao") -> int:
    """查找或创建关键词，返回 keyword_id。"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id FROM "Keyword" WHERE name = %s AND platform = %s',
                (name, platform),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                'INSERT INTO "Keyword" (name, platform, is_active) VALUES (%s, %s, %s) RETURNING id',
                (name, platform, True),
            )
            keyword_id = cur.fetchone()[0]
            conn.commit()
            logger.info("自动创建关键词: %s (id=%d)", name, keyword_id)
            return keyword_id
    except Exception:
        logger.exception("查找/创建关键词失败")
        return 0
    finally:
        conn.close()


def insert_search_results(keyword: str, items: list[dict[str, Any]]) -> int:
    """将搜索结果商品批量入库。

    Args:
        keyword: 搜索关键词
        items: [{"product_id": "", "title": "", "price": 0, "shop": "", "url": ""}]

    Returns:
        入库的商品数量
    """
    keyword_id = find_or_create_keyword(keyword)
    if not keyword_id:
        return 0

    conn = _get_conn()
    inserted = 0
    try:
        with conn.cursor() as cur:
            for item in items:
                pid = item.get("product_id", "")
                title = item.get("title", "").strip()
                shop = item.get("shop", "").strip()
                price = float(item.get("price", 0)) if item.get("price") else 0

                if not pid or not title:
                    continue

                # 检查是否存在
                cur.execute(
                    'SELECT product_id FROM "Product" WHERE product_id = %s',
                    (pid,),
                )
                if cur.fetchone():
                    continue

                # 插入商品
                cur.execute("""
                    INSERT INTO "Product" (product_id, title, shop_name, is_approved, is_whitelist, created_at, last_sku_crawled_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                """, (pid, title[:200], shop[:100], False, False))

                # 链接关键词
                cur.execute("""
                    INSERT INTO "ProductKeyword" (keyword_id, product_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                """, (keyword_id, pid))

                # 记录历史价格
                if price > 0:
                    cur.execute("""
                        INSERT INTO "ProductHistory" (product_id, price, sales_volume, recorded_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (pid, price, 0))

                inserted += 1

        conn.commit()
        logger.info("关键词[%s]搜索结果入库: %d 个商品", keyword, inserted)
        return inserted
    except Exception:
        logger.exception("搜索结果入库失败")
        conn.rollback()
        return inserted
    finally:
        conn.close()


def insert_product_with_skus(
    product_id: str,
    title: str,
    shop_name: str,
    image_url: str = "",
    keyword_name: str = "",
    skus: list[dict[str, Any]] | None = None,
) -> bool:
    """插入单个商品及其 SKU 数据。

    Args:
        product_id: 淘宝商品 ID
        title: 商品标题
        shop_name: 店铺名
        image_url: 主图链接
        keyword_name: 关联关键词
        skus: SKU 列表 [{"sku_name": "", "sku_price": 0.0, "unit_price": 0.0}]

    Returns:
        是否成功
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # 检查是否存在
            cur.execute(
                'SELECT product_id FROM "Product" WHERE product_id = %s',
                (product_id,),
            )
            if cur.fetchone():
                logger.debug("商品 %s 已存在", product_id)
                return True

            # 插入商品
            cur.execute("""
                INSERT INTO "Product" (product_id, title, shop_name, main_image_url, is_approved, is_whitelist, created_at, last_sku_crawled_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """, (product_id, title[:200], shop_name[:100], image_url, True, False))

            # 插入 SKU
            if skus:
                base_price = skus[0]["sku_price"] if skus else 0
                for s in skus:
                    cur.execute("""
                        INSERT INTO "ProductSku" (product_id, sku_name, sku_price, unit_price, recorded_at)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (product_id, s["sku_name"][:150], s["sku_price"], s.get("unit_price", s["sku_price"])))

                # 历史价格
                if base_price > 0:
                    cur.execute("""
                        INSERT INTO "ProductHistory" (product_id, price, sales_volume, recorded_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (product_id, base_price, 0))

            # 关联关键词
            if keyword_name:
                kw_id = find_or_create_keyword(keyword_name)
                if kw_id:
                    cur.execute("""
                        INSERT INTO "ProductKeyword" (keyword_id, product_id)
                        VALUES (%s, %s) ON CONFLICT DO NOTHING
                    """, (kw_id, product_id))

        conn.commit()
        logger.info("商品入库完成: %s", title[:60])
        return True
    except Exception:
        logger.exception("商品入库失败: %s", product_id)
        conn.rollback()
        return False
    finally:
        conn.close()


def _extract_qty(name: str) -> int:
    """从 SKU 名称提取数量。"""
    m = re.search(r'(\d+)\s*(袋|罐|瓶|盒|个|件|支|包)', name)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*(袋装|罐装)', name)
    if m:
        return int(m.group(1))
    return 1
