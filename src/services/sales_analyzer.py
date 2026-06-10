"""日均销量计算服务

提供商品日均付款人数计算，支持首次导入估算和后续差值计算。
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("sales_analyzer")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"


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


def calculate_daily_sales(product_id: str, current_total_sales: int = 0) -> float:
    """计算商品日均付款人数。

    规则:
    - 首次导入: total_sales / 180（估算上架180天）
    - 后续导入: (current_total - previous_total) / days_between

    Returns:
        日均销量（付款人数/天）
    """
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 获取最近两次历史记录
            cur.execute("""
                SELECT sales_volume, recorded_at
                FROM "ProductHistory"
                WHERE product_id = %s
                ORDER BY recorded_at DESC
                LIMIT 2
            """, (product_id,))
            rows = cur.fetchall()

            if len(rows) < 2:
                # 首次导入：用总销量估算
                if current_total_sales > 0:
                    daily = round(current_total_sales / 180.0, 2)
                elif rows:
                    daily = round(float(rows[0]["sales_volume"] or 0) / 180.0, 2)
                else:
                    daily = 0.0
                logger.debug("日均销量(首次): pid=%s total=%d daily=%.2f",
                             product_id, current_total_sales or 0, daily)
            else:
                current = int(rows[0]["sales_volume"] or 0)
                previous = int(rows[1]["sales_volume"] or 0)
                current_date = rows[0]["recorded_at"].date() if isinstance(rows[0]["recorded_at"], date) else rows[0]["recorded_at"]
                previous_date = rows[1]["recorded_at"].date() if isinstance(rows[1]["recorded_at"], date) else rows[1]["recorded_at"]
                days = (current_date - previous_date).days
                if days <= 0:
                    days = 1
                daily = round((current - previous) / days, 2)
                if daily < 0:
                    daily = 0.0
                logger.debug("日均销量(差值): pid=%s cur=%d prev=%d days=%d daily=%.2f",
                             product_id, current, previous, days, daily)

            return daily
    except Exception:
        logger.exception("计算日均销量失败: %s", product_id)
        return 0.0
    finally:
        conn.close()


def update_product_daily_sales(product_id: str, total_sales: int = 0) -> float:
    """计算并更新商品日均销量到 Product 表。

    Returns:
        更新后的日均销量值
    """
    daily = calculate_daily_sales(product_id, total_sales)
    if daily > 0:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "Product" SET daily_sales = %s WHERE product_id = %s',
                    (daily, product_id),
                )
            conn.commit()
        except Exception:
            logger.exception("更新日均销量失败: %s", product_id)
            conn.rollback()
        finally:
            conn.close()
    return daily
