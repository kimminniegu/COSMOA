"""고객사·프로젝트 입력 검증 단위 테스트 — DB 접속 없음.

    python -m unittest discover -s src/common/tests -p "test_projects_unit.py"
"""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common.projects_service import ProjectService, clean_due_date, clean_name, clean_search  # noqa: E402
from src.common.versions import InvalidRequest, Unavailable  # noqa: E402


class InputTest(unittest.TestCase):
    def test_name(self):
        self.assertEqual(clean_name("  A사  ", "name", "고객사명"), "A사")
        self.assertEqual(clean_name("가" * 200, "name", "고객사명"), "가" * 200)
        for bad in ("", "   ", "가" * 201, None, 1, ["A"], "A\nB", "A\tB", "A\x00"):
            with self.subTest(bad=bad), self.assertRaises(InvalidRequest) as ctx:
                clean_name(bad, "name", "고객사명")
            self.assertEqual(ctx.exception.extra["field"], "name")

    def test_due_date(self):
        self.assertIsNone(clean_due_date(None))
        self.assertEqual(clean_due_date("2026-12-31"), date(2026, 12, 31))
        for bad in ("", "2026-02-30", "2026/01/01", "26-01-01", "2026-1-1", 20260101, "2026-01-01T00:00"):
            with self.subTest(bad=bad), self.assertRaises(InvalidRequest):
                clean_due_date(bad)

    def test_search(self):
        self.assertIsNone(clean_search(None))
        self.assertIsNone(clean_search("   "))
        self.assertEqual(clean_search(" A사 "), "A사")
        with self.assertRaises(InvalidRequest):
            clean_search("가" * 101)

    def test_validation_before_db_and_no_db_is_503(self):
        service = ProjectService(None)
        with self.assertRaises(InvalidRequest):          # 입력 오류는 DB 확인 전에
            service.create_customer(actor_id=1, name=" ")
        with self.assertRaises(PermissionError):
            service.create_project(actor_id=None, customer_id=1, name="제품")
        with self.assertRaises(Unavailable):
            service.list_customers()


if __name__ == "__main__":
    unittest.main()
