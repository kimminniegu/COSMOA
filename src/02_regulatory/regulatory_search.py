"""국가별 인허가 규제 — 식약처 성분 DB + 규제 DB 통합 성분 검색 (읽기 전용, 담당자 B).

규제 화면의 성분 검색·조회 모듈 — app.py [B] 의 /api/regulatory/search(search) · /api/regulatory/lookup(lookup_candidate) 가 쓴다.
챗봇 성분 도구(src/06_chatbot/tools.py)도 같은 search·lookup_candidate 를 직접 쓴다. (이전 K-Beauty API 성분 검색을 대체 — 그 모듈은 2026-11-11 삭제) 외부 API 호출·API 키·자동 재수집 없음. DB 는 mode=ro 로만 연다.

검색 대상 (완료된 수집본만: status completed | completed_with_warnings)
- 성분 DB  (mfds_ingredients.py 수집, MFDS_INGREDIENT_DB_PATH): INGR_KOR_NAME · INGR_ENG_NAME · INGR_SYNONYM · CAS_NO
- 규제 DB  (mfds_use_restriction.py 수집, MFDS_DB_PATH):          INGR_STD_NAME · INGR_ENG_NAME · INGR_SYNONYM · NOTICE_INGR_NAME · CAS_NO
  규제 DB 는 같은 성분이 국가·조건별로 여러 행이다 → regulatory_mfds_lookup._identity
  (INGR_STD_NAME 원문, 영문명 정규화) 와 같은 기준으로 한 후보로 묶고, 묶인 행의 원문 값은 목록으로 보존한다.
- 두 DB 의 후보는 합치지 않는다. 출처별로 따로 반환하고 성분을 자동 확정하지 않는다.

이름 처리
- 검색용 정규화: 앞뒤 공백 제거·연속 공백 하나로·대소문자 무시(casefold). 숫자·기호·위치 표기는 그대로.
- 영문명·이명·고시원료명은 쉼표 나열을 mfds_ingredients.split_names 규칙으로 나눠 '항목'으로도 비교한다
  (화학명 위치 표기 1,2- · 4,4'- · N,N- 와 '/' 는 나누지 않음). 한글 표준명은 나누지 않는다.
- 이명·고시원료명은 ; 와 줄바꿈도 항목 구분으로 본다.
- '메칠→메틸' 같은 치환·유사도 매칭은 하지 않는다.
- CAS: 검색어가 CAS 형식(숫자-숫자-숫자)이면 CAS 토큰 전체 일치만 본다. 부분 문자열 일치로 판정하지 않는다.

일치 단계와 정렬 (같은 요청 → 같은 순서)
  exact(값 전체 또는 나열 항목이 같음) → prefix(값 또는 항목이 검색어로 시작) → contains(값에 검색어 포함)
  같은 단계 안: 일치 필드(표준명·한글명 → 영문명 → 이명 → 고시원료명) → 출처(성분 DB → 규제 DB) → 이름 길이 → 이름 → 후보 키

후보 키 (K-Beauty code 대체, 영구 성분 코드 아님)
  "<source>:<snapshot_id>:<local_id>"
  - source: mfds_ingredients | mfds_restriction  (DB 가 달라 내부 id 가 같아도 충돌하지 않음)
  - snapshot_id: 수집본 지문 = sha256(dataset, run_id, started_at, finished_at, records_saved, 페이지 content_hash 들) 앞 16자.
    run_id 는 DB 를 새로 만들면 다시 1 이 되므로 단독으로 쓰지 않는다. 재수집하면 내용이 같아도 키가 바뀐다.
  - local_id: 성분 DB = records.id / 규제 DB = 묶음(identity) 안 가장 작은 records.id. 해당 수집본 안에서만 의미가 있다.
  resolve_key() 는 현재 수집본과 snapshot_id 가 다르면 stale_key 오류를 낸다 (다른 성분으로 잘못 해석하지 않음).
  저장이 필요하면 키와 함께 원문 이름·CAS 를 같이 남기고, 수집본이 바뀌면 이름으로 다시 찾아 사람이 확인해야 한다.

사용:  search(query, limit=10, sources=None) → dict   /  resolve_key(key) → candidate dict
오류:  SearchError(kind) — validation(400) | db_missing(503) | db_incomplete(503) | db_error(503) | stale_key(409) | not_found(404)
       DB 누락·읽기 실패는 '검색 결과 없음'으로 바꾸지 않고 오류로 낸다.
"""

import hashlib
import importlib.util
import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE.parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ingr = _load("mfds_ingredients", "mfds_ingredients.py")          # split_names, 데이터셋 표시, 완료 상태
_lookup = _load("regulatory_mfds_lookup", "regulatory_mfds_lookup.py")   # _identity, norm_name, 완료 상태

split_names = _ingr.split_names
norm = _lookup.norm_name
CAS_RE = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
CAS_QUERY_RE = re.compile(r"\d{2,7}-\d{2}-\d")

SRC_INGR = "mfds_ingredients"
SRC_RSTR = "mfds_restriction"
SOURCES = (SRC_INGR, SRC_RSTR)
SOURCE_LABELS = {SRC_INGR: "식약처 화장품 원료성분정보 (수집 DB)", SRC_RSTR: "식약처 화장품 사용제한 원료정보 (수집 DB)"}
SOURCE_ORDER = {SRC_INGR: 0, SRC_RSTR: 1}
COMPLETED = {SRC_INGR: tuple(_ingr.COMPLETED), SRC_RSTR: tuple(_lookup.COMPLETED)}
RESTRICTION_DATASET = "mfds_use_restriction"

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MIN_QUERY_LENGTH = 2
LEVELS = ("exact", "prefix", "contains")
FIELD_PRIORITY = {"INGR_KOR_NAME": 0, "INGR_STD_NAME": 0, "CAS_NO": 0, "INGR_ENG_NAME": 1, "INGR_SYNONYM": 2, "NOTICE_INGR_NAME": 3}
NOTICE = ("검색 후보입니다. 성분을 자동으로 확정하지 않았어요 — 사용자가 후보를 선택해야 해요. "
          "후보가 검색됐다는 것은 사용 허용·안전·규제 없음을 뜻하지 않아요.")


class SearchError(Exception):
    STATUS = {"validation": 400, "db_missing": 503, "db_incomplete": 503, "db_error": 503, "stale_key": 409, "not_found": 404}

    def __init__(self, kind, message, source=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.source = source
        self.http_status = self.STATUS.get(kind, 503)

    def to_dict(self):
        return {"kind": self.kind, "message": self.message, "source": self.source}


# ---------------------------------------------------------------------------
# DB 경로·열기·수집본
# ---------------------------------------------------------------------------

def db_paths():
    return {
        SRC_INGR: Path(os.getenv("MFDS_INGREDIENT_DB_PATH") or (BASE_DIR / "instance" / "regulatory" / "mfds_ingredients.sqlite")),
        SRC_RSTR: Path(os.getenv("MFDS_DB_PATH") or (BASE_DIR / "instance" / "regulatory" / "mfds_use_restriction.sqlite")),
    }


def _open_ro(source, path):
    """읽기 전용. 파일이 없으면 만들지 않고 db_missing."""
    if not path.is_file():
        raise SearchError("db_missing", "%s 파일이 없어요 (%s). 수집을 먼저 실행하거나 완료된 DB 를 복사해 주세요." % (SOURCE_LABELS[source], path.name), source)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path.resolve().as_posix(), uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise SearchError("db_error", "%s 를 열지 못했어요 (%s)." % (SOURCE_LABELS[source], exc.__class__.__name__), source)


def _check_dataset(conn, source):
    """경로가 뒤바뀌거나 다른 DB 를 가리키면 db_error (조용히 엉뚱한 결과를 내지 않음)."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"runs", "pages", "records"} <= tables:
        raise SearchError("db_error", "%s 의 수집 스키마(runs/pages/records)가 없어요." % SOURCE_LABELS[source], source)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}
    if source == SRC_INGR:
        ds = conn.execute("SELECT value FROM meta WHERE key='dataset'").fetchone() if "meta" in tables else None
        if ds is None or ds[0] != _ingr.DATASET or "INGR_KOR_NAME" not in cols:
            raise SearchError("db_error", "MFDS_INGREDIENT_DB_PATH 가 원료성분정보 DB 가 아니에요.", source)
    else:
        if not {"REGULATE_TYPE", "INGR_STD_NAME", "NOTICE_INGR_NAME", "COUNTRY_NAME"} <= cols:
            raise SearchError("db_error", "MFDS_DB_PATH 가 사용제한 원료정보 DB 가 아니에요.", source)


def _snapshot(conn, source):
    statuses = COMPLETED[source]
    run = conn.execute("SELECT * FROM runs WHERE status IN (%s) ORDER BY run_id DESC LIMIT 1" % ",".join("?" * len(statuses)), statuses).fetchone()
    if run is None:
        raise SearchError("db_incomplete", "%s 에 완료된 수집 실행이 없어요." % SOURCE_LABELS[source], source)
    dataset = _ingr.DATASET if source == SRC_INGR else RESTRICTION_DATASET
    h = hashlib.sha256()
    for part in (dataset, run["run_id"], run["started_at"], run["finished_at"], run["records_saved"]):
        h.update(("%s\x1f" % part).encode("utf-8"))
    for (ch,) in conn.execute("SELECT content_hash FROM pages WHERE run_id=? ORDER BY page_no", (run["run_id"],)):
        h.update((ch or "").encode("ascii"))
    return {"snapshot_id": h.hexdigest()[:16], "run_id": run["run_id"], "status": run["status"],
            "started_at": run["started_at"], "collected_at": run["finished_at"], "records": run["records_saved"]}


# ---------------------------------------------------------------------------
# 색인 (수집본별 메모리 캐시 — 파일 크기·수정시각·snapshot 이 바뀌면 다시 만든다)
# ---------------------------------------------------------------------------

def _items(value, list_like):
    """검색용 비교 대상: (정규화 전체값, [정규화 항목들])."""
    whole = norm(value)
    if not whole:
        return "", []
    if not list_like:
        return whole, [whole]
    parts = []
    for line in re.split(r"[;\r\n]+", value):
        parts += [norm(p) for p in split_names(line)]
    return whole, sorted(set(p for p in parts if p) | {whole})


def _field_entry(field, value, list_like):
    whole, items = _items(value, list_like)
    if not whole:
        return None
    return {"field": field, "raw": value, "whole": whole, "items": items, "cas": set(CAS_RE.findall(value)) if field == "CAS_NO" else None}


def _build_ingredients(conn, snap):
    out = []
    for r in conn.execute("SELECT id, INGR_KOR_NAME, INGR_ENG_NAME, CAS_NO, INGR_SYNONYM, ORIGIN_MAJOR_KOR_NAME FROM records WHERE run_id=? ORDER BY id", (snap["run_id"],)):
        fields = [f for f in (
            _field_entry("INGR_KOR_NAME", r["INGR_KOR_NAME"], False),
            _field_entry("INGR_ENG_NAME", r["INGR_ENG_NAME"], True),
            _field_entry("INGR_SYNONYM", r["INGR_SYNONYM"], True),
            _field_entry("CAS_NO", r["CAS_NO"], False),
        ) if f]
        out.append({
            "local_id": r["id"], "fields": fields, "sort_name": norm(r["INGR_KOR_NAME"] or r["INGR_ENG_NAME"]),
            "public": {"kr_name": r["INGR_KOR_NAME"], "eng_name": r["INGR_ENG_NAME"], "synonym": r["INGR_SYNONYM"], "cas": r["CAS_NO"],
                       "origin_definition": r["ORIGIN_MAJOR_KOR_NAME"], "record_id": r["id"]},
        })
    return out


def _uniq(seq):
    seen, out = set(), []
    for v in seq:
        if v is not None and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _build_restriction(conn, snap):
    groups = {}
    for r in conn.execute("SELECT id, INGR_STD_NAME, INGR_ENG_NAME, CAS_NO, INGR_SYNONYM, NOTICE_INGR_NAME, COUNTRY_NAME, REGULATE_TYPE "
                          "FROM records WHERE run_id=? ORDER BY id", (snap["run_id"],)):
        g = groups.setdefault(_lookup._identity(r), {"rows": []})
        g["rows"].append(r)
    out = []
    for ident, g in groups.items():
        rows = g["rows"]
        first = rows[0]
        vals = {f: _uniq(r[f] for r in rows) for f in ("INGR_STD_NAME", "INGR_ENG_NAME", "CAS_NO", "INGR_SYNONYM", "NOTICE_INGR_NAME")}
        fields = []
        for f, list_like in (("INGR_STD_NAME", False), ("INGR_ENG_NAME", True), ("INGR_SYNONYM", True), ("NOTICE_INGR_NAME", True), ("CAS_NO", False)):
            for v in vals[f]:
                e = _field_entry(f, v, list_like)
                if e:
                    fields.append(e)
        out.append({
            "local_id": first["id"], "fields": fields, "sort_name": norm(first["INGR_STD_NAME"] or first["INGR_ENG_NAME"]),
            "public": {
                "kr_name": first["INGR_STD_NAME"], "eng_name": first["INGR_ENG_NAME"],
                "synonym": first["INGR_SYNONYM"], "cas": first["CAS_NO"],
                "identity": {"std_name": ident[0], "eng_name_normalized": ident[1]},   # regulatory_mfds_lookup 과 같은 성분 구분 기준
                "record_count": len(rows), "record_ids_min": first["id"],
                "countries": sorted(_uniq(r["COUNTRY_NAME"] for r in rows)),          # 등재 국가 원문 값 (규제 판정 아님)
                "regulate_types": sorted(_uniq(r["REGULATE_TYPE"] for r in rows)),
                "values": vals,                                                       # 묶인 행들의 서로 다른 원문 값 전부
            },
        })
    out.sort(key=lambda c: c["local_id"])
    return out


_cache = {}
_cache_lock = threading.Lock()


def _index(source, path):
    """(snapshot, entries). DB 를 매 호출 열어 수집본을 확인한다 — 파일이 사라지면 캐시가 있어도 오류."""
    conn = _open_ro(source, path)
    try:
        try:
            _check_dataset(conn, source)
            snap = _snapshot(conn, source)
            st = path.stat()
            ck = (source, str(path.resolve()), st.st_size, st.st_mtime_ns, snap["snapshot_id"])
            with _cache_lock:
                hit = _cache.get(ck)
            if hit is not None:
                return hit
            entries = _build_ingredients(conn, snap) if source == SRC_INGR else _build_restriction(conn, snap)
        except sqlite3.Error as exc:
            raise SearchError("db_error", "%s 를 읽지 못했어요 (%s)." % (SOURCE_LABELS[source], exc.__class__.__name__), source)
    finally:
        conn.close()
    with _cache_lock:
        for k in [k for k in _cache if k[0] == source and k[1] == ck[1]]:
            del _cache[k]
        _cache[ck] = (snap, entries)
    return snap, entries


# ---------------------------------------------------------------------------
# 매칭
# ---------------------------------------------------------------------------

def _match_field(fe, q, is_cas):
    """한 필드의 일치 단계와 근거. 없으면 None."""
    if fe["field"] == "CAS_NO":
        if is_cas and q in fe["cas"]:
            return {"level": "exact", "via": "cas_token"}
        return None                                    # CAS 는 토큰 전체 일치만
    if is_cas:
        return None
    if q in fe["items"]:
        return {"level": "exact", "via": "whole" if q == fe["whole"] else "item"}
    for it in fe["items"]:
        if it.startswith(q):
            return {"level": "prefix", "via": "whole" if it == fe["whole"] else "item"}
    if q in fe["whole"]:
        return {"level": "contains", "via": "whole"}
    return None


def _match_entry(entry, q, is_cas):
    matched = []
    for fe in entry["fields"]:
        m = _match_field(fe, q, is_cas)
        if m:
            matched.append({"field": fe["field"], "level": m["level"], "via": m["via"], "value": fe["raw"]})
    if not matched:
        return None
    best = min(LEVELS.index(m["level"]) for m in matched)
    best_field = min(FIELD_PRIORITY[m["field"]] for m in matched if LEVELS.index(m["level"]) == best)
    matched.sort(key=lambda m: (LEVELS.index(m["level"]), FIELD_PRIORITY[m["field"]], m["field"], m["value"]))
    return best, best_field, matched


def _key(source, snap, local_id):
    return "%s:%s:%d" % (source, snap["snapshot_id"], local_id)


def _candidate(source, snap, entry, matched):
    c = {
        "key": _key(source, snap, entry["local_id"]),
        "key_note": "수집본 안에서만 유효한 후보 키예요 (영구 성분 코드 아님).",
        "source": source,
        "source_label": SOURCE_LABELS[source],
        "local_id": entry["local_id"],
        "match": matched[0]["level"] if matched else None,
        "matched": matched,
        "snapshot": {"snapshot_id": snap["snapshot_id"], "run_id": snap["run_id"], "collected_at": snap["collected_at"]},
    }
    c.update(entry["public"])
    return c


def normalize_query(text):
    return norm(text)


def search(query, limit=DEFAULT_LIMIT, sources=None):
    """두 DB 후보 검색. sources 로 출처를 고를 수 있고(기본 둘 다), 고른 출처의 DB 가 없으면 오류."""
    raw = (query or "").strip()
    q = norm(raw)
    if not q:
        raise SearchError("validation", "검색어를 입력해 주세요.")
    if len(q) < MIN_QUERY_LENGTH:
        raise SearchError("validation", "검색어를 %d글자 이상 입력해 주세요." % MIN_QUERY_LENGTH)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise SearchError("validation", "limit 은 정수여야 해요.")
    if not 1 <= limit <= MAX_LIMIT:
        raise SearchError("validation", "limit 은 1~%d 사이여야 해요." % MAX_LIMIT)
    sources = tuple(sources) if sources else SOURCES
    bad = [s for s in sources if s not in SOURCES]
    if bad:
        raise SearchError("validation", "알 수 없는 출처: %s" % ", ".join(bad))
    is_cas = bool(CAS_QUERY_RE.fullmatch(q))
    paths = db_paths()
    snaps, ranked = {}, []
    counts = {s: {"total": 0, "exact": 0, "prefix": 0, "contains": 0} for s in sources}
    for src in sources:
        snap, entries = _index(src, paths[src])
        snaps[src] = snap
        for e in entries:
            m = _match_entry(e, q, is_cas)
            if m is None:
                continue
            best, best_field, matched = m
            counts[src]["total"] += 1
            counts[src][LEVELS[best]] += 1
            ranked.append(((best, best_field, SOURCE_ORDER[src], len(e["sort_name"]), e["sort_name"], src, e["local_id"]), src, e, matched))
    ranked.sort(key=lambda x: x[0])
    total = len(ranked)
    shown = [_candidate(src, snaps[src], e, matched) for _, src, e, matched in ranked[:limit]]
    exact_total = sum(c["exact"] for c in counts.values())
    return {
        "query": raw,
        "query_normalized": q,
        "query_type": "cas" if is_cas else "name",
        "limit": limit,
        "candidates": shown,
        "returned": len(shown),
        "total": total,                                   # 제한 전 전체 후보 수
        "truncated": total > len(shown),
        "exact_total": exact_total,                       # 출처 합계 정확 일치 수 (표시 개수와 별개)
        "counts": counts,                                 # 출처별 total / exact / prefix / contains
        "auto_confirmed": False,                          # 이 모듈은 성분을 확정하지 않는다
        "selection_required": True,
        "notice": NOTICE,
        "sources": {s: dict(snaps[s], source_label=SOURCE_LABELS[s]) for s in sources},
        "queried_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


KEY_RE = re.compile(r"^(mfds_ingredients|mfds_restriction):([0-9a-f]{16}):(\d+)$")


def resolve_key(key):
    """후보 키 → 현재 수집본의 후보. 수집본이 다르면 stale_key (이전 키를 다른 성분으로 해석하지 않음)."""
    m = KEY_RE.match((key or "").strip())
    if not m:
        raise SearchError("validation", "후보 키 형식이 아니에요.")
    src, snap_id, local = m.group(1), m.group(2), int(m.group(3))
    snap, entries = _index(src, db_paths()[src])
    if snap["snapshot_id"] != snap_id:
        raise SearchError("stale_key", "후보 키의 수집본(%s)이 현재 수집본(%s)과 달라요. 성분을 다시 검색해 확인해 주세요." % (snap_id, snap["snapshot_id"]), src)
    for e in entries:
        if e["local_id"] == local:
            return _candidate(src, snap, e, [])
    raise SearchError("not_found", "현재 수집본에 이 후보 키가 없어요.", src)


def clear_cache():
    with _cache_lock:
        _cache.clear()


def db_status():
    """두 DB 의 이용 가능 상태 (진단용, 읽기 전용 — 색인을 만들지 않고 수집하지 않는다).
    {source: {"available": True, "collected_at", "run_id"} | {"available": False, "kind", "message"}}"""
    out = {}
    for src, path in db_paths().items():
        try:
            conn = _open_ro(src, path)
            try:
                _check_dataset(conn, src)
                snap = _snapshot(conn, src)
            except sqlite3.Error as exc:
                raise SearchError("db_error", "%s 를 읽지 못했어요 (%s)." % (SOURCE_LABELS[src], exc.__class__.__name__), src)
            finally:
                conn.close()
            out[src] = {"available": True, "collected_at": snap["collected_at"], "run_id": snap["run_id"]}
        except SearchError as exc:
            out[src] = {"available": False, "kind": exc.kind, "message": exc.message}
    return out


# ---------------------------------------------------------------------------
# 선택한 후보 → 규제 조회 (직접 검색 2단계)
# ---------------------------------------------------------------------------
# 규제 DB 후보: resolve_key 로 검증한 identity 그대로 regulatory_mfds_lookup.lookup_by_identity (이름 재매칭 없음).
# 성분 DB 후보: 서버가 복원한 한글명·영문명이 규제 DB 표준명·영문명과 '직접 정확 일치'하고 그 성분이 하나뿐이며 충돌이 없을 때만 연결.
#   - 한글명 = 규제 표준명 (정규화 후 전체 일치) / 영문명(쉼표 나열 항목 포함) = 규제 영문명(항목 포함)
#   - 이명·고시원료명·접두·포함·유사도·'메칠→메틸' 치환으로 연결하지 않는다. CAS 로 후보를 찾지 않고, 둘 다 있을 때 충돌 확인에만 쓴다.
#   - 연결 후보 여러 개 / 한쪽 이름만 같고 다른 쪽 이름이 다름 / CAS 가 서로 겹치지 않음 → link_required (사용자가 다시 선택)
# lookup_status: found | no_market_record | link_required | not_linked   (오류는 SearchError)

LOOKUP_NOTES = {
    "link_required": "성분정보에서 고른 성분과 규제정보의 성분을 하나로 연결할 수 없어요. 아래 근거와 후보를 확인하고 규제정보 후보를 직접 선택해 주세요.",
    "not_linked": "성분정보에서 고른 성분과 이름이 정확히 일치하는 규제정보 항목을 찾지 못했어요. 허용·안전·규제 없음을 뜻하지 않아요.",
}


def _fields_of(entry, field):
    return [f for f in entry["fields"] if f["field"] == field]


def _cas_of(entry):
    out = set()
    for f in _fields_of(entry, "CAS_NO"):
        out |= f["cas"]
    return out


def _link_candidate(snap, entry, basis):
    p = entry["public"]
    return {"key": _key(SRC_RSTR, snap, entry["local_id"]), "source": SRC_RSTR, "source_label": SOURCE_LABELS[SRC_RSTR],
            "std_name": p["kr_name"], "eng_name": p["eng_name"], "cas": sorted(_cas_of(entry)),
            "basis": sorted(basis), "markets": p["countries"], "identity": p["identity"]}


def link_ingredient(cand, rst_snap, rst_entries):
    """성분 DB 후보 → 규제 DB identity. {"status": linked|ambiguous|none, "basis", "identity", "candidates", "conflict"}"""
    kor = norm(cand.get("kr_name"))
    _, eng_items = _items(cand.get("eng_name"), True)
    eng_set = set(eng_items)
    cas_in = set(CAS_RE.findall(cand.get("cas") or ""))
    hits = []
    for e in rst_entries:
        basis = set()
        if kor and any(f["whole"] == kor for f in _fields_of(e, "INGR_STD_NAME")):
            basis.add("한글명 = 규제 표준명")
        if eng_set and any(set(f["items"]) & eng_set for f in _fields_of(e, "INGR_ENG_NAME")):
            basis.add("영문명 = 규제 영문명")
        if basis:
            hits.append((e, basis))
    if not hits:
        return {"status": "none", "basis": [], "identity": None, "candidates": [], "conflict": None}
    cands = [_link_candidate(rst_snap, e, b) for e, b in hits]
    if len(hits) > 1:
        return {"status": "ambiguous", "basis": [], "identity": None, "candidates": cands,
                "conflict": "이름이 정확히 일치하는 규제 성분이 %d개예요." % len(hits)}
    e, basis = hits[0]
    conflict = None
    r_std = [f["whole"] for f in _fields_of(e, "INGR_STD_NAME")]
    r_eng = set()
    for f in _fields_of(e, "INGR_ENG_NAME"):
        r_eng |= set(f["items"])
    if basis == {"영문명 = 규제 영문명"} and kor and r_std:
        conflict = "영문명은 같지만 한글명이 달라요 (성분정보 ‘%s’ / 규제정보 ‘%s’)." % (cand.get("kr_name"), e["public"]["kr_name"])
    elif basis == {"한글명 = 규제 표준명"} and eng_set and r_eng:
        conflict = "한글명은 같지만 영문명이 달라요 (성분정보 ‘%s’ / 규제정보 ‘%s’)." % (cand.get("eng_name"), e["public"]["eng_name"])
    r_cas = _cas_of(e)
    if not conflict and cas_in and r_cas and not (cas_in & r_cas):
        conflict = "CAS 번호가 서로 겹치지 않아요 (성분정보 %s / 규제정보 %s)." % (", ".join(sorted(cas_in)), ", ".join(sorted(r_cas)))
    if conflict:
        return {"status": "ambiguous", "basis": sorted(basis), "identity": None, "candidates": cands, "conflict": conflict}
    if cas_in and r_cas:
        basis.add("CAS 일치")
    return {"status": "linked", "basis": sorted(basis), "identity": e["public"]["identity"], "candidates": cands, "conflict": None}


def _as_search_error(exc):
    kind = {"stale_run": "stale_key", "identity_missing": "not_found"}.get(exc.kind, exc.kind)
    return SearchError(kind, exc.message, SRC_RSTR)


def _run_view(snap):
    return {"run_id": snap["run_id"], "status": snap["status"], "records_saved": snap["records"],
            "started_at": snap["started_at"], "finished_at": snap["collected_at"]}


def lookup_candidate(key, market):
    """후보 키(브라우저가 보낸 값) → 서버 검증(resolve_key) → 규제 DB 조회. 브라우저가 보낸 이름·CAS·identity 는 쓰지 않는다."""
    if market not in _lookup.MARKET_TO_COUNTRY:
        raise SearchError("validation", "국가/시장을 선택해 주세요.")
    cand = resolve_key(key)
    paths = db_paths()
    rst_snap, rst_entries = _index(SRC_RSTR, paths[SRC_RSTR])
    if cand["source"] == SRC_RSTR:
        link = {"status": "direct", "basis": ["규제정보 후보를 직접 선택"], "identity": cand["identity"], "candidates": [], "conflict": None}
    else:
        link = link_ingredient(cand, rst_snap, rst_entries)
    countries = _lookup.MARKET_TO_COUNTRY[market]
    try:
        if link["identity"]:
            ident = link["identity"]
            res = _lookup.lookup_by_identity(ident["std_name"], ident["eng_name_normalized"], market, path=paths[SRC_RSTR], expected_run=_run_view(rst_snap))
            status = res["lookup_status"]                                   # found | no_market_record
        else:
            conn = _lookup.open_readonly(paths[SRC_RSTR])
            try:
                related = _lookup.related_items(conn, rst_snap["run_id"], countries, (cand.get("kr_name") or "").strip() or None,
                                                (cand.get("eng_name") or "").strip() or None)
            except sqlite3.Error as exc:
                raise _lookup.MfdsLookupError("db_error", "식약처 수집 DB 를 읽지 못했어요 (%s)." % exc.__class__.__name__)
            finally:
                conn.close()
            status = "link_required" if link["status"] == "ambiguous" else "not_linked"
            res = _lookup._common_result(_run_view(rst_snap), market, countries)
            res.update({"entries": [], "related": related, "markets_listed": [], "matched_identity": None, "identity": None,
                        "result_note": LOOKUP_NOTES[status] + (" 관련 항목 %d건은 적용 여부 확인이 필요해요." % len(related) if related else "")})
    except _lookup.MfdsLookupError as exc:
        raise _as_search_error(exc)
    regulation_ingredient = res.get("ingredient")
    sel_snap = cand["snapshot"]
    res.update({
        "lookup_status": status,
        "result_status": "mfds_" + status,
        # 화면 제목은 사용자가 고른 후보 이름 (연결된 규제 성분 이름은 matched_identity·regulation_ingredient)
        "ingredient": {"code": None, "kr_name": (cand.get("kr_name") or "").strip() or None, "inci_name": (cand.get("eng_name") or "").strip() or None,
                       "cas_numbers": (cand.get("cas") or "").strip() or None},
        "regulation_ingredient": regulation_ingredient,
        "selection": {"key": cand["key"], "source": cand["source"], "source_label": SOURCE_LABELS[cand["source"]],
                      "kr_name": cand.get("kr_name"), "eng_name": cand.get("eng_name"), "synonym": cand.get("synonym"), "cas": cand.get("cas"),
                      "collected_at": sel_snap["collected_at"], "run_id": sel_snap["run_id"]},
        "link": link,
        "link_status": {"direct": "confirmed", "linked": "confirmed", "ambiguous": "ambiguous", "none": "none"}[link["status"]],
        "link_basis": link["basis"],
        "link_conflict": link["conflict"],
        "link_candidates": link["candidates"] if link["status"] == "ambiguous" else [],
        "ingredient_source": {"source": cand["source"], "label": SOURCE_LABELS[cand["source"]], "collected_at": sel_snap["collected_at"]},
        "regulation_source": {"source": SRC_RSTR, "label": SOURCE_LABELS[SRC_RSTR], "collected_at": rst_snap["collected_at"]},
        "auto_confirmed": False,
    })
    return res
