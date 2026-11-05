"""업무 DB 통합 테스트 — TEST_DATABASE_URL(테스트 브랜치)에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_db_integration.py"

- TEST_DATABASE_URL 이 없으면 건너뜁니다. DATABASE_URL 등으로 대체하지 않습니다.
- 테스트 DB 식별(허용 endpoint + DB 표식)에 실패하면 오류로 멈춥니다. 표식을 자동으로 만들지 않습니다.
- 0001_core·0002_project_rules 가 적용되어 있어야 합니다: python -m src.common.db_admin migrate --target test
- 테스트 데이터는 테스트 DB 에 남습니다. (project_history 는 추가만, 고객사·프로젝트는 삭제 금지)
"""
import os
from pathlib import Path
import sys
import unittest
import uuid

from psycopg import errors

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402
from src.common.db import Database  # noqa: E402
from src.common.projects import change_project, create_project  # noqa: E402

db_admin._load_env()
HASH = "scrypt:32768:8:1$testsalt$" + "ab" * 32


@unittest.skipUnless((os.getenv("TEST_DATABASE_URL") or "").strip(), "TEST_DATABASE_URL 없음 — 업무 DB 테스트 생략")
class CoreSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, url = db_admin.open_verified_test_db()   # 실패하면 GuardError → 테스트 중단
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['applied']} {state['problems']}")
            with conn.transaction():
                row = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()
                if row is None:   # 테스트 DB 의 시스템 계정 (테스트 전용)
                    row = conn.execute(
                        "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) RETURNING id",
                        ("system-test@cosmoa.test", "테스트 시스템 계정", HASH)).fetchone()
        cls.system_id = row["id"]
        cls.db = Database(url, max_size=2, name="test_database_url")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _run_id(self):
        return uuid.uuid4().hex[:10]

    def _new_user(self, cur):
        cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                    (f"user-{self._run_id()}@cosmoa.test", "테스트 사용자", HASH, self.system_id))
        return cur.fetchone()["id"]

    def _new_project(self, **extra):
        with self.db.transaction() as cur:
            user_id = self._new_user(cur)
            cur.execute("INSERT INTO customers (name, created_by) VALUES (%s, %s) RETURNING id",
                        (f"테스트 고객사 {self._run_id()}", user_id))
            customer_id = cur.fetchone()["id"]
            project = create_project(cur, customer_id=customer_id, name="테스트 제품", actor_id=user_id,
                                     due_date=extra.get("due_date"))
        return user_id, customer_id, project

    def _project(self, project_id):
        with self.db.transaction() as cur:
            cur.execute("SELECT stage, state, due_date FROM projects WHERE id = %s", (project_id,))
            current = cur.fetchone()
            cur.execute("SELECT field, old_value, new_value, reason, created_by FROM project_history "
                        "WHERE project_id = %s ORDER BY id", (project_id,))
            return current, cur.fetchall()

    def assertRejected(self, conn, error, query, params=()):
        with self.assertRaises(error):
            with conn.transaction():    # 저장점 — 실패해도 바깥 트랜잭션은 계속
                conn.execute(query, params)

    # --- FK / CHECK -----------------------------------------------------------

    def test_required_fk_and_check_constraints(self):
        user_id, customer_id, project = self._new_project()
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                pid = project["id"]
                self.assertRejected(conn, errors.ForeignKeyViolation,
                                    "INSERT INTO projects (customer_id, name, created_by) VALUES (%s, 'x', %s)",
                                    (-1, user_id))
                self.assertRejected(conn, errors.ForeignKeyViolation,
                                    "INSERT INTO customers (name, created_by) VALUES ('x', %s)", (-1,))
                self.assertRejected(conn, errors.NotNullViolation,
                                    "INSERT INTO customers (name) VALUES ('작성자 없음')")
                self.assertRejected(conn, errors.NotNullViolation,
                                    "INSERT INTO project_history (project_id, field, old_value, new_value) "
                                    "VALUES (%s, 'stage', 'proposal', 'development')", (pid,))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO projects (customer_id, name, created_by, stage) VALUES (%s, 'x', %s, 'bogus')",
                                    (customer_id, user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO projects (customer_id, name, created_by, state) VALUES (%s, 'x', %s, 'paused')",
                                    (customer_id, user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO project_history (project_id, field, old_value, new_value, created_by) "
                                    "VALUES (%s, 'state', 'active', 'hold', %s)", (pid, user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO project_history (project_id, field, old_value, new_value, reason, created_by) "
                                    "VALUES (%s, 'state', 'active', 'drop', '   ', %s)", (pid, user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, 'x', %s, %s)",
                                    (f"plain-{self._run_id()}@cosmoa.test", "plaintext-password", user_id))
                self.assertRejected(conn, errors.CheckViolation,
                                    "INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, 'x', %s, %s)",
                                    (f"Upper-{self._run_id()}@cosmoa.test", HASH, user_id))
                # 최초 계정 외에는 created_by NULL 불가 (시스템 계정은 하나만)
                self.assertRejected(conn, errors.UniqueViolation,
                                    "INSERT INTO users (email, name, password_hash) VALUES (%s, 'x', %s)",
                                    (f"second-system-{self._run_id()}@cosmoa.test", HASH))
                # 신규 프로젝트는 proposal / active 로만 생성 (0002)
                for column, value in (("state", "hold"), ("state", "drop"), ("stage", "development"),
                                      ("stage", "completed")):
                    self.assertRejected(conn, errors.CheckViolation,
                                        f"INSERT INTO projects (customer_id, name, created_by, {column}) "
                                        "VALUES (%s, 'x', %s, %s)", (customer_id, user_id, value))
                # 납기일 미정(NULL)·생성 시 납기일 입력 허용
                conn.execute("INSERT INTO projects (customer_id, name, created_by, due_date) VALUES (%s, 'x', %s, NULL)",
                             (customer_id, user_id))
                row = conn.execute("INSERT INTO projects (customer_id, name, created_by, due_date) "
                                   "VALUES (%s, 'x', %s, '2027-01-15') RETURNING stage, state, due_date",
                                   (customer_id, user_id)).fetchone()
                self.assertEqual((row["stage"], row["state"], row["due_date"].isoformat()),
                                 ("proposal", "active", "2027-01-15"))

    def test_customers_and_projects_are_archived_not_deleted(self):
        _, customer_id, project = self._new_project()
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                self.assertRejected(conn, errors.RestrictViolation, "DELETE FROM projects WHERE id = %s", (project["id"],))
                self.assertRejected(conn, errors.RestrictViolation, "DELETE FROM customers WHERE id = %s", (customer_id,))
        with self.db.transaction() as cur:
            cur.execute("UPDATE projects SET archived_at = now() WHERE id = %s RETURNING archived_at, updated_at, created_at",
                        (project["id"],))
            row = cur.fetchone()
        self.assertIsNotNone(row["archived_at"])

    # --- 프로젝트 변경 + 이력 원자성 ------------------------------------------

    def test_change_commits_project_and_history_together(self):
        user_id, _, project = self._new_project()
        with self.db.transaction() as cur:
            change_project(cur, project["id"], actor_id=user_id, stage="development", state="hold",
                           due_date="2026-12-01", reason="바이어 예산 재검토")
        current, history = self._project(project["id"])
        self.assertEqual((current["stage"], current["state"], current["due_date"].isoformat()),
                         ("development", "hold", "2026-12-01"))
        self.assertEqual([(h["field"], h["old_value"], h["new_value"]) for h in history],
                         [("stage", "proposal", "development"), ("state", "active", "hold"),
                          ("due_date", None, "2026-12-01")])
        self.assertTrue(all(h["created_by"] == user_id for h in history))
        # 홀드 → 진행 복귀, 납기일 해제(new_value NULL)
        with self.db.transaction() as cur:
            change_project(cur, project["id"], actor_id=user_id, state="active", due_date=None)
        current, history = self._project(project["id"])
        self.assertEqual((current["state"], current["due_date"]), ("active", None))
        self.assertEqual((history[-1]["field"], history[-1]["old_value"], history[-1]["new_value"]),
                         ("due_date", "2026-12-01", None))

    def test_exception_rolls_back_project_and_history(self):
        user_id, _, project = self._new_project()
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as cur:
                change_project(cur, project["id"], actor_id=user_id, stage="order")
                raise RuntimeError("저장 도중 실패")
        current, history = self._project(project["id"])
        self.assertEqual(current["stage"], "proposal")
        self.assertEqual(history, [])

    def test_failed_history_insert_rolls_back_project_update(self):
        user_id, _, project = self._new_project()
        with self.assertRaises(errors.ForeignKeyViolation):
            with self.db.transaction() as cur:
                change_project(cur, project["id"], actor_id=-1, stage="order")   # 없는 작성자 → 이력 INSERT 실패
        current, history = self._project(project["id"])
        self.assertEqual((current["stage"], history), ("proposal", []))

    def test_update_without_history_is_rejected_at_commit(self):
        _, _, project = self._new_project()
        with self.assertRaises(errors.IntegrityConstraintViolation):
            with self.db.transaction() as cur:
                cur.execute("UPDATE projects SET state = 'drop' WHERE id = %s", (project["id"],))
        current, history = self._project(project["id"])
        self.assertEqual((current["state"], history), ("active", []))

    def test_past_history_cannot_authorize_new_change(self):
        user_id, _, project = self._new_project()
        with self.db.transaction() as cur:     # 과거 트랜잭션 1: proposal → development
            change_project(cur, project["id"], actor_id=user_id, stage="development")
        with self.db.transaction() as cur:     # 과거 트랜잭션 2: development → proposal
            change_project(cur, project["id"], actor_id=user_id, stage="proposal")
        # 새 트랜잭션에서 이력 없이 proposal → development: 같은 전후 값의 과거 이력(트랜잭션 1)이 있어도 거부
        with self.assertRaises(errors.IntegrityConstraintViolation):
            with self.db.transaction() as cur:
                cur.execute("UPDATE projects SET stage = 'development' WHERE id = %s", (project["id"],))
        current, history = self._project(project["id"])
        self.assertEqual((current["stage"], len(history)), ("proposal", 2))

    def test_history_xact_id_is_set_by_server(self):
        user_id, _, project = self._new_project()
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                row = conn.execute(
                    """INSERT INTO project_history (project_id, field, old_value, new_value, created_by, xact_id)
                       VALUES (%s, 'stage', 'proposal', 'development', %s, '1'::xid8)
                       RETURNING xact_id = pg_current_xact_id() AS same_tx""", (project["id"], user_id)).fetchone()
                self.assertTrue(row["same_tx"])   # 클라이언트가 보낸 값 대신 현재 트랜잭션 id

    def test_multiple_changes_in_one_transaction(self):
        user_id, _, project = self._new_project(due_date="2026-11-30")
        with self.db.transaction() as cur:
            change_project(cur, project["id"], actor_id=user_id, stage="development")
            change_project(cur, project["id"], actor_id=user_id, stage="order", due_date="2026-12-31")
            change_project(cur, project["id"], actor_id=user_id, state="hold", reason="원료 수급 지연")
            change_project(cur, project["id"], actor_id=user_id, state="active")
        current, history = self._project(project["id"])
        self.assertEqual((current["stage"], current["state"], current["due_date"].isoformat()),
                         ("order", "active", "2026-12-31"))
        self.assertEqual([(h["field"], h["old_value"], h["new_value"]) for h in history],
                         [("stage", "proposal", "development"), ("stage", "development", "order"),
                          ("due_date", "2026-11-30", "2026-12-31"), ("state", "active", "hold"),
                          ("state", "hold", "active")])

    # --- 비밀번호 호환성 -------------------------------------------------------

    def test_password_hash_roundtrip_with_werkzeug(self):
        from werkzeug.security import check_password_hash, generate_password_hash
        email = f"pw-{self._run_id()}@cosmoa.test"
        with self.db.transaction() as cur:
            cur.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, %s, %s, %s)",
                        (email, "비밀번호 확인", generate_password_hash("Valid-Pass-123"), self.system_id))
        with self.db.transaction() as cur:
            cur.execute("SELECT password_hash FROM users WHERE email = %s", (email,))
            stored = cur.fetchone()["password_hash"]
        self.assertTrue(check_password_hash(stored, "Valid-Pass-123"))
        self.assertFalse(check_password_hash(stored, "Wrong-Pass-123"))

    # --- 이력 수정·삭제 차단 --------------------------------------------------

    def test_history_is_append_only(self):
        user_id, _, project = self._new_project()
        with self.db.transaction() as cur:
            change_project(cur, project["id"], actor_id=user_id, stage="development")
        with self.db.connection() as conn:
            with conn.transaction(force_rollback=True):
                self.assertRejected(conn, errors.RestrictViolation,
                                    "UPDATE project_history SET reason = 'x' WHERE project_id = %s", (project["id"],))
                self.assertRejected(conn, errors.RestrictViolation,
                                    "DELETE FROM project_history WHERE project_id = %s", (project["id"],))
                self.assertRejected(conn, errors.RestrictViolation, "TRUNCATE project_history")
        _, history = self._project(project["id"])
        self.assertEqual(len(history), 1)

    # --- 마이그레이션 재실행 ---------------------------------------------------

    def test_migrations_are_not_reapplied(self):
        result = db_admin.migrate("test")
        self.assertEqual(result["applied_now"], [])
        self.assertEqual(result["before"]["pending"], [])


if __name__ == "__main__":
    unittest.main()
