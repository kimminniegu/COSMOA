"""고객사·프로젝트 생성·조회 API (PM 관리) — Blueprint. 경로·예시: docs/api_contract.md 5장

인증(401)·CSRF(403)·JSON 필수·오류 응답 형식은 공통 저장 API(versions_api.py)와 같은 규칙을 씁니다.
작성자는 서버 로그인 사용자. 수정·보관 API 는 아직 없습니다.
"""

from __future__ import annotations

from flask import Blueprint, current_app, request

from src.common.projects_service import ProjectService
from src.common.versions import VersionError
from src.common.versions_api import _actor_id, _body, _ok, _query_int, apply_api_policy

bp = Blueprint("projects_api", __name__, url_prefix="/api")
apply_api_policy(bp)

CUSTOMER_FIELDS = {"name"}
PROJECT_FIELDS = {"name", "due_date"}   # 단계·상태·작성자는 받지 않음 (unknown_fields)


def init_app(app) -> None:
    app.register_blueprint(bp)


def _service() -> ProjectService:
    return ProjectService(current_app.extensions.get("business_db"))


def _required(body: dict, *names: str) -> None:
    missing = [n for n in names if n not in body]
    if missing:
        raise VersionError(f"필요한 필드가 없습니다: {', '.join(missing)}", "missing_fields", fields=missing)


@bp.get("/customers")
def list_customers():
    return _ok(_service().list_customers(search=request.args.get("q"), limit=_query_int("limit"),
                                         after=_query_int("after")))


@bp.post("/customers")
def create_customer():
    body = _body(CUSTOMER_FIELDS)
    _required(body, "name")
    return _ok({"customer": _service().create_customer(actor_id=_actor_id(), name=body["name"])}, 201)


@bp.get("/customers/<int:customer_id>")
def get_customer(customer_id: int):
    return _ok({"customer": _service().get_customer(customer_id)})


@bp.get("/customers/<int:customer_id>/projects")
def list_projects(customer_id: int):
    return _ok(_service().list_projects(customer_id=customer_id, limit=_query_int("limit"),
                                        before=_query_int("before")))


@bp.post("/customers/<int:customer_id>/projects")
def create_project(customer_id: int):
    body = _body(PROJECT_FIELDS)
    _required(body, "name")
    return _ok({"project": _service().create_project(actor_id=_actor_id(), customer_id=customer_id,
                                                     name=body["name"], due_date=body.get("due_date"))}, 201)


@bp.get("/projects/<int:project_id>")
def get_project(project_id: int):
    return _ok({"project": _service().get_project(project_id)})
