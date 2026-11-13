"""국가별 인허가 규제 — 화면·정적 자산·소스 보호·Route 목록 테스트 (담당자 B).

실행 (프로젝트 루트):  python -m unittest discover -s src/02_regulatory/tests -p "test_regulatory_routes.py" -v

- 4-3단계(2026-11-11)에 test_regulatory_service.py 에서 옮겼다. K-Beauty API 테스트는 모듈과 함께 삭제했다.
- 외부 HTTP 를 호출하지 않는다. 검색·조회 흐름은 test_regulatory_direct_search.py, 추출·OCR 은 test_regulatory_extract.py.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REG_DIR = HERE.parent
BASE_DIR = REG_DIR.parent.parent

sys.path.insert(0, str(BASE_DIR))
import app as flask_app  # noqa: E402


def _login(client):
    """페이지·API Route 가 @login_required 라서 테스트 세션에 사용자를 넣는다. (업무 DB·비밀번호 불필요)"""
    from src.common.testing import login_as   # 업무 DB 대신 메모리 사용자 (세션 형식 v2)
    login_as(client, {"id": 0, "email": "test@example.invalid", "name": "테스트", "team": "B"}, flask_app)


class RouteTest(unittest.TestCase):
    def setUp(self):
        flask_app.app.config["TESTING"] = True
        self.client = flask_app.app.test_client()
        _login(self.client)

    def test_page_and_assets_load(self):
        for path in ("/regulatory", "/assets/02_regulatory/regulatory.css", "/assets/02_regulatory/regulatory.js"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
            res.close()
        html = self.client.get("/regulatory").get_data(as_text=True)
        for marker in ("regulatory-search-form", "regulatory-autocomplete-options", "regulatory-search-selected",
                       'data-detail="lookup-raw"', "regulatory-result-body"):
            self.assertIn(marker, html, marker)
        self.assertNotIn("RAPIDAPI", html)

    def test_python_sources_not_served_as_assets(self):
        """현재 존재하는 Python 소스(규제·챗봇·공통 등 src/ 전체)가 /assets 로 노출되지 않는다 (확장자 허용 목록)"""
        src_dir = BASE_DIR / "src"
        sources = sorted(p for p in src_dir.rglob("*.py") if "__pycache__" not in p.parts)
        self.assertGreater(len(sources), 10)
        must = {"02_regulatory/regulatory_search.py", "02_regulatory/regulatory_mfds_lookup.py", "02_regulatory/regulatory_extract.py",
                "06_chatbot/tools.py", "06_chatbot/server.py", "common/auth.py"}
        rels = {p.relative_to(src_dir).as_posix() for p in sources}
        self.assertTrue(must <= rels, must - rels)                        # 대표 소스가 실제로 목록에 있는지
        for rel in sorted(rels):
            for variant in (rel, rel[:-3] + ".PY"):
                res = self.client.get("/assets/" + variant)
                self.assertEqual(res.status_code, 404, variant)
                res.close()
        for other in ("02_regulatory/regulatory.md", "02_regulatory/api_reference.md", "06_chatbot/chatbot.md"):
            res = self.client.get("/assets/" + other)                     # 명세·내부 문서도 자산이 아님
            self.assertEqual(res.status_code, 404, other)
            res.close()
        res = self.client.get("/assets/02_regulatory/regulatory.js")    # 같은 경로 규칙으로 허용 자산은 200 (404 가 경로 오류가 아님을 확인)
        self.assertEqual(res.status_code, 200)
        res.close()

    def test_removed_kbeauty_module_and_routes(self):
        """4-1·4-3단계: 이전 K-Beauty 경로·모듈은 없다 — 외부 호출 없이 404, Route 는 search·lookup·extract 뿐"""
        self.assertFalse((REG_DIR / "regulatory_service.py").exists())
        self.assertFalse((REG_DIR / "test_data").exists())
        self.assertFalse(hasattr(flask_app, "regulatory_service"))
        with mock.patch("requests.sessions.Session.request", side_effect=AssertionError("external HTTP must not be called")) as req:
            for url in ("/api/regulatory/ingredients?q=%EB%A0%88%ED%8B%B0%EB%86%80",
                        "/api/regulatory/regulations?code=5489&country=EU&source=api",
                        "/api/regulatory/regulations?code=5489&country=EU&inci_name=Retinol",
                        "/assets/02_regulatory/regulatory_service.py"):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 404, url)
                self.assertNotIn("RAPIDAPI", res.get_data(as_text=True))
            req.assert_not_called()
        rules = {r.rule for r in flask_app.app.url_map.iter_rules() if r.rule.startswith("/api/regulatory/")}
        self.assertEqual(rules, {"/api/regulatory/search", "/api/regulatory/lookup", "/api/regulatory/extract"})

    def test_page_copy_mentions_bilingual_autocomplete(self):
        html = self.client.get("/regulatory").get_data(as_text=True)
        self.assertIn("영문 INCI", html)
        self.assertNotIn("<<<<<<<", html)


if __name__ == "__main__":
    unittest.main()
