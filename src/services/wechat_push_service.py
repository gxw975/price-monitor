"""个人微信推送服务 — 基于 Server酱 HTTP API

Server酱（https://sct.ftqq.com）是国内成熟的微信推送服务：
- 扫码关注公众号即可获得 SendKey
- 调用 HTTP API 直接推送到个人微信
- 免费额度：每天 5 条
- 支持 Markdown 格式

用法:
    from services.wechat_push_service import send_wechat_message, send_wechat_alert
    ok, msg = send_wechat_message(sendkey, "测试", "内容")
"""

from __future__ import annotations

import logging
from typing import Tuple

import requests

logger = logging.getLogger("wechat_push")

SERVERCHAN_URL = "https://sctapi.ftqq.com/{sendkey}.send"


def send_wechat_message(sendkey: str, title: str, content: str) -> Tuple[bool, str]:
    """通过 Server酱 推送消息到个人微信。

    Args:
        sendkey: Server酱 SendKey（从 sct.ftqq.com 获取）
        title: 消息标题
        content: 消息正文（支持 Markdown）

    Returns:
        (是否成功, 消息)
    """
    if not sendkey or not sendkey.strip():
        return False, "SendKey 未配置"

    try:
        resp = requests.post(
            SERVERCHAN_URL.format(sendkey=sendkey.strip()),
            data={"title": title, "desp": content},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info("微信推送成功: %s", title)
            return True, "发送成功"
        else:
            err_msg = data.get("message", data.get("info", "unknown"))
            logger.warning("微信推送失败: %s", err_msg)
            return False, str(err_msg)
    except requests.exceptions.Timeout:
        logger.warning("微信推送超时")
        return False, "推送超时"
    except Exception as e:
        logger.exception("微信推送异常")
        return False, str(e)


def send_wechat_alert(sendkey: str, alert: dict) -> Tuple[bool, str]:
    """发送预警消息到微信。

    Args:
        sendkey: Server酱 SendKey
        alert: 预警信息字典，包含:
            - alert_type: 'price' 或 'sales'
            - monitor_product_name: 监控商品名称
            - product_title: 商品标题
            - price: 当前价格
            - threshold: 预警阈值
            - shop_name: 店铺名称

    Returns:
        (是否成功, 消息)
    """
    alert_type = alert.get("alert_type", "price")
    is_price = alert_type == "price"

    title = "{} {} — {}".format(
        "💰" if is_price else "📈",
        "低价预警" if is_price else "销量突增预警",
        alert.get("monitor_product_name", "未知商品"),
    )

    content = """## {} {}

| 项目 | 详情 |
|------|------|
| 监控商品 | {} |
| 商品标题 | {} |
| 当前价格 | ¥{} |
| 预警阈值 | ¥{} |
| 店铺 | {} |
""".format(
        "💰" if is_price else "📈",
        "低价预警" if is_price else "销量突增预警",
        alert.get("monitor_product_name", "-"),
        alert.get("product_title", "-"),
        alert.get("price", "-"),
        alert.get("threshold", "-"),
        alert.get("shop_name", "-"),
    )

    return send_wechat_message(sendkey, title, content.strip())
