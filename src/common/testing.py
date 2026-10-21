"""테스트 도우미 (PM 관리) — 업무 DB 없이 로그인 세션을 만듭니다. 운영 코드에서는 쓰지 않습니다.

기능 테스트(규제·개발요청서·챗봇 등)는 로그인 자체가 아니라 화면·API 를 확인하므로,
app.py 의 업무 DB 를 메모리 사용자 저장소로 바꿔 dev DB 에 접속하지 않게 합니다.

    from src.common.testing import login_as
    client = app.test_client()
    login_as(client, {"id": 1, "email": "t@example.invalid", "name": "테스트", "team": "B"})

로그인·세션 자체의 검증은 src/common/tests/test_auth_integration.py (test DB) 에서 합니다.
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager


class MemoryUserDB:
    """auth 가 쓰는 Database 대신 쓰는 메모리 저장소. users 조회(id / email)만 흉내 냅니다."""

    def __init__(self, users: list[dict]):
        self.users = {int(u["id"]): {"id": int(u["id"]), "email": u.get("email", ""), "name": u.get("name", ""),
                                      "team": u.get("team", ""), "password_hash": ""} for u in users}

    @contextmanager
    def transaction(self):
        yield _MemoryCursor(self.users)

    def close(self) -> None:
        pass


class _MemoryCursor:
    def __init__(self, users: dict):
        self._users = users
        self._row = None

    def execute(self, sql: str, params: tuple) -> None:
        if "WHERE id = %s" in sql:
            self._row = self._users.get(params[0])
        else:   # 이메일·비밀번호 로그인은 지원하지 않음 (해시 없음)
            self._row = None

    def fetchone(self):
        return dict(self._row) if self._row else None


_LOGIN_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def login_form_token(client) -> str:
    """로그인 화면(GET /login)을 열어 로그인 폼의 CSRF hidden 값을 꺼냅니다."""
    match = _LOGIN_CSRF_RE.search(client.get("/login").get_data(as_text=True))
    if not match:
        raise AssertionError("로그인 화면에 CSRF 토큰이 없습니다.")
    return match.group(1)


def login_form(client, email: str, password: str, **fields):
    """실제 로그인 폼처럼 POST /login (CSRF 토큰 포함). 응답을 돌려줍니다."""
    data = {"email": email, "password": password, "csrf_token": login_form_token(client), **fields}
    return client.post("/login", data=data)


def login_as(client, user: dict, app_module=None) -> None:
    """client 에 로그인 세션(형식 v2)을 넣고, app 의 업무 DB 를 이 사용자만 있는 메모리 저장소로 바꿉니다."""
    app_module = app_module or sys.modules["app"]
    app_module.configure_business_db(MemoryUserDB([user]))
    auth = app_module.auth
    with client.session_transaction() as sess:
        sess.clear()
        sess[auth.SESSION_KEY] = {"v": auth.SESSION_VERSION, "uid": int(user["id"]), "remember": False, "at": None,
                                  "pw": auth.password_fingerprint("", app_module.app.secret_key)}   # 메모리 사용자는 해시 없음
