"""공통 저장 API (PM 관리) — Blueprint. 경로·예시: docs/api_contract.md

- 로그인한 팀 사용자 전체가 모든 프로젝트·저장본을 조회·저장한다 (개발용 기본 정책, db_rules.md 3-5).
- 작성자는 서버 로그인 사용자(auth.current_user). 요청 본문의 작성자·버전 번호는 받지 않습니다.
- 상태 코드: 미인증 401 / CSRF 403 / 없는 대상 404 / 잘못된 입력 400 / 최종본 충돌 409 / 크기 초과 413 / DB 장애 503.
- 변경 요청(POST)은 JSON 본문 + X-CSRF-Token 헤더가 필요합니다. 토큰: GET /api/csrf-token
- 오류 응답에는 SQL·접속 정보를 넣지 않습니다.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.common import auth, payloads
from src.common.versions import VersionError, VersionService, _MISSING

log = logging.getLogger("cosmoa.versions_api")

bp = Blueprint("versions_api", __name__, url_prefix="/api")

SAVE_FIELDS = {"schema_version", "title", "based_on_id", "payload", "links"}
FINAL_FIELDS = {"action", "version_id", "expected_final_history_id"}


def init_app(app) -> None:
    """앱에 등록. 크기 상한은 환경변수(VERSION_*_MAX*)에서 읽고, 테스트는 app.config["VERSION_LIMITS"] 를 바꿉니다."""
    app.config.setdefault("VERSION_LIMITS", payloads.Limits.from_env())
    app.register_blueprint(bp)


def apply_api_policy(blueprint) -> None:
    """다른 업무 API Blueprint(고객사·프로젝트 등)에 같은 인증·CSRF·오류 응답 규칙을 적용합니다."""
    blueprint.before_request(_guard)
    for error, handler in ((VersionError, _version_error), (payloads.PayloadError, _payload_error),
                           (RequestEntityTooLarge, _too_large), (PermissionError, _no_user), (Exception, _unexpected)):
        blueprint.register_error_handler(error, handler)


def _limits() -> payloads.Limits:
    return current_app.config["VERSION_LIMITS"]


def _service() -> VersionService:
    return VersionService(current_app.extensions.get("business_db"), _limits())


def _error(status: int, code: str, message: str, **extra):
    return jsonify(ok=False, error={"code": code, "message": message, **extra}), status


def _ok(data: dict, status: int = 200):
    return jsonify(ok=True, **data), status


@bp.before_request
def _guard():
    if not auth.current_user():                 # DB 장애는 AuthUnavailable → app.py 처리기(JSON 503)
        return _error(401, "unauthorized", "로그인 후 다시 이용해 주세요.")
    request.max_content_length = _limits().request_bytes
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not request.is_json:
            return _error(400, "json_required", "Content-Type: application/json 본문이 필요합니다.")
        if not auth.csrf_valid():
            return _error(403, "csrf_failed", "보안 토큰이 없거나 맞지 않습니다. 페이지를 새로 고친 뒤 다시 시도해 주세요.")
    return None


def _body(allowed: set) -> dict:
    if request.content_length is not None and request.content_length > _limits().request_bytes:
        raise RequestEntityTooLarge()
    try:
        data = json.loads(request.get_data(cache=True) or b"null")
    except (ValueError, UnicodeDecodeError):
        raise VersionError("JSON 본문을 읽을 수 없습니다.", "invalid_json") from None
    if not isinstance(data, dict):
        raise VersionError("JSON 객체 본문이 필요합니다.", "invalid_json")
    unknown = sorted(set(data) - allowed)
    if unknown:   # created_by·version_no 등 서버가 정하는 값도 여기서 거부
        raise VersionError(f"받지 않는 필드입니다: {', '.join(unknown)}", "unknown_fields", fields=unknown)
    return data


def _query_int(name: str):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if not raw.isdigit():
        raise VersionError(f"{name} 는 양의 정수여야 합니다.", "invalid_parameter", field=name)
    return int(raw)


def _actor_id() -> int:
    return auth.current_user()["id"]


# --- 오류 처리 -------------------------------------------------------------------

@bp.errorhandler(VersionError)
def _version_error(e: VersionError):
    return jsonify(ok=False, error=e.to_dict()), e.status


@bp.errorhandler(payloads.PayloadError)
def _payload_error(e: payloads.PayloadError):
    status = 413 if isinstance(e, payloads.PayloadTooLarge) else 400
    extra = {"limit": e.limit, "size": e.size} if isinstance(e, payloads.PayloadTooLarge) else {}
    return _error(status, e.code, str(e), field=e.path, **extra)


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_e):
    return _error(413, "request_too_large", f"요청이 너무 큽니다 (최대 {_limits().request_bytes} 바이트). 잘라서 저장하지 않습니다.",
                  limit=_limits().request_bytes)


@bp.errorhandler(PermissionError)
def _no_user(_e):
    return _error(401, "unauthorized", "로그인 후 다시 이용해 주세요.")


@bp.errorhandler(Exception)
def _unexpected(e):
    if isinstance(e, auth.AuthUnavailable):       # 로그인 확인 중 DB 장애
        return _error(503, "db_unavailable", auth.UNAVAILABLE_MESSAGE)
    if getattr(e, "code", None) and getattr(e, "description", None):   # werkzeug HTTPException (404 등)
        return _error(e.code, "http_error", e.description)
    log.exception("저장 API 처리 실패 (%s)", type(e).__name__)
    return _error(500, "server_error", "처리 중 오류가 발생했습니다.")


# --- 경로 ------------------------------------------------------------------------

@bp.get("/csrf-token")
def csrf_token():
    return _ok({"csrf_token": auth.csrf_token(), "header": auth.CSRF_HEADER})


@bp.get("/projects/<int:project_id>/tabs/<tab>/versions")
def list_versions(project_id: int, tab: str):
    return _ok(_service().list_versions(project_id=project_id, tab=tab, limit=_query_int("limit"),
                                        before=_query_int("before")))


@bp.post("/projects/<int:project_id>/tabs/<tab>/versions")
def save_version(project_id: int, tab: str):
    payloads.validate_tab(tab)
    body = _body(SAVE_FIELDS)
    if "schema_version" not in body or "payload" not in body:
        raise VersionError("schema_version 과 payload 가 필요합니다.", "missing_fields")
    result = _service().save_version(project_id=project_id, tab=tab, actor_id=_actor_id(),
                                     schema_version=body["schema_version"], payload=body["payload"],
                                     title=body.get("title"), based_on_id=body.get("based_on_id"),
                                     links=body.get("links"))
    return _ok(result, 201)


@bp.get("/versions/<int:version_id>")
def get_version(version_id: int):
    return _ok({"version": _service().get_version(version_id)})


@bp.get("/projects/<int:project_id>/tabs/<tab>/final")
def get_final(project_id: int, tab: str):
    return _ok({"final": _service().get_final(project_id=project_id, tab=tab)})


@bp.post("/projects/<int:project_id>/tabs/<tab>/final")
def change_final(project_id: int, tab: str):
    payloads.validate_tab(tab)
    body = _body(FINAL_FIELDS)
    final = _service().change_final(project_id=project_id, tab=tab, actor_id=_actor_id(), action=body.get("action"),
                                    version_id=body.get("version_id"),
                                    expected_final_history_id=body.get("expected_final_history_id", _MISSING))
    return _ok({"final": final})


@bp.get("/projects/<int:project_id>/tabs/<tab>/final/history")
def final_history(project_id: int, tab: str):
    return _ok(_service().final_history(project_id=project_id, tab=tab, limit=_query_int("limit"),
                                        before=_query_int("before")))
