"""AI 제형 모델링 서버 처리 단위 테스트 — OpenAI 는 모의 처리합니다 (실제 호출·비용 없음).

실행: python -m unittest discover -s src/04_simulation/tests -p "test_*.py"
"""
import importlib
import os
import unittest
from unittest import mock

service = importlib.import_module("src.04_simulation.service")


class IngredientRequestTest(unittest.TestCase):
    def test_valid_request_is_trimmed(self):
        self.assertEqual(service.parse_ingredient_request({"query": "  나이아신아마이드 ", "mode": "name"}),
                         ("나이아신아마이드", "name"))

    def test_control_characters_are_removed(self):
        query, _ = service.parse_ingredient_request({"query": "미백\n탄력", "mode": "keyword"})
        self.assertEqual(query, "미백 탄력")

    def test_invalid_requests(self):
        for body in (None, [], {"query": "미백"}, {"query": "미백", "mode": "other"},
                     {"query": "   ", "mode": "name"}, {"query": 3, "mode": "name"},
                     {"query": "가" * 61, "mode": "name"}):
            with self.subTest(body=body), self.assertRaises(service.BriefError) as ctx:
                service.parse_ingredient_request(body)
            self.assertEqual(ctx.exception.status, 400)


class IngredientNormalizeTest(unittest.TestCase):
    def item(self, name, **extra):
        return {"name": name, "inci": "", "summary": "요약", "properties": "특성",
                "efficacy_tags": ["미백", "미백", " ", "보습"], "caution": "주의", **extra}

    def test_name_mode_keeps_one_item_and_cleans_tags(self):
        result = service._normalize_ingredients(
            {"found": True, "items": [self.item("나이아신아마이드"), self.item("아데노신")], "note": ""}, "나이아신", "name")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["efficacy_tags"], ["미백", "보습"])
        self.assertEqual(result["mode"], "name")

    def test_keyword_mode_limits_and_dedupes(self):
        items = [self.item(f"원료{i}") for i in range(8)] + [self.item("원료0")]
        result = service._normalize_ingredients({"found": True, "items": items, "note": ""}, "미백", "keyword")
        self.assertEqual([i["name"] for i in result["items"]], [f"원료{i}" for i in range(5)])

    def test_lengths_are_capped(self):
        result = service._normalize_ingredients(
            {"found": True, "items": [self.item("가" * 300, summary="나" * 900, efficacy_tags=["다" * 80] * 10)], "note": ""},
            "q", "keyword")
        item = result["items"][0]
        self.assertEqual(len(item["name"]), 100)
        self.assertEqual(len(item["summary"]), 300)
        self.assertEqual(item["efficacy_tags"], ["다" * 30])

    def test_not_found_has_note(self):
        result = service._normalize_ingredients({"found": False, "items": [self.item("무시")], "note": ""}, "xyz", "name")
        self.assertEqual(result["items"], [])
        self.assertTrue(result["note"])


class IngredientLookupTest(unittest.TestCase):
    def test_lookup_uses_structured_output_without_file(self):
        raw = {"found": True, "items": [{"name": "아데노신", "inci": "Adenosine", "summary": "s", "properties": "p",
                                         "efficacy_tags": ["주름개선"], "caution": "c"}], "note": ""}
        with mock.patch.object(service, "_post_responses", return_value=raw) as post:
            result = service.lookup_ingredient({"query": "아데노신", "mode": "name"})
        body = post.call_args.args[0]
        self.assertEqual(body["text"]["format"]["name"], "concept_ingredient")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("input_file", str(body["input"]))
        self.assertIn("아데노신", body["input"][0]["content"][0]["text"])
        self.assertEqual(result["items"][0]["inci"], "Adenosine")

    def test_missing_key_is_503_without_network(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
                mock.patch.object(service.urllib.request, "urlopen") as urlopen, \
                self.assertRaises(service.BriefError) as ctx:
            service.lookup_ingredient({"query": "미백", "mode": "keyword"})
        self.assertEqual(ctx.exception.status, 503)
        urlopen.assert_not_called()

    def test_store_false_and_model_env(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            import json
            captured.update(json.loads(request.data))
            return FakeResponse()

        output = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"found": false, "items": [], "note": "없음"}'}]}]}
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "SIMULATION_OPENAI_MODEL": "test-model"}), \
                mock.patch.object(service.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(service.json, "load", return_value=output):
            result = service.lookup_ingredient({"query": "미백", "mode": "keyword"})
        self.assertFalse(captured["store"])
        self.assertEqual(captured["model"], "test-model")
        self.assertEqual(result, {"mode": "keyword", "query": "미백", "items": [], "note": "없음"})


class BriefStillWorksTest(unittest.TestCase):
    def test_brief_call_goes_through_shared_post(self):
        with mock.patch.object(service, "_post_responses", return_value={}) as post:
            service._call_openai("a.pdf", b"%PDF-1.4 test", ".pdf")
        body, message = post.call_args.args
        self.assertEqual(body["text"]["format"]["name"], "formulation_brief")
        self.assertEqual(body["input"][0]["content"][1]["type"], "input_file")
        self.assertIn("파일", message)


if __name__ == "__main__":
    unittest.main()
