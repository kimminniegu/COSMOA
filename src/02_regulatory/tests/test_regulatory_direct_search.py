"""직접 검색 2단계 Route 테스트 (담당자 B) — /api/regulatory/search · /api/regulatory/lookup.

임시 DB 만 쓴다 (실제 수집 DB·외부 API 사용 안 함). K뷰티 API(regulatory_service._get) 호출이 0회인지 함께 확인한다.
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
SVC = flask_app.regulatory_service


class DirectSearchRouteTest(unittest.TestCase):
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
        # K뷰티 API 호출 감시 — 직접 검색 흐름에서 한 번도 불리면 안 된다 (키 없이도 동작)
        self.kbeauty = mock.patch.object(SVC, "_get", side_effect=AssertionError("K-Beauty API must not be called"))
        self.kget = self.kbeauty.start()
        self.nokey = mock.patch.dict(os.environ, {"RAPIDAPI_KEY": "", "RAPIDAPI_HOST": "", "MFDS_API_KEY": ""})
        self.nokey.start()
        flask_app.app.config["TESTING"] = True
        self.client = flask_app.app.test_client()
        from src.common.testing import login_as
        login_as(self.client, {"id": 0, "email": "t@example.invalid", "name": "t", "team": "B"}, flask_app)

    def tearDown(self):
        self.assertEqual(self.kget.call_count, 0)
        self.kbeauty.stop()
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
        self.assertIn('id="regulatory-file-source"', html)                                 # 파일 탭 전환은 3단계
        self.assertIn('id="regulatory-single-ingredient-source"', html)
        js = self.client.get("/assets/02_regulatory/regulatory.js").get_data(as_text=True)
        self.assertIn("/api/regulatory/search?q=", js)
        self.assertIn("/api/regulatory/lookup?key=", js)


if __name__ == "__main__":
    unittest.main()
