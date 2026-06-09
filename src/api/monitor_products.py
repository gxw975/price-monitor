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
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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


def require_write_permission(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """FastAPI 依赖：校验写入权限（admin/manager）"""
    _check_write_permission(current_user["role"])
    return current_user


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
    brand: str | None = None
    description: str | None = None
    price_threshold_bag: float | None = None
    price_threshold_can: float | None = None
    price_threshold_mix: float | None = None
    sales_threshold: float | None = None


class MonitorProductUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    description: str | None = None
    price_threshold_bag: float | None = None
    price_threshold_can: float | None = None
    price_threshold_mix: float | None = None
    sales_threshold: float | None = None
    whitelist_sellers: str | None = None

class ConfirmImportRequest(BaseModel):
    file_name: str
    selected_product_ids: list[str]
    products_data: list[dict] = []  # full product data from preview


class SkuCategoryCreate(BaseModel):
    name: str
    unit: str = ""
    conversion_factor: float = 1.0


# ═══════════════════════════════════════════════
# 监控商品 CRUD
# ═══════════════════════════════════════════════

@router.get("/")
@router.get("", include_in_schema=False)
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


@router.post("/", dependencies=[Depends(require_write_permission)])
@router.post("", dependencies=[Depends(require_write_permission)], include_in_schema=False)
def create_monitor_product(
    body: MonitorProductCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """新增监控商品"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'INSERT INTO "MonitorProduct" (name, brand, description, price_threshold_bag, price_threshold_can, price_threshold_mix, sales_threshold) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *',
                (body.name, body.brand, body.description, body.price_threshold_bag,
                 body.price_threshold_can, body.price_threshold_mix, body.sales_threshold),
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


@router.put("/{product_id}", dependencies=[Depends(require_write_permission)])
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
            for field in ['name', 'brand', 'description', 'price_threshold_bag',
                          'price_threshold_can', 'price_threshold_mix', 'sales_threshold',
                          'whitelist_sellers']:
                val = getattr(body, field, None)
                if val is not None:
                    updates.append(f'{field} = %s')
                    params.append(val)
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


@router.delete("/{product_id}", dependencies=[Depends(require_write_permission)])
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


@router.post("/{product_id}/sku-categories", dependencies=[Depends(require_write_permission)])
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


@router.delete("/{product_id}/sku-categories/{cat_id}", dependencies=[Depends(require_write_permission)])
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


@router.delete("/{product_id}/imports/{batch_id}", dependencies=[Depends(require_write_permission)])
def delete_import_batch(
    product_id: int,
    batch_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """删除导入批次及其商品数据"""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            # 先删除所有子表记录 (否则外键约束阻止删除Product)
            cur.execute(
                'DELETE FROM "ProductHistory" WHERE product_id IN (SELECT product_id FROM "Product" WHERE import_batch_id=%s AND monitor_product_id=%s)',
                (batch_id, product_id),
            )
            cur.execute(
                'DELETE FROM "ProductSku" WHERE product_id IN (SELECT product_id FROM "Product" WHERE import_batch_id=%s AND monitor_product_id=%s)',
                (batch_id, product_id),
            )
            cur.execute(
                'DELETE FROM "ProductKeyword" WHERE product_id IN (SELECT product_id FROM "Product" WHERE import_batch_id=%s AND monitor_product_id=%s)',
                (batch_id, product_id),
            )
            cur.execute(
                'DELETE FROM "Alert" WHERE product_id IN (SELECT product_id FROM "Product" WHERE import_batch_id=%s AND monitor_product_id=%s)',
                (batch_id, product_id),
            )
            # 删除该批次的商品
            cur.execute(
                'DELETE FROM "Product" WHERE import_batch_id=%s AND monitor_product_id=%s',
                (batch_id, product_id),
            )
            prod_deleted = cur.rowcount
            # 删除批次记录
            cur.execute(
                'DELETE FROM "ImportBatch" WHERE id=%s AND monitor_product_id=%s',
                (batch_id, product_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="批次不存在")
            conn.commit()
        logger.info("删除导入批次: batch=%d products=%d by %s", batch_id, prod_deleted, current_user["username"])
        return {"success": True, "products_deleted": prod_deleted}
    except HTTPException: raise
    except Exception:
        logger.exception("删除批次失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除失败")
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# 商品列表 + 预警
# ═══════════════════════════════════════════════

@router.get("/{product_id}/products")
def list_products(
    product_id: int,
    keyword: str | None = None,
    limit: int = 200,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取监控商品下的所有淘宝商品"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if keyword:
                cur.execute(
                    'SELECT *, sales_volume AS sales FROM "Product" WHERE monitor_product_id=%s AND (title ILIKE %s OR shop_name ILIKE %s OR product_id ILIKE %s) ORDER BY last_updated_at DESC LIMIT %s',
                    (product_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
                )
            else:
                cur.execute(
                    'SELECT *, sales_volume AS sales FROM "Product" WHERE monitor_product_id=%s ORDER BY last_updated_at DESC LIMIT %s',
                    (product_id, limit),
                )
            items = [dict(r) for r in cur.fetchall()]
            for item in items:
                for df in ('created_at', 'last_updated_at', 'last_sku_crawled_at'):
                    if item.get(df): item[df] = item[df].isoformat()
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询商品列表失败")
        raise HTTPException(status_code=500, detail="查询失败")
    finally:
        conn.close()


@router.get("/{product_id}/alerts")
def list_alerts_for_product(
    product_id: int,
    limit: int = 50,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取监控商品的所有预警记录"""
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT a.*, p.title AS product_title FROM "Alert" a LEFT JOIN "Product" p ON a.product_id=p.product_id WHERE a.monitor_product_id=%s ORDER BY a.created_at DESC LIMIT %s',
                (product_id, limit),
            )
            items = [dict(r) for r in cur.fetchall()]
            for item in items:
                for df in ('created_at', 'sent_at', 'handled_at'):
                    if item.get(df): item[df] = item[df].isoformat()
        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询预警失败")
        raise HTTPException(status_code=500, detail="查询失败")
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# Excel 导入（两阶段）
# ═══════════════════════════════════════════════

@router.post("/{product_id}/import", dependencies=[Depends(require_write_permission)])
async def import_excel_preview(
    product_id: int,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """阶段A — 上传DTS Excel，返回清洗后的预览数据"""
    import os as _os, tempfile as _tempfile, uuid as _uuid
    from pathlib import Path as _Path

    temp_path = ""
    try:
        if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="仅支持Excel文件格式")

        suffix = _Path(file.filename).suffix
        temp_path = _os.path.join(_tempfile.gettempdir(), f"dts_import_{_uuid.uuid4().hex}{suffix}")
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        from services.dts_parser import DtsDataParser
        parser = DtsDataParser()
        parsed = parser.parse(temp_path)
        if not parsed:
            raise HTTPException(status_code=400, detail="Excel解析失败")
        valid, total_count, ad_count, dup_count = parser.clean_ad_data(parsed)

        return {"code": 200, "msg": "解析成功", "data": {
            "file_name": file.filename, "total_count": total_count,
            "ad_count": ad_count, "dup_count": dup_count, "valid_count": len(valid), "preview_data": valid,
        }}
    except HTTPException: raise
    except Exception as e:
        logger.exception("Excel预览失败")
        raise HTTPException(status_code=500, detail=f"解析失败：{e}")
    finally:
        if temp_path and _os.path.exists(temp_path):
            try: _os.unlink(temp_path)
            except OSError: pass


@router.post("/{product_id}/import/confirm", dependencies=[Depends(require_write_permission)])
def confirm_import(
    product_id: int,
    data: ConfirmImportRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """阶段B — 确认导入"""
    conn = _get_conn()
    try:
        if not data.selected_product_ids:
            raise HTTPException(status_code=400, detail="未选择任何商品")

        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "ImportBatch" (monitor_product_id, file_name, total_count, ad_count, valid_count, imported_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                (product_id, data.file_name, len(data.selected_product_ids), 0, len(data.selected_product_ids), current_user.get("user_id")),
            )
            batch_id = cur.fetchone()[0]
            conn.commit()

        # Build a lookup from product_id to full data
        products_map = {p.get('product_id', ''): p for p in data.products_data}

        inserted = 0
        from services.product_service import _get_conn as svc_conn_fn
        svc = svc_conn_fn()
        try:
            for pid in data.selected_product_ids:
                try:
                    pdata = products_map.get(pid, {})
                    title = (pdata.get('title') or pdata.get('商品名称') or pid)[:200]
                    image_url = (pdata.get('image_url') or pdata.get('main_image_url') or '')[:500]
                    shop_name = (pdata.get('shop_name') or pdata.get('shop') or '')[:200]
                    seller_name = (pdata.get('seller_name') or '')[:100]
                    price = float(pdata.get('price', 0) or 0)
                    sales = int(pdata.get('sales', 0) or 0)
                    url = (pdata.get('url') or '')[:500]
                    platform = (pdata.get('platform') or '')[:50]
                    shop_type = (pdata.get('shop_type') or '')[:50]
                    location = (pdata.get('location') or '')[:100]

                    with svc.cursor() as cur:
                        cur.execute('SELECT product_id FROM "Product" WHERE product_id=%s', (pid,))
                        if cur.fetchone():
                            cur.execute(
                                'UPDATE "Product" SET monitor_product_id=%s, import_batch_id=%s, title=%s, main_image_url=%s, shop_name=%s, seller_name=%s, product_url=%s, platform=%s, shop_type=%s, location=%s, price=%s, sales_volume=%s, last_updated_at=NOW() WHERE product_id=%s',
                                (product_id, batch_id, title, image_url, shop_name, seller_name, url, platform, shop_type, location, price, sales, pid))
                        else:
                            cur.execute(
                                'INSERT INTO "Product" (product_id, title, main_image_url, shop_name, seller_name, product_url, platform, shop_type, location, price, sales_volume, monitor_product_id, import_batch_id, is_approved, is_whitelist, created_at, last_updated_at) '
                                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,FALSE,NOW(),NOW())',
                                (pid, title, image_url, shop_name, seller_name, url, platform, shop_type, location, price, sales, product_id, batch_id))
                        # Record price/sales history
                        if price > 0:
                            cur.execute(
                                'INSERT INTO "ProductHistory" (product_id, price, sales_volume, recorded_at) VALUES (%s,%s,%s,NOW())',
                                (pid, price, sales))
                        inserted += 1
                    svc.commit()
                except Exception:
                    svc.rollback()
                    logger.exception("插入失败: %s", pid)
        finally:
            svc.close()

        with conn.cursor() as cur:
            cur.execute('UPDATE "ImportBatch" SET valid_count=%s WHERE id=%s', (inserted, batch_id))
            conn.commit()

        from scripts.check_alerts import run_alerts
        ar = run_alerts(test_mode=False, force=False)

        return {"code": 200, "msg": "导入成功", "data": {
            "batch_id": batch_id, "import_result": {"success_count": inserted, "fail_count": len(data.selected_product_ids)-inserted, "total": len(data.selected_product_ids)},
            "alert_result": {"checked": ar.get("checked",0), "sent": ar.get("sent",0)},
        }}
    except HTTPException: raise
    except Exception as e:
        logger.exception("确认导入失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")
    finally:
        conn.close()
