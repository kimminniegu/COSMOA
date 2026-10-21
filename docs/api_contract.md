# COSMOA 공통 저장 API 계약 (공통 개발 문서)

> **상태: 2단계 구현됨** — 서버 API·DB(`0003_versioning`, test·dev 적용). **화면(저장 버튼·개발요청서 연결)은 아직 연결하지 않았다** (3단계).
> **3-1단계 구현됨** — 고객사·프로젝트 생성·조회 API 와 개발요청서의 프로젝트 선택 화면 ([5장](#5-고객사프로젝트-생성조회-api--3-1단계-구현됨)).
> 코드: `src/common/versions_api.py`(경로) → `versions.py`(업무 규칙) → `versions_repo.py`(SQL), payload 검증 `payloads.py`.
> 규칙 근거: [DB 규칙](db_rules.md) 3·4·5장, [데이터 계약](data_contract.md) 2·3·5·6장.

---

## 1. 공통

### 1-1. 인증·사용자 범위

- 세션 쿠키 로그인(`/login`) 후 사용한다. 로그인하지 않으면 **401** (JSON).
- 로그인한 팀 사용자 전체가 모든 프로젝트·저장본을 조회·저장한다 (개발용 기본 정책, `db_rules.md` 3-5). 운영 권한 체계는 별도 확정 항목.
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
