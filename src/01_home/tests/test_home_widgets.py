"""홈 위젯 개편 테스트 — 업무 DB·외부 API 에 접속하지 않습니다. 명세: src/01_home/home.md 2장"""
import importlib
import sys
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from src.common.testing import MemoryUserDB, login_as  # noqa: E402
from src.common.versions import Unavailable  # noqa: E402

home_data = importlib.import_module("src.01_home.home_data")
home_projects = importlib.import_module("src.01_home.home_projects")

TODAY = date(2026, 11, 5)   # 목요일 → 이번 주는 11/2(월) ~ 11/8(일)
USER = {"id": 7, "email": "home@example.invalid", "name": "홈테스트", "team": "A"}


def project(pid, name, *, due=None, stage="development", state="active"):
    return {"id": pid, "name": name, "stage": stage, "state": state, "customer_name": "테스트 고객사",
            "due_date": TODAY + timedelta(days=due) if due is not None else None}


class BuildWidgetsTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            project(1, "지난 납기", due=-2), project(2, "오늘 납기", due=0, stage="order"),
            project(3, "3일 뒤", due=3, stage="production"), project(4, "4일 뒤", due=4),
            project(5, "홀드 납기", due=1, state="hold"), project(6, "드롭 납기", due=1, state="drop"),
            project(7, "완료 납기", due=1, stage="completed"), project(8, "납기 미정"),
        ]
        self.result = home_projects.build_widgets(self.rows, TODAY)

    def test_items_are_scheduled_projects_in_due_order(self):
        """기간·홀드 거르기는 위젯 설정이라 화면에서 함. 서버는 드롭·완료·납기 미정만 뺌"""
        items = self.result["items"]
        self.assertEqual([i["name"] for i in items], ["지난 납기", "오늘 납기", "홀드 납기", "3일 뒤", "4일 뒤"])
        self.assertEqual([i["d_day_text"] for i in items], ["D+2", "D-Day", "D-1", "D-3", "D-4"])
        self.assertEqual([i["due_date"] for i in items][:2], ["2026-11-03", "2026-11-05"])
        self.assertEqual(items[2]["state"], "hold")
        self.assertEqual(self.result["today"], "2026-11-05")

    def test_counts_by_state_and_stage_by_state(self):
        self.assertEqual(self.result["total"], 8)
        self.assertEqual({c["code"]: c["count"] for c in self.result["counts"]}, {"active": 6, "hold": 1, "drop": 1})
        stages = {s["code"]: s for s in self.result["stages"]}
        self.assertEqual({k: s["count"] for k, s in stages.items()},
                         {"proposal": 0, "development": 3, "order": 1, "production": 1, "shipping": 0, "completed": 1})
        self.assertEqual(stages["development"]["by_state"], {"active": 3, "hold": 1, "drop": 1})

    def test_empty_projects(self):
        result = home_projects.build_widgets([], TODAY)
        self.assertTrue(result["ok"])
        self.assertEqual((result["total"], result["items"]), (0, []))


class _ProjectCursor:
    def __init__(self, db):
        self.db = db
        self.sql = ""

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return dict(self.db.users.get(self.params[0])) if "WHERE id = %s" in self.sql else None

    def fetchall(self):
        return list(self.db.rows)


class ProjectDB(MemoryUserDB):
    """로그인 사용자 조회 + 프로젝트 목록 조회만 흉내 냅니다."""

    def __init__(self, users, rows):
        super().__init__(users)
        self.rows = rows

    @contextmanager
    def transaction(self):
        yield _ProjectCursor(self)


class HomeRouteTest(unittest.TestCase):
    def setUp(self):
        self.kick = mock.patch.object(home_data, "kick_refresh", return_value=[])
        self.kick.start()
        self.addCleanup(self.kick.stop)
        self.addCleanup(app_module.configure_business_db, None)
        self.client = app_module.app.test_client()
        login_as(self.client, USER, app_module)
        app_module.configure_business_db(ProjectDB([USER], [project(1, "테스트 제품", due=0)]))

    def test_home_has_widgets_and_no_trade_cards(self):
        html = self.client.get("/").get_data(as_text=True)
        for widget in ("today", "projects", "week", "rates", "clock", "news", "regs"):
            self.assertIn(f'data-widget="{widget}"', html)
        self.assertIn('data-user-id="7"', html)
        for removed in ("home-trade-col", "home-trade-modal", "화장품 수출입"):
            self.assertNotIn(removed, html)

    def test_dashboard_sends_widget_choices_and_no_trade(self):
        with mock.patch.object(home_data, "get_rates", return_value={"items": [], "date": None, "error": None}) as rates:
            data = self.client.get("/api/home/data").get_json()
        rates.assert_called_once_with(limit=None)   # 통화는 위젯 설정에서 고르므로 전부 보냄
        self.assertEqual(data["news_sources"], home_data.NEWS_SOURCES)
        self.assertEqual(data["reg_countries"], home_data.REG_COUNTRIES)
        self.assertNotIn("trade", data)
        self.assertNotIn("trade_cards", data)

    def test_chatbot_rates_keep_first_six_codes(self):
        self.assertEqual(home_data.RATE_CODES[:home_data.RATE_DISPLAY], ["USD", "JPY(100)", "CNH", "EUR", "THB", "VND"])
        self.assertEqual(home_data._resolve_rate_code("GBP"), "GBP")   # 추가 통화도 환율 상세 모달 사용 가능
        self.assertEqual(home_data._resolve_rate_code("IDR"), "IDR(100)")

    def test_trade_backend_stays_for_chatbot_and_existing_urls(self):
        rules = {r.rule for r in app_module.app.url_map.iter_rules()}
        self.assertIn("/api/home/trade", rules)
        self.assertTrue(callable(home_data.get_trade_cards))
        self.assertTrue(callable(home_data.top_export_cities))

    def test_projects_api_returns_widget_data(self):
        with mock.patch.object(home_projects, "datetime") as fake:
            fake.now.return_value.date.return_value = TODAY
            data = self.client.get("/api/home/projects").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["items"][0]["name"], "테스트 제품")
        self.assertEqual(data["items"][0]["customer"], "테스트 고객사")

    def test_projects_api_reports_db_failure_as_json(self):
        with mock.patch.object(home_projects, "get_widgets", side_effect=Unavailable("업무 DB 연결 실패")):
            res = self.client.get("/api/home/projects")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json(), {"ok": False, "error": "업무 DB 연결 실패"})

    def test_projects_api_requires_login(self):
        res = app_module.app.test_client().get("/api/home/projects")
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
