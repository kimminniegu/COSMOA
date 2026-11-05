"""개발요청서 저장 계약 v1 테스트 — DB·외부 API 에 접속하지 않습니다.

    python -m unittest discover -s src/05_requisition/tests -p "test_contract.py"

- 서버 검증(contract.py) 규칙: 필수 키·필수값·빈 값·목록·자료형·허용값·알 수 없는 키
- 문서 예시(docs/data_contract.md 4-2) = db/schemas/requisition.v1.example.json = 서버 검증 통과
- 화면 payload 생성(requisition_payload.js, Node.js 로 실행) → 서버 검증 통과, 파일 본문·원문 보존 데이터 제외
"""
import base64
import copy
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.common.payloads import Limits, PayloadError, clean_payload  # noqa: E402

schema = importlib.import_module("src.05_requisition.schema")
service = importlib.import_module("src.05_requisition.service")
EXAMPLE_FILE = ROOT / "db/schemas/requisition.v1.example.json"
EXAMPLE = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))
LIMITS = Limits()
FILE_B64 = base64.b64encode(os.urandom(900)).decode()


def validate(payload):
    return clean_payload("requisition", 1, payload, LIMITS)


def changed(path, value=None, *, delete=False):
    payload = copy.deepcopy(EXAMPLE)
    keys = re.findall(r"[^.\[\]]+", path)
    target = payload
    for key in keys[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]
    last = int(keys[-1]) if keys[-1].isdigit() else keys[-1]
    if delete:
        del target[last]
    else:
        target[last] = value
    return payload


class ContractTest(unittest.TestCase):
    def assertRejected(self, payload, code, path=None):
        with self.assertRaises(PayloadError) as ctx:
            validate(payload)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        if path:
            self.assertEqual(ctx.exception.path, path)

    def test_example_is_fully_validated(self):
        result = validate(EXAMPLE)
        v = result.validation()
        self.assertEqual((v["schema"], v["level"], v["fully_validated"], v["removed_fields"]), ("requisition.v1", "full", True, []))
        self.assertEqual(result.payload, EXAMPLE)                      # 통과한 값은 바꾸지 않음

    def test_docs_example_matches_contract_file(self):
        text = (ROOT / "docs/data_contract.md").read_text(encoding="utf-8")
        section = text[text.index("### 4-2."):text.index("### 4-3.")]
        block = re.search(r"```json\n(.*?)\n```", section, re.S).group(1)
        self.assertEqual(json.loads(block), EXAMPLE)

    def test_every_key_is_required(self):
        for path in ["context.project_id", "context.source_file_name", "inputs.target_prices", "inputs.rnd_check_requests",
                     "inputs.product_development.spf", "inputs.product_development.viscosity_level", "inputs.ingredients.concept",
                     "inputs.quality.additional_notes", "meta.reference_files", "meta.field_provenance",
                     "inputs.ingredients.concept.0.must_contain", "inputs.target_prices.0.currency"]:
            with self.subTest(path=path):
                self.assertRejected(changed(path, delete=True), "missing_field")
        self.assertRejected(changed("inputs.ingredients", {"concept": []}), "missing_field", "inputs.ingredients.other_notes")

    def test_unknown_keys_rejected(self):
        for path in ("inputs.customer", "inputs.target_price_tier", "inputs.product_development.color", "context.recipients",
                     "meta.notes", "outputs.review_status", "inputs.ingredients.necessary", "inputs.ingredients.concept.0.note",
                     "inputs.target_prices.0.tier", "meta.legacy_fields.product_type"):
            with self.subTest(path=path):
                self.assertRejected(changed(path, "x"), "unknown_field")
        provenance = changed("meta.field_provenance.0.field_key", "target_price_tier")
        self.assertRejected(provenance, "unknown_field", "meta.field_provenance[0].field_key")

    def test_types_and_allowed_values(self):
        cases = [
            ("inputs.product_name", 1, "invalid_payload"), ("inputs.export_countries", "미국", "invalid_payload"),
            ("inputs.export_countries", ["미국", " "], "invalid_payload"), ("inputs.export_countries", ["미국", "미국 "], "duplicate_value"),
            ("inputs.product_type", "마스크", "invalid_value"), ("inputs.request_source", "기타", "invalid_value"),
            ("inputs.product_type_detail", "에센스", "invalid_value"), ("inputs.product_development.application_type", "Spray", "invalid_value"),
            ("inputs.product_development.viscosity_level", "중간", "invalid_value"),     # 선택값 미정 — 빈 값만
            ("inputs.product_development.spf", "S" * 51, "invalid_payload"), ("inputs.product_name", "가" * 10001, "invalid_payload"),
            ("context.customer_id", "7", "invalid_value"), ("context.project_id", 0, "invalid_value"), ("context.project_id", True, "invalid_value"),
            ("context.creation_method", "copy", "invalid_value"), ("context.target_language", "xx", "invalid_value"),
            ("meta.field_provenance.0.review_status", "ok", "invalid_value"), ("meta.field_provenance.0.input_source", "ai", "invalid_value"),
            ("meta.legacy_fields.target_price_tier", "premium", "invalid_value"), ("outputs", {"x": 1}, "unknown_field"),
        ]
        for path, value, code in cases:
            with self.subTest(path=path, value=str(value)[:10]):
                self.assertRejected(changed(path, value), code)

    def test_linked_values(self):
        self.assertRejected(changed("inputs.product_type", "립"), "invalid_value", "inputs.product_type_detail")   # 세부 유형은 스킨케어만
        lip = changed("inputs.product_type", "립")
        lip["inputs"]["product_type_detail"] = ""
        validate(lip)
        other = changed("inputs.product_type_custom", "패치")
        self.assertRejected(other, "invalid_value", "inputs.product_type_custom")
        other["inputs"].update(product_type="기타", product_type_detail="")
        validate(other)
        other["inputs"]["product_type_custom"] = " "
        self.assertRejected(other, "required_field", "inputs.product_type_custom")

    def test_required_values(self):
        for path, empty in (("inputs.product_name", " "), ("inputs.request_source", ""), ("inputs.sample_request_type", ""),
                            ("inputs.product_type", ""), ("inputs.export_countries", []), ("inputs.quality.tests", [])):
            payload = changed(path, empty)
            if path == "inputs.product_type":
                payload["inputs"]["product_type_detail"] = ""
            with self.subTest(path=path):
                self.assertRejected(payload, "required_field", path)
        # 선택 항목은 비워도 됨
        optional = copy.deepcopy(EXAMPLE)
        optional["inputs"].update(target_prices=[], rnd_check_requests="", buyer_prohibited_ingredients=[])
        optional["inputs"]["ingredients"]["concept"] = []
        optional["inputs"]["product_development"].update(spf="", pa="", container_reference="", viscosity="")
        optional["meta"] = {"field_provenance": [], "reference_files": []}            # legacy_fields 는 선택
        self.assertTrue(validate(optional).validation()["fully_validated"])

    def test_target_prices(self):
        validate(changed("inputs.target_prices", [{"amount": 1.25, "currency": "USD"}, {"amount": 1300, "currency": "KRW"}]))
        for bad in ([{"amount": 0, "currency": "KRW"}], [{"amount": -1, "currency": "KRW"}], [{"amount": "1300", "currency": "KRW"}],
                    [{"amount": True, "currency": "KRW"}], [{"amount": 1300, "currency": "krw"}], [{"amount": 1300, "currency": "WON"[:2]}],
                    [{"amount": 1300, "currency": "KRW"}] * 2, [{"amount": i + 1, "currency": "KRW"} for i in range(11)],
                    "mid", [{"amount": 1e13, "currency": "KRW"}]):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(PayloadError):
                validate(changed("inputs.target_prices", bad))

    def test_concept_ingredients(self):
        item = {"name": "Retinol", "kind": "ideal", "must_contain": False, "efficacy_tags": ["주름"]}
        validate(changed("inputs.ingredients.concept", [item]))
        for bad in ([dict(item, kind="banned")], [dict(item, must_contain="yes")], [dict(item, name=" ")],
                    [dict(item, efficacy_tags="주름")], [dict(item, efficacy_tags=["a"] * 2)], [dict(item, efficacy_tags=[str(i) for i in range(11)])],
                    [item, dict(item, name="retinol ", kind="necessary")], ["Retinol"]):
            with self.subTest(bad=str(bad)[:50]), self.assertRaises(PayloadError):
                validate(changed("inputs.ingredients.concept", bad))

    def test_file_bodies_and_excluded_fields_never_saved(self):
        payload = copy.deepcopy(EXAMPLE)
        payload["meta"]["reference_files"][0]["data_url"] = "data:image/png;base64," + FILE_B64
        payload["meta"]["field_provenance"][0]["translated_value"] = "가벼운 젤"
        payload["inputs"]["raw_extracted_data"] = {"commercial_data": [{"source_value": "SECRET_MOQ"}]}
        payload["inputs"].update(version=3, document_id="u-1")
        payload["meta"]["raw_extracted_data"] = {}
        result = validate(payload)
        self.assertTrue(result.validation()["fully_validated"])
        self.assertEqual(result.payload, EXAMPLE)
        self.assertEqual(sorted(result.removed), sorted([
            "inputs.raw_extracted_data", "inputs.version", "inputs.document_id", "meta.raw_extracted_data",
            "meta.reference_files[0].data_url", "meta.field_provenance[0].translated_value"]))
        hidden = changed("inputs.basic_notes", "data:image/png;base64," + FILE_B64)   # 다른 위치의 파일 본문은 거부
        self.assertRejected(hidden, "file_content_not_allowed", "inputs.basic_notes")


@unittest.skipUnless(shutil.which("node"), "Node.js 없음 — 화면 payload 생성 테스트 생략")
class ScreenPayloadTest(unittest.TestCase):
    """화면 문서(직접 작성·자동변환 후 편집) → requisition_payload.js → 서버 검증."""
    PROJECT = {"id": 12, "name": "비타민 세럼", "customer": {"id": 7, "name": "A사"}}

    def build(self, document, project=PROJECT):
        script = ("const b = require(process.argv[1]); const [doc, project, options] = JSON.parse(process.argv[2]);"
                  "console.log(JSON.stringify(b.build(doc, project, options)));")
        run = subprocess.run(["node", "-e", script, str(ROOT / "src/05_requisition/requisition_payload.js"),
                              json.dumps([document, project, schema.page_options()], ensure_ascii=False)],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def converted_and_edited(self):
        """자동변환 결과(고정 응답)를 사용자가 필수값을 채워 완성한 화면 문서."""
        raw = {key: "" for key in service.STRING_FIELDS}
        raw.update({key: [] for key in service.ARRAY_FIELDS})
        raw.update(customer="Glowtree Inc.", product_name="Vitamin C Serum", product_type="스킨케어", product_type_detail="세럼",
                   target_price_tier="mid", export_countries=["미국"], source_language="en", is_development_request=True,
                   ingredients={"necessary": ["Ascorbic Acid"], "ideal": ["Niacinamide"], "other_notes": ""},
                   product_development={"spf": "SPF50+"},
                   raw_extracted_data={"commercial_data": [{"field_key": "Target Cost", "source_value": "USD 1.10", "source_page": "1"}]})
        raw["evidence"] = [{"field_key": key, "source_value": str(service.get_value(raw, key)), "source_page": "1", "needs_review": False}
                           for key in service.DATA_FIELDS if service.get_value(raw, key)]
        doc = service.normalize_result(raw, "brief.pdf", "A사", "auto", "ko", [])
        # 화면에서 하는 일: 고객사는 연결 프로젝트 기준, 필수값 입력, 목표 가격대 직접 입력, 참고자료(본문은 페이지 메모리에만)
        doc.update(customer="A사", request_source="고객사 요청", sample_request_type="신규 샘플", creation_method="auto_edited",
                   target_prices=[{"amount": 1300, "currency": "KRW"}, {"amount": 1500, "currency": "KRW"}])
        doc["quality"]["tests"] = ["안정도 시험"]
        doc["ingredients"]["concept"][0].update(must_contain=True, efficacy_tags=["미백"])
        doc["reference_files"] = [{"name": "bench.png", "size": 900, "type": "image/png", "data_url": "data:image/png;base64," + FILE_B64}]
        doc["field_provenance"].append({"field_key": "reference_files", "source_value": "", "input_source": "user_edited",
                                        "review_status": "user_edited", "user_value": []})
        return doc

    def test_converted_document_payload_passes_server_validation(self):
        built = self.build(self.converted_and_edited())
        self.assertEqual(built["schema_version"], 1)
        payload = built["payload"]
        text = json.dumps(payload, ensure_ascii=False)
        for leaked in ("data_url", "base64", "raw_extracted_data", "USD 1.10", "translated_value", "document_id", "recipients"):
            self.assertNotIn(leaked, text)
        result = validate(payload)
        self.assertEqual((result.validation()["fully_validated"], result.removed), (True, []))   # 서버가 지울 것이 없음
        self.assertEqual(payload["context"], {"customer_id": 7, "customer_name": "A사", "project_id": 12, "project_name": "비타민 세럼",
                                              "creation_method": "auto_edited", "source_language": "en", "target_language": "ko",
                                              "source_file_name": "brief.pdf"})
        self.assertEqual(payload["meta"]["legacy_fields"], {"target_price_tier": "mid"})
        self.assertEqual(payload["meta"]["reference_files"], [{"name": "bench.png", "size": 900, "type": "image/png"}])
        self.assertNotIn("reference_files", {p["field_key"] for p in payload["meta"]["field_provenance"]})
        customer = next(p for p in payload["meta"]["field_provenance"] if p["field_key"] == "customer")
        self.assertEqual(customer["source_value"], "Glowtree Inc.")                  # 원문 고객사명은 출처에만
        self.assertEqual(payload["inputs"]["ingredients"]["concept"][1],
                         {"name": "Niacinamide", "kind": "ideal", "must_contain": None, "efficacy_tags": []})
        self.assertEqual(set(payload["inputs"]) | {"customer"}, set(schema.blank_inputs()) | {"customer"})

    def test_manual_blank_document_payload(self):
        doc = schema.blank_inputs()
        doc.update(customer="A사", creation_method="manual", source_language="", target_language="ko", source_file="",
                   review_status="needs_review", field_provenance=[], raw_extracted_data={}, reference_files=[], legacy={},
                   request_source="자사기획", product_name="립 틴트", sample_request_type="신규 샘플", product_type="립",
                   export_countries=["일본"])
        doc["quality"]["tests"] = ["안정도 시험"]
        payload = self.build(doc)["payload"]
        self.assertNotIn("legacy_fields", payload["meta"])
        self.assertTrue(validate(payload).validation()["fully_validated"])

    def test_unlinked_document_cannot_build_payload(self):
        doc = self.converted_and_edited()
        for project in (None, {"id": 12, "name": "x"}):
            with self.subTest(project=project):
                self.assertIn("프로젝트에 연결", self.build(doc, project)["error"])


if __name__ == "__main__":
    unittest.main()
