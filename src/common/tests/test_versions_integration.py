"""공통 저장 엔진·API 통합 테스트 — TEST_DATABASE_URL(테스트 브랜치)에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_versions_integration.py"

- TEST_DATABASE_URL 이 없으면 건너뛰고, 테스트 DB 식별에 실패하면 멈춥니다. 0003_versioning 까지 적용되어 있어야 합니다.
- 테스트 데이터(사용자·고객사·프로젝트·저장본)는 test DB 에 남습니다 (저장본·이력은 추가만).
- Flask test_client 만 사용합니다. 웹서버를 띄우지 않고 외부 API 를 호출하지 않습니다.
"""
import base64
import importlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import unittest
from unittest import mock
import uuid

from psycopg import errors

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin, versions_repo  # noqa: E402
from src.common.db import Database  # noqa: E402
from src.common.payloads import Limits, PayloadError, PayloadTooLarge  # noqa: E402
from src.common.projects import create_project  # noqa: E402
from src.common.versions import FinalConflict, InvalidRequest, NotFound, VersionService  # noqa: E402

db_admin._load_env()
FILE_B64 = base64.b64encode(os.urandom(900)).decode()


def payload(**inputs):
    return {"context": {"project_name": "테스트"}, "inputs": dict(inputs), "outputs": {}, "meta": {}}


REQUISITION_EXAMPLE = json.loads((Path(__file__).resolve().parents[3] / "db/schemas/requisition.v1.example.json").read_text(encoding="utf-8"))


def requisition_payload(db, project_id: int) -> dict:
    """개발요청서 저장 계약 v1 예시를 이 프로젝트(고객사·프로젝트 id)에 연결한 payload."""
    body = json.loads(json.dumps(REQUISITION_EXAMPLE))
    with db.transaction() as cur:
        cur.execute("SELECT customer_id FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
    body["context"].update(project_id=project_id, customer_id=row["customer_id"] if row else 1)
    return body


@unittest.skipUnless((os.getenv("TEST_DATABASE_URL") or "").strip(), "TEST_DATABASE_URL 없음 — 저장 엔진 테스트 생략")
class VersioningTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, url = db_admin.open_verified_test_db()
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            cls.system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]
        cls.url = url
        cls.db = Database(url, max_size=4, name="test_versions")
        cls.service = VersionService(cls.db, Limits())
        from werkzeug.security import generate_password_hash
        cls.password = secrets.token_urlsafe(18)
        cls.users = []
        with cls.db.transaction() as cur:
            for label in ("a", "b"):
                cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s) RETURNING id, email",
                            (f"ver-{label}-{uuid.uuid4().hex[:8]}@cosmoa.test", f"저장 테스트 {label}",
                             generate_password_hash(cls.password), cls.system_id))
                cls.users.append(cur.fetchone())
        cls.user_id = cls.users[0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def new_project(self):
        with self.db.transaction() as cur:
            cur.execute("INSERT INTO customers (name, created_by) VALUES (%s, %s) RETURNING id",
                        (f"저장 고객사 {uuid.uuid4().hex[:6]}", self.user_id))
            customer_id = cur.fetchone()["id"]
            return create_project(cur, customer_id=customer_id, name="저장 테스트 제품", actor_id=self.user_id)["id"]

    def save(self, project_id, tab="margin", **kw):
        kw.setdefault("schema_version", 1)
        if "payload" not in kw:   # 개발요청서는 계약 v1 전체 검사 → 프로젝트에 연결된 완전한 payload
            kw["payload"] = requisition_payload(self.db, project_id) if tab == "requisition" else payload()
        return self.service.save_version(project_id=project_id, tab=tab, actor_id=kw.pop("actor_id", self.user_id), **kw)

    def count_versions(self, project_id):
        with self.db.transaction() as cur:
            cur.execute("SELECT count(*) AS n FROM tab_versions WHERE project_id = %s", (project_id,))
            return cur.fetchone()["n"]

    def assertRejected(self, conn, error, query, params=()):
        with self.assertRaises(error):
            with conn.transaction():
                conn.execute(query, params)


class SaveListLoadTest(VersioningTestBase):
    def test_save_list_and_load(self):
        pid = self.new_project()
        first = self.save(pid, title="견적 A", payload=payload(qty=1000))
        self.assertEqual((first["version"]["version_no"], first["base"]["is_stale"]), (1, False))
        second = self.save(pid, based_on_id=first["version"]["id"], payload=payload(qty=2000))
        self.assertEqual((second["version"]["version_no"], second["version"]["based_on_version_no"]), (2, 1))
        self.assertEqual(self.save(pid, tab="requisition")["version"]["version_no"], 1)   # 탭별 번호

        listed = self.service.list_versions(project_id=pid, tab="margin")
        self.assertEqual([v["version_no"] for v in listed["items"]], [2, 1])
        self.assertEqual(listed["items"][1]["title"], "견적 A")
        self.assertNotIn("payload", listed["items"][0])
        page = self.service.list_versions(project_id=pid, tab="margin", limit=1)
        self.assertEqual(([v["version_no"] for v in page["items"]], page["next_before"]), ([2], 2))
        page2 = self.service.list_versions(project_id=pid, tab="margin", limit=1, before=page["next_before"])
        self.assertEqual([v["version_no"] for v in page2["items"]], [1])
        with self.assertRaises(InvalidRequest):
            self.service.list_versions(project_id=pid, tab="margin", limit=101)

        loaded = self.service.get_version(second["version"]["id"])
        self.assertEqual(loaded["payload"]["inputs"], {"qty": 2000})
        self.assertEqual((loaded["created_by"]["id"], loaded["based_on_id"]), (self.user_id, first["version"]["id"]))
        with self.assertRaises(NotFound):
            self.service.get_version(-1)
        with self.assertRaises(NotFound):
            self.service.list_versions(project_id=-1, tab="margin")

    def test_stale_base_is_saved_and_reported(self):
        pid = self.new_project()
        v1 = self.save(pid)["version"]
        self.save(pid, based_on_id=v1["id"])
        v3 = self.save(pid, based_on_id=v1["id"])        # v1 을 불러와 편집 → 최신은 v2
        self.assertEqual(v3["version"]["version_no"], 3)
        self.assertEqual(v3["base"], {"based_on_id": v1["id"], "based_on_version_no": 1,
                                      "latest_version_no_before_save": 2, "is_stale": True})

    def test_client_cannot_choose_author_or_number(self):
        pid = self.new_project()
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                row = conn.execute("INSERT INTO tab_versions (project_id, tab, version_no, schema_version, payload, created_by) "
                                   "VALUES (%s, 'margin', 99, 1, %s, %s) RETURNING version_no",
                                   (pid, '{"context":{},"inputs":{},"outputs":{},"meta":{}}', self.user_id)).fetchone()
                self.assertEqual(row["version_no"], 1)       # DB 가 부여

    def test_archived_project_rejects_save(self):
        pid = self.new_project()
        with self.db.transaction() as cur:
            cur.execute("UPDATE projects SET archived_at = now() WHERE id = %s", (pid,))
        with self.assertRaises(InvalidRequest) as ctx:
            self.save(pid)
        self.assertEqual(ctx.exception.code, "project_archived")


class ConcurrencyTest(VersioningTestBase):
    def test_concurrent_saves_get_distinct_numbers(self):
        pid = self.new_project()
        barrier, results, failures = threading.Barrier(2), [], []

        def worker():
            try:
                barrier.wait(10)
                for _ in range(4):
                    results.append(self.save(pid)["version"]["version_no"])
            except Exception as e:   # noqa: BLE001
                failures.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(results), list(range(1, 9)))

    def test_db_assigns_numbers_even_without_app_lock(self):
        pid = self.new_project()
        body = '{"context":{},"inputs":{},"outputs":{},"meta":{}}'
        with self.db.connection() as a, self.db.connection() as b:
            a.execute("INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) "
                      "VALUES (%s, 'simulation', 1, %s, %s)", (pid, body, self.user_id))   # a 가 프로젝트 잠금 보유
            out = {}

            def second():
                out["no"] = b.execute("INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) "
                                      "VALUES (%s, 'simulation', 1, %s, %s) RETURNING version_no",
                                      (pid, body, self.user_id)).fetchone()["version_no"]
                b.commit()

            t = threading.Thread(target=second)
            t.start()
            t.join(2)
            self.assertTrue(t.is_alive())     # a 가 커밋할 때까지 기다림
            a.commit()
            t.join(20)
        self.assertEqual(out["no"], 2)

    def test_concurrent_final_change_conflicts(self):
        pid = self.new_project()
        v1, v2 = self.save(pid)["version"]["id"], self.save(pid)["version"]["id"]
        barrier, outcome = threading.Barrier(2), []

        def worker(version_id, user):
            barrier.wait(10)
            try:
                self.service.change_final(project_id=pid, tab="margin", actor_id=user, action="set",
                                          version_id=version_id, expected_final_history_id=None)
                outcome.append("ok")
            except FinalConflict as e:
                outcome.append(("conflict", e.extra["current"]["version"]["id"]))

        threads = [threading.Thread(target=worker, args=(v, u["id"])) for v, u in ((v1, self.users[0]), (v2, self.users[1]))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        winner = self.service.get_final(project_id=pid, tab="margin")["version"]["id"]
        self.assertEqual(outcome.count("ok"), 1, outcome)
        self.assertIn(("conflict", winner), outcome)          # 진 쪽은 409 + 이긴 쪽 상태를 받음
        self.assertEqual(len(self.service.final_history(project_id=pid, tab="margin")["items"]), 1)


class ScopeTest(VersioningTestBase):
    def test_other_project_and_wrong_tab_references_rejected(self):
        p1, p2 = self.new_project(), self.new_project()
        m1 = self.save(p1)["version"]["id"]
        r1 = self.save(p1, tab="requisition")["version"]["id"]
        m2 = self.save(p2)["version"]["id"]
        cases = [
            ("invalid_based_on", dict(based_on_id=m2)),          # 다른 프로젝트
            ("invalid_based_on", dict(based_on_id=r1)),          # 같은 프로젝트 다른 탭
            ("invalid_link_source", dict(links=[{"source_version_id": m2, "applied_values": {"a": 1}}], tab="requisition")),
            ("invalid_link_source", dict(links=[{"source_version_id": m1, "applied_values": {"a": 1}}])),   # 같은 탭
        ]
        for code, kw in cases:
            with self.subTest(code=code, kw=sorted(kw)), self.assertRaises(InvalidRequest) as ctx:
                self.save(p1, **kw)
            self.assertEqual(ctx.exception.code, code)
        for version_id, code in ((m2, "invalid_version_scope"), (r1, "invalid_version_scope")):
            with self.assertRaises(InvalidRequest) as ctx:
                self.service.change_final(project_id=p1, tab="margin", actor_id=self.user_id, action="set",
                                          version_id=version_id, expected_final_history_id=None)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(PayloadError):
            self.save(p1, tab="pricing")

    def test_db_rejects_cross_project_and_cross_tab_rows(self):
        p1, p2 = self.new_project(), self.new_project()
        m1 = self.save(p1)["version"]["id"]
        r1 = self.save(p1, tab="requisition")["version"]["id"]
        m2 = self.save(p2)["version"]["id"]
        body = '{"context":{},"inputs":{},"outputs":{},"meta":{}}'
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                ins = ("INSERT INTO tab_versions (project_id, tab, based_on_id, schema_version, payload, created_by) "
                       "VALUES (%s, %s, %s, 1, %s, %s)")
                self.assertRejected(conn, errors.ForeignKeyViolation, ins, (p1, "margin", m2, body, self.user_id))
                self.assertRejected(conn, errors.ForeignKeyViolation, ins, (p1, "margin", r1, body, self.user_id))
                self.assertRejected(conn, errors.CheckViolation, ins, (p1, "pricing", None, body, self.user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) "
                                    "VALUES (%s, 'margin', 1, '{\"context\":{}}', %s)", (p1, self.user_id))
                fin = "INSERT INTO final_history (project_id, tab, action, version_id, created_by) VALUES (%s, %s, %s, %s, %s)"
                self.assertRejected(conn, errors.ForeignKeyViolation, fin, (p1, "margin", "set", m2, self.user_id))
                self.assertRejected(conn, errors.ForeignKeyViolation, fin, (p1, "margin", "set", r1, self.user_id))
                self.assertRejected(conn, errors.CheckViolation, fin, (p1, "margin", "set", None, self.user_id))
                self.assertRejected(conn, errors.CheckViolation, fin, (p1, "margin", "unset", m1, self.user_id))
                new = conn.execute("INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) "
                                   "VALUES (%s, 'requisition', 1, %s, %s) RETURNING id", (p1, body, self.user_id)).fetchone()["id"]
                link = ("INSERT INTO version_links (project_id, version_id, tab, source_tab, source_version_id, applied_values, "
                        "created_by) VALUES (%s, %s, %s, %s, %s, '{\"a\":1}', %s)")
                self.assertRejected(conn, errors.ForeignKeyViolation, link, (p1, new, "requisition", "margin", m2, self.user_id))
                self.assertRejected(conn, errors.CheckViolation, link, (p1, new, "requisition", "requisition", r1, self.user_id))
                conn.execute(link, (p1, new, "requisition", "margin", m1, self.user_id))   # 같은 프로젝트 다른 탭: 허용


class ImmutabilityTest(VersioningTestBase):
    def test_update_delete_truncate_blocked(self):
        pid = self.new_project()
        m = self.save(pid)["version"]["id"]
        r = self.save(pid, tab="requisition", links=[{"source_version_id": m, "applied_values": {"a": 1}}])
        self.service.change_final(project_id=pid, tab="margin", actor_id=self.user_id, action="set", version_id=m,
                                  expected_final_history_id=None)
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                for table, key in (("tab_versions", "id"), ("final_history", "project_id"), ("version_links", "project_id")):
                    value = m if table == "tab_versions" else pid
                    with self.subTest(table=table):
                        self.assertRejected(conn, errors.RestrictViolation, f"UPDATE {table} SET created_by = created_by WHERE {key} = %s", (value,))
                        self.assertRejected(conn, errors.RestrictViolation, f"DELETE FROM {table} WHERE {key} = %s", (value,))
                        self.assertRejected(conn, errors.RestrictViolation, f"TRUNCATE {table} CASCADE")
        self.assertEqual(len(self.service.get_version(r["version"]["id"])["links"]), 1)

    def test_links_only_in_same_transaction_as_new_version(self):
        pid = self.new_project()
        m = self.save(pid)["version"]["id"]
        r = self.save(pid, tab="requisition")["version"]["id"]   # 이미 커밋된 저장본
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                self.assertRejected(conn, errors.IntegrityConstraintViolation,
                                    "INSERT INTO version_links (project_id, version_id, tab, source_tab, source_version_id, "
                                    "applied_values, created_by) VALUES (%s, %s, 'requisition', 'margin', %s, '{\"a\":1}', %s)",
                                    (pid, r, m, self.user_id))


class FinalTest(VersioningTestBase):
    def test_set_change_unset_and_history(self):
        pid = self.new_project()
        v1, v2 = self.save(pid)["version"]["id"], self.save(pid)["version"]["id"]
        state = self.service.get_final(project_id=pid, tab="margin")
        self.assertEqual((state["final_history_id"], state["version"]), (None, None))
        change = self.service.change_final
        with self.assertRaises(InvalidRequest) as ctx:          # 필드 누락 ≠ null
            change(project_id=pid, tab="margin", actor_id=self.user_id, action="set", version_id=v1)
        self.assertEqual(ctx.exception.code, "expected_final_history_id_required")
        s1 = change(project_id=pid, tab="margin", actor_id=self.user_id, action="set", version_id=v1,
                    expected_final_history_id=None)
        self.assertEqual(s1["version"]["id"], v1)
        with self.assertRaises(InvalidRequest) as ctx:
            change(project_id=pid, tab="margin", actor_id=self.user_id, action="set", version_id=v1,
                   expected_final_history_id=s1["final_history_id"])
        self.assertEqual(ctx.exception.code, "already_final")
        s2 = change(project_id=pid, tab="margin", actor_id=self.users[1]["id"], action="set", version_id=v2,
                    expected_final_history_id=s1["final_history_id"])
        self.assertEqual((s2["version"]["version_no"], s2["changed_by"]["id"]), (2, self.users[1]["id"]))
        with self.assertRaises(FinalConflict) as ctx:            # 오래된 기준(s1)으로 변경 시도
            change(project_id=pid, tab="margin", actor_id=self.user_id, action="unset",
                   expected_final_history_id=s1["final_history_id"])
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.extra["current"]["final_history_id"], s2["final_history_id"])
        s3 = change(project_id=pid, tab="margin", actor_id=self.user_id, action="unset",
                    expected_final_history_id=s2["final_history_id"])
        self.assertEqual((s3["action"], s3["version"]), ("unset", None))
        with self.assertRaises(InvalidRequest) as ctx:
            change(project_id=pid, tab="margin", actor_id=self.user_id, action="unset",
                   expected_final_history_id=s3["final_history_id"])
        self.assertEqual(ctx.exception.code, "no_final")
        history = self.service.final_history(project_id=pid, tab="margin")
        self.assertEqual([h["action"] for h in history["items"]], ["unset", "set", "set"])
        self.assertFalse(any(v["is_final"] for v in self.service.list_versions(project_id=pid, tab="margin")["items"]))


class AtomicityTest(VersioningTestBase):
    def test_invalid_link_rolls_back_whole_save(self):
        pid, other = self.new_project(), self.new_project()
        m = self.save(pid)["version"]["id"]
        m_other = self.save(other)["version"]["id"]
        before = self.count_versions(pid)
        with self.assertRaises(InvalidRequest):
            self.save(pid, tab="requisition", links=[{"source_version_id": m, "applied_values": {"a": 1}},
                                                     {"source_version_id": m_other, "applied_values": {"b": 2}}])
        self.assertEqual(self.count_versions(pid), before)

    def test_failure_after_version_insert_rolls_back(self):
        pid = self.new_project()
        m = self.save(pid)["version"]["id"]
        before = self.count_versions(pid)
        real = versions_repo.insert_link
        with mock.patch.object(versions_repo, "insert_link", side_effect=RuntimeError("중간 실패")):
            with self.assertRaises(RuntimeError):
                self.save(pid, tab="requisition", links=[{"source_version_id": m, "applied_values": {"a": 1}}])
        self.assertIs(versions_repo.insert_link, real)
        self.assertEqual(self.count_versions(pid), before)
        ok = self.save(pid, tab="requisition", links=[{"source_version_id": m, "applied_values": {"inserted_text": "VE"}}])
        self.assertEqual(ok["version"]["version_no"], 1)      # 실패한 저장은 번호도 쓰지 않음
        self.assertEqual(len(ok["links"]), 1)


class RequisitionContractTest(VersioningTestBase):
    """개발요청서 v1: 요청서의 연결 프로젝트·고객사 id 를 서버가 저장 대상과 대조하고, 이름 사본은 DB 값으로 저장."""

    def test_context_must_match_target_project_and_customer(self):
        pid, other = self.new_project(), self.new_project()
        wrong_project = requisition_payload(self.db, other)          # 다른 프로젝트에 연결된 요청서
        with self.assertRaises(InvalidRequest) as ctx:
            self.save(pid, tab="requisition", payload=wrong_project)
        self.assertEqual(ctx.exception.code, "context_project_mismatch")
        wrong_customer = requisition_payload(self.db, pid)
        wrong_customer["context"]["customer_id"] = requisition_payload(self.db, other)["context"]["customer_id"]
        with self.assertRaises(InvalidRequest) as ctx:
            self.save(pid, tab="requisition", payload=wrong_customer)
        self.assertEqual(ctx.exception.code, "context_customer_mismatch")
        self.assertEqual(self.count_versions(pid), 0)

    def test_names_snapshot_from_db_and_fully_validated(self):
        pid = self.new_project()
        body = requisition_payload(self.db, pid)
        body["context"].update(customer_name="화면에서 잘못 입력한 이름", project_name="옛 이름")
        saved = self.save(pid, tab="requisition", payload=body)
        self.assertEqual((saved["validation"]["level"], saved["validation"]["fully_validated"]), ("full", True))
        with self.db.transaction() as cur:
            cur.execute("""SELECT v.payload->'context' AS c, p.name AS project_name, cu.name AS customer_name
                           FROM tab_versions v JOIN projects p ON p.id = v.project_id JOIN customers cu ON cu.id = p.customer_id
                           WHERE v.id = %s""", (saved["version"]["id"],))
            row = cur.fetchone()
        self.assertEqual((row["c"]["project_name"], row["c"]["customer_name"]), (row["project_name"], row["customer_name"]))
        self.assertEqual(row["c"]["project_id"], pid)
        other = self.save(pid, tab="margin")                           # 다른 탭은 기존 검증 수준 그대로
        self.assertEqual((other["validation"]["level"], other["validation"]["fully_validated"]), ("structure", False))


class FileAndSizeTest(VersioningTestBase):
    def test_file_body_never_stored(self):
        pid = self.new_project()
        m = self.save(pid)["version"]["id"]
        p = requisition_payload(self.db, pid)
        p["meta"]["reference_files"] = [{"name": "a.png", "size": 3, "type": "image/png", "data_url": "data:image/png;base64," + FILE_B64}]
        p["inputs"]["raw_extracted_data"] = {"text": "원문"}
        saved = self.save(pid, tab="requisition", payload=p,
                          links=[{"source_version_id": m, "applied_values": {"inserted_text": "x", "data_url": "y"}}])
        self.assertIn("meta.reference_files[0].data_url", saved["validation"]["removed_fields"])
        self.assertIn("links[0].applied_values.data_url", saved["validation"]["removed_fields"])
        with self.db.transaction() as cur:
            cur.execute("SELECT v.payload::text AS p, l.applied_values::text AS a FROM tab_versions v "
                        "JOIN version_links l ON l.version_id = v.id WHERE v.id = %s", (saved["version"]["id"],))
            row = cur.fetchone()
        for text in (row["p"], row["a"]):
            self.assertNotIn("base64", text)
            self.assertNotIn("data_url", text)
        self.assertNotIn("raw_extracted_data", row["p"])
        before = self.count_versions(pid)
        for bad in (payload(image=FILE_B64), payload(image="data:image/png;base64,iVBORw0KGgo=")):
            with self.assertRaises(PayloadError):
                self.save(pid, payload=bad)
        with self.assertRaises(PayloadError):
            self.save(pid, tab="requisition", links=[{"source_version_id": m, "applied_values": {"img": "data:image/png;base64,AAAA"}}])
        self.assertEqual(self.count_versions(pid), before)

    def test_size_limit_rejects_without_saving(self):
        pid = self.new_project()
        small = VersionService(self.db, Limits(payload_bytes=1000, applied_values_bytes=200, links_per_save=1))
        with self.assertRaises(PayloadTooLarge):
            small.save_version(project_id=pid, tab="margin", actor_id=self.user_id, schema_version=1,
                               payload=payload(text="가" * 400))
        self.assertEqual(self.count_versions(pid), 0)


class ApiTest(VersioningTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
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
        super().tearDownClass()

    def setUp(self):
        self.app.config["VERSION_LIMITS"] = Limits()
        self.client = self.app.test_client()

    def login(self, client=None):
        client = client or self.client
        from src.common.testing import login_form
        res = login_form(client, self.users[0]["email"], self.password)
        self.assertEqual(res.status_code, 302)
        token = client.get("/api/csrf-token").get_json()["csrf_token"]
        self.assertTrue(token)
        return {"X-CSRF-Token": token}

    def assertClean(self, res):
        text = res.get_data(as_text=True)
        for leak in ("SELECT", "INSERT", "postgresql://", "psycopg", "Traceback", "Sup3r"):
            self.assertNotIn(leak, text)

    def test_unauthenticated_401(self):
        pid = self.new_project()
        for method, path in (("get", f"/api/projects/{pid}/tabs/margin/versions"), ("post", f"/api/projects/{pid}/tabs/margin/versions"),
                             ("get", "/api/versions/1"), ("get", f"/api/projects/{pid}/tabs/margin/final"),
                             ("post", f"/api/projects/{pid}/tabs/margin/final"), ("get", f"/api/projects/{pid}/tabs/margin/final/history"),
                             ("get", "/api/csrf-token")):
            with self.subTest(path=path, method=method):
                res = getattr(self.client, method)(path, json={})
                self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (401, "unauthorized"))

    def test_csrf_and_json_required(self):
        pid = self.new_project()
        headers = self.login()
        url = f"/api/projects/{pid}/tabs/margin/versions"
        body = {"schema_version": 1, "payload": payload()}
        self.assertEqual(self.client.post(url, json=body).status_code, 403)
        self.assertEqual(self.client.post(url, json=body, headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post(url, data={"schema_version": "1"}, headers=headers).status_code, 400)
        other = self.app.test_client()
        other_headers = self.login(other)
        self.assertEqual(self.client.post(url, json=body, headers=other_headers).status_code, 403)   # 다른 세션 토큰
        self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 201)
        self.assertEqual(self.count_versions(pid), 1)

    def test_api_flow_and_status_codes(self):
        pid = self.new_project()
        h = self.login()
        base = f"/api/projects/{pid}/tabs"
        created = self.client.post(f"{base}/margin/versions", json={"schema_version": 1, "title": "견적 A", "payload": payload(q=1)}, headers=h)
        self.assertEqual(created.status_code, 201)
        v1 = created.get_json()["version"]
        self.assertEqual((v1["version_no"], v1["created_by"]["id"]), (1, self.user_id))
        self.assertEqual(created.get_json()["validation"]["fully_validated"], False)

        r = self.client.post(f"{base}/requisition/versions", headers=h, json={
            "schema_version": 1, "payload": requisition_payload(self.db, pid),
            "links": [{"source_version_id": v1["id"], "applied_values": {"inserted_text": "VE 반영"}}]})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(r.get_json()["validation"]["fully_validated"], True)        # 개발요청서 v1 계약 전체 검사
        partial = self.client.post(f"{base}/requisition/versions", headers=h, json={
            "schema_version": 1, "payload": payload(target_prices=[{"amount": 1300, "currency": "KRW"}])})
        self.assertEqual((partial.status_code, partial.get_json()["error"]["code"]), (400, "missing_field"))

        for body, code in (({"schema_version": 1, "payload": payload(), "created_by": 999}, "unknown_fields"),
                           ({"schema_version": 1, "payload": payload(), "version_no": 9}, "unknown_fields"),
                           ({"payload": payload()}, "missing_fields"),
                           ({"schema_version": 1, "payload": {"inputs": {}}}, "invalid_payload"),
                           ({"schema_version": 1, "payload": payload(img=FILE_B64)}, "file_content_not_allowed")):
            with self.subTest(code=code):
                res = self.client.post(f"{base}/margin/versions", json=body, headers=h)
                self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (400, code))
                self.assertClean(res)
        self.assertEqual(self.client.post(f"{base}/pricing/versions", json={"schema_version": 1, "payload": payload()}, headers=h).status_code, 400)
        self.assertEqual(self.client.get(f"{base}/margin/versions?limit=abc").status_code, 400)
        self.assertEqual(self.client.post("/api/projects/999999999/tabs/margin/versions", json={"schema_version": 1, "payload": payload()}, headers=h).status_code, 404)
        self.assertEqual(self.client.get("/api/versions/999999999").status_code, 404)

        listed = self.client.get(f"{base}/margin/versions?limit=10").get_json()
        self.assertEqual([v["version_no"] for v in listed["items"]], [1])
        loaded = self.client.get(f"/api/versions/{v1['id']}").get_json()["version"]
        self.assertEqual(loaded["payload"]["inputs"], {"q": 1})

        final = self.client.get(f"{base}/margin/final").get_json()["final"]
        self.assertIsNone(final["final_history_id"])
        missing = self.client.post(f"{base}/margin/final", json={"action": "set", "version_id": v1["id"]}, headers=h)
        self.assertEqual((missing.status_code, missing.get_json()["error"]["code"]), (400, "expected_final_history_id_required"))
        ok = self.client.post(f"{base}/margin/final", json={"action": "set", "version_id": v1["id"], "expected_final_history_id": None}, headers=h)
        self.assertEqual(ok.status_code, 200)
        conflict = self.client.post(f"{base}/margin/final", json={"action": "unset", "expected_final_history_id": None}, headers=h)
        self.assertEqual(conflict.status_code, 409)
        err = conflict.get_json()["error"]
        self.assertEqual((err["code"], err["current"]["version"]["id"]), ("final_conflict", v1["id"]))
        self.assertTrue(self.client.get(f"{base}/margin/versions").get_json()["items"][0]["is_final"])
        self.assertEqual(len(self.client.get(f"{base}/margin/final/history").get_json()["items"]), 1)

    def test_size_limit_413(self):
        pid = self.new_project()
        h = self.login()
        self.app.config["VERSION_LIMITS"] = Limits(payload_bytes=1000, applied_values_bytes=100, links_per_save=1)
        res = self.client.post(f"/api/projects/{pid}/tabs/margin/versions", json={"schema_version": 1, "payload": payload(t="가" * 400)}, headers=h)
        self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (413, "payload_too_large"))
        huge = self.client.post(f"/api/projects/{pid}/tabs/margin/versions", json={"schema_version": 1, "payload": payload(t="가" * 20000)}, headers=h)
        self.assertEqual(huge.status_code, 413)
        self.assertEqual(self.count_versions(pid), 0)

    def test_db_outage_503_without_secrets(self):
        pid = self.new_project()
        h = self.login()
        broken = Database("postgresql://u:Sup3r-Secret@127.0.0.1:1/x?connect_timeout=2", timeout=3, name="broken")
        self.app.extensions["business_db"] = broken          # 저장 API 만 장애 (로그인 확인은 정상 DB)
        try:
            with self.assertLogs("cosmoa.versions", level="ERROR"):
                res = self.client.post(f"/api/projects/{pid}/tabs/margin/versions", json={"schema_version": 1, "payload": payload()}, headers=h)
            self.assertEqual((res.status_code, res.get_json()["error"]["code"]), (503, "db_unavailable"))
            self.assertClean(res)
        finally:
            self.app.extensions["business_db"] = self.db
            broken.close()
        self.app_mod.configure_business_db(broken)           # 로그인 확인까지 장애
        try:
            res = self.client.get(f"/api/projects/{pid}/tabs/margin/versions")
            self.assertEqual(res.status_code, 503)
            self.assertClean(res)
        finally:
            self.app_mod.configure_business_db(self.db)


if __name__ == "__main__":
    unittest.main()
