# COSMOA 데이터 계약 (공통 DB 문서)

> **상태: 1장(고객사·프로젝트·이력)·`users`(0001·0002)와 2장 `tab_versions`·6장 `version_links`(저장본 출처, 0003)는 구현됨 (test·dev 적용). 4장 개발요청서 저장 계약 v1(FIX 반영)은 서버 검증·화면 payload 까지 구현됨 (3-2, 저장 버튼 연결 전). 다른 탭 payload 는 네 칸 구조·파일 제외·크기만 검증 ([API 계약](api_contract.md) 3장).**
> 저장·최종본·동시 작업 규칙은 [DB 규칙](db_rules.md), 전체 범위와 실행 절차는 [개발 안내](development.md)를 따른다.
>
> 표기: **확정(FIX)** 10.19 수정안 명시 / **확정(개발기준)** 공통 개발기준으로 정한 구현 방식 / **기본설계** DB 최종안 / **제안** 구현 전 확인 (공통 개발·설계: 김민 PM·유정현 및 관련 담당자 협의 후 확정 / DB 적용·마이그레이션: 공통 DB 담당 유정현 확인 후 확정) / **미정** 임의 확정 금지

---

## 1. 고객사·프로젝트

### 1-0. `users` (계정) — 구현됨 (0001)

| 열 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | bigint identity | ✓ | |
| `email` | text, UNIQUE | ✓ | 소문자·앞뒤 공백 없이 저장 (CHECK) |
| `name` | text | ✓ | |
| `team` | text | ✓ (기본 `''`) | 기존 SQLite 계정과 같은 항목 |
| `password_hash` | text | ✓ | werkzeug `generate_password_hash` 결과만 (CHECK). 평문 저장 불가 |
| `created_by` | bigint → users | 최초 계정만 NULL | NULL = 시스템 작업(최초 계정). NULL 인 행은 하나만 허용 |
| `created_at`, `updated_at` | timestamptz | ✓ | |

- `home_widgets` 는 7단계에서 추가한다.

### 1-1. `customers` (고객사)

| 열 | 타입 (안) | 필수 | 근거 | 설명 |
|---|---|---|---|---|
| `id` | bigint identity | ✓ | 기본설계 | |
| `name` | text | ✓ | 기본설계 | 고객사명 |
| `timezone` | text (IANA, 예: `Europe/Paris`) | 미정 | 제안 (기본설계 + FIX 바이어 현지시각 위젯) | 바이어 현지시각 표시용 |
| `created_by`, `created_at`, `updated_at` | | ✓ | 기본설계 | 작성자는 서버 로그인 사용자 |
| `archived_at` | timestamptz | | 확정(개발기준), 0001 구현 | 보관 시각. NULL = 사용 중. 행 삭제는 DB 가 거부 |
| 국가 등 그 외 | | | **미정** | |

- 0001 구현 열: `id`, `name`, `archived_at`, `created_by`, `created_at`, `updated_at`. `timezone` 은 제안 상태라 넣지 않았다.
- 생성·조회 API (3-1): `name` 만 받는다(1~200자, 제어 문자 불가 — API 입력 상한). 이름 중복은 DB 가 막지 않는다(**미정**). [API 계약](api_contract.md) 5장.

### 1-2. `customer_contacts` (고객사 담당자)

| 열 | 필수 | 근거 | 설명 |
|---|---|---|---|
| `customer_id` | ✓ | 기본설계 | FK → customers |
| `name` | ✓ (제안) | 기본설계 | 담당자 이름 |
| 연락처·직함 등 | | **미정** | |

- 0001 구현 열: `id`, `customer_id`, `name`, `created_by`, `created_at`, `updated_at`.

### 1-3. `projects` (프로젝트 = 단일 제품)

| 열 | 타입 (안) | 필수 | 근거 | 설명 |
|---|---|---|---|---|
| `id` | bigint identity | ✓ | 기본설계 | |
| `customer_id` | bigint | ✓ | 기본설계 | FK → customers, `ON DELETE RESTRICT` |
| `name` | text | ✓ | 확정(FIX) 단일 제품 기준 | 프로젝트(제품)명 |
| `stage` | text + CHECK | ✓ | 확정(FIX) 값 목록 | 단계 (아래 코드) |
| `state` | text + CHECK | ✓ | 확정(FIX) 값 목록 | 상태 (아래 코드) |
| `due_date` | date | NULL 허용 (확정(개발기준)) | 확정(FIX) 납기일이 일정의 핵심 | 납기일, D-day 계산 기준. 미정이면 NULL |
| `archived_at` | timestamptz | | 확정(개발기준) | 보관 시각. NULL = 사용 중. 행 삭제는 DB 가 거부 |
| `created_by`, `created_at`, `updated_at` | | ✓ | 기본설계 | |
| 그 외 (제품 유형, 담당자 등) | | | **미정** | |

단계·상태 값 — 의미는 **확정(FIX)**, 저장 코드는 **확정(개발기준)** — 0001 의 CHECK 에 적용됨

| 구분 | 화면 표시 | 저장 코드 |
|---|---|---|
| `stage` | 제안 → 개발 → 발주 → 생산 → 선적 → 완료 | `proposal`, `development`, `order`, `production`, `shipping`, `completed` |
| `state` | 진행 / 홀드 / 드롭 | `active`, `hold`, `drop` |

- 새 프로젝트는 `stage=proposal`, `state=active` 로만 생성한다 (0002, DB 가 다른 값 거부). 납기일은 생성 시 입력할 수 있다.
- 생성·조회 API (3-1): `POST /api/customers/<id>/projects` 에 `name`(필수)·`due_date`(선택)만 받는다. 고객사는 URL 로 정하고 서버가 존재·보관 여부를 확인한다. [API 계약](api_contract.md) 5장.
- 홀드는 다시 진행할 수 있다. (확정(FIX))

### 1-4. `project_history` (단계·상태·납기일 변경 이력, 추가만)

| 열 | 필수 | 근거 |
|---|---|---|
| `project_id` | ✓ | 기본설계 |
| `field` (`stage` / `state` / `due_date`) | ✓ | 기본설계 |
| `old_value`, `new_value` | **NULL 허용** | 기본설계 + 확정(개발기준) — 납기일 최초 지정(`old_value` NULL)·해제(`new_value` NULL) 등 |
| `reason` | 홀드·드롭으로 바꿀 때 **필수** | 확정(FIX) 사유 기록 |
| `created_by`, `created_at` | ✓ | 기본설계 |

- `projects` 수정과 `project_history` 추가는 **같은 트랜잭션**에서 한다. 하나라도 실패하면 둘 다 취소한다. — 확정(개발기준). 0001 에서 DB 가 커밋 시 확인한다 (`db_rules.md` 2-4).
- 값 저장 형식: `stage`·`state` 는 저장 코드, `due_date` 는 `YYYY-MM-DD` 문자열. `reason` 은 `state` 를 `hold`/`drop` 으로 바꿀 때 필수(공백 불가), 그 외에는 선택.
- 구현 열: `id`, `project_id`, `field`, `old_value`, `new_value`, `reason`, `created_by`, `created_at`(표시용 시각), `xact_id`(0002, 기록한 트랜잭션 id — 서버가 채움, 0002 이전 행은 NULL). UPDATE·DELETE 는 DB 가 거부한다.

### 1-5. `regulatory_notes` (프로젝트별 규제 확인사항 메모, 수정 가능) — 확정(개발기준)

규제 탭 저장본과 별개로 수정할 수 있는 프로젝트별 메모다. 규제 탭 저장본 없이 개발요청서에 바로 반영할 수 있다. (`db_rules.md` 5-1) 4단계에서 만든다.

| 열 | 필수 | 근거 | 설명 |
|---|---|---|---|
| `id` | ✓ | 기본설계 | |
| `project_id` | ✓ | 확정(FIX) 연결 프로젝트 | FK → projects. UNIQUE (`id`, `project_id`) — `version_links` 가 같은 프로젝트 조건으로 참조 |
| `ingredient_name` | | 확정(FIX) | 선택한 성분명. 메모만 있으면 NULL |
| `country` | | 확정(FIX) | 대상 국가 (ISO 2글자) |
| `regulation_text` | | 확정(FIX) | 선택한 규제 내용 (조회 결과에서 복사) |
| `lookup_source`, `looked_up_at` | | 확정(FIX) | 조회 출처·조회일 |
| `memo` | | 확정(FIX) | 담당자 메모 (조회 결과와 구분) |
| `created_by`, `created_at`, `updated_at` | ✓ | 확정(FIX) 작성자·작성일 | |
| 관련 개발요청서·샘플 수정 요청 연결 | | 확정(FIX) "필요하면" | 방식 **미정** |

- 열 이름은 **제안**. 조회 결과 없이 메모만 있는 행을 허용한다. (확정(FIX)) 조회 결과도 메모도 없는 행은 막는다. (CHECK, 제안)
- 메모를 수정해도 이미 저장된 요청서와 `version_links` 반영 기록은 바뀌지 않는다.
- 반영 출처로 참조된 메모는 삭제할 수 없다 (`ON DELETE RESTRICT`). 그 외 삭제 허용 여부는 **미정**.

---

## 2. `tab_versions` (탭 저장본, 추가만)

| 열 | 타입 (안) | 필수 | 설명 |
|---|---|---|---|
| `id` | bigint identity | ✓ | |
| `project_id` | bigint | ✓ | FK → projects |
| `tab` | text + CHECK | ✓ | `regulatory` / `margin` / `simulation` / `requisition` |
| `version_no` | integer | ✓ | **서버가 부여**. UNIQUE (`project_id`, `tab`, `version_no`) |
| `based_on_id` | bigint | | 같은 프로젝트·탭에서 편집을 시작한 저장본. 새로 작성하면 NULL |
| `schema_version` | integer | ✓ | payload 구조 버전 (`db/schemas/<탭>.v<번호>.json`) |
| `title` | text | 제안 | 저장본 이름. FIX "개발요청서 이름(파일명) 부여" 근거. 다른 탭 사용 여부 **미정** |
| `payload` | jsonb | ✓ | 3장 구조. 파일 본문 제외 |
| `created_by`, `created_at` | | ✓ | 서버 로그인 사용자, 저장 시각 |

제약 — 확정(개발기준)
- UNIQUE (`project_id`, `tab`, `version_no`)
- UNIQUE (`id`, `project_id`, `tab`)
- FK (`based_on_id`, `project_id`, `tab`) → `tab_versions(id, project_id, tab)` — 다른 프로젝트·다른 탭 저장본을 기준으로 삼을 수 없다.
- `UPDATE`·`DELETE`·`TRUNCATE` 는 트리거로 거부. (0003 구현)
- 0003 구현 열: 위 표 + `xact_id`(저장 트랜잭션 id, 서버 기록 — 반영 출처의 같은 트랜잭션 확인용). `title` 은 모든 탭에서 선택 입력(1~200자).
- `is_final` 열 없음. 현재 최종본은 `final_history` 마지막 기록으로 판단 (`db_rules.md` 4장).

---

## 3. payload 구조 — 기본설계 + 확정(개발기준)

모든 탭 payload 는 네 칸으로 나눈다. `schema_version` 은 payload 안이 아니라 `tab_versions` 열에 둔다.

| 칸 | 담는 것 | 예 |
|---|---|---|
| `context` | 저장 당시의 맥락 **스냅샷** (나중에 원본이 바뀌어도 그대로) | 고객사명·프로젝트명 사본, 작성 방식, 언어, 원본 파일명 |
| `inputs` | 사용자가 입력·확인한 값 | 개발요청서 필드, 마진 입력 조건, 규제 선택 항목·메모, 모델링 배합 조절 |
| `outputs` | 계산·판정·생성 결과 | 마진 계산 결과, 모델링 예측 점도·질감·용기 적합성 |
| `meta` | 출처·검토 정보 등 부가 정보 | 필드별 출처(`field_provenance`), 참고자료 메타데이터, 화면 구조 버전 |

- payload 에는 값을 **복사**해서 넣는다. 다른 테이블 id 만 넣고 표시할 때 다시 읽는 방식으로 저장 내용을 대신하지 않는다.
- 탭별 세부 필드는 탭 담당자와 `db/schemas/` 파일로 합의한다. 개발요청서 외 3개 탭은 아래 FIX 기록 항목만 확정이며 필드 이름·구조는 **미정**.

| 탭 | FIX 에 명시된 기록 항목 (확정(FIX)) |
|---|---|
| `regulatory` | 선택한 성분명, 대상 국가, 선택한 규제 내용, 조회 출처 및 조회일, 담당자 메모 (메모만 있는 항목 허용), 작성자·작성일, 필요 시 관련 요청서·샘플 수정 요청 연결. 조회 결과 전체는 저장하지 않음. → 이 항목들은 `regulatory_notes`(1-5)에 기록한다. 규제 탭 저장본 payload 의 구조·용도는 **미정** (4단계 합의) |
| `margin` | 탭 내 모든 요소 저장, 원료 등급 대체(사양 변경) 선택 여부 |
| `simulation` | 개발요청서 번호(제목), 예측 점도, 배합 조절 항목과 수치, 총 배합 비율, 예상 질감, 상대 유동성, 용기 적합성(대체 권장 용기 포함), 컨셉원료 코멘트, 바이어 제안 가이드(R&D 연구소 리포트, 바이어 세일즈 피칭) |
| `requisition` | 4장 |

---

## 4. 개발요청서 저장 구조

### 4-1. 스키마 버전 계획 — 확정(개발기준)

- 개발요청서 저장은 3단계에서 처음 연결한다. 그 전에는 개발요청서 저장본이 없다.
- FIX 필드 변경을 3단계에 포함하므로 **FIX 를 반영한 구조를 첫 저장 형식 `schema_version = 1`** 로 정한다. — **구현됨 (3-2)**: 검증 `src/05_requisition/contract.py`, 예시 `db/schemas/requisition.v1.example.json`. (별도 JSON Schema 파일은 만들지 않았다. 서버 검증 코드가 기준)
- 현재 `schema.py`·`requisition.js` 의 문서 구조는 저장 형식 버전이 아니다. 따라서 **v1→v2 변환 코드를 미리 만들지 않는다.** 기존 화면 형식에서 넘어오는 값은 4-4 에 따라 처리한다.
- v1 저장본이 개발·운영 DB 에 생긴 뒤 구조를 바꿀 때 v2 와 변환 코드를 만든다. (`db_rules.md` 7-1)
- 첫 구현은 프로젝트·탭별 하나의 버전 흐름이다. 여러 문서를 따로 묶는 기능은 만들지 않는다. (`development.md` 2장)

### 4-2. 저장 JSON 예시 (`schema_version = 1`) — 구현됨 (3-2)

아래 예시는 `db/schemas/requisition.v1.example.json` 과 **같은 내용**이고, 서버 검증(`src/05_requisition/contract.py`)을 통과한다 (`fully_validated: true`). 세 가지가 같은지는 테스트(`src/05_requisition/tests/test_contract.py`)가 확인한다.

```json
{
  "context": {
    "customer_id": 7,
    "customer_name": "A사",
    "project_id": 12,
    "project_name": "비타민 세럼",
    "creation_method": "auto_edited",
    "source_language": "en",
    "target_language": "ko",
    "source_file_name": "buyer_brief.pdf"
  },
  "inputs": {
    "request_source": "고객사 요청",
    "product_name": "Vitamin C Serum",
    "sample_request_type": "신규 샘플",
    "product_type": "스킨케어",
    "target_prices": [
      {
        "amount": 1300,
        "currency": "KRW"
      },
      {
        "amount": 1500,
        "currency": "KRW"
      },
      {
        "amount": 1800,
        "currency": "KRW"
      }
    ],
    "export_countries": [
      "미국",
      "프랑스"
    ],
    "company_description": "",
    "basic_notes": "",
    "benchmark_product_name": "",
    "product_development": {
      "application_type": "Leave-on",
      "product_description": "",
      "formula_guidelines": "",
      "texture": "가벼운 젤 텍스처",
      "appearance_sensory": "",
      "viscosity": "흐르지 않는 젤 정도",
      "spf": "SPF50+",
      "pa": "PA++++",
      "container_reference": "에어리스 펌프 30mL (참고)",
      "fragrance_flavor": "",
      "finish": "",
      "coverage": "",
      "color_shade_reference": "",
      "other_requirements": "",
      "viscosity_level": ""
    },
    "buyer_prohibited_ingredients": [
      "Parabens"
    ],
    "ingredients": {
      "concept": [
        {
          "name": "Ascorbic Acid",
          "kind": "necessary",
          "must_contain": true,
          "efficacy_tags": [
            "미백"
          ]
        },
        {
          "name": "Niacinamide",
          "kind": "ideal",
          "must_contain": null,
          "efficacy_tags": [
            "미백",
            "보습"
          ]
        }
      ],
      "other_notes": ""
    },
    "rnd_check_requests": "할랄 인증 필요 여부 확인",
    "quality": {
      "tests": [
        "안정도 시험"
      ],
      "additional_notes": ""
    },
    "product_type_custom": "",
    "product_type_detail": "세럼",
    "regulatory_restricted_ingredients": [],
    "reference_notes": ""
  },
  "outputs": {},
  "meta": {
    "field_provenance": [
      {
        "field_key": "product_development.texture",
        "source_value": "light gel texture",
        "source_page": "2",
        "input_source": "auto",
        "review_status": "confirmed",
        "user_value": null
      },
      {
        "field_key": "target_prices",
        "source_value": "mid-tier",
        "source_page": "1",
        "input_source": "user_edited",
        "review_status": "user_edited",
        "user_value": [
          {
            "amount": 1300,
            "currency": "KRW"
          },
          {
            "amount": 1500,
            "currency": "KRW"
          },
          {
            "amount": 1800,
            "currency": "KRW"
          }
        ]
      }
    ],
    "reference_files": [
      {
        "name": "benchmark.png",
        "size": 183204,
        "type": "image/png"
      }
    ],
    "legacy_fields": {
      "target_price_tier": "mid"
    }
  }
}
```

- 버전 번호는 payload 에 넣지 않는다. `tab_versions.version_no` 가 기준이다.
- 고객사·프로젝트는 **id 로 연결**한다 (`context.customer_id`·`project_id`). `customer_name`·`project_name` 은 저장 당시 이름의 사본이며, 저장할 때 서버가 DB 의 현재 이름으로 덮어쓴다. 화면의 고객사 칸도 연결 프로젝트의 고객사를 표시만 한다 (입력칸 아님). 원문(바이어 파일)에 적힌 고객사명은 `field_provenance` 의 `customer` 출처에만 남는다.
- `outputs` 는 v1 에서 빈 객체다. 검토 상태(확인 필요 개수 등)는 화면에서 다시 계산한다.
- `meta.legacy_fields` 는 선택 키다 (4-4).

### 4-3. 필드 매핑 — FIX 반영 (v1 구현)

기존 `schema.py` 의 키·화면 위치를 그대로 두고 FIX 칸만 더했다. 바뀐 키는 두 가지다: `target_price_tier` → `target_prices`, `ingredients.necessary`·`ideal` → `ingredients.concept` (이전 값 처리는 4-4).

| FIX 요구 (확정(FIX)) | 화면 위치 | v1 키 | 형식·허용값 | 상태 |
|---|---|---|---|---|
| 목표 가격대 복수 (예: 1,300·1,500·1,800원) | 01 기본정보 · 목표 가격대 (줄 추가) | `target_prices` | `[{ "amount": 0보다 큰 숫자, "currency": ISO 4217 대문자 3글자 }]`, 최대 10개, 같은 금액·통화 중복 불가. 화면 통화 선택: KRW·USD·EUR·JPY·CNY | 확정(개발기준) |
| SPF/PA 칸 | 02 제품 개발 요구사항 · SPF, PA | `product_development.spf`, `product_development.pa` | 문자열 50자 이하, 원문 표기 그대로 (예: `SPF50+`, `PA++++`) | 칸 확정. 선택형(드롭다운)으로 할지는 **미정** |
| 컨셉 원료 필수/선호 분리 + 함유 필수 여부·효능 태그 | 03 원료 요구사항 · 컨셉 원료 (필수 원료 / 선호 원료 묶음) | `ingredients.concept[]`: `name`, `kind`(`necessary`/`ideal`), `must_contain`(`true`/`false`/`null`=미확인), `efficacy_tags`(문자열 목록) | 최대 50개, 원료명 중복 불가(필수·선호 통틀어, 대소문자 무시). 태그 10개·각 50자 이하, 자유 입력 | 구조 확정. 효능 태그 목록은 **미정** |
| R&D 확인 요청사항 | 03 원료 요구사항 · 마지막 칸 | `rnd_check_requests` | 텍스트 | 칸 확정. 위치는 개발기준(규제 확인사항 반영 대상, 6단계) |
| 용기 칸 (모델링 용기 적합성 참고값) | 02 제품 개발 요구사항 · 용기 (참고값) | `product_development.container_reference` | 텍스트 | 칸 확정. 모델링 반영은 6단계 |
| 스킨케어 세분화 (토너·스킨·세럼·앰플·크림·로션) | 01 기본정보 · 제품 유형 → 스킨케어 선택 시 세부 유형 | `product_type` = `스킨케어` + `product_type_detail` | 세부 유형은 6개 중 하나 또는 `""`. 스킨케어가 아니면 `""` 만 | 값 확정(FIX) |
| 점도: 서술형 + 드롭다운 | 02 제품 개발 요구사항 · 점도 (선택값 + 서술) | `product_development.viscosity_level` + `product_development.viscosity` | `viscosity` 텍스트. `viscosity_level` 값 목록은 **미정** → 지금은 `""` 만 허용, 화면 선택칸은 비활성 | 구조 확정, 값 **미정** |
| 이전 차수 값 누락 경고 | – | – | 차수 기능(5단계) 후 이전 차수 요청서와 비교 | 후속 |

- 값 목록은 한 곳(`src/05_requisition/schema.py`)에서 정의하고 화면·자동변환·서버 검증이 같이 쓴다. 점도 선택값이 정해지면 `VISCOSITY_LEVELS` 에 넣으면 화면 선택칸이 켜지고 서버도 그 값만 받는다.
- 자동변환(AI)이 채우는 FIX 칸: `product_type_detail`(원문에 명시된 경우), `spf`·`pa`(원문 표기 그대로), 컨셉 원료 이름·필수/선호 구분. **채우지 않는 칸**: 목표 가격대 금액, 점도 선택값, 용기, R&D 확인 요청사항, 함유 필수 여부, 효능 태그. 근거(원문 발췌)가 없는 추출값은 비운다 (기존 규칙).

### 4-4. 이전 형식 호환 — 구현됨 (3-2)

- `target_price_tier` (`low`/`mid`/`high`) 는 v1 필드가 아니다. 자동변환이 원문에서 이 표기를 근거와 함께 찾은 경우에만 화면에 "원문 가격대 표기: 중가 — 금액으로 자동 변환하지 않았어요. 목표 가격대를 직접 입력해 주세요." 로 안내하고 `target_prices` 는 **비워 둔다** (확인 필요로 표시). **금액으로 바꾸지 않는다.**
- 그 원래 값은 저장할 때 `meta.legacy_fields.target_price_tier` 에 그대로 남긴다 (선택 키, `low`/`mid`/`high` 만).
- 기존 `ingredients.necessary`/`ideal` 목록(자동변환 추출 형식)은 `kind` 만 채워 `ingredients.concept` 로 옮기고, `must_contain` 은 `null`(미확인), `efficacy_tags` 는 `[]` 로 둔다. 같은 원료가 양쪽에 있으면 필수 쪽 하나만 남긴다.
- 바이어 파일의 Target Cost 등 금액은 지금처럼 원문 보존 데이터(`raw_extracted_data`)에만 두고, 저장 payload 에는 넣지 않는다.
- **기존 저장본은 추정해 삭제·변환하지 않는다.** dev 에는 개발요청서 저장 화면이 없었으므로 정식 저장본이 없을 것으로 보지만 조회로 확인하지는 않았다. test DB 에는 2단계 테스트가 이전 검사 수준(목표 가격대만 검사)으로 저장한 requisition 저장본이 같은 `schema_version = 1` 로 남아 있다 (확인 결과 42개 중 18개가 현재 계약 검사에 실패) — 그대로 둔다. 실패 원인·출처를 단정하지 않고 **"현재 계약과 호환되지 않는 저장본"** 으로 부르며, 번호는 바꾸지 않고 읽을 때 계약을 다시 검사해 구분하는 해결안: [개발 안내](development.md) 8-1 (읽기 호환 처리는 후속).

### 4-5. 서버 검증 기준 (v1) — 구현됨 (3-2)

| 항목 | 기준 |
|---|---|
| 처리 순서 | ① 저장 제외 필드 제거(5장, `removed_fields` 로 알림) ② 그 밖 위치의 파일 본문 거부 ③ 계약 검사(아래) ④ 크기 상한 ⑤ 저장 시 연결 프로젝트·고객사 id 대조 |
| 키 | `context` 8개(`customer_id`, `customer_name`, `project_id`, `project_name`, `creation_method`, `source_language`, `target_language`, `source_file_name`), `inputs` 는 4-2 예시의 모든 키, `outputs` 는 `{}`, `meta` 는 `field_provenance`·`reference_files`(+ 선택 `legacy_fields`). **빠진 키는 400 `missing_field`, 계약에 없는 키는 400 `unknown_field`** (저장 제외 필드는 거부하지 않고 제거) |
| 빈 값 | 텍스트·선택값 `""`, 목록 `[]`. `null` 은 `ingredients.concept[].must_contain`(미확인)과 `field_provenance[].user_value` 만 |
| 자료형·길이 | 텍스트 10,000자 이하 (SPF·PA 50자). 목록 항목은 문자열 300자 이하, 최대 50개, 빈 항목·중복(대소문자·앞뒤 공백 무시) 불가 → 400 `duplicate_value`. 문자열 앞뒤 공백은 그대로 저장(화면이 정리) |
| 허용값 | `request_source`, `sample_request_type`, `product_type`, `product_type_detail`(스킨케어일 때만), `product_type_custom`(기타일 때만), `product_development.application_type`, `viscosity_level`(현재 `""` 만), `concept.kind`, `context.creation_method`(`auto`·`auto_edited`·`manual`·`manual_edited`), `context.target_language`, 출처의 `input_source`(`auto`·`user_edited`)·`review_status`(5개). 위반 400 `invalid_value` |
| 필수값 | `request_source`, `product_name`, `sample_request_type`, `product_type`(기타면 `product_type_custom` 도), `export_countries` 1개 이상, `quality.tests` 1개 이상, `context.customer_id`·`project_id`. 비면 400 `required_field`. 화면 "작성 완료" 필수 항목과 같다 |
| 고객사·프로젝트 | id 로 식별. 저장 시 `context.project_id` 가 URL 프로젝트와 다르면 400 `context_project_mismatch`, `customer_id` 가 그 프로젝트의 고객사와 다르면 400 `context_customer_mismatch`. 이름 사본은 서버가 DB 값으로 덮어쓴다 |
| 출처 (`field_provenance`) | `field_key` 는 `inputs` 의 칸 경로 또는 `customer`. 허용 키 6개 밖(`translated_value` 등)은 제거 |
| 검증 수준 | 통과하면 `validation.level = "full"`, `fully_validated = true`. 다른 탭은 기존대로 `structure` / `false` |

- 화면 payload 는 `src/05_requisition/requisition_payload.js` 가 화면 문서에서 계약 키만 골라 만든다 (요청서의 **연결 프로젝트** id 사용, 연결 프로젝트가 없으면 만들지 않음). 인쇄/PDF 는 화면 문서(참고 이미지 포함)를 그대로 쓴다.
- 임시 저장(필수값이 비어 있는 저장)은 v1 에서 받지 않는다. 필요하면 정책을 정한 뒤 계약을 바꾼다 (**미정**).

## 5. 저장 제외 필드 — 확정(개발기준)

| 필드 | 이유 |
|---|---|
| `reference_files[].data_url` | 파일 본문 저장 금지 |
| 파일 본문을 담은 모든 base64 값 | 파일 본문 저장 금지. 서버에서도 다시 검사·제거 |
| 원본 업로드 파일 (`originalFile`) | 파일 본문 저장 금지. 파일명만 `context.source_file_name` |
| `raw_extracted_data` | 1차 저장 대상 제외 (자동변환 원문 보존 데이터) |
| `version` (기존 클라이언트 버전) | 서버 `version_no` 가 기준. 3-2 부터 화면 문서에 두지 않음 |
| `document_id` (클라이언트 UUID) | 저장본은 서버 `tab_versions.id` 로 식별. 3-2 부터 화면 문서에 두지 않음 |
| `recipients` (예전 전달 대상) | 화면에서 쓰지 않음. 저장 계약에 없음 |
| 화면 상태 (편집 중 여부, 선택 탭 등) | 문서 내용이 아님 |
| 작성자 정보 | 서버 로그인 사용자로 `created_by` 에 기록. payload 값 사용 안 함 |
| 마진 → 요청서 반영 시 단가·마진 수치 | 확정(FIX) 반영 제외 |
| 모델링 → 요청서 반영 시 배합 조절 수치 | 확정(FIX) 반영 제외 |

- ⚠ 저장본을 다시 불러오면 **원본 파일·참고자료 본문·참고 이미지는 복원되지 않는다.** 화면에 안내한다.
- 크기 상한 초기값: payload 256 KiB, 반영 기록 32 KiB (환경변수로 변경, 근거 `api_contract.md` 4장). 넘으면 잘라 저장하지 않고 413 을 반환한다.
- 서버 처리: 위 필드는 제거하고 `removed_fields` 로 알린다. `meta.reference_files[]`·`meta.field_provenance[]` 는 허용 키만 남긴다. 그 밖의 위치에 파일 본문(data URL·긴 base64)이 있으면 400 으로 거부한다.

---

## 6. `based_on_id` 와 `version_links` — 확정(개발기준)

### 6-1. 차이

| | `based_on_id` | `version_links` |
|---|---|---|
| 뜻 | **같은 프로젝트·같은 탭**에서 편집을 시작한 저장본 | 같은 프로젝트의 **다른 탭 저장본** 또는 **규제 메모**(`regulatory_notes`) 내용을 실제 반영한 출처 |
| 위치 | `tab_versions` 의 열 (0 또는 1개) | 별도 테이블 (저장본 하나에 여러 출처 가능) |
| 만드는 시점 | 저장할 때 항상 기록 (새 작성이면 NULL) | 반영 후 저장할 때만, 같은 트랜잭션 |
| 당시 값 | 기준 저장본 자체가 불변이라 별도 기록 없음 | `applied_values` 에 반영한 항목·값·위치 기록. 메모 출처는 반영 당시 메모 내용 사본 포함 |
| DB 보장 | FK (`based_on_id`, `project_id`, `tab`) | FK (`version_id`, `project_id`, `tab`), FK (`source_version_id`, `project_id`, `source_tab`), FK (`source_note_id`, `project_id`) |

### 6-2. `version_links` 열

| 열 | 필수 | 설명 |
|---|---|---|
| `id` | ✓ | |
| `project_id` | ✓ | 새 저장본과 출처가 공유하는 프로젝트 |
| `version_id`, `tab` | ✓ | 반영해 새로 저장한 저장본과 그 탭 |
| `source_tab` | ✓ | 출처 탭. 메모 출처면 `regulatory` |
| `source_version_id` | 저장본 출처일 때 | 메모만 출처이면 **NULL** |
| `source_note_id` | 메모 출처일 때 | 4단계 마이그레이션에서 추가. 저장본 출처면 NULL |
| `applied_values` | ✓ | jsonb, 반영 당시 값 |
| `created_by`, `created_at` | ✓ | 서버 로그인 사용자, 저장 시각 |

- `source_version_id` 와 `source_note_id` 중 정확히 하나만 값이 있다. (CHECK) 세부 제약은 `db_rules.md` 2-2.

### 6-3. 예시

예: 마진 v3 의 체크한 사양 변경을 요청서 v4 를 불러와 반영한 뒤 저장 → 새 요청서 v5

- `tab_versions(requisition, v5).based_on_id` = 요청서 v4 의 id
- `version_links`: `version_id` = 요청서 v5, `source_version_id` = 마진 v3, `applied_values` 예:

```json
{
  "target_field": "ingredients.other_notes",
  "items": [
    { "target": "핵심 원료", "before_spec": "…", "after_spec": "…", "lab_request_text": "변경 처방 기준 Lab 샘플 재제작 및 안정도 검토 필요" }
  ],
  "inserted_text": "[견적 사양 변경 (VE) 반영] 변경 사양: … / 요청 사항: …"
}
```

규제 메모만 출처로 반영한 예 (규제 탭 저장본 없음, 조회 결과 없는 메모): 요청서 v5 를 불러와 메모를 반영한 뒤 저장 → 새 요청서 v6

- `version_links`: `version_id` = 요청서 v6, `source_tab` = `regulatory`, `source_version_id` = NULL, `source_note_id` = 메모 id, `applied_values` 예:

```json
{
  "target_field": "rnd_check_requests",
  "note_snapshot": {
    "ingredient_name": null, "country": "SA", "regulation_text": null,
    "lookup_source": null, "looked_up_at": null,
    "memo": "할랄 인증 필요 여부 확인", "note_updated_at": "…"
  },
  "inserted_text": "할랄 인증 필요 여부 확인"
}
```

- 이후 메모를 고쳐도 요청서 v6 payload 와 이 기록은 바뀌지 않는다. 바뀐 메모를 반영하려면 다시 반영해 새 버전(v7)으로 저장한다.

`applied_values` 의 키 이름은 탭별 payload 확정 후 맞춘다. (제안)

---

## 7. 문서 버전과 연구소 개발 차수

| | 문서 버전 | 연구소 개발 차수 |
|---|---|---|
| 기준 | `tab_versions.version_no` (서버 부여) | `dev_rounds` (5단계, 기본설계) |
| 오르는 시점 | 저장할 때마다 | **연구소에 신규·수정 샘플을 의뢰하는 시점** (확정(FIX)) |
| 오르지 않는 경우 | – | 단순 저장, 최종본 지정 (확정(FIX)·개발기준) |
| 단위 | 프로젝트·탭별 | 프로젝트별. 같은 차수 안에 여러 가격대 샘플, 샘플은 Lab No. 로 구분 (확정(FIX)) |

- 기존 개발요청서의 `version` 필드(화면에서 수정 시 1씩 증가)와 PDF 파일명의 버전은 **저장본의 서버 `version_no` 기준으로 맞춘다.** (확정(개발기준))
- **저장하지 않은 문서는 정식 저장 버전처럼 표시하지 않는다.** — 구현됨 (3-2): 화면 문서의 클라이언트 `version`·`document_id` 를 없앴다. 문서 정보 패널에 "문서 버전: 저장 전"과 "저장하면 서버가 버전 번호를 정하고, 연구소 개발 차수와는 따로 관리돼요" 안내, PDF 에는 `Version: 저장 전 (서버 버전 없음)`·꼬리글 "저장 전 문서"(예전의 클라이언트 문서 번호 대신). PDF 파일명에는 버전을 붙이지 않는다. 저장 후 표시는 저장 버튼 연결 때 서버 `version_no` 로 한다.
- PDF 파일명의 나머지 형식(고객사·제품·언어·날짜, FIX 의 "개발요청서 이름" 반영 방식)은 `requisition.md` 44장과 함께 정리한다. (**미정**)
- 차수와 요청서 버전의 연결(어느 차수에 어느 요청서 버전으로 의뢰했는지)과 피드백-요청서 버전 연결(`feedback_version_links`)은 5단계에서 정한다.
