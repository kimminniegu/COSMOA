"""업무 DB 공통 모듈 단위 테스트 — 원격 DB·외부 API 에 접속하지 않습니다.

    python -m unittest discover -s src/common/tests -p "test_db_unit.py"
"""
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db, db_admin, projects  # noqa: E402

DEV_POOLED = "postgresql://app:Pw-dev-9x@ep-dev-alpha-11111111-pooler.c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"
DEV_DIRECT = "postgresql://app:Pw-dev-9x@ep-dev-alpha-11111111.c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"
TEST_DIRECT = "postgresql://app:Pw-test-7y@ep-test-beta-22222222.c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"
FAKE_ENV = {"DATABASE_URL": DEV_POOLED, "DATABASE_URL_DIRECT": DEV_DIRECT, "TEST_DATABASE_URL": TEST_DIRECT,
            "TEST_DATABASE_ENDPOINT_ID": "ep-test-beta-22222222", "DEV_DATABASE_ENDPOINT_ID": "ep-dev-alpha-11111111"}
DB_HASH_RE = r"^(scrypt|pbkdf2):[^$]+\$[^$]+\$[0-9a-f]+$"   # 0001_core users_password_hash_format 과 같은 식


class FakeConn:
    """접속 없이 server_identity() 결과만 돌려주는 연결."""
    def __init__(self, **ident):
        self.ident = {"db": "neondb", "endpoint": "ep-dev-alpha-11111111", "branch": "br-dev-1", "comment": None, **ident}
        self.closed = False

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return self.ident

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class UrlHelpersTest(unittest.TestCase):
    def test_endpoint_id_strips_pooler(self):
        self.assertEqual(db.neon_endpoint_id(DEV_POOLED), "ep-dev-alpha-11111111")
        self.assertEqual(db.neon_endpoint_id(DEV_DIRECT), "ep-dev-alpha-11111111")
        self.assertTrue(db.is_pooled_url(DEV_POOLED))
        self.assertFalse(db.is_pooled_url(DEV_DIRECT))
        self.assertIsNone(db.neon_endpoint_id("postgresql://u:p@localhost/x"))

    def test_mask_secrets_hides_password_url_and_host(self):
        msg = f'failed: {TEST_DIRECT} host "ep-test-beta-22222222.c-4.us-west-2.aws.neon.tech" password Pw-test-7y'
        masked = db.mask_secrets(msg, TEST_DIRECT)
        for secret in ("Pw-test-7y", "ep-test-beta", "postgresql://"):
            self.assertNotIn(secret, masked)

    def test_yoyo_url_uses_psycopg3_scheme_and_keeps_params(self):
        converted = db_admin.yoyo_url(TEST_DIRECT)
        self.assertTrue(converted.startswith("postgresql+psycopg://"))
        self.assertTrue(converted.endswith("/neondb?sslmode=require"))

    def test_env_url_does_not_fall_back(self):
        with patch.dict(os.environ, {"DATABASE_URL": DEV_POOLED}, clear=True):
            with self.assertRaises(db.DatabaseConfigError):
                db.env_url("TEST_DATABASE_URL")


class DatabaseModuleTest(unittest.TestCase):
    def test_import_and_construct_do_not_connect(self):
        with patch("psycopg_pool.ConnectionPool.open") as opened, patch("psycopg.connect") as connected:
            importlib.import_module("src.common.db")
            database = db.Database(TEST_DIRECT)
            self.assertNotIn("Pw-test-7y", repr(database))
        opened.assert_not_called()
        connected.assert_not_called()

    def test_connection_error_is_masked(self):
        # 로컬 닫힌 포트 — 외부 접속 없음
        url = "postgresql://someone:Sup3r-Secret@127.0.0.1:1/x?connect_timeout=2"
        database = db.Database(url, timeout=3)
        with self.assertRaises(db.DatabaseConnectionError) as ctx:
            with database.transaction():
                pass
        self.assertNotIn("Sup3r-Secret", str(ctx.exception))
        self.assertNotIn("postgresql://", str(ctx.exception))
        database.close()


class TestGuardTest(unittest.TestCase):
    ident = {"db": "neondb", "endpoint": "ep-test-beta-22222222", "branch": "br-test-1",
             "comment": db_admin.marker_text("ep-test-beta-22222222", "br-test-1")}

    def test_config_passes_for_pinned_test_endpoint(self):
        with patch.dict(os.environ, FAKE_ENV, clear=True):
            url, allowed = db_admin.check_test_config()
        self.assertEqual(allowed, "ep-test-beta-22222222")

    def test_config_rejects_missing_pin_or_other_endpoint(self):
        for change in ({"TEST_DATABASE_ENDPOINT_ID": ""},
                       {"TEST_DATABASE_ENDPOINT_ID": "ep-dev-alpha-11111111"},
                       {"TEST_DATABASE_URL": DEV_DIRECT, "TEST_DATABASE_ENDPOINT_ID": "ep-dev-alpha-11111111"},
                       {"TEST_DATABASE_URL": TEST_DIRECT.replace("22222222.", "22222222-pooler.")}):
            with self.subTest(change=sorted(change)), patch.dict(os.environ, {**FAKE_ENV, **change}, clear=True):
                with self.assertRaises((db_admin.GuardError, db.DatabaseConfigError)):
                    db_admin.check_test_config()

    def test_identity_passes_only_with_matching_marker(self):
        db_admin.verify_test_identity(dict(self.ident), "ep-test-beta-22222222")

    def test_identity_rejects_missing_marker(self):
        with self.assertRaises(db_admin.GuardError):
            db_admin.verify_test_identity(dict(self.ident, comment=None), "ep-test-beta-22222222")

    def test_copied_marker_fails_on_other_branch_or_endpoint(self):
        # 표식이 다른 브랜치로 복제된 경우: 서버 endpoint·branch 가 표식과 다름
        with self.assertRaises(db_admin.GuardError):
            db_admin.verify_test_identity(dict(self.ident, branch="br-child-2"), "ep-test-beta-22222222")
        with self.assertRaises(db_admin.GuardError):
            db_admin.verify_test_identity(dict(self.ident, endpoint="ep-child-33333333"), "ep-child-33333333")
        with self.assertRaises(db_admin.GuardError):
            db_admin.verify_test_identity(dict(self.ident, endpoint="ep-dev-alpha-11111111"), "ep-test-beta-22222222")

    def test_config_rejects_test_endpoint_equal_to_dev_pin(self):
        with patch.dict(os.environ, dict(FAKE_ENV, DEV_DATABASE_ENDPOINT_ID="ep-test-beta-22222222",
                                         DATABASE_URL="", DATABASE_URL_DIRECT=""), clear=True):
            with self.assertRaises(db_admin.GuardError):
                db_admin.check_test_config()

    def test_dev_target_rejects_test_endpoint_before_connecting(self):
        env = dict(FAKE_ENV, DATABASE_URL_DIRECT=TEST_DIRECT, DATABASE_URL=TEST_DIRECT.replace("22222222.", "22222222-pooler."),
                   DEV_DATABASE_ENDPOINT_ID="ep-test-beta-22222222")
        with patch.dict(os.environ, env, clear=True), patch.object(db_admin, "connect") as connected:
            with self.assertRaises(db_admin.GuardError):
                db_admin.open_verified_dev_db()
        connected.assert_not_called()

    def test_dev_target_rejects_missing_or_mismatched_pin_before_connecting(self):
        for change in ({"DEV_DATABASE_ENDPOINT_ID": ""},
                       {"DEV_DATABASE_ENDPOINT_ID": "ep-other-44444444"},
                       {"DATABASE_URL": ""},
                       {"DATABASE_URL": DEV_POOLED.replace("/neondb", "/otherdb")},
                       {"DATABASE_URL_DIRECT": DEV_POOLED}):
            with self.subTest(change=sorted(change)), patch.dict(os.environ, {**FAKE_ENV, **change}, clear=True),                     patch.object(db_admin, "connect") as connected:
                with self.assertRaises((db_admin.GuardError, db.DatabaseConfigError)):
                    db_admin.open_verified_dev_db()
                connected.assert_not_called()

    def test_dev_target_checks_server_reported_endpoint_and_marker(self):
        cases = {"server endpoint differs": FakeConn(endpoint="ep-other-44444444"),
                 "test marker present": FakeConn(comment=db_admin.marker_text("ep-dev-alpha-11111111", "br-dev-1"))}
        for label, fake in cases.items():
            with self.subTest(label), patch.dict(os.environ, FAKE_ENV, clear=True),                     patch.object(db_admin, "connect", return_value=fake):
                with self.assertRaises(db_admin.GuardError):
                    db_admin.open_verified_dev_db()
                self.assertTrue(fake.closed)
        fake = FakeConn()
        with patch.dict(os.environ, FAKE_ENV, clear=True), patch.object(db_admin, "connect", return_value=fake):
            conn, _ = db_admin.open_verified_dev_db()
        self.assertIs(conn, fake)

    def test_production_env_refuses_all_admin_commands_without_connecting(self):
        for prod in ({"COSMOA_ENV": "production"}, {"RENDER": "true"}):
            env = {**FAKE_ENV, **prod}
            with self.subTest(prod=prod), patch.dict(os.environ, env, clear=True),                     patch.object(db_admin, "connect") as connected, patch("getpass.getpass") as asked:
                for target in ("dev", "test"):
                    with self.assertRaises(db_admin.GuardError):
                        db_admin.open_target(target)
                with self.assertRaises(db_admin.GuardError):
                    db_admin.init_test_marker()
                for argv in (["test-marker", "check"], ["test-marker", "init"], ["status", "--target", "dev"],
                             ["migrate", "--target", "dev"], ["migrate", "--target", "test"],
                             ["create-first-user", "--target", "dev", "--email", "a@b.co", "--name", "x"]):
                    with patch("sys.stderr"):
                        self.assertEqual(db_admin.main(argv), 2, argv)
                connected.assert_not_called()
                asked.assert_not_called()

    def test_dev_target_rejects_mixed_pooled_and_direct(self):
        env = dict(FAKE_ENV, DATABASE_URL=DEV_POOLED.replace("alpha", "gamma"))
        with patch.dict(os.environ, env, clear=True), patch.object(db_admin, "connect") as connected:
            with self.assertRaises(db_admin.GuardError):
                db_admin.open_verified_dev_db()
        connected.assert_not_called()

    def test_rollback_only_for_test_target(self):
        with self.assertRaises(db_admin.GuardError):
            db_admin.rollback_last("dev")


class MigrationFilesTest(unittest.TestCase):
    def test_first_migration_creates_stage1_tables_only(self):
        files = db_admin.migration_files()
        self.assertEqual(files["0001_core"],
                         {"users", "customers", "customer_contacts", "projects", "project_history"})


class PasswordHashFormatTest(unittest.TestCase):
    """DB CHECK 는 형식만 본다. 실제 비밀번호 검증은 check_password_hash (통합 테스트에서 저장·조회 후 확인)."""

    def test_werkzeug_hashes_match_db_format_and_verify(self):
        import re
        from werkzeug.security import check_password_hash, generate_password_hash
        for method in ("scrypt", "pbkdf2:sha256"):
            with self.subTest(method=method):
                hashed = generate_password_hash("correct-horse-9", method=method)
                self.assertRegex(hashed, DB_HASH_RE)
                self.assertTrue(check_password_hash(hashed, "correct-horse-9"))
                self.assertFalse(check_password_hash(hashed, "wrong-horse-9"))
        self.assertIsNone(re.match(DB_HASH_RE, "plaintext-password"))


TEST_APP_POOLED = ("postgresql://cosmoa_app_test:Pw-app-5z@ep-test-beta-22222222-pooler.c-4.us-west-2.aws.neon.tech/neondb"
                   "?sslmode=require")


class AppRoleGuardTest(unittest.TestCase):
    """앱용 DB 역할 명령의 접속 전 확인 (DB 접속 없음)."""

    def test_login_role_name_rule(self):
        self.assertEqual(db_admin.validate_app_login_name(" cosmoa_app_test "), "cosmoa_app_test")
        for bad in ("cosmoa_app", "cosmoa_app_", "cosmoa_app_Test", "cosmoa_app_1a", "neondb_owner", 'cosmoa_app_"x"',
                    "cosmoa_app_x; DROP ROLE y", "cosmoa_app_" + "a" * 41, ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                db_admin.validate_app_login_name(bad)

    def test_test_app_url_must_be_pooled_app_role_on_test_endpoint(self):
        with patch.dict(os.environ, {**FAKE_ENV, "TEST_APP_DATABASE_URL": TEST_APP_POOLED}, clear=True):
            self.assertEqual(db_admin.check_test_app_config()[1:], ("cosmoa_app_test", "ep-test-beta-22222222"))
        for bad in ("", TEST_APP_POOLED.replace("-pooler.", "."),                          # 직접 연결
                    TEST_APP_POOLED.replace("ep-test-beta-22222222", "ep-dev-alpha-11111111"),   # dev endpoint
                    TEST_APP_POOLED.replace("cosmoa_app_test", "app"),                       # 관리 역할
                    TEST_APP_POOLED.replace("/neondb", "/otherdb")):
            with self.subTest(bad=bad[:40]), patch.dict(os.environ, {**FAKE_ENV, "TEST_APP_DATABASE_URL": bad}, clear=True):
                with self.assertRaises((db_admin.GuardError, db.DatabaseConfigError)):
                    db_admin.check_test_app_config()

    def test_create_login_rejects_bad_input_before_connecting(self):
        with patch.dict(os.environ, FAKE_ENV, clear=True), patch.object(db_admin, "connect") as connected:
            for name, password in (("cosmoa_app_test", "short-pass"), ("bad name", "x" * 32)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    db_admin.create_app_login("test", name, password)
            connected.assert_not_called()

    def test_app_role_commands_refused_in_production(self):
        for prod in ({"COSMOA_ENV": "production"}, {"RENDER": "true"}):
            with self.subTest(prod=prod), patch.dict(os.environ, {**FAKE_ENV, **prod}, clear=True), \
                    patch.object(db_admin, "connect") as connected, patch("getpass.getpass") as asked:
                for action in (["init-group"], ["create-login", "--role", "cosmoa_app_test"], ["check"], ["whoami"]):
                    with patch("sys.stderr"):
                        self.assertEqual(db_admin.main(["app-role", *action, "--target", "test"]), 2, action)
                connected.assert_not_called()
                asked.assert_not_called()


class ProjectChangeValidationTest(unittest.TestCase):
    def test_requires_actor_and_reason(self):
        with self.assertRaises(PermissionError):
            projects.change_project(None, 1, actor_id=None, stage="development")
        with self.assertRaises(ValueError):
            projects.change_project(None, 1, actor_id=1, state="hold")
        with self.assertRaises(ValueError):
            projects.change_project(None, 1, actor_id=1, stage="bogus")
        with self.assertRaises(PermissionError):
            projects.create_project(None, customer_id=1, name="x", actor_id=None)
        with self.assertRaises(ValueError):
            projects.create_project(None, customer_id=1, name="  ", actor_id=1)


if __name__ == "__main__":
    unittest.main()
