"""공통 저장 엔진 업무 규칙 (PM 관리) — 저장(새 버전)·목록·불러오기·최종본 지정/변경/해제·이력.

SQL 은 versions_repo.py, payload 검증은 payloads.py 에 있습니다. 근거: docs/db_rules.md 3·4·5장.

- 저장: 프로젝트 행 잠금 → (DB 가) 다음 version_no 부여 → 저장본·반영 출처 추가 → 커밋. 하나라도 실패하면 전부 롤백.
- 오래된 저장본에서 편집해 저장해도 허용. based_on_id 는 그대로 남기고 결과에 is_stale 로 알립니다.
- 최종본 변경: 프로젝트 행 잠금 → 마지막 final_history id 와 expected_final_history_id 비교 → 같으면 새 기록, 다르면 FinalConflict(409).
- created_by 는 호출자가 넘기는 서버 로그인 사용자 id. version_no 는 DB 가 정합니다. 클라이언트 값은 쓰지 않습니다.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime

import psycopg

from src.common import payloads, versions_repo as repo
from src.common.db import DatabaseConnectionError, mask_secrets

log = logging.getLogger("cosmoa.versions")

DEFAULT_PAGE = 20
MAX_PAGE = 100
_MISSING = object()


class VersionError(Exception):
    status = 400
    code = "invalid_request"

    def __init__(self, message: str, code: str | None = None, **extra):
        super().__init__(message)
        if code:
            self.code = code
        self.extra = extra

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), **self.extra}


class InvalidRequest(VersionError):
    status = 400


class NotFound(VersionError):
    status = 404
    code = "not_found"


class FinalConflict(VersionError):
    status = 409
    code = "final_conflict"


class Unavailable(VersionError):
    status = 503
    code = "db_unavailable"


class ServerError(VersionError):
    status = 500
    code = "server_error"


class _Retry(Exception):
    pass


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _int_param(value, name: str, *, minimum: int = 1, allow_none: bool = True):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidRequest(f"{name} 는 {minimum} 이상의 정수여야 합니다.", "invalid_parameter", field=name)
    return value


def page_size(value) -> int:
    if value is None:
        return DEFAULT_PAGE
    value = _int_param(value, "limit")
    if value > MAX_PAGE:
        raise InvalidRequest(f"limit 은 {MAX_PAGE} 이하여야 합니다.", "invalid_parameter", field="limit")
    return value


def _person(row: dict) -> dict:
    return {"id": row["created_by"], "name": row["created_by_name"]}


def _version_summary(row: dict, final_version_id: int | None) -> dict:
    data = {
        "id": row["id"], "project_id": row["project_id"], "tab": row["tab"], "version_no": row["version_no"],
        "title": row["title"], "schema_version": row["schema_version"],
        "based_on_id": row["based_on_id"], "based_on_version_no": row.get("based_on_version_no"),
        "created_by": _person(row) if "created_by_name" in row else {"id": row["created_by"]},
        "created_at": _iso(row["created_at"]), "is_final": row["id"] == final_version_id,
    }
    if "payload_bytes" in row:
        data["payload_bytes"] = row["payload_bytes"]
    return data


def _final_state(row: dict | None) -> dict:
    if row is None:
        return {"final_history_id": None, "action": None, "version": None, "changed_by": None, "changed_at": None}
    return {
        "final_history_id": row["id"], "action": row["action"],
        "version": {"id": row["version_id"], "version_no": row["version_no"]} if row["action"] == "set" else None,
        "changed_by": _person(row), "changed_at": _iso(row["created_at"]),
    }


@contextmanager
def business_transaction(db, logger=log, *, integrity_message="같은 프로젝트·탭 규칙에 맞지 않는 참조입니다."):
    """업무 DB 트랜잭션. DB 오류를 API 오류(400/503/500)로 바꾸고, 접속 정보는 가린 채 서버 로그에만 남깁니다.
    직렬화 충돌(40001)은 _Retry 로 올려 호출자가 재시도 여부를 정합니다."""
    if db is None:
        raise Unavailable("업무 DB 가 설정되지 않았습니다.")
    try:
        with db.transaction() as cur:
            yield cur
    except VersionError:
        raise
    except DatabaseConnectionError as e:
        logger.error("업무 DB 연결 실패: %s", e)
        raise Unavailable("업무 DB 에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
    except psycopg.errors.SerializationFailure:
        raise _Retry() from None
    except psycopg.IntegrityError as e:
        logger.warning("저장 제약 위반: %s", mask_secrets(f"{type(e).__name__}: {e.diag.constraint_name or ''}"))
        raise InvalidRequest(integrity_message, "invalid_reference") from None
    except (psycopg.OperationalError, psycopg.InterfaceError) as e:
        logger.error("업무 DB 오류: %s", mask_secrets(f"{type(e).__name__}: {e}"))
        raise Unavailable("업무 DB 에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
    except psycopg.Error as e:
        logger.error("업무 DB 처리 실패: %s", mask_secrets(f"{type(e).__name__}: {e}"))
        raise ServerError("저장 처리 중 오류가 발생했습니다.") from None


def _bind_project_context(context: dict, project: dict) -> None:
    """payload 의 연결 프로젝트·고객사 id 가 저장 대상(URL) 프로젝트와 같은지 확인하고, 이름 사본은 DB 값으로 맞춥니다.
    화면에서 지금 고른 프로젝트가 아니라 요청서가 연결된 프로젝트로 저장했는지 서버가 다시 확인하는 단계입니다."""
    if context.get("project_id") != project["id"]:
        raise InvalidRequest("요청서가 연결된 프로젝트와 저장하려는 프로젝트가 다릅니다.", "context_project_mismatch",
                             field="context.project_id")
    if context.get("customer_id") != project["customer_id"]:
        raise InvalidRequest("요청서의 고객사가 프로젝트의 고객사와 다릅니다.", "context_customer_mismatch",
                             field="context.customer_id")
    context["project_name"] = project["name"]
    context["customer_name"] = project["customer_name"]


class VersionService:
    def __init__(self, db, limits: payloads.Limits | None = None):
        self.db = db
        self.limits = limits or payloads.Limits()

    def _tx(self):
        return business_transaction(self.db)

    # --- 저장 -------------------------------------------------------------------

    def _clean_links(self, links, tab: str) -> list[dict]:
        if links is None:
            return []
        if not isinstance(links, list):
            raise InvalidRequest("links 는 목록이어야 합니다.", "invalid_parameter", field="links")
        if len(links) > self.limits.links_per_save:
            raise payloads.PayloadTooLarge(f"반영 출처는 한 번에 {self.limits.links_per_save}개까지입니다.", "links",
                                           len(links), self.limits.links_per_save)
        cleaned, seen = [], set()
        for i, link in enumerate(links):
            path = f"links[{i}]"
            if not isinstance(link, dict) or set(link) - {"source_version_id", "applied_values"}:
                raise InvalidRequest("반영 출처는 {source_version_id, applied_values} 객체여야 합니다.", "invalid_link",
                                     field=path)
            source_id = _int_param(link.get("source_version_id"), f"{path}.source_version_id", allow_none=False)
            if source_id in seen:
                raise InvalidRequest("같은 출처 저장본을 두 번 넣을 수 없습니다.", "invalid_link", field=path)
            seen.add(source_id)
            values, removed = payloads.clean_applied_values(link.get("applied_values"), f"{path}.applied_values",
                                                            self.limits)
            cleaned.append({"source_version_id": source_id, "applied_values": values, "removed": removed})
        return cleaned

    def save_version(self, *, project_id: int, tab: str, actor_id: int, schema_version, payload,
                     title=None, based_on_id=None, links=None) -> dict:
        if actor_id is None:
            raise PermissionError("로그인 사용자 없이 저장할 수 없습니다.")
        payloads.validate_tab(tab)
        result = payloads.clean_payload(tab, schema_version, payload, self.limits)
        title = payloads.clean_title(title)
        based_on_id = _int_param(based_on_id, "based_on_id")
        clean_links = self._clean_links(links, tab)

        with self._tx() as cur:
            project = repo.lock_project(cur, project_id)                    # 1. 프로젝트 행 잠금
            if project is None:
                raise NotFound("프로젝트가 없습니다.", "project_not_found")
            if project["archived_at"] is not None:
                raise InvalidRequest("보관된 프로젝트에는 저장할 수 없습니다.", "project_archived")
            if result.schema.project_bound:
                _bind_project_context(result.payload["context"], project)
            latest = repo.latest_version(cur, project_id, tab)               # 오래된 기준 판단용 (저장 직전 최신)
            base = None
            if based_on_id is not None:
                base = repo.version_scope(cur, based_on_id)
                if base is None or base["project_id"] != project_id or base["tab"] != tab:
                    raise InvalidRequest("based_on_id 는 같은 프로젝트·같은 탭의 저장본이어야 합니다.", "invalid_based_on",
                                         field="based_on_id")
            sources = []
            for i, link in enumerate(clean_links):
                src = repo.version_scope(cur, link["source_version_id"])
                if src is None or src["project_id"] != project_id:
                    raise InvalidRequest("반영 출처는 같은 프로젝트의 저장본이어야 합니다.", "invalid_link_source",
                                         field=f"links[{i}].source_version_id")
                if src["tab"] == tab:
                    raise InvalidRequest("같은 탭의 저장본은 반영 출처가 아니라 based_on_id 로 지정합니다.",
                                         "invalid_link_source", field=f"links[{i}].source_version_id")
                sources.append(src)
            row = repo.insert_version(cur, project_id=project_id, tab=tab, based_on_id=based_on_id,  # 2. 번호는 DB 가 부여
                                      schema_version=schema_version, title=title, payload=result.payload,
                                      created_by=actor_id)
            link_rows = [repo.insert_link(cur, project_id=project_id, version_id=row["id"], tab=tab,  # 3. 같은 트랜잭션
                                          source_tab=src["tab"], source_version_id=src["id"],
                                          applied_values=link["applied_values"], created_by=actor_id)
                         for src, link in zip(sources, clean_links)]
        # 4. 커밋 완료
        validation = result.validation()
        validation["removed_fields"] += [p for link in clean_links for p in link["removed"]]
        return {
            "version": _version_summary(row, None) | {"based_on_version_no": base["version_no"] if base else None},
            "base": {
                "based_on_id": based_on_id,
                "based_on_version_no": base["version_no"] if base else None,
                "latest_version_no_before_save": latest["version_no"] if latest else None,
                "is_stale": bool(base and latest and base["id"] != latest["id"]),
            },
            "links": [{"id": r["id"], "source_tab": r["source_tab"], "source_version_id": r["source_version_id"]}
                      for r in link_rows],
            "validation": validation,
        }

    # --- 조회 -------------------------------------------------------------------

    def list_versions(self, *, project_id: int, tab: str, limit=None, before=None) -> dict:
        payloads.validate_tab(tab)
        limit = page_size(limit)
        before = _int_param(before, "before")
        with self._tx() as cur:
            if not repo.project_exists(cur, project_id):
                raise NotFound("프로젝트가 없습니다.", "project_not_found")
            rows = repo.list_versions(cur, project_id, tab, limit=limit, before_version_no=before)
            final_id = repo.current_final_version_id(cur, project_id, tab)
        return {"items": [_version_summary(r, final_id) for r in rows],
                "next_before": rows[-1]["version_no"] if len(rows) == limit else None, "limit": limit}

    def get_version(self, version_id: int) -> dict:
        with self._tx() as cur:
            row = repo.get_version(cur, version_id)
            if row is None:
                raise NotFound("저장본이 없습니다.", "version_not_found")
            links = repo.links_of(cur, version_id)
            final_id = repo.current_final_version_id(cur, row["project_id"], row["tab"])
        data = _version_summary(row, final_id)
        data["payload"] = row["payload"]
        data["links"] = [{"id": l["id"], "source_tab": l["source_tab"], "source_version_id": l["source_version_id"],
                          "source_version_no": l["source_version_no"], "applied_values": l["applied_values"],
                          "created_at": _iso(l["created_at"])} for l in links]
        return data

    def get_final(self, *, project_id: int, tab: str) -> dict:
        payloads.validate_tab(tab)
        with self._tx() as cur:
            if not repo.project_exists(cur, project_id):
                raise NotFound("프로젝트가 없습니다.", "project_not_found")
            return _final_state(repo.last_final(cur, project_id, tab))

    def final_history(self, *, project_id: int, tab: str, limit=None, before=None) -> dict:
        payloads.validate_tab(tab)
        limit = page_size(limit)
        before = _int_param(before, "before")
        with self._tx() as cur:
            if not repo.project_exists(cur, project_id):
                raise NotFound("프로젝트가 없습니다.", "project_not_found")
            rows = repo.list_final_history(cur, project_id, tab, limit=limit, before_id=before)
        items = [{"id": r["id"], "action": r["action"],
                  "version": {"id": r["version_id"], "version_no": r["version_no"]} if r["action"] == "set" else None,
                  "changed_by": _person(r), "changed_at": _iso(r["created_at"])} for r in rows]
        return {"items": items, "next_before": rows[-1]["id"] if len(rows) == limit else None, "limit": limit}

    # --- 최종본 지정·변경·해제 ----------------------------------------------------

    def change_final(self, *, project_id: int, tab: str, actor_id: int, action,
                     version_id=None, expected_final_history_id=_MISSING) -> dict:
        """expected_final_history_id: 클라이언트가 아는 마지막 기록 id. 기록이 없다고 알면 None.
        인자를 아예 넘기지 않으면(_MISSING) 거부합니다 — null 과 누락을 구분."""
        if actor_id is None:
            raise PermissionError("로그인 사용자 없이 최종본을 바꿀 수 없습니다.")
        payloads.validate_tab(tab)
        if action not in ("set", "unset"):
            raise InvalidRequest("action 은 set 또는 unset 이어야 합니다.", "invalid_parameter", field="action")
        if expected_final_history_id is _MISSING:
            raise InvalidRequest("expected_final_history_id 가 필요합니다. 기록이 없으면 null 을 보내세요.",
                                 "expected_final_history_id_required", field="expected_final_history_id")
        expected = _int_param(expected_final_history_id, "expected_final_history_id")
        if action == "set":
            version_id = _int_param(version_id, "version_id", allow_none=False)
        elif version_id is not None:
            raise InvalidRequest("unset 에는 version_id 를 보내지 않습니다.", "invalid_parameter", field="version_id")

        for attempt in range(2):     # 기록 순서 충돌(40001)은 한 번 재시도
            try:
                return self._change_final_once(project_id, tab, actor_id, action, version_id, expected)
            except _Retry:
                if attempt:
                    raise Unavailable("최종본 변경이 몰려 처리하지 못했습니다. 다시 시도해 주세요.", "retry_later")
        raise AssertionError("unreachable")

    def _change_final_once(self, project_id, tab, actor_id, action, version_id, expected) -> dict:
        with self._tx() as cur:
            project = repo.lock_project(cur, project_id)                     # 1. 프로젝트 행 잠금
            if project is None:
                raise NotFound("프로젝트가 없습니다.", "project_not_found")
            if project["archived_at"] is not None:
                raise InvalidRequest("보관된 프로젝트의 최종본은 바꿀 수 없습니다.", "project_archived")
            last = repo.last_final(cur, project_id, tab)                     # 2. 마지막 기록 다시 조회
            current_id = last["id"] if last else None
            if current_id != expected:                                       # 4. 다르면 기록 없이 409
                raise FinalConflict("다른 사용자가 먼저 최종본을 바꿨습니다. 현재 상태를 확인한 뒤 다시 결정해 주세요.",
                                    current=_final_state(last))
            current_version = last["version_id"] if last and last["action"] == "set" else None
            if action == "set":
                scope = repo.version_scope(cur, version_id)
                if scope is None:
                    raise NotFound("저장본이 없습니다.", "version_not_found")
                if scope["project_id"] != project_id or scope["tab"] != tab:
                    raise InvalidRequest("같은 프로젝트·같은 탭의 저장본만 최종본으로 지정할 수 있습니다.",
                                         "invalid_version_scope", field="version_id")
                if current_version == version_id:
                    raise InvalidRequest("이미 최종본인 저장본입니다.", "already_final", field="version_id")
            elif current_version is None:
                raise InvalidRequest("해제할 최종본이 없습니다.", "no_final")
            repo.insert_final(cur, project_id=project_id, tab=tab, action=action,      # 3. 같으면 새 기록
                              version_id=version_id, created_by=actor_id)
            return _final_state(repo.last_final(cur, project_id, tab))
