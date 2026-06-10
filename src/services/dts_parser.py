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
        "现价", "售价", "成交价", "商品价格", "price", "销售价", "原价", "折扣价", "价格",
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
    "platform": [
        "平台", "platform",
    ],
    "shop_type": [
        "店铺类型", "shop_type", "卖家类型",
    ],
    "is_tmall": [
        "是否天猫", "天猫", "is_tmall",
    ],
    "location": [
        "所在地", "发货地", "location", "地址",
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
        # 实例变量拷贝，允许子类覆盖列映射
        self.column_patterns = dict(COLUMN_PATTERNS)

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
        all_rows = []
        total_ad_count = 0
        for row_num, row in enumerate(rows[1:], 2):
            record = {}
            for std_field, col_name in mapping.items():
                col_idx = raw_headers.index(col_name) if col_name in raw_headers else -1
                if col_idx >= 0 and col_idx < len(row):
                    val = row[col_idx]
                    record[std_field] = str(val).strip() if val is not None else ""
                else:
                    record[std_field] = ""

            pid = self.extract_product_id(record)
            if not pid:
                logger.debug("行%d: 无法提取商品ID，跳过", row_num)
                continue
            record["product_id"] = pid
            # 格式化
            record["price"] = self._parse_price(record.get("price", "0"))
            record["sales"] = self._parse_sales(record.get("sales", "0"))
            # 统计原始广告数
            if record.get("placeholder_type") == "广告位":
                total_ad_count += 1
            all_rows.append(record)

        # 去重：每个product_id只保留一条，优先保留"自然位"
        products = []
        seen_ids: dict[str, int] = {}
        dup_count = 0
        for record in all_rows:
            pid = record["product_id"]
            if pid in seen_ids:
                dup_count += 1
                existing_idx = seen_ids[pid]
                existing = products[existing_idx]
                if record.get("placeholder_type") == "自然位" and existing.get("placeholder_type") != "自然位":
                    products[existing_idx] = record
            else:
                seen_ids[pid] = len(products)
                products.append(record)

        # 存储解析统计供 clean_ad_data 使用
        self._parse_stats = {
            "total_rows": len(rows) - 1,
            "total_ad_count": total_ad_count,
            "total_dup_count": dup_count,
        }
        logger.info("解析完成: %d 个商品 (共%d行, 广告%d, 去重%d)", len(products), len(rows)-1, total_ad_count, dup_count)

        # 复制文件到 data/downloads
        self._archive_file(filepath)

        return products

    # ── 列名匹配 ─────────────────────────────────────────

    def _find_column_mapping(self, headers: list[str]) -> dict[str, str]:
        """自动识别Excel列名与标准字段的映射。

        使用模糊匹配：表头包含关键词即匹配成功。
        """
        mapping: dict[str, str] = {}

        for std_field, patterns in self.column_patterns.items():
            for pattern in patterns:
                for h in headers:
                    h_lower = h.lower()
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

    def clean_ad_data(self, raw_products: list[dict]) -> tuple[list[dict], int, int, int]:
        """清洗广告数据，返回(有效商品列表, 原始总行数, 广告数, 去重数)。

        使用 parse() 执行时存储的统计信息。
        """
        stats = getattr(self, '_parse_stats', {"total_rows": len(raw_products), "total_ad_count": 0, "total_dup_count": 0})

        # 只保留自然位
        natural = self.filter_natural_products(raw_products)

        # 过滤无效商品ID
        valid = []
        for p in natural:
            pid = p.get("product_id", "")
            if not pid or not re.match(r'^\d{8,20}$', str(pid)):
                continue
            url = p.get("url", "")
            if url and not url.startswith("http"):
                url = "https:" + url
                p["url"] = url
            valid.append(p)

        logger.info("数据清洗: 总计=%d 广告=%d 去重=%d 有效=%d",
                     stats["total_rows"], stats["total_ad_count"], stats["total_dup_count"], len(valid))
        return valid, stats["total_rows"], stats["total_ad_count"], stats["total_dup_count"]


# ── 京东解析器 ────────────────────────────────────────────

JD_COLUMN_PATTERNS: dict[str, list[str]] = {
    "product_id": ["商品ID", "SKUID", "id", "商品编码"],
    "title": ["商品标题", "标题", "商品名"],
    "price": ["现价", "价格", "售价", "京东价"],
    "sales": ["总销量", "销量", "累计销量"],
    "shop_name": ["店铺名称", "店铺", "商家"],
    "seller_name": ["掌柜名", "卖家", "供应商"],
    "url": ["商品链接", "链接", "商品地址", "URL"],
    "image_url": ["图片", "主图", "商品图片"],
    "placeholder_type": ["占位类型", "广告位类型", "推广类型"],
    "location": ["发货地", "所在地", "仓库"],
    "shop_type": ["店铺类型", "类型"],
    "daily_sales": ["日均销量", "日均付款人数"],
    "category": ["类目", "商品类目"],
    "is_tmall": ["是否自营", "自营"],
    "tags": ["标签", "商品标签"],
}


class JdDtsParser(DtsDataParser):
    """京东DTS解析器——继承淘宝解析器，仅覆盖列映射。

    复用父类全部逻辑（parse, clean_ad_data, filter_natural_products,
    extract_product_id, _parse_price, _parse_sales, normalize_products 等），
    只在初始化时替换列映射为京东版。
    """

    def __init__(self, output_dir=None):
        super().__init__(output_dir)
        self.column_patterns = dict(JD_COLUMN_PATTERNS)


# ── 便捷函数 ──────────────────────────────────────────────

def parse_dts_export(filepath: str | Path) -> list[dict[str, Any]]:
    """解析DTS导出Excel的便捷函数。"""
    parser = DtsDataParser()
    products = parser.parse(filepath)
    return parser.normalize_products(products)
