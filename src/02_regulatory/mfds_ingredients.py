"""국가별 인허가 규제 — 식약처 '화장품 원료성분정보' 공공데이터 API 수집·분석 스크립트 (담당자 B).

목적: K-Beauty API 의 성분 검색·자동완성·파일 성분 매칭을 대체할 성분 사전(DB)을 만든다.
      규제 DB(mfds_use_restriction.sqlite)와 별개 DB 다. app.py 에서 import 하지 않으며 자동 실행되지 않는다.

공식 안내: https://www.data.go.kr/data/15111774/openapi.do  (수정일 2025-08-12, 갱신주기 '실시간', 이용허락범위 제한 없음)
호출:     GET https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01
          ?serviceKey=<Decoding 키> &pageNo=N &numOfRows=M &type=json   (선택: INGR_KOR_NAME 표준명 필터 — 수집에는 쓰지 않음)
확인된 응답 (2026-11-09 probe): {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
             "body": {"pageNo", "totalCount", "numOfRows", "items": [ {INGR_KOR_NAME, INGR_ENG_NAME, CAS_NO,
             ORIGIN_MAJOR_KOR_NAME, INGR_SYNONYM}, ... ]}}
  - items 는 배열. 원천 식별자(성분 코드)는 응답에 없다 → 내부 id 는 수집본 안에서만 의미가 있다.
  - CAS_NO 는 '328-39-2(DL-)\\r,61-90-5(L-)' 처럼 복수·주석·개행이 섞인 원문 그대로 온다. 저장 시 고치지 않는다.
  - 명세에 없는 필드가 오면 raw_json 과 pages.item_keys 에 그대로 남는다.

인증키: .env 의 MFDS_API_KEY (규제 API 와 같은 키). 키·키가 든 URL 은 저장·로그·오류 메시지에 넣지 않는다.

저장: instance/regulatory/mfds_ingredients.sqlite (Git 제외). MFDS_INGREDIENT_DB_PATH 로만 바꾼다 (규제용 MFDS_DB_PATH 는 읽지 않음).
  규제 DB 경로(MFDS_DB_PATH·기본 instance 경로·배포용 data 경로)와 같거나, 다른 데이터셋 DB 파일이면 쓰지 않고 중단한다.
  meta    : dataset 표시 (이 DB 가 원료성분정보 DB 임을 확인)
  runs    : 수집 실행 (running | interrupted | completed | completed_with_warnings | aborted)
            interrupted = 네트워크·한도·인증·사용자 중단 등 → 다음 collect 가 이어받음 / aborted = 구조·무결성 문제 → 원인 확인 후 --new-run
  pages   : 페이지 기록 (요청/응답 건수·totalCount·resultCode·HTTP 상태·내용 해시·실제 필드 키)
  records : 원본 5개 필드 그대로 + raw_json + run_id/page_no/row_index/fetched_at
  페이지 하나가 트랜잭션 단위다. 재개는 완료된 마지막 페이지 다음부터.

사용법 (프로젝트 루트, tdenv):
  python -u src/02_regulatory/mfds_ingredients.py probe                # 5건 호출로 연결·구조 확인 (저장 안 함)
  python -u src/02_regulatory/mfds_ingredients.py collect              # 수집 (running/interrupted 실행이 있으면 이어받음)
  python -u src/02_regulatory/mfds_ingredients.py collect --new-run    # 새 실행으로 처음부터
  python -u src/02_regulatory/mfds_ingredients.py status | analyze | find 글리세린 Glycerin   (API 호출 없음)
환경변수(선택): MFDS_INGREDIENT_DB_PATH, MFDS_INGREDIENT_PAGE_SIZE(기본 100), MFDS_INGREDIENT_REQUEST_INTERVAL(초, 기본 0.3),
               MFDS_TIMEOUT(초, 기본 30), MFDS_MAX_RETRIES(기본 3)
"""

import argparse
import functools
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

print = functools.partial(print, flush=True)   # 백그라운드·리다이렉트에서도 진행 로그가 바로 보이게

BASE_DIR = Path(__file__).resolve().parents[2]
DATASET = "mfds_cosmetic_ingredients"
SOURCE_PAGE = "https://www.data.go.kr/data/15111774/openapi.do"
BASE_URL = "https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01"
ENDPOINT = "/getCsmtcsIngdCpntInfoService01"
FIELDS = ("INGR_KOR_NAME", "INGR_ENG_NAME", "CAS_NO", "ORIGIN_MAJOR_KOR_NAME", "INGR_SYNONYM")
DEFAULT_DB = BASE_DIR / "instance" / "regulatory" / "mfds_ingredients.sqlite"
RESTRICTION_DB_PATHS = (BASE_DIR / "instance" / "regulatory" / "mfds_use_restriction.sqlite",
                        BASE_DIR / "data" / "regulatory" / "mfds_use_restriction.sqlite")

PORTAL_CODES = {
    "00": "NORMAL_SERVICE", "01": "APPLICATION_ERROR", "02": "DB_ERROR", "03": "NODATA_ERROR", "04": "HTTP_ERROR",
    "05": "SERVICETIME_OUT", "10": "INVALID_REQUEST_PARAMETER_ERROR", "11": "NO_MANDATORY_REQUEST_PARAMETERS_ERROR",
    "12": "NO_OPENAPI_SERVICE_ERROR", "20": "SERVICE_ACCESS_DENIED_ERROR", "22": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "30": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "31": "DEADLINE_HAS_EXPIRED_ERROR", "32": "UNREGISTERED_IP_ERROR",
    "33": "UNSIGNED_CALL_ERROR", "99": "UNKNOWN_ERROR",
}
AUTH_CODES = {"20", "30", "31", "32", "33"}
NO_RETRY_CODES = AUTH_CODES | {"22", "10", "11", "12"}
TRANSIENT_CODES = {"01", "02", "04", "05", "99"}
# 이어받을 수 있는 중단 사유 → interrupted. 그 외(구조·무결성·결과 코드·페이지 크기·설정) → aborted
RESUMABLE_KINDS = {"http", "limit", "auth", "count_change", "interrupt"}
RESUMABLE_STATUSES = ("running", "interrupted")
COMPLETED = ("completed", "completed_with_warnings")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Abort(Exception):
    """kind: config | auth | limit | http | structure | result | integrity | count_change | page_size | interrupt"""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


class Transient(Exception):
    """재시도 가능한 일시 오류 (시간 초과·연결·5xx·포털 일시 오류)"""


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env", override=False)
    except ImportError:
        pass


def _same_path(a, b):
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def resolve_db_path():
    """성분 DB 경로. 규제 DB 경로와 같으면 Abort(config)."""
    p = Path(os.getenv("MFDS_INGREDIENT_DB_PATH") or DEFAULT_DB)
    guarded = list(RESTRICTION_DB_PATHS)
    if os.getenv("MFDS_DB_PATH"):
        guarded.append(Path(os.getenv("MFDS_DB_PATH")))
    for g in guarded:
        if _same_path(p, g):
            raise Abort("config", "성분 DB 저장 경로가 규제 DB(%s) 와 같아요. MFDS_INGREDIENT_DB_PATH 를 다른 파일로 지정해 주세요." % Path(g).name)
    return p


def config(require_key=True):
    load_env()
    key = (os.getenv("MFDS_API_KEY") or "").strip()
    if require_key and not key:
        raise Abort("config", ".env 에 MFDS_API_KEY 가 없어요. (값은 어디에도 출력하지 않아요)")
    return {
        "key": key,
        "page_size": int(os.getenv("MFDS_INGREDIENT_PAGE_SIZE", "100")),
        "interval": float(os.getenv("MFDS_INGREDIENT_REQUEST_INTERVAL", "0.3")),
        "timeout": float(os.getenv("MFDS_TIMEOUT", "30")),
        "retries": int(os.getenv("MFDS_MAX_RETRIES", "3")),
        "db_path": resolve_db_path(),
    }


def public_url():
    """저장·보고용 주소 (인증키 없음)"""
    return BASE_URL + ENDPOINT


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_get(session, params, timeout):
    """실제 GET. 테스트에서 바꿔 끼운다. (status_code, text). 네트워크 예외는 Transient (예외 메시지에 URL 이 있어 그대로 쓰지 않음)."""
    import requests
    try:
        r = session.get(public_url(), params=params, timeout=(min(10.0, timeout), timeout))
    except requests.exceptions.Timeout:
        raise Transient("timeout")
    except requests.exceptions.RequestException as exc:
        raise Transient("connection:" + exc.__class__.__name__)
    return r.status_code, r.text


def _code_abort(code, label):
    kind = "auth" if code in AUTH_CODES else ("limit" if code == "22" else "result")
    return Abort(kind, "%s resultCode=%s (%s)" % (label, code, PORTAL_CODES.get(code, "?")))


def parse_response(status, text):
    """HTTP 상태 + 본문 → dict. 오류·예상 밖 구조는 '빈 데이터'로 취급하지 않고 Abort/Transient."""
    if status in (401, 403):
        raise Abort("auth", "인증·접근 거부 응답(HTTP %d). 인증키·활용신청 승인 상태를 확인해 주세요." % status)
    if status == 429:
        raise Abort("limit", "호출 한도 초과 응답(HTTP 429). 진행 내용을 보존하고 멈춰요.")
    if status >= 500:
        raise Transient("http_%d" % status)
    if status != 200:
        raise Abort("http", "예상 밖 HTTP 상태 %d" % status)
    stripped = (text or "").lstrip()
    if stripped.startswith("<"):
        m = re.search(r"<returnReasonCode>\s*(\d+)\s*</returnReasonCode>", stripped)
        code = m.group(1) if m else None
        if code in NO_RETRY_CODES:
            raise _code_abort(code, "포털 오류 응답(XML)")
        if code in TRANSIENT_CODES:
            raise Transient("portal_%s" % code)
        raise Abort("structure", "JSON 이 아닌 응답(XML). returnReasonCode=%s" % code)
    try:
        data = json.loads(stripped)
    except ValueError:
        raise Abort("structure", "JSON 으로 해석할 수 없는 응답 (길이 %d)" % len(stripped))
    if not isinstance(data, dict) or not isinstance(data.get("header"), dict) or not isinstance(data.get("body"), dict):
        raise Abort("structure", "응답에 header/body 객체가 없어요.")
    header, body = data["header"], data["body"]
    code = str(header.get("resultCode", "")).strip()
    msg = str(header.get("resultMsg", "")).strip()
    if code != "00":
        if code in NO_RETRY_CODES:
            raise _code_abort(code, "API 오류")
        if code in TRANSIENT_CODES:
            raise Transient("portal_%s" % code)
        raise Abort("result", "resultCode=%s resultMsg=%s — 정상 코드(00)가 아니라 중단해요." % (code, msg))
    items = body.get("items")
    if items is None or items == "":
        items = []
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise Abort("structure", "body.items 가 객체 배열이 아니에요 (type=%s)." % type(items).__name__)
    try:
        total = int(body.get("totalCount"))
    except (TypeError, ValueError):
        raise Abort("structure", "body.totalCount 를 읽을 수 없어요.")
    return {"total_count": total, "items": items, "result_code": code, "result_msg": msg,
            "page_no": body.get("pageNo"), "num_rows": body.get("numOfRows")}


def fetch_page(session, cfg, page_no, num_rows, counter):
    """한 페이지. 일시 오류는 제한 재시도, 인증·한도·구조 오류는 즉시 Abort."""
    params = OrderedDict([("serviceKey", cfg["key"]), ("pageNo", page_no), ("numOfRows", num_rows), ("type", "json")])
    attempt = 0
    while True:
        attempt += 1
        counter["calls"] += 1
        try:
            status, text = _http_get(session, params, cfg["timeout"])
            parsed = parse_response(status, text)
            parsed["http_status"] = status
            return parsed
        except Transient as exc:
            if attempt > cfg["retries"]:
                raise Abort("http", "%d쪽 일시 오류가 %d회 반복됐어요 (%s)." % (page_no, attempt, exc))
            time.sleep(min(8.0, 1.5 * attempt))


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL,                 -- running | interrupted | completed | completed_with_warnings | aborted
  source_url TEXT NOT NULL,             -- 인증키 없는 주소
  source_page TEXT NOT NULL,
  page_size INTEGER NOT NULL,
  total_count_first INTEGER, total_count_last INTEGER,
  pages_done INTEGER NOT NULL DEFAULT 0, records_saved INTEGER NOT NULL DEFAULT 0, calls_made INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
CREATE TABLE IF NOT EXISTS pages (
  run_id INTEGER NOT NULL, page_no INTEGER NOT NULL,
  fetched_at TEXT NOT NULL, http_status INTEGER, result_code TEXT, result_msg TEXT,
  num_rows_requested INTEGER, num_rows_returned INTEGER, total_count INTEGER, content_hash TEXT,
  item_keys TEXT,                       -- 이 페이지 응답 항목에 실제로 있던 필드명 (JSON 배열)
  PRIMARY KEY (run_id, page_no)
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL, page_no INTEGER NOT NULL, row_index INTEGER NOT NULL, fetched_at TEXT NOT NULL,
  INGR_KOR_NAME TEXT, INGR_ENG_NAME TEXT, CAS_NO TEXT, ORIGIN_MAJOR_KOR_NAME TEXT, INGR_SYNONYM TEXT,
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingr_run ON records(run_id, page_no);
CREATE INDEX IF NOT EXISTS idx_ingr_kor ON records(INGR_KOR_NAME);
CREATE INDEX IF NOT EXISTS idx_ingr_eng ON records(INGR_ENG_NAME);
CREATE INDEX IF NOT EXISTS idx_ingr_cas ON records(CAS_NO);
"""


def open_db(path, readonly=False):
    """쓰기용: 다른 데이터셋 DB(예: 규제 DB) 파일이면 아무것도 쓰지 않고 중단한다."""
    path = Path(path)
    if readonly:
        if not path.is_file():
            raise Abort("config", "성분 DB 가 없어요: %s (먼저 collect)" % path)
        conn = sqlite3.connect("file:%s?mode=ro" % path.resolve().as_posix(), uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    if path.is_file():
        chk = sqlite3.connect("file:%s?mode=ro" % path.resolve().as_posix(), uri=True)
        try:
            tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            ds = chk.execute("SELECT value FROM meta WHERE key='dataset'").fetchone() if "meta" in tables else None
        finally:
            chk.close()
        if tables and (ds is None or ds[0] != DATASET):
            raise Abort("config", "%s 는 원료성분정보 DB 가 아니에요 (dataset 표시 없음). 다른 DB 에 쓰지 않게 중단해요." % path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    with conn:
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('dataset', ?)", (DATASET,))
    return conn


def content_hash(items):
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def save_page(conn, run_id, page_no, parsed, requested, fetched_at):
    """페이지 하나를 트랜잭션으로 저장. 이미 있으면 저장하지 않는다(재개 중복 방지)."""
    items = parsed["items"]
    keys = sorted({k for it in items for k in it})
    with conn:
        if conn.execute("SELECT 1 FROM pages WHERE run_id=? AND page_no=?", (run_id, page_no)).fetchone():
            return False
        conn.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (run_id, page_no, fetched_at, parsed.get("http_status"), parsed["result_code"], parsed["result_msg"],
                      requested, len(items), parsed["total_count"], content_hash(items), json.dumps(keys)))
        conn.executemany(
            "INSERT INTO records (run_id, page_no, row_index, fetched_at, %s, raw_json) VALUES (?,?,?,?,%s,?)" % (", ".join(FIELDS), ",".join("?" * len(FIELDS))),
            [(run_id, page_no, i, fetched_at) + tuple(it.get(f) for f in FIELDS) + (json.dumps(it, ensure_ascii=False),) for i, it in enumerate(items)])
        conn.execute("UPDATE runs SET pages_done=pages_done+1, records_saved=records_saved+?, total_count_last=? WHERE run_id=?",
                     (len(items), parsed["total_count"], run_id))
    return True


def finish_run(conn, run_id, status, calls, note=None, finished=True):
    with conn:
        conn.execute("UPDATE runs SET status=?, finished_at=?, calls_made=calls_made+?, note=COALESCE(?, note) WHERE run_id=?",
                     (status, now_iso() if finished else None, calls, note, run_id))


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------

def probe(cfg, num_rows=5):
    """소량 호출 1회. 저장하지 않는다."""
    import requests
    counter = {"calls": 0}
    with requests.Session() as s:
        parsed = fetch_page(s, cfg, 1, num_rows, counter)
    print("연결 확인: HTTP %s resultCode=%s (%s)" % (parsed["http_status"], parsed["result_code"], parsed["result_msg"]))
    print("totalCount=%s, 요청 %d건 → 응답 %d건, body.pageNo=%s numOfRows=%s" % (parsed["total_count"], num_rows, len(parsed["items"]), parsed["page_no"], parsed["num_rows"]))
    keys = sorted({k for it in parsed["items"] for k in it})
    print("응답 필드:", keys)
    print("명세 5개 필드 누락:", [f for f in FIELDS if f not in keys] or "없음", "| 명세 밖 필드:", [k for k in keys if k not in FIELDS] or "없음")
    print("호출 횟수:", counter["calls"])
    return parsed


def collect(cfg, new_run=False, max_pages=None, allow_count_change=False, log=print):
    """페이지 순차 수집. running/interrupted 실행이 있고 page_size 가 같으면 이어받는다."""
    import requests
    conn = open_db(cfg["db_path"])
    page_size = cfg["page_size"]
    counter = {"calls": 0}
    run, run_id = None, None
    if not new_run:
        run = conn.execute("SELECT * FROM runs WHERE status IN (?,?) ORDER BY run_id DESC LIMIT 1", RESUMABLE_STATUSES).fetchone()
        if run and run["page_size"] != page_size:
            conn.close()
            raise Abort("page_size", "이어받을 실행(run %d)의 페이지 크기는 %d 인데 지금 설정은 %d 예요. --new-run 으로 새로 시작하거나 크기를 맞춰 주세요."
                        % (run["run_id"], run["page_size"], page_size))
    try:
        with requests.Session() as session:
            if run is None:
                fetched_at = now_iso()
                first = fetch_page(session, cfg, 1, page_size, counter)
                total = first["total_count"]
                if len(first["items"]) != min(page_size, total):
                    raise Abort("page_size", "요청한 페이지 크기 %d 가 적용되지 않았어요 (응답 %d건, totalCount %d)." % (page_size, len(first["items"]), total))
                with conn:
                    cur = conn.execute("INSERT INTO runs (started_at, status, source_url, source_page, page_size, total_count_first, total_count_last) VALUES (?,?,?,?,?,?,?)",
                                       (fetched_at, "running", public_url(), SOURCE_PAGE, page_size, total, total))
                    run_id = cur.lastrowid
                save_page(conn, run_id, 1, first, page_size, fetched_at)
                log("run %d 시작: totalCount=%d, 페이지 크기 %d → 예상 %d쪽. 1쪽 저장(%d건)" % (run_id, total, page_size, math.ceil(total / page_size), len(first["items"])))
                next_page, prev_hash, warnings = 2, content_hash(first["items"]), []
            else:
                run_id = run["run_id"]
                total = run["total_count_first"]
                last = conn.execute("SELECT MAX(page_no) AS p FROM pages WHERE run_id=?", (run_id,)).fetchone()["p"] or 0
                next_page = last + 1
                row = conn.execute("SELECT content_hash FROM pages WHERE run_id=? AND page_no=?", (run_id, last)).fetchone()
                prev_hash = row["content_hash"] if row else None
                warnings = [w for w in (run["note"] or "").split(" / ") if w.startswith("경고:")]
                with conn:
                    conn.execute("UPDATE runs SET status='running', finished_at=NULL WHERE run_id=?", (run_id,))
                log("run %d 재개(이전 상태 %s): 완료 %d쪽까지, %d쪽부터 (페이지 크기 %d, 시작 totalCount %d)" % (run_id, run["status"], last, next_page, page_size, total))
            total_pages = math.ceil(total / page_size)
            done_this_call = 0
            page_no = next_page
            while page_no <= total_pages:
                if max_pages is not None and done_this_call >= max_pages:
                    finish_run(conn, run_id, "interrupted", counter["calls"], "--max-pages %d 도달 — 재개 가능" % max_pages, finished=False)
                    log("--max-pages %d 에 도달해 멈춰요 (run %d interrupted, 재개 가능)" % (max_pages, run_id))
                    return run_id
                time.sleep(cfg["interval"])
                fetched_at = now_iso()
                parsed = fetch_page(session, cfg, page_no, page_size, counter)
                if parsed["total_count"] != total:
                    msg = "경고: totalCount 변화 시작 %d → %d쪽 응답 %d" % (total, page_no, parsed["total_count"])
                    if run is not None and page_no == next_page and not allow_count_change:
                        raise Abort("count_change", msg + " — 재개 조건이 달라졌어요. 원인 확인 후 --new-run 또는 --allow-count-change.")
                    if msg not in warnings:
                        warnings.append(msg)
                        log(msg)
                h = content_hash(parsed["items"])
                if parsed["items"] and h == prev_hash:
                    raise Abort("integrity", "%d쪽 내용이 직전 쪽과 같아요(반복 페이지)." % page_no)
                if not parsed["items"] and page_no < total_pages:
                    raise Abort("integrity", "%d쪽이 마지막 쪽(%d)보다 앞인데 비어 있어요." % (page_no, total_pages))
                if page_no < total_pages and len(parsed["items"]) != page_size:
                    warnings.append("경고: %d쪽 응답 %d건 ≠ 페이지 크기 %d" % (page_no, len(parsed["items"]), page_size))
                    log(warnings[-1])
                save_page(conn, run_id, page_no, parsed, page_size, fetched_at)
                prev_hash = h
                done_this_call += 1
                if page_no % 25 == 0 or page_no == total_pages:
                    log("  %d/%d쪽 저장 (이번 호출 %d회)" % (page_no, total_pages, counter["calls"]))
                page_no += 1
            saved = conn.execute("SELECT COUNT(*) AS c FROM records WHERE run_id=?", (run_id,)).fetchone()["c"]
            last_total = conn.execute("SELECT total_count FROM pages WHERE run_id=? ORDER BY page_no DESC LIMIT 1", (run_id,)).fetchone()["total_count"]
            if saved != last_total:
                warnings.append("경고: 저장 %d건 ≠ 마지막 totalCount %d" % (saved, last_total))
            status = "completed_with_warnings" if warnings else "completed"
            finish_run(conn, run_id, status, counter["calls"], " / ".join(warnings) if warnings else None)
            log("완료: run %d status=%s 저장 %d건, totalCount(마지막) %d, 이번 호출 %d회" % (run_id, status, saved, last_total, counter["calls"]))
            return run_id
    except Abort as exc:
        if run_id is not None:
            st = "interrupted" if exc.kind in RESUMABLE_KINDS else "aborted"
            finish_run(conn, run_id, st, counter["calls"], "%s: %s" % (exc.kind, exc.message), finished=(st == "aborted"))
            log("중단(%s) → run %d %s. 저장된 페이지는 보존했어요. 이번 호출 %d회." % (exc.kind, run_id, st, counter["calls"]))
        else:
            log("중단(%s): 실행 기록 생성 전이라 저장된 것이 없어요. 호출 %d회." % (exc.kind, counter["calls"]))
        raise
    except KeyboardInterrupt:
        if run_id is not None:
            finish_run(conn, run_id, "interrupted", counter["calls"], "interrupt: 사용자 중단 — 재개 가능", finished=False)
        log("사용자 중단. 완료한 페이지는 보존했고 다음 collect 에서 이어받아요.")
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 상태·분석·검색 (API 호출 없음, 읽기 전용)
# ---------------------------------------------------------------------------

def latest_completed(conn):
    return conn.execute("SELECT * FROM runs WHERE status IN (?,?) ORDER BY run_id DESC LIMIT 1", COMPLETED).fetchone()


def status(cfg):
    conn = open_db(cfg["db_path"], readonly=True)
    for r in conn.execute("SELECT * FROM runs ORDER BY run_id"):
        print("run %d | %s | 시작 %s | 종료 %s | 페이지 크기 %d | 완료 %d쪽 | 저장 %d건 | totalCount %s→%s | 호출 %d | %s"
              % (r["run_id"], r["status"], r["started_at"], r["finished_at"] or "-", r["page_size"], r["pages_done"], r["records_saved"],
                 r["total_count_first"], r["total_count_last"], r["calls_made"], r["note"] or ""))
    conn.close()


def norm(t):
    return re.sub(r"\s+", " ", (t or "").strip()).casefold()


def _is_latin(ch):
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def split_names(text):
    """영문명·이명 칸의 쉼표 나열을 나눈다 (예: 'Water,Aqua'). 원문은 바꾸지 않고 검색용으로만 쓴다.
    화학명 위치 표기의 쉼표는 나누지 않는다: 숫자·프라임과 숫자 사이 (1,2-, 5,2',5'-), 한 글자 라틴 문자 사이 (N,N-).
    '/' 는 코폴리머·부위 나열처럼 이름의 일부라 나누지 않는다."""
    s = text or ""
    out, start = [], 0
    for i, ch in enumerate(s):
        if ch != ",":
            continue
        prev = s[i - 1] if i > 0 else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if (prev.isdigit() or (prev and prev in "'′")) and nxt.isdigit():
            continue
        prev2 = s[i - 2] if i > 1 else ""
        nxt2 = s[i + 2] if i + 2 < len(s) else ""
        if _is_latin(prev) and not _is_latin(prev2) and _is_latin(nxt) and not _is_latin(nxt2):
            continue
        out.append(s[start:i])
        start = i + 1
    out.append(s[start:])
    return [p.strip() for p in out if p.strip()]


def analyze(cfg, run_id=None):
    conn = open_db(cfg["db_path"], readonly=True)
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone() if run_id else latest_completed(conn)
    if run is None:
        conn.close()
        return None
    rid = run["run_id"]
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    out = OrderedDict()
    out["run"] = dict(run)
    out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    pages = q("SELECT * FROM pages WHERE run_id=? ORDER BY page_no", rid)
    out["records"] = q("SELECT COUNT(*) c FROM records WHERE run_id=?", rid)[0]["c"]
    out["pages"] = len(pages)
    out["expected_pages"] = math.ceil((run["total_count_last"] or 0) / run["page_size"])
    nums = {p["page_no"] for p in pages}
    out["page_gaps"] = sorted(set(range(1, out["expected_pages"] + 1)) - nums)
    hc = Counter(p["content_hash"] for p in pages if p["num_rows_returned"])
    out["repeated_pages"] = [h[:12] for h, c in hc.items() if c > 1]
    out["short_pages"] = [(p["page_no"], p["num_rows_returned"]) for p in pages[:-1] if p["num_rows_returned"] != run["page_size"]]
    out["total_count_values"] = sorted({p["total_count"] for p in pages})
    out["result_codes"] = dict(Counter(p["result_code"] for p in pages))
    out["count_match"] = out["records"] == run["total_count_last"]
    out["item_keys"] = sorted({k for p in pages for k in json.loads(p["item_keys"] or "[]")})
    out["empty"] = OrderedDict()
    for f in FIELDS:
        n = q("SELECT COUNT(*) c FROM records WHERE run_id=? AND %s IS NULL" % f, rid)[0]["c"]
        b = q("SELECT COUNT(*) c FROM records WHERE run_id=? AND %s IS NOT NULL AND trim(%s)=''" % (f, f), rid)[0]["c"]
        out["empty"][f] = (n, b)
    dup_all = q("SELECT COUNT(*) c FROM (SELECT 1 FROM records WHERE run_id=? GROUP BY %s HAVING COUNT(*)>1)" % ", ".join(FIELDS), rid)[0]["c"]
    out["dup_all_fields_groups"] = dup_all
    kor = Counter(r["INGR_KOR_NAME"] for r in q("SELECT INGR_KOR_NAME FROM records WHERE run_id=? AND INGR_KOR_NAME IS NOT NULL", rid))
    out["kor_distinct"] = len(kor)
    out["kor_dup_groups"] = sum(1 for c in kor.values() if c > 1)
    out["kor_dup_examples"] = [k for k, c in kor.items() if c > 1][:5]
    eng = Counter(norm(r["INGR_ENG_NAME"]) for r in q("SELECT INGR_ENG_NAME FROM records WHERE run_id=? AND INGR_ENG_NAME IS NOT NULL AND trim(INGR_ENG_NAME)<>''", rid))
    out["eng_distinct"] = len(eng)
    out["eng_dup_groups"] = sum(1 for c in eng.values() if c > 1)
    out["eng_dup_extra"] = sum(c - 1 for c in eng.values() if c > 1)
    out["eng_dup_examples"] = [k for k, c in eng.most_common(5) if c > 1]
    cas_re = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
    toks = Counter()
    multi = 0
    for r in q("SELECT CAS_NO FROM records WHERE run_id=? AND CAS_NO IS NOT NULL", rid):
        t = set(cas_re.findall(r["CAS_NO"]))
        multi += len(t) > 1
        toks.update(t)
    out["cas_multi_records"] = multi
    out["cas_tokens_distinct"] = len(toks)
    out["cas_token_shared"] = sum(1 for c in toks.values() if c > 1)
    out["cas_with_newline"] = q("SELECT COUNT(*) c FROM records WHERE run_id=? AND (instr(CAS_NO, char(13))>0 OR instr(CAS_NO, char(10))>0)", rid)[0]["c"]
    out["cas_nonstandard"] = q("SELECT COUNT(*) c FROM records WHERE run_id=? AND CAS_NO IS NOT NULL", rid)[0]["c"] - \
        sum(1 for r in q("SELECT CAS_NO FROM records WHERE run_id=? AND CAS_NO IS NOT NULL", rid) if cas_re.fullmatch(r["CAS_NO"].strip()))
    conn.close()
    return out


def print_analysis(out):
    if not out:
        print("완료된 수집 실행이 없어요. (미완료 실행은 status 로 확인)")
        return
    r = out["run"]
    print("== run %d (%s) %s ~ %s, 호출 %d회, 페이지 크기 %d | integrity_check=%s" % (r["run_id"], r["status"], r["started_at"], r["finished_at"], r["calls_made"], r["page_size"], out["integrity"]))
    print("   저장 %d건 / totalCount 시작 %s · 마지막 %s / 페이지 %d쪽(예상 %d) / 건수 일치 %s / resultCode %s"
          % (out["records"], r["total_count_first"], r["total_count_last"], out["pages"], out["expected_pages"], out["count_match"], out["result_codes"]))
    print("   페이지 누락:", out["page_gaps"] or "없음", "| 반복:", out["repeated_pages"] or "없음", "| 짧은 페이지:", out["short_pages"] or "없음", "| totalCount 값:", out["total_count_values"])
    if r["note"]:
        print("   메모:", r["note"])
    print("== 실제 응답 필드:", out["item_keys"])
    print("== 빈 값 (NULL / 공백 문자열)")
    for f, (n, b) in out["empty"].items():
        print("   %-22s %6d / %d" % (f, n, b))
    print("== 중복")
    print("   5개 필드 전부 동일 그룹 %d | 한글명 고유 %d, 중복 그룹 %d %s" % (out["dup_all_fields_groups"], out["kor_distinct"], out["kor_dup_groups"], out["kor_dup_examples"]))
    print("   영문명(대소문자·공백 무시) 고유 %d, 중복 그룹 %d(추가 %d건) 예: %s" % (out["eng_distinct"], out["eng_dup_groups"], out["eng_dup_extra"], out["eng_dup_examples"]))
    print("== CAS: 고유 토큰 %d | 여러 레코드가 공유하는 토큰 %d | 복수 CAS 레코드 %d | 개행 포함 %d | 표준형(숫자-숫자-숫자) 단일 아님 %d"
          % (out["cas_tokens_distinct"], out["cas_token_shared"], out["cas_multi_records"], out["cas_with_newline"], out["cas_nonstandard"]))


def find(cfg, terms, run_id=None):
    """정확 일치(한글명·영문명 전체·영문명 항목·이명 항목·CAS 토큰)와 포함 일치를 구분해 보여준다.
    한글명은 나누지 않는다. 검색 결과는 사용 허용·안전 판정이 아니다."""
    conn = open_db(cfg["db_path"], readonly=True)
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone() if run_id else latest_completed(conn)
    if run is None:
        print("완료된 수집 실행이 없어요.")
        conn.close()
        return {}
    rows = conn.execute("SELECT * FROM records WHERE run_id=?", (run["run_id"],)).fetchall()
    conn.close()
    results = {}
    for term in terms:
        t = norm(term)
        exact, contains = [], []
        for r in rows:
            basis = []
            if norm(r["INGR_KOR_NAME"]) == t: basis.append("한글명")
            if norm(r["INGR_ENG_NAME"]) == t:
                basis.append("영문명")
            elif t in [norm(s) for s in split_names(r["INGR_ENG_NAME"])]:
                basis.append("영문명 항목")
            syn = [norm(s) for line in re.split(r"[;\r\n]+", r["INGR_SYNONYM"] or "") for s in split_names(line)]
            if t in syn: basis.append("이명")
            if r["CAS_NO"] and term.strip() in re.findall(r"\b\d{2,7}-\d{2}-\d\b", r["CAS_NO"]): basis.append("CAS")
            if basis:
                exact.append((r, basis))
            elif t and any(t in norm(r[f]) for f in ("INGR_KOR_NAME", "INGR_ENG_NAME", "INGR_SYNONYM")):
                contains.append(r)
        results[term] = {"exact": exact, "contains": contains}
        print("== '%s' — 정확 일치 %d건 / 포함 일치(후보) %d건" % (term, len(exact), len(contains)))
        for r, basis in exact:
            print("   [정확·%s] id=%d | %s | %s | CAS %s | 이명 %s" % ("·".join(basis), r["id"], r["INGR_KOR_NAME"], r["INGR_ENG_NAME"],
                                                              (r["CAS_NO"] or "—").replace("\r", "\\r").replace("\n", "\\n"), (r["INGR_SYNONYM"] or "—")[:80]))
        for r in contains[:5]:
            print("   [후보] id=%d | %s | %s" % (r["id"], r["INGR_KOR_NAME"], r["INGR_ENG_NAME"]))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="식약처 화장품 원료성분정보 수집·분석 (담당자 B)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="5건 호출로 연결·구조 확인 (저장 안 함)")
    c = sub.add_parser("collect", help="페이지 순차 수집 (running/interrupted 실행 자동 재개)")
    c.add_argument("--new-run", action="store_true")
    c.add_argument("--max-pages", type=int, default=None)
    c.add_argument("--allow-count-change", action="store_true")
    sub.add_parser("status")
    a = sub.add_parser("analyze")
    a.add_argument("--run-id", type=int, default=None)
    f = sub.add_parser("find")
    f.add_argument("terms", nargs="+")
    f.add_argument("--run-id", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        cfg = config(require_key=args.cmd in ("probe", "collect"))
        if args.cmd == "probe":
            probe(cfg)
        elif args.cmd == "collect":
            collect(cfg, new_run=args.new_run, max_pages=args.max_pages, allow_count_change=args.allow_count_change)
        elif args.cmd == "status":
            status(cfg)
        elif args.cmd == "analyze":
            print_analysis(analyze(cfg, args.run_id))
        elif args.cmd == "find":
            find(cfg, args.terms, args.run_id)
    except Abort as exc:
        print("오류(%s): %s" % (exc.kind, exc.message))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
