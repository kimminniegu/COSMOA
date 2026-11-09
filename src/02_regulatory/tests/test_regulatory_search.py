"""식약처 성분 DB + 규제 DB 통합 검색 모듈 테스트 (담당자 B). 임시 DB 만 쓴다 — 실제 수집 DB·외부 API 사용 안 함.

실행 (프로젝트 루트):  python -m unittest discover -s src/02_regulatory/tests -p "test_regulatory_search.py" -v
"""

import hashlib
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("regulatory_search", "regulatory_search.py")
ING = _load("mfds_ingredients_t", "mfds_ingredients.py")
RST = _load("mfds_use_restriction_t", "mfds_use_restriction.py")


def ingr(kor, eng=None, cas=None, syn=None, origin=None):
    return {"INGR_KOR_NAME": kor, "INGR_ENG_NAME": eng, "CAS_NO": cas, "ORIGIN_MAJOR_KOR_NAME": origin, "INGR_SYNONYM": syn}


def rstr(std, eng, country, rtype="금지", cas=None, syn=None, notice=None, limit=None):
    return {"REGULATE_TYPE": rtype, "INGR_STD_NAME": std, "INGR_ENG_NAME": eng, "CAS_NO": cas, "INGR_SYNONYM": syn,
            "COUNTRY_NAME": country, "NOTICE_INGR_NAME": notice, "PROVIS_ATRCL": None, "LIMIT_COND": limit}


INGR_ITEMS = [
    ingr("정제수", "Water,Aqua"),
    ingr("탄산수", "Water"),
    ingr("글리세린", "Glycerin"),
    ingr("레티놀", "Retinol"),
    ingr("하이드로제네이티드레티놀", "Hydrogenated Retinol"),
    ingr("녹차추출물", "Camellia Sinensis Leaf Extract"),
    ingr("홍차추출물", "Camellia Sinensis Leaf Extract"),
    ingr("1,2-헥산다이올", "1,2-Hexanediol", cas="6920-22-5"),
    ingr("글리세린/프탈릭애씨드코폴리머", "Glycerin/Phthalic Acid Copolymer"),
    ingr("에틸헥실글리세린", "Ethylhexylglycerin", syn="옥톡시글리세린"),
    ingr("리치추출물", "Litchi Chinensis Fruit Extract", syn="리치열매추출물,여지열매추출물"),
    ingr("류신", "Leucine", cas="328-39-2(DL-)\r,61-90-5(L-)"),
    ingr("  페녹시에탄올 ", "Phenoxyethanol"),
    ingr("마이카", "Mica,CI 77019"),                       # 규제 DB 에서 같은 표준명·다른 영문명 2개와 이름 일치 → 연결 확인 필요
    ingr("니코틴", "Nicotine", cas="54-11-6"),              # 이름은 같지만 CAS 가 규제 DB 와 겹치지 않음 → 충돌
]
RSTR_ITEMS = [
    rstr("레티놀", "Retinol", "EU", "한도", limit="0.3%"),
    rstr("레티놀", "retinol ", "캐나다", "한도"),
    rstr("페녹시에탄올", "Phenoxyethanol", "한국", "한도", cas="122-99-6", limit="1%"),
    rstr("페녹시에탄올", "Phenoxyethanol", "EU", "한도", cas="122-99-6"),
    rstr("페녹시에탄올", "Phenoxyethanol", "중국", "한도", cas="122-99-6"),
    rstr("수은", "Mercury", "한국", cas="7439-97-6"),
    rstr("수은", "Mercury", "EU", cas="7439-97-6"),
    rstr("포름알데하이드 및 p-폼알데하이드", "Formaldehyde and p-Formaldehyde", "한국", cas="50-00-0, 30525-89-4", notice="Formaldehyde [1]; Paraformaldehyde [2]"),
    rstr("레티닐팔미테이트", "Retinyl Palmitate", "EU", "한도", syn="Retinol,Vitamin A Palmitate"),
    rstr("페녹시에탄올", "Phenoxyethanol", "한국", "한도", cas="122-99-6", limit="사용 후 씻어내는 제품 1%"),   # 같은 국가의 두 번째 조건
    rstr("마이카", "Mica", "중국", "한도"),
    rstr("마이카", "CI 77019", "EU", "한도"),
    rstr("니코틴", "Nicotine", "한국", cas="54-11-5"),
    rstr("글리세린", "Glycerol", "캐나다", "한도"),          # 한글명만 같고 영문명이 다른 규제 성분 → 연결 충돌
]


def build_ingredient_db(path, items, page_size=5, started_at="2026-11-09T09:13:19+00:00"):
    conn = ING.open_db(path)
    with conn:
        cur = conn.execute("INSERT INTO runs (started_at, status, source_url, source_page, page_size, total_count_first, total_count_last) VALUES (?,?,?,?,?,?,?)",
                           (started_at, "running", ING.public_url(), ING.SOURCE_PAGE, page_size, len(items), len(items)))
    rid = cur.lastrowid
    for p in range(0, len(items), page_size):
        ING.save_page(conn, rid, p // page_size + 1, {"items": items[p:p + page_size], "total_count": len(items), "result_code": "00", "result_msg": "OK", "http_status": 200}, page_size, started_at)
    ING.finish_run(conn, rid, "completed", 0)
    conn.close()
    return rid


def build_restriction_db(path, items, page_size=5, status="completed", started_at="2026-11-09T08:52:13+00:00"):
    conn = RST.open_db(path)
    with conn:
        cur = conn.execute("INSERT INTO runs (started_at, status, source_url, source_page, page_size, total_count_first, total_count_last) VALUES (?,?,?,?,?,?,?)",
                           (started_at, "running", RST.public_url(), RST.SOURCE_PAGE, page_size, len(items), len(items)))
    rid = cur.lastrowid
    for p in range(0, len(items), page_size):
        RST.save_page(conn, rid, p // page_size + 1, {"items": items[p:p + page_size], "total_count": len(items), "result_code": "00", "result_msg": "OK", "http_status": 200}, page_size, started_at)
    RST.finish_run(conn, rid, status, 0)
    conn.close()
    return rid


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.ingr_path = d / "mfds_ingredients.sqlite"
        self.rstr_path = d / "mfds_use_restriction.sqlite"
        build_ingredient_db(self.ingr_path, INGR_ITEMS)
        build_restriction_db(self.rstr_path, RSTR_ITEMS)
        self.env = mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(self.ingr_path), "MFDS_DB_PATH": str(self.rstr_path)})
        self.env.start()
        S.clear_cache()

    def tearDown(self):
        self.env.stop()
        S.clear_cache()
        self.tmp.cleanup()

    def exact(self, r, source=None):
        return [c for c in r["candidates"] if c["match"] == "exact" and (source is None or c["source"] == source)]


class SearchTest(Base):
    def test_kr_and_eng_find_same_candidate(self):
        a = self.exact(S.search("글리세린"), S.SRC_INGR)
        b = self.exact(S.search("glycerin"), S.SRC_INGR)
        self.assertEqual([c["key"] for c in a], [c["key"] for c in b])
        self.assertEqual(a[0]["matched"][0]["field"], "INGR_KOR_NAME")
        self.assertEqual(b[0]["matched"][0]["field"], "INGR_ENG_NAME")

    def test_water_keeps_two_candidates_and_aqua_finds_purified_water(self):
        r = S.search("Water")
        ex = self.exact(r, S.SRC_INGR)
        self.assertEqual(sorted(c["kr_name"] for c in ex), ["정제수", "탄산수"])
        self.assertEqual(r["counts"][S.SRC_INGR]["exact"], 2)
        via = {c["kr_name"]: c["matched"][0]["via"] for c in ex}
        self.assertEqual(via, {"정제수": "item", "탄산수": "whole"})
        self.assertEqual(ex[0]["eng_name"] if ex[0]["kr_name"] == "정제수" else ex[1]["eng_name"], "Water,Aqua")   # 원문 보존
        aq = self.exact(S.search("aqua"))
        self.assertEqual([c["kr_name"] for c in aq], ["정제수"])

    def test_both_sources_kept_separate(self):
        r = S.search("레티놀")
        ex = self.exact(r)
        self.assertEqual([c["source"] for c in ex], [S.SRC_INGR, S.SRC_RSTR])      # 성분 DB 먼저, 합치지 않음
        self.assertNotEqual(ex[0]["key"], ex[1]["key"])
        self.assertEqual(r["counts"][S.SRC_INGR]["exact"], 1)
        self.assertEqual(r["counts"][S.SRC_RSTR]["exact"], 1)
        self.assertFalse(r["auto_confirmed"])
        self.assertTrue(r["selection_required"])
        for c in r["candidates"]:
            self.assertIn(c["snapshot"]["snapshot_id"], c["key"])
            self.assertTrue(c["snapshot"]["collected_at"])

    def test_restriction_only_item_found(self):
        r = S.search("수은")
        self.assertEqual(r["counts"][S.SRC_INGR]["total"], 0)
        self.assertEqual([(c["source"], c["kr_name"]) for c in self.exact(r)], [(S.SRC_RSTR, "수은")])
        r2 = S.search("7439-97-6")
        self.assertEqual(r2["query_type"], "cas")
        self.assertEqual([c["kr_name"] for c in r2["candidates"]], ["수은"])

    def test_country_rows_grouped_once_with_raw_values(self):
        r = S.search("Phenoxyethanol")
        rs = [c for c in r["candidates"] if c["source"] == S.SRC_RSTR]
        self.assertEqual(len(rs), 1)
        c = rs[0]
        self.assertEqual(c["record_count"], 4)                                 # 한국 2건(조건별) + EU + 중국 → 후보 1개
        self.assertEqual(c["countries"], ["EU", "중국", "한국"])
        self.assertEqual(c["identity"], {"std_name": "페녹시에탄올", "eng_name_normalized": "phenoxyethanol"})
        # 영문명 대소문자·공백만 다른 행은 regulatory_mfds_lookup._identity 와 같이 한 묶음, 원문 값은 둘 다 보존
        ret = [x for x in S.search("retinol")["candidates"] if x["source"] == S.SRC_RSTR and x["kr_name"] == "레티놀"][0]
        self.assertEqual(ret["record_count"], 2)
        self.assertEqual(ret["values"]["INGR_ENG_NAME"], ["Retinol", "retinol "])

    def test_exact_before_prefix_before_contains_and_stable(self):
        r = S.search("글리세린")
        levels = [c["match"] for c in r["candidates"]]
        self.assertEqual(levels, sorted(levels, key=S.LEVELS.index))
        self.assertEqual(r["candidates"][0]["kr_name"], "글리세린")
        self.assertIn("prefix", levels)
        self.assertIn("contains", levels)                                      # 에틸헥실글리세린
        self.assertEqual([c["key"] for c in r["candidates"]], [c["key"] for c in S.search("  글리세린  ")["candidates"]])

    def test_limit_keeps_total_and_exact_counts(self):
        r = S.search("Water", limit=1)
        self.assertEqual(r["returned"], 1)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["counts"][S.SRC_INGR]["exact"], 2)                   # 1개만 보여도 정확 일치 2건
        self.assertEqual(r["exact_total"], 2)
        self.assertGreaterEqual(r["total"], 2)
        full = S.search("Water", limit=S.MAX_LIMIT)
        self.assertEqual(full["total"], r["total"])
        self.assertEqual(r["candidates"][0]["key"], full["candidates"][0]["key"])
        for bad in (0, S.MAX_LIMIT + 1, "x"):
            with self.assertRaises(S.SearchError):
                S.search("Water", limit=bad)

    def test_no_merge_on_duplicate_eng_or_missing_cas(self):
        ex = self.exact(S.search("Camellia Sinensis Leaf Extract"), S.SRC_INGR)
        self.assertEqual(sorted(c["kr_name"] for c in ex), ["녹차추출물", "홍차추출물"])
        self.assertEqual(len({c["key"] for c in ex}), 2)
        self.assertTrue(all(c["cas"] is None for c in ex))

    def test_cas_full_token_only(self):
        self.assertEqual([c["kr_name"] for c in S.search("61-90-5")["candidates"]], ["류신"])       # 개행·주석 섞인 원문에서도 토큰 일치
        self.assertEqual(S.search("1-90-5")["total"], 0)                                        # 부분 문자열 아님
        self.assertEqual(S.search("61-90")["total"], 0)
        f = S.search("30525-89-4")["candidates"]
        self.assertEqual([(c["source"], c["matched"][0]["via"]) for c in f], [(S.SRC_RSTR, "cas_token")])

    def test_split_preserves_locants_and_slash(self):
        r = S.search("1,2-Hexanediol")
        self.assertEqual([c["kr_name"] for c in self.exact(r)], ["1,2-헥산다이올"])
        self.assertEqual(S.search("2-Hexanediol")["counts"][S.SRC_INGR]["exact"], 0)          # 쉼표에서 나누지 않음
        r2 = S.search("Glycerin/Phthalic Acid Copolymer")
        self.assertEqual([c["kr_name"] for c in self.exact(r2)], ["글리세린/프탈릭애씨드코폴리머"])
        self.assertEqual(S.search("Phthalic Acid Copolymer")["counts"][S.SRC_INGR]["exact"], 0)  # '/' 에서 나누지 않음
        syn = self.exact(S.search("여지열매추출물"))
        self.assertEqual([(c["kr_name"], c["matched"][0]["field"], c["matched"][0]["via"]) for c in syn], [("리치추출물", "INGR_SYNONYM", "item")])
        notice = self.exact(S.search("Paraformaldehyde [2]"))
        self.assertEqual([c["matched"][0]["field"] for c in notice], ["NOTICE_INGR_NAME"])

    def test_whitespace_normalized_raw_preserved(self):
        c = self.exact(S.search("페녹시에탄올"), S.SRC_INGR)[0]
        self.assertEqual(c["kr_name"], "  페녹시에탄올 ")

    def test_query_validation_and_no_result(self):
        for q in ("", "   ", None, "a"):
            with self.assertRaises(S.SearchError) as ctx:
                S.search(q)
            self.assertEqual(ctx.exception.kind, "validation")
        r = S.search("없는성분이름")
        self.assertEqual((r["total"], r["candidates"]), (0, []))
        with self.assertRaises(S.SearchError):
            S.search("레티놀", sources=["kbeauty"])


class LookupCandidateTest(Base):
    """2단계: 선택한 후보 key → 서버 검증 → 규제 DB 조회 (이름 재매칭 없음, 자동 확정 없음)"""

    def pick(self, q, source, kr=None):
        for c in S.search(q, limit=S.MAX_LIMIT)["candidates"]:
            if c["source"] == source and (kr is None or c["kr_name"].strip() == kr):
                return c
        self.fail("후보 없음: %s %s %s" % (q, source, kr))

    def test_restriction_candidate_direct_found_and_no_market_record(self):
        c = self.pick("레티놀", S.SRC_RSTR, "레티놀")
        eu = S.lookup_candidate(c["key"], "EU")
        self.assertEqual((eu["lookup_status"], eu["link"]["status"]), ("found", "direct"))
        self.assertEqual([(e["country"], e["limit_condition"]) for e in eu["entries"]], [("EU", "0.3%")])
        self.assertEqual(eu["matched_identity"]["std_name"], "레티놀")
        kr = S.lookup_candidate(c["key"], "KR")
        self.assertEqual((kr["lookup_status"], kr["entries"]), ("no_market_record", []))
        self.assertEqual(kr["markets_listed"], ["EU", "캐나다"])
        self.assertIn("허용·안전·규제 없음을 뜻하지 않아요", kr["result_note"])
        self.assertFalse(kr["auto_confirmed"])

    def test_ingredient_candidate_linked_by_exact_names(self):
        c = self.pick("레티놀", S.SRC_INGR, "레티놀")
        r = S.lookup_candidate(c["key"], "EU")
        self.assertEqual((r["lookup_status"], r["link"]["status"]), ("found", "linked"))
        self.assertEqual(r["link"]["basis"], ["영문명 = 규제 영문명", "한글명 = 규제 표준명"])
        self.assertEqual(r["ingredient"]["kr_name"], "레티놀")                      # 화면 제목 = 사용자가 고른 성분
        self.assertEqual(r["selection"]["source"], S.SRC_INGR)
        self.assertEqual(r["ingredient_source"]["source"], S.SRC_INGR)
        self.assertEqual(r["regulation_source"]["source"], S.SRC_RSTR)
        srcs = S.search("레티놀")["sources"]                                          # 출처별 수집 시각을 각자 수집본에서 가져옴
        self.assertEqual(r["ingredient_source"]["collected_at"], srcs[S.SRC_INGR]["collected_at"])
        self.assertEqual(r["regulation_source"]["collected_at"], srcs[S.SRC_RSTR]["collected_at"])
        self.assertEqual(r["collection_run"]["run_id"], srcs[S.SRC_RSTR]["run_id"])

    def test_retinol_synonym_hit_does_not_change_selected_ingredient(self):
        res = S.search("Retinol")
        palm = [c for c in res["candidates"] if c["kr_name"] == "레티닐팔미테이트"]
        self.assertEqual(palm[0]["matched"][0]["field"], "INGR_SYNONYM")            # 이명 때문에 검색은 됨
        for src in (S.SRC_INGR, S.SRC_RSTR):
            r = S.lookup_candidate(self.pick("Retinol", src, "레티놀")["key"], "EU")
            self.assertEqual(r["matched_identity"]["std_name"], "레티놀", src)        # 레티닐팔미테이트로 바뀌지 않음
            self.assertTrue(all(e["std_name"] == "레티놀" for e in r["entries"]))
        p = S.lookup_candidate(palm[0]["key"], "EU")
        self.assertEqual(p["matched_identity"]["std_name"], "레티닐팔미테이트")
        self.assertTrue(all(e["std_name"] == "레티닐팔미테이트" for e in p["entries"]))

    def test_all_condition_records_for_market_kept(self):
        r = S.lookup_candidate(self.pick("페녹시에탄올", S.SRC_RSTR)["key"], "KR")
        self.assertEqual([e["limit_condition"] for e in r["entries"]], ["1%", "사용 후 씻어내는 제품 1%"])
        self.assertEqual(r["markets_listed"], ["EU", "중국", "한국"])
        self.assertEqual(S.lookup_candidate(self.pick("페녹시에탄올", S.SRC_INGR)["key"], "KR")["entries"], r["entries"])

    def test_not_linked_keeps_related_separate(self):
        r = S.lookup_candidate(self.pick("Aqua", S.SRC_INGR, "정제수")["key"], "KR")
        self.assertEqual((r["lookup_status"], r["link"]["status"], r["entries"]), ("not_linked", "none", []))
        self.assertIsNone(r["matched_identity"])
        self.assertIn("허용·안전·규제 없음을 뜻하지 않아요", r["result_note"])

    def test_ambiguous_names_need_user_choice(self):
        r = S.lookup_candidate(self.pick("마이카", S.SRC_INGR)["key"], "EU")
        self.assertEqual((r["lookup_status"], r["entries"]), ("link_required", []))
        self.assertEqual(len(r["link_candidates"]), 2)
        self.assertTrue(all(c["key"].startswith(S.SRC_RSTR + ":") for c in r["link_candidates"]))
        chosen = [c for c in r["link_candidates"] if c["eng_name"] == "CI 77019"][0]
        r2 = S.lookup_candidate(chosen["key"], "EU")                                   # 사용자가 고른 규제 후보로 다시 조회
        self.assertEqual((r2["lookup_status"], r2["matched_identity"]["eng_name"]), ("found", "CI 77019"))

    def test_conflicts_are_not_auto_linked(self):
        nic = S.lookup_candidate(self.pick("니코틴", S.SRC_INGR)["key"], "KR")
        self.assertEqual(nic["lookup_status"], "link_required")
        self.assertIn("CAS", nic["link_conflict"])
        gly = S.lookup_candidate(self.pick("글리세린", S.SRC_INGR, "글리세린")["key"], "EU")
        self.assertEqual(gly["lookup_status"], "link_required")
        self.assertIn("영문명이 달라요", gly["link_conflict"])

    def test_cas_search_then_restriction_lookup(self):
        c = S.search("7439-97-6")["candidates"][0]
        r = S.lookup_candidate(c["key"], "EU")
        self.assertEqual((r["lookup_status"], r["matched_identity"]["std_name"], len(r["entries"])), ("found", "수은", 1))

    def test_key_and_market_validation(self):
        key = self.pick("레티놀", S.SRC_RSTR)["key"]
        with self.assertRaises(S.SearchError) as ctx:
            S.lookup_candidate(key, "XX")
        self.assertEqual(ctx.exception.kind, "validation")
        with self.assertRaises(S.SearchError) as ctx:
            S.lookup_candidate("not-a-key", "EU")
        self.assertEqual(ctx.exception.kind, "validation")

    def test_stale_keys_after_rebuild(self):
        rkey = self.pick("레티놀", S.SRC_RSTR)["key"]
        ikey = self.pick("레티놀", S.SRC_INGR)["key"]
        S.clear_cache()
        self.rstr_path.unlink()
        build_restriction_db(self.rstr_path, RSTR_ITEMS, started_at="2026-12-01T00:00:00+00:00")
        with self.assertRaises(S.SearchError) as ctx:
            S.lookup_candidate(rkey, "EU")
        self.assertEqual(ctx.exception.kind, "stale_key")
        r = S.lookup_candidate(ikey, "EU")                                             # 성분 DB 는 그대로 → 새 규제 수집본으로 연결
        self.assertEqual(r["lookup_status"], "found")

    def test_run_changed_between_resolve_and_lookup_is_stale(self):
        with self.assertRaises(S._lookup.MfdsLookupError) as ctx:
            S._lookup.lookup_by_identity("레티놀", "retinol", "EU", path=self.rstr_path,
                                         expected_run={"run_id": 1, "started_at": "other", "finished_at": "other"})
        self.assertEqual(ctx.exception.kind, "stale_run")
        self.assertEqual(S._as_search_error(ctx.exception).kind, "stale_key")

    def test_restriction_db_missing_is_error_for_ingredient_candidate(self):
        key = self.pick("레티놀", S.SRC_INGR)["key"]
        with mock.patch.dict(os.environ, {"MFDS_DB_PATH": str(Path(self.tmp.name) / "none.sqlite")}):
            with self.assertRaises(S.SearchError) as ctx:
                S.lookup_candidate(key, "EU")
        self.assertEqual((ctx.exception.kind, ctx.exception.source), ("db_missing", S.SRC_RSTR))

    def test_lookup_does_not_modify_db_files(self):
        before = (sha(self.ingr_path), sha(self.rstr_path))
        for q, src in (("레티놀", S.SRC_INGR), ("레티놀", S.SRC_RSTR), ("마이카", S.SRC_INGR), ("Aqua", S.SRC_INGR)):
            S.lookup_candidate(self.pick(q, src)["key"], "EU")
        self.assertEqual((sha(self.ingr_path), sha(self.rstr_path)), before)


class KeyTest(Base):
    def test_same_local_id_different_sources_no_collision(self):
        a = S.resolve_key(S.search("정제수")["candidates"][0]["key"])
        k_ing = "%s:%s:%d" % (S.SRC_INGR, a["snapshot"]["snapshot_id"], 1)
        rs = S.search("레티놀", sources=[S.SRC_RSTR])["sources"][S.SRC_RSTR]
        k_rst = "%s:%s:%d" % (S.SRC_RSTR, rs["snapshot_id"], 1)
        self.assertNotEqual(k_ing, k_rst)
        self.assertEqual(S.resolve_key(k_ing)["kr_name"], "정제수")
        self.assertEqual(S.resolve_key(k_rst)["kr_name"], "레티놀")
        self.assertNotEqual(a["snapshot"]["snapshot_id"], rs["snapshot_id"])

    def test_rebuilt_db_same_run_id_gets_new_snapshot_and_old_key_is_stale(self):
        old = self.exact(S.search("레티놀"), S.SRC_INGR)[0]
        self.assertEqual(old["snapshot"]["run_id"], 1)
        S.clear_cache()
        self.ingr_path.unlink()
        reordered = list(reversed(INGR_ITEMS))                       # 다시 만든 DB: run_id 는 또 1, 내부 id 는 다른 성분을 가리킴
        build_ingredient_db(self.ingr_path, reordered, started_at="2026-12-01T00:00:00+00:00")
        new = self.exact(S.search("레티놀"), S.SRC_INGR)[0]
        self.assertEqual(new["snapshot"]["run_id"], 1)
        self.assertNotEqual(new["snapshot"]["snapshot_id"], old["snapshot"]["snapshot_id"])
        self.assertNotEqual(new["key"], old["key"])
        with self.assertRaises(S.SearchError) as ctx:
            S.resolve_key(old["key"])
        self.assertEqual(ctx.exception.kind, "stale_key")

    def test_resolve_key_errors(self):
        for bad in ("", "x", "kbeauty:abc:1", "mfds_ingredients:XYZ:1"):
            with self.assertRaises(S.SearchError) as ctx:
                S.resolve_key(bad)
            self.assertEqual(ctx.exception.kind, "validation")
        snap = S.search("정제수")["sources"][S.SRC_INGR]["snapshot_id"]
        with self.assertRaises(S.SearchError) as ctx:
            S.resolve_key("%s:%s:999999" % (S.SRC_INGR, snap))
        self.assertEqual(ctx.exception.kind, "not_found")


class DbErrorTest(Base):
    def test_missing_db_is_error_not_empty_and_not_created(self):
        missing = Path(self.tmp.name) / "nope.sqlite"
        with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(missing)}):
            with self.assertRaises(S.SearchError) as ctx:
                S.search("레티놀")
            self.assertEqual((ctx.exception.kind, ctx.exception.source), ("db_missing", S.SRC_INGR))
            self.assertFalse(missing.exists())
            self.assertEqual(S.search("레티놀", sources=[S.SRC_RSTR])["counts"][S.SRC_RSTR]["exact"], 1)  # 고른 출처만 쓰면 동작

    def test_deleted_after_cache_still_errors(self):
        S.search("레티놀")                      # 캐시를 만든 뒤 캐시는 그대로 두고 파일만 삭제
        self.rstr_path.unlink()
        with self.assertRaises(S.SearchError) as ctx:
            S.search("레티놀")
        self.assertEqual(ctx.exception.kind, "db_missing")

    def test_incomplete_run_not_searched(self):
        p = Path(self.tmp.name) / "running.sqlite"
        build_restriction_db(p, RSTR_ITEMS, status="running")
        with mock.patch.dict(os.environ, {"MFDS_DB_PATH": str(p)}):
            with self.assertRaises(S.SearchError) as ctx:
                S.search("레티놀")
            self.assertEqual(ctx.exception.kind, "db_incomplete")

    def test_swapped_paths_rejected(self):
        with mock.patch.dict(os.environ, {"MFDS_INGREDIENT_DB_PATH": str(self.rstr_path), "MFDS_DB_PATH": str(self.ingr_path)}):
            with self.assertRaises(S.SearchError) as ctx:
                S.search("레티놀")
            self.assertEqual(ctx.exception.kind, "db_error")

    def test_corrupt_file_is_db_error(self):
        p = Path(self.tmp.name) / "corrupt.sqlite"
        p.write_bytes(b"not a sqlite database" * 100)
        with mock.patch.dict(os.environ, {"MFDS_DB_PATH": str(p)}):
            with self.assertRaises(S.SearchError) as ctx:
                S.search("레티놀")
            self.assertEqual(ctx.exception.kind, "db_error")

    def test_search_does_not_modify_db_files(self):
        before = (sha(self.ingr_path), sha(self.rstr_path))
        for q in ("레티놀", "Water", "122-99-6"):
            S.search(q)
        S.resolve_key(S.search("수은")["candidates"][0]["key"])
        self.assertEqual((sha(self.ingr_path), sha(self.rstr_path)), before)
        self.assertEqual(sorted(x.name for x in Path(self.tmp.name).iterdir()), ["mfds_ingredients.sqlite", "mfds_use_restriction.sqlite"])


if __name__ == "__main__":
    unittest.main()
