"""규제 확인사항 메모 DB 구조 통합 테스트 (0006_regulatory_notes) — 테스트 DB 에서만 실행합니다.

    python -m unittest discover -s src/common/tests -p "test_regulatory_notes_integration.py"

- 관리 역할(TEST_DATABASE_URL)로 제약·트리거·반영 출처 FK 를, 앱 역할(TEST_APP_DATABASE_URL)로 권한을 확인합니다.
  각 변수가 없으면 해당 묶음을 건너뛰고, 테스트 DB 식별에 실패하면 멈춥니다. 0006 까지 적용되어 있어야 합니다.
- **모든 쓰기는 항상 롤백하는 트랜잭션 안에서 합니다** — 고객사·프로젝트·저장본·메모·반영 기록이 test DB 에 남지 않습니다.
- 근거: src/02_regulatory/regulatory.md 17장, docs/data_contract.md 1-5, docs/db_rules.md 5-1·8-9.
  삭제 주체(작성자만 등)는 미정이라 DB 에 없고 서버(R3)가 확인한다 — 여기서 검사하지 않습니다.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import db_admin  # noqa: E402

db_admin._load_env()
HAS_TEST_DB = bool((os.getenv("TEST_DATABASE_URL") or "").strip())
HAS_APP_DB = HAS_TEST_DB and bool((os.getenv(db_admin.TEST_APP_URL_VAR) or "").strip())
MIGRATION = "0006_regulatory_notes"
NOW = datetime(2026, 11, 13, 5, 2, 11, tzinfo=timezone.utc)

SOURCES = {"mfds_ingredients": {"snapshot_id": "e36457e0445f4c55", "run_id": 1, "collected_at": "2026-11-09T09:15:47+00:00"},
           "mfds_restriction": {"snapshot_id": "a74e63a3d8a6f149", "run_id": 1, "collected_at": "2026-11-09T08:55:53+00:00"}}
ENTRY = {"country": "아세안", "regulate_type": "한도", "limit_condition": "* 【Restrictions】 …", "record_id": 27310, "page_no": 274}


def market_snapshot(entries=(ENTRY,)):
    return {"selection": {"source": "mfds_ingredients", "kr_name": "페녹시에탄올"}, "market": {"code": "ASEAN"},
            "entries": list(entries), "sources": SOURCES, "notices": ["허용·적합 판정이 아니에요."]}


def search_snapshot():
    return {"search": {"query": "Bakuchiol", "counts": {"mfds_ingredients": 0, "mfds_restriction": 0}}, "sources": SOURCES}


# 유형별 정상 행 (regulatory.md 17-5 유형표). created_by/project_id 는 삽입할 때 채운다.
MARKET = dict(note_type="market_lookup", origin="direct", ingredient_name="페녹시에탄올", ingredient_name_source="mfds_ingredients",
              ingredient_eng_name="Phenoxyethanol", ingredient_cas="122-99-6", lookup_market="ASEAN", lookup_status="found",
              lookup_source="식약처 화장품 사용제한 원료정보 (수집 DB)", looked_up_at=NOW,
              regulation_text="[아세안 · 한도] * 【Restrictions】 …", lookup_snapshot=market_snapshot(),
              target_country="VN", target_region=None, memo="베트남 바이어 확인 요청")
NO_RECORD = dict(MARKET, ingredient_name="레티놀", ingredient_eng_name="Retinol", ingredient_cas=None, lookup_market="KR",
                 lookup_status="no_market_record", regulation_text=None, lookup_snapshot=market_snapshot(()),
                 target_country="KR", memo=None)
SEARCH = dict(note_type="search_no_result", origin="direct", lookup_source="식약처 화장품 원료성분정보 · 사용제한 원료정보 (수집 DB)",
              looked_up_at=NOW, lookup_snapshot=search_snapshot(), target_country="US", memo="검색 결과 없음 — 별도 확인")
MEMO = dict(note_type="memo_only", ingredient_name="Bakuchiol (바이어 지정 원료)", ingredient_name_source="user",
            target_country="TW", memo="대만 바이어 문의 — R&D 확인 필요")

LOOKUP_FIELDS = ("note_type", "origin", "ingredient_name", "ingredient_name_source", "ingredient_eng_name", "ingredient_cas",
                 "lookup_market", "lookup_status", "lookup_source", "looked_up_at", "regulation_text", "lookup_snapshot")


def insert_note(conn, project_id, user_id, fields):
    cols = dict(fields, project_id=project_id, created_by=user_id)
    if isinstance(cols.get("lookup_snapshot"), (dict, list)):
        cols["lookup_snapshot"] = Jsonb(cols["lookup_snapshot"])
    names = list(cols)
    query = sql.SQL("INSERT INTO regulatory_notes ({}) VALUES ({}) RETURNING *").format(
        sql.SQL(", ").join(map(sql.Identifier, names)), sql.SQL(", ").join(sql.Placeholder() * len(names)))
    return conn.execute(query, [cols[n] for n in names]).fetchone()


def make_project(conn, user_id, label="규제 메모"):
    tag = uuid.uuid4().hex[:8]
    customer = conn.execute("INSERT INTO customers (name, created_by) VALUES (%s, %s) RETURNING id",
                            (f"{label} 고객사 {tag}", user_id)).fetchone()["id"]
    return conn.execute("INSERT INTO projects (customer_id, name, created_by) VALUES (%s, %s, %s) RETURNING id",
                        (customer, f"{label} 프로젝트 {tag}", user_id)).fetchone()["id"]


def make_version(conn, project_id, user_id, tab="requisition"):
    return conn.execute(
        "INSERT INTO tab_versions (project_id, tab, schema_version, payload, created_by) VALUES (%s, %s, 1, %s, %s) RETURNING id",
        (project_id, tab, Jsonb({"context": {}, "inputs": {}, "outputs": {}, "meta": {}}), user_id)).fetchone()["id"]


def insert_link(conn, project_id, version_id, user_id, *, source_version_id=None, source_note_id=None, source_tab="regulatory"):
    return conn.execute(
        """INSERT INTO version_links (project_id, version_id, tab, source_tab, source_version_id, source_note_id, applied_values, created_by)
           VALUES (%s, %s, 'requisition', %s, %s, %s, %s, %s) RETURNING id""",
        (project_id, version_id, source_tab, source_version_id, source_note_id,
         Jsonb({"target_field": "ingredients.other_notes", "inserted_text": "…"}), user_id)).fetchone()["id"]


class NotesDbMixin:
    def assertSqlState(self, conn, state, func, *args):
        """func 이 sqlstate 오류를 내는지 (저장점 안에서 실행 — 바깥 트랜잭션은 유지)."""
        with self.assertRaises(psycopg.Error) as ctx:
            with conn.transaction():
                func(*args)
        self.assertEqual(ctx.exception.sqlstate, state, f"{ctx.exception.sqlstate}: {ctx.exception}")


@unittest.skipUnless(HAS_TEST_DB, "TEST_DATABASE_URL 없음 — 규제 메모 DB 테스트 생략")
class RegulatoryNotesSchemaTest(NotesDbMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn, _ = db_admin.open_verified_test_db()
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"] or MIGRATION not in state["applied"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            cls.system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]

    def setUp(self):
        self.conn, _ = db_admin.open_verified_test_db()
        self.tx = self.conn.transaction(force_rollback=True)   # 테스트마다 전부 롤백
        self.tx.__enter__()
        self.uid = self.system_id
        self.pid = make_project(self.conn, self.uid)

    def tearDown(self):
        self.tx.__exit__(None, None, None)
        self.conn.close()

    def note(self, fields, project_id=None):
        return insert_note(self.conn, project_id or self.pid, self.uid, fields)

    def rejects(self, fields, state="23514"):
        self.assertSqlState(self.conn, state, self.note, fields)

    # --- 구조 -----------------------------------------------------------------

    def test_version_links_keeps_existing_columns_and_adds_note_source(self):
        cols = {r["column_name"]: r["is_nullable"] for r in self.conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'version_links'")}
        self.assertEqual(cols["source_version_id"], "YES")          # 메모 출처 행은 NULL
        self.assertEqual(cols["source_note_id"], "YES")
        for name in ("project_id", "version_id", "tab", "source_tab", "applied_values", "created_by", "created_at"):
            self.assertEqual(cols[name], "NO", name)
        # 저장본 출처 기존 행은 그대로 정확히 하나의 출처(저장본)를 가진다
        bad = self.conn.execute("SELECT count(*) AS n FROM version_links WHERE num_nonnulls(source_version_id, source_note_id) <> 1").fetchone()
        self.assertEqual(bad["n"], 0)
        fk = self.conn.execute(
            """SELECT confdeltype, pg_get_constraintdef(oid) AS d FROM pg_constraint
               WHERE conrelid = 'version_links'::regclass AND conname = 'version_links_note_fk'""").fetchone()
        self.assertEqual(fk["confdeltype"], "r")                        # ON DELETE RESTRICT
        self.assertIn("(source_note_id, project_id) REFERENCES regulatory_notes(id, project_id)", fk["d"])

    # --- 기록 유형 3가지 --------------------------------------------------------

    def test_three_note_types_are_stored(self):
        for label, fields in (("market found", MARKET), ("market no_market_record", NO_RECORD),
                              ("not_linked", dict(NO_RECORD, lookup_status="not_linked")),
                              ("search_no_result", SEARCH), ("search + user name", dict(SEARCH, ingredient_name="바쿠치올", ingredient_name_source="user")),
                              ("memo_only", MEMO), ("memo_only no name/target", dict(MEMO, ingredient_name=None, ingredient_name_source=None, target_country=None)),
                              ("region target", dict(MARKET, target_country=None, target_region="ASEAN")),
                              ("no target", dict(MARKET, target_country=None)),
                              ("restriction candidate", dict(MARKET, ingredient_name_source="mfds_restriction")),
                              ("file batch", dict(MARKET, origin="file_batch")),
                              ("memo with newline·tab", dict(MEMO, memo="첫 줄\r\n둘째 줄\t탭")),
                              ("memo 5000", dict(MEMO, memo="가" * 5000))):
            with self.subTest(label=label):
                row = self.note(fields)
                self.assertEqual((row["revision"], row["updated_by"], row["created_by"]), (1, self.uid, self.uid))
                self.assertEqual(row["updated_at"], row["created_at"])

    def test_wrong_field_combinations_are_rejected_including_nulls(self):
        cases = {
            # market_lookup 필수값 누락 (NULL 로 CHECK 를 통과하지 않아야 함)
            "market: lookup_market NULL": dict(MARKET, lookup_market=None),
            "market: lookup_status NULL": dict(MARKET, lookup_status=None, regulation_text=None),
            "market: origin NULL": dict(MARKET, origin=None),
            "market: 성분명·출처 NULL": dict(MARKET, ingredient_name=None, ingredient_name_source=None),
            "market: 이름 출처 user": dict(MARKET, ingredient_name_source="user"),
            "market: snapshot NULL": dict(MARKET, lookup_snapshot=None),
            "market: lookup_source NULL": dict(MARKET, lookup_source=None),
            "market: looked_up_at NULL": dict(MARKET, looked_up_at=None),
            "market: found 인데 regulation_text NULL": dict(MARKET, regulation_text=None),
            "market: no_market_record 인데 regulation_text": dict(NO_RECORD, regulation_text="x"),
            "market: no_market_record 인데 행 사본": dict(NO_RECORD, lookup_snapshot=market_snapshot()),
            "market: found 인데 행 0개": dict(MARKET, lookup_snapshot=market_snapshot(())),
            "market: snapshot sources 없음": dict(MARKET, lookup_snapshot={k: v for k, v in market_snapshot().items() if k != "sources"}),
            "market: entries 가 배열 아님": dict(MARKET, lookup_snapshot=dict(market_snapshot(), entries={"0": ENTRY})),
            "market: 지원 외 시장": dict(MARKET, lookup_market="TW"),
            "market: 알 수 없는 상태": dict(MARKET, lookup_status="search_no_result", regulation_text=None),
            "market: snapshot 이 배열": dict(MARKET, lookup_snapshot=[ENTRY]),
            # search_no_result: 시장별 조회가 아니므로 시장·상태·행 없음, 근거 3종 필수
            "search: lookup_market 있음": dict(SEARCH, lookup_market="EU"),
            "search: lookup_status 있음": dict(SEARCH, lookup_status="not_linked"),
            "search: regulation_text 있음": dict(SEARCH, regulation_text="x"),
            "search: origin NULL": dict(SEARCH, origin=None),
            "search: snapshot NULL": dict(SEARCH, lookup_snapshot=None),
            "search: lookup_source NULL": dict(SEARCH, lookup_source=None),
            "search: looked_up_at NULL": dict(SEARCH, looked_up_at=None),
            "search: snapshot 에 entries": dict(SEARCH, lookup_snapshot=dict(search_snapshot(), entries=[])),
            "search: snapshot search 없음": dict(SEARCH, lookup_snapshot={"sources": SOURCES}),
            "search: 식약처 이름 출처": dict(SEARCH, ingredient_name="x", ingredient_name_source="mfds_ingredients"),
            "search: 영문명": dict(SEARCH, ingredient_eng_name="x"),
            "search: CAS": dict(SEARCH, ingredient_cas="50-00-0"),
            # memo_only: 조회 근거 전부 NULL, 메모 필수
            "memo: memo NULL": dict(MEMO, memo=None),
            "memo: 공백만": dict(MEMO, memo="   "),
            "memo: 줄바꿈·탭만": dict(MEMO, memo="\r\n\t"),
            "memo: origin 있음": dict(MEMO, origin="direct"),
            "memo: snapshot 있음": dict(MEMO, lookup_snapshot=search_snapshot()),
            "memo: lookup_source 있음": dict(MEMO, lookup_source="x"),
            "memo: looked_up_at 있음": dict(MEMO, looked_up_at=NOW),
            "memo: lookup_market 있음": dict(MEMO, lookup_market="KR"),
            "memo: lookup_status 있음": dict(MEMO, lookup_status="found"),
            "memo: 이름 없이 출처": dict(MEMO, ingredient_name=None),
            "memo: 출처 없이 이름": dict(MEMO, ingredient_name_source=None),
            "memo: 식약처 이름 출처": dict(MEMO, ingredient_name_source="mfds_restriction"),
            # 공통 값 규칙
            "국가·권역 동시": dict(MARKET, target_country="VN", target_region="ASEAN"),
            "국가 소문자": dict(MEMO, target_country="tw"),
            "국가 3글자": dict(MEMO, target_country="TWN"),
            "권역 목록 밖": dict(MEMO, target_country=None, target_region="APAC"),
            "메모 5001자": dict(MEMO, memo="가" * 5001),
            "메모 제어 문자": dict(MEMO, memo="벨\x07소리"),
            "성분명 201자": dict(MEMO, ingredient_name="가" * 201),
            "성분명 줄바꿈": dict(MEMO, ingredient_name="가\n나"),
            "성분명 공백만": dict(MEMO, ingredient_name="  "),
            "출처 문구 공백만": dict(SEARCH, lookup_source="  "),
            "snapshot 32 KiB 초과": dict(SEARCH, lookup_snapshot=dict(search_snapshot(), pad="x" * 33000)),
            "알 수 없는 유형": dict(MEMO, note_type="regulation_ok"),
            "알 수 없는 호출 경로": dict(SEARCH, origin="chatbot"),
        }
        for label, fields in cases.items():
            with self.subTest(label=label):
                self.rejects(fields)
        with self.subTest(label="유형 NULL"):
            self.rejects(dict(MEMO, note_type=None), state="23502")

    # --- 트리거: revision·시각·수정 불가 열 ------------------------------------------

    def test_insert_ignores_client_revision_and_stamps(self):
        other = self.conn.execute("INSERT INTO users (email, name, password_hash, created_by) VALUES (%s, '다른 사용자', %s, %s) RETURNING id",
                                  (f"notes-{uuid.uuid4().hex[:8]}@cosmoa.test", generate_password_hash("notes-test-pw-1"), self.uid)).fetchone()["id"]
        row = self.note(dict(MEMO, revision=7, updated_by=other, created_at=datetime(2000, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual((row["revision"], row["updated_by"]), (1, self.uid))
        self.assertGreater(row["created_at"].year, 2000)

    def test_update_bumps_revision_and_protects_lookup_basis(self):
        row = self.note(MARKET)
        upd = self.conn.execute("UPDATE regulatory_notes SET memo = %s, target_country = NULL, target_region = 'ASEAN', revision = 99 "
                                "WHERE id = %s RETURNING revision, memo, target_region", ("수정 메모", row["id"])).fetchone()
        self.assertEqual(upd, {"revision": 2, "memo": "수정 메모", "target_region": "ASEAN"})
        for column, value in (("lookup_snapshot", Jsonb({"x": 1})), ("regulation_text", "바꾼 원문"), ("lookup_status", "not_linked"),
                              ("lookup_market", "EU"), ("lookup_source", "x"), ("looked_up_at", datetime(2026, 1, 1, tzinfo=timezone.utc)), ("note_type", "memo_only"),
                              ("origin", "file_batch"), ("ingredient_name", "다른 성분"), ("ingredient_cas", "1-1-1"),
                              ("created_at", NOW), ("project_id", make_project(self.conn, self.uid, "다른"))):
            with self.subTest(column=column):
                self.assertSqlState(self.conn, "23000", self.conn.execute,
                                    sql.SQL("UPDATE regulatory_notes SET {} = %s WHERE id = %s").format(sql.Identifier(column)),
                                    (value, row["id"]))
        self.assertEqual(self.conn.execute("SELECT revision FROM regulatory_notes WHERE id = %s", (row["id"],)).fetchone()["revision"], 2)
        # 대상 국가·권역 동시 지정은 수정에서도 거부
        self.assertSqlState(self.conn, "23514", self.conn.execute,
                            "UPDATE regulatory_notes SET target_country = 'VN' WHERE id = %s", (row["id"],))
        # memo_only 의 메모를 비우면 거부
        memo_row = self.note(MEMO)
        self.assertSqlState(self.conn, "23514", self.conn.execute,
                            "UPDATE regulatory_notes SET memo = NULL WHERE id = %s", (memo_row["id"],))

    # --- 반영 출처 (version_links) ---------------------------------------------------

    def test_links_note_source_same_project_and_exactly_one_source(self):
        note = self.note(MARKET)
        margin = make_version(self.conn, self.pid, self.uid, "margin")
        version = make_version(self.conn, self.pid, self.uid)
        insert_link(self.conn, self.pid, version, self.uid, source_note_id=note["id"])                       # 메모 출처
        insert_link(self.conn, self.pid, version, self.uid, source_version_id=margin, source_tab="margin")   # 기존 저장본 출처
        other_pid = make_project(self.conn, self.uid, "다른")
        other_note = self.note(MEMO, project_id=other_pid)
        cases = (
            ("다른 프로젝트 메모", "23503", dict(source_note_id=other_note["id"])),
            ("없는 메모", "23503", dict(source_note_id=-1)),
            ("출처 0개", "23514", dict()),
            ("출처 2개", "23514", dict(source_note_id=note["id"], source_version_id=margin, source_tab="margin")),
            ("메모 출처인데 탭이 regulatory 아님", "23514", dict(source_note_id=note["id"], source_tab="margin")),
            ("같은 메모 중복", "23505", dict(source_note_id=note["id"])),
        )
        for label, state, kwargs in cases:
            with self.subTest(label=label):
                self.assertSqlState(self.conn, state, lambda: insert_link(self.conn, self.pid, version, self.uid, **kwargs))
        # 기존 같은 트랜잭션 규칙 유지: 이전 트랜잭션 저장본에 반영 기록을 붙이지 못함은 versions 통합 테스트가 확인 (여기서는 추가만 규칙)
        link = self.conn.execute("SELECT id FROM version_links WHERE source_note_id = %s", (note["id"],)).fetchone()["id"]
        for statement in ("UPDATE version_links SET applied_values = '{}'::jsonb WHERE id = %s", "DELETE FROM version_links WHERE id = %s"):
            with self.subTest(statement=statement):
                self.assertSqlState(self.conn, "23001", self.conn.execute, statement, (link,))

    def test_delete_unreferenced_note_and_restrict_referenced(self):
        free = self.note(MEMO)
        used = self.note(MARKET)
        version = make_version(self.conn, self.pid, self.uid)
        insert_link(self.conn, self.pid, version, self.uid, source_note_id=used["id"])
        self.assertEqual(self.conn.execute("DELETE FROM regulatory_notes WHERE id = %s", (free["id"],)).rowcount, 1)
        self.assertSqlState(self.conn, "23001", self.conn.execute, "DELETE FROM regulatory_notes WHERE id = %s", (used["id"],))   # ON DELETE RESTRICT = restrict_violation
        self.assertIsNotNone(self.conn.execute("SELECT id FROM regulatory_notes WHERE id = %s", (used["id"],)).fetchone())

    def test_rollback_guard_refuses_when_notes_exist(self):
        text = (db_admin.MIGRATIONS_DIR / f"{MIGRATION}.rollback.sql").read_text(encoding="utf-8")
        guard = text[text.index("DO $$"):text.index("$$;") + 3]
        self.note(MEMO)
        self.assertSqlState(self.conn, "P0001", self.conn.execute, guard)


@unittest.skipUnless(HAS_APP_DB, "TEST_DATABASE_URL·TEST_APP_DATABASE_URL 없음 — 규제 메모 앱 역할 테스트 생략")
class RegulatoryNotesAppRoleTest(NotesDbMixin, unittest.TestCase):
    """앱 역할로: 메모 조회·작성·메모/대상 수정·반영 전 삭제 가능, 조회 근거 수정 불가, REFERENCES 없이 메모 출처 링크 가능."""

    @classmethod
    def setUpClass(cls):
        conn, _ = db_admin.open_verified_test_db()
        with conn:
            state = db_admin.inspect_state(conn)
            if state["pending"] or state["problems"] or MIGRATION not in state["applied"]:
                raise RuntimeError(f"테스트 DB 마이그레이션 상태 이상: {state['pending']} {state['problems']}")
            cls.system_id = conn.execute("SELECT id FROM users WHERE created_by IS NULL").fetchone()["id"]
        _, cls.role, _ = db_admin.check_test_app_config()
        problems, _ = db_admin.app_role_report("test", cls.role)
        if problems:
            raise RuntimeError("앱 역할 확인 실패 (app-role check):\n  - " + "\n  - ".join(problems))

    def setUp(self):
        self.conn, _, _ = db_admin.open_verified_test_app_db()
        self.tx = self.conn.transaction(force_rollback=True)
        self.tx.__enter__()
        self.uid = self.system_id
        self.pid = make_project(self.conn, self.uid, "앱 역할 메모")

    def tearDown(self):
        self.tx.__exit__(None, None, None)
        self.conn.close()

    def test_privileges_match_contract(self):
        row = self.conn.execute(
            """SELECT current_user AS u,
                      has_table_privilege('regulatory_notes', 'SELECT') AS s, has_table_privilege('regulatory_notes', 'INSERT') AS i,
                      has_table_privilege('regulatory_notes', 'DELETE') AS d, has_table_privilege('regulatory_notes', 'UPDATE') AS u_all,
                      has_table_privilege('regulatory_notes', 'REFERENCES') AS r, has_table_privilege('regulatory_notes', 'TRUNCATE') AS t,
                      has_table_privilege('version_links', 'DELETE') AS vl_d, has_table_privilege('version_links', 'REFERENCES') AS vl_r,
                      has_table_privilege('tab_versions', 'DELETE') AS tv_d""").fetchone()
        self.assertEqual(row["u"], self.role)
        self.assertEqual((row["s"], row["i"], row["d"]), (True, True, True))
        self.assertEqual((row["u_all"], row["r"], row["t"], row["vl_d"], row["vl_r"], row["tv_d"]), (False,) * 6)
        updatable = {r["attname"] for r in self.conn.execute(
            """SELECT attname FROM pg_attribute WHERE attrelid = 'regulatory_notes'::regclass AND attnum > 0 AND NOT attisdropped
                 AND has_column_privilege('regulatory_notes', attnum, 'UPDATE')""")}
        self.assertEqual(updatable, db_admin.APP_UPDATE_COLUMNS["regulatory_notes"])

    def test_app_creates_edits_links_and_deletes(self):
        note = insert_note(self.conn, self.pid, self.uid, MARKET)
        row = self.conn.execute("SELECT id FROM regulatory_notes WHERE id = %s FOR UPDATE", (note["id"],)).fetchone()   # 잠금 가능 (서버 수정 순서)
        self.assertIsNotNone(row)
        upd = self.conn.execute(
            "UPDATE regulatory_notes SET memo = %s, target_country = 'TH', updated_by = %s WHERE id = %s AND revision = 1 RETURNING revision",
            ("앱 수정", self.uid, note["id"])).fetchone()
        self.assertEqual(upd["revision"], 2)
        stale = self.conn.execute("UPDATE regulatory_notes SET memo = 'x' WHERE id = %s AND revision = 1", (note["id"],))
        self.assertEqual(stale.rowcount, 0)                    # 기준 revision 이 다르면 0행 → 서버가 409
        # REFERENCES 권한 없이 메모 출처 링크 추가 (FK 검사는 DB 가 수행)
        version = make_version(self.conn, self.pid, self.uid)
        insert_link(self.conn, self.pid, version, self.uid, source_note_id=note["id"])
        self.assertSqlState(self.conn, "23001", self.conn.execute, "DELETE FROM regulatory_notes WHERE id = %s", (note["id"],))
        free = insert_note(self.conn, self.pid, self.uid, MEMO)
        self.assertEqual(self.conn.execute("DELETE FROM regulatory_notes WHERE id = %s", (free["id"],)).rowcount, 1)
        other = make_project(self.conn, self.uid, "앱 역할 다른")
        other_note = insert_note(self.conn, other, self.uid, MEMO)
        self.assertSqlState(self.conn, "23503", lambda: insert_link(self.conn, self.pid, version, self.uid, source_note_id=other_note["id"]))

    def test_app_cannot_change_lookup_basis_or_identity(self):
        note = insert_note(self.conn, self.pid, self.uid, MARKET)
        for column, value in (("lookup_snapshot", Jsonb({"x": 1})), ("regulation_text", "바꾼 원문"), ("lookup_status", "not_linked"),
                              ("lookup_market", "EU"), ("lookup_source", "x"), ("looked_up_at", NOW), ("note_type", "memo_only"),
                              ("origin", "file_batch"), ("ingredient_name", "다른 성분"), ("ingredient_name_source", "user"),
                              ("ingredient_eng_name", "x"), ("ingredient_cas", "1-1-1"), ("project_id", self.pid),
                              ("created_by", self.uid), ("created_at", NOW)):
            with self.subTest(column=column):
                self.assertSqlState(self.conn, "42501", self.conn.execute,
                                    sql.SQL("UPDATE regulatory_notes SET {} = %s WHERE id = %s").format(sql.Identifier(column)),
                                    (value, note["id"]))
        for statement in ("TRUNCATE regulatory_notes", "ALTER TABLE regulatory_notes DISABLE TRIGGER regulatory_notes_stamp",
                          "DELETE FROM version_links WHERE source_note_id IS NOT NULL", "DROP TABLE regulatory_notes"):
            with self.subTest(statement=statement):
                self.assertSqlState(self.conn, "42501", self.conn.execute, statement)


@unittest.skipUnless(HAS_APP_DB, "TEST_DATABASE_URL·TEST_APP_DATABASE_URL 없음 — app-role check 상태 판단 테스트 생략")
class AppRoleCheckStateTest(unittest.TestCase):
    """app-role check 본체(db_admin.app_role_problems — app_role_report·CLI 와 같은 함수)가 마이그레이션 적용 기록과
    실제 구조를 함께 보는지. 관리 역할 연결의 **항상 롤백하는 트랜잭션** 안에서 구조를 잠깐 바꿔 확인한다
    (DROP·REVOKE 등은 커밋되지 않음. 실행 중 해당 표에 잠금이 걸린다 — 공유 test DB 에서는 사용이 적을 때 실행)."""

    @classmethod
    def setUpClass(cls):
        _, cls.role, _ = db_admin.check_test_app_config()

    def setUp(self):
        self.conn, _ = db_admin.open_verified_test_db()
        self.tx = self.conn.transaction(force_rollback=True)
        self.tx.__enter__()

    def tearDown(self):
        self.tx.__exit__(None, None, None)
        self.conn.close()

    def problems(self):
        problems, _ = db_admin.app_role_problems(self.conn, self.role)
        self.assertEqual(self.conn.info.transaction_status, psycopg.pq.TransactionStatus.INTRANS)   # 호출자 트랜잭션 유지
        return problems

    def assertProblem(self, problems, *fragments):
        for fragment in fragments:
            self.assertTrue(any(fragment in p for p in problems), f"{fragment!r} 없음: {problems}")

    def forget_0006(self):
        self.conn.execute("DELETE FROM _yoyo_migration WHERE migration_id = %s", (MIGRATION,))

    def test_current_state_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_0004_applied_0006_not_applied_is_normal(self):
        """0006 을 실제로 되돌린 구조(되돌리기 파일 실행 + 적용 기록 삭제)에서는 regulatory_notes 가 없어도 정상."""
        text = (db_admin.MIGRATIONS_DIR / f"{MIGRATION}.rollback.sql").read_text(encoding="utf-8")
        try:
            with self.conn.transaction():
                self.conn.execute(text)
        except psycopg.errors.RaiseException:
            self.skipTest("test DB 에 메모·메모 출처 반영 기록이 있어 되돌린 구조를 만들 수 없음")
        self.forget_0006()
        self.assertEqual(self.problems(), [])
        self.assertNotIn("regulatory_notes", db_admin.read_state(self.conn)["tables"])

    def test_0006_recorded_but_table_missing_is_reported(self):
        self.conn.execute("DROP TABLE regulatory_notes CASCADE")
        self.assertProblem(self.problems(), f"{MIGRATION} 적용 기록이 있는데 테이블이 없음: regulatory_notes",
                           "권한 기준 표가 없습니다 (적용 기록 있음): regulatory_notes")

    def test_existing_required_table_missing_is_reported(self):
        self.conn.execute("DROP TABLE final_history CASCADE")
        self.assertProblem(self.problems(), "0003_versioning 적용 기록이 있는데 테이블이 없음: final_history",
                           "권한 기준 표가 없습니다 (적용 기록 있음): final_history")

    def test_missing_or_excessive_privileges_are_reported(self):
        cases = (
            ("DELETE 회수", "REVOKE DELETE ON regulatory_notes FROM cosmoa_app", "regulatory_notes 권한"),
            ("메모 UPDATE 회수", "REVOKE UPDATE (memo) ON regulatory_notes FROM cosmoa_app", "수정 가능 열"),
            ("근거 열 UPDATE 부여", "GRANT UPDATE (lookup_snapshot) ON regulatory_notes TO cosmoa_app", "수정 가능 열"),
            ("다른 표 DELETE 부여", "GRANT DELETE ON tab_versions TO cosmoa_app", "tab_versions 권한"),
            ("REFERENCES 부여", "GRANT REFERENCES ON regulatory_notes TO cosmoa_app", "regulatory_notes 권한"),
        )
        for label, statement, fragment in cases:
            with self.subTest(label=label):
                with self.conn.transaction(force_rollback=True):
                    self.conn.execute(statement)
                    self.assertProblem(self.problems(), fragment)

    def test_table_without_migration_record_is_reported(self):
        with self.subTest(label="0006 기록 없이 표만"):
            with self.conn.transaction(force_rollback=True):
                self.forget_0006()
                problems = self.problems()
                self.assertProblem(problems, f"{MIGRATION} 미적용인데 테이블이 이미 있음: regulatory_notes")
                self.assertProblem(problems, "regulatory_notes 권한")   # 기록이 없는 표에는 권한이 없어야 함
        with self.subTest(label="마이그레이션에 없는 표"):
            with self.conn.transaction(force_rollback=True):
                self.conn.execute("CREATE TABLE app_role_state_probe (id int)")
                self.assertProblem(self.problems(), "마이그레이션에 없는 테이블: app_role_state_probe")

    def test_inspect_state_still_ends_read_transaction(self):
        """기존 호출 방식(inspect_state)은 그대로 읽기 트랜잭션을 끝낸다 — 별도 연결에서 확인."""
        conn, _ = db_admin.open_verified_test_db()
        with conn:
            conn.execute("SELECT 1")
            db_admin.inspect_state(conn)
            self.assertEqual(conn.info.transaction_status, psycopg.pq.TransactionStatus.IDLE)
            db_admin.read_state(conn)
            self.assertEqual(conn.info.transaction_status, psycopg.pq.TransactionStatus.INTRANS)
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
