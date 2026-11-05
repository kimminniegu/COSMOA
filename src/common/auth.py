"""로그인 / 세션 (PM 관리)

- 사용자 정보는 업무 DB(Neon PostgreSQL) users 테이블에서 읽습니다. (db/migrations/0001_core.sql)
  SQLite 로 자동 대체하지 않습니다. 테이블 생성·데모 계정 자동 생성도 하지 않습니다.
  첫 계정·비밀번호 변경은 관리 명령으로 합니다: python -m src.common.db_admin create-first-user / set-password
- 비밀번호는 werkzeug 해시로만 저장·확인합니다. 해시는 세션·API 응답에 넣지 않습니다.
- 세션에는 형식 버전과 사용자 id 만 둡니다. 요청마다 DB 에서 사용자를 다시 확인하고(요청당 1번), 없으면 세션을 지웁니다.
  예전 SQLite 시절 세션(session["user"])은 믿지 않고 다시 로그인하게 합니다.
- 페이지 Route 에는 @login_required 를 붙입니다. 페이지는 /login 으로 이동, /api/ 는 JSON 401.
- DB 장애는 AuthUnavailable 로 구분합니다 (비밀번호 오류와 다름). 메시지에 접속 정보를 넣지 않습니다.
- CSRF: 로그인할 때 세션에 토큰을 만들고, 세션 쿠키로 인증하는 변경 API 는 X-CSRF-Token 헤더 값을 비교합니다.
  화면 폼(비밀번호 변경 등)은 같은 토큰을 hidden 필드(csrf_token)로 보냅니다.
- 세션에는 비밀번호 지문(pw: 앱 비밀키로 만든 HMAC 일부, 해시 자체가 아님)을 둡니다. 비밀번호가 바뀌면 지문이 달라져
  다른 기기·브라우저의 기존 세션은 다음 요청에서 로그아웃됩니다. 본인 변경 시 지금 브라우저는 새 세션으로 이어집니다.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg
from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from src.common.db import Database, DatabaseConnectionError, mask_secrets

log = logging.getLogger("cosmoa.auth")

SESSION_KEY = "auth"
SESSION_VERSION = 2            # 2 = 업무 DB(PostgreSQL) users 기준. 그 외 형식은 다시 로그인
LEGACY_SESSION_KEYS = ("user",)  # SQLite 시절 세션: 사용자 정보를 통째로 담고 있었음
UNAVAILABLE_MESSAGE = "로그인 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
CSRF_HEADER = "X-CSRF-Token"
LOGIN_CSRF_KEY = "login_csrf"     # 로그인 전 세션의 로그인 폼 토큰
LOGIN_CSRF_FIELD = "csrf_token"   # 로그인 폼 hidden 필드 이름
LOGIN_CSRF_MESSAGE = "보안 확인 시간이 지났어요. 다시 로그인해 주세요."
PASSWORD_MIN = 8               # 관리 명령(db_admin)과 같은 기준
PASSWORD_MAX = 128             # 해시 계산 부담을 막는 입력 상한

_db: Database | None = None
_dummy_hash: str | None = None
_NOT_LOADED = object()


class AuthUnavailable(RuntimeError):
    """업무 DB 에 접속할 수 없거나 설정이 없음. 메시지에 비밀값이 없습니다."""


class PasswordChangeError(ValueError):
    """본인 비밀번호 변경 입력 오류 (400). 메시지에 비밀번호·해시를 넣지 않습니다."""


def password_fingerprint(password_hash: str, key: str | bytes | None = None) -> str:
    """세션용 비밀번호 지문. 해시를 세션에 그대로 두지 않고 앱 비밀키로 HMAC 한 앞부분만 둡니다."""
    key = current_app.secret_key if key is None else key
    key = key.encode() if isinstance(key, str) else (key or b"")
    return hmac.new(key, (password_hash or "").encode(), "sha256").hexdigest()[:32]


def init(db: Database | None) -> None:
    """앱 시작 시 한 번 (테스트는 test DB 의 Database 를 넘김). 접속은 첫 로그인·사용자 확인 때 합니다."""
    global _db
    _db = db


def _query_one(sql: str, params: tuple) -> dict | None:
    if _db is None:
        raise AuthUnavailable("업무 DB(DATABASE_URL)가 설정되지 않았습니다.")
    try:
        with _db.transaction() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    except DatabaseConnectionError as e:
        log.error("업무 DB 연결 실패: %s", e)            # 이미 비밀값을 가린 메시지
        raise AuthUnavailable(UNAVAILABLE_MESSAGE) from None
    except psycopg.Error as e:
        log.error("업무 DB 조회 실패: %s", mask_secrets(f"{type(e).__name__}: {e}"))
        raise AuthUnavailable(UNAVAILABLE_MESSAGE) from None


def _public(row: dict) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "team": row["team"]}


def authenticate(email: str, password: str) -> dict | None:
    """맞으면 사용자 정보(해시 제외), 틀리거나 없으면 None. DB 장애는 AuthUnavailable."""
    global _dummy_hash
    row = _query_one("SELECT id, email, name, team, password_hash FROM users WHERE email = %s",
                     ((email or "").strip().lower(),))
    if row is None:
        # 없는 계정도 해시 확인 시간을 비슷하게 맞춥니다 (계정 존재 여부 추측 방지)
        _dummy_hash = _dummy_hash or generate_password_hash("cosmoa-no-such-user")
        check_password_hash(_dummy_hash, password or "")
        return None
    if not check_password_hash(row["password_hash"], password or ""):
        return None
    return dict(_public(row), pw=password_fingerprint(row["password_hash"]))   # pw 는 login_user 가 세션에만 둠


def current_user() -> dict | None:
    """세션의 로그인 사용자. 같은 요청 안에서는 DB 를 한 번만 조회합니다. DB 장애는 AuthUnavailable."""
    cached = g.get("_cosmoa_user", _NOT_LOADED)
    if isinstance(cached, AuthUnavailable):
        raise cached
    if cached is not _NOT_LOADED:
        return cached
    try:
        user = _load_session_user()
    except AuthUnavailable as e:
        g._cosmoa_user = e
        raise
    g._cosmoa_user = user
    return user


def _load_session_user() -> dict | None:
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict) or data.get("v") != SESSION_VERSION or not isinstance(data.get("uid"), int):
        if data is not None or any(k in session for k in LEGACY_SESSION_KEYS):
            session.clear()       # 예전 형식·손상된 세션 → 다시 로그인
        return None
    row = _query_one("SELECT id, email, name, team, password_hash FROM users WHERE id = %s", (data["uid"],))
    if row is None:
        session.clear()           # DB 에서 지워진 사용자
        return None
    given = data.get("pw")
    if not isinstance(given, str) or not hmac.compare_digest(given, password_fingerprint(row["password_hash"])):
        session.clear()           # 비밀번호가 바뀐 뒤의 다른 기기 세션, 또는 지문이 없는 이전 세션 → 다시 로그인
        return None
    return dict(_public(row), logged_in_at=data.get("at"), remember=bool(data.get("remember")))


def login_user(user: dict, remember: bool = False) -> None:
    session.clear()
    # 로그인 시각·유지 여부는 사이드바 "내 계정" 모달(base.html)에서 보여줍니다
    session[SESSION_KEY] = {
        "v": SESSION_VERSION, "uid": int(user["id"]), "remember": bool(remember),
        "at": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M"),
        "csrf": secrets.token_urlsafe(32), "pw": user["pw"],
    }
    session.permanent = remember  # 로그인 상태 유지 → PERMANENT_SESSION_LIFETIME 만큼
    public = {k: v for k, v in user.items() if k != "pw"}
    g._cosmoa_user = dict(public, logged_in_at=session[SESSION_KEY]["at"], remember=bool(remember))


def change_own_password(user_id: int, current_password: str, new_password: str) -> str:
    """로그인한 사용자 **본인**의 비밀번호 변경. user_id 는 호출자가 서버 세션에서 정합니다.
    현재 비밀번호를 확인한 뒤 바꾸고, 새 세션 지문을 돌려줍니다. 입력 오류는 PasswordChangeError, DB 장애는 AuthUnavailable."""
    new_password = new_password or ""
    if not PASSWORD_MIN <= len(new_password) <= PASSWORD_MAX:
        raise PasswordChangeError(f"새 비밀번호는 {PASSWORD_MIN}자 이상 {PASSWORD_MAX}자 이하로 입력해 주세요.")
    if _db is None:
        raise AuthUnavailable("업무 DB(DATABASE_URL)가 설정되지 않았습니다.")
    try:
        with _db.transaction() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if row is None or not check_password_hash(row["password_hash"], current_password or ""):
                raise PasswordChangeError("현재 비밀번호가 맞지 않아요.")
            if check_password_hash(row["password_hash"], new_password):
                raise PasswordChangeError("현재 비밀번호와 다른 비밀번호를 입력해 주세요.")
            new_hash = generate_password_hash(new_password)
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    except DatabaseConnectionError as e:
        log.error("업무 DB 연결 실패: %s", e)
        raise AuthUnavailable(UNAVAILABLE_MESSAGE) from None
    except psycopg.Error as e:
        log.error("비밀번호 변경 실패: %s", mask_secrets(f"{type(e).__name__}: {e}"))
        raise AuthUnavailable(UNAVAILABLE_MESSAGE) from None
    return password_fingerprint(new_hash)


def renew_session_after_password_change(fingerprint: str) -> None:
    """비밀번호를 바꾼 지금 브라우저는 로그인을 이어 가되, 세션을 새로 만들고(CSRF 토큰 교체) 새 지문을 둡니다."""
    data = dict(session.get(SESSION_KEY) or {})
    permanent = session.permanent
    session.clear()
    data.update(csrf=secrets.token_urlsafe(32), pw=fingerprint)
    session[SESSION_KEY] = data
    session.permanent = permanent


def csrf_token() -> str:
    """로그인 세션의 CSRF 토큰. 토큰이 없는 세션(이 기능 이전 로그인)이면 새로 만듭니다. 로그인 전에는 빈 문자열."""
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict) or data.get("v") != SESSION_VERSION:
        return ""
    if not data.get("csrf"):
        data["csrf"] = secrets.token_urlsafe(32)
        session.modified = True
    return data["csrf"]


def csrf_valid() -> bool:
    """X-CSRF-Token 헤더가 세션 토큰과 같은지 (상수 시간 비교)."""
    data = session.get(SESSION_KEY)
    expected = data.get("csrf") if isinstance(data, dict) else None
    given = request.headers.get(CSRF_HEADER, "")
    return bool(expected) and bool(given) and hmac.compare_digest(str(expected), given)


def csrf_form_valid() -> bool:
    """화면 폼의 csrf_token hidden 값이 로그인 세션 토큰과 같은지 (상수 시간 비교)."""
    data = session.get(SESSION_KEY)
    expected = data.get("csrf") if isinstance(data, dict) else None
    given = request.form.get(LOGIN_CSRF_FIELD, "")
    return bool(expected) and bool(given) and hmac.compare_digest(str(expected), given)


def login_csrf_token() -> str:
    """로그인 폼(POST /login)용 CSRF 토큰. 로그인 전 세션에 두고 폼 hidden 값으로 보냅니다.
    로그인 성공 시 login_user() 의 session.clear() 로 사라지고, 로그인 세션은 별도 토큰(csrf_token)을 씁니다."""
    token = session.get(LOGIN_CSRF_KEY)
    if not isinstance(token, str) or not token:
        token = session[LOGIN_CSRF_KEY] = secrets.token_urlsafe(32)
    return token


def login_csrf_valid() -> bool:
    """폼의 csrf_token 이 로그인 전 세션 토큰과 같은지 (상수 시간 비교). 비밀번호 확인·DB 조회 전에 검사합니다."""
    expected = session.get(LOGIN_CSRF_KEY)
    given = request.form.get(LOGIN_CSRF_FIELD, "")
    return isinstance(expected, str) and bool(expected) and bool(given) and hmac.compare_digest(expected, given)


def logout_user() -> None:
    session.clear()
    g.pop("_cosmoa_user", None)


def safe_next(target: str | None) -> str | None:
    """외부 주소로 튕기는 것을 막습니다. 같은 사이트 경로만 허용."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    return target


def wants_json() -> bool:
    """API 요청인지 (JSON 401/503 으로 응답). 페이지는 /login 이동."""
    return request.path.startswith("/api/") or request.is_json


def unauthorized_response():
    if wants_json():
        return jsonify(ok=False, error="로그인 후 다시 이용해 주세요."), 401
    return redirect(url_for("login", next=request.full_path.rstrip("?")))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():          # DB 장애는 AuthUnavailable → app.py 오류 처리기
            return unauthorized_response()
        return view(*args, **kwargs)
    return wrapped


if __name__ == "__main__":
    # 예전 명령 호환: python -m src.common.auth set-password --target dev --email <email>
    # 실제 처리는 관리 명령(endpoint 확인·운영 차단·숨김 입력)이 합니다.
    import sys

    from src.common import db_admin

    sys.exit(db_admin.main(sys.argv[1:]))
