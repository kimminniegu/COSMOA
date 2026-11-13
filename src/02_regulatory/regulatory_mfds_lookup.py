"""국가별 인허가 규제 — 식약처 '화장품 사용제한 원료정보' 수집 DB 읽기 전용 조회 모듈 (담당자 B).

- lookup_by_identity(): 규제 화면(app.py [B] /api/regulatory/lookup)과 챗봇이 regulatory_search.lookup_candidate 를 거쳐 쓴다.
  성분 후보 검색·key 검증·성분 연결은 regulatory_search 가 하고, 이 모듈은 검증된 identity 의 규제 기록만 읽는다.
- MARKET_CODES / MARKET_TO_COUNTRY: 화면·/lookup·챗봇의 국가 검증 기준 (KR · EU · US · CN · JP · ASEAN).
- related_items(): 이름을 '포함'만 하는 레코드(염류·유도체·성분군·고시원료명·이명). 확정 규제와 분리해 '적용 여부 확인 필요'로만 전달한다.
수집·재수집은 mfds_use_restriction.py(별도 실행)이며, 이 모듈은 DB 를 만들거나 쓰지 않는다(mode=ro). 외부 API 호출 없음.

- '식별자'(identity) = (INGR_STD_NAME 원문, INGR_ENG_NAME 정규화). 정규화는 앞뒤 공백 제거·영문 대소문자 무시·연속 공백 정리만 한다.
- 이전의 이름·CAS 재매칭 조회 lookup()·identify() 는 K-Beauty 제거 4-3단계(2026-11-11)에서 삭제했다 (실행 코드 미사용).

시장 매핑 (명시적. 새 국가 추가 없음). 원본 '유럽' 은 근거가 없어 EU 에 합치지 않는다.
"""

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SOURCE_PAGE = "https://www.data.go.kr/data/15111772/openapi.do"
SOURCE_LABEL = "식약처 화장품 사용제한 원료정보 (공공데이터포털) 수집 DB"
DATA_SOURCE_TEXT = "식품의약품안전처 '화장품 사용제한 원료정보' 공공데이터 API 를 수집한 로컬 DB. 안내 페이지: " + SOURCE_PAGE + " (개별 법령 원문 링크 아님)"
DISCLAIMER = "규제 참고 자료입니다. 법률·규제 적합성·안전성 판단이 아니며, 수집 시각은 원천 데이터 갱신일이나 법령 개정일이 아닙니다."

# 화면 시장 코드 → 원본 COUNTRY_NAME (수집 DB 값 그대로). 'EU' 는 원본 'EU' 만 — '유럽'(54건)은 별개 값이라 포함하지 않는다.
MARKET_TO_COUNTRY = {
    "KR": ["한국"],
    "EU": ["EU"],
    "US": ["미국"],
    "CN": ["중국"],
    "JP": ["일본"],
    "ASEAN": ["아세안"],
}
COUNTRY_TO_MARKET = {c: m for m, cs in MARKET_TO_COUNTRY.items() for c in cs}
MARKET_CODES = tuple(MARKET_TO_COUNTRY.keys())
COMPLETED = ("completed", "completed_with_warnings")
MFDS_REFRESH_POLICY = "수동 재수집 (자동 갱신 없음)"       # mfds_use_restriction.py collect 를 사람이 실행할 때만 갱신된다
MAX_RELATED = 30


class MfdsLookupError(Exception):
    """kind: db_missing(503) | db_incomplete(503) | db_error(503) | validation(400) | stale_run(409) | identity_missing(404)"""

    STATUS = {"db_missing": 503, "db_incomplete": 503, "db_error": 503, "validation": 400,
              "stale_run": 409, "identity_missing": 404}     # 뒤 두 개는 lookup_by_identity 전용

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.http_status = self.STATUS.get(kind, 503)

    def to_dict(self):
        return {"kind": self.kind, "message": self.message, "source": "mfds"}


def db_path():
    return Path(os.getenv("MFDS_DB_PATH") or (BASE_DIR / "instance" / "regulatory" / "mfds_use_restriction.sqlite"))


def open_readonly(path=None):
    """읽기 전용으로 연다. 파일이 없으면 만들지 않고 db_missing."""
    p = Path(path) if path else db_path()
    if not p.is_file():
        raise MfdsLookupError("db_missing", "식약처 수집 DB 가 서버에 없어요 (instance/regulatory/mfds_use_restriction.sqlite). 수집을 먼저 실행하거나 완료된 DB 를 복사해 주세요. regulatory.md 13항 참고.")
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % p.resolve().as_posix(), uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM runs LIMIT 1")
        conn.execute("SELECT 1 FROM records LIMIT 1")
        return conn
    except sqlite3.Error as exc:
        raise MfdsLookupError("db_error", "식약처 수집 DB 를 읽지 못했어요 (%s). 파일이 손상되었거나 수집 스키마와 달라요." % exc.__class__.__name__)


def latest_completed_run(conn):
    """완료된 수집 실행만 서비스에 쓴다. 없으면 db_incomplete."""
    try:
        row = conn.execute("SELECT * FROM runs WHERE status IN (?, ?) ORDER BY run_id DESC LIMIT 1", COMPLETED).fetchone()
    except sqlite3.Error as exc:
        raise MfdsLookupError("db_error", "식약처 수집 DB 의 실행 기록을 읽지 못했어요 (%s)." % exc.__class__.__name__)
    if row is None:
        raise MfdsLookupError("db_incomplete", "식약처 수집 DB 에 완료된 수집 실행이 없어요. 'mfds_use_restriction.py collect' 로 수집을 끝낸 뒤 사용할 수 있어요.")
    return {"run_id": row["run_id"], "status": row["status"], "started_at": row["started_at"], "finished_at": row["finished_at"],
            "records_saved": row["records_saved"], "total_count_last": row["total_count_last"], "page_size": row["page_size"],
            "source_page": row["source_page"] or SOURCE_PAGE, "note": row["note"]}


def db_status():
    """화면·진단용 요약. 예외를 상태 dict 로 바꾼다."""
    try:
        conn = open_readonly()
        try:
            run = latest_completed_run(conn)
        finally:
            conn.close()
        return {"available": True, "run": run}
    except MfdsLookupError as exc:
        return {"available": False, "kind": exc.kind, "message": exc.message}


# ---------------------------------------------------------------------------
# 정규화·매칭
# ---------------------------------------------------------------------------

def norm_name(t):
    """안전한 정규화만: 앞뒤 공백 제거, 연속 공백 하나로, 영문 대소문자 무시. 숫자·기호·괄호는 그대로."""
    return re.sub(r"\s+", " ", (t or "").strip()).casefold()


def _identity(row):
    return (row["INGR_STD_NAME"] or "", norm_name(row["INGR_ENG_NAME"]))


def _entry(row):
    limit = (row["LIMIT_COND"] or "").strip() or None
    rtype = (row["REGULATE_TYPE"] or "").strip()
    return {
        "country": row["COUNTRY_NAME"],
        "country_code": COUNTRY_TO_MARKET.get(row["COUNTRY_NAME"]),
        "regulate_type": rtype,                      # 원본 그대로 (금지 / 한도 / 한도/금지)
        "notice_ingr_name": row["NOTICE_INGR_NAME"],
        "proviso": (row["PROVIS_ATRCL"] or "").strip() or None,   # 실제 필드 PROVIS_ATRCL
        "limit_condition": limit,                    # 원문 그대로. null 이면 None
        "limit_missing": limit is None and "한도" in rtype,        # '한도'인데 제한사항 없음 → 화면 '상세 제한사항 미제공'
        "source_type": "mfds",
        "std_name": row["INGR_STD_NAME"],
        "eng_name": row["INGR_ENG_NAME"],
        "cas": row["CAS_NO"],
        "record_id": row["id"],
        "page_no": row["page_no"],
    }


def related_items(conn, run_id, countries, kr_name=None, inci_name=None, exclude_identity=None):
    """이름을 '포함'하는 레코드 (염류·유도체·성분군·이명·고시원료명). 확정 규제와 분리해 '적용 여부 확인 필요'로만 쓴다."""
    kr = (kr_name or "").strip()
    inci_n = norm_name(inci_name)
    if not kr and not inci_n:
        return []
    marks = ",".join("?" * len(countries))
    sql = ("SELECT * FROM records WHERE run_id=? AND COUNTRY_NAME IN (%s) AND (" % marks)
    params = [run_id] + list(countries)
    conds = []
    if kr:
        conds += ["instr(INGR_STD_NAME, ?)>0", "instr(COALESCE(INGR_SYNONYM,''), ?)>0", "instr(COALESCE(NOTICE_INGR_NAME,''), ?)>0"]
        params += [kr, kr, kr]
    if inci_n:
        conds += ["instr(lower(INGR_ENG_NAME), ?)>0", "instr(lower(COALESCE(INGR_SYNONYM,'')), ?)>0", "instr(lower(COALESCE(NOTICE_INGR_NAME,'')), ?)>0"]
        params += [inci_n, inci_n, inci_n]
    sql += " OR ".join(conds) + ") ORDER BY INGR_STD_NAME, COUNTRY_NAME LIMIT ?"
    params.append(MAX_RELATED * 4)
    out, seen = [], set()
    for r in conn.execute(sql, params):
        ident = _identity(r)
        if exclude_identity is not None and ident == exclude_identity:
            continue
        key = ident + (r["COUNTRY_NAME"], r["REGULATE_TYPE"])
        if key in seen:
            continue
        seen.add(key)
        where = "표준명" if kr and kr in (r["INGR_STD_NAME"] or "") else ("영문명" if inci_n and inci_n in norm_name(r["INGR_ENG_NAME"]) else ("고시원료명" if (kr and kr in (r["NOTICE_INGR_NAME"] or "")) or (inci_n and inci_n in norm_name(r["NOTICE_INGR_NAME"])) else "이명"))
        out.append({"std_name": r["INGR_STD_NAME"], "eng_name": r["INGR_ENG_NAME"], "country": r["COUNTRY_NAME"], "regulate_type": r["REGULATE_TYPE"], "matched_in": where})
        if len(out) >= MAX_RELATED:
            break
    return out


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _common_result(run, market, countries):
    """lookup_by_identity() 와 regulatory_search.lookup_candidate 가 같은 형식으로 쓰는 출처·날짜·시장 필드."""
    return {
        "source": "mfds",
        "source_label": SOURCE_LABEL,
        "source_page": SOURCE_PAGE,
        "collected_at": run["finished_at"],               # DB 에 기록된 수집 완료 시각 (원천 갱신일 아님). None 이면 화면 '수집 시각 미기록'
        "acquired_at": run["finished_at"],                # 데이터 확보 시각 = 수집 완료 시각 (runs.finished_at). 파일 수정 시각·현재 시각을 쓰지 않는다
        "refresh_policy": MFDS_REFRESH_POLICY,
        "refresh_basis": "프로젝트에 자동 갱신 기능 없음. 재수집은 담당자가 스크립트로 실행",
        "law_dates": None,                                 # 법령 개정·적용일: 응답에 없음 → 미제공
        "collection_run": {"run_id": run["run_id"], "status": run["status"], "records": run["records_saved"], "started_at": run["started_at"], "finished_at": run["finished_at"]},
        "country": {"requested": market, "resolved": " / ".join(countries), "code": market, "country_names": countries},
        "data_source": DATA_SOURCE_TEXT,
        "disclaimer": DISCLAIMER,
        "source_updated_at": None,                         # 원천 갱신일·법령 개정일은 응답에 없음 → 미제공
        "queried_at": _now_iso(),                          # 서비스 조회 시각 = DB 를 읽은 시각 (확보 시각과 다름)
    }


def lookup_by_identity(std_name, eng_name_normalized, market, path=None, expected_run=None):
    """검증된 성분 구분값(identity = (INGR_STD_NAME 원문, 영문명 정규화))으로 규제 기록을 조회한다.

    사용자가 고른 후보(직접 검색·파일 일괄 조회·챗봇)를 서버가 regulatory_search.resolve_key 로 검증한 뒤 쓴다.
    이름을 다시 매칭하지 않으므로 CAS·이름 재검색 때문에 다른 성분으로 바뀌거나 모호해지지 않는다.

    expected_run: {"run_id", "started_at", "finished_at"} — 검증 당시 수집본과 다르면 stale_run 오류.
    lookup_status: found (선택 시장 기록 있음) | no_market_record (성분은 있으나 선택 시장 기록 없음)
    """
    if market not in MARKET_TO_COUNTRY:
        raise MfdsLookupError("validation", "식약처 수집 DB 조회는 %s 시장만 연결되어 있어요." % ", ".join(MARKET_CODES))
    ident = (std_name or "", norm_name(eng_name_normalized))
    conn = open_readonly(path)
    try:
        run = latest_completed_run(conn)
        if expected_run is not None and any(expected_run.get(k) != run[k] for k in ("run_id", "started_at", "finished_at")):
            raise MfdsLookupError("stale_run", "규제 DB 수집본이 후보를 검증한 뒤 바뀌었어요. 성분을 다시 검색해 선택해 주세요.")
        rid = run["run_id"]
        countries = MARKET_TO_COUNTRY[market]
        try:
            rows = [r for r in conn.execute("SELECT * FROM records WHERE run_id=? AND COALESCE(INGR_STD_NAME,'')=? ORDER BY page_no, row_index", (rid, ident[0]))
                    if _identity(r) == ident]
            if not rows:
                raise MfdsLookupError("identity_missing", "현재 규제 DB 수집본에 이 성분이 없어요. 다시 검색해 주세요.")
            entries = [_entry(r) for r in rows if r["COUNTRY_NAME"] in countries]      # 조건별 레코드를 모두 (합치지 않음)
            markets_listed = sorted({r["COUNTRY_NAME"] for r in rows})
            related = related_items(conn, rid, countries, ident[0] or None, ident[1] or None, exclude_identity=ident)
        except sqlite3.Error as exc:
            raise MfdsLookupError("db_error", "식약처 수집 DB 를 읽지 못했어요 (%s)." % exc.__class__.__name__)
    finally:
        conn.close()
    first = rows[0]
    lookup_status = "found" if entries else "no_market_record"
    note = None if entries else (
        "이 성분은 식약처 규제 DB 에 있지만 선택한 시장(%s)의 기록은 없어요. 허용·안전·규제 없음을 뜻하지 않아요." % " / ".join(countries))
    out = _common_result(run, market, countries)
    out.update({
        "ingredient": {"code": None, "kr_name": (first["INGR_STD_NAME"] or "").strip() or None, "inci_name": (first["INGR_ENG_NAME"] or "").strip() or None,
                       "cas_numbers": ", ".join(sorted({(r["CAS_NO"] or "").strip() for r in rows if (r["CAS_NO"] or "").strip()})) or None},
        "link_status": "confirmed",
        "link_basis": ["선택한 규제 성분"],
        "link_conflict": None,
        "link_candidates": [],
        "matched_identity": {"std_name": ident[0], "eng_name": first["INGR_ENG_NAME"]},
        "identity": {"std_name": ident[0], "eng_name_normalized": ident[1]},
        "lookup_status": lookup_status,
        "result_status": "mfds_" + lookup_status,
        "result_note": note,
        "entries": entries,
        "related": related,
        "markets_listed": markets_listed,
    })
    return out
