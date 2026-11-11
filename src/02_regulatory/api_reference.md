# 국가별 인허가 규제 — API 참고 문서

담당자 B. `/api/regulatory/` Route 계약과 외부 K뷰티 API 호출 방식을 기록한다.
기능 요구사항은 `regulatory.md`가 우선이며, 이 문서는 구현된 계약과 실제 확인한 API 응답만 다룬다.

- 처리 모듈: `src/02_regulatory/regulatory_service.py`(규제 API), `src/02_regulatory/regulatory_extract.py`(파일 추출) — app.py [B] 영역에서 파일 경로로 로드
- 실제 호출 기록: `src/02_regulatory/test_data/*.json` (인증 정보 제거, 응답 본문·HTTP 상태·호출 제한 헤더만)
- 테스트: `python -m unittest discover -s src/02_regulatory/tests -v` (외부 호출 없음)

## 1. 내부 Route (브라우저 → Flask)

브라우저는 아래 Route만 호출한다. 외부 API Key는 서버 환경변수(`RAPIDAPI_KEY`, `RAPIDAPI_HOST`)에서만 읽고 응답·로그에 넣지 않는다.

> **화면(직접 검색 2단계 · 파일 탭 3단계, 2026-11-09)은 `/api/regulatory/search` · `/api/regulatory/lookup` · `/api/regulatory/extract` 만 쓴다** (식약처 수집 DB 두 개, 외부 API·API 키 없음).
> 아래 `/ingredients` · `/regulations` 는 **화면에서 더 이상 호출하지 않는 이전 경로**다. 챗봇(`src/06_chatbot/tools.py`)이 `regulatory_service`·`regulatory_mfds_lookup.lookup()` 을 직접 쓰므로 4단계 삭제는 챗봇 담당과 함께 진행한다 (3장 9항).

### GET `/api/regulatory/search?q=<검색어>` — 직접 검색 후보 (로그인 필요)

`regulatory_search.search(q, limit=10)`. 한글명·영문명·이명·고시원료명·CAS 로 **성분정보**(`mfds_ingredients`)·**규제정보**(`mfds_restriction`) 두 DB 를 검색한다. 두 출처 후보는 합치지 않고, 성분을 자동 확정하지 않는다.

- 정렬: 정확 일치 → 앞부분 일치 → 포함 일치 (같은 요청 → 같은 순서). 기본 10개.
- 응답: `candidates[]`(key·source·kr_name·eng_name·synonym·cas·match·matched[필드·단계·근거·원문]·snapshot) / `total`(제한 전) / `returned` / `truncated` / `exact_total` / `counts{source: total·exact·prefix·contains}` / `auto_confirmed=false` / `sources{snapshot_id·run_id·collected_at}`.
- `key` = `<source>:<snapshot_id>:<local_id>` — 수집본 안에서만 유효한 후보 키(영구 성분 코드 아님). 화면에는 표시하지 않는다.
- 오류 (`{"ok": false, "error": {kind, message, source}}`): `validation` 400 (빈 값·2글자 미만) · `db_missing` / `db_incomplete` / `db_error` 503. 결과 없음은 200 + `total: 0` (오류와 구분).

### GET `/api/regulatory/lookup?key=<후보 key>&country=<시장코드>` — 직접 검색 규제 조회 (로그인 필요)

`regulatory_search.lookup_candidate(key, country)`. 서버가 `resolve_key` 로 key 를 검증한 뒤 규제 DB 를 읽는다. **브라우저가 보낸 이름·CAS·identity 는 받지 않는다.**

- 규제정보 후보: 검증된 identity 그대로 `regulatory_mfds_lookup.lookup_by_identity` (이름 재매칭 없음). `link.status = direct`.
- 성분정보 후보: 서버가 복원한 한글명 = 규제 표준명, 영문명(쉼표 나열 항목 포함) = 규제 영문명 이 **직접 정확 일치**하고 그 규제 성분이 하나뿐이며 충돌이 없을 때만 연결(`linked`). 이명·고시원료명·접두·포함·유사도·'메칠→메틸' 치환으로 연결하지 않고, CAS 로 찾지 않는다(둘 다 있을 때 충돌 확인만). 복수 후보·한쪽 이름 불일치·CAS 불일치 → `ambiguous`. 일치 없음 → `none`.
- `lookup_status`: `found`(선택 시장 기록 있음, 조건별 레코드 모두) · `no_market_record`(규제 성분은 있으나 선택 시장 기록 없음) · `link_required`(연결 확인 필요, `link_candidates[]` 에 규제 후보 key 포함) · `not_linked`(정확 일치 규제 성분 없음). 모두 200. 기록이 없다고 허용·안전·규제 없음으로 판정하지 않는다.
- 응답은 `/regulations?source=mfds` 와 같은 필드(entries·related·markets_listed·collection_run·출처·날짜)에 더해 `selection`(고른 후보) · `link`{status·basis·identity·candidates·conflict} · `ingredient_source` / `regulation_source`(출처별 수집 시각 따로) · `regulation_ingredient`. `ingredient` 는 사용자가 고른 후보 이름이다. `related` 는 확정 규제와 분리된 포함 일치 항목.
- 오류: `validation` 400 (key·국가 누락·형식) · `stale_key` 409 (key 의 수집본이 현재와 다름 → 다시 검색·선택) · `not_found` 404 · `db_missing` / `db_incomplete` / `db_error` 503.

### GET `/api/regulatory/ingredients?q=<성분명>` — 이전 경로 (화면 미사용, 4단계 삭제 대상)

한글명·영문 INCI명 후보 검색. **규제 조회를 하지 않는다.** 자동완성(입력 멈춤 300ms 후)과 검색 버튼 모두 이 Route를 사용한다.

| 항목 | 내용 |
|---|---|
| 파라미터 | `q` 필수. 앞뒤 공백 제거 후 빈 값 또는 2글자 미만이면 400 (API 문서의 min 2 chars) |
| 외부 호출 | 입력에 한글이 있으면 `GET /v1/ingredient/kr?q=<q>`, 없으면 `GET /v1/ingredient/inci?q=<q>` — **항상 1회** |
| 성공 200 | 아래 JSON |
| 검증 실패 400 | `{"ok": false, "error": {"kind": "validation", "message": "..."}}` |
| 설정 오류 503 | `error.kind = "config"` — Key/Host 미설정. 외부 호출 없음 |
| 외부 API 오류 502 | `error.kind = timeout / connection / auth(401) / access(403: 인증·구독·요금제 확인 필요) / rate_limit(429) / http / invalid_response` |

```json
{
  "ok": true,
  "query": "레티놀",
  "candidates": [
    {
      "code": 5489,
      "kr_name": "레티놀",
      "inci_name": "Retinol",
      "old_name": null,
      "cas_numbers": "11103-57-4, 68-26-8",
      "record_updated_at": "2026-08-26 23:44:59",
      "match_rank": 0
    }
  ],
  "total": 1,
  "truncated": false,
  "search_field": "kr",
  "match_mode": "starts_with",
  "data_source": "Ministry of Food and Drug Safety (MFDS, ...), European Commission CosIng Database (...)",
  "queried_at": "2026-09-23T10:21:49+09:00"
}
```

- `candidates`는 `code` 기준 중복 제거 후 `match_rank`(0 정확 일치 → 1 시작 일치 → 2 포함 일치 → 3 그 외) 순, 같은 순위는 API 순서. 최대 10개, 초과 시 `truncated: true`.
- `kr_name`이 비어 있으면 `null` — 화면은 영문명만 표시하고 한글명을 만들지 않는다.
- `record_updated_at`은 API 레코드의 `updated_at`이다. **규제 자료 갱신일이 아니다.**
- 매칭은 앞뒤 공백 제거 + `casefold()`(영문 대소문자 무시). 순위 계산에는 `kr_name`·`inci_name`·`old_name`을 사용한다.
- `search_field`는 실제 호출한 엔드포인트(`kr` | `inci`), `match_mode`는 API 일치 방식(`starts_with`). 두 엔드포인트 모두 **시작 일치**라 중간 포함 입력(예: `티놀`)은 후보가 없다.
- 한글 엔드포인트에 영문을 넣으면 0건(`test_data/search_kr_english_retinol.json`)이므로 언어별로 엔드포인트를 고른다. 혼합 입력(한글+영문)은 한글 엔드포인트로 보낸다.

### GET `/api/regulatory/regulations?code=<성분코드>&country=<시장코드>&source=mfds|api` — 이전 경로 (화면 미사용, 4단계 삭제 대상)

규제 조회. 화면에서 성분이 확정된 뒤 검색 버튼(직접 검색) 또는 ‘확정 성분 규제 조회’(일괄)에서 호출한다. **`source` 기본값 `mfds`.** 선택한 출처만 조회하며 실패해도 다른 출처로 바꾸지 않는다.

| 항목 | 내용 |
|---|---|
| 공통 | `country` ∈ `KR, EU, CN, US, JP, ASEAN`, `source` ∈ `mfds`(기본) / `api` |
| `source=api` | `code` 숫자 필수. 외부 호출 `GET /v1/ingredient/{code}/regulations?country=` 1회. 응답에 `source: "api"` 추가. 오류 400/502/503 기존과 동일 |
| `source=mfds` | `kr_name` / `inci_name` 중 하나 필수, `cas` 선택(쉼표·줄바꿈 구분 여러 개 가능), `code` 는 표시용. 외부 호출 없음 — `instance/regulatory/mfds_use_restriction.sqlite` 를 읽기 전용으로 조회 |
| mfds 오류 | 400 `validation`(이름 없음·미연결 시장) / 503 `db_missing`(DB 파일 없음) / 503 `db_incomplete`(완료된 수집 실행 없음) / 503 `db_error`(열기·스키마 오류). `error.source = "mfds"` |

`source=mfds` 응답 (기존 응답 형태 + 추가 필드):

```json
{
  "ok": true, "source": "mfds", "source_label": "식약처 화장품 사용제한 원료정보 (공공데이터포털) 수집 DB",
  "source_page": "https://www.data.go.kr/data/15111772/openapi.do", "collected_at": "2026-09-23T10:53:54+00:00",
  "collection_run": {"run_id": 1, "status": "completed", "records": 31191},
  "ingredient": {"code": 5489, "kr_name": "레티놀", "inci_name": "Retinol", "cas_numbers": "11103-57-4, 68-26-8"},
  "country": {"requested": "EU", "resolved": "EU", "code": "EU", "country_names": ["EU"]},
  "link_status": "confirmed", "link_basis": ["CAS", "영문명", "표준명"], "link_conflict": null, "link_candidates": [...],
  "matched_identity": {"std_name": "레티놀", "eng_name": "Retinol"},
  "lookup_status": "found", "result_status": "mfds_found", "result_note": null,
  "entries": [{"country": "EU", "country_code": "EU", "regulate_type": "한도", "notice_ingr_name": "...", "proviso": null,
               "limit_condition": "* 【Restrictions】...", "limit_missing": false, "source_type": "mfds", "std_name": "레티놀", "eng_name": "Retinol", "cas": "..."}],
  "related": [{"std_name": "레티닐아세테이트", "eng_name": "Retinyl Acetate", "country": "EU", "regulate_type": "한도", "matched_in": "이명"}],
  "markets_listed": ["EU", "캐나다"], "data_source": "...", "disclaimer": "...", "source_updated_at": null, "queried_at": "..."
}
```

- `lookup_status`: `found`(조건별 레코드 모두 `entries`) / `not_listed`(이 출처에서 이름·CAS 정확 일치 없음 — 화면 ‘출처에서 일치 항목 없음’) / `link_required`(식별 불가 — `link_candidates` 표시, 자동 확정 없음).
- `link_status`: `confirmed` / `ambiguous` / `none`. 확정 조건은 이름(표준명 또는 영문명) 정확 일치 식별자가 하나뿐이고 CAS 가 충돌하지 않을 때. CAS 만 일치하면 `ambiguous`.
- `entries[].limit_missing`: ‘한도’인데 `LIMIT_COND` 가 비어 있음(화면 ‘상세 제한사항 미제공’). ‘금지’+null 은 `limit_missing=false` 이며 금지 항목으로 표시.
- 시장 매핑: KR→한국, EU→EU(원본 ‘유럽’ 제외), US→미국, CN→중국, JP→일본, ASEAN→아세안.
- `collected_at` 과 `acquired_at` 은 DB `runs.finished_at`(수집 완료 시각)이며 원천 갱신일이 아니다(값이 없으면 `null` → 화면 ‘수집 시각 미기록’). `queried_at` 은 DB 를 읽은 시각. `refresh_policy` = "수동 재수집 (자동 갱신 없음)", `law_dates` = `null`. `source_page` 는 공공데이터 안내 페이지(개별 법령 원문 링크 아님)이며 그 페이지의 수정일을 갱신일로 쓰지 않는다.

```json
{
  "ok": true,
  "ingredient": {"code": 5489, "kr_name": "레티놀", "inci_name": "Retinol"},
  "country": {"requested": "EU", "resolved": "EU", "code": "EU"},
  "lookup_status": "found",
  "result_status": "listed",
  "result_note": null,
  "entries": [
    {
      "country": "EU",
      "country_code": "EU",
      "regulate_type": "제한",
      "notice_ingr_name": "(2E,4E,6E,8E)-3,7-dimethyl-...",
      "proviso": null,
      "limit_condition": "* 【Restrictions】\nProduct Type, body parts : (a) Body lotion\n... (원문 그대로)",
      "source_type": "limit"
    }
  ],
  "markets_listed": ["EU"],
  "data_source": "Ministry of Food and Drug Safety (MFDS, ...), European Commission CosIng Database (...)",
  "disclaimer": "Regulatory reference data only. ...",
  "source_updated_at": null,
  "queried_at": "2026-09-23T10:21:56+09:00"
}
```

### POST `/api/regulatory/extract` (multipart/form-data)

업로드 문서에서 성분명·함량을 추출한다. **규제 API 를 호출하지 않고 API 성분 매칭도 하지 않는다.** 서버는 파일을 OS 임시 경로에서 처리하고 요청이 끝나면 삭제한다.

| 항목 | 내용 |
|---|---|
| 필드 | `file` 필수 (PDF · .xlsx · PNG · JPG 1개), `sheet` 선택 (Excel 시트명) |
| 제한 | 10 MB 이하 · PDF 20쪽 이하 · Excel 시트 20개 이하 · 시트당 앞 2,000행 · 성분 행 200개 · OCR 파일당 10쪽/90초, 쪽당 25초, 이미지 3,000만 화소 |
| 성공 200 | `status`: `extracted`(성분 있음) / `empty`(성분 표 없음) / `sheet_required`(시트 선택 필요) |
| 검증 실패 400 | `error.kind = validation`(파일 없음·빈 파일·알 수 없는 확장자·없는 시트) / `limit`(용량·쪽수·시트 수 초과) |
| 형식 미지원 415 | `error.kind = unsupported` — .gif·.webp·.tif·.xls·.csv 등, 텍스트도 없고 OCR 도 없는 PDF |
| 읽기 실패 422 | `error.kind = unreadable`(손상·암호 PDF, 확장자와 내용 불일치) / `ocr_timeout` / `ocr_failed` |
| OCR 준비 안 됨 503 | `error.kind = ocr_unavailable` — 이미지 또는 스캔 전용 PDF 인데 Tesseract·언어 데이터·pip 패키지가 없음. 메시지에 부족한 항목과 설치 안내 포함 |

```json
{
  "ok": true,
  "status": "extracted",
  "file": {"name": "brief.pdf", "kind": "pdf", "size": 8458},
  "scope": {"pages": 3, "processed": "1~3쪽"},
  "items": [
    {"id": "r1", "name_raw": "Niacinamide", "amount_raw": "4.0%", "amount_unit_hint": null,
     "role_raw": "Required finished-product target", "location": "2쪽", "needs_review": false, "review_reasons": []}
  ],
  "review_count": 0,
  "notes": [],
  "document_market": {"text": "European Union: France and Germany", "location": "1쪽"},
  "document_use": {"text": "Leave-on; adult facial skin. ...", "location": "2쪽"},
  "extracted_at": "2026-09-23T14:30:00+09:00"
}
```

- 여러 시트인 Excel 은 `sheet` 없이 보내면 `{"status": "sheet_required", "sheets": ["Cover", "Ingredients", ...], "items": []}` 를 돌려준다. 화면은 시트를 고른 뒤 **같은 파일을 `sheet` 와 함께 다시** 보낸다. Excel 응답의 `scope` 는 `{"sheets", "selected_sheet", "scanned_rows"}`.
- 추출 규칙: `INCI name / Ingredient / 성분명 / 원료명` 등 제목이 있는 표만 읽는다(제목 행은 2칸 이상, 함량·역할 열이 함께 있거나 제목이 정확히 성분 제목일 때). 제목이 없으면 `status = empty` 로 돌려주고 성분을 만들지 않는다.
- `amount_raw` 는 문서 원문 그대로(수치·범위·단위·`q.s.`). 없으면 `null`. Excel 에서 열 제목에만 단위가 있으면 `amount_unit_hint`(예: `"%"`)로 따로 준다.
- `needs_review` 사유: 문장처럼 보이는 이름(7단어 이상·문장 부호), 80자 초과, 함량 형식 불일치(원문 유지), 빈 이름, 함량 열이 있는 표에서 함량 칸을 못 찾은 행.
- `document_market` / `document_use` 는 `Distribution countries`·`대상 국가`·`Application`·`제품 유형` 같은 라벨 행의 **원문 텍스트**다. 시장 코드로 바꾸거나 자동 선택하지 않는다.
- `location`: PDF 는 `N쪽`(OCR 쪽은 `N쪽 (OCR)`), Excel 은 `시트명!B7`, 이미지는 `이미지 (OCR)`. 각 항목의 `source` 는 `text` | `ocr`.
- 항목에 `inci_raw`(같은 행의 영문/INCI 이름 열 원문, 없으면 null)가 추가되었다. 한글 열이 비어 있으면 영문명이 `name_raw` 가 된다.
- 응답의 `ocr` 객체: `{available, engine, applied_pages, skipped_pages, no_text_pages, message, psm, retried, header_found, outcome}`. `outcome` 은 이미지에서 `extracted` / `no_rows`(제목은 찾았으나 행 없음) / `no_header`(글자는 읽었으나 표 제목 없음, notes 에 인식된 줄 예시) / `no_text`(글자 인식 실패). PDF 는 텍스트가 20자 미만인 쪽만 OCR 하고(`scope.text_pages` / `scope.ocr_pages`), OCR 로 읽은 행은 모두 `needs_review = true` 에 사유 "OCR 인식 결과예요…" 가 붙는다. `file.kind` 는 `pdf` | `xlsx` | `image`.

**`lookup_status` 판정 규칙** (응답의 `data`와 `result_status`만 사용)

| 값 | 조건 | 화면 조회 상태 |
|---|---|---|
| `found` | `result_status = "listed"` 이고 `data`가 비어 있지 않음 | 규제 정보 조회됨 |
| `no_data` | `result_status = "not_listed_in_country"` 이고 `data = []` — 요청 시장 항목 없음. `result_note` 가 "다른 시장에 있음" 또는 "요금제 밖 시장에만 있음(markets outside your plan)" 을 안내 | 규제 데이터 미확인 (허용·안전 아님). 화면은 안내문 원문과 `note_mentions_plan` 여부만 표시 |
| `not_listed` | `result_status = "not_listed"` 이고 `data = []` — "No restriction or prohibition is listed for this ingredient in our source data" (2026-09-23 확인, `regulations_1941_eu_not_listed.json`) | 규제 목록 미등재 (허용·안전 아님) |
| `hold` | 확인하지 않은 `result_status` 값, 또는 `listed`인데 `data = []` 등 예상 밖 조합 | 판단 보류 · 추가 확인 필요 |
| (오류) | HTTP 오류·연결 실패·`success != true`·형식 불일치 → 502 `error` | `error.kind` 가 `access`(403)·`auth`(401)·`rate_limit`(429) 이면 화면 ‘접근 제한’, 그 외는 ‘API 오류’ (미확인으로 바꾸지 않음) |

- `ingredient.regulation_status`(예: `Restricted`)는 성분 전체 속성이라 **선택 시장의 상태로 쓰지 않으며 응답에서 제외**한다.
- `markets_outside_plan` 은 원문 값을 그대로 전달하지만 의미가 문서에 없어 화면에서 해석하지 않는다. `note_mentions_plan` 은 `result_note` 에 "outside your plan" 문구가 있는지 여부만 나타낸다(요금제 제한으로 단정하지 않음). 응답에 `note_mentions_plan`, `markets_outside_plan` 필드가 추가되었다.
- `limit_condition`, `proviso`, `notice_ingr_name`은 가공 없이 원문 그대로 전달한다.
- `source_updated_at`은 응답에 규제 자료 갱신일이 없어 항상 `null`(화면 '미제공'). `queried_at`은 서버가 외부 API 응답을 받은 시각이며 `acquired_at`(데이터 확보 시각)과 같다. `law_dates` 는 항상 `null`(법령 개정·적용일 미제공). `refresh_policy` = "월 1회 (제공자 안내 기준)", `refresh_basis` = 제공자 공개 README “Update Frequency | Monthly”(2026-09-23 확인) — 마지막 갱신일은 제공되지 않으므로 화면은 역산하지 않는다.

## 2. 외부 API (K-Beauty Cosmetic Ingredients / RapidAPI)

| 항목 | 내용 |
|---|---|
| 기본 주소 | `https://k-beauty-cosmetic-ingredients.p.rapidapi.com` (`RAPIDAPI_HOST`) |
| 인증 헤더 | `x-rapidapi-key`, `x-rapidapi-host` — 서버만 보유 |
| 타임아웃 | 연결 5초 / 읽기 15초 (`regulatory_service.py`) |
| 재시도·캐시 | 없음 (화면의 '다시 시도' 버튼으로 수동 재조회) |

### 확인된 호출 (2026-09-23 실제 호출, `test_data/`)

| 파일 | 호출 | HTTP | 확인 내용 |
|---|---|---|---|
| `search_kr_retinol.json` | `GET /v1/ingredient/kr?q=레티놀` | 200 | `success=true, count=1`, `data[0].code=5489`, `kr_name=레티놀`, `inci_name=Retinol`, `regulation_status=Restricted`, `updated_at` 있음 |
| `search_kr_partial_reti.json` | `GET /v1/ingredient/kr?q=레티` | 200 | `count=15`, 모두 `레티`로 **시작**하는 한글명 (레티놀·레티닐…·레티노일…). 부분(시작) 검색 지원 확인 |
| `search_kr_partial_etan.json` | `GET /v1/ingredient/kr?q=에탄` | 200 | `count=8`, `에탄`(6203)·`에탄올`(2093)·`에탄올아민`… 명세 예시 확인 |
| `search_kr_english_retinol.json` | `GET /v1/ingredient/kr?q=Retinol` | 200 | `success=true, count=0, data=[]` — 한글 엔드포인트는 영문 미지원 |
| `search_inci_partial_retin.json` | `GET /v1/ingredient/inci?q=retin` | 200 | `count=17`, 소문자 입력으로 `Retinol`·`Retinal`·`Retinyl …` 반환 — 영문 시작 일치·대소문자 무시 확인 |
| `regulations_5489_eu.json` | `GET /v1/ingredient/5489/regulations?country=EU` | 200 | `result_status=listed`, `count=1`, `data[0].limit_condition`에 제품 유형·최대 농도(0,05 % / 0,3 % RE)·표시 문구 원문, `source_type=limit`, `markets_listed=["EU"]` |
| `regulations_5489_us.json` | `GET /v1/ingredient/5489/regulations?country=US` | 200 | `result_status=not_listed_in_country`, `count=0`, `data=[]`, `result_note="No entry for US in our source data. There are entries for other markets."` |
| `regulations_1013_eu_plan_note.json` | `GET /v1/ingredient/1013/regulations?country=EU` (Glycerin) | 200 | `not_listed_in_country`, `markets_listed=[]`, `markets_outside_plan=1`, `result_note="No entry for EU in our source data. There are entries for markets outside your plan only."` — KR·CN 도 같은 응답(미저장) |
| `regulations_1941_eu_not_listed.json` | `GET /v1/ingredient/1941/regulations?country=EU` (Niacinamide) | 200 | **`result_status=not_listed`**, `count=0`, `result_note="No restriction or prohibition is listed for this ingredient in our source data."`, `ingredient.regulation_status=Not Listed` |
| (미저장) | `GET /v1/ingredient/3579/regulations?country=EU` (Phenoxyethanol) | 200 | `listed`, `count=1`, 최대 농도 1.0%, `markets_listed=[KR,EU,CN,JP,ASEAN]`, `markets_outside_plan=3` |

응답 공통 필드: `data_source`(MFDS + EU CosIng), `disclaimer`, `available_country_codes = ["KR","EU","CN","US","JP","ASEAN"]`, `available_countries`(한글 표시명), `country.{requested, resolved, code}`.

호출 제한 헤더(2026-09-23 관측): `X-RateLimit-Requests-Limit: 25000`, `X-RateLimit-Requests-Remaining: 24906`(4단계 확인 호출 4회 후). 월 단위 요청 한도로 보이나 요금제 문서로 재확인 필요.

**엔드포인트 문서 출처**: API 제공자의 공개 저장소 README(github.com/han-tagg/Korean-cosmetic-ingredients-api). 검색 엔드포인트 `/v1/ingredient/{inci|kr|cas}?q=`는 모두 "starts with", `/v1/ingredient/search?q=&field=inci|kr|cas|all`은 "contains"이며 PRO+ 전용, 검색어 최소 2글자. 문서에 오류 응답 형식은 없다.

### 아직 확인하지 않은 것 (4단계 이후)

- 중간 포함 검색 `/v1/ingredient/search`(PRO+)의 실제 동작·현재 요금제 사용 가능 여부 (미호출). 동의어 검색 지원 여부
- `result_status` 전체 값 목록(확인: listed / not_listed_in_country / not_listed), 오류 응답(4xx/5xx) 본문 형식. 요금제 밖 시장·미구독 엔드포인트가 403 인지 200+안내문인지는 미확인(Glycerin 사례는 200)
- `ASEAN` 조회가 아세안 공통 기준인지 개별 국가 규정을 포함하는지
- `markets_outside_plan` 의미, 규제 자료 갱신일 제공 여부
- 429 초과 시 응답 형식. 자동완성은 300ms 디바운스·조합 중 미요청으로 호출을 줄이며 캐시는 없음

## 3. 화면 흐름 (직접 검색, 2단계 — 식약처 수집 DB 전용)

1. 성분명(한글명·영문명·이명·CAS) 입력 → 앞뒤 공백 제거 후 2글자 이상이고 한글 조합이 끝난 뒤 300ms 동안 입력이 없으면 `/api/regulatory/search` → 검색창 아래 후보 최대 10개 (로딩 / 후보 없음 / 후보 검색 실패 중 하나만 표시). 후보마다 한글명·영문명·출처 배지(**성분정보**·**규제정보**)·일치 근거(예: '영문명 정확 일치 (나열된 이름 중 하나)', '이명 정확 일치 · 원문'). 목록 머리에 전체 후보 수·출처별 정확 일치 수, 잘렸으면 'N건 중 10건만 표시 — 검색어를 구체적으로'. 입력이 바뀌거나 목록이 닫히면 진행 중 응답은 무시한다(`acSeq`). 직접 검색에는 출처 선택지·함량·제품 조건 입력이 없다.
2. 후보 클릭 또는 ↑↓ + Enter 로 성분 선택 → 목록 닫힘, 검색창 아래 "선택한 성분 · 출처" 표시. **이 단계에서 규제 조회는 하지 않는다.**
   - **후보가 하나이거나 정확 일치가 하나여도 자동 선택·자동 조회하지 않는다** (1단계 이전의 '정확 일치 자동 확정'은 직접 검색에서 제거, 파일 매칭에만 남음). 선택 전 검색 버튼은 후보 목록만 열고 '목록에서 직접 선택' 안내를 보인다. 목록이 열릴 때 활성 후보는 없다.
   - 선택은 서버가 준 `key` 로만 기억한다 (`state.selected.key`). key·내부 id·해시는 화면에 표시하지 않는다.
3. 선택한 상태에서 **검색 버튼** → `/api/regulatory/lookup?key=&country=` → **결과 카드** 1장: 고른 성분명·영문명·시장, 조회 상태, 규제 유형(원문), 규제 조건(조건별 레코드 모두), 관련 항목(분리), **선택한 성분 출처·수집 시각 / 성분 연결 근거 / 규제 조회 출처·수집 시각**(따로 표시), '규제 원문·출처 보기' → 상세 Modal.
   - 결과 영역은 `loading / error / single / batch` 중 한 블록만 표시한다. 요청 완료·실패 시 로딩과 버튼 비활성은 항상 해제된다.
   - 상태 배지: `found` '규제 정보 조회됨'(중립) · `no_market_record` '선택 국가 기록 없음' · `link_required` '성분 연결 확인 필요'(근거 + 규제 후보 목록, 후보마다 '이 규제 성분으로 조회' 버튼 = 사용자가 명시적으로 고를 때만 조회) · `not_linked` '규제 성분 연결 미확인'. 모두 '허용·안전·규제 없음을 뜻하지 않아요' 안내. 오류: `db_*` '출처 이용 불가 (… · 성분정보/규제정보)', `stale_key`·`not_found` '후보 다시 선택 필요' — 선택을 해제하고 '다시 시도'는 이전 key 로 조회하지 않는다.
   - 검토 상태·기준 비교·입력 부족 안내는 표시하지 않는다. 적합성·안전성 판정을 생성하지 않는다.
4. **규제 조건 표시 규칙** (`regulatory.js` `parseConditionText` / `renderConditions`)
   - `limit_condition` 원문이 `* 【태그】 라벨 : 값` 블록 구조이면 블록별로 나누고, 먼저 언어별로 배치한다: 라벨(없으면 태그·값)에 한글이 있으면 한국어, 아니면 영문. **영문 전체가 위(English · API 제공 영문), 한국어 전체가 아래(한국어 · API 제공 한국어)** 이며 한 언어만 있으면 그 언어만 표시한다. 한국어 문장 안의 영문 성분명·단위는 분리하지 않는다. 각 언어 안에서 라벨 키워드로 묶는다: 적용 제품·부위(`product type`, `body part`, `제품 유형`, `사용 부위`) / 최대 농도(`maximum concentration`, `최대 농도`) / 사용 조건·주의 문구(`conditions of use`, `warning`, `사용 조건`, `주의`) / 분류가 불확실한 블록은 '기타 원문'에 라벨 그대로 누락 없이.
   - 값 안의 `(a) … (b) …` 는 표기를 유지한 채 줄로 나눈다. 글자 표기가 적용 제품과 최대 농도의 대응 관계이며, 둘 이상 그룹에 표기가 있으면 안내 문구를 붙인다.
   - 블록 하나라도 `라벨 : 값` 으로 읽을 수 없으면 나누지 않고 원문 전체를 `pre-wrap` 으로 표시하고 "원문 구분이 확실하지 않아 그대로 표시했어요"를 붙인다.
   - 규제 항목(`entries`)이 여러 건이면 항목별 제목(순번·유형·국가)으로 구분하고, `proviso` 가 있으면 '단서 조항 (원문)' 블록으로 붙인다.
   - 문장은 재배치만 하며 번역·요약·환산·재해석을 하지 않고, 성분별 규칙을 두지 않는다. 원문 전체·출처·고시 성분명·응답 상태값은 상세 Modal 에 그대로 둔다.
5. '이전 조건의 결과' 안내는 표시 중인 결과의 조건 키(직접 검색: 후보 key·시장 / 파일: 시장 + 행별 검색어·선택 key)와 현재 입력이 다를 때만 보이고, 같은 조건으로 돌아오면 사라진다. 검색어를 수정하면 선택한 성분은 해제된다. 조회 중 시장을 바꾸면 늦게 온 응답은 '이전 조건의 결과'로 표시된다.
6. **파일 탭 (현재 구현)**: 파일·시장 선택 → ‘파일 분석’ → 화면에서 확장자·용량을 먼저 확인(이미지 등은 업로드 없이 미지원 안내) → `POST /api/regulatory/extract` → `sheet_required` 면 시트 선택 블록 → 선택 후 재전송 → 추출값 확인·수정 표(조회 포함 체크 · 원문 성분명→수정 · 함량 원문→수정(미기재 표시) · 원문 위치 · 상태(추출됨/확인 필요/수정됨/직접 입력) · 삭제, ‘행 추가’). 처리 중·실패(사유·종류)·추출 결과 없음을 한 블록씩만 표시한다. 편집값은 `fileState.items` 에만 있고 서버로 보내지 않는다.
7. **성분 확인·규제 일괄 조회 (3단계, 식약처 수집 DB 전용 · 새 Route 없음)** — 파일 탭 출처 선택지는 없고 '조회 자료' 안내(`regulatory-file-datasource`)만 있다.
   - 행 상태는 따로 보관한다: `name_raw`(추출 원문, 덮어쓰지 않음) · `name`(사용자가 고친 검색어) · `match`(마지막 후보 검색 결과) · `selected`{candidate·method·from}(사용자가 고른 후보) · `result`(규제 조회 결과).
   - **‘성분 확인’** → 조회 포함·미선택 행마다 `GET /api/regulatory/search?q=` 순차 호출. 같은 검색어(공백·대소문자 무시)는 한 작업 안에서 1회만 요청하고 결과를 공유하되 선택은 행별. 2글자 미만은 요청 없이 '검색 오류'. 검색 DB 이용 불가면 남은 행은 같은 이유의 검색 오류로 두고 중단.
   - 행 표시: 후보마다 한글명·영문명·출처 배지(성분정보·규제정보)·일치 근거. 잘렸으면 'N건 중 10건만 표시 — 성분명을 구체적으로'. key·내부 id·해시는 표시하지 않는다(select option 값은 목록 순번).
   - **추천 기준**: 제한 전 `exact_total === 1` 이고 그 후보가 한글명·표준명·영문명에서 정확 일치했을 때만 '추천 · 선택 전'. 이명·고시원료명·CAS 만 일치, 정확 일치 여러 개(Water: 정제수·탄산수 / 레티놀처럼 양쪽 DB) → '후보 선택 필요'. **추천은 선택이 아니다** — 행의 '추천 후보 선택' 또는 '추천 N건 선택 완료'(지금 추천 조건인 행만)를 눌러야 조회 대상. 후보 없음 '검색 결과 없음', 실패 '검색 오류'로 따로 남긴다.
   - **‘선택 성분 규제 조회’** → 선택 완료 행만 `GET /api/regulatory/lookup?key=&country=` 를 (key, 시장)당 1회 순차 호출 (이름·CAS 를 보내지 않음, 서버 `lookup_candidate`·연결 규칙 그대로). 같은 이름이라도 key 가 다르면 따로. 결과는 '아직 표에 있고 조회 포함이며 같은 key 를 선택한 행'에만 쓴다 → 조회 중 수정·삭제·제외·후보 변경된 행과 새 파일·시트(순번 `batchSeq`·`matchSeq`)를 덮어쓰지 않는다. 진행 중에는 확인·조회·추천 버튼이 중복 실행되지 않는다.
   - 오류: `stale_key`·`not_found` → 그 행 선택 해제 + 이전 후보 목록 폐기('후보 다시 검색 필요'), 재시도 대상 아님, '조회 중 수집본이 바뀌었어요' 안내. `db_*` → 그 자리에서 중단, 남은 행은 '조회 오류 · 출처 이용 불가 (이유)'로 미조회 표시(호출 한도 초과로 표시하지 않음). 네트워크 등 일시 오류 → '조회 오류', **‘실패 항목 재시도’는 현재 시장·같은 key 가 유지되는 재시도 가능 행만**. 규제정보 수집본이 결과마다 다르면 같은 기준으로 보이지 않게 안내.
   - 결과 표: 성분명(추출 원문·선택 원료·조회한 규제 성분·연결 근거·문서 함량) · 선택 시장(규제정보 수집 시각) · 조회 상태(직접 검색과 같은 문구: 규제 정보 조회됨 / 선택 국가 기록 없음 / 성분 연결 확인 필요 / 규제 성분 연결 미확인 / 조회 오류, 그리고 미조회 상태: 추천 · 선택 전 / 후보 선택 필요 / 검색 결과 없음 / 검색 오류 / 후보 다시 선택 필요) · 규제 유형 · 상세. 성분 연결 확인 필요 행은 직접 검색과 같은 연결 후보 목록 + '이 규제 성분으로 조회' — 그 행의 선택·결과만 바뀌고(처음 고른 원료는 `selected.from` 으로 보존) 직접 검색 탭·다른 행은 그대로. 관련 항목은 건수만 따로(상세에서).
   - 집계(KPI): 조회 포함 / 조회됨 / 선택 국가 기록 없음 / 규제 성분 연결 확인(필요+미확인) / 조회 오류 / 미조회. 미조회 행이 있으면 '일부 성분만 규제를 조회했어요 — 전체 성분 검토가 끝난 것이 아니에요' 안내. 출처·시각은 성분정보(고른 성분정보 후보의 수집본)와 규제정보(조회 결과)를 따로 표시. 함량은 문서·사용자 입력값만, 적합 판정 없음. 상세 Modal 은 직접 검색과 공유(`input-amount`·`input-location` 추가).
8. **3단계에서 제거한 것**: 파일 탭 출처 radio(`regulatory-file-source`) · `fileSource()`·`groupSource()`·`syncSourceCards()` · `regulationsUrl()` · `findExactMatch()`·`confirmMatch()`·'정확 일치 자동 확정' · `candidateLabel()`·`confirmedRows()`·`BATCH_LABEL` · code 기반 선택·요청 묶기·캐시·`batchKey` · 'API 매칭'·'확정 성분' 문구 · KPI '접근 제한'·'API 오류'(→ 조회 오류) · rate_limit 기준 중단.
9. **4단계 삭제 대상 (화면은 이미 호출하지 않음)**
   - app.py: `regulatory_ingredients`(`/api/regulatory/ingredients`) · `regulatory_regulations`(`/api/regulatory/regulations`, source=mfds·api) · `_regulatory_error` · `regulatory_service` 로드. 단 `/api/regulatory/lookup` 의 국가 검증이 `regulatory_service.MARKET_CODES` 를 쓰므로 `regulatory_search`/`regulatory_mfds_lookup.MARKET_CODES` 로 바꾼 뒤 삭제.
   - `regulatory_service.py`(K뷰티 호출 전체) · `tests/test_regulatory_service.py` 의 K뷰티 검색·규제·HTTP 분류·Route 테스트(추출·OCR 테스트는 남김) · `test_data/*.json`(K뷰티 응답 기록) · `regulatory_mfds_lookup.lookup()`(이름·CAS 재매칭, `/regulations?source=mfds` 전용)과 그 테스트.
   - **챗봇 의존**: `src/06_chatbot/tools.py` 가 `regulatory_service.search_ingredients`·`get_regulations`·`MARKET_CODES`·`MIN_QUERY_LENGTH` 와 `regulatory_mfds_lookup.lookup()` 을, `server.py` 가 `RAPIDAPI_*` 확인을 쓴다 — 챗봇 담당과 `regulatory_search` 로 전환을 합의한 뒤 삭제한다 (다른 담당 파일은 임의로 수정하지 않음).
   - regulatory.js: `SOURCE_LABEL.api` · `LOOKUP_LABEL` 의 K뷰티 상태(`no_data`·`not_listed`·`hold`·`api_error`·`access`) · `ACCESS_KINDS`·`errorCategory` 의 access 분기 · `statusLabel`·`noDataReason`·`acquiredText`·`refreshText`·`scopeText`·`sourceText` 의 api 분기(`note_mentions_plan` 등) · `fillModal` 의 `sel.code`·`record_updated_at`·'K뷰티 API 는 성분 code 로 조회' 분기 · `ingredientKr` 의 code 대체 표시.
   - 문서·설정: 이 문서 2장(외부 K뷰티 API) · `regulatory.md`·`demo_verification.md` 의 K뷰티 설명 · README·`docs/deploy_render.md`·`docs/team_onboarding.md` 의 `RAPIDAPI_KEY`·`RAPIDAPI_HOST` 안내(공통 문서 — 담당 범위 확인 후) · 배포 환경변수.

**공통 CSS 관련 PM 협의 사항**: `src/common/style.css`에 `[hidden] { display: none }` 규칙이 없어 `.loading`, `.state`, `.badge`, `.alert`처럼 class로 `display`를 지정하는 요소는 `hidden` 속성이 무시된다(로딩·오류·후보 상태가 동시에 보이던 원인). 공통 파일은 수정하지 않고 `regulatory.css`에서 이 페이지 영역(`#regulatory-panel-search`, `#regulatory-panel-file`, `#regulatory-results`, `#regulatory-detail-modal`)에만 `[hidden] { display: none !important }`를 적용했다. 공통 CSS에 같은 규칙을 추가하면 페이지 규칙은 제거해도 된다.
