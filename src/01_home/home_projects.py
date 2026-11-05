"""홈 프로젝트 위젯 데이터 (담당자 A) — 명세: src/01_home/home.md 2-4

오늘 챙길 것 · 프로젝트 현황 · 이번 주 일정 위젯이 쓰는 값을 업무 DB 에서 읽기 전용으로 만듭니다.
쓰기·스키마 변경은 없습니다. 일정의 기준은 납기일(due_date)입니다. (docs/development.md 1-2, 1-3)
projects 에 담당자 열이 아직 없어(docs/data_contract.md 1-3) 보관되지 않은 전체 프로젝트를 대상으로 합니다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.common.versions import VersionError, business_transaction

__all__ = ["VersionError", "build_widgets", "get_widgets"]

log = logging.getLogger("cosmoa.home.projects")

KST = ZoneInfo("Asia/Seoul")
DUE_SOON_DAYS = 3   # 오늘 챙길 것: 납기가 지났거나 3일 이내인 프로젝트

STAGES = (("proposal", "제안"), ("development", "개발"), ("order", "발주"),
          ("production", "생산"), ("shipping", "선적"), ("completed", "완료"))
STAGE_LABELS = dict(STAGES)
STATE_LABELS = {"active": "진행", "hold": "홀드", "drop": "드롭"}
WEEKDAYS = "월화수목금토일"

_PROJECTS_SQL = """
    SELECT p.id, p.name, p.stage, p.state, p.due_date, c.name AS customer_name
    FROM projects p JOIN customers c ON c.id = p.customer_id
    WHERE p.archived_at IS NULL AND c.archived_at IS NULL
    ORDER BY p.due_date NULLS LAST, p.id
"""


def _d_day_text(days: int) -> str:
    if days == 0:
        return "D-Day"
    return f"D-{days}" if days > 0 else f"D+{-days}"


def _due_item(row: dict, today: date) -> dict:
    days = (row["due_date"] - today).days
    return {
        "id": row["id"],
        "name": row["name"],
        "customer": row["customer_name"],
        "stage_text": STAGE_LABELS.get(row["stage"], row["stage"]),
        "state": row["state"],
        "state_text": STATE_LABELS.get(row["state"], row["state"]),
        "due_date": row["due_date"].isoformat(),
        "d_day": days,
        "d_day_text": _d_day_text(days),
    }


def build_widgets(rows: list[dict], today: date) -> dict:
    """프로젝트 행 → 위젯 값. 드롭·완료 프로젝트는 챙길 일정에서 뺍니다. (홀드는 납기가 남아 있으므로 표시)"""
    counts = {state: 0 for state in STATE_LABELS}
    in_progress = {code: 0 for code, _ in STAGES}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
        if row["state"] == "active":
            in_progress[row["stage"]] = in_progress.get(row["stage"], 0) + 1

    scheduled = [r for r in rows if r["due_date"] and r["state"] != "drop" and r["stage"] != "completed"]
    due_soon = [r for r in scheduled if (r["due_date"] - today).days <= DUE_SOON_DAYS]

    monday = today - timedelta(days=today.weekday())
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        days.append({
            "date": day.isoformat(),
            "weekday": WEEKDAYS[offset],
            "label": f"{day.month}/{day.day}",
            "is_today": day == today,
            "items": [_due_item(r, today) for r in scheduled if r["due_date"] == day],
        })

    sunday = monday + timedelta(days=6)
    return {
        "ok": True,
        "today": today.isoformat(),
        "total": len(rows),
        "counts": [{"code": code, "label": label, "count": counts[code]} for code, label in STATE_LABELS.items()],
        "stages": [{"code": code, "label": label, "count": in_progress[code]} for code, label in STAGES],
        "due_soon": [_due_item(r, today) for r in sorted(due_soon, key=lambda r: (r["due_date"], r["id"]))],
        "week": {"range_text": f"{monday.month}/{monday.day} ~ {sunday.month}/{sunday.day}", "days": days},
    }


def get_widgets(db, today: date | None = None) -> dict:
    """/api/home/projects. DB 장애는 VersionError(Unavailable 등)로 올라가며 메시지에 접속 정보가 없습니다."""
    with business_transaction(db, log) as cur:
        cur.execute(_PROJECTS_SQL)
        rows = cur.fetchall()
    return build_widgets(rows, today or datetime.now(KST).date())
