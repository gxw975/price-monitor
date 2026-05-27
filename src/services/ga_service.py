"""GenericAgent 技能调用服务

通过 subprocess 调用 GA 命令行模式执行技能，提供统一的
Python 接口用于触发淘宝店透视数据导出和 SKU 抓取等功能。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ga_service")

GA_PYTHON = "/home/lab-admin/GenericAgent/.venv/bin/python"
GA_MAIN = "/home/lab-admin/GenericAgent/agentmain.py"
SKILLS_DIR = Path(__file__).resolve().parent.parent / "ga_skills"


def run_diantoushi_export(keyword: str) -> Optional[str]:
    """执行淘宝店透视数据导出。

    优先使用 GA agentmain.py 调用，不支持则降级到直接调技能脚本。

    Args:
        keyword: 搜索关键词

    Returns:
        成功时返回导出文件路径，失败时返回 None
    """
    if not keyword or not keyword.strip():
        logger.error("关键词不能为空")
        return None

    keyword = keyword.strip()
    logger.info("触发店透视导出: keyword=%s", keyword)

    diantoushi_script = SKILLS_DIR / "diantoushi_export.py"

    if not diantoushi_script.exists():
        logger.error("店透视导出脚本不存在: %s", diantoushi_script)
        return None

    ga_cmd = [GA_PYTHON, GA_MAIN, "--skill", "diantoushi_export", "--keyword", keyword]
    fallback_cmd = [
        sys.executable,
        str(diantoushi_script),
        keyword,
    ]

    return _exec_and_parse(ga_cmd, fallback_cmd, keyword)


def run_sku_crawl(product_id: str, url: str) -> list[dict]:
    """执行淘宝商品 SKU 抓取。

    Args:
        product_id: 商品 ID
        url: 商品详情页链接

    Returns:
        SKU 信息列表 [{"sku_name": "", "sku_price": 0.0, ...}]
    """
    if not product_id or not url:
        logger.error("product_id 和 url 不能为空")
        return []

    logger.info("触发 SKU 抓取: product_id=%s, url=%s", product_id, url)

    sku_script = SKILLS_DIR / "sku_crawler.py"

    if not sku_script.exists():
        logger.error("SKU 抓取脚本不存在: %s", sku_script)
        return []

    cmd = [sys.executable, str(sku_script), str(product_id), url]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15 * 60,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )

        output = result.stdout.strip()
        lines = output.splitlines()
        json_start = -1
        json_end = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if json_start == -1 and (stripped.startswith("[") or stripped.startswith("{")):
                json_start = i
                if stripped in ("[]", "{}"):
                    json_end = i
                    break
            elif json_start != -1 and stripped == "]":
                json_end = i
                break

        if json_start != -1 and json_end != -1:
            json_text = "\n".join(lines[json_start:json_end + 1])
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                logger.exception("SKU JSON 解析失败")

        logger.error("SKU 抓取无有效输出: %s", result.stderr[:200] if result.stderr else "")
        return []
    except subprocess.TimeoutExpired:
        logger.error("SKU 抓取超时")
        return []
    except Exception:
        logger.exception("SKU 抓取异常")
        return []


def _exec_and_parse(
    ga_cmd: list[str],
    fallback_cmd: list[str],
    keyword: str,
) -> Optional[str]:
    stdout = _exec_fallback(fallback_cmd, keyword)
    return _parse_output(stdout)


def _exec_fallback(cmd: list[str], keyword: str) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15 * 60,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("导出超时: keyword=%s", keyword)
        return ""
    except Exception:
        logger.exception("导出异常: keyword=%s", keyword)
        return ""


def _parse_output(stdout: str) -> Optional[str]:
    if not stdout:
        return None

    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("SUCCESS: "):
            path = line.replace("SUCCESS: ", "").strip()
            if os.path.exists(path):
                logger.info("导出成功: %s", path)
                return path

        if line.startswith("FAILED:"):
            logger.error("导出失败: %s", line)
            return None

    return None
