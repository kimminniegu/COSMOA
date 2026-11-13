"""0006_regulatory_notes 되돌리기의 동시 저장 보호 — **일회용 로컬 PostgreSQL 전용** (공유 Neon 에서는 실행하지 않음).

    COSMOA_DISPOSABLE_PG_URL=postgresql://<관리자>@127.0.0.1:<port>/postgres \
    python -m unittest discover -s src/common/tests -p "test_regulatory_notes_rollback_concurrency.py"

- 이 테스트는 표를 실제로 DROP 하므로 공유 test DB 에서 돌리면 안 된다. 그래서 TEST_DATABASE_URL 을 쓰지 않고,
  COSMOA_DISPOSABLE_PG_URL 이 **루프백 주소(127.0.0.1·localhost·::1)이고 Neon endpoint 가 아닐 때만** 실행한다. 없으면 건너뛴다.
- 테스트마다 새 DB(cosmoa_rbtest_<무작위>)를 만들고 0001~0006 을 적용한 뒤, 끝나면 DB 를 지운다 (DROP DATABASE … WITH (FORCE)).
  cosmoa_app 공통 역할이 없으면 0004 의 확인 조건대로 만든다 (그 서버 전체 객체 — 일회용 서버에서만).
- 두(세) 연결을 실제로 동시에 열어 순서를 만든다. 대기 여부는 pg_stat_activity 의 wait_event_type='Lock' 으로 확인한다.
- 보호가 없던 순서(확인 → 다른 저장 커밋 → DROP)의 데이터 손실 재현도 남긴다 (현재 파일에서 잠금 두 줄을 뺀 SQL).
"""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from urllib.parse import urlsplit
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402
from src.common.db import neon_endpoint_id  # noqa: E402

URL = (os.getenv("COSMOA_DISPOSABLE_PG_URL") or "").strip()
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MIGRATION = "0006_regulatory_notes"
ROLLBACK_SQL = (db_admin.MIGRATIONS_DIR / f"{MIGRATION}.rollback.sql").read_text(encoding="utf-8")
LOCK_LINES = ("SET LOCAL lock_timeout = '5s';", "LOCK TABLE version_links, regulatory_notes IN ACCESS EXCLUSIVE MODE;")
GUARD_END = ROLLBACK_SQL.index("$$;") + 3


def _disposable_ok() -> bool:
    if not URL or db_admin.is_production_env():
        return False
    parts = urlsplit(URL)
    return parts.scheme in ("postgres", "postgresql") and parts.hostname in LOOPBACK and neon_endpoint_id(URL) is None


def _with_db(url: str, db: str) -> str:
    return urlsplit(url)._replace(path="/" + db).geturl()


def _connect(url: str, **kw) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10, **kw)


@unittest.skipUnless(_disposable_ok(), "COSMOA_DISPOSABLE_PG_URL(루프백 일회용 PostgreSQL) 없음 — 되돌리기 동시성 테스트 생략")
class RollbackConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with _connect(URL, autocommit=True) as c:
            if c.execute("SELECT current_setting('neon.endpoint_id', true) AS e").fetchone()["e"]:
                raise RuntimeError("Neon 서버에서는 실행하지 않습니다")
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (db_admin.APP_GROUP,)).fetchone() is None:
                ident = sql.Identifier(db_admin.APP_GROUP)
                c.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(ident))
                c.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(ident, sql.Literal(db_admin.APP_GROUP_MARK)))

    def setUp(self):
        self.db = f"cosmoa_rbtest_{uuid.uuid4().hex[:10]}"
        with _connect(URL, autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.db)))
        self.url = _with_db(URL, self.db)
        backend, migrations = db_admin._yoyo(self.url)
        try:
            with backend.lock():
                backend.apply_migrations(backend.to_apply(migrations))
        finally:
            backend.connection.close()
        self.conns = []
        admin = self.conn()
        with admin.transaction():
            self.uid = admin.execute("INSERT INTO users (email, name, password_hash) VALUES (%s, '시스템', %s) RETURNING id",
                                     ("system@cosmoa.test", generate_password_hash("rollback-test-pw-1"))).fetchone()["id"]
            cust = admin.execute("INSERT INTO customers (name, created_by) VALUES ('동시성 고객사', %s) RETURNING id", (self.uid,)).fetchone()["id"]
            self.pid = admin.execute("INSERT INTO projects (customer_id, name, created_by) VALUES (%s, '동시성 프로젝트', %s) RETURNING id",
                                     (cust, self.uid)).fetchone()["id"]

    def tearDown(self):
        for c in self.conns:
            try:
                c.close()
            except Exception:
                pass
        with _connect(URL, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.db)))

    # --- 도우미 ------------------------------------------------------------------

    def conn(self, **kw):
        c = _connect(self.url, **kw)
        self.conns.append(c)
        return c

    def insert_note(self, c, memo="동시 저장 메모"):
        return c.execute("INSERT INTO regulatory_notes (project_id, note_type, memo, created_by) VALUES (%s, 'memo_only', %s, %s) RETURNING id",
                         (self.pid, memo, self.uid)).fetchone()["id"]

    def state(self):
        with _connect(self.url) as c:
            st = db_admin.read_state(c)
            has_col = c.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'version_links' "
                                "AND column_name = 'source_note_id'").fetchone() is not None
            notes = c.execute("SELECT count(*) AS n FROM regulatory_notes").fetchone()["n"] if "regulatory_notes" in st["tables"] else None
        return {"applied": MIGRATION in st["applied"], "table": "regulatory_notes" in st["tables"], "column": has_col,
                "notes": notes, "problems": st["problems"]}

    def wait_for_lock_waiter(self, timeout=10.0):
        """다른 연결이 잠금을 기다리는 상태가 될 때까지 (pg_stat_activity)."""
        with _connect(self.url, autocommit=True) as c:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                n = c.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname = current_database() "
                              "AND wait_event_type = 'Lock'").fetchone()["n"]
                if n:
                    return n
                time.sleep(0.05)
        self.fail("잠금 대기 상태가 나타나지 않았습니다")

    def run_in_thread(self, func):
        box = {}

        def target():
            try:
                box["result"] = func()
            except BaseException as e:   # noqa: BLE001 — 결과를 본 스레드에서 확인
                box["error"] = e
        t = threading.Thread(target=target, daemon=True)
        t.start()
        return t, box

    def rollback_via_yoyo(self):
        return db_admin._yoyo_rollback_last(self.url)   # 실제 되돌리기 경로 (rollback_last 가 쓰는 함수)

    # --- 재현: 잠금 없이 확인 → 다른 저장 커밋 → DROP --------------------------------------

    def test_reproduction_without_lock_loses_committed_note(self):
        unsafe = ROLLBACK_SQL
        for line in LOCK_LINES:
            self.assertIn(line, unsafe)
            unsafe = unsafe.replace(line, "")
        guard_end = unsafe.index("$$;") + 3
        a, b = self.conn(), self.conn()
        a.execute(unsafe[:guard_end])                  # A: 확인 통과 (아직 메모 없음)
        note = self.insert_note(b)                     # B: 그 사이 메모 저장·커밋 — 사용자는 저장 성공을 받음
        b.commit()
        a.execute(unsafe[guard_end:])                  # A: DROP
        a.commit()
        st = self.state()
        self.assertFalse(st["table"])                  # 재현: 커밋된 메모(note)가 표와 함께 사라짐
        self.assertIsInstance(note, int)

    # --- 수정 후 -------------------------------------------------------------------

    def test_uncommitted_save_first_then_commit_aborts_rollback(self):
        b = self.conn()
        note = self.insert_note(b)                     # B: 먼저 저장 시작 (커밋 전)
        t, box = self.run_in_thread(self.rollback_via_yoyo)
        self.wait_for_lock_waiter()                    # 되돌리기는 LOCK 에서 대기
        self.assertTrue(t.is_alive())
        b.commit()                                     # B 커밋 → 되돌리기 확인에서 발견
        t.join(30)
        self.assertIn("error", box)
        self.assertIn("메모가 있어 되돌리지 않습니다", str(box["error"]))
        st = self.state()
        self.assertEqual((st["applied"], st["table"], st["column"], st["notes"], st["problems"]), (True, True, True, 1, []))
        with _connect(self.url) as c:
            self.assertIsNotNone(c.execute("SELECT id FROM regulatory_notes WHERE id = %s", (note,)).fetchone())

    def test_uncommitted_save_first_then_rollback_lets_rollback_proceed(self):
        b = self.conn()
        self.insert_note(b)
        t, box = self.run_in_thread(self.rollback_via_yoyo)
        self.wait_for_lock_waiter()
        b.rollback()                                   # B 취소 → 되돌리기 진행
        t.join(30)
        self.assertEqual(box.get("result"), [MIGRATION], box.get("error"))
        st = self.state()
        self.assertEqual((st["applied"], st["table"], st["column"], st["problems"]), (False, False, False, []))

    def test_save_after_rollback_holds_lock_fails_instead_of_vanishing(self):
        a = self.conn()
        a.execute(ROLLBACK_SQL[:GUARD_END])            # A: 잠금 → 확인 통과 (실제 파일 순서), 아직 DROP 전
        b = self.conn()
        t, box = self.run_in_thread(lambda: (self.insert_note(b), b.commit()))
        self.wait_for_lock_waiter()                    # B 는 잠금 대기 (확인과 DROP 사이에 끼어들지 못함)
        self.assertTrue(t.is_alive())
        a.execute(ROLLBACK_SQL[GUARD_END:])
        a.commit()
        t.join(30)
        self.assertIn("error", box)                    # B 는 성공을 받지 못함 (표가 없어져 오류)
        self.assertIsInstance(box["error"], psycopg.Error)
        st = self.state()
        self.assertFalse(st["table"])

    def test_link_save_racing_rollback_also_blocked(self):
        """메모·반영 기록이 함께 저장되는 트랜잭션이 먼저 커밋되면 되돌리기가 중단되고 둘 다 남는다."""
        b = self.conn()
        note = self.insert_note(b)
        v = b.execute("INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) "
                      "VALUES (%s, 'requisition', 1, '{\"context\":{},\"inputs\":{},\"outputs\":{},\"meta\":{}}', %s) RETURNING id",
                      (self.pid, self.uid)).fetchone()["id"]
        b.execute("INSERT INTO version_links (project_id, version_id, tab, source_tab, source_note_id, applied_values, created_by) "
                  "VALUES (%s, %s, 'requisition', 'regulatory', %s, '{\"t\":1}', %s)", (self.pid, v, note, self.uid))
        t, box = self.run_in_thread(self.rollback_via_yoyo)
        self.wait_for_lock_waiter()
        b.commit()
        t.join(30)
        self.assertIn("반영 기록", str(box.get("error")))
        st = self.state()
        self.assertEqual((st["applied"], st["table"], st["column"], st["notes"]), (True, True, True, 1))

    def test_lock_timeout_changes_nothing(self):
        b = self.conn()
        note = self.insert_note(b)                     # 오래 걸리는 저장 (5초 넘게 커밋 안 함)
        started = time.monotonic()
        with self.assertRaises(RuntimeError) as ctx:
            self.rollback_via_yoyo()
        self.assertGreaterEqual(time.monotonic() - started, 4.5)
        self.assertIn("lock timeout", str(ctx.exception).lower())
        b.commit()                                     # 저장은 그대로 성공
        st = self.state()
        self.assertEqual((st["applied"], st["table"], st["column"], st["notes"]), (True, True, True, 1))
        self.assertIsInstance(note, int)

    def test_rollback_then_reapply_on_empty_db(self):
        self.assertEqual(self.rollback_via_yoyo(), [MIGRATION])
        backend, migrations = db_admin._yoyo(self.url)
        try:
            with backend.lock():
                todo = backend.to_apply(migrations)
                backend.apply_migrations(todo)
                self.assertEqual([m.id for m in todo], [MIGRATION])
        finally:
            backend.connection.close()
        st = self.state()
        self.assertEqual((st["applied"], st["table"], st["column"], st["problems"]), (True, True, True, []))


if __name__ == "__main__":
    unittest.main()
