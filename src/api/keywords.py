"""关键词管理 API

提供关键词的增删改查功能。
权限：主管(manager)和管理员(admin)能增删改查，员工(staff)仅可查看。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth_service import get_current_user
from services.ga_service import run_diantoushi_export

load_dotenv()
logger = logging.getLogger("api.keywords")

DATABASE_URL = os.getenv("DATABASE_URL", "")
_SCHEMA = "price_monitor"

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


class KeywordCreate(BaseModel):
    name: str
    platform: str = "taobao"


class KeywordUpdate(BaseModel):
    name: str | None = None
    platform: str | None = None
    is_active: bool | None = None


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


def _check_write_permission(role: str) -> None:
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="权限不足，仅管理员和主管可以操作")


def _keyword_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "is_active": row["is_active"],
        "created_by": row["created_by"],
        "created_by_name": row.get("created_by_name", ""),
        "product_count": int(row.get("product_count", 0) or 0),
        "crawled_today": int(row.get("crawled_today", 0) or 0),
        "last_crawl_time": row.get("last_crawl_time").isoformat() if row.get("last_crawl_time") else None,
        "created_at": row["createdAt"].isoformat() if row.get("createdAt") else None,
    }


@router.get("/list")
def list_keywords(
    is_active: bool | None = None,
    platform: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions: list[str] = []
            params: list[Any] = []

            if is_active is not None:
                conditions.append("k.is_active = %s")
                params.append(is_active)
            if platform:
                conditions.append("k.platform = %s")
                params.append(platform)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            cur.execute(
                'SELECT k.*, u.username AS created_by_name, '
                "COUNT(pk.product_id) AS product_count, "
                "MAX(ph.recorded_at) AS last_crawl_time, "
                "COUNT(DISTINCT CASE WHEN ph.recorded_at::date = CURRENT_DATE THEN pk.product_id END) AS crawled_today "
                'FROM "Keyword" k '
                'LEFT JOIN "User" u ON k.created_by = u.id '
                'LEFT JOIN "ProductKeyword" pk ON k.id = pk.keyword_id '
                'LEFT JOIN "ProductHistory" ph ON ph.product_id = pk.product_id '
                f"{where} "
                "GROUP BY k.id, u.username "
                "ORDER BY k.\"createdAt\" DESC",
                params,
            )
            items = [_keyword_to_dict(r) for r in cur.fetchall()]

        return {"items": items, "total": len(items)}
    except Exception:
        logger.exception("查询关键词列表失败")
        raise HTTPException(status_code=500, detail="查询关键词列表失败")
    finally:
        conn.close()


@router.post("/create")
def create_keyword(
    body: KeywordCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                'SELECT id FROM "Keyword" WHERE name = %s AND platform = %s',
                (body.name, body.platform),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="关键词已存在")

            cur.execute(
                'INSERT INTO "Keyword" (name, platform, created_by) '
                "VALUES (%s, %s, %s) RETURNING id",
                (body.name, body.platform, current_user["user_id"]),
            )
            keyword_id = cur.fetchone()["id"]
            conn.commit()

            cur.execute(
                'SELECT k.*, u.username AS created_by_name '
                'FROM "Keyword" k '
                'LEFT JOIN "User" u ON k.created_by = u.id '
                "WHERE k.id = %s",
                (keyword_id,),
            )
            row = cur.fetchone()
            if row:
                item = _keyword_to_dict(row)
        logger.info("关键词已创建: %s (by %s)", body.name, current_user["username"])
        return {"success": True, "item": item}
    except HTTPException:
        raise
    except Exception:
        logger.exception("创建关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="创建关键词失败")
    finally:
        conn.close()


@router.put("/{keyword_id}")
def update_keyword(
    keyword_id: int,
    body: KeywordUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT id FROM "Keyword" WHERE id = %s', (keyword_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="关键词不存在")

            updates: list[str] = []
            params: list[Any] = []

            if body.name is not None:
                updates.append("name = %s")
                params.append(body.name)
            if body.platform is not None:
                updates.append("platform = %s")
                params.append(body.platform)
            if body.is_active is not None:
                updates.append("is_active = %s")
                params.append(body.is_active)

            if updates:
                params.append(keyword_id)
                cur.execute(
                    f'UPDATE "Keyword" SET {", ".join(updates)} WHERE id = %s',
                    params,
                )
                conn.commit()

        logger.info("关键词已更新: id=%d (by %s)", keyword_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("更新关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="更新关键词失败")
    finally:
        conn.close()


@router.post("/batch-toggle")
def batch_toggle(
    ids: list[int],
    is_active: bool,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f'UPDATE "Keyword" SET is_active = %s WHERE id IN ({placeholders})',
                [is_active] + ids,
            )
            affected = cur.rowcount
            conn.commit()

        logger.info("批量切换关键词: ids=%s, is_active=%s, affected=%d (by %s)",
                     ids, is_active, affected, current_user["username"])
        return {"success": True, "affected": affected}
    except Exception:
        logger.exception("批量切换关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="批量切换关键词失败")
    finally:
        conn.close()


@router.delete("/{keyword_id}")
def delete_keyword(
    keyword_id: int,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "ProductKeyword" WHERE keyword_id = %s', (keyword_id,))
            cur.execute('DELETE FROM "Keyword" WHERE id = %s', (keyword_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="关键词不存在")
            conn.commit()

        logger.info("关键词已删除: id=%d (by %s)", keyword_id, current_user["username"])
        return {"success": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("删除关键词失败")
        conn.rollback()
        raise HTTPException(status_code=500, detail="删除关键词失败")
    finally:
        conn.close()


class SearchRequest(BaseModel):
    keyword_id: int | None = None


_search_tasks: dict[str, dict[str, Any]] = {}
_search_lock = threading.Lock()


def _run_keyword_search(keyword_id: int, keyword_name: str, task_id: str) -> None:
    logger.info("开始搜索关键词: id=%d name=%s", keyword_id, keyword_name)
    try:
        result = run_diantoushi_export(keyword_name)
        with _search_lock:
            if result:
                _search_tasks[task_id] = {
                    "status": "completed",
                    "keyword_id": keyword_id,
                    "keyword_name": keyword_name,
                    "result": result,
                    "message": f"搜索完成，已导出数据到 {result}",
                    "started_at": _search_tasks.get(task_id, {}).get("started_at", 0),
                    "finished_at": time.time(),
                }
            else:
                _search_tasks[task_id] = {
                    "status": "failed",
                    "keyword_id": keyword_id,
                    "keyword_name": keyword_name,
                    "message": "导出失败：淘宝未登录或搜索被反爬系统拦截。请在「系统设置 → 淘宝登录」中扫码登录后再试",
                    "started_at": _search_tasks.get(task_id, {}).get("started_at", 0),
                    "finished_at": time.time(),
                }
    except Exception as e:
        error_msg = str(e)[:300]
        logger.exception("关键词搜索异常: id=%d name=%s", keyword_id, keyword_name)
        with _search_lock:
            _search_tasks[task_id] = {
                "status": "failed",
                "keyword_id": keyword_id,
                "keyword_name": keyword_name,
                "message": f"搜索异常: {error_msg}",
                "started_at": _search_tasks.get(task_id, {}).get("started_at", 0),
                "finished_at": time.time(),
            }


@router.post("/search")
def search_keywords(
    body: SearchRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    _check_write_permission(current_user["role"])

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if body.keyword_id:
                cur.execute(
                    'SELECT id, name FROM "Keyword" WHERE id = %s',
                    (body.keyword_id,),
                )
                kws = cur.fetchall()
            else:
                cur.execute(
                    'SELECT id, name FROM "Keyword" WHERE is_active = true',
                )
                kws = cur.fetchall()
    finally:
        conn.close()

    if not kws:
        return {"success": False, "message": "没有找到需要搜索的关键词"}

    import uuid
    task_ids: list[str] = []
    now = time.time()
    for kw in kws:
        task_id = f"kw_{kw['id']}_{uuid.uuid4().hex[:6]}"
        with _search_lock:
            _search_tasks[task_id] = {
                "status": "running",
                "keyword_id": kw["id"],
                "keyword_name": kw["name"],
                "started_at": now,
            }
        t = threading.Thread(
            target=_run_keyword_search,
            args=(kw["id"], kw["name"], task_id),
            daemon=True,
        )
        t.start()
        task_ids.append(task_id)

    logger.info(
        "关键词搜索已触发: count=%d ids=%s by %s",
        len(kws), [kw["id"] for kw in kws], current_user["username"],
    )
    return {
        "success": True,
        "message": f"已开始搜索 {len(kws)} 个关键词",
        "task_ids": task_ids,
        "keyword_count": len(kws),
    }


@router.get("/search/status")
def search_status(
    task_ids: str = "",
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取搜索任务状态。运行超过20分钟的任务自动标记为失败。"""
    ids = [t for t in task_ids.split(",") if t]
    TASK_TIMEOUT_SECONDS = 20 * 60

    with _search_lock:
        if ids:
            tasks = {tid: dict(_search_tasks.get(tid, {"status": "unknown"})) for tid in ids}
        else:
            tasks = {tid: dict(t) for tid, t in _search_tasks.items()}

    now = time.time()
    for tid, task in tasks.items():
        if task.get("status") == "running":
            started_at = task.get("started_at", 0)
            if started_at > 0 and now - started_at > TASK_TIMEOUT_SECONDS:
                task["status"] = "failed"
                task["message"] = f"搜索超时（已运行 {int((now - started_at) / 60)} 分钟），可能淘宝未登录或被反爬拦截，请检查扩展状态并在系统设置中扫码登录"
                with _search_lock:
                    if tid in _search_tasks:
                        _search_tasks[tid]["status"] = "failed"
                        _search_tasks[tid]["message"] = task["message"]

    running = sum(1 for t in tasks.values() if t.get("status") == "running")
    completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
    failed = sum(1 for t in tasks.values() if t.get("status") == "failed")

    return {
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "running": running,
            "completed": completed,
            "failed": failed,
        },
        "all_done": running == 0,
    }
