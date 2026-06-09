"""DTS店透视导出Excel解析服务

解析店透视（DTS）插件导出的Excel文件，提取商品数据并转换为系统标准格式。
支持自动识别列名、商品ID提取、销量格式化等功能。

用法:
    from services.dts_parser import DtsDataParser
    parser = DtsDataParser()
    products = parser.parse("/path/to/export.xlsx")
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any

logger = logging.getLogger("dts_parser")

# 默认数据下载目录
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "downloads"

# ── 列名映射表 ──
# DTS导出的各种可能列名 → 标准字段
COLUMN_PATTERNS: dict[str, list[str]] = {
    "product_id": [
        "商品ID", "商品id", "product_id", "item_id", "宝贝ID", "宝贝id",
    ],
    "title": [
        "标题", "商品标题", "商品名", "商品名称", "宝贝标题", "title",
    ],
    "price": [
        "价格", "售价", "成交价", "商品价格", "price", "销售价",
        "现价", "原价", "折扣价",
    ],
    "sales": [
        "销量", "月销量", "付款人数", "成交笔数", "sales", "月销",
        "30天销量",
    ],
    "shop_name": [
        "所属店铺", "店铺", "店铺名", "店铺名称", "卖家", "shop",
        "卖家旺旺",
    ],
    "url": [
        "商品链接", "链接", "URL", "url", "商品地址", "宝贝链接",
    ],
    "category": [
        "类目", "商品类目", "category", "分类",
    ],
    "is_tmall": [
        "是否天猫", "天猫", "is_tmall",
    ],
    "location": [
        "所在地", "发货地", "location",
    ],
    "tags": [
        "标签", "商品标签", "tags",
    ],
    "placeholder_type": [
        "占位类型", "广告位类型", "展位类型", "推广位类型",
    ],
    "seller_name": [
        "掌柜名", "掌柜", "卖家昵称", "seller",
    ],
    "daily_sales": [
        "日均付款人数", "日均销量", "日均付款", "日销量",
    ],
    "image_url": [
        "图片", "主图", "商品图片", "宝贝图片", "image",
        "图片链接", "主图链接",
    ],
}


class DtsDataParser:
    """DTS Excel 数据解析器"""

    def __init__(self, output_dir: str | Path | None = None):
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── 主入口 ───────────────────────────────────────────

    def parse(self, filepath: str | Path) -> list[dict[str, Any]]:
        """解析DTS导出的Excel文件，返回标准化商品数据列表。

        Args:
            filepath: xlsx 文件路径

        Returns:
            [{"product_id": "", "title": "", "price": 0, "sales": 0,
              "shop_name": "", "url": "", ...}]
        """
        try:
            from openpyxl import load_workbook
        except ImportError:
            logger.error("请安装 openpyxl: pip install openpyxl")
            return []

        filepath = Path(filepath)
        if not filepath.exists():
            logger.error("文件不存在: %s", filepath)
            return []

        logger.info("解析 DTS 导出文件: %s (%d bytes)",
                     filepath.name, filepath.stat().st_size)

        try:
            wb = load_workbook(str(filepath), read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
        except Exception as e:
            logger.error("读取 Excel 失败: %s", e)
            return []

        if not rows:
            logger.warning("Excel 文件为空")
            return []

        # 解析表头
        raw_headers = [str(h).strip() if h else "" for h in rows[0]]
        mapping = self._find_column_mapping(raw_headers)
        logger.info("列映射: %s", {k: v for k, v in mapping.items()})

        # 解析数据行
        products = []
        seen_ids = set()

        for row_num, row in enumerate(rows[1:], 2):
            record = {}
            for std_field, col_name in mapping.items():
                col_idx = raw_headers.index(col_name) if col_name in raw_headers else -1
                if col_idx >= 0 and col_idx < len(row):
                    val = row[col_idx]
                    record[std_field] = str(val).strip() if val is not None else ""
                else:
                    record[std_field] = ""

            # 提取商品ID
            pid = self.extract_product_id(record)
            if not pid:
                logger.debug("行%d: 无法提取商品ID，跳过", row_num)
                continue
            if pid in seen_ids:
                logger.debug("行%d: 商品ID重复 %s，跳过", row_num, pid)
                continue
            seen_ids.add(pid)
            record["product_id"] = pid

            # 格式化数据
            record["price"] = self._parse_price(record.get("price", "0"))
            record["sales"] = self._parse_sales(record.get("sales", "0"))

            products.append(record)

        logger.info("解析完成: %d 个商品 (共%d行数据)", len(products), len(rows) - 1)

        # 复制文件到 data/downloads
        self._archive_file(filepath)

        return products

    # ── 列名匹配 ─────────────────────────────────────────

    def _find_column_mapping(self, headers: list[str]) -> dict[str, str]:
        """自动识别Excel列名与标准字段的映射。

        使用模糊匹配：表头包含关键词即匹配成功。
        """
        mapping: dict[str, str] = {}

        for std_field, patterns in COLUMN_PATTERNS.items():
            for h in headers:
                h_lower = h.lower()
                for pattern in patterns:
                    if pattern.lower() in h_lower or h_lower in pattern.lower():
                        mapping[std_field] = h
                        break
                if std_field in mapping:
                    break

        # 兜底：直接用表头名作为字段名的映射
        if "product_id" not in mapping:
            for h in headers:
                hl = h.lower()
                if "id" in hl and ("商品" in hl or "宝贝" in hl or "item" in hl):
                    mapping["product_id"] = h
                    break

        logger.debug("列映射结果: %s", mapping)
        return mapping

    # ── 商品ID提取 ───────────────────────────────────────

    def extract_product_id(self, record: dict) -> str:
        """从记录中提取商品ID。

        尝试顺序:
        1. product_id 字段如果已经是纯数字ID（13位），直接返回
        2. 从 url / 商品链接 中提取 ?id=xxx
        3. 从商品链接路径中提取 item.htm?id=xxx
        """
        # 优先使用已有的 product_id 字段
        pid = record.get("product_id", "")
        if pid and re.match(r'^\d{11,15}$', pid):
            return pid

        # 从URL中提取
        url = record.get("url", "")
        if not url:
            # 有时链接在别的字段中
            for v in record.values():
                if "item.taobao.com" in str(v) or "detail.tmall.com" in str(v):
                    url = str(v)
                    break

        if url:
            # 方式1: ?id=1234567890123
            m = re.search(r'[?&]id=(\d{11,15})', url)
            if m:
                return m.group(1)

            # 方式2: /item.htm?id=123&... 已在上面捕获

        return ""

    # ── 数据格式化 ───────────────────────────────────────

    def _parse_price(self, val: str) -> float:
        """解析价格字符串为浮点数。

        处理格式: "200", "42.9", "¥128.00", "128.00元"
        """
        if not val:
            return 0.0
        # 去除货币符号和单位
        cleaned = val.replace("¥", "").replace("￥", "").replace("元", "")
        cleaned = cleaned.replace(",", "").strip()
        try:
            return round(float(cleaned), 2)
        except (ValueError, TypeError):
            return 0.0

    def _parse_sales(self, val: str) -> int:
        """解析销量字符串为整数。

        处理格式: "1万+人付款" → 10000, "5000+人付款" → 5000,
                  "600+人付款" → 600, "100" → 100
        """
        if not val:
            return 0

        # 提取数字部分
        cleaned = val.replace(",", "").replace("+", "").strip()

        if "万" in cleaned:
            m = re.search(r'([\d.]+)\s*万', cleaned)
            if m:
                return int(float(m.group(1)) * 10000)

        # 纯数字
        m = re.search(r'(\d+)', cleaned)
        if m:
            return int(m.group(1))

        return 0

    # ── 文件归档 ─────────────────────────────────────────

    def _archive_file(self, filepath: Path) -> str:
        """复制文件到 data/downloads/ 存档"""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_name = f"DTS_{filepath.stem}_{ts}.xlsx"
            dest = self.output_dir / dest_name
            shutil.copy2(str(filepath), str(dest))
            logger.info("文件已归档: %s", dest)
            return str(dest)
        except Exception as e:
            logger.warning("文件归档失败: %s", e)
            return ""

    def normalize_products(self, raw_products: list[dict]) -> list[dict]:
        """标准化商品列表为入库格式。

        Returns:
            [{"product_id": "", "title": "", "price": 0, "shop": "", "url": ""}]
        """
        result = []
        for p in raw_products:
            result.append({
                "product_id": p.get("product_id", ""),
                "title": p.get("title", p.get("商品标题", "")),
                "price": self._parse_price(str(p.get("price", "0"))),
                "sales": self._parse_sales(str(p.get("sales", "0"))),
                "shop": p.get("shop_name", p.get("店铺", "")),
                "url": p.get("url", p.get("商品链接", "")),
            })
        return result


    def filter_natural_products(self, raw_products: list[dict]) -> list[dict]:
        """过滤只保留'自然位'数据，清除广告位。

        根据DTS占位类型字段过滤：
        - "自然位"：正常搜索结果，保留
        - 其他（广告位、推广位等）：过滤掉

        Returns:
            仅含自然位的商品列表
        """
        natural = []
        for p in raw_products:
            pt = p.get("placeholder_type", "")
            if not pt or pt == "自然位":
                natural.append(p)
        ad_count = len(raw_products) - len(natural)
        logger.info("数据清洗: 总数=%d 自然位=%d 广告=%d",
                     len(raw_products), len(natural), ad_count)
        return natural

    def clean_ad_data(self, raw_products: list[dict]) -> tuple[list[dict], int]:
        """清洗广告数据，返回(有效商品列表, 广告数量)。

        清洗规则:
        1. 只保留占位类型为"自然位"的记录
        2. 过滤商品ID为空或格式不正确的记录
        3. 过滤价格为0或负数的记录
        4. 自动补全商品链接（添加https:前缀）
        """
        # 第一步：只保留自然位
        natural = self.filter_natural_products(raw_products)
        ad_count = len(raw_products) - len(natural)

        # 第二步：过滤无效商品ID
        valid = []
        for p in natural:
            pid = p.get("product_id", "")
            # 过滤空ID或非数字ID
            if not pid or not re.match(r'^\d{8,20}$', str(pid)):
                continue
            # 补全商品链接
            url = p.get("url", "")
            if url and not url.startswith("http"):
                url = "https:" + url
                p["url"] = url
            p["price"] = self._parse_price(str(p.get("price", "0")))
            p["sales"] = self._parse_sales(str(p.get("sales", "0")))
            valid.append(p)

        logger.info("数据清洗完成: 总数=%d 自然位=%d 广告=%d 有效=%d",
                     len(raw_products), len(natural), ad_count, len(valid))
        return valid, ad_count


# ── 便捷函数 ──────────────────────────────────────────────

def parse_dts_export(filepath: str | Path) -> list[dict[str, Any]]:
    """解析DTS导出Excel的便捷函数。"""
    parser = DtsDataParser()
    products = parser.parse(filepath)
    return parser.normalize_products(products)
