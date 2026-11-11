"""직접 검색 2단계 Route 테스트 (담당자 B) — /api/regulatory/search · /api/regulatory/lookup.

임시 DB 만 쓴다 (실제 수집 DB·외부 API 사용 안 함). 모든 외부 HTTP(requests) 호출을 막고 0회인지 함께 확인한다.
app.py 는 4-1단계부터 K뷰티 모듈(regulatory_service)을 로드하지 않는다 — 규제 화면 Route 에서 K뷰티 호출 경로 자체가 없다.
실행 (프로젝트 루트):  python -m unittest discover -s src/02_regulatory/tests -p "test_regulatory_direct_search.py" -v
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE.parents[2]
sys.path.insert(0, str(BASE_DIR))

_spec = importlib.util.spec_from_file_location("test_regulatory_search_fixtures", HERE / "test_regulatory_search.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

import app as flask_app  # noqa: E402

RS = flask_app.regulatory_search


class _RouteBase(unittest.TestCase):
    """임시 DB + 외부 HTTP 차단 + API 키 비움 + 테스트 로그인 (공통 준비만, 테스트 없음)"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.ingr_path = d / "mfds_ingredients.sqlite"
        self.rstr_path = d / "mfds_use_restriction.sqlite"
        F.build_ingredient_db(self.ingr_path, F.INGR_ITEMS)
        F.build_restriction_db(self.rstr_path, F.RSTR_ITEMS)
        self.env = mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(self.ingr_path), "MFDS_DB_PATH": str(self.rstr_path)})
        self.env.start()
        RS.clear_cache()
        # 외부 HTTP 감시 — 검색·조회·추출 흐름에서 한 번도 불리면 안 된다 (K뷰티·식약처 API 키 없이도 동작)
        self.http_block = mock.patch("requests.sessions.Session.request", side_effect=AssertionError("external HTTP must not be called"))
        self.http = self.http_block.start()
        self.nokey = mock.patch.dict(os.environ, {"RAPIDAPI_KEY": "", "RAPIDAPI_HOST": "", "MFDS_API_KEY": ""})
        self.nokey.start()
        flask_app.app.config["TESTING"] = True
        self.client = flask_app.app.test_client()
        from src.common.testing import login_as
        login_as(self.client, {"id": 0, "email": "t@example.invalid", "name": "t", "team": "B"}, flask_app)

    def tearDown(self):
        self.assertEqual(self.http.call_count, 0)
        self.http_block.stop()
        self.nokey.stop()
        self.env.stop()
        RS.clear_cache()
        self.tmp.cleanup()

    def get(self, url):
        res = self.client.get(url)
        return res.status_code, res.get_json()

    def key_of(self, q, source, kr=None):
        st, body = self.get("/api/regulatory/search?q=" + q)
        self.assertEqual(st, 200)
        for c in body["candidates"]:
            if c["source"] == source and (kr is None or c["kr_name"].strip() == kr):
                return c["key"]
        self.fail("후보 없음 %s" % q)


class DirectSearchRouteTest(_RouteBase):
    def test_search_returns_both_sources_without_auto_confirm(self):
        st, body = self.get("/api/regulatory/search?q=Water")
        self.assertEqual(st, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["auto_confirmed"])
        ex = [c["kr_name"] for c in body["candidates"] if c["match"] == "exact"]
        self.assertEqual(sorted(ex), ["정제수", "탄산수"])
        st, body = self.get("/api/regulatory/search?q=%EB%A0%88%ED%8B%B0%EB%86%80")          # 레티놀
        self.assertEqual({c["source"] for c in body["candidates"] if c["match"] == "exact"}, {RS.SRC_INGR, RS.SRC_RSTR})

    def test_search_validation_and_db_errors(self):
        for q in ("", "a", "%20"):
            st, body = self.get("/api/regulatory/search?q=" + q)
            self.assertEqual((st, body["error"]["kind"]), (400, "validation"), q)
        with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(Path(self.tmp.name) / "none.sqlite")}):
            st, body = self.get("/api/regulatory/search?q=Water")
        self.assertEqual((st, body["error"]["kind"], body["error"]["source"]), (503, "db_missing", RS.SRC_INGR))
        st, body = self.get("/api/regulatory/search?q=%EC%97%86%EB%8A%94%EC%84%B1%EB%B6%84")   # 없는성분 → 오류 아님
        self.assertEqual((st, body["total"]), (200, 0))

    def test_lookup_restriction_and_ingredient_candidates(self):
        key = self.key_of("%EB%A0%88%ED%8B%B0%EB%86%80", RS.SRC_INGR, "레티놀")
        st, body = self.get("/api/regulatory/lookup?key=%s&country=EU" % key)
        self.assertEqual((st, body["lookup_status"], body["link"]["status"]), (200, "found", "linked"))
        self.assertEqual(body["entries"][0]["limit_condition"], "0.3%")
        key2 = self.key_of("Mercury", RS.SRC_RSTR)
        st, body = self.get("/api/regulatory/lookup?key=%s&country=US" % key2)
        self.assertEqual((st, body["lookup_status"]), (200, "no_market_record"))

    def test_lookup_ignores_browser_supplied_names(self):
        """브라우저가 이름·CAS·identity 를 보내도 조회 대상은 서버가 검증한 key 로만 정한다"""
        key = self.key_of("%EB%A0%88%ED%8B%B0%EB%86%80", RS.SRC_RSTR, "레티놀")
        st, body = self.get("/api/regulatory/lookup?key=%s&country=EU&kr_name=%%EC%%88%%98%%EC%%9D%%80&inci_name=Mercury&cas=7439-97-6&std_name=x" % key)
        self.assertEqual(st, 200)
        self.assertEqual(body["matched_identity"]["std_name"], "레티놀")

    def test_lookup_errors(self):
        st, body = self.get("/api/regulatory/lookup?country=EU")
        self.assertEqual((st, body["error"]["kind"]), (400, "validation"))
        key = self.key_of("Mercury", RS.SRC_RSTR)
        st, body = self.get("/api/regulatory/lookup?key=%s&country=XX" % key)
        self.assertEqual((st, body["error"]["kind"]), (400, "validation"))
        st, body = self.get("/api/regulatory/lookup?key=garbage&country=EU")
        self.assertEqual((st, body["error"]["kind"]), (400, "validation"))
        snap = key.split(":")[1]
        st, body = self.get("/api/regulatory/lookup?key=%s:%s:999999&country=EU" % (RS.SRC_RSTR, snap))
        self.assertEqual((st, body["error"]["kind"]), (404, "not_found"))
        st, body = self.get("/api/regulatory/lookup?key=%s:%s:1&country=EU" % (RS.SRC_RSTR, "0" * 16))
        self.assertEqual((st, body["error"]["kind"]), (409, "stale_key"))
        with mock.patch.dict(os.environ, {"MFDS_DB_PATH": str(Path(self.tmp.name) / "none.sqlite")}):
            RS.clear_cache()
            st, body = self.get("/api/regulatory/lookup?key=%s&country=EU" % key)
        self.assertEqual((st, body["error"]["kind"]), (503, "db_missing"))

    def test_lookup_markets_from_mfds_module(self):
        """국가 검증은 regulatory_mfds_lookup.MARKET_CODES 기준 (4-1단계 전환). 지원 시장은 기존과 같은 6개"""
        self.assertFalse(hasattr(flask_app, "regulatory_service"))
        self.assertEqual(set(flask_app.regulatory_mfds.MARKET_CODES), {"KR", "EU", "CN", "US", "JP", "ASEAN"})
        key = self.key_of("Mercury", RS.SRC_RSTR)
        for m in flask_app.regulatory_mfds.MARKET_CODES:
            st, body = self.get("/api/regulatory/lookup?key=%s&country=%s" % (key, m.lower()))   # 소문자도 대문자로 정규화
            self.assertEqual(st, 200, m)
            self.assertIn(body["lookup_status"], ("found", "no_market_record"), m)

    def test_link_required_and_not_linked_are_200_not_errors(self):
        key = self.key_of("%EB%A7%88%EC%9D%B4%EC%B9%B4", RS.SRC_INGR)                       # 마이카
        st, body = self.get("/api/regulatory/lookup?key=%s&country=EU" % key)
        self.assertEqual((st, body["lookup_status"], len(body["link_candidates"])), (200, "link_required", 2))
        key = self.key_of("Aqua", RS.SRC_INGR, "정제수")
        st, body = self.get("/api/regulatory/lookup?key=%s&country=KR" % key)
        self.assertEqual((st, body["lookup_status"]), (200, "not_linked"))

    def test_login_required(self):
        anon = flask_app.app.test_client()
        for url in ("/api/regulatory/search?q=Water", "/api/regulatory/lookup?key=x&country=EU"):
            res = anon.get(url)
            self.assertIn(res.status_code, (401, 302), url)

    def test_page_direct_search_has_no_kbeauty_choice(self):
        html = self.client.get("/regulatory").get_data(as_text=True)
        self.assertNotIn('id="regulatory-search-source"', html)
        self.assertIn('id="regulatory-search-datasource"', html)
        self.assertIn('id="regulatory-file-datasource"', html)                             # 파일 탭도 3단계에서 식약처 DB 고정
        self.assertIn('id="regulatory-single-ingredient-source"', html)
        js = self.client.get("/assets/02_regulatory/regulatory.js").get_data(as_text=True)
        self.assertIn("/api/regulatory/search?q=", js)
        self.assertIn("/api/regulatory/lookup?key=", js)


class FileFlowRouteTest(_RouteBase):
    """3단계: 실제 샘플 파일 업로드(/extract) → 추출 성분명으로 /search → 선택 key 로 /lookup.
    K뷰티 호출 차단·키 없음 상태에서 파일 흐름 전체가 식약처 DB 만으로 동작하는지 (화면 JS 는 브라우저 확인에서)"""

    SAMPLE_PDF = HERE.parent / "samples" / "eu_ser_041_development_brief_regulatory.pdf"

    def upload(self, path):
        with open(path, "rb") as f:
            res = self.client.post("/api/regulatory/extract", data={"file": (f, path.name)}, content_type="multipart/form-data")
        return res.status_code, res.get_json()

    def test_pdf_upload_search_select_lookup_without_kbeauty(self):
        st, body = self.upload(self.SAMPLE_PDF)
        self.assertEqual((st, body["status"]), (200, "extracted"))
        names = [it["name_raw"] for it in body["items"]]
        for n in ("Glycerin", "Retinol", "Phenoxyethanol", "Aqua"):
            self.assertIn(n, names)
        found = {}
        for n in names:
            st, s = self.get("/api/regulatory/search?q=" + n.replace(" ", "%20"))
            self.assertEqual(st, 200, n)
            found[n] = s
        # Aqua: 정확 일치 1건(성분정보 정제수, 영문명 나열 항목) → 화면 추천 조건 충족. 자동 선택은 서버가 하지 않는다
        aqua = found["Aqua"]
        self.assertEqual(aqua["exact_total"], 1)
        self.assertFalse(aqua["auto_confirmed"])
        self.assertEqual(aqua["candidates"][0]["kr_name"], "정제수")
        self.assertEqual(aqua["candidates"][0]["matched"][0]["field"], "INGR_ENG_NAME")
        # Retinol: 정확 일치가 여러 출처·이명(레티닐팔미테이트)에 있어 추천 조건 아님
        self.assertGreater(found["Retinol"]["exact_total"], 1)
        # 레티놀(성분정보) 선택 → EU 조회: 레티놀 규제만
        k = [c["key"] for c in found["Retinol"]["candidates"] if c["source"] == RS.SRC_INGR and c["kr_name"] == "레티놀"][0]
        st, r = self.get("/api/regulatory/lookup?key=%s&country=EU" % k)
        self.assertEqual((st, r["lookup_status"], r["matched_identity"]["std_name"]), (200, "found", "레티놀"))
        self.assertTrue(all(e["std_name"] == "레티놀" for e in r["entries"]))
        # 같은 key 는 같은 결과 (화면은 (key, 시장)당 1회만 요청해 공유)
        st, r2 = self.get("/api/regulatory/lookup?key=%s&country=EU" % k)
        self.assertEqual(r2["entries"], r["entries"])

    def test_xlsx_sheet_selection_then_search(self):
        path = HERE / "fixtures" / "sample_multisheet_en.xlsx"
        st, body = self.upload(path)
        self.assertEqual((st, body["status"]), (200, "sheet_required"))
        with open(path, "rb") as f:
            res = self.client.post("/api/regulatory/extract", data={"file": (f, path.name), "sheet": "Ingredients"}, content_type="multipart/form-data")
        body = res.get_json()
        self.assertEqual((res.status_code, body["status"]), (200, "extracted"))
        st, s = self.get("/api/regulatory/search?q=" + body["items"][0]["name_raw"].replace(" ", "%20"))
        self.assertEqual(st, 200)

    def test_page_file_tab_uses_new_routes_only(self):
        js = self.client.get("/assets/02_regulatory/regulatory.js").get_data(as_text=True)
        self.assertNotIn("/api/regulatory/ingredients", js)
        self.assertNotIn("/api/regulatory/regulations", js)
        self.assertNotIn("findExactMatch", js)
        self.assertNotIn("fileSource", js)
        # 4-1단계: K뷰티 전용 표시·분기 제거 (출처 라벨·접근 제한·요금제 안내·code/updated_at 표시)
        for legacy in ("RapidAPI", "ACCESS_KINDS", "note_mentions_plan", "record_updated_at", "sel.code", "성분 code 로 조회", "외부 API HTTP"):
            self.assertNotIn(legacy, js, legacy)
        html = self.client.get("/regulatory").get_data(as_text=True)
        for marker in ("regulatory-review-accept", "regulatory-kpi-nomarket", "regulatory-kpi-link", "regulatory-kpi-pending",
                       "regulatory-batch-incomplete", "regulatory-batch-snapshot", "regulatory-file-datasource"):
            self.assertIn(marker, html, marker)


if __name__ == "__main__":
    unittest.main()
