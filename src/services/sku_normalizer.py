"""SKU规格标准化服务

根据监控商品预定义的SKU分类，自动匹配SKU名称并计算单单位价格。
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
logger = logging.getLogger("sku_normalizer")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

# ── SKU分类关键词规则 ──
DEFAULT_CATEGORY_RULES: dict[str, list[str]] = {
    "袋装": ["袋", "袋装", "包", "小袋", "便携装"],
    "罐装": ["罐", "罐装", "听", "桶", "瓶", "铁罐"],
    "条装": ["条", "条装"],
    "混合装": ["混合", "组合", "套装", "礼盒", "混装", "多口味"],
    "盒装": ["盒", "盒装", "箱"],
}


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


class SkuNormalizer:
    """SKU规格标准化处理器"""

    def __init__(self, monitor_product_id: int):
        self.monitor_product_id = monitor_product_id
        self._categories: list[dict] = []
        self._rules: dict[str, list[str]] = {}
        self._load_categories()

    def _load_categories(self):
        """加载监控商品的预定义SKU分类。无自定义分类时回退到默认规则。"""
        conn = _get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    'SELECT * FROM "SkuCategory" WHERE monitor_product_id = %s ORDER BY id',
                    (self.monitor_product_id,),
                )
                self._categories = [dict(r) for r in cur.fetchall()]

            if self._categories:
                # 有自定义分类：构建关键词规则
                for cat in self._categories:
                    name = cat["name"]
                    # 从默认规则中匹配关键词
                    matched_default = False
                    for rule_name, keywords in DEFAULT_CATEGORY_RULES.items():
                        if rule_name in name or name in rule_name:
                            self._rules[name] = list(keywords)
                            matched_default = True
                            break
                    if not matched_default:
                        self._rules[name] = [name]
                    # 加载自学习关键词（从SkuCategory.keywords字段，逗号分隔）
                    self_learned = (cat.get("keywords") or "").strip()
                    if self_learned:
                        learned_list = [kw.strip().lower() for kw in self_learned.split(",") if kw.strip()]
                        for kw in learned_list:
                            if kw not in self._rules[name]:
                                self._rules[name].append(kw)
                        logger.debug("加载自学习关键词: cat=%s keywords=%s", name, learned_list)
            else:
                # 无自定义分类：使用所有默认规则
                for name, keywords in DEFAULT_CATEGORY_RULES.items():
                    self._categories.append({"id": 0, "name": name, "unit": name, "conversion_factor": 1.0})
                    self._rules[name] = keywords

            logger.debug("SKU分类加载: monitor_id=%d categories=%d",
                          self.monitor_product_id, len(self._categories))
        except Exception:
            logger.exception("加载SKU分类失败")
            self._categories = []
            self._rules = {}
        finally:
            conn.close()

    def match_sku_category(self, sku_name: str) -> dict | None:
        """根据SKU名称匹配分类（含默认规则+重量推断）"""
        if not sku_name or not self._rules:
            return None
        # 1. Keyword matching
        for cat in self._categories:
            name = cat["name"]
            keywords = self._rules.get(name, [name])
            for kw in keywords:
                if kw in sku_name:
                    return cat
        # 2. Weight fallback: 300g→袋装, 800g→罐装
        weight_cat = {'25':'条装','300':'袋装','400':'袋装','500':'袋装','800':'罐装','900':'罐装','1000':'罐装','1100':'罐装','1200':'罐装'}
        import re as _re
        m = _re.search(r'(\d+)\s*g', sku_name.lower())
        if m:
            base = weight_cat.get(m.group(1))
            if base:
                for cat in self._categories:
                    if cat['name'].startswith(base):
                        return cat
        return None

    def match_sku_category_with_detail(self, sku_name: str) -> dict | None:
        """匹配分类并返回命中关键词详情（供测试端点使用）"""
        if not sku_name or not self._rules:
            return None
        # 1. Keyword matching
        for cat in self._categories:
            name = cat["name"]
            keywords = self._rules.get(name, [name])
            for kw in keywords:
                if kw in sku_name:
                    return {
                        "category_id": cat["id"],
                        "category_name": name,
                        "matched_keyword": kw,
                        "match_type": "keyword",
                    }
        # 2. Weight fallback
        weight_cat_map = {'25':'条装','300':'袋装','400':'袋装','500':'袋装','800':'罐装','900':'罐装','1000':'罐装','1100':'罐装','1200':'罐装'}
        import re as _re
        m = _re.search(r'(\d+)\s*g', sku_name.lower())
        if m:
            base = weight_cat_map.get(m.group(1))
            if base:
                for cat in self._categories:
                    if cat['name'].startswith(base):
                        return {
                            "category_id": cat["id"],
                            "category_name": cat["name"],
                            "matched_keyword": f"重量推断({m.group(1)}g)",
                            "match_type": "weight",
                        }
        return None

    def extract_quantity(self, sku_name: str) -> int:
        """从SKU名称中提取数量信息。

        例如: "2袋装" → 2, "3罐礼盒" → 3, "单袋" → 1
        """
        # 匹配中文数字
        chinese_num = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                       "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                       "两": 2, "双": 2, "单": 1}
        for cn, num in chinese_num.items():
            if sku_name.startswith(cn):
                return num

        # 匹配阿拉伯数字开头
        m = re.match(r'^(\d+)\s*[袋罐听盒包条桶瓶]', sku_name)
        if m:
            return int(m.group(1))

        # 匹配 "xN" 格式
        m = re.search(r'[xX×](\d+)', sku_name)
        if m:
            return int(m.group(1))

        return 1

    def calculate_unit_price(
        self, sku_price: float, quantity: int, conversion_factor: float = 1.0
    ) -> float:
        """计算单单位价格。

        unit_price = sku_price / quantity * conversion_factor
        """
        if quantity <= 0:
            quantity = 1
        return round(sku_price / quantity * conversion_factor, 2)

    def normalize_sku(self, sku_name: str, sku_price: float) -> dict:
        """标准化单个SKU。

        Returns:
            {
                "sku_name": str,
                "sku_price": float,
                "category_id": int | None,
                "category_name": str | None,
                "quantity": int,
                "unit_price": float | None,
                "is_verified": bool,
            }
        """
        result: dict[str, Any] = {
            "sku_name": sku_name,
            "sku_price": sku_price,
            "category_id": None,
            "category_name": None,
            "quantity": 1,
            "unit_price": None,
            "is_verified": False,
        }

        quantity = self.extract_quantity(sku_name)
        result["quantity"] = quantity

        cat = self.match_sku_category(sku_name)
        if cat:
            result["category_id"] = cat["id"]
            result["category_name"] = cat["name"]
            result["is_verified"] = True
            result["unit_price"] = self.calculate_unit_price(
                sku_price, quantity, cat.get("conversion_factor", 1.0)
            )

        return result

    def normalize_skus(self, raw_skus: list[dict]) -> list[dict]:
        """批量标准化SKU列表。

        Args:
            raw_skus: [{"sku_name": "", "sku_price": 0, ...}]

        Returns:
            标准化后的SKU列表，含分类和单单位价格
        """
        results = []
        for sku in raw_skus:
            normalized = self.normalize_sku(
                sku.get("sku_name", ""),
                float(sku.get("sku_price", 0)),
            )
            normalized["sku_image_url"] = sku.get("sku_image_url")
            results.append(normalized)

        auto_matched = sum(1 for s in results if s["is_verified"])
        logger.info("SKU标准化: total=%d auto_matched=%d manual=%d",
                     len(results), auto_matched, len(results) - auto_matched)
        return results


def auto_classify_skus(monitor_product_id: int, taobao_product_id: str,
                       raw_skus: list[dict]) -> list[dict]:
    """便捷函数：加载分类规则并批量标准化SKU。"""
    normalizer = SkuNormalizer(monitor_product_id)
    return normalizer.normalize_skus(raw_skus)
