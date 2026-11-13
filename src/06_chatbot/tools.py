"""AI 챗봇 도구 모듈 (담당자 F) — 명세: src/06_chatbot/chatbot.md 5·9·10장

OpenAI 모델이 호출할 수 있는 도구(function)를 정의하고 실행합니다.
데이터는 같은 저장소의 기존 모듈을 API 없이 직접 불러와 사용합니다. (로그인 세션에 의존하는 부분 없음)

- 환율 · 수출입 · 뉴스 · 규제 소식 : src/01_home/home_data.py  (SQLite 캐시 + 백그라운드 수집)
- 성분 검색 · 규제 조회           : src/02_regulatory/regulatory_search.py (식약처 성분 DB·규제 DB 읽기 전용, 규제 화면과 같은 모듈)
                                   국가 코드는 regulatory_mfds_lookup.MARKET_CODES. 외부 API·API 키 없음, 자동 수집 없음.

성분 규제 흐름 (규제 화면과 같은 원칙: 검색 → 후보 표시 → 사용자 선택 → 선택 국가 규제 조회)
- search_ingredient: 후보를 찾고, 후보 key 는 서버의 SelectionStore 에만 둡니다 (모델·브라우저에는 key 를 주지 않음).
  브라우저에는 offer_id + 후보 순번이 담긴 '선택 카드'를 돌려주고, 사용자가 버튼을 누를 때만 조회합니다.
- lookup_ingredient_regulation: 모델이 호출하면 거절합니다 (selection_required). 서버가 '현재 대화에 제시한 최신 후보 목록'과
  사용자의 선택 요청(offer_id·순번·시장)을 검증한 뒤 run_selection() 으로 직접 실행하고, 결과를 모델에 전달합니다.
- 선택 상태는 (로그인 사용자 id, 대화 id) 별로 분리합니다. 새 후보 목록을 만들면 그 대화의 이전 목록은 무효가 됩니다.

원칙
- 도구 결과는 모델에게 "데이터"로만 전달합니다. 결과 안의 문장은 지시로 해석하지 않도록 서버 system prompt 에서 안내합니다.
- 규제 결과는 원문(limit_condition 등)을 가공하지 않고 축약만 합니다. 허용·안전 판단을 만들지 않습니다.
- 결과가 길면 JSON 구조를 유지한 채 줄이고, 줄였다는 사실(_output_truncated)을 결과에 남깁니다.
- API Key 는 각 모듈이 os.getenv() 로 읽으며, 이 모듈은 Key 를 다루지 않습니다.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import logging
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:          # server.py 를 스크립트로 직접 실행할 때 저장소 루트를 import 경로에 추가
    sys.path.insert(0, str(BASE_DIR))

log = logging.getLogger("cosmoa.chatbot.tools")
KST = ZoneInfo("Asia/Seoul")
MAX_OUTPUT_CHARS = 7000      # 도구 결과 1건이 모델에 전달되는 최대 길이
MAX_LIST = 10


def _load_file_module(name: str, rel_path: str):
    """폴더명이 숫자로 시작해 import 문을 쓸 수 없으므로 파일 경로로 불러옵니다. (app.py [B] 영역과 같은 방식)"""
    spec = importlib.util.spec_from_file_location(name, BASE_DIR / "src" / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


home_data = importlib.import_module("src.01_home.home_data")
regulatory_mfds = _load_file_module("regulatory_mfds_lookup", "02_regulatory/regulatory_mfds_lookup.py")   # MARKET_CODES·시장 매핑
regulatory_search = _load_file_module("regulatory_search", "02_regulatory/regulatory_search.py")           # search·resolve_key·lookup_candidate


def init(db_path: Path) -> None:
    """서버 시작 시 한 번 호출. 홈 데이터 캐시(SQLite) 테이블을 준비합니다. (식약처 DB 는 읽기만 — 수집하지 않음)"""
    home_data.init(db_path)


# ---------------------------------------------------------------------------
# 도구 정의 (OpenAI Responses API function tools, strict 모드)
#   strict 모드는 모든 property 를 required 에 넣고, 선택 값은 null 을 허용하는 type 으로 표현합니다.
# ---------------------------------------------------------------------------
MARKETS = list(regulatory_mfds.MARKET_CODES)              # KR, EU, US, CN, JP, ASEAN (규제 화면 /lookup 과 같은 상수)
MARKET_LABELS = {"KR": "한국", "EU": "유럽연합(EU)", "US": "미국", "CN": "중국", "JP": "일본", "ASEAN": "아세안"}
REG_COUNTRIES = list(home_data.REG_COUNTRIES)            # 미국, EU, 중국, 일본, 동남아, 중동, 한국, 기타
NEWS_SOURCES = list(home_data.NEWS_SOURCES)

TOOLS = [
    {
        "type": "function",
        "name": "get_exchange_rates",
        "description": "오늘 기준 원화 환율(매매기준율, 한국수출입은행)과 전일 대비 변동률을 가져와요. USD, JPY(100엔), CNH, EUR, THB, VND 등 주요 수출국 통화. 환산 계산이 필요하면 이 값을 기준으로 계산해요.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_trade_stats",
        "description": "관세청 화장품(HS 3304 등) 수출입 실적: 최근 월 수출·수입액, 전년 동월 대비, 최근 12개월 추이, 수출 상위국, 품목(HS 6단위)별 수출.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_news",
        "description": "화장품 업계 최신 뉴스를 검색해요. 출처: 장업신문, CMN, 뷰티누리, 코스인, 코스모닝, 식약처 + 검색어가 있으면 구글 뉴스. query 가 없으면 최신 기사 목록.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"], "description": "검색어 (제목·매체명). 없으면 null"},
                "source": {"type": ["string", "null"], "enum": NEWS_SOURCES + [None], "description": "특정 매체만 볼 때. 없으면 null"},
                "limit": {"type": "integer", "description": "최대 건수 (1~10)"},
            },
            "required": ["query", "source", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_regulation_news",
        "description": "해외 화장품 규제 업데이트 소식(구글 뉴스·KOTRA 수집)을 검색해요. 국가별 최신 규제 동향, MoCRA·CPNP·NMPA 등 제도 소식.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"], "description": "검색어. 없으면 null"},
                "country": {"type": ["string", "null"], "enum": REG_COUNTRIES + [None], "description": "국가 필터. 없으면 null"},
                "limit": {"type": "integer", "description": "최대 건수 (1~10)"},
            },
            "required": ["query", "country", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_ingredient",
        "description": ("식약처 수집 DB 두 개(성분정보 = 화장품 원료성분정보, 규제정보 = 화장품 사용제한 원료정보)에서 성분 후보를 찾아요. "
                        "한글명·영문명·이명·고시원료명·CAS 로 검색하고 정확 → 앞부분 → 포함 일치 순으로 최대 10개를 돌려줘요. "
                        "후보는 채팅창에 선택 버튼으로 표시되고, 사용자가 버튼으로 성분과 국가를 골라야 규제가 조회돼요. "
                        "정확 일치가 하나여도 자동으로 확정·조회하지 않아요. 규제를 물으면 먼저 이 도구로 후보를 보여 주세요."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "성분명 또는 CAS 2글자 이상 (예: 레티놀, Retinol, 122-99-6)"},
                "market": {"type": ["string", "null"], "enum": MARKETS + [None],
                           "description": "사용자가 말한 시장이 있으면 그 코드 (선택 카드의 기본값으로만 쓰이며 조회하지 않음). 없으면 null"},
            },
            "required": ["query", "market"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "lookup_ingredient_regulation",
        "description": ("선택한 성분의 국가별 사용제한·금지 규제 조회 결과예요. 이 도구는 사용자가 채팅창의 후보 버튼을 눌렀을 때 서버가 "
                        "검증한 뒤 실행하고 결과를 전달해요. 모델이 직접 호출하면 실행되지 않고 '사용자 선택 필요'만 돌아와요 — "
                        "후보 번호나 이름으로 조회할 수 없어요. 결과는 참고 자료이며 허용·안전 판단이 아니에요."),
        "parameters": {
            "type": "object",
            "properties": {"market": {"type": "string", "enum": MARKETS, "description": "시장 코드"}},
            "required": ["market"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_local_time",
        "description": "주요 수출국 바이어의 현지 시각과 업무 시간(09~18시) 여부를 알려줘요. country_code 가 null 이면 수출 상위국 4곳.",
        "parameters": {
            "type": "object",
            "properties": {"country_code": {"type": ["string", "null"], "description": "ISO 국가코드 2자리 (CN, US, JP, VN, TH, DE …). 없으면 null"}},
            "required": ["country_code"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# ---------------------------------------------------------------------------
# 후보 선택 상태 (대화별) — 후보 key 는 여기에만 둔다
# ---------------------------------------------------------------------------
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
OFFER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class SelectionStore:
    """(사용자 id, 대화 id) → 현재 유효한 후보 목록들. 서버 메모리(스레드 잠금)에만 둔다.

    - 한 요청에서 새 후보 목록을 만들면 그 대화의 이전 목록은 모두 무효가 된다 (최신 목록만 선택 가능).
    - TTL 이 지나거나 서버가 다시 시작되면 사라진다 → 사용자는 다시 검색한다 (조회를 추측으로 이어가지 않음).
    - 챗봇 서버는 워커 1개로 실행한다 (docs/deploy_render.md). 워커를 늘리면 공유 저장소가 필요하다.
    """

    TTL_SECONDS = 2 * 60 * 60
    MAX_CONVERSATIONS = 1000

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[tuple[str, str], dict] = {}

    def _prune(self, now: float) -> None:
        for k in [k for k, v in self._data.items() if now - v["touched"] > self.TTL_SECONDS]:
            del self._data[k]
        while len(self._data) > self.MAX_CONVERSATIONS:
            del self._data[min(self._data, key=lambda k: self._data[k]["touched"])]

    def replace(self, conv: tuple[str, str], offers: list[dict]) -> None:
        now = time.time()
        with self._lock:
            self._data[conv] = {"touched": now, "offers": {o["offer_id"]: o for o in offers}}
            self._prune(now)

    def add(self, conv: tuple[str, str], offer: dict) -> None:
        now = time.time()
        with self._lock:
            slot = self._data.setdefault(conv, {"touched": now, "offers": {}})
            slot["touched"] = now
            slot["offers"][offer["offer_id"]] = offer
            self._prune(now)

    def get(self, conv: tuple[str, str], offer_id: str) -> dict | None:
        now = time.time()
        with self._lock:
            self._prune(now)
            slot = self._data.get(conv)
            if not slot:
                return None
            offer = slot["offers"].get(offer_id)
            if offer is not None:
                slot["touched"] = now
            return offer

    def has(self, conv: tuple[str, str] | None) -> bool:
        if conv is None:
            return False
        with self._lock:
            self._prune(time.time())
            slot = self._data.get(conv)
            return bool(slot and slot["offers"])

    def clear(self, conv: tuple[str, str]) -> None:
        with self._lock:
            self._data.pop(conv, None)

    def reset(self) -> None:          # 테스트용
        with self._lock:
            self._data.clear()


SELECTIONS = SelectionStore()


@dataclass
class ChatContext:
    """요청 1건의 대화 맥락. server.run_chat 이 만들고 도구 실행에 넘긴다."""
    user_id: str | None = None
    conversation_id: str | None = None
    new_offers: list = field(default_factory=list)     # 이번 요청에서 만든 후보 목록 (브라우저용 공개 형태)
    reset: bool = False                                 # 이전 후보 목록이 무효가 됐는지 (브라우저가 이전 카드를 비활성화)
    _replaced: bool = False

    @property
    def conv(self) -> tuple[str, str] | None:
        if self.user_id and self.conversation_id and CONVERSATION_ID_RE.match(self.conversation_id):
            return (self.user_id, self.conversation_id)
        return None

    def add_offer(self, offer: dict) -> bool:
        conv = self.conv
        if conv is None:
            return False
        if not self._replaced:                           # 이번 요청의 첫 목록 → 이 대화의 이전 목록 전부 무효
            SELECTIONS.replace(conv, [offer])
            self._replaced = True
            self.reset = True
        else:
            SELECTIONS.add(conv, offer)
        self.new_offers.append(_public_offer(offer))
        return True

    def clear_offers(self) -> None:
        conv = self.conv
        if conv is not None:
            SELECTIONS.clear(conv)
        self.reset = True


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def _clamp(n, lo, hi, default):
    try:
        return max(lo, min(hi, int(n)))
    except (TypeError, ValueError):
        return default


def _collecting(section: str) -> str | None:
    if section in home_data.is_refreshing():
        return "데이터를 지금 수집하는 중이에요. 30초쯤 뒤에 다시 물어봐 주세요."
    return None


def tool_get_exchange_rates() -> dict:
    home_data.kick_refresh(("rates",))
    rates = home_data.get_rates()
    if not rates["items"]:
        home_data.refresh_rates()          # 첫 실행(캐시 없음)은 바로 조회 — 외부 호출 1~2회
        rates = home_data.get_rates()
    return {
        "date": rates["date"],
        "basis": "한국수출입은행 매매기준율 (KRW). unit 이 100이면 100단위 통화 기준 (예: JPY 100엔)",
        "items": [{"code": r["code"], "unit": r["unit"], "name": r["name"], "rate_krw": r["rate"],
                   "change_pct_vs_prev_day": None if r["change"] is None else round(r["change"], 2)} for r in rates["items"]],
        "error": rates["error"],
    }


def tool_get_trade_stats() -> dict:
    home_data.kick_refresh(("trade",))
    cards = home_data.get_trade_cards()
    if not cards.get("ok"):
        return {"ok": False, "message": _collecting("trade") or cards.get("message"), "reference": cards.get("kstat_url")}
    summary = cards.get("summary", {})
    return {
        "ok": True,
        "unit": "USD 백만 (musd)",
        "hs_codes": cards.get("hs_codes") or home_data.HS_CODES,
        "latest_month": summary.get("month_text"),
        "summary": {k: summary.get(k) for k in ("exp_musd", "imp_musd", "bal_musd", "exp_yoy", "imp_yoy", "total_12m_musd")},
        "trend_12m": [{"month": t["label"], "exp_musd": t["musd"]} for t in summary.get("trend", [])],
        "top_countries_12m": [{k: c.get(k) for k in ("code", "name", "musd", "share", "pct", "direction")} for c in cards.get("countries", [])],
        "top_products_12m": [{k: p.get(k) for k in ("code", "name", "musd", "share", "pct", "direction")} for p in cards.get("products", [])],
        "source": "관세청 품목별 국가별 수출입실적 (공공데이터포털)",
    }


def tool_search_news(query=None, source=None, limit=5) -> dict:
    home_data.kick_refresh(("news",))
    q = (query or "").strip() or None
    limit = _clamp(limit, 1, MAX_LIST, 5)
    news = home_data.get_news(limit=limit, per_source=None, q=q, source=source or None, external=bool(q))
    items = [{"source": n["source"], "press": n["press"] or None, "title": n["title"], "url": n["url"],
              "published_at": n["published_at"]} for n in news["items"]]
    return {"query": q, "count": len(items), "items": items,
            "updated_at": news["updated_at"],
            "note": None if items else (_collecting("news") or news["error"])}


def tool_search_regulation_news(query=None, country=None, limit=5) -> dict:
    home_data.kick_refresh(("regulations",))
    q = (query or "").strip() or None
    limit = _clamp(limit, 1, MAX_LIST, 5)
    regs = home_data.get_regulations(limit=limit, q=q, country=country or None)
    items = [{"country": r["country"], "title": r["title"], "source": r["source"], "url": r["url"],
              "published_at": r["published_at"]} for r in regs["items"]]
    return {"query": q, "country": country, "count": len(items), "items": items,
            "checked_at": regs["checked_at"],
            "note": None if items else (_collecting("regulations") or "조건에 맞는 규제 소식이 아직 없어요.")}


# --- 성분 검색 · 규제 조회 (식약처 수집 DB) ----------------------------------

SOURCE_SHORT = {regulatory_search.SRC_INGR: "성분정보", regulatory_search.SRC_RSTR: "규제정보"}
FIELD_LABEL = {"INGR_KOR_NAME": "한글명", "INGR_STD_NAME": "표준명", "INGR_ENG_NAME": "영문명", "INGR_SYNONYM": "이명",
               "NOTICE_INGR_NAME": "고시원료명", "CAS_NO": "CAS"}
FIELD_KIND = {"INGR_KOR_NAME": "표준명·영문명", "INGR_STD_NAME": "표준명·영문명", "INGR_ENG_NAME": "표준명·영문명",
              "INGR_SYNONYM": "이명", "NOTICE_INGR_NAME": "고시원료명", "CAS_NO": "CAS"}
LEVEL_LABEL = {"exact": "정확 일치", "prefix": "앞부분 일치", "contains": "포함 일치"}
STATUS_LABEL = {"found": "규제 정보 조회됨", "no_market_record": "선택 국가 기록 없음",
                "link_required": "성분 연결 확인 필요", "not_linked": "규제 성분 연결 미확인"}
DB_KINDS = {"db_missing": "DB 미설치 (수집 DB 없음)", "db_incomplete": "수집 미완료 (완료된 수집 없음)", "db_error": "DB 읽기 오류"}
COLLECTED_NOTE = "수집 시각은 DB 에 기록된 수집 완료 시각이에요. 원천 자료 갱신일·법령 개정일이 아니며 최신성을 보장하지 않아요."
REFERENCE_NOTE = ("규제 참고 자료예요. 검색·조회됐다고 사용 가능·안전하다는 뜻이 아니고, 기록이 없다고 제한이 없다는 뜻도 아니에요. "
                  "최종 판단은 담당자·법령 원문 확인이 필요해요.")
SELECTION_NOTE = ("후보는 채팅창에 선택 버튼으로 표시돼요. 사용자가 버튼으로 성분과 국가를 골라야 서버가 규제를 조회해요. "
                  "대신 고르거나 번호·이름으로 조회할 수 없으니, 사용자에게 버튼으로 선택해 달라고 안내해 주세요.")


def _match_basis(matched: list) -> dict:
    m = matched[0] if matched else None
    if not m:
        return {"text": "—", "kind": None}
    text = "%s %s" % (FIELD_LABEL.get(m["field"], m["field"]), LEVEL_LABEL.get(m["level"], m["level"]))
    if m.get("via") == "item":
        text += " (나열된 이름 중 하나)"
    if m["field"] in ("INGR_SYNONYM", "NOTICE_INGR_NAME"):
        text += " · 원문 ‘%s’" % " ".join((m.get("value") or "").split())[:80]
    return {"text": text, "kind": FIELD_KIND.get(m["field"])}


def _db_error_result(exc) -> dict:
    kind = getattr(exc, "kind", "db_error")
    out = {"error": exc.to_dict(), "status_label": "조회 오류"}
    if kind in DB_KINDS:
        out["error"]["category"] = "출처 이용 불가 · " + DB_KINDS[kind] + (" · " + SOURCE_SHORT[exc.source] if exc.source in SOURCE_SHORT else "")
        out["hint"] = ("식약처 수집 DB 를 쓸 수 없어요. '검색 결과 없음'이나 '규제 없음'이 아니에요. 다른 출처나 다른 성분으로 대신 답하지 말고, "
                       "관리자에게 DB 준비를 요청하도록 안내해 주세요.")
    return out


def tool_search_ingredient(query="", market=None, ctx: ChatContext | None = None) -> dict:
    """후보 검색 (자동 확정·조회 없음). key 는 SelectionStore 에만 저장하고 결과에는 넣지 않는다."""
    if market is not None and market not in MARKETS:
        market = None
    try:
        r = regulatory_search.search(query, limit=MAX_LIST)
    except regulatory_search.SearchError as exc:
        return _db_error_result(exc)
    base = {
        "query": r["query"],
        "total": r["total"], "returned": r["returned"], "truncated": r["truncated"], "exact_total": r["exact_total"],
        "counts": {SOURCE_SHORT[s]: v for s, v in r["counts"].items()},
        "sources": {SOURCE_SHORT[s]: {"label": v["source_label"], "collected_at": v["collected_at"]} for s, v in r["sources"].items()},
        "collected_at_note": COLLECTED_NOTE,
    }
    if r["total"] == 0:
        base.update({"status": "no_result",
                     "note": "두 DB 모두 일치하는 후보가 없어요 (DB 오류 아님). 사용 가능·규제 없음을 뜻하지 않아요. 철자·영문명·CAS 로 다시 찾도록 안내해 주세요."})
        return base
    items, view = [], []
    for i, c in enumerate(r["candidates"], start=1):
        basis = _match_basis(c["matched"])
        disp = {"index": i, "kr_name": (c.get("kr_name") or "").strip() or None, "eng_name": (c.get("eng_name") or "").strip() or None,
                "source": SOURCE_SHORT[c["source"]], "match": basis["text"], "match_kind": basis["kind"], "level": c["match"]}
        view.append(disp)
        items.append(dict(disp, key=c["key"], cas=c.get("cas")))
    offer = {"offer_id": secrets.token_urlsafe(12), "kind": "ingredient", "query": r["query"], "market": market,
             "items": items, "total": r["total"], "returned": r["returned"], "truncated": r["truncated"], "exact_total": r["exact_total"]}
    selectable = bool(ctx and ctx.add_offer(offer))
    base.update({
        "status": "candidates",
        "candidates": view,
        "market_hint": market,
        "auto_confirmed": False,
        "selection": SELECTION_NOTE if selectable else
                     "이 대화에서는 선택 버튼을 만들 수 없어요 (대화 정보 없음). 화면을 새로 고친 뒤 다시 검색하도록 안내해 주세요.",
        "truncated_note": ("전체 %d건 중 %d건만 표시했어요. 원하는 성분이 없으면 더 구체적인 이름으로 다시 검색하도록 안내해 주세요." % (r["total"], r["returned"]))
                          if r["truncated"] else None,
        "notice": r["notice"],
    })
    return base


def _compact_entries(entries: list[dict]) -> list[dict]:
    keys = ("country", "regulate_type", "notice_ingr_name", "limit_condition", "proviso")
    return [{k: e.get(k) for k in keys} for e in entries[:MAX_LIST]]


def tool_lookup_ingredient_regulation(key: str, market: str, origin: dict | None = None) -> dict:
    """서버가 검증한 후보 key + 시장으로 규제 DB 조회 (regulatory_search.lookup_candidate). 모델이 직접 부르지 않는다."""
    if market not in MARKETS:
        return {"error": {"kind": "validation", "message": "시장 코드는 %s 중 하나여야 해요." % ", ".join(MARKETS)}}
    try:
        r = regulatory_search.lookup_candidate(key, market)
    except regulatory_search.SearchError as exc:
        if exc.kind in ("stale_key", "not_found"):
            return {"error": exc.to_dict(), "status_label": "후보 다시 선택 필요",
                    "hint": "선택한 후보의 수집본이 바뀌어 조회하지 않았어요. 이전 선택은 해제됐어요. 성분명을 다시 검색해 후보를 새로 고르도록 안내해 주세요."}
        return _db_error_result(exc)
    status = r["lookup_status"]
    sel = r.get("selection") or {}
    ident = r.get("matched_identity") or None
    entries = r.get("entries") or []
    out = {
        "lookup_status": status,
        "status_label": STATUS_LABEL.get(status, status),
        "market": {"code": market, "label": MARKET_LABELS.get(market, market), "country_names": (r.get("country") or {}).get("country_names")},
        "selected": {"kr_name": sel.get("kr_name"), "eng_name": sel.get("eng_name"), "source": SOURCE_SHORT.get(sel.get("source"), sel.get("source"))},
        "first_selected": origin,                                    # 연결 후보를 다시 고른 경우 처음 고른 성분 (아니면 null)
        "regulation_ingredient": {"std_name": ident.get("std_name"), "eng_name": ident.get("eng_name")} if ident else None,
        "link": {"status": r["link"]["status"], "basis": r["link"]["basis"], "conflict": r["link"]["conflict"]},
        "entries_total": len(entries),
        "entries_shown": min(len(entries), MAX_LIST),
        "entries": _compact_entries(entries),
        "related_count": len(r.get("related") or []),
        "related_sample": [{"std_name": x.get("std_name"), "eng_name": x.get("eng_name"), "country": x.get("country"),
                            "regulate_type": x.get("regulate_type"), "matched_in": x.get("matched_in")} for x in (r.get("related") or [])[:5]],
        "related_note": "관련 항목은 이름을 포함하는 항목(염류·유도체·성분군 등)이에요. 확정 규제가 아니며 적용 여부 확인이 필요해요.",
        "markets_listed": r.get("markets_listed"),
        "result_note": r.get("result_note"),
        "ingredient_source": {"label": (r.get("ingredient_source") or {}).get("label"), "collected_at": (r.get("ingredient_source") or {}).get("collected_at")},
        "regulation_source": {"label": (r.get("regulation_source") or {}).get("label"), "collected_at": (r.get("regulation_source") or {}).get("collected_at")},
        "collected_at_note": COLLECTED_NOTE,
        "disclaimer": r.get("disclaimer"),
        "reference_note": REFERENCE_NOTE,
    }
    if len(entries) > MAX_LIST:
        out["entries_note"] = "규제 조건 %d건 중 %d건만 전달했어요. 일부 조건만 확인한 것으로 답하고, 전체는 규제 화면·원문에서 확인하도록 안내해 주세요." % (len(entries), MAX_LIST)
    if status == "link_required":
        out["link_candidates"] = [{"index": i, "std_name": c.get("std_name"), "eng_name": c.get("eng_name"), "basis": c.get("basis"),
                                   "markets": c.get("markets")} for i, c in enumerate(r.get("link_candidates") or [], start=1)]
        out["_link_candidates_full"] = r.get("link_candidates") or []          # run_selection 이 선택 카드로 옮기고 지운다 (key 포함)
    return out


def _public_offer(offer: dict) -> dict:
    """브라우저용 선택 카드 — key·내부 id·수집본 해시는 넣지 않는다 (offer_id 는 이 대화의 서버 상태를 가리키는 임의 값)."""
    return {
        "offer_id": offer["offer_id"], "kind": offer["kind"], "query": offer.get("query"), "market": offer.get("market"),
        "market_fixed": offer["kind"] == "link",
        "markets": [{"code": m, "label": MARKET_LABELS.get(m, m)} for m in MARKETS],
        "origin": offer.get("origin"),
        "total": offer.get("total"), "returned": offer.get("returned"), "truncated": offer.get("truncated"), "exact_total": offer.get("exact_total"),
        "items": [{k: it.get(k) for k in ("index", "kr_name", "eng_name", "source", "match", "match_kind")} for it in offer["items"]],
    }


def run_selection(ctx: ChatContext, selection) -> dict:
    """사용자의 버튼 선택을 검증하고 규제를 조회한다. 반환 {"ok": bool, "result": dict, "label": str}.
    ok=False 면 조회하지 않았다 (목록 없음·다른 대화·만료·이전 목록·잘못된 순번/시장)."""
    def invalid(message):
        return {"ok": False, "result": {"error": {"kind": "selection_invalid", "message": message}}, "label": None}

    conv = ctx.conv
    if conv is None:
        return invalid("대화 정보가 없어 선택을 확인할 수 없어요. 화면을 새로 고친 뒤 성분을 다시 검색해 주세요.")
    if not isinstance(selection, dict):
        return invalid("선택 정보가 올바르지 않아요.")
    offer_id, index, market = selection.get("offer_id"), selection.get("index"), selection.get("market")
    if not isinstance(offer_id, str) or not OFFER_ID_RE.match(offer_id) or isinstance(index, bool) or not isinstance(index, int):
        return invalid("선택 정보가 올바르지 않아요.")
    offer = SELECTIONS.get(conv, offer_id)
    if offer is None:
        return invalid("이 대화의 최신 후보 목록이 아니거나 만료된 선택이에요. 성분명을 다시 검색해 최신 목록에서 골라 주세요.")
    item = next((it for it in offer["items"] if it["index"] == index), None)
    if item is None:
        return invalid("목록에 없는 후보예요. 최신 목록에서 다시 골라 주세요.")
    if offer["kind"] == "link":
        market = offer["market"]                                   # 연결 후보는 처음 조회한 시장 그대로
    if market not in MARKETS:
        return invalid("국가/시장을 선택해 주세요 (%s)." % ", ".join(MARKETS))

    origin = offer.get("origin") if offer["kind"] == "link" else None
    result = tool_lookup_ingredient_regulation(item["key"], market, origin=origin)
    err_kind = (result.get("error") or {}).get("kind")
    if err_kind in ("stale_key", "not_found"):
        ctx.clear_offers()                                         # 오래된 선택 해제 — 같은 목록으로 다시 조회하지 않음
    full = result.pop("_link_candidates_full", None)
    if result.get("lookup_status") == "link_required" and full:
        first = origin or dict({k: item.get(k) for k in ("kr_name", "eng_name", "source")},
                               link_conflict=(result.get("link") or {}).get("conflict"))
        link_offer = {"offer_id": secrets.token_urlsafe(12), "kind": "link", "query": None, "market": market, "origin": first,
                      "items": [{"index": i, "key": c["key"], "kr_name": c.get("std_name"), "eng_name": c.get("eng_name"), "source": SOURCE_SHORT[regulatory_search.SRC_RSTR],
                                 "match": "연결 근거: " + (" · ".join(c.get("basis") or []) or "—"), "match_kind": None}
                                for i, c in enumerate(full, start=1)]}
        if ctx.add_offer(link_offer):
            result["selection"] = "연결 후보가 채팅창에 버튼으로 표시돼요. 사용자가 맞는 규제 성분을 직접 골라야 조회해요. 대신 고르지 마세요."
    label = "%s%s · %s · %s" % (item.get("kr_name") or item.get("eng_name") or "이름 미제공",
                                " (%s)" % item["eng_name"] if item.get("kr_name") and item.get("eng_name") else "",
                                item.get("source"), MARKET_LABELS.get(market, market))
    return {"ok": True, "result": result, "label": label, "market": market}


def tool_lookup_ingredient_regulation_by_model(market=None, **_ignored) -> dict:
    """모델의 직접 호출은 실행하지 않는다 — 사용자 선택을 서버가 확인한 경우에만 run_selection 이 조회한다."""
    return {"error": {"kind": "selection_required",
                      "message": "규제 조회는 사용자가 채팅창의 후보 버튼으로 성분과 국가를 고른 뒤에만 실행돼요. 조회하지 않았어요."},
            "hint": "search_ingredient 로 후보를 보여 주고, 사용자에게 버튼으로 선택해 달라고 안내해 주세요. 후보를 대신 고르거나 규제 내용을 추측하지 마세요."}


def tool_get_local_time(country_code=None) -> dict:
    now = datetime.now(KST)
    if country_code:
        code = country_code.strip().upper()
        city = home_data.CITY_MAP.get(code)
        if not city:
            return {"error": {"kind": "validation", "message": "지원하는 국가코드: " + ", ".join(home_data.CITY_MAP)}}
        cities = [{"code": code, **city}]
    else:
        cities = home_data.top_export_cities()
    out = []
    for c in cities:
        local = now.astimezone(ZoneInfo(c["tz"]))
        out.append({"country": c["country"], "city": c["name"], "local_time": local.strftime("%Y-%m-%d %H:%M"),
                    "weekday": "월화수목금토일"[local.weekday()],
                    "business_hours": local.weekday() < 5 and 9 <= local.hour < 18,
                    "offset_from_kst_hours": round((local.utcoffset() - now.utcoffset()).total_seconds() / 3600, 1)})
    return {"kst_now": now.strftime("%Y-%m-%d %H:%M"), "items": out}


EXECUTORS = {
    "get_exchange_rates": tool_get_exchange_rates,
    "get_trade_stats": tool_get_trade_stats,
    "search_news": tool_search_news,
    "search_regulation_news": tool_search_regulation_news,
    "search_ingredient": tool_search_ingredient,
    "lookup_ingredient_regulation": tool_lookup_ingredient_regulation_by_model,
    "get_local_time": tool_get_local_time,
}
CONTEXT_TOOLS = {"search_ingredient"}          # 대화 맥락(선택 상태)이 필요한 도구


# --- 결과 길이 제한: JSON 을 문자열 중간에서 자르지 않고 구조를 유지한 채 줄인다 ------------------

def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, path + (i,))
    yield path, obj


def _set(obj, path, value):
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def _path_text(path) -> str:
    out = ""
    for p in path:
        out += "[%d]" % p if isinstance(p, int) else ("." if out else "") + str(p)
    return out


# 줄이지 않는 최상위 필드 — 출처·조회 상태·참고/일부 안내·선택 안내·오류는 결과가 길어도 그대로 전달한다
FIT_PROTECTED = {"_output_truncated", "error", "hint", "status", "status_label", "lookup_status", "market", "selected", "first_selected",
                 "regulation_ingredient", "link", "ingredient_source", "regulation_source", "sources", "collected_at_note",
                 "reference_note", "disclaimer", "notice", "selection", "truncated_note", "entries_note", "candidates_note",
                 "total", "returned", "truncated", "exact_total", "entries_total", "entries_shown", "candidates_sent"}
FIT_RESERVE = 800            # 건수 보정·안내 문구를 붙일 여유


def _family(path) -> str:
    """entries[3].limit_condition → entries[*].limit_condition (같은 종류의 축약은 한 줄로 센다)"""
    return "".join("[*]" if isinstance(p, int) else ("." if i else "") + str(p) for i, p in enumerate(path))


def _reconcile_counts(data: dict, info: dict) -> None:
    """목록을 뺐거나 원문을 줄였으면 표시 건수를 실제 전달 건수에 맞추고, 일부 결과라는 안내를 남긴다."""
    if isinstance(data.get("entries"), list):
        sent = len(data["entries"])
        total = data.get("entries_total", sent)
        cut_text = any(k.startswith("entries[") for k in info["shortened"])
        if "entries_shown" in data:
            data["entries_shown"] = sent
        if sent < total or cut_text:
            data["entries_note"] = ("규제 조건 %d건 중 %d건만 전달했어요%s. 일부 조건만 확인한 것으로 답하고, 전체 조건·원문은 규제 화면에서 확인하도록 안내해 주세요."
                                    % (total, sent, " (일부 원문은 길어서 줄였어요)" if cut_text else ""))
    if isinstance(data.get("candidates"), list) and "candidates" in info["dropped"]:
        sent = len(data["candidates"])
        data["candidates_sent"] = sent
        data["candidates_note"] = ("채팅창 카드에는 후보 %s건이 표시되지만 결과가 길어 모델에는 %d건만 전달했어요 (전체 %s건). "
                                   "전달되지 않은 후보를 추측하지 말고, 사용자에게 카드에서 직접 고르도록 안내해 주세요."
                                   % (data.get("returned", "?"), sent, data.get("total", "?")))
    for name in ("link_candidates", "related_sample"):
        if name in info["dropped"] and isinstance(data.get(name), list):
            data[name + "_sent"] = len(data[name])


def fit_output(result, limit: int = MAX_OUTPUT_CHARS) -> str:
    """limit 을 넘으면 가장 긴 문자열부터 줄이고, 그래도 길면 가장 긴 목록의 뒤 항목을 뺀다. 항상 유효한 JSON 을 돌려준다.
    출처·상태·안내 필드(FIT_PROTECTED)는 줄이지 않고, 줄인 뒤에는 표시 건수(entries_shown 등)를 실제 전달 건수에 맞춘다."""
    text = _dumps(result)
    if len(text) <= limit:
        return text
    data = copy.deepcopy(result) if isinstance(result, dict) else {"data": copy.deepcopy(result)}
    info = {"note": "결과가 길어 일부 문자열·항목을 줄였어요. 줄인 부분은 확인하지 않은 것으로 다루고, 전체를 확인한 것처럼 답하지 마세요.",
            "shortened": {}, "dropped": {}}
    data["_output_truncated"] = info
    budget = max(limit - FIT_RESERVE, limit // 2)

    def finish():
        _reconcile_counts(data, info)
        out = _dumps(data)
        return out if len(out) <= limit else None

    for _ in range(1000):
        if len(_dumps(data)) <= budget:
            out = finish()
            if out is not None:
                return out
            budget -= FIT_RESERVE // 2                              # 보정 문구로 넘쳤으면 조금 더 줄인다
        strings = [(p, v) for p, v in _walk(data) if isinstance(v, str) and p and p[0] not in FIT_PROTECTED]
        p, s = max(strings, key=lambda x: len(x[1]), default=((), ""))
        if len(s) > 120:
            _set(data, p, s[:max(100, len(s) // 2)] + " …(생략)")
            fam = _family(p)
            info["shortened"][fam] = info["shortened"].get(fam, 0) + 1
            continue
        lists = [(p, v) for p, v in _walk(data) if isinstance(v, list) and len(v) > 1 and p and p[0] not in FIT_PROTECTED]
        if lists:
            p, lst = max(lists, key=lambda x: len(_dumps(x[1])))
            lst.pop()
            name = _family(p)
            info["dropped"][name] = info["dropped"].get(name, 0) + 1
            continue
        out = finish()
        if out is not None:
            return out
        break
    return _dumps({"error": {"kind": "too_large", "message": "결과가 너무 커서 전달하지 못했어요. 조건을 좁혀 다시 요청해 주세요."}})


def execute(name: str, arguments: str | dict | None, ctx: ChatContext | None = None) -> str:
    """모델의 function_call 을 실행해 JSON 문자열로 돌려줍니다. 예외는 모델이 읽을 수 있는 오류로 바꿉니다."""
    fn = EXECUTORS.get(name)
    if fn is None:
        return _dumps({"error": {"kind": "unknown_tool", "message": "알 수 없는 도구예요: %s" % name}})
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
        if not isinstance(args, dict):
            args = {}
        args.pop("ctx", None)                       # 모델이 맥락을 만들어 보낼 수 없음
        result = fn(**args, ctx=ctx) if name in CONTEXT_TOOLS else fn(**args)
    except json.JSONDecodeError:
        result = {"error": {"kind": "validation", "message": "도구 인자가 올바른 JSON 이 아니에요. 인자를 다시 만들어 호출해 주세요."}}
    except TypeError as exc:
        result = {"error": {"kind": "validation", "message": "도구 인자가 올바르지 않아요 (%s)." % exc.__class__.__name__}}
    except Exception as exc:  # noqa: BLE001 — 도구 하나가 실패해도 대화는 이어져야 함
        log.warning("도구 실행 실패 %s: %s", name, exc)
        result = {"error": {"kind": "tool_error", "message": "%s 도구 실행 중 오류가 났어요 (%s)." % (name, exc.__class__.__name__)}}
    return fit_output(result)
