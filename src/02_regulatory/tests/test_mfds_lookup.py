"""식약처 규제 DB 조회 모듈(regulatory_mfds_lookup.lookup_by_identity) 테스트 (담당자 B). 임시 DB(수집 스키마 재사용)와 실제 수집 DB(있을 때만, 읽기 전용)로 검증. 외부 API 호출 없음.

실행: python -m unittest discover -s src/02_regulatory/tests -p "test_mfds_lookup*.py" -v
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG_DIR = HERE.parent
BASE_DIR = REG_DIR.parent.parent

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

mfds = _load("mfds_collect", REG_DIR / "mfds_use_restriction.py")
lk = _load("mfds_lookup", REG_DIR / "regulatory_mfds_lookup.py")

REAL_DB = BASE_DIR / "instance" / "regulatory" / "mfds_use_restriction.sqlite"


def rec(std, eng, country, rtype, limit=None, proviso=None, cas=None, syn=None, notice=None):
    return {"REGULATE_TYPE": rtype, "INGR_STD_NAME": std, "INGR_ENG_NAME": eng, "CAS_NO": cas, "INGR_SYNONYM": syn,
            "COUNTRY_NAME": country, "NOTICE_INGR_NAME": notice or eng, "PROVIS_ATRCL": proviso, "LIMIT_COND": limit}


FIXTURE = [
    rec("레티놀", "Retinol", "EU", "한도", "* 【Restrictions】\nProduct Type : (a) Body lotion\n* 【제한】\n제품 유형 : (a) 바디 로션", cas="11103-57-4\n68-26-8"),
    rec("레티놀", "Retinol", "캐나다", "한도", "* 【Restrictions】\nMax : 1.0%", cas="11103-57-4\n68-26-8"),
    rec("레티닐아세테이트", "Retinyl Acetate", "EU", "한도", "x", cas="127-47-9", syn="retinol acetate"),
    rec("페녹시에탄올", "Phenoxyethanol", "EU", "한도", "* 【Restrictions】\nMaximum concentration : 1.0%\n* 【제한】\n최대 농도 : 1.0%", cas="122-99-6"),
    rec("페녹시에탄올", "Phenoxyethanol", "중국", "한도", "* 【화장품 중 최대사용농도】 배합한도 : 1%", cas="122-99-6"),
    rec("페녹시에탄올", "Phenoxyethanol", "일본", "한도", "* 【100g당 최대 배합량】 : 1.0 g", cas="122-99-6"),
    rec("페녹시에탄올", "Phenoxyethanol", "아세안", "한도", "* 【Restrictions】\nMax : 1.0%", cas="122-99-6"),
    rec("2,4-다이아미노페녹시에탄올", "2,4-Diaminophenoxyethanol", "EU", "금지", None, cas="70643-19-5"),
    rec("가상금지물질", "Fictional Prohibited", "EU", "금지", None, proviso="단서 예시", cas="11-11-1"),
    rec("가상한도물질", "Fictional Limited", "EU", "한도", None, cas="22-22-2"),                        # 한도인데 제한사항 없음
    rec("복수조건물질", "Multi Condition", "EU", "한도", "* 【Restrictions】\n조건 A", cas="33-33-3"),
    rec("복수조건물질", "Multi Condition", "EU", "한도", "* 【Restrictions】\n조건 B", cas="33-33-3"),
    rec("동명물질", "Same Name A", "EU", "금지", None, cas="44-44-4"),                                  # 표준명 같고 영문명 다름 → 모호
    rec("동명물질", "Same Name B", "EU", "한도", "x", cas="55-55-5"),
    rec("유럽전용", "Europe Only", "유럽", "금지", None, cas="66-66-6"),                                 # 원본 '유럽' — EU 조회 범위 밖
]


def build_db(path, status="completed"):
    conn = mfds.open_db(path)
    with conn:
        conn.execute("INSERT INTO runs (started_at, status, source_url, source_page, page_size, total_count_first, total_count_last, pages_done, records_saved, calls_made, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ("2026-09-23T10:50:37+00:00", status, mfds.public_url(), mfds.SOURCE_PAGE, 100, len(FIXTURE), len(FIXTURE), 1, len(FIXTURE), 1, "2026-09-23T10:53:54+00:00"))
        rid = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()[0]
        conn.executemany("INSERT INTO records (run_id, page_no, row_index, fetched_at, %s, raw_json) VALUES (?,?,?,?,%s,?)" % (", ".join(mfds.FIELDS), ",".join("?" * len(mfds.FIELDS))),
                         [(rid, 1, i, "2026-09-23T10:50:40+00:00") + tuple(r.get(f) for f in mfds.FIELDS) + (json.dumps(r, ensure_ascii=False),) for i, r in enumerate(FIXTURE)])
    conn.close()
    return rid


class IdentityLookupFixtureTest(unittest.TestCase):
    """lookup_by_identity() — 규제 화면·챗봇이 regulatory_search.lookup_candidate 를 거쳐 쓰는 조회 경로.
    4-3단계에서 삭제한 이름·CAS 재매칭 lookup() 테스트 중 새 경로에도 필요한 검증(국가별 조회·조건별 복수 레코드·제한 조건 없음·
    EU/유럽 구분·DB 상태·수집 시각과 원문 보존)을 이 경로 기준으로 옮겼다. 이름·CAS 로 성분을 찾는 검증은 test_regulatory_search.py 가 맡는다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = Path(cls.tmp) / "fixture.sqlite"
        build_db(cls.db)

    def look(self, std, eng, market, **kw):
        kw.setdefault("path", self.db)
        return lk.lookup_by_identity(std, eng, market, **kw)

    def test_retinol_eu_found_with_raw_text_and_source(self):
        r = self.look("레티놀", "retinol", "EU")
        self.assertEqual(r["lookup_status"], "found")
        self.assertEqual(len(r["entries"]), 1)
        e = r["entries"][0]
        self.assertEqual((e["regulate_type"], e["country"], e["country_code"], e["source_type"]), ("한도", "EU", "EU", "mfds"))
        self.assertEqual(e["limit_condition"], FIXTURE[0]["LIMIT_COND"])          # 원문 그대로 (가공·번역 없음)
        self.assertFalse(e["limit_missing"])
        self.assertEqual(r["markets_listed"], ["EU", "캐나다"])
        self.assertEqual(r["matched_identity"], {"std_name": "레티놀", "eng_name": "Retinol"})
        self.assertEqual(r["source_page"], lk.SOURCE_PAGE)
        self.assertIsNone(r["source_updated_at"]); self.assertIsNone(r["law_dates"])
        self.assertTrue(any(x["std_name"] == "레티닐아세테이트" for x in r["related"]))   # 관련 항목은 확정 규제와 분리
        self.assertTrue(all(x["std_name"] != "레티놀" for x in r["related"]))

    def test_country_mapping_and_no_market_record(self):
        for m, snippet in (("EU", "1.0%"), ("CN", "배합한도"), ("JP", "1.0 g"), ("ASEAN", "1.0%")):
            r = self.look("페녹시에탄올", "phenoxyethanol", m)
            self.assertEqual(r["lookup_status"], "found", m)
            self.assertIn(snippet, r["entries"][0]["limit_condition"], m)
        r = self.look("페녹시에탄올", "phenoxyethanol", "US")
        self.assertEqual(r["lookup_status"], "no_market_record")                    # 기록 없음 ≠ 허용
        self.assertEqual(r["entries"], [])
        self.assertIn("허용·안전·규제 없음을 뜻하지 않아요", r["result_note"])

    def test_identity_normalization_keeps_symbols(self):
        self.assertEqual(self.look("페녹시에탄올", "  PHENOXYETHANOL ", "EU")["lookup_status"], "found")   # 대소문자·공백만 정규화
        r = self.look("2,4-다이아미노페녹시에탄올", "2,4-diaminophenoxyethanol", "EU")                  # 숫자·기호 유지
        self.assertEqual(r["entries"][0]["regulate_type"], "금지")
        self.assertIsNone(r["entries"][0]["limit_condition"]); self.assertFalse(r["entries"][0]["limit_missing"])   # 금지 + null ≠ 제한 없음

    def test_limited_without_limit_text_flagged_and_proviso(self):
        self.assertTrue(self.look("가상한도물질", "fictional limited", "EU")["entries"][0]["limit_missing"])   # 화면 '상세 제한사항 미제공'
        self.assertEqual(self.look("가상금지물질", "fictional prohibited", "EU")["entries"][0]["proviso"], "단서 예시")

    def test_multiple_condition_records_all_returned(self):
        r = self.look("복수조건물질", "multi condition", "EU")
        self.assertEqual([e["limit_condition"] for e in r["entries"]], ["* 【Restrictions】\n조건 A", "* 【Restrictions】\n조건 B"])

    def test_same_std_name_identities_not_merged(self):
        a = self.look("동명물질", "same name a", "EU")
        b = self.look("동명물질", "same name b", "EU")
        self.assertEqual([e["regulate_type"] for e in a["entries"]], ["금지"])
        self.assertEqual([e["regulate_type"] for e in b["entries"]], ["한도"])

    def test_eu_scope_excludes_europe_label(self):
        r = self.look("유럽전용", "europe only", "EU")
        self.assertEqual(r["lookup_status"], "no_market_record")                    # 원본 '유럽' 은 EU 조회 범위 밖 (합치지 않음)
        self.assertEqual(r["markets_listed"], ["유럽"])
        self.assertEqual(r["country"]["country_names"], ["EU"])
        self.assertEqual(lk.MARKET_TO_COUNTRY["EU"], ["EU"])

    def test_collected_at_from_run_metadata(self):
        r = self.look("레티놀", "retinol", "EU")
        self.assertEqual(r["collected_at"], "2026-09-23T10:53:54+00:00")             # runs.finished_at 그대로 (파일 수정 시각·현재 시각 아님)
        self.assertEqual(r["acquired_at"], r["collected_at"])
        self.assertNotEqual(r["queried_at"], r["acquired_at"])
        self.assertEqual(r["refresh_policy"], "수동 재수집 (자동 갱신 없음)")
        self.assertEqual(r["collection_run"]["records"], len(FIXTURE))
        nofin = Path(self.tmp) / "nofinish.sqlite"; build_db(nofin)
        conn = mfds.open_db(nofin)
        with conn:
            conn.execute("UPDATE runs SET finished_at=NULL")
        conn.close()
        self.assertIsNone(self.look("레티놀", "retinol", "EU", path=nofin)["acquired_at"])   # 기록 없으면 None (화면 '수집 시각 미기록')

    def test_missing_identity_and_stale_run(self):
        with self.assertRaises(lk.MfdsLookupError) as ctx:
            self.look("없는성분", "no such", "EU")
        self.assertEqual(ctx.exception.kind, "identity_missing")
        run = self.look("레티놀", "retinol", "EU")["collection_run"]
        ok = self.look("레티놀", "retinol", "EU", expected_run={"run_id": run["run_id"], "started_at": run["started_at"], "finished_at": run["finished_at"]})
        self.assertEqual(ok["lookup_status"], "found")
        with self.assertRaises(lk.MfdsLookupError) as ctx2:
            self.look("레티놀", "retinol", "EU", expected_run={"run_id": run["run_id"], "started_at": "2000-01-01T00:00:00+00:00", "finished_at": run["finished_at"]})
        self.assertEqual(ctx2.exception.kind, "stale_run")

    def test_db_states(self):
        missing = Path(self.tmp) / "nope.sqlite"
        with self.assertRaises(lk.MfdsLookupError) as ctx:
            self.look("레티놀", "retinol", "EU", path=missing)
        self.assertEqual(ctx.exception.kind, "db_missing")
        self.assertFalse(missing.exists())                                       # 빈 DB 를 만들지 않는다
        inc = Path(self.tmp) / "incomplete.sqlite"; build_db(inc, status="running")
        with self.assertRaises(lk.MfdsLookupError) as ctx2:
            self.look("레티놀", "retinol", "EU", path=inc)
        self.assertEqual(ctx2.exception.kind, "db_incomplete")
        bad = Path(self.tmp) / "bad.sqlite"; bad.write_bytes(b"this is not a sqlite database at all")
        with self.assertRaises(lk.MfdsLookupError) as ctx3:
            self.look("레티놀", "retinol", "EU", path=bad)
        self.assertEqual(ctx3.exception.kind, "db_error")
        with self.assertRaises(lk.MfdsLookupError) as ctx4:
            self.look("레티놀", "retinol", "TW")
        self.assertEqual(ctx4.exception.kind, "validation")

    def test_removed_name_lookup_api(self):
        for name in ("lookup", "identify", "cas_tokens"):
            self.assertFalse(hasattr(lk, name), name)                              # 4-3단계 삭제 (실행 코드 미사용)


class RouteSourceTest(unittest.TestCase):
    """규제 화면 출처 표시. 이전 /api/regulatory/regulations(source=mfds|api) Route 테스트는 4-1단계에서 경로와 함께 삭제했다.
    규제 기록 조회는 위 IdentityLookupFixtureTest(lookup_by_identity), 화면 조회(/lookup)는 test_regulatory_direct_search.py 가 검증한다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); cls.db = Path(cls.tmp) / "fixture.sqlite"; build_db(cls.db)
        os.environ["MFDS_DB_PATH"] = str(cls.db)
        sys.path.insert(0, str(BASE_DIR))
        import app as flask_app
        cls.app = flask_app
        flask_app.app.config["TESTING"] = True

    def client(self):
        c = self.app.app.test_client()
        from src.common.testing import login_as   # 업무 DB 대신 메모리 사용자 (세션 형식 v2)
        login_as(c, {"id": 0, "email": "t@example.invalid", "name": "t", "team": "B"}, self.app)
        return c

    def test_page_has_no_kbeauty_source_choice(self):
        """출처 선택 radio 는 없다 — 직접 검색(2단계)·파일 탭(3단계) 모두 식약처 수집 DB 고정 안내로 바뀌었다"""
        html = self.client().get("/regulatory").get_data(as_text=True)
        for p in ("search", "file"):
            self.assertNotIn('id="regulatory-%s-source"' % p, html)
            self.assertIn('id="regulatory-%s-datasource"' % p, html)
        self.assertNotIn('name="regulatory-file-source"', html)
        self.assertNotIn("K뷰티 API (RapidAPI)", html)
        self.assertNotIn("API 매칭", html)


@unittest.skipUnless(REAL_DB.is_file(), "수집 DB 가 있을 때만")
class RealDbTest(unittest.TestCase):
    """실제 로컬 수집 DB (읽기 전용) — lookup_by_identity 로 대표 성분 확인"""

    def test_real_records(self):
        r = lk.lookup_by_identity("레티놀", "retinol", "EU", path=REAL_DB)
        self.assertEqual(r["lookup_status"], "found"); self.assertEqual(r["entries"][0]["regulate_type"], "한도")
        for m in ("EU", "CN", "JP", "ASEAN", "KR"):
            self.assertEqual(lk.lookup_by_identity("페녹시에탄올", "phenoxyethanol", m, path=REAL_DB)["lookup_status"], "found", m)
        self.assertEqual(lk.lookup_by_identity("레티놀", "retinol", "US", path=REAL_DB)["lookup_status"], "no_market_record")
        self.assertIsNotNone(r["collected_at"])
