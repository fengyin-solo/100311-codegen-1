"""隐患排查整改台账接口：登记、查重合并、状态流转、矿级督办清单与存量补录。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.hazard import HazardService

router = APIRouter(prefix="/api/hazard", tags=["隐患排查整改台账"])

service = HazardService()

LIST_FIELDS = ["隐患编号", "发现日期", "隐患地点", "隐患内容", "责任单位", "整改期限", "复查结论", "状态"]
STATUSES = ["待整改", "整改中", "待复查", "已销号"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按隐患编号或内容检索"),
    status: str | None = Query(default=None, description="待整改、整改中、待复查、已销号"),
    unit: str | None = Query(default=None, description="按责任单位检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号/内容、状态、责任单位过滤隐患台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, unit=unit, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/supervision")
def supervision_entries() -> dict[str, Any]:
    """矿级督办清单：超期未整改自动升入，销号结论与进度随台账一起更新。"""
    items = service.supervision_list()
    return {"module": "hazard", "total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出隐患排查整改台账：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "hazard", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条隐患明细（含补充记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"隐患 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条隐患；重复登记并入最早一条，存量补录按发现日期与历史结论原样保留。"""
    entry, missing, merged = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if merged:
        return ActionResult(ok=True, message="同一隐患已登记过，本次并入最早一条作为补充记录", entry=entry)
    return ActionResult(ok=True, message=f"隐患已登记，状态为「{entry.get('status', '待整改')}」", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条隐患执行开始整改、整改完成、复查销号；跳级、回退、无结论销号都会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
