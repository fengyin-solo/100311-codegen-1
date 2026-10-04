"""矿级督办台账接口：超期隐患自动升办后的督办清单、催办与销号结论回写。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.supervision import STATUS_ORDER, supervision_service

router = APIRouter(prefix="/api/supervision", tags=["矿级督办"])

service = supervision_service

LIST_FIELDS = ["督办编号", "隐患编号", "隐患内容", "责任单位", "责任人", "升办日期", "整改期限", "办理进度", "督办状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按督办编号、隐患编号、内容检索"),
    status: str | None = Query(default=None, description="跟踪整改、待复查、已销号"),
    unit: str | None = Query(default=None, description="按责任单位过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """督办清单：每条超期升办的隐患单独排一行，进度与隐患台账同步。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, unit=unit, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """督办指标卡：各督办状态数量与超期办理数量。"""
    return {"items": service.stats()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出矿级督办清单全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "supervision", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条督办行，含待办清单全过程记录。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"督办单 {entry_id} 不存在")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """督办侧动作：催办（在待办清单里记一行催办记录）。状态推进由隐患台账联动。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "催办":
        return ActionResult(ok=False, message=f"动作「{action}」不属于矿级督办可执行范围（督办进度随隐患复查与销号自动更新）")
    note = str(payload.values.get("说明") or "").strip()
    entry, message = service.urge(entry_id, note)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
