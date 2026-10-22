"""고객사·프로젝트 생성·조회 업무 규칙 (PM 관리). SQL 은 projects.py, 경로는 projects_api.py.

- 작성자는 호출자가 넘기는 서버 로그인 사용자 id. 요청 본문의 작성자 값은 쓰지 않습니다.
- 프로젝트는 URL 의 고객사 아래에만 만듭니다 (고객사 존재·보관 여부를 같은 트랜잭션에서 확인).
  단계·상태는 create_project() 가 proposal / active 로 시작합니다 (DB 도 다른 값을 거부, 0002).
- 목록은 보관(archived_at)되지 않은 행만, 페이지 크기 기본 20·최대 100.
- 이번 단계는 생성·조회만 합니다. 수정·보관은 아직 API 가 없습니다.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from src.common import projects as repo
from src.common.versions import InvalidRequest, NotFound, _int_param, _iso, business_transaction, page_size

log = logging.getLogger("cosmoa.projects")

NAME_MAX = 200
SEARCH_MAX = 100
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_name(value, field: str, label: str) -> str:
    if not isinstance(value, str):
        raise InvalidRequest(f"{label}은(는) 문자열이어야 합니다.", "invalid_parameter", field=field)
    value = value.strip()
    if not value:
        raise InvalidRequest(f"{label}을(를) 입력해 주세요.", "invalid_parameter", field=field)
    if len(value) > NAME_MAX:
        raise InvalidRequest(f"{label}은(는) {NAME_MAX}자 이하여야 합니다.", "invalid_parameter", field=field)
    if _CONTROL.search(value):
        raise InvalidRequest(f"{label}에 줄바꿈·제어 문자를 넣을 수 없습니다.", "invalid_parameter", field=field)
    return value


def clean_due_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and _DATE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InvalidRequest("납기일은 YYYY-MM-DD 형식의 날짜이거나 null 이어야 합니다.", "invalid_parameter", field="due_date")


def clean_search(value) -> str | None:
    value = (value or "").strip()
    if len(value) > SEARCH_MAX:
        raise InvalidRequest(f"검색어는 {SEARCH_MAX}자 이하여야 합니다.", "invalid_parameter", field="q")
    return value or None


def _person(row: dict) -> dict:
    return {"id": row["created_by"], "name": row["created_by_name"]}


def customer_view(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "archived": row["archived_at"] is not None,
            "created_by": _person(row), "created_at": _iso(row["created_at"])}


def project_view(row: dict) -> dict:
    return {"id": row["id"], "customer": {"id": row["customer_id"], "name": row["customer_name"]},
            "name": row["name"], "stage": row["stage"], "state": row["state"],
            "due_date": row["due_date"].isoformat() if row["due_date"] else None,
            "archived": row["archived_at"] is not None,
            "created_by": _person(row), "created_at": _iso(row["created_at"])}


class ProjectService:
    def __init__(self, db):
        self.db = db

    def _tx(self):
        return business_transaction(self.db, log, integrity_message="고객사·프로젝트 규칙에 맞지 않는 값입니다.")

    # --- 고객사 ---------------------------------------------------------------

    def create_customer(self, *, actor_id: int, name) -> dict:
        if actor_id is None:
            raise PermissionError("로그인 사용자 없이 고객사를 만들 수 없습니다.")
        name = clean_name(name, "name", "고객사명")
        with self._tx() as cur:
            row = repo.create_customer(cur, name=name, actor_id=actor_id)
            return customer_view(repo.get_customer(cur, row["id"]))

    def list_customers(self, *, search=None, limit=None, after=None) -> dict:
        search = clean_search(search)
        limit = page_size(limit)
        after = _int_param(after, "after")
        with self._tx() as cur:
            rows = repo.list_customers(cur, search=search, limit=limit, after_id=after)
        return {"items": [customer_view(r) for r in rows],
                "next_after": rows[-1]["id"] if len(rows) == limit else None, "limit": limit}

    def get_customer(self, customer_id: int) -> dict:
        with self._tx() as cur:
            row = repo.get_customer(cur, customer_id)
        if row is None:
            raise NotFound("고객사가 없습니다.", "customer_not_found")
        return customer_view(row)

    # --- 프로젝트 -------------------------------------------------------------

    def create_project(self, *, actor_id: int, customer_id: int, name, due_date=None) -> dict:
        if actor_id is None:
            raise PermissionError("로그인 사용자 없이 프로젝트를 만들 수 없습니다.")
        name = clean_name(name, "name", "프로젝트(제품)명")
        due = clean_due_date(due_date)
        with self._tx() as cur:
            customer = repo.lock_customer(cur, customer_id)
            if customer is None:
                raise NotFound("고객사가 없습니다.", "customer_not_found")
            if customer["archived_at"] is not None:
                raise InvalidRequest("보관된 고객사에는 프로젝트를 만들 수 없습니다.", "customer_archived")
            row = repo.create_project(cur, customer_id=customer_id, name=name, actor_id=actor_id, due_date=due)
            return project_view(repo.get_project(cur, row["id"]))

    def list_projects(self, *, customer_id: int, limit=None, before=None) -> dict:
        limit = page_size(limit)
        before = _int_param(before, "before")
        with self._tx() as cur:
            if repo.get_customer(cur, customer_id) is None:
                raise NotFound("고객사가 없습니다.", "customer_not_found")
            rows = repo.list_projects(cur, customer_id, limit=limit, before_id=before)
        return {"items": [project_view(r) for r in rows],
                "next_before": rows[-1]["id"] if len(rows) == limit else None, "limit": limit}

    def get_project(self, project_id: int) -> dict:
        with self._tx() as cur:
            row = repo.get_project(cur, project_id)
        if row is None:
            raise NotFound("프로젝트가 없습니다.", "project_not_found")
        return project_view(row)
