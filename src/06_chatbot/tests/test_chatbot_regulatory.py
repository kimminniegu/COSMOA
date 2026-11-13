"""챗봇 성분 검색·사용자 선택·규제 조회 테스트 (K-Beauty 제거 4-2단계).

실행: python -m unittest src/06_chatbot/tests/test_chatbot_regulatory.py -v

- 식약처 DB 는 임시 DB(규제 화면 테스트와 같은 픽스처)만 쓴다. 실제 수집 DB·.env 를 건드리지 않는다.
- OpenAI 는 server._openai_request 를 대본(script) 함수로 바꿔 검증한다 (네트워크 없음).
- 모든 requests 호출을 막아 K-Beauty(RapidAPI) 등 외부 호출이 0회인지 확인한다. RAPIDAPI_* 는 비운다.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parents[3]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("CHATBOT_SECRET", "test-secret")
os.environ.setdefault("CHATBOT_DB_PATH", str(Path(tempfile.mkdtemp()) / "chatbot-test.db"))

_spec = importlib.util.spec_from_file_location("chatbot_reg_fixtures", BASE_DIR / "src" / "02_regulatory" / "tests" / "test_regulatory_search.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

server_mod = importlib.import_module("src.06_chatbot.server")
tools = importlib.import_module("src.06_chatbot.tools")
server_mod.app.config["TESTING"] = True
RS = tools.regulatory_search

KEY_PATTERN = re.compile(r"mfds_(ingredients|restriction):[0-9a-f]{16}:\d+")
CONV_A = "a" * 32
CONV_B = "b" * 32


def call(name, args, cid="call_1"):
    return [{"type": "function_call", "call_id": cid, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}]


def msg(text="안내했어요."):
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


class Script:
    """가짜 OpenAI: 단계별 output 을 순서대로 돌려주고, 받은 payload 를 기록한다."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.payloads = []

    def __call__(self, payload, _key):
        self.payloads.append(copy.deepcopy(payload))
        if not self.steps:
            raise AssertionError("OpenAI 가 예상보다 많이 호출됨")
        return {"status": "completed", "output": self.steps.pop(0)}

    def outputs(self):
        """마지막 payload 의 function_call_output 들 (call_id → dict)"""
        last = self.payloads[-1]["input"]
        return {i["call_id"]: json.loads(i["output"]) for i in last if i.get("type") == "function_call_output"}


class RegBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.ingr = d / "mfds_ingredients.sqlite"
        self.rstr = d / "mfds_use_restriction.sqlite"
        F.build_ingredient_db(self.ingr, F.INGR_ITEMS)
        F.build_restriction_db(self.rstr, F.RSTR_ITEMS)
        self.env = mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(self.ingr), "MFDS_DB_PATH": str(self.rstr),
                                                "RAPIDAPI_KEY": "", "RAPIDAPI_HOST": "", "MFDS_API_KEY": "",
                                                "OPENAI_API_KEY": "sk-test", "CHATBOT_SECRET": "test-secret"})
        self.env.start()
        RS.clear_cache()
        tools.SELECTIONS.reset()
        self.http_block = mock.patch("requests.sessions.Session.request", side_effect=AssertionError("external HTTP must not be called"))
        self.http = self.http_block.start()
        self.spy = mock.patch.object(RS, "lookup_candidate", wraps=RS.lookup_candidate)
        self.lookup = self.spy.start()
        self.client = server_mod.app.test_client()

    def tearDown(self):
        self.assertEqual(self.http.call_count, 0)         # K-Beauty 등 외부 HTTP 0회
        self.spy.stop()
        self.http_block.stop()
        self.env.stop()
        RS.clear_cache()
        tools.SELECTIONS.reset()
        self.tmp.cleanup()

    def chat(self, script, text="질문", conv=CONV_A, user_id=1, selection=None):
        body = {"messages": [{"role": "user", "content": text}], "user": {"id": user_id, "name": "데모", "team": "해외영업팀"},
                "conversation_id": conv, "selection": selection}
        with mock.patch.object(server_mod, "_openai_request", script):
            res = self.client.post("/chat", json=body, headers={"X-Chatbot-Secret": "test-secret"})
        data = res.get_json()
        self.assertEqual(res.status_code, 200, data)
        return data

    def search(self, query, market=None, conv=CONV_A, user_id=1):
        s = Script(call("search_ingredient", {"query": query, "market": market}), msg("후보를 골라 주세요."))
        data = self.chat(s, "%s 규제 알려줘" % query, conv=conv, user_id=user_id)
        self.assertEqual(len(data["choices"]), 1)
        return data, s

    @staticmethod
    def pick(choice, kr_name, source):
        return next(it["index"] for it in choice["items"] if it["kr_name"] == kr_name and it["source"] == source)

    def assert_no_keys(self, *objs):
        for o in objs:
            self.assertIsNone(KEY_PATTERN.search(json.dumps(o, ensure_ascii=False)), "후보 key 가 노출됨")


class SearchAndSelectionTest(RegBase):
    def test_search_shows_choices_and_model_lookup_is_refused(self):
        """검색 직후 모델이 lookup 을 호출해도 조회되지 않는다 (사용자 선택 전)"""
        s = Script(call("search_ingredient", {"query": "Retinol", "market": "EU"}, "c1"),
                   call("lookup_ingredient_regulation", {"market": "EU"}, "c2"),
                   msg("아래 후보에서 골라 주세요."))
        data = self.chat(s, "Retinol EU 규제 알려줘")
        self.assertEqual(self.lookup.call_count, 0)
        outs = s.outputs()
        self.assertEqual(outs["c2"]["error"]["kind"], "selection_required")
        self.assertFalse(outs["c1"]["auto_confirmed"])
        self.assertEqual(data["tools_used"], ["search_ingredient", "lookup_ingredient_regulation"])
        choice = data["choices"][0]
        self.assertEqual((choice["kind"], choice["market"], choice["market_fixed"]), ("ingredient", "EU", False))
        self.assertTrue(data["choices_reset"])
        self.assert_no_keys(data, s.payloads)                      # 브라우저·모델 어디에도 key 없음

    def test_water_candidates_stay_separate(self):
        data, s = self.search("Water")
        names = [(it["kr_name"], it["source"]) for it in data["choices"][0]["items"]]
        self.assertIn(("정제수", "성분정보"), names)
        self.assertIn(("탄산수", "성분정보"), names)
        out = list(s.outputs().values())[0]
        self.assertEqual(out["exact_total"], 2)                     # 정확 일치 2건 — 자동 확정 없음
        self.assertEqual(self.lookup.call_count, 0)

    def test_same_name_other_source_not_merged_and_synonym_is_distinct(self):
        data, s = self.search("Retinol")
        items = data["choices"][0]["items"]
        retinol = [it for it in items if it["kr_name"] == "레티놀"]
        self.assertEqual(sorted(it["source"] for it in retinol), ["규제정보", "성분정보"])     # 합치지 않음
        palm = next(it for it in items if it["kr_name"] == "레티닐팔미테이트")
        self.assertEqual(palm["match_kind"], "이명")                                          # 이명 일치는 구분
        self.assertTrue(all(it["match_kind"] == "표준명·영문명" for it in retinol))
        self.assertIn("이명", palm["match"])

    def test_select_retinol_does_not_become_retinyl_palmitate(self):
        data, _ = self.search("Retinol", market="EU")
        choice = data["choices"][0]
        idx = self.pick(choice, "레티놀", "성분정보")
        s = Script(msg("레티놀 EU 결과예요."))
        data2 = self.chat(s, "[후보 선택] 레티놀", selection={"offer_id": choice["offer_id"], "index": idx, "market": "EU"})
        self.assertEqual(self.lookup.call_count, 1)
        out = list(s.outputs().values())[0]
        self.assertEqual(out["lookup_status"], "found")
        self.assertEqual(out["status_label"], "규제 정보 조회됨")
        self.assertEqual(out["selected"], {"kr_name": "레티놀", "eng_name": "Retinol", "source": "성분정보"})
        self.assertEqual(out["regulation_ingredient"]["std_name"], "레티놀")
        self.assertNotIn("레티닐팔미테이트", json.dumps(out["entries"], ensure_ascii=False))
        self.assertEqual(out["link"]["status"], "linked")
        self.assertTrue(out["ingredient_source"]["collected_at"] and out["regulation_source"]["collected_at"])
        self.assertIn("법령 개정일", out["collected_at_note"])
        self.assertEqual(data2["tools_used"], ["lookup_ingredient_regulation"])
        self.assert_no_keys(data2, s.payloads)

    def test_no_market_record_and_not_linked_are_distinct(self):
        data, _ = self.search("Mercury")
        c = data["choices"][0]
        s = Script(msg())
        self.chat(s, "선택", selection={"offer_id": c["offer_id"], "index": self.pick(c, "수은", "규제정보"), "market": "US"})
        self.assertEqual(list(s.outputs().values())[0]["status_label"], "선택 국가 기록 없음")
        data, _ = self.search("Aqua")
        c = data["choices"][0]
        s = Script(msg())
        self.chat(s, "선택", selection={"offer_id": c["offer_id"], "index": self.pick(c, "정제수", "성분정보"), "market": "KR"})
        self.assertEqual(list(s.outputs().values())[0]["status_label"], "규제 성분 연결 미확인")

    def test_link_required_needs_second_user_choice(self):
        data, _ = self.search("마이카")
        first = data["choices"][0]
        s = Script(msg("연결 후보를 골라 주세요."))
        data2 = self.chat(s, "선택", selection={"offer_id": first["offer_id"], "index": self.pick(first, "마이카", "성분정보"), "market": "EU"})
        out = list(s.outputs().values())[0]
        self.assertEqual(out["status_label"], "성분 연결 확인 필요")
        self.assertNotIn("_link_candidates_full", out)
        self.assertEqual(len(data2["choices"]), 1)
        link = data2["choices"][0]
        self.assertEqual((link["kind"], link["market"], link["market_fixed"], len(link["items"])), ("link", "EU", True, 2))
        self.assertEqual(link["origin"]["kr_name"], "마이카")
        self.assert_no_keys(data2, s.payloads)
        self.assertEqual(self.lookup.call_count, 1)                    # 연결 후보는 자동 조회하지 않음

        ci = next(it["index"] for it in link["items"] if it["eng_name"] == "CI 77019")
        s2 = Script(msg("CI 77019 EU 결과예요."))
        self.chat(s2, "선택", selection={"offer_id": link["offer_id"], "index": ci, "market": "CN"})   # 시장은 처음 조회 시장으로 고정
        out2 = list(s2.outputs().values())[0]
        self.assertEqual(out2["market"]["code"], "EU")
        self.assertEqual(out2["lookup_status"], "found")
        self.assertEqual(out2["first_selected"]["kr_name"], "마이카")          # 처음 고른 성분 보존
        self.assertEqual(out2["regulation_ingredient"]["eng_name"], "CI 77019")
        self.assertEqual(out2["link"]["status"], "direct")

        # 연결 후보 목록이 생기면서 처음 목록은 무효 → 조회 안 됨
        s3 = Script()
        data3 = self.chat(s3, "선택", selection={"offer_id": first["offer_id"], "index": 1, "market": "EU"})
        self.assertEqual(self.lookup.call_count, 2)
        self.assertIn("최신 후보 목록", data3["reply"])
        self.assertEqual(s3.payloads, [])

    def test_stale_key_clears_selection(self):
        data, _ = self.search("Water")
        c = data["choices"][0]
        sel = {"offer_id": c["offer_id"], "index": self.pick(c, "정제수", "성분정보"), "market": "KR"}
        F.build_ingredient_db(self.ingr, F.INGR_ITEMS, started_at="2026-11-10T00:00:00+00:00")   # 재수집 → 수집본 변경
        RS.clear_cache()
        s = Script(msg("다시 검색해 주세요."))
        data2 = self.chat(s, "선택", selection=sel)
        out = list(s.outputs().values())[0]
        self.assertEqual(out["error"]["kind"], "stale_key")
        self.assertEqual(out["status_label"], "후보 다시 선택 필요")
        self.assertTrue(data2["choices_reset"])
        s2 = Script()
        data3 = self.chat(s2, "선택", selection=sel)                     # 같은 목록으로 다시 조회 불가
        self.assertEqual(s2.payloads, [])
        self.assertTrue(data3["choices_reset"])
        self.assertIn("다시 검색", data3["reply"])

    def test_selection_isolated_by_conversation_and_user(self):
        data, _ = self.search("Water", conv=CONV_A, user_id=1)
        c = data["choices"][0]
        good = {"offer_id": c["offer_id"], "index": 1, "market": "KR"}
        cases = [
            dict(conv=CONV_B, user_id=1, selection=good),                                  # 다른 대화
            dict(conv=CONV_A, user_id=2, selection=good),                                  # 다른 사용자
            dict(conv=None, user_id=1, selection=good),                                    # 대화 정보 없음
            dict(conv=CONV_A, user_id=None, selection=good),                               # 사용자 정보 없음
            dict(conv=CONV_A, user_id=1, selection=dict(good, offer_id="x" * 16)),         # 임의 목록
            dict(conv=CONV_A, user_id=1, selection=dict(good, index=99)),                  # 목록에 없는 순번
            dict(conv=CONV_A, user_id=1, selection=dict(good, index=True)),
            dict(conv=CONV_A, user_id=1, selection=dict(good, market="XX")),               # 국가 미선택·잘못된 국가
            dict(conv=CONV_A, user_id=1, selection=dict(good, market=None)),
            dict(conv=CONV_A, user_id=1, selection={"key": "mfds_ingredients:0123456789abcdef:1", "market": "KR", "confirmed": True}),
        ]
        for case in cases:
            s = Script()
            self.chat(s, "선택", **case)
            self.assertEqual(s.payloads, [], case)                         # 모델 호출 없이 거절
        self.assertEqual(self.lookup.call_count, 0)
        s = Script(msg())
        self.chat(s, "선택", conv=CONV_A, user_id=1, selection=good)          # 원래 대화·사용자는 정상
        self.assertEqual(self.lookup.call_count, 1)

    def test_new_search_invalidates_previous_list(self):
        old, _ = self.search("Water")
        new, _ = self.search("Retinol")
        s = Script()
        data = self.chat(s, "선택", selection={"offer_id": old["choices"][0]["offer_id"], "index": 1, "market": "KR"})
        self.assertEqual(s.payloads, [])
        self.assertFalse(data["choices_reset"])                              # 최신 목록은 여전히 유효 — 화면의 최신 카드는 유지
        self.assertEqual(self.lookup.call_count, 0)


class ResultAndErrorTest(RegBase):
    def test_db_error_and_no_result_are_distinct(self):
        out = json.loads(tools.execute("search_ingredient", {"query": "없는성분zz", "market": None}))
        self.assertEqual(out["status"], "no_result")
        self.assertNotIn("error", out)
        with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(Path(self.tmp.name) / "none.sqlite")}):
            RS.clear_cache()
            out = json.loads(tools.execute("search_ingredient", {"query": "Water", "market": None}))
        self.assertEqual(out["error"]["kind"], "db_missing")
        self.assertIn("출처 이용 불가", out["error"]["category"])
        self.assertIn("검색 결과 없음", out["hint"])
        bad = Path(self.tmp.name) / "incomplete.sqlite"
        F.build_restriction_db(bad, F.RSTR_ITEMS, status="running")
        with mock.patch.dict(os.environ, {"MFDS_DB_PATH": str(bad)}):
            RS.clear_cache()
            out = json.loads(tools.execute("search_ingredient", {"query": "Water", "market": None}))
        self.assertEqual(out["error"]["kind"], "db_incomplete")

    def test_truncated_search_reports_totals(self):
        out = json.loads(tools.execute("search_ingredient", {"query": "에", "market": None}))
        self.assertEqual(out["error"]["kind"], "validation")
        out = json.loads(tools.execute("search_ingredient", {"query": "추출물", "market": None}))
        self.assertIn("total", out)
        self.assertEqual(out["returned"], len(out["candidates"]))
        self.assertEqual(out["truncated"], out["total"] > out["returned"])

    def test_long_lookup_result_is_valid_json_and_marked_partial(self):
        long_text = "* 【Restrictions】 " + "가" * 1500
        items = [F.rstr("테스트성분", "Test Ingredient", "EU", "한도", limit="%d %s" % (i, long_text)) for i in range(15)]
        F.build_restriction_db(self.rstr, items, started_at="2026-11-10T00:00:00+00:00")
        RS.clear_cache()
        data, _ = self.search("Test Ingredient")
        c = data["choices"][0]
        s = Script(msg())
        self.chat(s, "선택", selection={"offer_id": c["offer_id"], "index": 1, "market": "EU"})
        raw = [i["output"] for i in s.payloads[-1]["input"] if i.get("type") == "function_call_output"][0]
        self.assertLessEqual(len(raw), tools.MAX_OUTPUT_CHARS)
        out = json.loads(raw)                                                  # 유효한 JSON
        self.assertEqual((out["entries_total"], out["entries_shown"]), (15, 10))
        self.assertIn("일부 조건만", out["entries_note"])
        self.assertIn("_output_truncated", out)
        self.assertTrue(out["_output_truncated"]["shortened"] or out["_output_truncated"]["dropped"])

    def test_fit_output_counts_match_what_was_sent(self):
        """4-3단계 회귀: 목록을 줄이면 표시 건수를 실제 전달 건수에 맞추고, 출처·상태·안내 문구는 줄이지 않는다"""
        cands = [{"index": i, "kr_name": "K" * 300, "eng_name": "E" * 300, "source": "성분정보", "match": "M" * 300} for i in range(1, 11)]
        search = {"status": "candidates", "total": 40, "returned": 10, "truncated": True, "candidates": cands,
                  "selection": tools.SELECTION_NOTE, "collected_at_note": tools.COLLECTED_NOTE}
        out = json.loads(tools.fit_output(search, 2500))
        self.assertEqual(out["candidates_sent"], len(out["candidates"]))
        self.assertLess(out["candidates_sent"], 10)
        self.assertEqual((out["returned"], out["total"]), (10, 40))                     # 화면 표시·전체 건수는 그대로 구분
        self.assertIn("%d건만 전달" % out["candidates_sent"], out["candidates_note"])
        self.assertEqual(out["selection"], tools.SELECTION_NOTE)                       # 안내 문구는 줄이지 않음
        self.assertEqual(out["collected_at_note"], tools.COLLECTED_NOTE)

        entries = [{"country": "EU", "regulate_type": "한도", "notice_ingr_name": "N" * 900, "limit_condition": "L" * 2500, "proviso": "P" * 900}
                   for _ in range(10)]
        res = {"lookup_status": "found", "status_label": "규제 정보 조회됨", "entries_total": 14, "entries_shown": 10, "entries": entries,
               "entries_note": "규제 조건 14건 중 10건만 전달했어요.", "reference_note": tools.REFERENCE_NOTE, "collected_at_note": tools.COLLECTED_NOTE,
               "regulation_source": {"label": "식약처 화장품 사용제한 원료정보 (수집 DB)", "collected_at": "2026-11-09T08:55:53+00:00"}}
        for limit in (7000, 3000, 1800):
            text = tools.fit_output(res, limit)
            self.assertLessEqual(len(text), limit, limit)
            o = json.loads(text)
            self.assertEqual(o["entries_shown"], len(o["entries"]), limit)            # 표시 건수 = 실제 전달 건수
            self.assertEqual(o["entries_total"], 14)
            self.assertIn("%d건만 전달" % len(o["entries"]), o["entries_note"], limit)
            self.assertIn("원문은 길어서 줄였어요", o["entries_note"], limit)
            for k in ("status_label", "lookup_status", "reference_note", "collected_at_note", "regulation_source"):
                self.assertEqual(o[k], res[k], (limit, k))
        self.assertLess(len(json.loads(tools.fit_output(res, 1800))["entries"]), 10)    # 이 크기에서는 항목도 줄어든다

    def test_fit_output_never_breaks_json(self):
        big = {"items": [{"t": "x" * 5000, "n": i} for i in range(30)], "note": "y" * 9000}
        text = tools.fit_output(big, 3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("_output_truncated", json.loads(text))
        self.assertEqual(json.loads(tools.fit_output({"a": 1}, 3000)), {"a": 1})   # 짧으면 그대로


class SourceStatusTest(RegBase):
    def test_status_uses_real_db_state_and_works_without_rapidapi(self):
        st = server_mod.data_sources_status()
        self.assertTrue(st["mfds_ingredient_db"] and st["mfds_restriction_db"])
        self.assertNotIn("rapidapi", st)
        prompt = server_mod._system_prompt(None)
        self.assertIn("사용 가능", prompt)
        self.assertNotIn("K-Beauty", prompt)
        with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(Path(self.tmp.name) / "none.sqlite")}):
            st = server_mod.data_sources_status()
            prompt = server_mod._system_prompt(None)
        self.assertFalse(st["mfds_ingredient_db"])
        self.assertIn("성분 DB", prompt)
        self.assertFalse((Path(self.tmp.name) / "none.sqlite").exists())         # 상태 확인이 DB 를 만들거나 수집하지 않음


class RelayAndWidgetTest(unittest.TestCase):
    def test_relay_passes_session_user_id_conversation_and_selection(self):
        app_mod = importlib.import_module("app")
        app_mod.app.config["TESTING"] = True
        client = app_mod.app.test_client()
        from src.common.testing import login_as
        login_as(client, {"id": 7, "email": "t@example.invalid", "name": "t", "team": "B"}, app_mod)
        fake = mock.Mock()
        fake.json.return_value = {"ok": True, "reply": "ok", "choices": [], "choices_reset": False}
        fake.status_code = 200
        with mock.patch.dict(os.environ, {"CHATBOT_URL": "http://chatbot.invalid", "CHATBOT_SECRET": "s"}), \
             mock.patch.object(app_mod._chatbot_requests, "post", return_value=fake) as post:
            res = client.post("/api/chatbot/message", json={
                "messages": [{"role": "user", "content": "hi"}], "conversation_id": CONV_A,
                "selection": {"offer_id": "o" * 16, "index": 2, "market": "EU", "key": "forged"},
                "user": {"id": 999}})                                               # 브라우저가 보낸 user 는 무시
        self.assertEqual(res.status_code, 200)
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["user"]["id"], 7)
        self.assertEqual(sent["conversation_id"], CONV_A)
        self.assertEqual(sent["selection"], {"offer_id": "o" * 16, "index": 2, "market": "EU"})   # key 등 다른 값은 전달하지 않음

    def test_widget_sends_selection_and_renders_without_keys(self):
        js = (BASE_DIR / "src" / "06_chatbot" / "chatbot.js").read_text(encoding="utf-8")
        for marker in ("conversation_id", "selection", "offer_id", "choiceCard", "newConversationId", "markChoicesStale"):
            self.assertIn(marker, js)
        self.assertNotRegex(js, r"\b(it|c|item|cand|candidate)\.key\b|\[\"key\"\]")      # 후보 key 를 다루지 않음 (e.key 키보드 이벤트는 별개)
        css = (BASE_DIR / "src" / "06_chatbot" / "chatbot.css").read_text(encoding="utf-8")
        self.assertIn(".chatbot__choice-btn", css)


@unittest.skipUnless(shutil.which("node"), "Node.js 가 있을 때만")
class WidgetDomTest(unittest.TestCase):
    """chatbot.js 를 Node 의 최소 DOM 대역(widget_dom_harness.js)으로 실제 실행 — 브라우저 확인을 대신하지 않음"""

    def test_choice_card_flow(self):
        markets = [{"code": m, "label": tools.MARKET_LABELS[m]} for m in tools.MARKETS]
        offer = {"offer_id": "offerA" * 3, "kind": "ingredient", "query": "Retinol", "market": None, "market_fixed": False, "markets": markets,
                 "origin": None, "total": 4, "returned": 4, "truncated": False, "exact_total": 3,
                 "items": [{"index": 1, "kr_name": "레티놀", "eng_name": "Retinol", "source": "성분정보", "match": "영문명 정확 일치", "match_kind": "표준명·영문명"},
                           {"index": 2, "kr_name": "레티놀", "eng_name": "Retinol", "source": "규제정보", "match": "영문명 정확 일치", "match_kind": "표준명·영문명"}]}
        link = {"offer_id": "offerB" * 3, "kind": "link", "query": None, "market": "EU", "market_fixed": True, "markets": markets,
                "origin": {"kr_name": "마이카", "eng_name": "Mica", "source": "성분정보", "link_conflict": "이름이 정확히 일치하는 규제 성분이 2개예요."},
                "total": None, "returned": None, "truncated": None, "exact_total": None,
                "items": [{"index": 1, "kr_name": "마이카", "eng_name": "Mica", "source": "규제정보", "match": "연결 근거: 한글명 = 규제 표준명", "match_kind": None},
                          {"index": 2, "kr_name": "마이카", "eng_name": "CI 77019", "source": "규제정보", "match": "연결 근거: 한글명 = 규제 표준명", "match_kind": None}]}
        responses = [
            {"ok": True, "reply": "후보를 골라 주세요.", "choices": [offer], "choices_reset": True},
            {"ok": True, "reply": "연결 후보를 골라 주세요.", "choices": [link], "choices_reset": True},
            {"ok": True, "reply": "EU 결과예요.", "choices": [], "choices_reset": False},
            {"ok": True, "reply": "안녕하세요.", "choices": [], "choices_reset": False},
        ]
        harness = Path(__file__).with_name("widget_dom_harness.js")
        js = BASE_DIR / "src" / "06_chatbot" / "chatbot.js"
        proc = subprocess.run(["node", str(harness), str(js), json.dumps(responses, ensure_ascii=False)],
                              capture_output=True, timeout=60, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        obs = json.loads(proc.stdout)
        self.assertNotIn("error", obs, obs.get("error"))
        self.assertEqual((obs["after_search"]["requests"], obs["after_search"]["cards"], obs["after_search"]["buttons"]), (1, 1, 2))
        self.assertIn("성분정보", obs["after_search"]["text"])
        self.assertIn("규제정보", obs["after_search"]["text"])
        self.assertEqual(obs["no_market"], {"requests": 1, "hint_visible": True})          # 국가 없이는 요청하지 않음
        req = obs["selection_request"]
        self.assertEqual(req["selection"], {"offer_id": offer["offer_id"], "index": 1, "market": "EU"})
        self.assertTrue(all(set(m) == {"role", "content"} for m in req["messages"]))        # 카드 정보는 서버로 보내지 않음
        self.assertEqual(obs["after_link"], {"cards": 2, "stale": [True, False], "old_disabled": True, "new_enabled": True, "link_has_select": False})
        self.assertEqual(obs["stale_click_requests"], 2)                                    # 이전 카드 클릭은 요청하지 않음
        self.assertEqual(obs["link_request"]["selection"], {"offer_id": link["offer_id"], "index": 2, "market": "EU"})
        self.assertTrue(obs["conv_changed"])                                                # 대화 지우기 → 새 대화 id
        self.assertEqual(obs["cards_after_clear"], 0)
        self.assertFalse(obs["stored_has_key"])


if __name__ == "__main__":
    unittest.main()
