"""多渠道推送服务

支持飞书卡片消息、企业微信 Webhook 消息、个人微信（OpenClaw Agent 路由）推送。
工作时段 9:00-18:00 + 周末跳过，推送渠道从 SystemConfig 读取。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("push_service")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"
ENV = os.getenv("ENV", "production")


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


def _get_push_config() -> dict[str, Any]:
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM "SystemConfig" ORDER BY id LIMIT 1')
            row = cur.fetchone()
            if not row:
                return {}
            return {
                "feishu_webhook": row.get("feishu_webhook") or os.getenv("FEISHU_WEBHOOK_URL", ""),
                "wechat_webhook": row.get("wechat_webhook") or "",
                "enabled_channels": json.loads(row.get("push_enabled_channels", '["feishu"]')),
                "work_start_hour": row["work_start_hour"],
                "work_end_hour": row["work_end_hour"],
            }
    except Exception:
        logger.exception("读取推送配置失败")
        return {
            "feishu_webhook": os.getenv("FEISHU_WEBHOOK_URL", ""),
            "wechat_webhook": "",
            "enabled_channels": ["feishu"],
            "work_start_hour": 9,
            "work_end_hour": 18,
        }
    finally:
        conn.close()


def _is_work_hour(work_start: int = 9, work_end: int = 18) -> bool:
    now = datetime.now()
    current_hour = now.hour
    current_weekday = now.weekday()
    if current_weekday >= 5:
        return False
    return work_start <= current_hour < work_end


def _send_feishu_card(webhook_url: str, card: dict[str, Any]) -> bool:
    if not webhook_url:
        logger.warning("飞书 Webhook 未配置")
        return False

    data = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("飞书消息发送成功")
                return True
            logger.error("飞书返回错误: %s", body[:300])
            return False
    except urllib.error.URLError:
        logger.error("飞书消息发送失败: 网络错误")
        return False
    except Exception:
        logger.exception("飞书消息发送异常")
        return False


def _send_wechat_markdown(webhook_url: str, content: str) -> bool:
    if not webhook_url:
        logger.warning("微信 Webhook 未配置")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            logger.info("微信消息发送成功, 响应: %s", body[:200])
            return True
    except urllib.error.URLError:
        logger.error("微信消息发送失败: 网络错误")
        return False
    except Exception:
        logger.exception("微信消息发送异常")
        return False


def _send_openclaw_wechat(agent_id: str, content: str) -> tuple[bool, str]:
    if not agent_id:
        return False, "Agent ID 为空"
    try:
        openclaw_bin = "/home/lab-admin/.nvm/versions/node/v22.22.0/bin/openclaw"
        cmd = [
            openclaw_bin, "agent",
            "--agent", agent_id,
            "--message", content,
            "--deliver",
            "--json",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()[:300]
            logger.warning("OpenClaw 消息发送失败: agent=%s err=%s", agent_id, err)
            return False, err or f"退出码 {result.returncode}"
        logger.info("OpenClaw 个人微信消息已投递: agent=%s", agent_id)
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "OpenCLI 命令执行超时"
    except FileNotFoundError:
        return False, f"OpenCLI 二进制不可用: {openclaw_bin}"
    except Exception as e:
        logger.exception("OpenClaw 个人微信消息发送异常: agent=%s", agent_id)
        return False, str(e)


def _get_users_with_agent() -> list[dict[str, Any]]:
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id, username, openclaw_agent_id FROM "User" '
                "WHERE openclaw_agent_id IS NOT NULL AND openclaw_agent_id != ''"
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("查询绑定了Agent的用户失败")
        return []
    finally:
        conn.close()


def _send_personal_wechat_to_all(content: str) -> dict[str, bool]:
    users = _get_users_with_agent()
    results: dict[str, bool] = {}
    for u in users:
        agent_id = u.get("openclaw_agent_id", "")
        if agent_id:
            ok, _ = _send_openclaw_wechat(agent_id, content)
            results[agent_id] = ok
    if not users:
        logger.info("没有绑定 OpenClaw Agent 的用户，跳过个人微信推送")
    return results


def _build_feishu_price_card(
    product_id: str,
    title: str,
    current_price: Decimal,
    history_prices: list[dict[str, Any]],
) -> dict[str, Any]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    history_lines = ""
    for h in history_prices[-5:]:
        history_lines += f"\n  • {h['recorded_at']}: ¥{h['price']} (销量: {h.get('sales_volume', '?')})"

    return {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": "🔴 低价预警", "tag": "plain_text"},
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
                        {"tag": "plain_text", "content": "价格已低于系统设定的预警阈值，请及时关注"}
                    ],
                },
            ],
        },
    }


def _build_wechat_price_md(
    product_id: str,
    title: str,
    current_price: Decimal,
    history_prices: list[dict[str, Any]],
) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_lines = ""
    for h in history_prices[-5:]:
        history_lines += f"\n> {h['recorded_at']}: ¥{h['price']} (销量: {h.get('sales_volume', '?')})"

    return (
        f"## 🔴 低价预警\n"
        f"**商品:** {title}\n"
        f"**商品ID:** {product_id}\n"
        f"**当前价格:** ¥{current_price}\n"
        f"**检测时间:** {now_str}\n\n"
        f"**近期走势:**{history_lines}\n\n"
        f"> 价格已低于系统设定的预警阈值，请及时关注"
    )


def _build_feishu_sales_card(
    product_id: str,
    title: str,
    today_sales: int,
    yesterday_sales: int,
    today_price: Decimal,
) -> dict[str, Any]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    growth = today_sales - yesterday_sales
    if yesterday_sales > 0:
        ratio_text = f"+{growth / yesterday_sales * 100:.1f}%"
    else:
        ratio_text = f"+{growth} 单"

    return {
        "msgtype": "interactive",
        "card": {
            "header": {
                "title": {"content": "🟠 销量预警", "tag": "plain_text"},
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
                        {"tag": "plain_text", "content": "销量较昨日大幅增长，可能存在低价跟卖风险"}
                    ],
                },
            ],
        },
    }


def _build_wechat_sales_md(
    product_id: str,
    title: str,
    today_sales: int,
    yesterday_sales: int,
    today_price: Decimal,
) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    growth = today_sales - yesterday_sales
    if yesterday_sales > 0:
        ratio_text = f"+{growth / yesterday_sales * 100:.1f}%"
    else:
        ratio_text = f"+{growth} 单"

    return (
        f"## 🟠 销量预警\n"
        f"**商品:** {title}\n"
        f"**商品ID:** {product_id}\n"
        f"**今日销量:** {today_sales} 单\n"
        f"**昨日销量:** {yesterday_sales} 单\n"
        f"**增长:** {ratio_text}\n"
        f"**当前售价:** ¥{today_price}\n"
        f"**检测时间:** {now_str}\n\n"
        f"> 销量较昨日大幅增长，可能存在低价跟卖风险"
    )


def send_price_alert(
    product_id: str,
    title: str,
    current_price: Decimal,
    history_prices: list[dict[str, Any]],
) -> dict[str, bool]:
    """发送价格预警到所有已启用渠道"""
    config = _get_push_config()
    work_start = config["work_start_hour"]
    work_end = config["work_end_hour"]

    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过价格预警: product_id=%s", product_id)
        return {}

    channels = config["enabled_channels"]
    results: dict[str, bool] = {}

    if "feishu" in channels:
        wh = config["feishu_webhook"]
        if wh:
            card = _build_feishu_price_card(product_id, title, current_price, history_prices)
            results["feishu"] = _send_feishu_card(wh, card)

    if "wechat" in channels:
        wh = config["wechat_webhook"]
        if wh:
            md = _build_wechat_price_md(product_id, title, current_price, history_prices)
            results["wechat"] = _send_wechat_markdown(wh, md)

    if "personal_wechat" in channels:
        content = f"🔴 低价预警\n商品: {title}\n商品ID: {product_id}\n当前价格: ¥{current_price}\n检测时间: {datetime.now().strftime('%m-%d %H:%M')}"
        pc_results = _send_personal_wechat_to_all(content)
        results["personal_wechat"] = any(pc_results.values()) if pc_results else False

    return results


def send_sales_alert(
    product_id: str,
    title: str,
    today_sales: int,
    yesterday_sales: int,
    today_price: Decimal,
) -> dict[str, bool]:
    """发送销量预警到所有已启用渠道"""
    config = _get_push_config()
    work_start = config["work_start_hour"]
    work_end = config["work_end_hour"]

    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过销量预警: product_id=%s", product_id)
        return {}

    channels = config["enabled_channels"]
    results: dict[str, bool] = {}

    if "feishu" in channels:
        wh = config["feishu_webhook"]
        if wh:
            card = _build_feishu_sales_card(product_id, title, today_sales, yesterday_sales, today_price)
            results["feishu"] = _send_feishu_card(wh, card)

    if "wechat" in channels:
        wh = config["wechat_webhook"]
        if wh:
            md = _build_wechat_sales_md(product_id, title, today_sales, yesterday_sales, today_price)
            results["wechat"] = _send_wechat_markdown(wh, md)

    if "personal_wechat" in channels:
        content = f"🟠 销量预警\n商品: {title}\n商品ID: {product_id}\n今日销量: {today_sales} 单\n昨日销量: {yesterday_sales} 单\n当前售价: ¥{today_price}\n检测时间: {datetime.now().strftime('%m-%d %H:%M')}"
        pc_results = _send_personal_wechat_to_all(content)
        results["personal_wechat"] = any(pc_results.values()) if pc_results else False

    return results


def send_custom_alert(
    alert_type: str,
    title_content: str,
    body_md: str,
    template: str = "red",
) -> dict[str, bool]:
    """发送自定义预警到所有已启用渠道"""
    config = _get_push_config()
    work_start = config["work_start_hour"]
    work_end = config["work_end_hour"]

    if not _is_work_hour(work_start, work_end):
        logger.info("非工作时段，跳过自定义预警发送")
        return {}

    channels = config["enabled_channels"]
    results: dict[str, bool] = {}

    type_label = "🔴 价格预警" if alert_type == "price" else "🟠 销量预警"

    if "feishu" in channels:
        wh = config["feishu_webhook"]
        if wh:
            card = {
                "msgtype": "interactive",
                "card": {
                    "header": {
                        "title": {"content": type_label, "tag": "plain_text"},
                        "template": template,
                    },
                    "elements": [
                        {"tag": "div", "text": {"tag": "lark_md", "content": body_md}},
                        {"tag": "hr"},
                        {
                            "tag": "note",
                            "elements": [{"tag": "plain_text", "content": "电商低价监控系统 · 自动预警"}],
                        },
                    ],
                },
            }
            results["feishu"] = _send_feishu_card(wh, card)

    if "wechat" in channels:
        wh = config["wechat_webhook"]
        if wh:
            md_content = f"## {type_label}\n{body_md}\n\n> 电商低价监控系统 · 自动预警"
            results["wechat"] = _send_wechat_markdown(wh, md_content)

    if "personal_wechat" in channels:
        content = f"{type_label}\n{body_md}"
        pc_results = _send_personal_wechat_to_all(content)
        results["personal_wechat"] = any(pc_results.values()) if pc_results else False

    return results


def send_test_message(channel: str, webhook_url: str) -> bool:
    """发送测试消息到指定渠道"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if channel == "feishu":
        card = {
            "msgtype": "interactive",
            "card": {
                "header": {
                    "title": {"content": "✅ 连接测试", "tag": "plain_text"},
                    "template": "green",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"飞书 Webhook 连接测试成功！\n测试时间: {now_str}\n来源: 电商低价监控系统",
                        },
                    },
                ],
            },
        }
        return _send_feishu_card(webhook_url, card)

    if channel == "wechat":
        md = f"## ✅ 连接测试\n微信 Webhook 连接测试成功！\n\n测试时间: {now_str}\n来源: 电商低价监控系统"
        return _send_wechat_markdown(webhook_url, md)

    return False


def send_test_personal_wechat(agent_id: str) -> dict[str, Any]:
    """发送测试消息到指定用户的个人微信"""
    if not agent_id:
        return {"success": False, "message": "未绑定 OpenClaw Agent ID，请先在个人中心绑定"}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"✅ price-monitor 个人微信推送连接测试成功！\n测试时间: {now_str}"
    ok, err = _send_openclaw_wechat(agent_id, content)

    if ok:
        return {"success": True, "message": "测试消息已发送，请查看你的个人微信"}
    else:
        return {"success": False, "message": f"发送失败：{err}"}
