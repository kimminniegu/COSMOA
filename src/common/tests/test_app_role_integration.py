"""앱용 DB 역할(cosmoa_app + 로그인 역할) 검증 — test 브랜치에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_app_role_integration.py"

- TEST_DATABASE_URL(관리 역할)과 TEST_APP_DATABASE_URL(앱 로그인 역할, 풀링 주소)이 모두 있어야 실행합니다. 없으면 건너뜁니다.
- 관리 역할 연결은 대상 식별·역할 확인(app-role check)·테스트 사용자 준비에만 씁니다.
- 앱 요청(Flask test_client)과 금지·한계 확인은 앱 역할 풀링 연결로만 합니다. 앱 연결은 꺼낼 때마다 current_user 를 기록해 확인합니다.
- 금지 동작은 항상 롤백하는 트랜잭션 안에서 실행하고, 권한 오류(42501)로 실행 전에 거부되는지 봅니다. 트리거를 끄거나 행을 지우지 않습니다.
- 테스트 사용자·고객사·프로젝트·저장본은 test DB 에 남습니다 (추가만 표). 실제 팀원·dev 계정은 쓰지 않습니다.
"""
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import unittest
from unittest import mock
import uuid

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402
from src.common.db import Database  # noqa: E402
from src.common.testing import login_form  # noqa: E402

db_admin._load_env()
HAS_DBS = all((os.getenv(v) or "").strip() for v in ("TEST_DATABASE_URL", db_admin.TEST_APP_URL_VAR))
REQUISITION_EXAMPLE = json.loads((Path(__file__).resolve().parents[3] / "db/schemas/requisition.v1.example.json").read_text(encoding="utf-8"))


def payload(**inputs):
    return {"context": {"project_name": "앱 역할 테스트"}, "inputs": dict(inputs), "outputs": {}, "meta": {}}


class RoleRecordingDatabase(Database):
    """연결을 꺼낼 때마다 접속 사용자(current_user)를 기록합니다 — 앱 요청이 실제로 앱 역할로 실행됐는지 확인용."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_users = []

    @contextmanager
    def connection(self):
        with super().connection() as conn:
            self.seen_users.append(conn.execute("SELECT current_user AS u").fetchone()["u"])
            conn.commit()
            yield conn


@unittest.skipUnless(HAS_DBS, "TEST_DATABASE_URL·TEST_APP_DATABASE_URL 없음 — 앱 역할 검증 생략")
class AppRoleIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, admin_url = db_admin.open_verified_test_db()
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]
            cls.admin_role = conn.execute("SELECT current_user AS u").fetchone()["u"]
        app_url, cls.role, cls.endpoint = db_admin.check_test_app_config()
        problems, _ = db_admin.app_role_report("test", cls.role)
        if problems:
            raise RuntimeError("앱 역할 확인 실패 (app-role check):\n  - " + "\n  - ".join(problems))

        from werkzeug.security import generate_password_hash
        cls.password = secrets.token_urlsafe(18)
        cls.users = {}
        setup_db = Database(admin_url, max_size=1, name="test_app_role_setup")   # 테스트 사용자 준비만
        try:
            with setup_db.transaction() as cur:
                for label in ("flow", "password", "other"):
                    cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s) "
                                "RETURNING id, email", (f"approle-{label}-{uuid.uuid4().hex[:8]}@cosmoa.test",
                                                       f"앱 역할 {label}", generate_password_hash(cls.password), system_id))
                    cls.users[label] = cur.fetchone()
        finally:
            setup_db.close()

        cls.app_db = RoleRecordingDatabase(app_url, max_size=3, name="test_app_role")
        cls.app_mod = importlib.import_module("app")
        cls.app_mod.configure_business_db(cls.app_db)
        cls.app = cls.app_mod.app
        cls.app.config["TESTING"] = True
        cls.kick = mock.patch.object(cls.app_mod.home_data, "kick_refresh", side_effect=AssertionError("홈 외부 갱신 호출"))
        cls.kick.start()

    @classmethod
    def tearDownClass(cls):
        cls.kick.stop()
        cls.app_mod.configure_business_db(None)
        cls.app_db.close()

    def setUp(self):
        self.conn, _, _ = db_admin.open_verified_test_app_db()   # 금지·한계 확인용 앱 역할 연결 (풀링)
        self.tag = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.conn.close()

    def assertAppRoleOnly(self):
        self.assertTrue(self.app_db.seen_users, "앱 요청이 업무 DB 를 쓰지 않았습니다")
        self.assertEqual(set(self.app_db.seen_users), {self.role})
        self.assertIs(self.app_mod.business_db, self.app_db)
        self.assertIs(self.app.extensions["business_db"], self.app_db)

    def login(self, client, label):
        self.assertEqual(login_form(client, self.users[label]["email"], self.password).status_code, 302)
        res = client.get("/api/csrf-token")                     # 로그인 세션이 필요한 API
        self.assertEqual(res.status_code, 200)
        return {"X-CSRF-Token": res.get_json()["csrf_token"]}

    def one(self, query, params=()):
        with self.conn.transaction(force_rollback=True):
            return self.conn.execute(query, params).fetchone()

    def assertDenied(self, query, params=(), codes=("42501",)):
        with self.assertRaises(psycopg.Error) as ctx:
            with self.conn.transaction(force_rollback=True):
                self.conn.execute(query, params)
        self.assertIn(ctx.exception.sqlstate, codes, f"{query} → {ctx.exception.sqlstate}")

    # --- 연결·인증 -------------------------------------------------------------

    def test_pooled_connection_authenticates_as_app_role(self):
        who = self.one("""SELECT current_user AS cur, session_user AS ses, current_setting('neon.endpoint_id', true) AS ep,
                                 (SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles
                                   WHERE rolname = current_user) AS admin_attr""")
        self.assertEqual((who["cur"], who["ses"], who["ep"], who["admin_attr"]), (self.role, self.role, self.endpoint, False))
        self.assertNotEqual(self.role, self.admin_role)
        with self.app_db.transaction() as cur:                    # 앱이 쓰는 연결 풀도 같은 역할
            cur.execute("SELECT current_user AS u")
            self.assertEqual(cur.fetchone()["u"], self.role)

    # --- 허용 동작 (Flask test_client → 앱 역할 연결) --------------------------------

    def test_login_session_and_own_password_change(self):
        client = self.app.test_client()
        self.login(client, "password")
        page = client.get("/account/password")
        self.assertEqual(page.status_code, 200)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
        new = secrets.token_urlsafe(14)
        res = client.post("/account/password", data={"current_password": self.password, "new_password": new,
                                                      "confirm_password": new, "csrf_token": token})
        self.assertEqual(res.status_code, 302)
        self.assertIn("changed=1", res.headers["Location"])
        self.assertEqual(login_form(self.app.test_client(), self.users["password"]["email"], self.password).status_code, 401)
        self.assertEqual(login_form(self.app.test_client(), self.users["password"]["email"], new).status_code, 302)
        self.assertAppRoleOnly()

    def test_customer_project_versions_links_and_final(self):
        client = self.app.test_client()
        h = self.login(client, "flow")
        res = client.post("/api/customers", json={"name": f"앱 역할 고객사 {self.tag}"}, headers=h)
        self.assertEqual(res.status_code, 201, res.get_json())
        customer = res.get_json()["customer"]
        listed = client.get(f"/api/customers?q={self.tag}").get_json()["items"]
        self.assertIn(customer["id"], [c["id"] for c in listed])

        res = client.post(f"/api/customers/{customer['id']}/projects", json={"name": "앱 역할 제품", "due_date": None}, headers=h)
        self.assertEqual(res.status_code, 201, res.get_json())
        project = res.get_json()["project"]
        self.assertEqual((project["stage"], project["state"], project["created_by"]["id"]),
                         ("proposal", "active", self.users["flow"]["id"]))
        self.assertEqual(client.get(f"/api/projects/{project['id']}").status_code, 200)
        self.assertEqual([p["id"] for p in client.get(f"/api/customers/{customer['id']}/projects").get_json()["items"]],
                         [project["id"]])

        base = f"/api/projects/{project['id']}/tabs"
        res = client.post(f"{base}/margin/versions", json={"schema_version": 1, "title": "앱 역할 견적", "payload": payload(q=1)},
                          headers=h)
        self.assertEqual(res.status_code, 201, res.get_json())
        v1 = res.get_json()["version"]
        res = client.post(f"{base}/margin/versions", json={"schema_version": 1, "based_on_id": v1["id"], "payload": payload(q=2)},
                          headers=h)
        self.assertEqual((res.status_code, res.get_json()["version"]["version_no"]), (201, 2))
        self.assertEqual([v["version_no"] for v in client.get(f"{base}/margin/versions").get_json()["items"]], [2, 1])
        self.assertEqual(client.get(f"/api/versions/{v1['id']}").get_json()["version"]["payload"]["inputs"], {"q": 1})

        body = json.loads(json.dumps(REQUISITION_EXAMPLE))
        body["context"].update(project_id=project["id"], customer_id=customer["id"])
        res = client.post(f"{base}/requisition/versions", headers=h, json={
            "schema_version": 1, "payload": body,
            "links": [{"source_version_id": v1["id"], "applied_values": {"inserted_text": "VE 반영"}}]})
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual([(l["source_tab"], l["source_version_id"]) for l in res.get_json()["links"]], [("margin", v1["id"])])

        res = client.post(f"{base}/margin/final", json={"action": "set", "version_id": v1["id"], "expected_final_history_id": None},
                          headers=h)
        self.assertEqual(res.status_code, 200, res.get_json())
        current = res.get_json()["final"]["final_history_id"]
        res = client.post(f"{base}/margin/final", json={"action": "unset", "expected_final_history_id": current}, headers=h)
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertIsNone(res.get_json()["final"]["version"])
        self.assertEqual(len(client.get(f"{base}/margin/final/history").get_json()["items"]), 2)
        self.assertAppRoleOnly()

    # --- 금지 동작 (앱 역할 연결, 항상 롤백) -----------------------------------------

    def test_forbidden_writes_on_business_tables(self):
        uid, other = self.users["flow"]["id"], self.users["other"]["id"]
        version = self.one("SELECT id, project_id FROM tab_versions ORDER BY id DESC LIMIT 1")
        customer = self.one("SELECT id FROM customers ORDER BY id DESC LIMIT 1")
        before = self.one("SELECT (SELECT count(*) FROM tab_versions) AS v, (SELECT count(*) FROM customers) AS c")
        for query, params in (
            ("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, 'x', 'scrypt:1$a$0', %s)",
             (f"approle-denied-{self.tag}@cosmoa.test", uid)),
            ("UPDATE users SET email = email WHERE id = %s", (other,)),
            ("UPDATE users SET name = name WHERE id = %s", (other,)),
            ("UPDATE customers SET name = name WHERE id = %s", (customer["id"],)),
            ("UPDATE projects SET stage = stage WHERE id = %s", (version["project_id"],)),
            ("UPDATE projects SET archived_at = archived_at WHERE id = %s", (version["project_id"],)),
            ("INSERT INTO project_history (project_id, field, old_value, new_value, reason, created_by) "
             "VALUES (%s, 'state', 'active', 'hold', 'x', %s)", (version["project_id"], uid)),
            ("INSERT INTO customer_contacts (customer_id, name, created_by) VALUES (%s, 'x', %s)", (customer["id"], uid)),
            ("UPDATE tab_versions SET title = title WHERE id = %s", (version["id"],)),
            ("DELETE FROM tab_versions WHERE id = %s", (version["id"],)),
            ("DELETE FROM customers WHERE id = %s", (customer["id"],)),
            ("TRUNCATE tab_versions", ()),
            ("TRUNCATE version_links", ()),
            ("SELECT * FROM _yoyo_migration", ()),
        ):
            with self.subTest(query=query):
                self.assertDenied(query, params)
        self.assertEqual(self.one("SELECT (SELECT count(*) FROM tab_versions) AS v, (SELECT count(*) FROM customers) AS c"), before)

    def test_forbidden_ddl_role_switch_and_grants(self):
        admin = sql.Identifier(self.admin_role)
        for query in (
            "CREATE TABLE app_role_probe (id int)",
            "CREATE SCHEMA app_role_probe",
            "DROP TABLE version_links",
            "ALTER TABLE tab_versions DISABLE TRIGGER tab_versions_append_only",
            "COMMENT ON TABLE users IS 'x'",
            "CREATE OR REPLACE FUNCTION forbid_append_only_change() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NULL; END$$",
            "SET session_replication_role = replica",
            sql.SQL("SET ROLE {}").format(admin),
            "SET ROLE cosmoa_app",                                         # 상속만, 전환 불가 (SET FALSE)
            "CREATE ROLE app_role_probe",
            sql.SQL("ALTER ROLE {} CREATEROLE").format(sql.Identifier(self.role)),
            sql.SQL("GRANT cosmoa_app TO {}").format(admin),
        ):
            with self.subTest(query=str(query) if isinstance(query, str) else query.as_string(self.conn)):
                self.assertDenied(query)
        # neon_superuser 전환은 Neon 확장이 먼저 막아 XX000 "It is not allowed to change role to neon_superuser" 로 거부됨
        # (멤버십 자체가 없다는 것은 app-role check 의 SET·상속 검사가 확인)
        self.assertDenied("SET ROLE neon_superuser", codes=("42501", "XX000"))
        with self.assertRaises(psycopg.Error) as ctx:                       # 트리거 함수는 직접 호출 불가
            with self.conn.transaction(force_rollback=True):
                self.conn.execute("SELECT forbid_append_only_change()")
        self.assertEqual(ctx.exception.sqlstate, "0A000")
        # GRANT OPTION 이 없으므로 다른 역할에 권한을 넘기면 경고만 나고 실제로 부여되지 않음
        with self.conn.transaction(force_rollback=True):
            self.conn.execute("GRANT SELECT ON users TO PUBLIC")
            self.conn.execute(sql.SQL("GRANT INSERT ON customers TO {}").format(admin))
            row = self.conn.execute("SELECT has_table_privilege('public', 'users', 'SELECT') AS pub, "
                                    "(SELECT relacl::text FROM pg_class WHERE oid = 'customers'::regclass) AS acl").fetchone()
        self.assertFalse(row["pub"])
        self.assertNotIn(f"/{self.role}", row["acl"])                       # 앱 역할이 부여자인 항목 없음
        triggers = self.one("SELECT count(*) AS n FROM pg_trigger WHERE tgname LIKE '%%append_only' AND tgenabled <> 'O'")
        self.assertEqual(triggers["n"], 0)                                  # 트리거는 그대로 켜져 있음

    # --- 한계 (DB 직접 접속 시 가능한 것 — docs/db_rules.md 8장에 기록) ----------------------

    def test_documented_limits_of_app_role(self):
        other = self.users["other"]["id"]
        self.assertIsNotNone(self.one("SELECT password_hash FROM users WHERE id = %s", (other,))["password_hash"])
        with self.conn.transaction(force_rollback=True):
            cur = self.conn.execute("UPDATE users SET password_hash = password_hash WHERE id = %s", (other,))
            self.assertEqual(cur.rowcount, 1)                              # 다른 사용자 행도 DB 수준에서는 수정 가능
            self.conn.execute("CREATE TEMP TABLE app_role_tmp (id int) ON COMMIT DROP")   # PUBLIC 기본 TEMP 권한
            cur = self.conn.execute("INSERT INTO customers (name, created_by) VALUES (%s, %s) RETURNING id",
                                    (f"앱 역할 한계 {self.tag}", other))       # 작성자 값은 DB 가 확인하지 않음 (서버가 세션 사용자로 정함)
            self.assertIsNotNone(cur.fetchone())
        self.assertIsNone(self.one("SELECT id FROM customers WHERE name = %s", (f"앱 역할 한계 {self.tag}",)))   # 롤백됨


@unittest.skipUnless(HAS_DBS, "TEST_DATABASE_URL·TEST_APP_DATABASE_URL 없음 — 앱 역할 검증 생략")
class AppRoleCommandGuardTest(unittest.TestCase):
    """관리 명령의 기존 역할 판단·0004 순서 확인 장치 — 관리 역할로 실행하고 항상 롤백 (역할·권한이 남지 않음)."""

    def setUp(self):
        self.conn, _ = db_admin.open_verified_test_db()

    def tearDown(self):
        self.conn.close()

    def probe_problems(self, *statements):
        with self.conn.transaction(force_rollback=True):
            for statement in statements:
                self.conn.execute(statement)
            return db_admin._role_problems(self.conn, db_admin._role(self.conn, "cosmoa_app_probe"), login=True)

    def test_unknown_or_altered_roles_are_not_adopted(self):
        mark = f"COMMENT ON ROLE cosmoa_app_probe IS '{db_admin.APP_LOGIN_MARK}'"
        self.assertEqual(self.probe_problems("CREATE ROLE cosmoa_app_probe LOGIN INHERIT", mark,
                                             "GRANT cosmoa_app TO cosmoa_app_probe WITH INHERIT TRUE, SET FALSE"), [])
        for label, statements in (
            ("표식 없음", ["CREATE ROLE cosmoa_app_probe LOGIN INHERIT",
                       "GRANT cosmoa_app TO cosmoa_app_probe WITH INHERIT TRUE, SET FALSE"]),
            ("SET ROLE 가능", ["CREATE ROLE cosmoa_app_probe LOGIN INHERIT", mark,
                             "GRANT cosmoa_app TO cosmoa_app_probe WITH INHERIT TRUE, SET TRUE"]),
            ("관리 속성", ["CREATE ROLE cosmoa_app_probe LOGIN INHERIT CREATEDB", mark,
                        "GRANT cosmoa_app TO cosmoa_app_probe WITH INHERIT TRUE, SET FALSE"]),
            ("멤버십 없음", ["CREATE ROLE cosmoa_app_probe LOGIN INHERIT", mark]),
        ):
            with self.subTest(label=label):
                self.assertTrue(self.probe_problems(*statements))
        self.assertIsNone(db_admin._role(self.conn, "cosmoa_app_probe"))      # 롤백되어 남지 않음

    def test_grants_migration_refuses_missing_or_altered_group(self):
        text = (db_admin.MIGRATIONS_DIR / f"{db_admin.APP_GRANTS_MIGRATION}.sql").read_text(encoding="utf-8")
        guard = text[text.index("DO $$"):text.index("$$;") + 3]
        for label, change in (("역할 없음", "ALTER ROLE cosmoa_app RENAME TO cosmoa_app_renamed_probe"),
                              ("표식 없음", "COMMENT ON ROLE cosmoa_app IS NULL"),
                              ("LOGIN 켬", "ALTER ROLE cosmoa_app LOGIN")):
            with self.subTest(label=label), self.assertRaises(psycopg.errors.RaiseException):
                with self.conn.transaction(force_rollback=True):
                    self.conn.execute(change)
                    self.conn.execute(guard)
        with self.conn.transaction(force_rollback=True):
            self.conn.execute(guard)                                         # 현재 역할은 통과
        self.assertEqual(db_admin._app_group_problems(self.conn), [])


if __name__ == "__main__":
    unittest.main()
