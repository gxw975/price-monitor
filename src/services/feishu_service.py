"""飞书通知服务

提供低价预警和销量预警的飞书卡片消息发送能力。
工作时段 9:00-18:00 才发送，非工作时段跳过。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("feishu_service")

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
ENV = os.getenv("ENV", "production")


class FeishuServiceError(Exception):
    """飞书服务异常"""


def _is_work_hour(work_start: int = 9, work_end: int = 18) -> bool:
    now = datetime.now()
    current_hour = now.hour
    current_weekday = now.weekday()
    if current_weekday >= 5:
        return False
    return work_start <= current_hour < work_end


def _send_card(card: dict[str, Any]) -> bool:
    if not FEISHU_WEBHOOK_URL:
        logger.warning("FEISHU_WEBHOOK_URL 未配置，跳过发送")
        return False

    data = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        FEISHU_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            logger.info("飞书消息发送成功, 响应: %s", body[:200])
            return True
    except urllib.error.URLError as e:
        logger.error("飞书消息发送失败: %s", str(e))
        return False
    except Exception:
        logger.exception("飞书消息发送异常")
        return False


def send_price_alert(
    product_id: str,
    title: str,
    current_price: Decimal,
    history_prices: list[dict[str, Any]],
    work_start: int = 9,
    work_end: int = 18,
) -> bool:
    """发送低价预警卡片"""
    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过价格预警发送: product_id=%s", product_id)
        return False

    env_tag = ""
    if ENV == "test":
        env_tag = " 【测试】"
    elif ENV == "staging":
        env_tag = " 【预发】"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    history_lines = ""
    for h in history_prices[-5:]:
        history_lines += f"\n  • {h['recorded_at']}: ¥{h['price']} (销量: {h.get('sales_volume', '?')})"

    card = {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": f"🔴 低价预警{env_tag}", "tag": "plain_text"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**商品:** {title}\n"
                            f"**商品ID:** {product_id}\n"
                            f"**当前价格:** ¥{current_price}\n"
                            f"**检测时间:** {now_str}\n\n"
                            f"**近期价格走势:**{history_lines}"
                        ),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "价格已低于系统设定的预警阈值，请及时关注",
                        }
                    ],
                },
            ],
        },
    }

    return _send_card(card)


def send_sales_alert(
    product_id: str,
    title: str,
    today_sales: int,
    yesterday_sales: int,
    today_price: Decimal,
    work_start: int = 9,
    work_end: int = 18,
) -> bool:
    """发送销量突增预警卡片"""
    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过销量预警发送: product_id=%s", product_id)
        return False

    env_tag = ""
    if ENV == "test":
        env_tag = " 【测试】"
    elif ENV == "staging":
        env_tag = " 【预发】"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    growth = today_sales - yesterday_sales
    if yesterday_sales > 0:
        ratio = (growth / yesterday_sales) * 100
        ratio_text = f"+{ratio:.1f}%"
    else:
        ratio_text = f"+{growth} 单"

    card = {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": f"🟠 销量预警{env_tag}", "tag": "plain_text"},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**商品:** {title}\n"
                            f"**商品ID:** {product_id}\n"
                            f"**今日销量:** {today_sales} 单\n"
                            f"**昨日销量:** {yesterday_sales} 单\n"
                            f"**增长:** {ratio_text}\n"
                            f"**当前售价:** ¥{today_price}\n"
                            f"**检测时间:** {now_str}"
                        ),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "销量较昨日大幅增长，可能存在低价跟卖风险",
                        }
                    ],
                },
            ],
        },
    }

    return _send_card(card)


def send_custom_alert(
    alert_type: str,
    title_content: str,
    body_md: str,
    template: str = "red",
    work_start: int = 9,
    work_end: int = 18,
) -> bool:
    """发送自定义预警卡片"""
    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过自定义预警发送")
        return False

    env_tag = ""
    if ENV == "test":
        env_tag = " 【测试】"
    elif ENV == "staging":
        env_tag = " 【预发】"

    type_label = "🔴 价格预警" if alert_type == "price" else "🟠 销量预警"

    card = {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": f"{type_label}{env_tag}", "tag": "plain_text"},
                "template": template,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": body_md,
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "电商低价监控系统 · 自动预警",
                        }
                    ],
                },
            ],
        },
    }

    return _send_card(card)
