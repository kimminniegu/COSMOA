"""저장 payload 검증 단위 테스트 — DB·외부 API 에 접속하지 않습니다.

    python -m unittest discover -s src/common/tests -p "test_versions_unit.py"
"""
import base64
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.common import payloads  # noqa: E402
from src.common.payloads import Limits, PayloadError, PayloadTooLarge, clean_applied_values, clean_payload  # noqa: E402

LIMITS = Limits()
FILE_B64 = base64.b64encode(os.urandom(600)).decode()
REQUISITION_EXAMPLE = Path(__file__).resolve().parents[3] / "db/schemas/requisition.v1.example.json"


def payload(**sections):
    base = {"context": {}, "inputs": {}, "outputs": {}, "meta": {}}
    base.update(sections)
    return base


class StructureTest(unittest.TestCase):
    def test_four_object_sections_required(self):
        clean_payload("margin", 1, payload(), LIMITS)
        for bad in ({"context": {}, "inputs": {}, "outputs": {}}, payload(meta=[]), payload(extra={}), [], None):
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(PayloadError):
                clean_payload("margin", 1, bad, LIMITS)

    def test_tab_and_schema_version(self):
        for tab, version in (("bogus", 1), ("margin", 2), ("margin", "1"), ("margin", True)):
            with self.subTest(tab=tab, version=version), self.assertRaises(PayloadError):
                clean_payload(tab, version, payload(), LIMITS)

    def test_validation_level_is_not_overstated(self):
        for tab in ("regulatory", "margin", "simulation"):
            v = clean_payload(tab, 1, payload(), LIMITS).validation()
            self.assertEqual((v["level"], v["fully_validated"]), ("structure", False))
        example = json.loads(REQUISITION_EXAMPLE.read_text(encoding="utf-8"))   # 개발요청서 v1 은 계약 전체 검사
        v = clean_payload("requisition", 1, example, LIMITS).validation()
        self.assertEqual((v["level"], v["fully_validated"]), ("full", True))
        with self.assertRaises(PayloadError):                                    # 빈 구조는 통과하지 않음
            clean_payload("requisition", 1, payload(), LIMITS)


class FileContentTest(unittest.TestCase):
    def test_reference_files_keep_only_allowed_keys(self):
        p = payload(meta={"reference_files": [{"name": "C:\\Users\\x\\bench.png", "size": 10, "type": "image/png",
                                               "data_url": "data:image/png;base64," + FILE_B64, "preview": "x"}]},
                    context={"source_file_name": "/tmp/upload/brief.pdf"})
        result = clean_payload("margin", 1, p, LIMITS)
        self.assertEqual(result.payload["meta"]["reference_files"], [{"name": "bench.png", "size": 10, "type": "image/png"}])
        self.assertEqual(result.payload["context"]["source_file_name"], "brief.pdf")
        self.assertIn("meta.reference_files[0].data_url", result.removed)
        self.assertNotIn("base64", str(result.payload))

    def test_excluded_fields_removed(self):
        p = payload(inputs={"version": 7, "document_id": "u-1", "created_by": 99, "product": {"version": "keep"},
                            "raw_extracted_data": {"a": 1}},
                    meta={"field_provenance": [{"field_key": "x", "source_value": "y", "translated_value": "z"}]})
        result = clean_payload("margin", 1, p, LIMITS)
        self.assertEqual(result.payload["inputs"], {"product": {"version": "keep"}})   # 칸 최상위만 제거
        self.assertEqual(result.payload["meta"]["field_provenance"], [{"field_key": "x", "source_value": "y"}])

    def test_file_body_elsewhere_is_rejected_not_silently_dropped(self):
        for value in ("data:application/pdf;base64,JVBERi0x", FILE_B64):
            with self.subTest(value=value[:20]), self.assertRaises(PayloadError) as ctx:
                clean_payload("margin", 1, payload(inputs={"note": {"attachment": value}}), LIMITS)
            self.assertEqual(ctx.exception.code, "file_content_not_allowed")
            self.assertEqual(ctx.exception.path, "inputs.note.attachment")
        # 긴 일반 문장은 허용
        clean_payload("margin", 1, payload(inputs={"memo": "가 나 다 " * 400}), LIMITS)

    def test_applied_values_rules(self):
        values, removed = clean_applied_values({"inserted_text": "a", "data_url": "x", "version": 3}, "links[0]", LIMITS)
        self.assertEqual(values, {"inserted_text": "a"})
        self.assertEqual(sorted(removed), ["links[0].data_url", "links[0].version"])
        for bad in ({}, [], {"image": "data:image/png;base64," + FILE_B64}):
            with self.subTest(bad=str(bad)[:20]), self.assertRaises(PayloadError):
                clean_applied_values(bad, "links[0]", LIMITS)


class SizeLimitTest(unittest.TestCase):
    def test_too_large_is_rejected_not_truncated(self):
        small = Limits(payload_bytes=500, applied_values_bytes=100, links_per_save=2)
        ok = payload(inputs={"t": "x" * 300})
        self.assertLessEqual(clean_payload("margin", 1, ok, small).size, 500)
        with self.assertRaises(PayloadTooLarge) as ctx:
            clean_payload("margin", 1, payload(inputs={"t": "x" * 600}), small)
        self.assertEqual((ctx.exception.limit, ctx.exception.code), (500, "payload_too_large"))
        with self.assertRaises(PayloadTooLarge):
            clean_applied_values({"t": "x" * 200}, "links[0]", small)

    def test_limits_from_env(self):
        with patch.dict(os.environ, {"VERSION_PAYLOAD_MAX_BYTES": "1000", "VERSION_APPLIED_VALUES_MAX_BYTES": "abc"}):
            limits = Limits.from_env()
        self.assertEqual((limits.payload_bytes, limits.applied_values_bytes), (1000, Limits().applied_values_bytes))


# 개발요청서 v1 계약 세부 검사는 src/05_requisition/tests/test_contract.py


class TitleTest(unittest.TestCase):
    def test_title(self):
        self.assertIsNone(payloads.clean_title("  "))
        self.assertEqual(payloads.clean_title(" 요청서 A "), "요청서 A")
        for bad in (1, "x" * 201):
            with self.subTest(bad=str(bad)[:5]), self.assertRaises(PayloadError):
                payloads.clean_title(bad)


if __name__ == "__main__":
    unittest.main()
