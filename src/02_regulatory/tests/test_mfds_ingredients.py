"""식약처 원료성분정보 수집 스크립트 테스트 (담당자 B). 외부 API 를 호출하지 않는다 — 모의 응답으로 검증.

실행 (프로젝트 루트):  python -m unittest discover -s src/02_regulatory/tests -p "test_mfds_ingredients.py" -v
"""

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mfds_ingredients", HERE.parent / "mfds_ingredients.py")
ing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ing)


def body(page_no, num_rows, total, items, code="00"):
    return json.dumps({"header": {"resultCode": code, "resultMsg": "NORMAL SERVICE." if code == "00" else "ERR"},
                       "body": {"pageNo": page_no, "totalCount": total, "numOfRows": num_rows, "items": items}}, ensure_ascii=False)


def rec(i):
    return {"INGR_KOR_NAME": "성분%d" % i, "INGR_ENG_NAME": "Ingredient %d" % i if i % 3 else None,
            "CAS_NO": "%d-00-0" % (1000 + i) if i % 2 else None, "ORIGIN_MAJOR_KOR_NAME": None, "INGR_SYNONYM": None}


class FakeServer:
    def __init__(self, total, fail=None):
        self.total, self.fail, self.calls = total, fail or {}, []

    def __call__(self, session, params, timeout):
        assert "serviceKey" in params and params["type"] == "json"
        page, n = int(params["pageNo"]), int(params["numOfRows"])
        self.calls.append(page)
        f = self.fail.get(page)
        if f is not None:
            return f() if callable(f) else f
        start = (page - 1) * n
        return 200, body(page, n, self.total, [rec(i) for i in range(start + 1, min(start + n, self.total) + 1)])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = {"key": "test-key-not-real", "page_size": 10, "interval": 0.0, "timeout": 5.0, "retries": 2,
                    "db_path": Path(self.tmp.name) / "ingr.sqlite"}
        self.sleep = mock.patch.object(ing.time, "sleep", lambda s: None)
        self.sleep.start()

        self.conns = []

    def tearDown(self):
        for c in self.conns:
            c.close()
        self.sleep.stop()
        self.tmp.cleanup()

    def run_collect(self, server, **kw):
        with mock.patch.object(ing, "_http_get", server):
            return ing.collect(self.cfg, log=lambda *a: None, **kw)

    def db(self):
        c = sqlite3.connect(str(self.cfg["db_path"]))
        c.row_factory = sqlite3.Row
        self.conns.append(c)
        return c


class PathGuardTest(unittest.TestCase):
    def test_restriction_paths_refused(self):
        for p in ing.RESTRICTION_DB_PATHS:
            with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(p)}):
                with self.assertRaises(ing.Abort) as ctx:
                    ing.resolve_db_path()
                self.assertEqual(ctx.exception.kind, "config")

    def test_same_as_mfds_db_path_refused_and_not_reused(self):
        with tempfile.TemporaryDirectory() as t:
            p = str(Path(t) / "x.sqlite")
            with mock.patch.dict(os.environ, {"MFDS_DB_PATH": p, "MFDS_INGREDIENT_DB_PATH": p}):
                with self.assertRaises(ing.Abort):
                    ing.resolve_db_path()
            env = {k: v for k, v in os.environ.items() if k != "MFDS_INGREDIENT_DB_PATH"}
            env["MFDS_DB_PATH"] = p
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(ing.resolve_db_path(), ing.DEFAULT_DB)   # MFDS_DB_PATH 를 성분 DB 경로로 쓰지 않음

    def test_other_dataset_file_not_written(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "restriction.sqlite"
            c = sqlite3.connect(str(p)); c.execute("CREATE TABLE records (id INTEGER, REGULATE_TYPE TEXT)"); c.commit(); c.close()
            before = p.read_bytes()
            with self.assertRaises(ing.Abort) as ctx:
                ing.open_db(p)
            self.assertEqual(ctx.exception.kind, "config")
            self.assertEqual(p.read_bytes(), before)


class CollectTest(Base):
    def test_full_collect_preserves_raw_and_nulls(self):
        rid = self.run_collect(FakeServer(25))
        c = self.db()
        run = c.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
        self.assertEqual((run["status"], run["pages_done"], run["records_saved"]), ("completed", 3, 25))
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM records").fetchone()[0], 25)
        r = c.execute("SELECT * FROM records WHERE INGR_KOR_NAME='성분3'").fetchone()
        self.assertIsNone(r["INGR_ENG_NAME"])                                  # null 그대로 (채우지 않음)
        self.assertEqual(json.loads(r["raw_json"]), rec(3))
        self.assertEqual(json.loads(c.execute("SELECT item_keys FROM pages WHERE page_no=1").fetchone()[0]), sorted(ing.FIELDS))
        self.assertEqual(c.execute("SELECT value FROM meta WHERE key='dataset'").fetchone()[0], ing.DATASET)

    def test_max_pages_interrupted_then_resume_without_duplicates(self):
        server = FakeServer(45)
        rid = self.run_collect(server, max_pages=2)       # 1쪽 + 2쪽 더
        c = self.db()
        self.assertEqual(c.execute("SELECT status, pages_done, finished_at FROM runs").fetchone()[:], ("interrupted", 3, None))
        c.close()
        rid2 = self.run_collect(server)
        self.assertEqual(rid, rid2)
        self.assertEqual(server.calls, [1, 2, 3, 4, 5])                     # 이미 받은 쪽은 다시 호출하지 않음
        c = self.db()
        self.assertEqual(c.execute("SELECT status, records_saved FROM runs").fetchone()[:], ("completed", 45))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM records").fetchone()[0], 45)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM (SELECT DISTINCT page_no, row_index FROM records)").fetchone()[0], 45)

    def test_transient_exhausted_is_interrupted_and_resumable(self):
        server = FakeServer(30, fail={2: (503, "")})
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server)
        self.assertEqual(ctx.exception.kind, "http")
        self.assertEqual(server.calls, [1, 2, 2, 2])                        # 재시도 2회로 제한
        c = self.db()
        self.assertEqual(c.execute("SELECT status, pages_done FROM runs").fetchone()[:], ("interrupted", 1))
        c.close()
        server.fail = {}
        self.run_collect(server)
        c = self.db()
        self.assertEqual(c.execute("SELECT status, records_saved FROM runs").fetchone()[:], ("completed", 30))

    def test_auth_error_not_retried(self):
        server = FakeServer(30, fail={1: (200, body(1, 10, 0, [], code="30"))})
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertEqual(server.calls, [1])
        c = self.db()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        server2 = FakeServer(30, fail={2: (200, "<OpenAPI_ServiceResponse><returnReasonCode>22</returnReasonCode></OpenAPI_ServiceResponse>")})
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server2, new_run=True)
        self.assertEqual(ctx.exception.kind, "limit")
        self.assertEqual(server2.calls, [1, 2])

    def test_structure_problem_is_aborted_not_resumed(self):
        server = FakeServer(30, fail={2: (200, json.dumps({"header": {"resultCode": "00"}, "body": {"totalCount": 30, "items": {"item": []}}}))})
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server)
        self.assertEqual(ctx.exception.kind, "structure")
        c = self.db()
        row = c.execute("SELECT status, finished_at FROM runs").fetchone()
        self.assertEqual(row[0], "aborted")
        self.assertIsNotNone(row[1])
        c.close()
        server.fail = {}
        rid = self.run_collect(server)                                       # aborted 는 이어받지 않고 새 실행
        self.assertEqual(rid, 2)

    def test_repeated_page_aborts(self):
        server = FakeServer(30)
        server.fail = {2: lambda: (200, body(2, 10, 30, [rec(i) for i in range(1, 11)]))}
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server)
        self.assertEqual(ctx.exception.kind, "integrity")

    def test_resume_count_change_stops(self):
        server = FakeServer(30)
        self.run_collect(server, max_pages=0)
        server.total = 31
        with self.assertRaises(ing.Abort) as ctx:
            self.run_collect(server)
        self.assertEqual(ctx.exception.kind, "count_change")
        c = self.db()
        self.assertEqual(c.execute("SELECT status FROM runs").fetchone()[0], "interrupted")

    def test_split_names_keeps_chemical_locants(self):
        self.assertEqual(ing.split_names("Water,Aqua"), ["Water", "Aqua"])
        self.assertEqual(ing.split_names("Acid Red 52,CI 45100"), ["Acid Red 52", "CI 45100"])
        self.assertEqual(ing.split_names("1,2,6-Hexanetriol"), ["1,2,6-Hexanetriol"])
        self.assertEqual(ing.split_names("N,N-Bis(2-Hydroxyethyl)-p-Phenylenediamine Sulfate"), ["N,N-Bis(2-Hydroxyethyl)-p-Phenylenediamine Sulfate"])
        self.assertEqual(ing.split_names("설페이트,황산N,N-비스"), ["설페이트", "황산N,N-비스"])
        self.assertEqual(ing.split_names("4,4'-이소프로필리덴디페놀/에피클로로하이드린코폴리머"), ["4,4'-이소프로필리덴디페놀/에피클로로하이드린코폴리머"])
        self.assertEqual(ing.split_names(None), [])

    def test_analyze_and_find(self):
        self.run_collect(FakeServer(25))
        out = ing.analyze(self.cfg)
        self.assertEqual((out["integrity"], out["count_match"], out["page_gaps"], out["dup_all_fields_groups"]), ("ok", True, [], 0))
        self.assertEqual(out["empty"]["ORIGIN_MAJOR_KOR_NAME"], (25, 0))
        with mock.patch("builtins.print"), mock.patch.object(ing, "print", lambda *a, **k: None):
            res = ing.find(self.cfg, ["ingredient 4", "1007-00-0", "없는성분"])
        self.assertEqual(len(res["ingredient 4"]["exact"]), 1)
        self.assertEqual(res["1007-00-0"]["exact"][0][1], ["CAS"])
        self.assertEqual(res["없는성분"]["exact"], [])


if __name__ == "__main__":
    unittest.main()
