"""隐患排查整改台账接口：登记/补录、状态顺向流转、重复并单、超期升办联动。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.hazard import STATUS_ORDER, hazard_service

router = APIRouter(prefix="/api/hazard", tags=["隐患排查整改"])

service = hazard_service

LIST_FIELDS = ["隐患编号", "隐患内容", "发现地点", "隐患等级", "责任单位", "责任人", "发现日期", "整改期限"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按隐患编号、内容、地点检索"),
    status: str | None = Query(default=None, description="待整改、整改中、待复查、已销号"),
    unit: str | None = Query(default=None, description="按责任单位过滤"),
    level: str | None = Query(default=None, description="按隐患等级过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """隐患台账列表：重复登记已并入的不单独建行，按发现日期从新到旧排列。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, unit=unit, level=level, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """台账指标卡：各状态数量、超期未整改与矿级督办数量。"""
    return {"items": service.stats()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出隐患排查整改台账全量数据（不含已并入的重复登记行）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "hazard", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条隐患的完整台账，含补充记录与全过程时间线。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"隐患 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条隐患；values.backfill=true 时为按发现日期补录存量。

    命中重复登记的不另开台账行，返回的是被并入的最早那条主记录。
    """
    entry, missing, message = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=message or "隐患登记失败，请核对填写内容")
    if message:
        return ActionResult(ok=True, message=message, entry=entry)
    if payload.values.get("backfill"):
        return ActionResult(ok=True, message="存量隐患已按发现日期补录", entry=entry)
    return ActionResult(ok=True, message="隐患已登记，状态为待整改", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """状态只能顺着待整改→整改中→待复查→已销号推进；复查结论不合格退回整改中。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
