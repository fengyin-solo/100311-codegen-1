"""隐患排查整改台账业务规则：状态机、重复登记合并、超期督办与存量补录口径。

台账口径来自安全检查整改要求：
- 状态只能顺着 待整改 → 整改中 → 待复查 → 已销号 往下走，不许跳级、不许回退；
- 没有复查结论不得销号；已销号归档的记录任何动作都拦下；
- 同一隐患重复登记只保留最早那条，后续登记并成它的补充记录；
- 超期未整改自动升矿级督办，销号结论回写督办清单待办进度；
- 存量数据按发现日期补录，历史销号结论按当时口径保留，不改写。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "hazard"
REQUIRED_FIELDS = ["隐患地点", "隐患内容", "责任单位", "整改期限", "登记人"]
BACKFILL_REQUIRED_FIELDS = ["隐患地点", "隐患内容", "责任单位", "发现日期"]
STATUS_ORDER = ["待整改", "整改中", "待复查", "已销号"]
ACTION_RULES = {"开始整改": ("待整改", "整改中"), "整改完成": ("整改中", "待复查"), "复查销号": ("待复查", "已销号")}
SUPERVISE_LEVEL = "矿级督办"
BACKFILL_SOURCE = "存量补录"


def _parse_day(value: Any) -> date | None:
    """把 YYYY-MM-DD 字符串解析成日期；解析不了返回 None，由调用方决定要不要拦。"""
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _dedup_key(values: dict[str, Any]) -> tuple[str, str]:
    """同一隐患的判定口径：地点 + 内容都一致才算重复登记。"""
    return _text(values.get("隐患地点")), _text(values.get("隐患内容"))


def _is_overdue(entry: dict[str, Any], today: date) -> bool:
    if entry.get("status") == STATUS_ORDER[-1]:
        return False
    deadline = _parse_day(entry.get("整改期限"))
    return deadline is not None and deadline < today


class HazardService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        unit: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("隐患编号", "")) or keyword in str(row.get("隐患内容", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if unit:
            rows = [row for row in rows if unit in str(row.get("责任单位", ""))]
        rows = sorted(rows, key=lambda row: (str(row.get("发现日期", "")), int(row.get("id", 0))), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记隐患；返回 (台账记录, 缺字段, 是否并入已有记录)。

        重复登记命中已有隐患时，不新建记录，把本次登记并成最早那条的补充记录。
        """
        backfill = _text(values.get("登记方式")) == BACKFILL_SOURCE
        required = BACKFILL_REQUIRED_FIELDS if backfill else REQUIRED_FIELDS
        missing = [field for field in required if not _text(values.get(field))]
        if backfill and _text(values.get("历史状态")) == STATUS_ORDER[-1] and not _text(values.get("复查结论")):
            # 补录的历史销号记录必须带着当时的复查结论，否则台账里就说不清依据
            missing.append("复查结论")
        if missing:
            return None, missing, False

        rows = store.rows(MODULE)
        key = _dedup_key(values)
        duplicates = [row for row in rows if _dedup_key(row) == key]
        if duplicates:
            canonical = min(duplicates, key=lambda row: (str(row.get("发现日期", "")), int(row.get("id", 0))))
            canonical.setdefault("supplements", []).append({
                "登记人": _text(values.get("登记人")) or "未署名",
                "发现日期": _text(values.get("发现日期")),
                "整改期限": _text(values.get("整改期限")),
                "补充说明": _text(values.get("补充说明")) or "重复登记并入",
            })
            return canonical, [], True

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["隐患编号"] = f"HAZ-{entry['id']:04d}"
        for field in ["隐患地点", "隐患内容", "隐患等级", "责任单位", "登记人", "整改期限", "整改措施"]:
            entry[field] = _text(values.get(field))
        entry["发现日期"] = _text(values.get("发现日期")) or date.today().isoformat()
        entry["登记方式"] = BACKFILL_SOURCE if backfill else "新登记"
        entry["supplements"] = []
        if backfill:
            # 存量补录：状态与复查结论都按历史原样保留，不按新口径改写
            entry["status"] = _text(values.get("历史状态")) if _text(values.get("历史状态")) in STATUS_ORDER else STATUS_ORDER[0]
            entry["复查结论"] = _text(values.get("复查结论"))
            entry["销号日期"] = _text(values.get("销号日期"))
        else:
            entry["status"] = STATUS_ORDER[0]
            entry["复查结论"] = ""
            entry["销号日期"] = ""
        entry["pending"] = entry["status"] != STATUS_ORDER[-1]
        entry["abnormal"] = _is_overdue(entry, date.today())
        rows.append(entry)
        return entry, [], False

    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"隐患 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于隐患整改可执行范围"
        source, target = ACTION_RULES[action]
        current = str(entry.get("status", ""))
        if current == STATUS_ORDER[-1]:
            return None, "该隐患已销号归档，不能再退回待整改或执行其他动作"
        if current != source:
            return None, f"当前状态「{current}」不能执行「{action}」，状态只能按 {'→'.join(STATUS_ORDER)} 顺序流转"
        if action == "复查销号":
            conclusion = _text(values.get("复查结论"))
            if not conclusion:
                return None, "缺少复查结论，不得销号"
            entry["复查结论"] = conclusion
            entry["销号日期"] = date.today().isoformat()
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = _is_overdue(entry, date.today())
        return entry, f"隐患已{action}，状态更新为「{target}」"

    def supervision_list(self) -> list[dict[str, Any]]:
        """矿级督办清单：超期未整改的隐患自动升入，每条单独排一行。

        销号后记录不撤下，进度改写为「已办结」并把销号结论回写进来，
        待办清单的进度跟着隐患状态一起变。
        """
        today = date.today()
        items: list[dict[str, Any]] = []
        for entry in store.rows(MODULE):
            deadline = _parse_day(entry.get("整改期限"))
            if deadline is None:
                continue
            closed = entry.get("status") == STATUS_ORDER[-1]
            close_day = _parse_day(entry.get("销号日期"))
            overdue_now = not closed and deadline < today
            overdue_when_closed = closed and close_day is not None and close_day > deadline
            if not (overdue_now or overdue_when_closed):
                continue
            overdue_days = ((close_day if closed and close_day else today) - deadline).days
            items.append({
                "督办编号": f"SUP-{int(entry.get('id', 0)):04d}",
                "隐患编号": entry.get("隐患编号", ""),
                "隐患内容": entry.get("隐患内容", ""),
                "责任单位": entry.get("责任单位", ""),
                "整改期限": entry.get("整改期限", ""),
                "超期天数": overdue_days,
                "督办等级": SUPERVISE_LEVEL,
                "进度": "已办结" if closed else str(entry.get("status", "")),
                "销号结论": str(entry.get("复查结论", "")) if closed else "",
            })
        items.sort(key=lambda item: (item["进度"] == "已办结", -int(item["超期天数"])))
        return items
