"""预警检测脚本

检测已审核商品的低价和销量异常，生成预警记录并发送飞书通知。
支持 --test 和 --force 参数用于调试。

用法:
    python src/scripts/check_alerts.py
    python src/scripts/check_alerts.py --test
    python src/scripts/check_alerts.py --force
    python src/scripts/check_alerts.py --test --force
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

DEFAULT_ALERT_PRICE = 50.0
DEFAULT_SALES_GROWTH_THRESHOLD = 100
DEFAULT_WORK_START = 9
DEFAULT_WORK_END = 18
DEDUP_HOURS = 24


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


def _setup_logging(date_str: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"alerts_{date_str}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)


def _read_config(conn: Any) -> dict[str, Any]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT * FROM "SystemConfig" ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
    if not row:
        return {
            "alert_price": DEFAULT_ALERT_PRICE,
            "sales_growth_threshold": DEFAULT_SALES_GROWTH_THRESHOLD,
            "work_start_hour": DEFAULT_WORK_START,
            "work_end_hour": DEFAULT_WORK_END,
        }
    return {
        "alert_price": float(row.get("alert_price", DEFAULT_ALERT_PRICE)),
        "sales_growth_threshold": int(row.get("sales_growth_threshold", DEFAULT_SALES_GROWTH_THRESHOLD)),
        "work_start_hour": int(row.get("work_start_hour", DEFAULT_WORK_START)),
        "work_end_hour": int(row.get("work_end_hour", DEFAULT_WORK_END)),
    }


def _get_approved_products(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            'SELECT product_id, title FROM "Product" '
            "WHERE is_approved = TRUE AND is_whitelist = FALSE"
        )
        return cur.fetchall()


def _get_today_history(conn: Any, product_id: str, target_date: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            'SELECT price, sales_volume FROM "ProductHistory" '
            "WHERE product_id = %s AND DATE(recorded_at) = %s "
            "ORDER BY recorded_at DESC LIMIT 1",
            (product_id, target_date),
        )
        return cur.fetchone()


def _get_yesterday_history(conn: Any, product_id: str, target_date: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            'SELECT sales_volume FROM "ProductHistory" '
            "WHERE product_id = %s AND DATE(recorded_at) = %s "
            "ORDER BY recorded_at DESC LIMIT 1",
            (product_id, target_date),
        )
        return cur.fetchone()


def _get_recent_histories(conn: Any, product_id: str, days: int = 7) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            'SELECT price, sales_volume, recorded_at FROM "ProductHistory" '
            "WHERE product_id = %s AND recorded_at >= NOW() - INTERVAL '1 day' * %s "
            "ORDER BY recorded_at DESC",
            (product_id, days),
        )
        return cur.fetchall()


def _is_duplicate(conn: Any, product_id: str, alert_type: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) FROM "Alert" '
            "WHERE product_id = %s AND alert_type = %s "
            "AND created_at >= NOW() - INTERVAL '1 hour' * %s",
            (product_id, alert_type, DEDUP_HOURS),
        )
        count = cur.fetchone()[0]
        return count > 0


def _insert_alert(conn: Any, product_id: str, alert_type: str, message: str, is_sent: bool = False) -> int:
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Alert" (product_id, alert_type, message, is_sent, sent_at) '
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (product_id, alert_type, message, is_sent, datetime.now() if is_sent else None),
        )
        alert_id = cur.fetchone()[0]
        conn.commit()
        return alert_id


def _mark_alert_sent(conn: Any, alert_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE "Alert" SET is_sent = TRUE, sent_at = %s WHERE id = %s',
            (datetime.now(), alert_id),
        )
        conn.commit()


def run_alerts(test_mode: bool = False, force: bool = False) -> dict[str, int]:
    conn = _get_conn()
    logger = logging.getLogger("check_alerts")

    config = _read_config(conn)
    alert_price = config["alert_price"]
    sales_growth_threshold = config["sales_growth_threshold"]
    work_start = int(config["work_start_hour"])
    work_end = int(config["work_end_hour"])

    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    result = {"checked": 0, "price_alerts": 0, "sales_alerts": 0, "sent": 0}

    products = _get_approved_products(conn)
    logger.info("开始预警检测: 商品数=%d, 价格阈值=%.2f, 销量阈值=%d%%, 去重=%dh",
                len(products), alert_price, sales_growth_threshold, DEDUP_HOURS)

    for product in products:
        product_id = product["product_id"]
        title = product.get("title", product_id)
        result["checked"] += 1

        if not force and _is_duplicate(conn, product_id, "price") and _is_duplicate(conn, product_id, "sales"):
            logger.debug("跳过已预警商品: %s", product_id)
            continue

        today = _get_today_history(conn, product_id, today_str)
        if not today:
            logger.debug("今日无数据: %s", product_id)
            continue

        current_price = float(today["price"])
        today_sales = int(today.get("sales_volume", 0) or 0)

        if current_price <= alert_price:
            if force or not _is_duplicate(conn, product_id, "price"):
                message = (
                    f"商品 {title}({product_id}) 当前价格 ¥{current_price:.2f} "
                    f"低于预警阈值 ¥{alert_price:.2f}"
                )
                alert_id = _insert_alert(conn, product_id, "price", message)
                result["price_alerts"] += 1

                try:
                    recent = _get_recent_histories(conn, product_id)
                    history_list = [
                        {"price": float(h["price"]),
                         "sales_volume": int(h.get("sales_volume", 0) or 0),
                         "recorded_at": str(h["recorded_at"])}
                        for h in recent
                    ]
                    from services.push_service import send_price_alert

                    sent = send_price_alert(
                        product_id, title, current_price, history_list,
                    )
                    if sent and any(sent.values()):
                        _mark_alert_sent(conn, alert_id)
                        result["sent"] += 1
                except Exception:
                    logger.exception("价格预警发送失败: %s", product_id)

                logger.warning("价格预警: %s ¥%.2f (阈值 ¥%.2f)", product_id, current_price, alert_price)

        yesterday = _get_yesterday_history(conn, product_id, yesterday_str)
        if yesterday:
            yesterday_sales = int(yesterday.get("sales_volume", 0) or 0)
            if today_sales > 0 and yesterday_sales > 0:
                growth = today_sales - yesterday_sales
                growth_pct = (growth / yesterday_sales) * 100
                if growth_pct >= sales_growth_threshold:
                    if force or not _is_duplicate(conn, product_id, "sales"):
                        message = (
                            f"商品 {title}({product_id}) 今日销量 {today_sales} 单 "
                            f"较昨日 {yesterday_sales} 单增长 {growth_pct:.1f}%"
                        )
                        alert_id = _insert_alert(conn, product_id, "sales", message)
                        result["sales_alerts"] += 1

                        try:
                            from services.push_service import send_sales_alert

                            sent = send_sales_alert(
                                product_id, title, today_sales, yesterday_sales,
                                current_price,
                            )
                            if sent and any(sent.values()):
                                _mark_alert_sent(conn, alert_id)
                                result["sent"] += 1
                        except Exception:
                            logger.exception("销量预警发送失败: %s", product_id)

                        logger.warning("销量预警: %s 增长 %.1f%% (%d→%d)",
                                       product_id, growth_pct, yesterday_sales, today_sales)

    conn.close()

    if test_mode:
        logger.info("【测试模式】: 检测完成, 结果=%s", result)
    else:
        logger.info("预警检测完成: 结果=%s", result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="电商低价监控 - 预警检测")
    parser.add_argument("--test", action="store_true", help="测试模式，仅输出结果不实际发送")
    parser.add_argument("--force", action="store_true", help="强制模式，忽略去重检测")
    args = parser.parse_args()

    date_str = date.today().isoformat()
    _setup_logging(date_str)

    logger = logging.getLogger("check_alerts")
    logger.info("预警检测启动: test=%s, force=%s", args.test, args.force)

    try:
        result = run_alerts(test_mode=args.test, force=args.force)
    except Exception:
        logger.exception("预警检测执行异常")
        sys.exit(1)

    logger.info("预警检测结束: 检查=%d 价格预警=%d 销量预警=%d 已发送=%d",
                result["checked"], result["price_alerts"],
                result["sales_alerts"], result["sent"])

    if result["price_alerts"] == 0 and result["sales_alerts"] == 0:
        logger.info("本次检测未发现预警")


if __name__ == "__main__":
    main()
