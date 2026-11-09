# COSMOA 공통 저장 API 계약 (공통 개발 문서)

> **상태: 2단계 구현됨** — 서버 API·DB(`0003_versioning`, test·dev 적용). **화면(저장 버튼·개발요청서 연결)은 아직 연결하지 않았다** (3단계).
> **3-1단계 구현됨** — 고객사·프로젝트 생성·조회 API 와 개발요청서의 프로젝트 선택 화면 ([5장](#5-고객사프로젝트-생성조회-api--3-1단계-구현됨)).
> **임시저장 API(6장)는 설계 단계·미구현이다.** 서버 코드·DB 테이블 모두 아직 없다.
> 코드: `src/common/versions_api.py`(경로) → `versions.py`(업무 규칙) → `versions_repo.py`(SQL), payload 검증 `payloads.py`.
> 규칙 근거: [DB 규칙](db_rules.md) 3·4·5장, [데이터 계약](data_contract.md) 2·3·5·6장.

---

## 1. 공통

### 1-1. 인증·사용자 범위

- 세션 쿠키 로그인(`/login`) 후 사용한다. 로그인하지 않으면 **401** (JSON).
- 로그인한 팀 사용자 전체가 모든 프로젝트·저장본을 조회·저장한다 (개발용 기본 정책, `db_rules.md` 3-5). 운영 권한 체계는 별도 확정 항목. 임시저장은 예외로 본인만 쓴다 (6장, 미구현).
- 작성자(`created_by`)는 **서버 로그인 사용자**로 정한다. 버전 번호(`version_no`)는 **DB 가 부여**한다. 요청 본문에 `created_by`·`version_no` 등 받지 않는 필드가 있으면 400 `unknown_fields`.

### 1-2. CSRF — 변경 요청(POST)

1. `GET /api/csrf-token` 으로 토큰을 받는다 (로그인할 때 세션에 만들어짐).
2. POST 요청에 **`X-CSRF-Token: <토큰>` 헤더**와 **`Content-Type: application/json`** 을 붙인다.
3. 토큰이 없거나 다르면 **403** `csrf_failed`, JSON 이 아니면 **400** `json_required`.
4. `Common.api`(`src/common/common.js`)는 **403 `csrf_failed` 일 때만** 새 토큰으로 한 번 다시 보낸다 (CSRF 거부는 서버가 처리 전에 막으므로 중복 처리 없음). 네트워크 오류·503·다른 403·409 등은 다시 보내지 않는다 — 생성·저장이 두 번 처리되지 않도록.
5. 로그인 폼(`POST /login`)도 CSRF 토큰을 확인한다: 로그인 화면이 로그인 전 세션에 토큰을 만들어 hidden 필드(`csrf_token`)로 보내고, 없거나 다르면 비밀번호 확인 전에 400 으로 거부한다. 로그인하면 이 토큰은 지워지고 위 세션 토큰을 쓴다.

```http
GET /api/csrf-token
→ 200 {"ok": true, "csrf_token": "Qm9…", "header": "X-CSRF-Token"}
```

### 1-3. 응답 형식

성공: `{"ok": true, ...}` / 실패: `{"ok": false, "error": {"code": "...", "message": "...", ...}}`
오류 응답에는 SQL·접속 정보·내부 예외 내용을 넣지 않는다.

| 상태 | 언제 | `error.code` 예 |
|---|---|---|
| 400 | 잘못된 입력·참조 | `missing_field`, `unknown_field`, `invalid_value`, `duplicate_value`, `required_field`, `context_project_mismatch`, `context_customer_mismatch` (개발요청서 v1 계약), `invalid_payload`, `invalid_tab`, `unsupported_schema_version`, `file_content_not_allowed`, `unknown_fields`, `missing_fields`, `invalid_parameter`, `invalid_json`, `json_required`, `invalid_based_on`, `invalid_link`, `invalid_link_source`, `invalid_version_scope`, `expected_final_history_id_required`, `already_final`, `no_final`, `project_archived`, `invalid_reference`, `customer_archived` |
| 401 | 로그인 안 함 | `unauthorized` |
| 403 | CSRF 토큰 없음·불일치 | `csrf_failed` |
| 404 | 고객사·프로젝트·저장본 없음 | `customer_not_found`, `project_not_found`, `version_not_found` |
| 409 | 최종본을 다른 사람이 먼저 바꿈 | `final_conflict` (+ `current`) |
| 413 | 크기 초과 (잘라 저장하지 않음) | `payload_too_large`, `request_too_large` |
| 503 | 업무 DB 장애 | `db_unavailable`, `retry_later` |

### 1-4. 탭

`tab` ∈ `regulatory` / `margin` / `simulation` / `requisition`. 그 외는 400 `invalid_tab`.

---

## 2. 경로

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/csrf-token` | CSRF 토큰 |
| POST | `/api/projects/<project_id>/tabs/<tab>/versions` | 새 버전 저장 (201) |
| GET | `/api/projects/<project_id>/tabs/<tab>/versions?limit=&before=` | 버전 목록 (payload 제외, 최신순) |
| GET | `/api/versions/<version_id>` | 저장본 불러오기 (payload·반영 출처 포함) |
| GET | `/api/projects/<project_id>/tabs/<tab>/final` | 현재 최종본 |
| POST | `/api/projects/<project_id>/tabs/<tab>/final` | 최종본 지정·변경·해제 |
| GET | `/api/projects/<project_id>/tabs/<tab>/final/history?limit=&before=` | 최종본 이력 (최신순) |

목록 페이지: `limit` 기본 20, 최대 100. 다음 페이지는 응답의 `next_before` 를 `before` 로 보낸다 (없으면 `null`).
고객사·프로젝트 생성·조회 API 는 5장.

### 2-1. 새 버전 저장

```http
POST /api/projects/12/tabs/requisition/versions
X-CSRF-Token: Qm9…
Content-Type: application/json

{
  "schema_version": 1,
  "title": "비타민 세럼 요청서",
  "based_on_id": 41,
  "payload": {
    "context": {"customer_id": 7, "project_id": 12, …},     // 개발요청서 v1 전체: db/schemas/requisition.v1.example.json
    "inputs": {"product_name": "Vitamin C Serum", "target_prices": [{"amount": 1300, "currency": "KRW"}], …},
    "outputs": {},
    "meta": {"field_provenance": […], "reference_files": [{"name": "benchmark.png", "size": 183204, "type": "image/png", "data_url": "data:…"}]}
  },
  "links": [
    {"source_version_id": 37, "applied_values": {"target_field": "ingredients.other_notes", "inserted_text": "[견적 사양 변경 (VE) 반영] …"}}
  ]
}
```

```json
201
{
  "ok": true,
  "version": {"id": 45, "project_id": 12, "tab": "requisition", "version_no": 4, "title": "비타민 세럼 요청서",
              "schema_version": 1, "based_on_id": 41, "based_on_version_no": 2,
              "created_by": {"id": 3}, "created_at": "2026-10-20T03:12:44.120+00:00", "is_final": false},
  "base": {"based_on_id": 41, "based_on_version_no": 2, "latest_version_no_before_save": 3, "is_stale": true},
  "links": [{"id": 9, "source_tab": "margin", "source_version_id": 37}],
  "validation": {"schema": "requisition.v1", "level": "full", "fully_validated": true,
                 "note": "개발요청서 저장 계약 v1 전체 검사 (data_contract.md 4장)",
                 "removed_fields": ["meta.reference_files[0].data_url"], "payload_bytes": 2094}
}
```

- 서버 순서: **프로젝트 행 잠금 → (DB 트리거가) 다음 `version_no` 부여 → 저장본·반영 출처 추가 → 커밋.** 하나라도 실패하면 전부 롤백 (저장본도 번호도 남지 않음).
- `based_on_id`: 같은 프로젝트·같은 탭 저장본만 (아니면 400 `invalid_based_on`). 최신이 아닌 저장본에서 시작해도 **저장은 진행**하고 `based_on_id` 를 그대로 남긴다. `base.is_stale = true` 와 저장 직전 최신 번호로 알린다 — 화면이 안내한다.
- `links`: 같은 프로젝트의 **다른 탭** 저장본만 (같은 탭이면 `based_on_id` 로, 다른 프로젝트면 400 `invalid_link_source`). 한 번에 최대 20개, 같은 출처 중복 불가. `applied_values` 는 비어 있지 않은 객체.
- 규제 메모(`regulatory_notes`) 출처는 4단계에서 추가한다. 지금은 저장본 출처만 받는다.
- 보관된 프로젝트에는 저장할 수 없다 (400 `project_archived`).
- 개발요청서 v1 은 payload 의 `context.project_id`·`customer_id` 가 URL 프로젝트·그 고객사와 같아야 한다 (400 `context_project_mismatch` / `context_customer_mismatch`). 이름 사본은 서버가 DB 값으로 저장한다. 계약 전체: [데이터 계약](data_contract.md) 4-5.
- 정식 저장 성공 시 임시저장을 지우는 연동은 6-5 (설계 단계·미구현). 지금 이 API 는 임시저장을 다루지 않는다.

### 2-2. 버전 목록 / 불러오기

```http
GET /api/projects/12/tabs/requisition/versions?limit=2
→ 200 {"ok": true, "limit": 2, "next_before": 3,
       "items": [{"id": 45, "version_no": 4, "title": "…", "schema_version": 1, "based_on_id": 41, "based_on_version_no": 2,
                  "created_by": {"id": 3, "name": "홍길동"}, "created_at": "…", "is_final": false, "payload_bytes": 431, …},
                 {"id": 44, "version_no": 3, …, "is_final": true}]}

GET /api/versions/45
→ 200 {"ok": true, "version": {…목록 항목과 같은 필드…, "payload": {"context": {…}, "inputs": {…}, "outputs": {}, "meta": {…}},
                                "links": [{"id": 9, "source_tab": "margin", "source_version_id": 37, "source_version_no": 3,
                                           "applied_values": {…}, "created_at": "…"}]}}
```

- 불러온 저장본에는 원본 파일·참고자료 본문이 없다 (저장하지 않음). 화면은 이를 안내한다 (`db_rules.md` 6장).

### 2-3. 최종본 조회·지정·변경·해제

```http
GET /api/projects/12/tabs/requisition/final
→ 200 {"ok": true, "final": {"final_history_id": 7, "action": "set", "version": {"id": 44, "version_no": 3},
                              "changed_by": {"id": 3, "name": "홍길동"}, "changed_at": "…"}}
   (기록이 없으면 모든 값이 null)

POST /api/projects/12/tabs/requisition/final
{"action": "set", "version_id": 45, "expected_final_history_id": 7}
→ 200 {"ok": true, "final": {"final_history_id": 8, "action": "set", "version": {"id": 45, "version_no": 4}, …}}

POST /api/projects/12/tabs/requisition/final
{"action": "unset", "expected_final_history_id": 8}
→ 200 {"ok": true, "final": {"final_history_id": 9, "action": "unset", "version": null, …}}
```

- `expected_final_history_id`: 화면이 알고 있는 현재 기록 id. **기록이 없으면 `null` 을 보낸다.** 필드를 아예 빼면 400 `expected_final_history_id_required` (null 과 누락을 구분).
- 서버는 프로젝트 행을 잠근 뒤 마지막 기록 id 와 비교한다. 다르면 기록을 추가하지 않고 **409** 와 현재 상태를 돌려준다. 화면은 편집 중 내용을 유지하고 바뀐 상태만 보여 준 뒤 사용자가 다시 결정한다.

```json
409
{"ok": false, "error": {"code": "final_conflict", "message": "다른 사용자가 먼저 최종본을 바꿨습니다. …",
  "current": {"final_history_id": 8, "action": "set", "version": {"id": 45, "version_no": 4},
              "changed_by": {"id": 5, "name": "김연구"}, "changed_at": "…"}}}
```

- `set` 은 같은 프로젝트·같은 탭 저장본만 (아니면 400 `invalid_version_scope`, 없는 저장본 404). 이미 최종본이면 400 `already_final`. 최종본이 없는데 `unset` 하면 400 `no_final`. `unset` 에 `version_id` 를 보내면 400.
- 최종본 지정은 발송 사실이 아니다 (`db_rules.md` 4-3).

```http
GET /api/projects/12/tabs/requisition/final/history?limit=20
→ 200 {"ok": true, "limit": 20, "next_before": null,
       "items": [{"id": 9, "action": "unset", "version": null, "changed_by": {…}, "changed_at": "…"},
                 {"id": 8, "action": "set", "version": {"id": 45, "version_no": 4}, …}]}
```

---

## 3. payload 검증

| 항목 | 처리 |
|---|---|
| 구조 | 최상위는 `context`·`inputs`·`outputs`·`meta` 네 칸(모두 객체)만. 다른 키는 400. DB 에도 같은 CHECK |
| 탭·버전 | `(tab, schema_version)` 별 검증 구조(`payloads.SCHEMAS`). 지원하지 않는 버전은 400 `unsupported_schema_version`. 현재 네 탭 모두 v1 |
| 검증 수준 표시 | 응답 `validation.level`: `structure`(네 칸·파일 제외·크기만, `fully_validated: false`) — regulatory·margin·simulation / `full`(저장 계약 전체 검사, `fully_validated: true`) — requisition v1 (3-2, [데이터 계약](data_contract.md) 4-5). 다른 탭은 세부 계약이 확정되면 올린다 |
| 파일 본문 | `meta.reference_files[]` 는 `name`·`size`·`type` 만 남김(파일명은 경로 제거). `meta.field_provenance[]` 는 6개 허용 키만. `data_url`·`raw_extracted_data`·`originalFile`·`base64` 등은 어느 깊이에서나 제거하고 `removed_fields` 로 알림. 그 밖의 위치에 **data URL 이나 긴 base64 문자열**(512자 이상, 대·소문자·숫자 혼합)이 있으면 몰래 지우지 않고 400 `file_content_not_allowed` |
| 서버가 정하는 값 | 각 칸·`applied_values` 최상위의 `version`·`version_no`·`document_id`·`created_by`·`author`·`ui_state` 는 제거 (`data_contract.md` 5장) |
| 반영 기록 | `applied_values` 도 같은 제외·파일 본문 검사·크기 상한 |

---

## 4. 크기 제한 — 설정 가능

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `VERSION_PAYLOAD_MAX_BYTES` | 262144 (256 KiB) | 정리 후 payload 의 UTF-8 JSON 바이트 |
| `VERSION_APPLIED_VALUES_MAX_BYTES` | 32768 (32 KiB) | 반영 기록 1건 |
| `VERSION_LINKS_MAX` | 20 | 한 번 저장의 반영 출처 수 |

- 요청 본문 전체 상한 = payload + 반영 기록 × 개수 + 16 KiB 여유 (기본 약 912 KiB). 넘으면 본문을 읽지 않고 413.
- 넘으면 **잘라 저장하지 않고 413** 으로 거부한다.

초기값 근거 — 측정 (2026-10-20, `payloads.json_size`)

| 예시 | 크기 |
|---|---|
| `data_contract.md` 4-2 개발요청서 저장 예시 | 1,868 B |
| 무거운 개발요청서 가정: 현재 30개 필드 각 400자(한글) + 목표 가격대 5개 + 컨셉 원료 15개 + 필드 출처 30개(원문 300자·사용자 값 100자) + 참고자료 메타 10개 | 78,312 B (약 76 KiB) |
| `data_contract.md` 6-3 반영 기록 예시 2개 | 302 B, 278 B |
| 참고: 179 KB 이미지 1장을 base64 로 넣은 경우 | 244,272 B — 파일 본문은 크기와 상관없이 거부 |

- payload 256 KiB = 무거운 개발요청서 가정의 약 3.3배. 마진·모델링 payload 는 아직 계약이 없어 측정하지 못했다. 탭별 대표 데이터가 나오면 다시 정한다 (`db_rules.md` 3-6 "미정" 유지).
- 반영 기록 32 KiB = 예시의 100배 이상. 반영 문구·항목 몇 개를 담는 용도라 충분하다고 본다.

---

## 5. 고객사·프로젝트 생성·조회 API — 3-1단계 구현됨

> 코드: `src/common/projects_api.py`(경로) → `projects_service.py`(업무 규칙) → `projects.py`(SQL, `create_customer()`·`create_project()`).
> 인증(401)·CSRF(403)·JSON 필수·오류 형식은 1장과 같다. **스키마 변경 없음** — 0001·0002 의 `customers`·`projects` 그대로 사용.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/customers?q=&limit=&after=` | 고객사 목록 — 사용 중(보관 안 됨)인 것만, 이름순 |
| POST | `/api/customers` | 고객사 만들기 (201) |
| GET | `/api/customers/<customer_id>` | 고객사 1건 (보관된 고객사도 조회, `archived` 로 표시) |
| GET | `/api/customers/<customer_id>/projects?limit=&before=` | 그 고객사의 프로젝트 목록 — 사용 중인 것만, 최신순 |
| POST | `/api/customers/<customer_id>/projects` | 그 고객사 아래 프로젝트 만들기 (201) |
| GET | `/api/projects/<project_id>` | 프로젝트 1건 (고객사 id·이름 포함, 보관 여부 표시) |

- 페이지: `limit` 기본 20, 최대 100 (넘으면 400). 고객사는 응답 `next_after` 를 `after` 로, 프로젝트는 `next_before` 를 `before` 로 보낸다. 다음이 없으면 `null`.
- `q`: 고객사명 부분 일치(대소문자 무시), 최대 100자. `%`·`_` 는 글자 그대로 찾는다.
- 수정·보관(archive) API 는 아직 없다. 단계·상태·납기일 변경은 이후 `change_project()`(이력 동시 기록)로 연결한다.

### 5-1. 입력 규칙

| 필드 | 규칙 | 근거 |
|---|---|---|
| `name` (고객사·프로젝트 공통, 필수) | 앞뒤 공백 제거 후 1~200자. 줄바꿈·제어 문자 불가 | DB: 공백뿐인 이름 거부(CHECK). 200자·제어 문자는 **API 입력 상한** (DB 제약 아님) |
| `due_date` (프로젝트, 선택) | `YYYY-MM-DD` 의 실제 날짜 또는 `null`(납기 미정). 빈 문자열 불가 | DB `date`, NULL 허용 (`data_contract.md` 1-3) |
| 그 밖의 필드 | 400 `unknown_fields` — `stage`·`state`·`created_by`·`customer_id` 도 여기에 해당 | 단계·상태는 항상 `proposal`/`active` 로 시작(0002), 작성자는 로그인 사용자, 고객사는 URL |

- 프로젝트는 **URL 의 고객사 아래에만** 만든다. 서버가 같은 트랜잭션에서 고객사 행을 공유 잠금하고 존재·보관 여부를 확인한다. 없으면 404 `customer_not_found`, 보관됐으면 400 `customer_archived`. 실패하면 아무 행도 남지 않는다.
- 고객사명 중복은 DB 가 막지 않는다 (규칙 **미정**). 화면은 같은 이름이 있으면 만들기 전에 확인을 묻는다.

### 5-2. 예시

```http
POST /api/customers
X-CSRF-Token: Qm9…
Content-Type: application/json

{"name": "A사"}
→ 201 {"ok": true, "customer": {"id": 7, "name": "A사", "archived": false,
                                "created_by": {"id": 3, "name": "홍길동"}, "created_at": "2026-10-20T06:10:02.511+00:00"}}

POST /api/customers/7/projects
{"name": "비타민 세럼", "due_date": "2026-12-31"}
→ 201 {"ok": true, "project": {"id": 12, "customer": {"id": 7, "name": "A사"}, "name": "비타민 세럼",
                               "stage": "proposal", "state": "active", "due_date": "2026-12-31", "archived": false,
                               "created_by": {"id": 3, "name": "홍길동"}, "created_at": "…"}}

GET /api/customers?q=A&limit=2        → 200 {"ok": true, "limit": 2, "next_after": 9, "items": [{…고객사…}, …]}
GET /api/customers/7/projects         → 200 {"ok": true, "limit": 20, "next_before": null, "items": [{…프로젝트…}]}
GET /api/projects/12                  → 200 {"ok": true, "project": {…}}

POST /api/customers/999999/projects {"name": "x"}                 → 404 customer_not_found
POST /api/customers/7/projects {"name": "x", "stage": "order"}   → 400 unknown_fields
POST /api/customers/7/projects {"name": "x", "due_date": "2026-02-30"} → 400 invalid_parameter (field: due_date)
```

| 상태 | `error.code` |
|---|---|
| 400 | `invalid_parameter`(+`field`), `missing_fields`, `unknown_fields`, `invalid_json`, `json_required`, `customer_archived` |
| 401 / 403 | `unauthorized` / `csrf_failed` |
| 404 | `customer_not_found`, `project_not_found` |
| 503 | `db_unavailable` |

### 5-3. 화면 클라이언트와 개발요청서 프로젝트 선택

- 공통 클라이언트 `Common.api(method, url, body)` (`src/common/common.js`, 모든 페이지에서 사용 가능): 변경 요청에 CSRF 헤더를 자동으로 붙이고, 403 `csrf_failed` 면 새 토큰으로 한 번 다시 보낸다. 결과는 `{ok, status, data, error}` (네트워크 오류도 `ok: false`).
- 개발요청서 상단 **연결 프로젝트** 카드: 고객사 검색·선택 → 그 고객사의 프로젝트 선택. 없으면 새 고객사·새 프로젝트를 만든다. 선택한 `고객사 › 프로젝트` 와 단계·상태·납기를 표시한다.
- **작성 중 프로젝트 변경 규칙** (`requisition.js`)
  1. 요청서를 시작할 때(직접 작성·파일 변환) 그때 선택된 프로젝트가 그 요청서의 **연결 프로젝트**가 된다. 문서 정보 패널에 표시한다.
  2. 연결된 요청서가 있는데 다른 프로젝트·고객사를 고르거나 새 프로젝트를 만들면 **먼저 확인**을 묻는다. 취소 → 선택을 되돌리고 내용 유지(새 프로젝트도 만들지 않음). 확인 → 작성 중 요청서·원본 파일·진행 중 변환을 **초기화**한 뒤 바꾼다.
  3. 프로젝트 없이 작성 중이면, 프로젝트를 고를 때 “이 프로젝트에 연결할까요?” 확인 후 내용을 유지한 채 연결한다.
  4. 선택은 브라우저 탭 단위(`sessionStorage`)로 기억한다. 새로 고침하면 서버에서 다시 확인하고, 없어졌거나 보관됐으면 선택을 해제한다. 요청서 내용은 지금처럼 페이지 메모리에만 있다.
- 저장·불러오기·최종본 버튼과 FIX 필드는 아직 연결하지 않았다. 저장을 연결할 때는 화면의 현재 선택이 아니라 **요청서의 연결 프로젝트**로 저장 API 를 호출한다.

---

## 6. 임시저장 API — **설계 단계·미구현**

> 서버 코드·테이블(`tab_drafts`)·화면 모두 없다. 아래 경로는 아직 등록되어 있지 않다.
> 테이블·저장 규칙: [DB 규칙](db_rules.md) 2-6·3-7 / 데이터 구조: [데이터 계약](data_contract.md) 8장 / 화면: [공통 UI 규격](ui_components.md) 20장.
> 표기: **확정(개발기준)** = 채택한 설계 / **제안** = 구현 전 확인 / **추가 결정 필요** = 정하지 않으면 구현할 수 없는 항목 / **구현 설계에서 검토** = 기술 세부, 구현 PR 에서 정하고 검토 / **이번 범위에서 제외** = 이번 설계에 넣지 않음.

### 6-1. 공통 규칙 — 확정(개발기준)

- **소유자는 서버 로그인 세션 사용자**다 (`auth.current_user()["id"]`). 서버가 세션으로 사용자를 식별하고 소유권을 검사하며, 클라이언트가 보낸 사용자 id 는 믿지 않는다. 주소·본문에 사용자 id 를 두지 않고, 본문에 `user_id`·`created_by` 등이 오면 400 `unknown_fields`. 서버는 항상 "세션 사용자 + 프로젝트 + 탭" 조건으로 찾으므로 **다른 사람의 임시저장은 웹사이트·API 로 조회·수정·삭제할 수 없다.** 서로 다른 사용자의 임시저장은 별개다. 보호 범위는 웹·API 이며, DB 직접 접속에서의 차단(RLS 등)은 이번 범위에서 제외했다 ([DB 규칙](db_rules.md) 3-7·8-9).
- 인증(401)·CSRF(403, `X-CSRF-Token`)·JSON 필수(400 `json_required`)·응답 형식·오류에 내부 정보 없음 — 1장 그대로. 지금 `versions_api` 의 공통 검사는 POST·PUT·PATCH·DELETE 모두에 CSRF·JSON 을 요구한다. 화면은 `Common.api()` 로 보낸다 (DELETE 도 빈 JSON `{}` 본문을 자동으로 붙임).
- 크기·파일 본문: 정식 저장과 **같은 상한**(4장 `VERSION_PAYLOAD_MAX_BYTES`)과 3장 파일 본문 규칙을 적용한다. 임시저장 전용 크기 환경변수는 두지 않는다. 넘으면 잘라 저장하지 않고 413.
- 검사 기준: 필수값은 검사하지 않고, 구조·자료형·크기는 임시저장용 기준으로 검사한다 ([데이터 계약](data_contract.md) 8-3).
- **보관된 프로젝트**: 보관 상태만을 이유로 조회·저장·갱신·삭제를 거부하지 않는다 (`project_archived` 는 임시저장 API 에서 쓰지 않음). 정식 저장(2-1)의 `project_archived` 거부는 그대로다.
- 임시저장은 2장 목록·불러오기·최종본 API 에 나오지 않는다. 버전 번호가 없다 (`revision` 은 충돌 방지용, 6-4).
- 자동 만료·정기 삭제 없음. 지워지는 경우는 정식 저장 연동(6-5)과 사용자 삭제(DELETE)뿐이다.

### 6-2. 경로 (안)

| 메서드 | 경로 | 설명 | 상태 |
|---|---|---|---|
| GET | `/api/projects/<project_id>/tabs/<tab>/draft` | 내 임시저장 조회. 없으면 `"draft": null` (200) | 제안 |
| PUT | `/api/projects/<project_id>/tabs/<tab>/draft` | 내 임시저장 저장 — 없으면 만들고 있으면 갱신 | 제안 |
| DELETE | `/api/projects/<project_id>/tabs/<tab>/draft` | 내 임시저장 삭제 (사용자가 확인한 뒤에만 화면이 호출). 서버의 임시저장만 지우며 화면 입력은 화면이 그대로 둔다 ([공통 UI 규격](ui_components.md) 20-4). 없어도 200 (`deleted: false`) | 제안 |

- 세 기능(조회·저장/갱신·삭제)은 확정(개발기준)이고, **경로·메서드·응답 모양은 제안**이다. 기존 저장 API 와 같은 `/api/projects/<id>/tabs/<tab>/…` 아래에 두고, 사용자는 경로에 넣지 않는다 (세션으로 정함).
- 없는 프로젝트 404 `project_not_found`, 잘못된 탭 400 `invalid_tab`. 보관된 프로젝트도 세 기능 모두 허용한다 (확정(개발기준), 6-1).

### 6-3. 예시 (안)

```http
PUT /api/projects/12/tabs/requisition/draft
X-CSRF-Token: Qm9…
Content-Type: application/json

{
  "schema_version": 1,
  "payload": {"context": {"customer_id": 7, "project_id": 12, …}, "inputs": {…필수값이 비어 있어도 됨…}, "outputs": {}, "meta": {…}},
  "expected_revision": 3
}
```

```json
200
{
  "ok": true,
  "draft": {"project_id": 12, "tab": "requisition", "schema_version": 1, "revision": 4,
            "updated_at": "2026-11-05T06:10:02.511+00:00", "payload_bytes": 2094},
  "validation": {"level": "draft", "fully_validated": false, "removed_fields": [], "note": "임시저장 기준 — 필수값 검사 안 함"}
}
```

- 예시의 필드 이름·값(`expected_revision`, `level: "draft"` 등)은 **제안**이다. 기준 번호를 보내고 서버 번호와 비교한다는 동작만 확정이다 (6-4).
- GET 응답의 `draft` 에는 위 항목 + `payload` 가 들어간다. 소유자는 항상 본인이므로 응답에 사용자 정보를 넣지 않아도 된다 (제안).
- 임시저장 요청·응답에는 `based_on_id` 가 없다 (이번 범위에서 제외, [DB 규칙](db_rules.md) 2-6). 정식 저장(2-1)의 `based_on_id` 는 그대로다.

### 6-4. 여러 창에서 동시에 수정 — 확정(개발기준)

같은 사람이 두 창(또는 두 기기)에서 같은 프로젝트·탭을 고치면 오래된 창의 내용이 최신 임시저장을 덮어쓸 수 있다. 이를 `revision` 으로 막는다.

**확정(개발기준)**
- 같은 사용자·프로젝트·탭의 임시저장에 저장 번호 **`revision`** 을 둔다. 정식 저장본의 `version_no` 와 다른, 충돌 방지용 번호다.
- 저장 요청에는 화면이 알고 있는 기준 번호를 담는다. **서버의 현재 번호와 다르면 갱신하지 않고 409 로 거부**한다 — 오래된 화면의 덮어쓰기 방지.
- 409 가 나도 **현재 화면의 입력은 그대로 둔다** (지우거나 서버 내용으로 바꾸지 않음).
- 서로 다른 사용자의 임시저장은 별개라 서로 충돌하지 않는다.

**제안** (확정 아님)
- 요청 필드 이름 `expected_revision`, 오류 코드 `draft_conflict`, 409 응답에 현재 `revision`·`updated_at` 을 담는다 — 최종본 변경(2-3, `expected_final_history_id`)과 같은 방식.
- 409 뒤 화면의 다음 선택지(예: 서버 내용 확인 후 덮어쓰기)는 [공통 UI 규격](ui_components.md) 20-6 에서 정한다.

**구현 설계에서 검토** (확정 아님)
- 같은 조합의 임시저장을 두 창에서 동시에 **처음 만들 때**의 충돌 처리.
- 임시저장을 **삭제한 뒤 다시 만들 때**, 삭제 전 번호를 기준으로 한 오래된 요청의 처리.
- `revision` 의 시작값·증가 방식.

### 6-5. 정식 저장과 연동 — 확정(개발기준)

**확정(개발기준)**
1. 정식 저장 요청(2-1)에 연결할 임시저장 번호 **`draft_revision`** 을 담을 수 있다 (선택 필드).
2. 서버는 정식 저장과 임시저장 정리를 **같은 트랜잭션**에서 처리한다. "세션 사용자 + 같은 프로젝트·탭 + 현재 `revision` = `draft_revision`" 일 때만 임시저장을 지운다.
3. 번호가 다르면 정식 저장 요청 뒤에 더 최신 임시저장이 생긴 것이므로 **지우지 않는다.** 정식 저장은 그대로 성공한다.
4. 정식 저장이 실패하면(400·409·413·503 등) 트랜잭션 전체가 취소되어 임시저장은 **남는다.**
5. `draft_revision` 이 없는 요청으로는 임시저장을 **지우지 않는다** (무조건 삭제 금지).
6. 정식 저장의 기존 동작(새 버전 추가·번호·검증·`based_on_id`·`project_archived` 거부)은 바꾸지 않는다.

**제안** (확정 아님)
- 응답에 정리 결과를 담는다: `"draft": {"deleted": true}` / `{"deleted": false, "reason": "changed"}` / `{"deleted": false, "reason": "none"}`. 화면은 `changed` 면 "정식 저장 뒤에 바뀐 임시저장이 남아 있어요" 로 안내한다.

- `draft_revision` 을 추가하면 2-1 의 허용 필드 목록이 바뀐다 (지금은 받지 않는 필드라 400 `unknown_fields`). 구현 PR 에서 2-1 을 함께 고친다.

### 6-6. 오류 (안)

| 상태 | `error.code` |
|---|---|
| 400 | `invalid_tab`, `unknown_fields`, `invalid_json`, `json_required`, `invalid_payload`, `unsupported_schema_version`, `file_content_not_allowed`, `context_project_mismatch`, `context_customer_mismatch` — 기존 코드 재사용. 필수값(`required_field`)·보관 프로젝트(`project_archived`)는 임시저장에서 나오지 않는다 |
| 401 / 403 | `unauthorized` / `csrf_failed` |
| 404 | `project_not_found` (임시저장이 없는 것은 오류가 아님 — GET 은 `null`, DELETE 는 `deleted: false`) |
| 409 | 기준 `revision` 불일치 (6-4, 확정). 코드 이름 `draft_conflict` 는 제안 |
| 413 | `payload_too_large`, `request_too_large` |
| 503 | `db_unavailable` |

### 6-7. 자동저장 — 후속 검토

- 첫 구현은 **수동 임시저장 버튼**만 둔다. 자동저장은 하지 않는다.
- 자동저장은 후속 검토 항목이다. "변경 시 30초 간격" 은 **검토안**이며 확정한 동작이 아니다. 도입하면 요청 빈도·6-4 충돌 처리·화면 표시를 함께 정한다.
