"""矿级督办台账业务规则。

与隐患台账（hazard）联动：
- 隐患超过整改期限仍未整改的，由 hazard 服务自动升办，在本清单单独排一行；
- 隐患状态推进、复查结论、销号都回写到本台账的待办清单，办理进度一起变；
- 销号后督办行同步置为「已销号」，历史上退回整改的也同步回「跟踪整改」。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "supervision"

STATUS_TRACKING = "跟踪整改"
STATUS_REVIEWING = "待复查"
STATUS_CLOSED = "已销号"
STATUS_ORDER = [STATUS_TRACKING, STATUS_REVIEWING, STATUS_CLOSED]


def _today() -> date:
    return date.today()


def _next_code(rows: list[dict[str, Any]]) -> str:
    return f"DB-{_today().isoformat().replace('-', '')}-{len(rows) + 1:03d}"


class SupervisionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        unit: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 督办清单打开时先跑一遍升办扫描，保证超期行“自动”出现。
        from app.services.hazard import hazard_service

        hazard_service.sweep_overdue()
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row for row in rows
                if key in str(row.get("督办编号", ""))
                or key in str(row.get("隐患编号", ""))
                or key in str(row.get("隐患内容", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if unit:
            rows = [row for row in rows if unit.strip() in str(row.get("责任单位", ""))]
        rows = sorted(rows, key=lambda row: (str(row.get("升办日期", "")), int(row.get("id", 0))), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [dict(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return dict(row) if row else None

    def stats(self) -> list[dict[str, object]]:
        from app.services.hazard import hazard_service

        hazard_service.sweep_overdue()
        rows = store.rows(MODULE)
        by_status = {name: 0 for name in STATUS_ORDER}
        overdue = 0
        for row in rows:
            by_status[str(row.get("status"))] = by_status.get(str(row.get("status")), 0) + 1
            if row.get("status") != STATUS_CLOSED:
                limit = self._parse_date(row.get("整改期限"))
                if limit is not None and limit < _today():
                    overdue += 1
        return [
            {"label": "督办总数", "value": len(rows)},
            {"label": "跟踪整改", "value": by_status[STATUS_TRACKING]},
            {"label": "待复查", "value": by_status[STATUS_REVIEWING]},
            {"label": "已销号", "value": by_status[STATUS_CLOSED]},
            {"label": "超期办理", "value": overdue},
        ]

    # ---------- 隐患侧联动入口 ----------
    def find_by_hazard(self, hazard_id: int) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if int(row.get("hazard_id", 0)) == hazard_id and not row.get("retargeted"):
                return row
        return None

    def escalate(self, hazard: dict[str, Any]) -> dict[str, Any]:
        """把一条超期隐患升成矿级督办行。已存在则直接返回，不重复建行。"""
        existing = self.find_by_hazard(int(hazard["id"]))
        if existing is not None:
            return existing
        rows = store.rows(MODULE)
        today = _today().isoformat()
        # 待办清单沿用隐患时间线（登记、整改、升办都在里面），后续靠游标增量回写。
        todo = [dict(event) for event in hazard.get("timeline", [])]
        ticket: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "督办编号": _next_code(rows),
            "hazard_id": int(hazard["id"]),
            "隐患编号": hazard.get("隐患编号", ""),
            "隐患内容": hazard.get("隐患内容", ""),
            "发现地点": hazard.get("发现地点", ""),
            "隐患等级": hazard.get("隐患等级", ""),
            "责任单位": hazard.get("责任单位", ""),
            "责任人": hazard.get("责任人", ""),
            "整改期限": hazard.get("整改期限", ""),
            "升办日期": today,
            "升办原因": f"超过整改期限 {hazard.get('整改期限', '—')} 仍未整改，自动升矿级督办",
            "办理进度": "已升矿级督办，等待责任单位反馈整改措施",
            "复查结论": "",
            "销号日期": "",
            "status": STATUS_TRACKING,
            "pending": True,
            "abnormal": True,
            "synced_events": len(todo),
            "待办清单": todo,
        }
        rows.append(ticket)
        return dict(ticket)

    def retarget(self, master_hazard_id: int, ticket_code: str) -> None:
        """重复隐患合并时，把挂在被并记录上的督办行改挂到主记录。"""
        for row in store.rows(MODULE):
            if row.get("督办编号") == ticket_code:
                row["hazard_id"] = master_hazard_id

    def sync_from_hazard(self, hazard: dict[str, Any]) -> dict[str, Any] | None:
        """隐患状态/复查结论变化后回写督办：进度、状态、待办清单一起更新。"""
        ticket = self.find_by_hazard(int(hazard["id"]))
        if ticket is None:
            return None
        cursor = int(ticket.get("synced_events", 0))
        events = list(hazard.get("timeline", []))
        for event in events[cursor:]:
            ticket.setdefault("待办清单", []).append(dict(event))
        ticket["synced_events"] = len(events)

        status = hazard.get("status")
        if status == "待复查":
            ticket["status"] = STATUS_REVIEWING
            ticket["办理进度"] = "责任单位已申请复查，等待复查结论"
            ticket["pending"] = True
            ticket["abnormal"] = False
        elif status == "整改中":
            ticket["status"] = STATUS_TRACKING
            ticket["pending"] = True
            ticket["abnormal"] = True
            # 复查不通过退回整改时，进度语要体现“复查未过、继续盯办”。
            if hazard.get("复查人") and not hazard.get("复查结论"):
                ticket["办理进度"] = "复查不通过已退回整改，矿上继续盯办"
            else:
                ticket["办理进度"] = "责任单位整改中，矿级督办持续跟踪"
        elif status == "已销号":
            # 销号结论原样回写到督办待办与办理结果。
            ticket["status"] = STATUS_CLOSED
            ticket["pending"] = False
            ticket["abnormal"] = False
            ticket["复查结论"] = hazard.get("复查结论", "")
            ticket["复查人"] = hazard.get("复查人", "")
            ticket["复查日期"] = hazard.get("复查日期", "")
            ticket["销号日期"] = hazard.get("销号日期", "")
            ticket["办理进度"] = f"复查{hazard.get('复查结论', '')}，已销号办结"
            ticket.setdefault("待办清单", []).append({
                "日期": hazard.get("销号日期", ""),
                "事项": "销号结论回写督办",
                "说明": f"复查人：{hazard.get('复查人', '—')}；结论：{hazard.get('复查结论', '—')}，督办办结",
            })
            # 办结事件是督办侧追加的，游标对齐到待办清单长度，避免下次同步重复。
            ticket["synced_events"] = len(events)
        return dict(ticket)

    # ---------- 督办自身动作：催办 ----------
    def urge(self, entry_id: int, note: str) -> tuple[dict[str, Any] | None, str]:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"督办单 {entry_id} 不存在"
        if row.get("status") == STATUS_CLOSED:
            return None, "该督办已随隐患销号办结，不再催办"
        today = _today().isoformat()
        row.setdefault("待办清单", []).append({"日期": today, "事项": "矿级催办", "说明": note or "电话/现场催办，要求限期整改"})
        row["办理进度"] = "已催办，等待责任单位反馈"
        return dict(row), "催办已记入督办待办清单"

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


supervision_service = SupervisionService()
