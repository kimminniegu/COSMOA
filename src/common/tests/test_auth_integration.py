"""로그인(업무 DB users) 통합 테스트 — Flask test_client + TEST_DATABASE_URL(테스트 브랜치)만 사용합니다.

    python -m unittest discover -s src/common/tests -p "test_auth_integration.py"

- TEST_DATABASE_URL 이 없으면 건너뜁니다. 테스트 DB 식별에 실패하면 멈춥니다.
- app.py 를 import 해도 dev DB 에 접속하지 않는지 확인한 뒤, test DB 의 Database 를 주입합니다.
- 실제 웹서버를 띄우지 않고, 외부 API·홈 갱신을 호출하지 않습니다 (홈 갱신은 호출되면 실패하도록 막음).
- 테스트 계정·비밀번호는 실행마다 새로 만들어 test DB 에만 둡니다. 출력하지 않습니다.
"""
import importlib
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402
from src.common.db import Database  # noqa: E402

db_admin._load_env()


@unittest.skipUnless((os.getenv("TEST_DATABASE_URL") or "").strip(), "TEST_DATABASE_URL 없음 — 로그인 통합 테스트 생략")
class AuthIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, url = db_admin.open_verified_test_db()   # 실패하면 GuardError → 중단
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            cls.users_before_import = conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]
            cls.system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]

        cls.app_mod = importlib.import_module("app")
        cls.dev_db_at_import = cls.app_mod.business_db
        cls.dev_pool_opened_at_import = cls.dev_db_at_import is not None and cls.dev_db_at_import._pool is not None
        cls.test_db = Database(url, max_size=2, name="test_auth")
        cls.app_mod.configure_business_db(cls.test_db)
        cls.app = cls.app_mod.app
        cls.app.config["TESTING"] = True
        cls.kick = mock.patch.object(cls.app_mod.home_data, "kick_refresh",
                                     side_effect=AssertionError("테스트 중 홈 외부 갱신 호출"))
        cls.kick.start()

        from werkzeug.security import generate_password_hash
        cls.password = secrets.token_urlsafe(18)
        cls.email = f"login-{uuid.uuid4().hex[:10]}@cosmoa.test"
        with cls.test_db.transaction() as cur:
            cur.execute("INSERT INTO users (email, name, team, password_hash, created_by) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (cls.email, "로그인 테스트", "해외영업팀", generate_password_hash(cls.password), cls.system_id))
            cls.user_id = cur.fetchone()["id"]

    @classmethod
    def tearDownClass(cls):
        cls.kick.stop()
        cls.app_mod.configure_business_db(None)
        cls.test_db.close()

    def setUp(self):
        self.client = self.app.test_client()

    def login(self, email=None, password=None, **extra):
        from src.common.testing import login_form   # 로그인 화면의 CSRF 토큰을 받아 실제 폼처럼 보냄
        return login_form(self.client, email or self.email, password if password is not None else self.password, **extra)

    def assertNoSecrets(self, text):
        for secret in (self.password, "password_hash", "scrypt:", "pbkdf2:", "postgresql://", "Sup3r-Secret"):
            self.assertNotIn(secret, text)

    # --- 시작·초기화 ------------------------------------------------------------

    def test_import_does_not_connect_or_create_tables_or_demo_account(self):
        self.assertFalse(self.dev_pool_opened_at_import, "app import 중 dev 연결 풀이 열렸습니다")
        with self.test_db.transaction() as cur:
            cur.execute("SELECT count(*) AS n FROM users WHERE created_at > now() - interval '1 hour' "
                        "AND email NOT LIKE %s AND email NOT LIKE %s", ("login-%", "%@cosmoa.test"))
            self.assertEqual(cur.fetchone()["n"], 0)   # 데모 계정 등 테스트 외 계정이 생기지 않음
        cache = sqlite3.connect(self.app_mod.HOME_CACHE_DB_PATH)
        try:
            tables = {r[0] for r in cache.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            cache.close()
        self.assertNotIn("users", tables)               # SQLite 계정 테이블을 만들지 않음
        self.assertFalse(hasattr(self.app_mod, "DB_PATH"))

    # --- 로그인·로그아웃 --------------------------------------------------------

    def test_login_and_logout(self):
        res = self.login(remember="1")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["Location"].endswith("/"))
        with self.client.session_transaction() as sess:
            self.assertEqual(set(sess.keys()) - {"_permanent"}, {"auth"})   # _permanent: Flask 의 로그인 유지 표시
            self.assertTrue(sess.permanent)
            self.assertEqual(set(sess["auth"]), {"v", "uid", "remember", "at", "csrf", "pw"})   # pw: 비밀번호 지문(HMAC), 해시 아님
            self.assertEqual((sess["auth"]["v"], sess["auth"]["uid"]), (2, self.user_id))
        page = self.client.get("/regulatory")
        self.assertEqual(page.status_code, 200)
        self.assertIn("로그인 테스트", page.get_data(as_text=True))
        self.assertNoSecrets(page.get_data(as_text=True))
        profile = self.client.get("/api/margin-calculator/quote-profile")
        self.assertEqual(profile.status_code, 200)
        self.assertNoSecrets(profile.get_data(as_text=True))
        out = self.client.get("/logout")
        self.assertTrue(out.headers["Location"].endswith("/login"))
        self.assertEqual(self.client.get("/regulatory").status_code, 302)

    def test_login_form_requires_csrf_token(self):
        from src.common.testing import login_form_token
        other = self.app.test_client()
        other_token = login_form_token(other)                       # 다른 브라우저(세션)의 토큰
        base = {"email": self.email, "password": self.password}
        with mock.patch.object(self.app_mod.auth, "authenticate", side_effect=AssertionError("CSRF 실패인데 계정 조회")):
            for extra in ({}, {"csrf_token": ""}, {"csrf_token": "wrong"}, {"csrf_token": other_token}):
                with self.subTest(token=sorted(extra)):
                    self.client.get("/login")                       # 이 세션에도 토큰은 있음
                    res = self.client.post("/login", data={**base, **extra})
                    self.assertEqual(res.status_code, 400)
                    self.assertIn("보안 확인", res.get_data(as_text=True))
                    self.assertNoSecrets(res.get_data(as_text=True))
                    with self.client.session_transaction() as sess:
                        self.assertNotIn("auth", sess)               # 로그인되지 않음
            fresh = self.app.test_client()                          # 로그인 화면을 열지 않은 세션
            self.assertEqual(fresh.post("/login", data={**base, "csrf_token": other_token}).status_code, 400)
        self.assertEqual(self.login().status_code, 302)              # 올바른 토큰이면 로그인
        with self.client.session_transaction() as sess:
            self.assertNotIn("login_csrf", sess)                    # 로그인 후 로그인 폼 토큰은 사라지고 세션 토큰만 남음
            self.assertTrue(sess["auth"]["csrf"])

    def test_email_is_case_insensitive(self):
        self.assertEqual(self.login(email=self.email.upper()).status_code, 302)

    def test_wrong_password_and_unknown_account(self):
        for email, password in ((self.email, "wrong-" + self.password), (f"none-{uuid.uuid4().hex}@cosmoa.test", self.password),
                                (self.email, "")):
            with self.subTest(case=email[:5]):
                res = self.login(email=email, password=password)
                self.assertEqual(res.status_code, 401)
                body = res.get_data(as_text=True)
                self.assertIn("이메일 또는 비밀번호를 다시 확인해 주세요.", body)
                self.assertNoSecrets(body)
                with self.client.session_transaction() as sess:
                    self.assertNotIn("auth", sess)

    # --- 로그인하지 않은 접근 ---------------------------------------------------

    def test_anonymous_page_redirects_and_api_returns_json_401(self):
        page = self.client.get("/regulatory")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/login?next=/regulatory", page.headers["Location"])
        for path in ("/api/home/data", "/api/margin-calculator/erp-cost"):
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 401)
                self.assertEqual(res.get_json()["ok"], False)

    # --- 세션 형식 ---------------------------------------------------------------

    def test_legacy_sqlite_session_requires_relogin(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"id": self.user_id, "email": self.email, "name": "예전 세션", "team": "B"}
        self.assertEqual(self.client.get("/regulatory").status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user", sess)
        with self.client.session_transaction() as sess:
            sess["user"] = {"id": self.user_id, "email": self.email, "name": "예전 세션", "team": "B"}
        self.assertEqual(self.client.get("/api/margin-calculator/erp-cost").status_code, 401)

    def test_session_for_user_not_in_db_is_rejected(self):
        for bad in ({"v": 2, "uid": -1}, {"v": 1, "uid": self.user_id}, {"v": 2, "uid": str(self.user_id)}):
            with self.subTest(bad=bad):
                with self.client.session_transaction() as sess:
                    sess["auth"] = bad
                self.assertEqual(self.client.get("/regulatory").status_code, 302)
                with self.client.session_transaction() as sess:
                    self.assertNotIn("auth", sess)

    def test_user_lookup_once_per_request(self):
        self.login()
        auth = self.app_mod.auth
        with mock.patch.object(auth, "_query_one", wraps=auth._query_one) as query:
            self.assertEqual(self.client.get("/regulatory").status_code, 200)
        self.assertEqual(query.call_count, 1)

    # --- next 주소 ---------------------------------------------------------------

    def test_unsafe_next_is_blocked(self):
        from src.common.testing import login_form_token
        for target in ("https://evil.example/x", "//evil.example/x", "/\\evil.example", "javascript:alert(1)", "evil"):
            with self.subTest(target=target):
                self.client = self.app.test_client()
                res = self.client.post("/login?next=" + target, data={"email": self.email, "password": self.password,
                                                                         "csrf_token": login_form_token(self.client)})
                self.assertEqual(res.status_code, 302)
                self.assertNotIn("evil", res.headers["Location"])
                self.assertTrue(res.headers["Location"].endswith("/"))
        self.client = self.app.test_client()
        res = self.client.post("/login?next=/margin-calculator", data={"email": self.email, "password": self.password,
                                                                       "csrf_token": login_form_token(self.client)})
        self.assertTrue(res.headers["Location"].endswith("/margin-calculator"))

    # --- DB 장애 -----------------------------------------------------------------

    def test_db_outage_returns_503_without_secrets(self):
        broken = Database("postgresql://cosmoa_user:Sup3r-Secret@127.0.0.1:1/x?connect_timeout=2", timeout=3, name="broken")
        self.app_mod.configure_business_db(broken)
        try:
            with self.assertLogs("cosmoa.auth", level="ERROR") as logs:
                res = self.login()
            self.assertEqual(res.status_code, 503)
            self.assertIn("일시적으로 연결할 수 없습니다", res.get_data(as_text=True))
            self.assertNotIn("다시 확인해 주세요", res.get_data(as_text=True))   # 비밀번호 오류와 구분
            self.assertNoSecrets(res.get_data(as_text=True))
            self.assertNoSecrets("\n".join(logs.output))
            with self.client.session_transaction() as sess:
                sess["auth"] = {"v": 2, "uid": self.user_id}
            page = self.client.get("/regulatory")
            self.assertEqual(page.status_code, 503)
            self.assertNoSecrets(page.get_data(as_text=True))
            with self.assertLogs("cosmoa.auth", level="ERROR"):
                api = self.client.get("/api/margin-calculator/erp-cost")
            self.assertEqual((api.status_code, api.get_json()["ok"]), (503, False))
            self.assertNoSecrets(api.get_data(as_text=True))
        finally:
            self.app_mod.configure_business_db(self.test_db)

    def test_missing_business_db_config_is_unavailable_not_sqlite(self):
        self.app_mod.configure_business_db(None)
        try:
            res = self.login()
            self.assertEqual(res.status_code, 503)
        finally:
            self.app_mod.configure_business_db(self.test_db)


if __name__ == "__main__":
    unittest.main()
