"""数据分析仪表盘 API

提供监控商品的聚合统计数据：总览卡片、平台分布、分类统计、
预警汇总、7日趋势，所有聚合在数据库层完成。
权限：全体可访问。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Query

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.statistics")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/statistics", tags=["统计"])


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


def _build_where(platform: str | None) -> tuple[str, list[Any]]:
    """构建 platform 筛选条件。未传 → 统计所有平台；传了 → 只统计该平台。"""
    if platform:
        return "p.platform = %s", [platform]
    return "TRUE", []


@router.get("/{monitor_id}/overview")
def get_statistics_overview(
    monitor_id: int,
    platform: str | None = Query(None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取监控商品的统计仪表盘数据（单次请求返回全部聚合）"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # ── Query 1: 统计卡片 ──
            where_clause, where_params = _build_where(platform)
            cur.execute(
                f"""SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE p.is_on_sale = TRUE)::int AS on_sale,
                    COUNT(*) FILTER (WHERE p.is_on_sale = FALSE)::int AS off_sale,
                    COUNT(*) FILTER (WHERE p.sku_category_id IS NULL)::int AS unclassified
                FROM "Product" p
                WHERE p.monitor_product_id = %s AND {where_clause}""",
                [monitor_id] + where_params,
            )
            stat_cards = dict(cur.fetchone() or {})

            # ── Query 2: 平台分布 ──
            cur.execute(
                """SELECT p.platform, COUNT(*)::int AS count
                FROM "Product" p
                WHERE p.monitor_product_id = %s
                GROUP BY p.platform
                ORDER BY count DESC""",
                (monitor_id,),
            )
            platform_dist = [dict(r) for r in cur.fetchall()]

            # ── Query 3: 分类统计 ──
            cur.execute(
                f"""SELECT
                    sc.id AS category_id,
                    COALESCE(sc.name, '未分类') AS category_name,
                    COUNT(p.product_id)::int AS count,
                    ROUND(AVG(p.price)::numeric, 2) AS avg_price,
                    ROUND(MIN(p.price)::numeric, 2) AS min_price,
                    (array_agg(p.product_id ORDER BY p.price ASC))[1] AS min_price_product_id,
                    ROUND(MAX(p.price)::numeric, 2) AS max_price,
                    ROUND(AVG(p.unit_price)::numeric, 4) AS avg_unit_price
                FROM "Product" p
                LEFT JOIN "SkuCategory" sc ON sc.id = p.sku_category_id
                    AND sc.monitor_product_id = p.monitor_product_id
                WHERE p.monitor_product_id = %s AND {where_clause} AND p.price > 0
                GROUP BY sc.id, sc.name
                ORDER BY count DESC""",
                [monitor_id] + where_params,
            )
            category_stats = [dict(r) for r in cur.fetchall()]

            # ── Query 4: 预警汇总 ──
            cur.execute(
                """SELECT
                    COUNT(*)::int AS total_unhandled,
                    COUNT(*) FILTER (WHERE a.alert_type = 'price')::int AS price_count,
                    COUNT(*) FILTER (WHERE a.alert_type = 'sales')::int AS sales_count
                FROM "Alert" a
                WHERE a.monitor_product_id = %s AND a.is_handled = FALSE""",
                (monitor_id,),
            )
            alert_counts = dict(cur.fetchone() or {})

            # ── Query 5a: 7天新增商品趋势 ──
            cur.execute(
                f"""SELECT d::date AS date, COALESCE(cnt, 0)::int AS count
                FROM generate_series(
                    CURRENT_DATE - INTERVAL '6 days',
                    CURRENT_DATE,
                    '1 day'
                ) d
                LEFT JOIN (
                    SELECT created_at::date AS day, COUNT(*) AS cnt
                    FROM "Product"
                    WHERE monitor_product_id = %s AND {where_clause}
                        AND created_at::date >= CURRENT_DATE - INTERVAL '6 days'
                    GROUP BY created_at::date
                ) t ON d::date = t.day
                ORDER BY d::date""",
                [monitor_id] + where_params,
            )
            new_product_trend = [
                {"date": r["date"].isoformat() if isinstance(r["date"], date) else str(r["date"]),
                 "count": r["count"]}
                for r in cur.fetchall()
            ]

            # ── Query 5b: 7天预警趋势 ──
            cur.execute(
                """SELECT d::date AS date, COALESCE(cnt, 0)::int AS count
                FROM generate_series(
                    CURRENT_DATE - INTERVAL '6 days',
                    CURRENT_DATE,
                    '1 day'
                ) d
                LEFT JOIN (
                    SELECT created_at::date AS day, COUNT(*) AS cnt
                    FROM "Alert"
                    WHERE monitor_product_id = %s
                        AND created_at::date >= CURRENT_DATE - INTERVAL '6 days'
                    GROUP BY created_at::date
                ) t ON d::date = t.day
                ORDER BY d::date""",
                (monitor_id,),
            )
            alert_trend = [
                {"date": r["date"].isoformat() if isinstance(r["date"], date) else str(r["date"]),
                 "count": r["count"]}
                for r in cur.fetchall()
            ]

        return {
            "stat_cards": stat_cards,
            "platform_dist": platform_dist,
            "category_stats": category_stats,
            "alert_counts": alert_counts,
            "trends": {
                "new_products": new_product_trend,
                "alerts": alert_trend,
            },
        }

    except Exception:
        logger.exception("获取统计数据失败: monitor_id=%d platform=%s", monitor_id, platform)
        return {
            "stat_cards": {},
            "platform_dist": [],
            "category_stats": [],
            "alert_counts": {},
            "trends": {"new_products": [], "alerts": []},
        }
    finally:
        conn.close()


@router.get("/{monitor_id}/match-analysis")
def get_match_analysis(
    monitor_id: int,
    platform: str | None = Query(None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """分类匹配效果分析：各分类匹配率 + 未分类商品高频词"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where_clause, where_params = _build_where(platform)

            # Category match stats
            cur.execute(
                f"""SELECT
                    COALESCE(sc.name, '未分类') AS category_name,
                    COUNT(*)::int AS total,
                    COUNT(p.sku_category_id)::int AS matched,
                    CASE WHEN COUNT(*) > 0
                        THEN ROUND(COUNT(p.sku_category_id)::numeric / COUNT(*)::numeric * 100, 1)
                        ELSE 0 END AS rate
                FROM "Product" p
                LEFT JOIN "SkuCategory" sc ON sc.id = p.sku_category_id
                    AND sc.monitor_product_id = p.monitor_product_id
                WHERE p.monitor_product_id = %s AND {where_clause}
                GROUP BY sc.id, sc.name
                ORDER BY total DESC""",
                [monitor_id] + where_params,
            )
            category_match = [dict(r) for r in cur.fetchall()]

            # Unclassified count
            cur.execute(
                f"""SELECT COUNT(*)::int AS unclassified_count
                FROM "Product" p
                WHERE p.monitor_product_id = %s AND {where_clause}
                  AND p.sku_category_id IS NULL""",
                [monitor_id] + where_params,
            )
            unclassified_count = cur.fetchone()["unclassified_count"] if cur.rowcount else 0

            # Top keywords from unclassified titles (2-char substrings)
            top_keywords = []
            if unclassified_count > 0:
                cur.execute(
                    f"""SELECT title FROM "Product" p
                    WHERE p.monitor_product_id = %s AND {where_clause}
                      AND p.sku_category_id IS NULL AND title IS NOT NULL AND title != ''""",
                    [monitor_id] + where_params,
                )
                titles = [r["title"] for r in cur.fetchall()]
                # Extract common 2-char segments
                from collections import Counter
                kw_counter: Counter = Counter()
                import re as _re
                for title in titles:
                    # Extract meaningful substrings: Chinese chars, units, numbers+units
                    words = _re.findall(r'[一-鿿]{2,3}|\d+\s*[袋罐条盒瓶克gG]|[袋罐条盒瓶桶听包]', title)
                    for w in words:
                        kw_counter[w.strip().lower()] += 1
                top_keywords = [{"keyword": kw, "count": cnt}
                               for kw, cnt in kw_counter.most_common(10)]

        return {
            "category_match": category_match,
            "unclassified_count": unclassified_count,
            "top_keywords": top_keywords,
        }
    except Exception:
        logger.exception("获取匹配分析失败")
        return {"category_match": [], "unclassified_count": 0, "top_keywords": []}
    finally:
        conn.close()
