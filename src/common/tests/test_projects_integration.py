"""고객사·프로젝트 생성·조회 API 통합 테스트 — TEST_DATABASE_URL(테스트 브랜치)에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_projects_integration.py"

- TEST_DATABASE_URL 이 없으면 건너뛰고, 테스트 DB 식별에 실패하면 멈춥니다. 0003 까지 적용되어 있어야 합니다.
- 테스트 데이터(사용자·고객사·프로젝트)는 test DB 에 남습니다 (고객사·프로젝트는 삭제 대신 보관).
- Flask test_client 만 사용합니다. 웹서버를 띄우지 않고 외부 API 를 호출하지 않습니다.
"""
import importlib
import json
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

db_admin._load_env()


def payload():
    return {"context": {}, "inputs": {}, "outputs": {}, "meta": {}}


@unittest.skipUnless((os.getenv("TEST_DATABASE_URL") or "").strip(), "TEST_DATABASE_URL 없음 — 고객사·프로젝트 API 테스트 생략")
class ProjectsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, url = db_admin.open_verified_test_db()
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]
        cls.db = Database(url, max_size=3, name="test_projects")
        from werkzeug.security import generate_password_hash
        cls.password = secrets.token_urlsafe(18)
        cls.users = []
        with cls.db.transaction() as cur:
            for label in ("a", "b"):
                cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s) RETURNING id, email, name",
                            (f"prj-{label}-{uuid.uuid4().hex[:8]}@cosmoa.test", f"프로젝트 테스트 {label}",
                             generate_password_hash(cls.password), system_id))
                cls.users.append(cur.fetchone())
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

    def setUp(self):
        self.client = self.app.test_client()
        self.tag = uuid.uuid4().hex[:8]      # 이 테스트가 만든 행만 찾기 위한 이름 표식

    def login(self, client=None, user=0):
        client = client or self.client
        from src.common.testing import login_form
        res = login_form(client, self.users[user]["email"], self.password)
        self.assertEqual(res.status_code, 302)
        return {"X-CSRF-Token": client.get("/api/csrf-token").get_json()["csrf_token"]}

    def post(self, url, body, headers):
        return self.client.post(url, json=body, headers=headers)

    def new_customer(self, headers, name=None):
        res = self.post("/api/customers", {"name": name or f"고객사 {self.tag}"}, headers)
        self.assertEqual(res.status_code, 201, res.get_json())
        return res.get_json()["customer"]

    def count(self, table, name_like):
        with self.db.transaction() as cur:
            cur.execute(f"SELECT count(*) AS n FROM {table} WHERE name LIKE %s", (f"%{name_like}%",))   # table 은 고정값만
            return cur.fetchone()["n"]

    def assertError(self, res, status, code):
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (status, code), res.get_json())
        text = res.get_data(as_text=True)
        for leak in ("SELECT", "INSERT", "postgresql://", "psycopg", "Traceback", "Sup3r"):
            self.assertNotIn(leak, text)

    # --- 생성·조회 --------------------------------------------------------------

    def test_create_and_get_customer_and_project(self):
        h = self.login(user=1)
        customer = self.new_customer(h, f"  A사 {self.tag}  ")
        self.assertEqual(customer["name"], f"A사 {self.tag}")                          # 앞뒤 공백 제거
        self.assertEqual(customer["created_by"], {"id": self.users[1]["id"], "name": self.users[1]["name"]})
        self.assertEqual(self.client.get(f"/api/customers/{customer['id']}").get_json()["customer"]["id"], customer["id"])

        res = self.post(f"/api/customers/{customer['id']}/projects", {"name": "비타민 세럼", "due_date": "2026-12-31"}, h)
        self.assertEqual(res.status_code, 201, res.get_json())
        project = res.get_json()["project"]
        self.assertEqual((project["stage"], project["state"], project["due_date"]), ("proposal", "active", "2026-12-31"))
        self.assertEqual(project["customer"], {"id": customer["id"], "name": customer["name"]})
        self.assertEqual(project["created_by"]["id"], self.users[1]["id"])            # 세션 사용자
        no_due = self.post(f"/api/customers/{customer['id']}/projects", {"name": "납기 미정 제품", "due_date": None}, h)
        self.assertIsNone(no_due.get_json()["project"]["due_date"])

        got = self.client.get(f"/api/projects/{project['id']}").get_json()["project"]
        self.assertEqual((got["name"], got["customer"]["id"], got["archived"]), ("비타민 세럼", customer["id"], False))
        with self.db.transaction() as cur:                                            # DB 에 실제로 기록된 값
            cur.execute("SELECT customer_id, stage, state, created_by FROM projects WHERE id = %s", (project["id"],))
            self.assertEqual(cur.fetchone(), {"customer_id": customer["id"], "stage": "proposal", "state": "active",
                                              "created_by": self.users[1]["id"]})

    def test_server_decides_author_and_initial_stage(self):
        h = self.login()
        customer = self.new_customer(h)
        for body in ({"name": f"X {self.tag}", "created_by": self.users[1]["id"]},
                     {"name": f"X {self.tag}", "stage": "order"}, {"name": f"X {self.tag}", "state": "hold"},
                     {"name": f"X {self.tag}", "customer_id": customer["id"]}):
            with self.subTest(body=sorted(body)):
                self.assertError(self.post(f"/api/customers/{customer['id']}/projects", body, h), 400, "unknown_fields")
        self.assertError(self.post("/api/customers", {"name": f"X {self.tag}", "created_by": 1}, h), 400, "unknown_fields")
        self.assertEqual(self.count("projects", f"X {self.tag}") + self.count("customers", f"X {self.tag}"), 0)

    def test_projects_listed_per_customer_with_page_limit(self):
        h = self.login()
        first, second = self.new_customer(h, f"첫째 {self.tag}"), self.new_customer(h, f"둘째 {self.tag}")
        made = [self.post(f"/api/customers/{first['id']}/projects", {"name": f"제품 {i}"}, h).get_json()["project"]["id"]
                for i in range(3)]
        other = self.post(f"/api/customers/{second['id']}/projects", {"name": "다른 고객사 제품"}, h).get_json()["project"]["id"]

        listed = self.client.get(f"/api/customers/{first['id']}/projects").get_json()
        self.assertEqual([p["id"] for p in listed["items"]], made[::-1])               # 최신순, 다른 고객사 제외
        self.assertNotIn(other, [p["id"] for p in listed["items"]])
        self.assertTrue(all(p["customer"]["id"] == first["id"] for p in listed["items"]))
        page = self.client.get(f"/api/customers/{first['id']}/projects?limit=2").get_json()
        self.assertEqual(([p["id"] for p in page["items"]], page["next_before"]), (made[:0:-1], made[1]))
        rest = self.client.get(f"/api/customers/{first['id']}/projects?limit=2&before={page['next_before']}").get_json()
        self.assertEqual(([p["id"] for p in rest["items"]], rest["next_before"]), ([made[0]], None))
        self.assertError(self.client.get(f"/api/customers/{first['id']}/projects?limit=101"), 400, "invalid_parameter")
        self.assertError(self.client.get(f"/api/customers/{first['id']}/projects?limit=0"), 400, "invalid_parameter")
        self.assertError(self.client.get(f"/api/customers/{first['id']}/projects?before=x"), 400, "invalid_parameter")

        with self.db.transaction() as cur:                                            # 보관한 프로젝트는 목록에서 제외
            cur.execute("UPDATE projects SET archived_at = now() WHERE id = %s", (made[0],))
        ids = [p["id"] for p in self.client.get(f"/api/customers/{first['id']}/projects").get_json()["items"]]
        self.assertEqual(ids, made[:0:-1])
        self.assertTrue(self.client.get(f"/api/projects/{made[0]}").get_json()["project"]["archived"])

    def test_customer_list_search_and_paging(self):
        h = self.login()
        names = [f"검색{self.tag} {c}" for c in ("다", "가", "나")]
        for name in names:
            self.new_customer(h, name)
        self.new_customer(h, f"특수{self.tag}%특수_문자")
        listed = self.client.get(f"/api/customers?q=검색{self.tag} &limit=100").get_json()
        self.assertEqual([c["name"] for c in listed["items"]], sorted(names))          # 이름순
        page = self.client.get(f"/api/customers?q=검색{self.tag} &limit=2").get_json()
        self.assertEqual(len(page["items"]), 2)
        rest = self.client.get(f"/api/customers?q=검색{self.tag} &limit=2&after={page['next_after']}").get_json()
        self.assertEqual([c["name"] for c in page["items"] + rest["items"]], sorted(names))
        self.assertIsNone(rest["next_after"])
        literal = self.client.get(f"/api/customers?q={self.tag}%25특수_").get_json()   # % _ 는 글자 그대로 검색
        self.assertEqual([c["name"] for c in literal["items"]], [f"특수{self.tag}%특수_문자"])
        self.assertEqual(self.client.get(f"/api/customers?q={self.tag}%25").get_json()["items"][0]["name"], f"특수{self.tag}%특수_문자")
        self.assertError(self.client.get("/api/customers?limit=101"), 400, "invalid_parameter")
        self.assertError(self.client.get("/api/customers?q=" + "가" * 101), 400, "invalid_parameter")
        self.assertLessEqual(len(self.client.get("/api/customers").get_json()["items"]), 20)   # 기본 페이지 크기

        archived = self.new_customer(h, f"검색{self.tag} 보관")
        with self.db.transaction() as cur:
            cur.execute("UPDATE customers SET archived_at = now() WHERE id = %s", (archived["id"],))
        listed = self.client.get(f"/api/customers?q=검색{self.tag} &limit=100").get_json()
        self.assertNotIn(archived["id"], [c["id"] for c in listed["items"]])
        self.assertError(self.post(f"/api/customers/{archived['id']}/projects", {"name": f"보관 {self.tag}"}, h), 400, "customer_archived")
        self.assertEqual(self.count("projects", f"보관 {self.tag}"), 0)

    # --- 잘못된 입력·없는 대상 ---------------------------------------------------

    def test_invalid_input_rejected(self):
        h = self.login()
        customer = self.new_customer(h)
        url = f"/api/customers/{customer['id']}/projects"
        for body, field in (({"name": "   "}, "name"), ({"name": "가" * 201}, "name"), ({"name": 123}, "name"),
                            ({"name": f"줄\n바꿈 {self.tag}"}, "name"), ({"name": f"P {self.tag}", "due_date": "2026-02-30"}, "due_date"),
                            ({"name": f"P {self.tag}", "due_date": "2026/01/01"}, "due_date"),
                            ({"name": f"P {self.tag}", "due_date": 20260101}, "due_date"), ({"name": f"P {self.tag}", "due_date": ""}, "due_date")):
            with self.subTest(body=body):
                res = self.post(url, body, h)
                self.assertError(res, 400, "invalid_parameter")
                self.assertEqual(res.get_json()["error"]["field"], field)
        self.assertError(self.post(url, {"due_date": "2026-01-01"}, h), 400, "missing_fields")
        self.assertError(self.post("/api/customers", {}, h), 400, "missing_fields")
        self.assertError(self.post("/api/customers", {"name": ""}, h), 400, "invalid_parameter")
        self.assertError(self.post("/api/customers", ["이름"], h), 400, "invalid_json")
        self.assertError(self.client.post("/api/customers", data=b"{bad", headers={**h, "Content-Type": "application/json"}), 400, "invalid_json")
        self.assertError(self.client.post("/api/customers", data={"name": "폼"}, headers=h), 400, "json_required")
        self.assertEqual(self.count("projects", f"P {self.tag}") + self.count("projects", "줄\n바꿈"), 0)

    def test_missing_customer_or_project_404(self):
        h = self.login()
        name = f"없는 고객사 제품 {self.tag}"
        self.assertError(self.post("/api/customers/999999999/projects", {"name": name}, h), 404, "customer_not_found")
        self.assertEqual(self.count("projects", name), 0)
        self.assertError(self.client.get("/api/customers/999999999/projects"), 404, "customer_not_found")
        self.assertError(self.client.get("/api/customers/999999999"), 404, "customer_not_found")
        self.assertError(self.client.get("/api/projects/999999999"), 404, "project_not_found")

    # --- 인증·CSRF·장애 ----------------------------------------------------------

    def test_unauthenticated_401(self):
        for method, path in (("get", "/api/customers"), ("post", "/api/customers"), ("get", "/api/customers/1"),
                             ("get", "/api/customers/1/projects"), ("post", "/api/customers/1/projects"), ("get", "/api/projects/1")):
            with self.subTest(method=method, path=path):
                self.assertError(getattr(self.client, method)(path, json={"name": f"미인증 {self.tag}"}), 401, "unauthorized")
        self.assertEqual(self.count("customers", f"미인증 {self.tag}"), 0)
        self.assertEqual(self.client.get("/dev-request").status_code, 302)               # 화면은 로그인으로 이동

    def test_csrf_required_for_changes(self):
        h = self.login()
        customer = self.new_customer(h)
        other = self.app.test_client()
        other_headers = self.login(other, user=1)
        for headers in ({}, {"X-CSRF-Token": "wrong"}, other_headers):                   # 없음 / 틀림 / 다른 세션 토큰
            with self.subTest(headers=bool(headers)):
                self.assertError(self.post("/api/customers", {"name": f"CSRF {self.tag}"}, headers), 403, "csrf_failed")
                self.assertError(self.post(f"/api/customers/{customer['id']}/projects", {"name": f"CSRF {self.tag}"}, headers),
                                 403, "csrf_failed")
        self.assertEqual(self.count("customers", f"CSRF {self.tag}") + self.count("projects", f"CSRF {self.tag}"), 0)
        self.assertEqual(self.client.get("/api/customers?limit=1").status_code, 200)       # 조회는 토큰 없이

    def test_created_project_used_by_save_api(self):
        h = self.login()
        customer = self.new_customer(h)
        project = self.post(f"/api/customers/{customer['id']}/projects", {"name": "저장 연결 확인"}, h).get_json()["project"]
        body = json.loads((Path(__file__).resolve().parents[3] / "db/schemas/requisition.v1.example.json").read_text(encoding="utf-8"))
        body["context"].update(customer_id=customer["id"], project_id=project["id"])   # 요청서의 연결 프로젝트 = 만든 프로젝트 (id 기준)
        res = self.post(f"/api/projects/{project['id']}/tabs/requisition/versions", {"schema_version": 1, "payload": body}, h)
        self.assertEqual((res.status_code, res.get_json()["version"]["version_no"]), (201, 1), res.get_json())
        margin = self.post(f"/api/projects/{project['id']}/tabs/margin/versions", {"schema_version": 1, "payload": payload()}, h)
        self.assertEqual(margin.status_code, 201)

    def test_db_outage_503_without_secrets(self):
        h = self.login()
        broken = Database("postgresql://u:Sup3r-Secret@127.0.0.1:1/x?connect_timeout=2", timeout=3, name="broken")
        self.app.extensions["business_db"] = broken                                     # 업무 API 만 장애 (로그인 확인은 정상)
        try:
            with self.assertLogs("cosmoa.projects", level="ERROR"):
                res = self.post("/api/customers", {"name": f"장애 {self.tag}"}, h)
            self.assertError(res, 503, "db_unavailable")
            with self.assertLogs("cosmoa.projects", level="ERROR"):
                self.assertError(self.client.get("/api/customers"), 503, "db_unavailable")
        finally:
            self.app.extensions["business_db"] = self.db
            broken.close()


if __name__ == "__main__":
    unittest.main()
