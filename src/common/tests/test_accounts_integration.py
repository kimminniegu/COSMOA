"""팀원 계정 추가(관리 명령)·본인 비밀번호 변경(화면) 통합 테스트 — TEST_DATABASE_URL(테스트 브랜치)에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_accounts_integration.py"

- TEST_DATABASE_URL 이 없으면 건너뛰고, 테스트 DB 식별에 실패하면 멈춥니다.
- 테스트 계정은 무작위 이메일(@cosmoa.test)로 test DB 에만 만듭니다 (계정은 삭제하지 않고 남음). 실제 팀원 정보는 쓰지 않습니다.
- Flask test_client 만 사용합니다. 웹서버를 띄우지 않고 외부 API 를 호출하지 않습니다.
"""
import contextlib
import importlib
import io
import os
from pathlib import Path
import secrets
import sys
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402
from src.common.db import Database  # noqa: E402
from src.common.db_admin import GuardError  # noqa: E402
from src.common.testing import login_form  # noqa: E402

db_admin._load_env()
HAS_TEST_DB = bool((os.getenv("TEST_DATABASE_URL") or "").strip())


class AccountInputTest(unittest.TestCase):
    """DB 접속 없이 확인하는 입력 규칙·운영 차단."""

    def test_normalize_account(self):
        self.assertEqual(db_admin.normalize_account("  New.Member@Cosmoa.TEST ", " 새 팀원 ", " 영업 "),
                         ("new.member@cosmoa.test", "새 팀원", "영업"))
        for email, name in (("no-at-sign", "a"), ("a@b", "a"), ("a b@c.d", "a"), ("a@c.d", " "), ("a@c.d", "가" * 101)):
            with self.subTest(email=email, name=name), self.assertRaises(ValueError):
                db_admin.normalize_account(email, name)

    def test_create_user_refused_in_production_before_any_prompt(self):
        for env in ({"COSMOA_ENV": "production"}, {"RENDER": "true"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env), \
                    mock.patch.object(db_admin.getpass, "getpass", side_effect=AssertionError("비밀번호를 물으면 안 됨")), \
                    mock.patch.object(db_admin, "open_target", side_effect=AssertionError("접속하면 안 됨")):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = db_admin.main(["create-user", "--target", "dev", "--email", "x@cosmoa.test", "--name", "x",
                                          "--by", "admin@cosmoa.test"])
                self.assertEqual(code, 2)
                self.assertIn("운영 환경", err.getvalue())


@unittest.skipUnless(HAS_TEST_DB, "TEST_DATABASE_URL 없음 — 계정 통합 테스트 생략")
class AccountsIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, url = db_admin.open_verified_test_db()
        with conn:
            system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]
        cls.db = Database(url, max_size=3, name="test_accounts")
        from werkzeug.security import generate_password_hash
        cls.admin_password = secrets.token_urlsafe(18)
        cls.admin_email = f"acct-admin-{uuid.uuid4().hex[:8]}@cosmoa.test"
        with cls.db.transaction() as cur:     # 계정 생성 담당자 역할을 할 테스트 계정
            cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                        (cls.admin_email, "계정 담당 테스트", generate_password_hash(cls.admin_password), system_id))
            cls.admin_id = cur.fetchone()["id"]
        cls.app_mod = importlib.import_module("app")
        cls.app_mod.configure_business_db(cls.db)
        cls.app = cls.app_mod.app
        cls.app.config["TESTING"] = True
        cls.kick = mock.patch.object(cls.app_mod.home_data, "kick_refresh", side_effect=AssertionError("홈 외부 갱신 호출"))
        cls.kick.start()

    @classmethod
    def tearDownClass(cls):
        cls.kick.stop()
        cls.app_mod.configure_business_db(None)
        cls.db.close()

    def user_row(self, email):
        with self.db.transaction() as cur:
            cur.execute("SELECT id, email, name, team, password_hash, created_by FROM users WHERE email = %s", (email,))
            return cur.fetchone()

    def new_user(self, password=None):
        email = f"acct-{uuid.uuid4().hex[:8]}@cosmoa.test"
        password = password or secrets.token_urlsafe(14)
        user_id = db_admin.create_user("test", email=email, name="계정 테스트", team="QA", password=password,
                                       created_by_email=self.admin_email, created_by_password=self.admin_password)
        return user_id, email, password

    # --- 계정 추가 (관리 명령) -----------------------------------------------------

    def test_create_user_records_creator_and_verifiable_hash(self):
        from werkzeug.security import check_password_hash
        tag = uuid.uuid4().hex[:8]
        password = secrets.token_urlsafe(14)
        user_id = db_admin.create_user("test", email=f"  Member-{tag}@Cosmoa.TEST ", name=" 팀원 ", team=" 개발 ",
                                       password=password, created_by_email=self.admin_email.upper(),
                                       created_by_password=self.admin_password)
        row = self.user_row(f"member-{tag}@cosmoa.test")                          # 이메일 정규화
        self.assertEqual((row["id"], row["name"], row["team"], row["created_by"]), (user_id, "팀원", "개발", self.admin_id))
        self.assertNotEqual(row["password_hash"], password)
        self.assertTrue(check_password_hash(row["password_hash"], password))
        self.assertFalse(check_password_hash(row["password_hash"], password + "x"))
        res = login_form(self.app.test_client(), f"member-{tag}@cosmoa.test", password)   # 만든 계정으로 로그인
        self.assertEqual(res.status_code, 302)

    def test_duplicate_and_bad_creator_rejected_without_writing(self):
        _, email, _ = self.new_user()
        with self.assertRaises(GuardError):                                        # 대소문자만 다른 중복
            db_admin.create_user("test", email=email.upper(), name="중복", team="", password="x" * 12,
                                 created_by_email=self.admin_email, created_by_password=self.admin_password)
        with self.assertRaises(GuardError):
            db_admin.check_create_user_possible("test", email, "중복", "", self.admin_email)
        fresh = f"acct-{uuid.uuid4().hex[:8]}@cosmoa.test"
        for by, by_password in ((self.admin_email, "wrong-password"), (f"nobody-{uuid.uuid4().hex[:6]}@cosmoa.test", "x" * 12)):
            with self.subTest(by=by[:12]), self.assertRaises(GuardError):
                db_admin.create_user("test", email=fresh, name="담당 확인 실패", team="", password="x" * 12,
                                     created_by_email=by, created_by_password=by_password)
        with self.assertRaises(GuardError):
            db_admin.check_create_user_possible("test", fresh, "x", "", f"nobody-{uuid.uuid4().hex[:6]}@cosmoa.test")
        with self.assertRaises(ValueError):                                        # 짧은 비밀번호는 접속 전에 거부
            db_admin.create_user("test", email=fresh, name="짧음", team="", password="short",
                                 created_by_email=self.admin_email, created_by_password=self.admin_password)
        self.assertIsNone(self.user_row(fresh))

    def test_cli_hidden_prompts_and_no_secret_output(self):
        email = f"acct-cli-{uuid.uuid4().hex[:8]}@cosmoa.test"
        new_password = secrets.token_urlsafe(14)
        argv = ["create-user", "--target", "test", "--email", email, "--name", "명령 테스트", "--by", self.admin_email]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(db_admin.getpass, "getpass", side_effect=[self.admin_password, new_password, new_password + "x"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(db_admin.main(argv), 1)                               # 확인 값 불일치 → 만들지 않음
        self.assertIsNone(self.user_row(email))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(db_admin.getpass, "getpass", side_effect=[self.admin_password, new_password, new_password]) as asked, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(db_admin.main(argv), 0)
        self.assertEqual(asked.call_count, 3)                                     # 모두 숨김 입력
        row = self.user_row(email)
        self.assertEqual(row["created_by"], self.admin_id)
        printed = out.getvalue() + err.getvalue()
        for secret in (new_password, self.admin_password, row["password_hash"], "scrypt:", "postgresql://",
                       os.getenv("TEST_DATABASE_URL")):
            self.assertNotIn(secret, printed)

    # --- 본인 비밀번호 변경 (화면) ---------------------------------------------------

    def page_token(self, client):
        import re
        html = client.get("/account/password").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def change(self, client, current, new, confirm=None, token=None, **extra):
        data = {"current_password": current, "new_password": new, "confirm_password": new if confirm is None else confirm,
                "csrf_token": self.page_token(client) if token is None else token, **extra}
        return client.post("/account/password", data=data)

    def test_change_own_password_and_session_effects(self):
        user_id, email, old = self.new_user()
        here, other_device = self.app.test_client(), self.app.test_client()
        self.assertEqual(login_form(here, email, old).status_code, 302)
        self.assertEqual(login_form(other_device, email, old).status_code, 302)
        new = secrets.token_urlsafe(14)
        res = self.change(here, old, new)
        self.assertEqual(res.status_code, 302)
        self.assertIn("changed=1", res.headers["Location"])
        page = here.get("/account/password?changed=1")
        self.assertEqual(page.status_code, 200)                                    # 이 브라우저는 로그인 유지
        self.assertIn("비밀번호를 변경했어요", page.get_data(as_text=True))
        with here.session_transaction() as sess:
            self.assertNotIn(new, str(sess))
        self.assertEqual(other_device.get("/regulatory").status_code, 302)          # 다른 기기의 기존 세션은 로그아웃
        self.assertEqual(other_device.get("/api/customers").status_code, 401)
        self.assertEqual(login_form(self.app.test_client(), email, old).status_code, 401)   # 이전 비밀번호 거부
        self.assertEqual(login_form(self.app.test_client(), email, new).status_code, 302)

    def test_change_rejections_and_no_other_user(self):
        user_id, email, old = self.new_user()
        victim_id, victim_email, victim_password = self.new_user()
        victim_hash = self.user_row(victim_email)["password_hash"]
        client = self.app.test_client()
        self.assertEqual(client.get("/account/password").status_code, 302)          # 로그인 필요
        self.assertEqual(client.post("/account/password", data={}).status_code, 302)
        login_form(client, email, old)
        before = self.user_row(email)["password_hash"]
        new = secrets.token_urlsafe(14)
        cases = [
            ("CSRF 없음", dict(token=""), "보안 확인"),
            ("CSRF 다름", dict(token="wrong"), "보안 확인"),
            ("현재 비밀번호 틀림", dict(current="wrong-" + old), "현재 비밀번호가 맞지 않아요"),
            ("확인 값 다름", dict(confirm=new + "x"), "확인 값이 달라요"),
            ("너무 짧음", dict(new="short", confirm="short"), "8자 이상"),
            ("현재와 같음", dict(new=old, confirm=old), "현재 비밀번호와 다른"),
        ]
        for label, override, message in cases:
            with self.subTest(label=label):
                kwargs = {"current": old, "new": new, **override}
                res = self.change(client, kwargs.pop("current"), kwargs.pop("new"), **kwargs)
                self.assertEqual(res.status_code, 400)
                text = res.get_data(as_text=True)
                self.assertIn(message, text)
                for secret in (old, new, before, "scrypt:", "postgresql://"):
                    self.assertNotIn(secret, text)
        self.assertEqual(self.user_row(email)["password_hash"], before)            # 실패 시 그대로
        # 다른 사람 대상 지정 시도: 폼의 사용자 값은 무시되고 세션 사용자만 바뀜
        res = self.change(client, old, new, user_id=str(victim_id), email=victim_email, uid=str(victim_id))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.user_row(victim_email)["password_hash"], victim_hash)
        self.assertNotEqual(self.user_row(email)["password_hash"], before)
        self.assertEqual(login_form(self.app.test_client(), victim_email, victim_password).status_code, 302)

    def test_admin_set_password_also_ends_existing_sessions(self):
        _, email, old = self.new_user()
        client = self.app.test_client()
        login_form(client, email, old)
        self.assertEqual(client.get("/regulatory").status_code, 200)
        db_admin.set_password("test", email, secrets.token_urlsafe(14))
        self.assertEqual(client.get("/regulatory").status_code, 302)


if __name__ == "__main__":
    unittest.main()
