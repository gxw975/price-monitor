"""监控商品管理 API

提供监控商品的增删改查、SKU分类管理、导入历史查询。
权限：查看全员可访问，写入仅admin/manager。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth_service import get_current_user

load_dotenv()
logger = logging.getLogger("api.monitor_products")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/monitor-products", tags=["监控商品"])


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


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


class MonitorProductCreate(BaseModel):
    name: str
    description: str | None = None


class MonitorProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class SkuCategoryCreate(BaseModel):
    name: str
    unit: str = ""
    conversion_factor: float = 1.0


# ═══════════════════════════════════════════════
# 监控商品 CRUD
# ═══════════════════════════════════════════════

@router.get("/")
def list_monitor_products(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取所有监控商品（含导入批次计数）"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT mp.*,
                    COUNT(DISTINCT ib.id) AS import_count,
                    MAX(ib.import_time) AS last_import_time,
                    COUNT(DISTINCT a.id) FILTER (WHERE a.is_handled = FALSE) AS unhandled_alert_count
                FROM "MonitorProduct" mp
                LEFT JOIN "ImportBatch" ib ON ib.monitor_product_id = mp.id
                LEFT JOIN "Alert" a ON a.monitor_product_id = mp.id
                GROUP BY mp.id
                ORDER BY mp.updated_at DESC
            """)
            items = [dict(r) for r in cur.fetchall()]
            for item in items:
                if item.get("last_import_time"):
                    item["last_import_time"] = item["last_import_time"].isoformat()
                if item.get("created_at"):
                    item["created_at"] = item["created_at"].isoformat()
                if item.get("updated_at"):
                    item["updated_at"] = item["updated_at"].isoformat()
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询监控商品列表失败")
        raise HTTPException(status_code=500, detail="查询失败")
    finally:
        conn.close()


@router.post("/", dependencies=[Depends(_check_write_permission)])
def create_monitor_product(
    body: MonitorProductCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """新增监控商品"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'INSERT INTO "MonitorProduct" (name, description) VALUES (%s, %s) RETURNING *',
                (body.name, body.description),
            )
            item = dict(cur.fetchone())
            conn.commit()
        logger.info("创建监控商品: id=%d name=%s by %s", item["id"], body.name, current_user["username"])
        return {"success": True, "data": item}
    except Exception:
        logger.exception("创建监控商品失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="创建失败")
    finally:
        conn.close()


@router.put("/{product_id}", dependencies=[Depends(_check_write_permission)])
def update_monitor_product(
    product_id: int,
    body: MonitorProductUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """编辑监控商品"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            updates = []
            params = []
            if body.name is not None:
                updates.append('name = %s')
                params.append(body.name)
            if body.description is not None:
                updates.append('description = %s')
                params.append(body.description)
            if not updates:
                raise HTTPException(status_code=400, detail="无更新内容")
            updates.append('updated_at = NOW()')
            params.append(product_id)
            cur.execute(
                f'UPDATE "MonitorProduct" SET {", ".join(updates)} WHERE id = %s RETURNING *',
                params,
            )
            item = cur.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="监控商品不存在")
            conn.commit()
        logger.info("更新监控商品: id=%d by %s", product_id, current_user["username"])
        return {"success": True, "data": dict(item)}
    except HTTPException:
        raise
    except Exception:
        logger.exception("更新监控商品失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="更新失败")
    finally:
        conn.close()


@router.delete("/{product_id}", dependencies=[Depends(_check_write_permission)])
def delete_monitor_product(
    product_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """删除监控商品"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "MonitorProduct" WHERE id = %s', (product_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="监控商品不存在")
            conn.commit()
        logger.info("删除监控商品: id=%d by %s", product_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除监控商品失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除失败")
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# SKU 分类管理
# ═══════════════════════════════════════════════

@router.get("/{product_id}/sku-categories")
def list_sku_categories(
    product_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取监控商品的SKU分类列表"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT * FROM "SkuCategory" WHERE monitor_product_id = %s ORDER BY id',
                (product_id,),
            )
            items = [dict(r) for r in cur.fetchall()]
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询SKU分类失败")
        raise HTTPException(status_code=500, detail="查询失败")
    finally:
        conn.close()


@router.post("/{product_id}/sku-categories", dependencies=[Depends(_check_write_permission)])
def create_sku_category(
    product_id: int,
    body: SkuCategoryCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """新增SKU分类"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'INSERT INTO "SkuCategory" (monitor_product_id, name, unit, conversion_factor) '
                'VALUES (%s, %s, %s, %s) RETURNING *',
                (product_id, body.name, body.unit, body.conversion_factor),
            )
            item = dict(cur.fetchone())
            conn.commit()
        logger.info("创建SKU分类: id=%d name=%s by %s", item["id"], body.name, current_user["username"])
        return {"success": True, "data": item}
    except Exception:
        logger.exception("创建SKU分类失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="创建失败")
    finally:
        conn.close()


@router.delete("/{product_id}/sku-categories/{cat_id}", dependencies=[Depends(_check_write_permission)])
def delete_sku_category(
    product_id: int,
    cat_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """删除SKU分类"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "SkuCategory" WHERE id = %s AND monitor_product_id = %s',
                (cat_id, product_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="SKU分类不存在")
            conn.commit()
        logger.info("删除SKU分类: id=%d by %s", cat_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除SKU分类失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除失败")
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# 导入历史
# ═══════════════════════════════════════════════

@router.get("/{product_id}/imports")
def list_imports(
    product_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取监控商品的导入历史"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT ib.*, u.username AS imported_by_name
                FROM "ImportBatch" ib
                LEFT JOIN "User" u ON u.id = ib.imported_by
                WHERE ib.monitor_product_id = %s
                ORDER BY ib.import_time DESC
                LIMIT 50
            """, (product_id,))
            items = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get("import_time"):
                    d["import_time"] = d["import_time"].isoformat()
                items.append(d)
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询导入历史失败")
        raise HTTPException(status_code=500, detail="查询失败")
    finally:
        conn.close()
