"""隐患排查整改台账业务规则。

规则口径（对应线下纸质台账的管理要求）：
- 状态只能顺着「待整改 → 整改中 → 待复查 → 已销号」单向推进；
  复查不通过可退回「整改中」继续整改，但「已销号」是终态，不能再退回；
- 没有复查结论不许落进已销号；
- 同一条隐患（同地点、同内容）重复登记时只保留发现日期最早的一条，
  后续登记并成它的补充记录，不另开台账行；
- 每条隐患必须落到具体责任单位；
- 超过整改期限仍未销号的自动升为矿级督办（见 supervision 服务），
  督办清单里单独排一行；销号结论回写督办待办，两边进度一起变；
- 存量按发现日期补录：允许直接登记历史各状态（含已销号），
  历史销号记录按当时复查结论原样保留，不按新口径改写。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.supervision import supervision_service
from app.store import store

MODULE = "hazard"

REQUIRED_FIELDS = ["隐患内容", "发现地点", "责任单位", "发现日期"]
# 补录历史记录时还必须给出当时的状态，普通新登记固定从「待整改」起步。
BACKFILL_REQUIRED_FIELDS = REQUIRED_FIELDS + ["状态"]

STATUS_PENDING = "待整改"
STATUS_WORKING = "整改中"
STATUS_REVIEWING = "待复查"
STATUS_CLOSED = "已销号"
STATUS_ORDER = [STATUS_PENDING, STATUS_WORKING, STATUS_REVIEWING, STATUS_CLOSED]

# 允许复查结论填写的取值；非合格才允许退回整改。
REVIEW_PASS = "合格"
REVIEW_FAIL = "不合格"
REVIEW_OPTIONS = [REVIEW_PASS, REVIEW_FAIL]

# 补录时允许落位的历史状态（不允许补录一个在状态机里不存在的状态）。
BACKFILL_STATUSES = STATUS_ORDER

# 超期升办时仍在整改口径内的状态——待复查说明已申请复查，不再按“没整改”升办。
ESCALATABLE_STATUSES = [STATUS_PENDING, STATUS_WORKING]


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date | None:
    """台账日期统一按 YYYY-MM-DD 解析；解析不了返回 None，由调用方报校验错。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _dedup_key(row: dict[str, Any]) -> tuple[str, str]:
    """同一条隐患的判重口径：同地点 + 同隐患描述（忽略空白与大小写差异）。"""
    location = "".join(str(row.get("发现地点") or "").split()).lower()
    content = "".join(str(row.get("隐患内容") or "").split()).lower()
    return location, content


class HazardService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        unit: str | None = None,
        level: str | None = None,
        page: int = 1,
        size: int = 20,
        include_merged: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        self.sweep_overdue()
        rows = store.rows(MODULE)
        if not include_merged:
            rows = [row for row in rows if not row.get("merged_into")]
        if keyword:
            key = keyword.strip()
            rows = [
                row for row in rows
                if key in str(row.get("隐患编号", ""))
                or key in str(row.get("隐患内容", ""))
                or key in str(row.get("发现地点", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if unit:
            rows = [row for row in rows if unit.strip() in str(row.get("责任单位", ""))]
        if level:
            rows = [row for row in rows if row.get("隐患等级") == level]
        # 台账按发现日期从新到旧展示，补录的存量数据同样按发现日期归位。
        rows = sorted(rows, key=lambda row: (str(row.get("发现日期", "")), int(row.get("id", 0))), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [dict(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return dict(row) if row else None

    def stats(self) -> list[dict[str, object]]:
        """台账首页指标卡：状态分布、超期、督办、待复查项。"""
        self.sweep_overdue()
        rows = [row for row in store.rows(MODULE) if not row.get("merged_into")]
        by_status = {name: 0 for name in STATUS_ORDER}
        overdue = 0
        supervised = 0
        for row in rows:
            by_status[str(row.get("status"))] = by_status.get(str(row.get("status")), 0) + 1
            if row.get("督办编号"):
                supervised += 1
            if self._is_overdue(row):
                overdue += 1
        return [
            {"label": "待整改", "value": by_status[STATUS_PENDING]},
            {"label": "整改中", "value": by_status[STATUS_WORKING]},
            {"label": "待复查", "value": by_status[STATUS_REVIEWING]},
            {"label": "已销号", "value": by_status[STATUS_CLOSED]},
            {"label": "超期未整改", "value": overdue},
            {"label": "矿级督办", "value": supervised},
        ]

    # ---------- 登记与补录 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        """登记一条隐患。

        返回 (记录, 缺失字段, 提示语)。命中重复登记时不新建主记录，
        而是并成最早那条的补充记录，提示语里写明并到了哪条。
        """
        backfill = bool(values.get("backfill"))
        required = BACKFILL_REQUIRED_FIELDS if backfill else REQUIRED_FIELDS
        missing = [field for field in required if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        if _parse_date(values.get("发现日期")) is None:
            return None, ["发现日期（需为 YYYY-MM-DD）"], ""

        rows = store.rows(MODULE)

        if backfill:
            history_status = str(values.get("状态") or "").strip()
            if history_status not in BACKFILL_STATUSES:
                return None, [], f"历史状态「{history_status}」不合法，只能取：{'、'.join(BACKFILL_STATUSES)}"
            if history_status == STATUS_CLOSED:
                # 历史销号必须保留当时的复查结论，没有结论不能按已销号补录。
                if not str(values.get("复查结论") or "").strip():
                    return None, ["复查结论"], ""
                if _parse_date(values.get("复查日期")) is None:
                    return None, ["复查日期（需为 YYYY-MM-DD）"], ""

        limit = _parse_date(values.get("整改期限"))
        if values.get("整改期限") and limit is None:
            return None, ["整改期限（需为 YYYY-MM-DD）"], ""

        entry = self._build_entry(values, backfill=backfill)
        rows.append(entry)

        # 判重：与同地点同内容的记录互为重复，只留发现日期最早的一条为主。
        # 补录可能补进一条比现有主记录更早的存量，因此用“重新选主”的方式处理，
        # 而不是只认本次新登记的这条。
        master, merged, message = self._consolidate_duplicates(entry)

        if backfill and master["status"] == STATUS_CLOSED:
            # 存量历史销号不按新口径改写，也不触发超期升办。
            pass
        else:
            self.sweep_overdue()
        return master, [], message

    def _build_entry(self, values: dict[str, Any], *, backfill: bool) -> dict[str, Any]:
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "隐患编号": str(values.get("隐患编号") or "").strip() or f"YH-{_today().isoformat().replace('-', '')}-{max((int(row.get('id', 0)) for row in rows), default=0) + 1:03d}",
            "隐患内容": str(values.get("隐患内容") or "").strip(),
            "发现地点": str(values.get("发现地点") or "").strip(),
            "隐患等级": str(values.get("隐患等级") or "一般隐患").strip(),
            "责任单位": str(values.get("责任单位") or "").strip(),
            "责任人": str(values.get("责任人") or "").strip(),
            "发现人": str(values.get("发现人") or "").strip(),
            "发现日期": str(values.get("发现日期") or "").strip(),
            "整改期限": str(values.get("整改期限") or "").strip(),
            "整改措施": str(values.get("整改措施") or "").strip(),
            "复查结论": "",
            "复查人": "",
            "复查日期": "",
            "销号日期": "",
            "补录": backfill,
            "merged_into": None,
            "补充记录": [],
            "timeline": [],
        }

        if backfill:
            status = str(values.get("状态") or STATUS_PENDING).strip()
            entry["status"] = status
            entry["pending"] = status != STATUS_CLOSED
            entry["abnormal"] = status in (STATUS_PENDING, STATUS_WORKING)
            # 按当时的复查结论原样保留历史销号，不重新走一遍现在的状态机。
            if status == STATUS_CLOSED:
                entry["复查结论"] = str(values.get("复查结论") or "").strip()
                entry["复查人"] = str(values.get("复查人") or "").strip()
                entry["复查日期"] = str(values.get("复查日期") or "").strip()
                entry["销号日期"] = str(values.get("销号日期") or values.get("复查日期") or "").strip()
                entry["timeline"].append(self._event(entry["发现日期"], "补录历史销号记录", "按当时复查结论归档"))
            else:
                entry["timeline"].append(self._event(entry["发现日期"], "补录存量隐患", f"补录时状态：{status}"))
        else:
            entry["status"] = STATUS_PENDING
            entry["pending"] = True
            entry["abnormal"] = True
            entry["timeline"].append(self._event(entry["发现日期"], "登记隐患", f"登记人：{entry['发现人'] or '—'}"))
        return entry

    def _consolidate_duplicates(
        self, anchor: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        """把同地点同内容的一组记录归并为「一条主记录 + 若干补充记录」。"""
        key = _dedup_key(anchor)
        group = [
            row for row in store.rows(MODULE)
            if not row.get("merged_into") and _dedup_key(row) == key
        ]
        if len(group) == 1:
            return group[0], [], ""

        def sort_key(row: dict[str, Any]) -> tuple[str, int]:
            return str(row.get("发现日期") or ""), int(row.get("id", 0))

        group.sort(key=sort_key)
        master = group[0]
        merged = group[1:]
        for row in merged:
            # 旧主记录身上可能已挂着更早并入的补充，换主时一并移交给新主。
            for old_supplement in row.pop("补充记录", []) or []:
                master.setdefault("补充记录", []).append(old_supplement)
            supplement = {
                "来源编号": row.get("隐患编号"),
                "发现日期": row.get("发现日期"),
                "登记人": row.get("发现人"),
                "补充内容": row.get("隐患内容"),
                "补充措施": row.get("整改措施"),
                "补录": bool(row.get("补录")),
            }
            master.setdefault("补充记录", []).append(supplement)
            master["timeline"].append(
                self._event(
                    str(row.get("发现日期") or _today()),
                    "并入重复登记",
                    f"{row.get('隐患编号')} 与本条同地点同内容，并为补充记录",
                )
            )
            row["merged_into"] = master["id"]
            row["pending"] = False
            row["abnormal"] = False
            # 重复行若已被升过督办，督办关系改挂到主记录上，避免督办清单里出现孤儿行。
            if row.get("督办编号"):
                supervision_service.retarget(int(row["merged_into"]), row["督办编号"])
                master["督办编号"] = row["督办编号"]
                row.pop("督办编号", None)

        if anchor.get("id") == master["id"]:
            message = f"补录的存量发现日期最早，已作为主记录，其余 {len(merged)} 条重复登记并入为补充记录"
        else:
            message = (
                f"该隐患与 {master['隐患编号']}（{master['发现日期']} 发现）为同一条，"
                f"已并为补充记录，台账只保留最早登记的 {master['隐患编号']}"
            )
        return master, merged, message

    # ---------- 状态流转 ----------
    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None or entry.get("merged_into"):
            return None, f"隐患 {entry_id} 不存在，或已并入其他记录"
        status = entry.get("status")

        if action == "开始整改":
            if status != STATUS_PENDING:
                return None, f"当前状态为「{status}」，只有待整改的隐患可以开始整改"
            self._set_status(entry, STATUS_WORKING, "责任单位开始整改")
            if str(values.get("整改措施") or "").strip():
                entry["整改措施"] = str(values["整改措施"]).strip()
            return self._after_transition(entry, "已转入整改中")

        if action == "整改完成":
            if status != STATUS_WORKING:
                return None, f"当前状态为「{status}」，整改中的隐患才能申请复查"
            self._set_status(entry, STATUS_REVIEWING, "整改完成，提交复查")
            return self._after_transition(entry, "已提交复查")

        if action == "复查":
            if status != STATUS_REVIEWING:
                return None, f"当前状态为「{status}」，待复查的隐患才能登记复查结论"
            conclusion = str(values.get("复查结论") or "").strip()
            reviewer = str(values.get("复查人") or "").strip()
            review_date = _parse_date(values.get("复查日期")) or _today()
            if not conclusion:
                return None, "缺少复查结论：没有复查结论不许销号，也不能结束复查环节"
            if not reviewer:
                return None, "缺少复查人"
            entry["复查结论"] = conclusion
            entry["复查人"] = reviewer
            entry["复查日期"] = review_date.isoformat()
            entry["timeline"].append(
                self._event(review_date.isoformat(), "复查登记", f"复查人：{reviewer}；结论：{conclusion}")
            )
            # 注意必须精确匹配：「不合格」里含「合格」二字，用子串判断会把退回误判成销号。
            if conclusion == REVIEW_PASS:
                # 状态机最后一步：只有复查结论合格才允许落进已销号。
                self._set_status(entry, STATUS_CLOSED, f"复查合格，销号归档（{conclusion}）", at=review_date.isoformat())
                entry["销号日期"] = review_date.isoformat()
                message = "复查合格，已销号归档"
            elif conclusion == REVIEW_FAIL:
                # 复查不通过：退回整改中重新整改，不是销号后的回退。
                self._set_status(entry, STATUS_WORKING, f"复查不通过，退回整改（{conclusion}）", at=review_date.isoformat())
                entry["复查结论"] = ""
                message = "复查不通过，已退回整改中"
            else:
                # 结论既不是合格也不是不合格：留在待复查，禁止凭模糊结论跳级销号。
                return None, f"复查结论「{conclusion}」无法判定，请明确填写「{REVIEW_PASS}」或「{REVIEW_FAIL}」"
            return self._after_transition(entry, message)

        return None, f"动作「{action}」不属于隐患台账可执行范围"

    def _set_status(self, entry: dict[str, Any], target: str, note: str, *, at: str | None = None) -> None:
        entry["status"] = target
        entry["pending"] = target != STATUS_CLOSED
        entry["abnormal"] = target in (STATUS_PENDING, STATUS_WORKING)
        entry["timeline"].append(self._event(at or _today().isoformat(), f"状态变更为{target}", note))

    def _after_transition(self, entry: dict[str, Any], message: str) -> tuple[dict[str, Any], str]:
        self.sweep_overdue()
        # 销号结论回写督办待办，督办进度跟着隐患状态一起变。
        if entry.get("督办编号"):
            supervision_service.sync_from_hazard(entry)
        return dict(entry), message

    # ---------- 超期自动升矿级督办 ----------
    def _is_overdue(self, row: dict[str, Any]) -> bool:
        # 已并入的重复行不单独升办；已销号（含历史补录销号）的不再升办。
        # 补录的存量只要现在仍未销号且过了整改期限，一样自动升矿级督办。
        if row.get("merged_into"):
            return False
        if row.get("status") not in ESCALATABLE_STATUSES:
            return False
        limit = _parse_date(row.get("整改期限"))
        return limit is not None and limit < _today()

    def sweep_overdue(self) -> list[dict[str, Any]]:
        """扫描超期未整改隐患并自动升为矿级督办；幂等，不重复升办。

        已销号归档的不会再回到这里；已升过办的也不重复建行。
        """
        escalated: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            if row.get("督办编号") or not self._is_overdue(row):
                continue
            row["timeline"].append(
                self._event(_today().isoformat(), "超期升矿级督办", f"超过整改期限 {row.get('整改期限')}，自动升办")
            )
            ticket = supervision_service.escalate(dict(row))
            row["督办编号"] = ticket["督办编号"]
            escalated.append(ticket)
        return escalated

    @staticmethod
    def _event(at: str, title: str, detail: str) -> dict[str, Any]:
        return {"日期": at, "事项": title, "说明": detail}


hazard_service = HazardService()
