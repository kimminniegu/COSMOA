# COSMOA 업무 DB 규칙 (PM)

> **상태: 1·2단계 구현됨** — 1단계 테이블(0001·0002, 2-4)과 2단계 `tab_versions`·`final_history`·`version_links`(0003, 2-5)를 test·dev 에 적용했다. 공통 저장 API 는 [API 계약](api_contract.md).
> 4단계 이후 테이블·화면 저장 연결은 **아직 구현되지 않았다. (구현 예정)** 로그인은 업무 DB `users` 를 쓴다 (`development.md` 2-1). production 은 미적용.
> 전체 범위·환경·실행 절차는 [개발 안내](development.md), 필드·payload 구조는 [데이터 계약](data_contract.md)을 따른다.
> 표기(확정(FIX) / 확정(개발기준) / 기본설계 / 제안 / 미정)는 `development.md` 0-2 와 같다.

---

## 1. DB 구분 — 확정(개발기준)

| DB | 종류 | 내용 | 관리 |
|---|---|---|---|
| **업무 DB** | Neon PostgreSQL | 사용자·고객사·프로젝트·탭 저장본·최종본 이력·반영 출처 (이후 차수·샘플 등) | yoyo 마이그레이션으로만 생성·변경 |
| 홈 캐시 | SQLite (`HOME_CACHE_DB_PATH`, 기본 `instance/cosmoa.db`) | 환율·뉴스·규제 소식 등 외부 데이터 캐시 | 기존 `home_data.init()` 유지 |
| 식약처 규제 DB | SQLite (읽기 전용) | 사용제한 원료 정보 | 기존 별도 수집 절차 유지 |

- 업무 DB 접근은 psycopg 3 로 **SQL 을 직접 작성**한다. ORM 은 쓰지 않는다.
- SQL 에 값을 문자열로 이어 붙이지 않는다. 항상 매개변수(`%s`)를 쓴다.
- 업무 테이블을 SQLite 에, 캐시 테이블을 업무 DB 에 만들지 않는다.

---

## 2. 테이블 목록과 구현 단계

기본설계 18개 테이블을 유지한다. 단계 번호는 `development.md` 2장과 같다.

| 영역 | 테이블 | 한 행의 뜻 | 기록 방식 | 단계 |
|---|---|---|---|---|
| 공통 | `users` | 계정 1개 | 수정 가능 (계정 정보, 이후 `home_widgets`) | 1 ✅ |
| 공통 | `customers` | 고객사 1곳 | 수정 가능, 삭제하지 않고 보관 | 1 ✅ |
| 공통 | `customer_contacts` | 고객사 담당자 1명 | 수정 가능 | 1 ✅ |
| 프로젝트 | `projects` | 제품 1개 (단계·상태·납기일) | 수정 가능, 삭제하지 않고 보관 | 1 ✅ |
| 프로젝트 | `project_history` | 단계·상태·납기일 변경 1번 (전후 값 + 사유) | **추가만** | 1 ✅ |
| 저장본 | `tab_versions` | 네 탭 중 하나의 저장본 1개 | **추가만** | 2 ✅ |
| 저장본 | `final_history` | 최종본 지정·해제 1번 | **추가만** | 2 ✅ |
| 저장본 | `version_links` | 다른 탭 저장본 또는 규제 메모 내용을 실제 반영한 1건 | **추가만** | 2 (구조) ✅ / 4 (메모 출처 열) / 6 (사용) |
| 저장본 보조 | `requisition_ingredients` | 요청서 저장본의 원료 항목 1개 | **추가만** | 4 이후 |
| 저장본 보조 | `cost_spec_changes` | 원가 저장본의 사양 변경(VE) 1개 | **추가만** | 4 |
| 인허가 | `regulatory_notes` | 프로젝트별 규제 확인사항 메모 1건 | 수정 가능 (반영된 요청서·기록에는 영향 없음, 5-1) | 4 |
| 샘플 | `dev_rounds` | 연구소 의뢰 1차수 | 메모만 수정 | 5 |
| 샘플 | `sample_requests` | 차수 안 가격대별 요청 1건 | 수정 가능 | 5 |
| 샘플 | `lab_samples` | 샘플 1개 (Lab No.) | 메모만 수정 | 5 |
| 샘플 | `sample_shipments` | 샘플 발송 1건 (분할 발송) | 수정 가능 | 5 |
| 샘플 | `sample_feedback` | 피드백 1건 | **추가만** | 5 |
| 샘플 | `feedback_version_links` | 피드백이 반영된 요청서 저장본 1건 | **추가만** | 5 |
| 프로젝트 | `contact_logs` | 연락 1건 | 작성자만 수정 | 7 |

넣지 않는 것 (기본설계): 탭별 전용 저장본 테이블, 최종본 포인터 테이블, 다형 연결 테이블, 첨부파일 테이블(파일 미저장), 사용자 설정 테이블(`users.home_widgets` 로 대체).
`project_events` 는 **미정** — 이번 주 일정 위젯이 납기일 외 직접 등록 일정을 다룰지에 따라 판단한다.
✅ = 마이그레이션 적용됨 (test·dev).

### 2-1. 공통 이름·타입 — 기본설계

1. 테이블·열 이름은 영어 `snake_case`, 테이블은 복수형. 외래키는 `<대상>_id`.
2. 모든 테이블: `id bigint generated always as identity`, `created_at timestamptz default now()`, `created_by → users.id`. 수정 가능한 테이블만 `updated_at`. `created_by` 의 NULL 허용 범위는 3-5.
3. 금액은 `numeric(14,4)` + `currency`(ISO 코드), 국가는 ISO 2글자, 비율은 퍼센트 숫자(25 = 25%).
4. 정해진 값 목록(`tab`, `stage`, `state`, `action` 등)은 `CHECK` 제약으로 막는다.
5. 고객사·프로젝트는 삭제하지 않고 보관한다. 저장본·차수·반영 기록에서 참조된 행은 `ON DELETE RESTRICT`.

### 2-2. 핵심 제약 (요약)

세부 열은 [데이터 계약](data_contract.md) 참고.

- `project_history` (1단계)
  - `projects` 의 단계·상태·납기일 수정과 이력 추가는 **같은 트랜잭션**에서 한다. 하나라도 실패하면 둘 다 취소. — 확정(개발기준)
  - `old_value`·`new_value` 는 **NULL 허용** (납기일 최초 지정·해제 등). — 확정(개발기준)
  - `reason` 은 홀드·드롭으로 바꿀 때 필수. — 확정(FIX)
- `tab_versions`
  - `tab` ∈ {`regulatory`, `margin`, `simulation`, `requisition`} (CHECK)
  - **UNIQUE (`project_id`, `tab`, `version_no`)**
  - **UNIQUE (`id`, `project_id`, `tab`)** — 다른 테이블이 "같은 프로젝트·같은 탭" 조건으로 참조하기 위한 키
  - `based_on_id` → FK (`based_on_id`, `project_id`, `tab`) → `tab_versions(id, project_id, tab)`
  - `is_final` 같은 최종본 표시 열은 **두지 않는다.**
- `final_history`
  - `action` ∈ {`set`, `unset`}, `set` 이면 `version_id` 필수·`unset` 이면 NULL (CHECK)
  - FK (`version_id`, `project_id`, `tab`) → `tab_versions(id, project_id, tab)`
- `version_links` — 한 행 = 새 저장본 하나에 반영한 출처 하나
  - 출처는 **다른 탭 저장본**(`source_version_id`) 또는 **규제 메모**(`source_note_id`) 중 **정확히 하나** (CHECK `num_nonnulls(source_version_id, source_note_id) = 1`). 메모만 출처이면 `source_version_id` 는 NULL.
  - FK (`version_id`, `project_id`, `tab`) → `tab_versions(id, project_id, tab)` — 반영해 새로 저장한 저장본
  - FK (`source_version_id`, `project_id`, `source_tab`) → `tab_versions(id, project_id, tab)` — 출처 저장본. `source_version_id` 가 NULL 이면 검사하지 않는다(기본 MATCH SIMPLE).
  - FK (`source_note_id`, `project_id`) → `regulatory_notes(id, project_id)` — 출처 메모. 이를 위해 `regulatory_notes` 에 UNIQUE (`id`, `project_id`).
  - 모든 FK 가 같은 `project_id` 열을 공유하므로 **다른 프로젝트의 저장본·메모는 연결할 수 없다.**
  - `source_note_id` 가 있으면 `source_tab = 'regulatory'` (CHECK)
  - `source_tab <> tab` (CHECK, 제안) — 같은 탭 안의 편집 시작점은 `based_on_id` 로 표현한다.
  - UNIQUE (`version_id`, `source_version_id`), UNIQUE (`version_id`, `source_note_id`)
  - 반영 출처로 참조된 메모는 삭제할 수 없다 (`ON DELETE RESTRICT`).
  - 단계: 2단계 마이그레이션은 저장본 출처만 다룬다(`source_version_id` 필수). `source_note_id` 열·FK·"출처는 정확히 하나" CHECK 는 `regulatory_notes` 를 만드는 4단계 마이그레이션(새 파일)에서 추가한다.

### 2-3. 확인이 필요한 설계 — 미정

- **규제 탭 저장본(`tab_versions`, `tab='regulatory'`)의 payload 구조와 용도.** 규제 확인사항은 수정 가능한 프로젝트별 메모 `regulatory_notes` 로 확정했고, 개발요청서에는 규제 탭 저장본 없이 메모를 바로 반영할 수 있다(5-1). 규제 탭 저장본에 무엇을 남길지는 4단계에서 탭 담당자와 정한다.
- `requisition_ingredients` 의 열(`kind` 필수/선호/금지, `must_contain`, `efficacy_tags`)은 FIX 컨셉 원료 구조(`data_contract.md` 4-3 `ingredients.concept`)와 맞춘다. 개발요청서 payload 는 3단계부터 이 구조로 저장하고, 색인 테이블은 4단계 이후 만든다. 만들 때 기존 저장본의 행을 payload 에서 채우는 방식은 구현 시 정한다.

### 2-4. 1단계 구현 내용 (`0001_core.sql`, `0002_project_rules.sql`) — 확정(개발기준)

| 대상 | 구현 |
|---|---|
| 공통 | `id bigint generated always as identity`, `created_at timestamptz default now()`, 수정 가능한 테이블은 `updated_at` (UPDATE 시 트리거로 갱신) |
| `users` | `email`(소문자·공백 없음, UNIQUE), `name`, `team`(기존 SQLite 와 같음, 기본 `''`), `password_hash`(werkzeug `scrypt:`/`pbkdf2:` 형식만 CHECK — 평문 저장 방지용이며 비밀번호 검증은 `check_password_hash`), `created_by` → users (NULL 허용, **NULL 인 행은 하나만** — 최초 계정) |
| `customers` | `name`, `archived_at`(보관 시각, NULL = 사용 중), `created_by` NOT NULL. **DELETE·TRUNCATE 거부** (보관으로 대체) |
| `customer_contacts` | `customer_id` → customers, `name`, `created_by` NOT NULL. 연락처·직함 등은 미정이라 두지 않음 |
| `projects` | `customer_id` → customers, `name`, `stage`(기본 `proposal`)·`state`(기본 `active`) 를 따로 CHECK, `due_date date`(NULL = 미정), `archived_at`, `created_by` NOT NULL. **DELETE·TRUNCATE 거부** |
| `project_history` | `field` ∈ {`stage`,`state`,`due_date`}, `old_value`/`new_value` NULL 허용·서로 달라야 함·필드별 값 형식 CHECK, `state` 를 `hold`/`drop` 으로 바꿀 때 `reason` 필수(공백 불가), `created_by` NOT NULL. **UPDATE·DELETE·TRUNCATE 거부** |
| 변경·이력 원자성 | `projects` 의 `stage`·`state`·`due_date` 를 바꾼 트랜잭션에 대응하는 `project_history` 행(같은 전후 값, **같은 `xact_id`**)이 없으면 **커밋 시 거부** (DEFERRABLE 제약 트리거). 0002 에서 판단 기준을 `created_at = now()` 에서 트랜잭션 id 로 교체 |
| `project_history.xact_id` (0002) | `xid8`. 이력을 기록한 최상위 트랜잭션 id 를 `BEFORE INSERT` 트리거가 `pg_current_xact_id()` 로 채운다(클라이언트 값 무시). 새 행은 NOT NULL(`NOT VALID` CHECK), 0002 이전 행은 NULL 그대로 둔다. `created_at` 은 표시용 시각 |
| 신규 프로젝트 (0002) | INSERT 시 `stage='proposal'`, `state='active'` 만 허용(트리거). 납기일은 생성 시 입력 가능. 이후 변경은 `change_project()` + 이력 |
| FK | 모든 FK `ON DELETE RESTRICT` |

- 홀드·드롭 사유는 `project_history.reason` 에 남긴다. `projects` 에 현재 사유 열은 두지 않는다 (마지막 `state` 이력에서 읽음).
- 서버 코드는 `src/common/projects.py` 의 `change_project()` 로 수정·이력을 한 트랜잭션에서 처리한다. 작성자는 서버 로그인 사용자 id 를 넘긴다.
- 고객사 `timezone`·국가, 프로젝트 제품 유형·담당자 등 **미정** 열은 넣지 않았다. 확정되면 새 마이그레이션으로 추가한다.

### 2-5. 2단계 구현 내용 (`0003_versioning.sql`) — 확정(개발기준)

| 대상 | 구현 |
|---|---|
| `tab_versions` | `project_id`·`tab`(CHECK 4개)·`version_no`·`schema_version`(≥1)·`payload`(jsonb, 네 칸 객체 CHECK)·`created_by` NOT NULL. `based_on_id`·`title` NULL 허용(`title` 1~200자). UNIQUE (`project_id`,`tab`,`version_no`), UNIQUE (`id`,`project_id`,`tab`), FK (`based_on_id`,`project_id`,`tab`) → 같은 프로젝트·같은 탭, `based_on_id < id`. `version_no`·`xact_id`(저장 트랜잭션 id) 는 트리거가 채움 |
| `final_history` | `action` ∈ {set, unset}, set ↔ `version_id` NOT NULL / unset ↔ NULL (CHECK). FK (`version_id`,`project_id`,`tab`) → 같은 프로젝트·같은 탭. 색인 (`project_id`,`tab`,`id DESC`). 트리거가 프로젝트 행을 잠근 뒤 **더 큰 id 의 기록이 이미 있으면 거부**(40001, 서버가 한 번 재시도) → id 순서 = 기록 순서 |
| `version_links` | 모든 열 NOT NULL (2단계는 저장본 출처만: `source_version_id` 필수). FK (`version_id`,`project_id`,`tab`), FK (`source_version_id`,`project_id`,`source_tab`) → 같은 프로젝트. `source_tab <> tab`, `source_version_id < version_id`, `applied_values` 객체, UNIQUE (`version_id`,`source_version_id`). **새 저장본과 같은 트랜잭션에서만** 추가 (저장본 `xact_id` = 현재 트랜잭션, 트리거) |
| 공통 | 세 테이블 UPDATE·DELETE·TRUNCATE 거부 (`forbid_append_only_change`). 참조 FK 는 모두 `ON DELETE RESTRICT` |

- `regulatory_notes` 와 `version_links.source_note_id`·"출처는 정확히 하나" CHECK 는 4단계 새 마이그레이션에서 추가한다 (2-2). 0003 은 없는 테이블을 참조하지 않는다.
- 현재 최종본 판단·409 처리·검증 수준은 [API 계약](api_contract.md) 2-3·3장.

---

## 3. 저장 규칙

### 3-1. 저장 = 불변 저장본 추가 — 확정(개발기준)

- 저장할 때마다 `tab_versions` 에 **새 행을 추가**한다. 저장본은 저장 시점의 값을 **복사한** 불변 기록이다.
- 기존 저장본을 수정·삭제·덮어쓰지 않는다.
- `tab_versions`, `final_history`, `version_links` 의 `UPDATE`·`DELETE`·`TRUNCATE` 는 **DB 트리거로 막는다.** (0003 구현됨)
  - 이후 추가되는 "추가만" 테이블(`project_history`, `sample_feedback`, 보조 테이블 등)도 같은 방식으로 막는다. (기본설계) — `project_history` 는 0001 에서 구현됨
- 원본(고객사·프로젝트 정보, 다른 탭 저장본, 규제 메모)이 나중에 바뀌어도 이미 저장한 요청서 내용은 바뀌지 않는다. 다른 탭 저장본을 다시 읽어 화면 값을 덮어쓰지 않는다.

### 3-2. 버전 번호 — 확정(개발기준)

- `version_no` 는 **서버가 부여**한다. 클라이언트가 보낸 버전 번호는 쓰지 않는다. (0003: `BEFORE INSERT` 트리거가 프로젝트 행을 잠근 뒤 `max + 1` 을 넣는다. INSERT 에 번호를 넣어도 무시됨. API 는 본문의 `version_no` 를 400 으로 거부)
- 같은 프로젝트·탭 안에서 1부터 증가하고 중복을 허용하지 않는다. (UNIQUE 가 최종 보장)
- 저장 트랜잭션 순서
  1. `SELECT ... FROM projects WHERE id = %s FOR UPDATE` 로 **프로젝트 행 잠금**
  2. 해당 프로젝트·탭의 `max(version_no) + 1` 계산
  3. `based_on_id` 검증 (같은 프로젝트·탭인지 — 복합 FK 로도 보장)
  4. `tab_versions` 행 추가
  5. 반영 출처(다른 탭 저장본 또는 규제 메모)가 있으면 `version_links` 추가, 보조 테이블이 있으면 payload 에서 생성 (같은 트랜잭션)
  6. 커밋. 하나라도 실패하면 전부 취소.
- UNIQUE 위반(예상 밖 충돌)이 나면 짧게 재시도하거나 오류를 돌려준다. 다른 번호를 몰래 쓰지 않는다.

### 3-3. based_on_id 와 오래된 저장본 기준 저장 — 확정(개발기준)

- `based_on_id`: **같은 프로젝트·탭**에서 사용자가 편집을 시작한 저장본. 새로 작성했으면 NULL.
- 사용자가 최신이 아닌 저장본을 불러와 편집한 뒤 저장해도 **저장은 진행**하고 새 버전을 만든다. `based_on_id` 는 사용자가 실제로 시작한 저장본 그대로 남긴다.
- 서버는 응답에 "기준 저장본이 최신 버전과 다르다"는 정보(기준 버전 번호, 저장 직전 최신 버전 번호)를 담고, 화면은 이를 안내한다. 기존 저장본은 덮어쓰지 않는다.

### 3-4. 보조 테이블 — 확정(개발기준)

- `requisition_ingredients`, `cost_spec_changes` 등 보조 테이블은 **저장본 payload 를 기준으로**, 저장본과 **같은 트랜잭션에서** 생성한다.
- 보조 테이블만 따로 수정하지 않는다. (추가만 + 트리거) payload 와 보조 테이블 값이 달라지지 않게 한다.
- 검색·누락 경고에 필요한 값이 생기면 payload 에서 빼지 말고 보조 테이블로 색인한다. (기본설계)

### 3-5. 작성자·사용자 범위

- `created_by` 는 **서버 로그인 세션 사용자**로 정한다. 요청 본문의 작성자 값은 무시한다. — 확정(개발기준)
  - 서버 코드는 `auth.current_user()["id"]` 를 쓴다. 이 값은 세션 v2 의 `uid` 를 매 요청 업무 DB `users` 에서 다시 확인한 것이다.
- **시스템 작업 예외** — 확정(개발기준)
  - 모든 `created_by` 가 기존 로그인 사용자를 요구하면 첫 계정을 만들 수 없다. 최초 계정 생성처럼 로그인 사용자가 없는 **시스템 작업**은 `created_by` 를 NULL 로 기록한다.
  - 1단계에서 NULL 을 허용하는 열은 `users.created_by` 다. 다른 테이블에 시스템 작업이 필요해지면 해당 마이그레이션에서 정하고 이 문서에 적는다.
  - **일반 사용자 작업**(웹 요청 처리)은 항상 세션 사용자를 기록한다. 로그인 사용자가 없으면 거부하며 NULL 로 저장하지 않는다.
  - 시스템 작업은 웹 요청이 아닌 별도 관리 명령으로만 수행한다. 첫 계정 명령: `python -m src.common.db_admin create-first-user` (계정이 하나도 없을 때만, 비밀번호는 숨김 입력). DB 도 `created_by` NULL 인 계정을 하나만 허용한다. (`development.md` 5-2)
- 로그인한 팀 사용자 전체가 프로젝트·저장본을 공유하는 것은 **개발용 기본 정책**이다. 운영 권한은 별도 확정 항목.

### 3-6. payload 크기

- **초기값** payload 256 KiB·반영 기록 32 KiB·출처 20개, 환경변수로 바꾼다. 근거·측정값은 `api_contract.md` 4장. 마진·모델링 대표 데이터가 나오면 다시 정한다.
- 상한을 넘으면 내용을 **몰래 잘라 저장하지 않고 오류를 반환**한다. — 확정(개발기준)

---

## 4. 최종본 규칙

### 4-1. 판단 방식 — 확정(개발기준)

- 최종본 지정·변경·해제는 모두 `final_history` 에 **새 기록을 추가**한다. `tab_versions` 에 `is_final` 을 두거나 고치지 않는다.
- **현재 최종본** = 해당 (`project_id`, `tab`) 의 `final_history` 중 **`id` 가 가장 큰 기록**.
  - `set` → 그 `version_id` 가 현재 최종본 / `unset` → 최종본 없음 / 기록 없음 → 최종본 없음.
  - 순서 기준은 `id` 이다. `created_at` 은 트랜잭션 시작 시각이라 순서 판단에 쓰지 않는다.
  - 같은 프로젝트의 최종본 변경은 프로젝트 행 잠금으로 **한 번에 하나씩** 처리되므로, 같은 (`project_id`, `tab`) 안에서는 `id` 순서가 기록 순서와 일치한다.
- 같은 프로젝트·같은 탭의 저장본만 지정할 수 있다. (복합 FK)
- "변경"은 다른 저장본으로 `set` 을 새로 추가하는 것이다.

### 4-2. 최종본 변경 동시 처리 — 확정(개발기준)

요청에는 클라이언트가 알고 있는 **현재 `final_history` 기록 id** (`expected_final_history_id`, 기록이 없으면 null)를 포함한다.

서버는 한 트랜잭션에서
1. 프로젝트 행 잠금 (`FOR UPDATE`)
2. 해당 프로젝트·탭의 마지막 `final_history` 를 다시 조회해 `expected_final_history_id` 와 비교
3. 같으면 새 기록 추가 후 커밋
4. 다르면 기록을 추가하지 않고 **409 와 현재 최종본 상태**(마지막 기록 id, `set`/`unset`, 대상 버전 번호, 작성자, 시각)를 반환

409 를 받은 화면은 **사용자가 편집 중인 내용을 그대로 유지**하고, 바뀐 최종본 상태만 갱신해 보여준 뒤 사용자가 다시 결정하게 한다.

### 4-3. 최종본의 의미

- 최종본으로 지정하면 프로젝트 화면·개발 진행 현황에 ★ 로 표시되고, 다른 탭에서 불러올 때 기본값으로 선택된다. — 확정(FIX)
- **최종본 지정 ≠ 발송.** 최종본 이력은 "누가 언제 어느 버전을 최종본으로 지정/해제했는지"만 뜻한다. 연구소·고객에게 실제로 보냈는지, 상대가 어떤 버전을 받았는지는 알 수 없다. 문서 발송 기록은 현재 구현 범위가 아니므로 "발송 이력"으로 표시하지 않는다. — 확정(개발기준)
- 최종본 지정은 개발 차수를 올리지 않는다. (`data_contract.md` 7장)

---

## 5. 반영 출처 규칙 (`version_links`) — 확정(개발기준)

- 단순 미리보기·불러오기만으로는 만들지 않는다. 사용자가 다른 탭 내용을 **실제 반영한 뒤 새 저장본을 저장할 때**, 그 저장본과 **같은 트랜잭션에서** 만든다.
- `applied_values` 에 **반영 당시의 값**(반영한 항목, 실제 들어간 문구·값, 반영 위치)을 기록한다. 출처 저장본이 나중에 바뀌어도 기록은 그대로다.
- 같은 프로젝트의 저장본·규제 메모만 연결한다. (복합 FK)
- 탭별 반영 허용 범위 — 확정(FIX)
  - 마진 → 요청서: **선택(체크)한 사양 변경 사항만.** 단가·마진 등 원가 수치는 제외.
  - 규제 → 요청서: 사용자가 선택한 규제 결과·메모. 출처는 규제 탭 저장본 또는 `regulatory_notes`(5-1). **메모만 반영**하는 경우도 지원.
  - 모델링 → 요청서: 예상 질감·예측 점도, 컨셉원료 코멘트, 용기 적합성(참고값)만. **배합 조절 수치 제외.**
  - 요청서 → 모델링·규제: 저장된 요청서 **payload(구조화 데이터)** 를 불러온다. PDF 재업로드·재추출을 기본 경로로 삼지 않는다.
- 서버는 반영 내용이 허용 범위를 벗어나는지(예: 마진 수치 포함) 확인한다. 구체 검사 항목은 탭별 payload 확정 후 정한다.
- 원가 변동 감지 배너(제안): 요청서의 마지막 `version_links` 출처 마진 저장본과 현재 마진 최종본(또는 최신 저장본)이 다르면 배너를 띄운다. 기준(최종본/최신)은 **미정**.

### 5-1. 규제 메모를 출처로 반영 — 확정(개발기준)

- `regulatory_notes` 는 **수정 가능한 프로젝트별 메모**로 유지한다. 규제 탭 저장본을 따로 만들지 않아도 사용자가 고른 메모를 개발요청서에 반영할 수 있다.
- 요청서 새 저장본을 저장하는 **같은 트랜잭션**에서 반영한 메모마다 `version_links` 한 행을 추가한다.
  - `source_note_id` = 메모 id, `source_version_id` = NULL, `source_tab` = `regulatory`
  - `applied_values` = **반영 당시 메모 내용 사본**(성분명·국가·규제 내용·조회 출처·조회일·메모, 메모의 `updated_at`)과 실제 넣은 문구·위치
- 메모 사본은 서버가 저장 트랜잭션 안에서 DB 의 메모를 읽어 만든다. 클라이언트가 보낸 메모 내용을 출처 기록으로 쓰지 않는다.
- 같은 프로젝트 검증: 서버가 메모의 `project_id` 를 확인하고, DB 도 FK (`source_note_id`, `project_id`) → `regulatory_notes(id, project_id)` 로 다른 프로젝트 메모를 거부한다.
- 원본 메모를 나중에 수정해도 이미 저장된 요청서 payload 와 `version_links` 기록은 바뀌지 않는다. (추가만 + 트리거) 화면은 메모를 다시 읽어 저장된 요청서 값을 덮어쓰지 않는다. 바뀐 메모를 반영하려면 다시 반영해 새 버전으로 저장한다.
- 반영 후 저장 전에 메모가 수정된 경우의 처리는 구현 시 정한다. (제안: 반영 시점 메모의 `updated_at` 을 함께 보내고, 다르면 저장은 진행하되 응답에 알린다 — 3-3 과 같은 방식)

---

## 6. 파일 제외 정책 — 확정(개발기준)

- **원본 업로드 파일과 참고자료 파일 본문은 영구 저장하지 않는다.** (DB·서버 디스크 모두)
- `data_url` 과 파일 본문을 담은 base64 는 **클라이언트와 서버 양쪽에서** 저장 대상에서 제외한다. 서버는 클라이언트가 보낸 값을 믿지 않고 다시 제거·검사한다.
- 참고자료는 파일명·크기·형식 등 **메타데이터만** 저장한다. `source_file` 은 파일명만 저장한다.
- 현재 화면의 참고자료 미리보기·다운로드·PDF 이미지 표시, 원본 RFP 다운로드는 **페이지 메모리에서만** 동작한다. DB 저장 범위와 구분한다.
- ⚠ **저장본을 다시 불러오면 원본 파일·참고자료 본문·참고 이미지는 복원되지 않는다.** 화면에 이 사실을 안내한다. 필요하면 사용자가 다시 첨부한다.
- `raw_extracted_data` 는 **1차 저장 대상에서 제외**한다. 사용자가 확인한 개발요청서 값과 필요한 출처 정보만 저장한다.
- `src/05_requisition/service.py` 의 "원본 파일은 서버 디스크에 저장하지 않습니다" 주석과 동작은 유지한다.
- 저장 제외 필드 전체 목록은 `data_contract.md` 5장.

---

## 7. 마이그레이션 규칙 (yoyo) — 확정(개발기준)

### 7-1. 작성

- 업무 테이블 생성·변경은 **yoyo 마이그레이션 파일로만** 한다. 서버 코드·Neon 콘솔에서 직접 `CREATE`/`ALTER` 하지 않는다.
- 위치: `db/migrations/`
- 파일명: `NNNN_설명.sql` (예: `0001_core.sql`). 되돌리기 파일이 필요하면 `NNNN_설명.rollback.sql`.
- 의존 관계는 파일 상단 `-- depends: <이전 파일 이름>` 으로 적는다.
- 한 파일에는 한 목적만 담는다.
- **이미 어느 DB 에든 적용했거나 `develop` 에 합쳐진 파일은 수정하지 않는다.** 바꿀 내용은 새 파일로 추가한다. (`0001_core.sql`·`0002_project_rules.sql`·`0003_versioning.sql` 은 test·dev 에, `0004_app_role_grants.sql` 은 test·dev 에 적용됨 → 수정 금지)
- 파일은 UTF-8 로 저장한다.
- 앱이 새로 쓰는 표·열의 권한(`GRANT … TO cosmoa_app`)도 같은 마이그레이션에 적는다 (8-9).
- 열 삭제·이름 변경은 바로 하지 않는다: 새 열 추가 → 코드 전환 → 다음 마이그레이션에서 삭제 (2단계, 기본설계).
- payload 구조를 바꾸면 `db/schemas/` 의 JSON Schema 버전을 올리고, **이전 버전 저장본을 읽는 변환 코드**를 같은 PR 에 넣는다. (기본설계)
  - 단, 버전 올림과 변환 코드는 **그 구조로 저장된 저장본이 개발·운영 DB 에 생긴 뒤**부터 필요하다. 저장본이 없을 때(테스트 DB 에만 있을 때 포함)는 버전을 올리지 않고 현재 버전을 고친다. 개발요청서는 3단계에서 FIX 구조를 첫 버전(`schema_version = 1`)으로 시작하며, v1→v2 변환을 미리 만들지 않는다. — 확정(개발기준)

### 7-2. 검토

- 업무 DB 변경 PR 은 **PM(DB 담당) 승인 필수**. 그 외 PR 은 조원 1명 리뷰. (기본설계)
- PR 에 적을 것: 목적, 영향 테이블, 되돌리기 방법, 테스트 DB 적용 결과, 데이터 삭제 여부.

### 7-3. 적용

- 마이그레이션은 **별도 명령으로 직접 실행**한다: `python -m src.common.db_admin migrate --target test|dev` (`development.md` 5-2). Flask·Gunicorn 시작 시 자동 실행하지 않는다.
- 적용 전 DB 상태가 저장소 마이그레이션과 다르면(모르는 테이블, 미적용인데 있는 테이블 등) 삭제·덮어쓰기 없이 거부하고 보고한다.
- `test` 대상은 테스트 DB 식별, `dev` 대상은 `DEV_DATABASE_ENDPOINT_ID` 고정 확인을 통과해야 한다 (`development.md` 4-2). 운영 환경에서는 관리 명령을 거부한다.
- 적용 순서: **테스트 DB → 개발 DB → 운영 DB**. 운영 적용은 PM 이 한다. 절차는 `development.md` 5-3.
- 마이그레이션은 해당 환경의 `DATABASE_URL_DIRECT` 를 쓴다. 테스트 DB 준비는 `TEST_DATABASE_URL` 만 쓴다. 다른 주소로 자동 대체하지 않는다.

### 7-4. 접속정보

- 접속정보는 `.env` 또는 배포 환경변수로만 전달한다. 문서·코드·커밋·PR·로그에 실제 값을 쓰지 않는다.


---

## 8. 접속 역할과 권한 — **test·dev 적용 완료 / production 미적용**

> 상태 (2026-10-21)
> - **test**: `cosmoa_app`·`cosmoa_app_test`·`0004_app_role_grants` 적용, 8-6 의 허용·금지 검증 모두 통과.
> - **dev**: `cosmoa_app`·`0004` 적용, 현재 개발자(공통 DB 담당)용 `cosmoa_app_yjh` 생성, 그 개발자의 로컬 `.env` `DATABASE_URL` 을 이 역할의 풀링 주소로 교체 (8-8). dev 는 읽기 전용 확인만 했고 파괴적 시험·통합 테스트는 돌리지 않았다.
> - **팀원용 DB 역할·대시보드 계정은 아직 만들지 않았다.**
> - **production**: 접속·적용하지 않음.
>
> 앱 역할은 **DDL·소유자 권한(트리거 끄기·표 삭제·TRUNCATE 등)으로부터 업무 DB 구조와 추가만 규칙을 보호**하는 장치다. DB 에 직접 접속하면 다른 사용자의 `password_hash` 조회·수정과 작성자(`created_by`) 사칭은 막지 못한다 (8-7).
> dev 는 **개발 전용 비밀번호**(운영과 다른 값)와 **테스트용 업무 데이터**만 쓴다. 실제 고객사 정보·운영 비밀번호를 넣지 않는다.

### 8-1. 두 종류의 계정 — 혼동 주의

| | 대시보드 계정 | PostgreSQL 로그인 역할 |
|---|---|---|
| 무엇 | 사람이 COSMOA 화면에 로그인하는 계정 (`users` 표의 한 행) | 앱 서버(Flask)가 DB 에 접속할 때 쓰는 DB 계정 (`DATABASE_URL` 의 사용자 부분) |
| 만드는 명령 | `create-first-user`, `create-user`, `set-password` (5-2) | `app-role create-login` (8-5) |
| 비밀번호 보관 | werkzeug 해시로 `users.password_hash`. 본인 변경 화면 `/account/password` | Neon(PostgreSQL)이 보관. 접속 주소 안에 들어감 |
| 권한 범위 | 앱 기능 (지금은 사용자 모두 같음) | DB 표·열 권한 (`cosmoa_app` 묶음) |

- 한쪽을 만들어도 다른 쪽은 생기지 않는다. 팀원 한 명은 보통 둘 다 받는다: **대시보드 계정**(로그인 화면용)과 **dev 앱 역할 주소**(로컬 앱 실행용 `DATABASE_URL`).
- 앱 역할로 접속한 앱도 대시보드 계정을 만들 수 없다 (`users` INSERT 없음). 계정 추가·재설정은 관리 역할 주소(`DATABASE_URL_DIRECT`)를 쓰는 관리 명령으로만 한다.

### 8-2. 적용 전 위험 (분리 이유)

- 앱(`DATABASE_URL`)과 관리 명령(`DATABASE_URL_DIRECT`)이 **같은 관리 역할**(Neon 기본 `neondb_owner`)로 접속했다. 이 역할은 `public` 의 테이블 12개(업무 8개 + yoyo 4개)를 **모두 소유**하고 `CREATEROLE` 을 가지며 `neon_superuser` 의 멤버다 (superuser 아님).
- 테이블 소유자는 `ALTER TABLE … DISABLE TRIGGER`·`DROP`·`TRUNCATE` 를 할 수 있다. 즉 **추가만·삭제 금지 트리거는 소유자 권한 앞에서는 보호가 아니다.** 이 주소를 팀원에게 그대로 나눠 주면 실수 한 번으로 저장본 불변 규칙이 깨질 수 있다.
- 마이그레이션 함수는 모두 `SECURITY INVOKER`(기본값, `SECURITY DEFINER` 0개)다. 트리거 안의 `SELECT … FOR UPDATE`·조회는 **앱 역할 권한으로** 실행되므로 앱 역할에 그만큼의 권한이 필요하다.

### 8-3. 역할 구성 — 확정(개발기준)

| 역할 | 종류 | 쓰는 곳 | 상태 |
|---|---|---|---|
| 관리 역할 (`neondb_owner`) | LOGIN, 테이블 소유 | `DATABASE_URL_DIRECT`·`TEST_DATABASE_URL` — 관리 명령·마이그레이션·통합 테스트 준비. 공통 DB 담당만 | 기존 |
| `cosmoa_app` | **NOLOGIN NOINHERIT 그룹**, 표식 `cosmoa-app-group v1` | 권한 묶음 (8-4) | test·dev 적용 |
| `cosmoa_app_test` | LOGIN INHERIT, 표식 `cosmoa-app-login v1`, `cosmoa_app` 멤버(INHERIT TRUE, **SET FALSE**) | `TEST_APP_DATABASE_URL` — 앱 역할 검증 전용 (test 풀링 주소). test 에만 있음 | test 적용 |
| `cosmoa_app_yjh` | 위와 같은 형태 | 현재 개발자(공통 DB 담당)의 dev `DATABASE_URL`. dev 에만 있음 | **dev 적용** |
| `cosmoa_app_<개발자>` | 위와 같은 형태, 개발자마다 하나 | 각 팀원의 dev `DATABASE_URL` | **미생성** (8-8) |
| production 앱 역할 | 위와 같은 형태 | production 앱 | 배포 준비 단계 (PM) |

- 이름 규칙: `cosmoa_app_<영문 소문자·숫자·_>` (`db_admin` 이 확인, 예: `cosmoa_app_test`, `cosmoa_app_jh`).
- **판단 기준은 이름이 아니라 실제 속성·멤버십·소유권이다.** `app-role check` 가 SUPERUSER·CREATEROLE·CREATEDB·REPLICATION·BYPASSRLS 없음, 소유 객체 0, 멤버십(`cosmoa_app` 하나, SET 불가), 다른 역할(관리 역할·`neon_superuser`·`pg_*` 기본 역할) 상속·전환 불가를 확인한다.
- 같은 이름의 역할이 이미 있으면 표식·속성·멤버십이 맞을 때만 "변경 없음"으로 통과한다. 표식이 없거나(알 수 없는 역할) 다르면 **고치거나 인수하지 않고 거부**한다. 이미 있는 역할의 비밀번호는 바꾸지 않는다.

**Neon·PostgreSQL 확인 사항 (2026-10-21)**

- 역할은 브랜치에 속한다: "In Neon, roles belong to a branch". 자식 브랜치를 만들 때 부모의 역할이 복제된다 (시점 지정 브랜치는 그 시점 이후 만든 역할 제외). → **test 에서 만든 역할은 dev·production 에 생기지 않는다.** test 를 부모로 새 브랜치를 만들면 거기에는 복제된다. test 를 부모 기준으로 reset 하면 "complete overwrite" 라서 역할도 사라질 수 있다 (문서에 역할 언급 없음) → reset 후에는 8-5 를 다시 실행한다. ([Manage roles](https://neon.com/docs/manage/roles), [Reset from parent](https://neon.com/docs/guides/reset-from-parent))
- 콘솔·CLI·API 로 만든 역할은 `neon_superuser` 멤버가 된다. SQL `CREATE ROLE` 역할은 기본 권한만 받는다 → **앱 역할은 SQL(`db_admin`)로 만든다.**
- 비밀번호: Neon 은 엔트로피 60비트 이상을 요구하고 평문으로만 받는다 (해시 미지원). `db_admin` 은 16자 이상을 요구한다.
- 풀링: Neon 문서는 SQL 역할의 풀링 제한을 언급하지 않는다 (PgBouncer 는 사용자·DB 조합마다 풀을 따로 둔다). **test 에서 SQL 로 만든 `cosmoa_app_test` 의 풀링(-pooler) 접속 인증을 실제로 확인했다.** ([Connection pooling](https://neon.com/docs/connect/connection-pooling))
- PostgreSQL 18.6: 멤버십 옵션(INHERIT·SET·ADMIN)을 따로 준다. 로그인 역할은 `WITH INHERIT TRUE, SET FALSE` 로 받아 권한은 상속하지만 `SET ROLE cosmoa_app` 은 못 한다 (그 역할 이름으로 객체 생성·소유권 이전 불가). CREATEROLE 관리 역할이 역할을 만들면 관리 역할이 그 역할의 ADMIN OPTION 을 자동으로 갖는다 (`createrole_self_grant` 빈 값 — INHERIT·SET 없음). 관리 역할 쪽 권한이며 앱 역할 권한은 늘지 않는다.
- PUBLIC 기본 권한(그대로 둠): DB `CONNECT`·`TEMP`, `public` 스키마 `USAGE`(PG15+ 는 CREATE 없음), 함수 `EXECUTE`. `public` 함수 9개는 모두 트리거 함수라 직접 호출하면 거부된다(0A000). `TEMP` 회수 여부는 미정 (8-8).

### 8-4. 앱 역할 권한 — `0004_app_role_grants.sql`

```sql
GRANT USAGE ON SCHEMA public TO cosmoa_app;
GRANT SELECT ON users, customers, customer_contacts, projects, project_history,
                tab_versions, final_history, version_links TO cosmoa_app;
GRANT INSERT ON customers, projects, tab_versions, final_history, version_links TO cosmoa_app;
GRANT UPDATE (password_hash) ON users TO cosmoa_app;          -- 본인 비밀번호 변경 (열 단위)
GRANT UPDATE (updated_at) ON customers, projects TO cosmoa_app; -- 행 잠금(FOR SHARE·FOR UPDATE)에 필요한 최소 열
```

- 파일 첫 부분의 `DO` 블록이 `cosmoa_app` 이 있고 NOLOGIN·관리 속성 없음·표식 일치인지 확인한다. 아니면 **실패하고 아무 권한도 주지 않는다** (역할을 먼저 만들게 하는 순서 확인 장치). 역할 자체는 마이그레이션이 만들지 않는다 (역할은 DB 전체 객체이고 브랜치마다 따로 있음).
- 기준 상수: `src/common/db_admin.py` 의 `APP_TABLE_PRIVILEGES`·`APP_UPDATE_COLUMNS`. `app-role check` 가 실제 유효 권한(직접 GRANT·PUBLIC·상속 포함)과 비교해 **적어도 많아도** 문제로 보고한다.
- `updated_at` 은 `BEFORE UPDATE` 트리거가 `now()` 로 다시 덮어써서 업무 값을 바꿀 수 없다.
- 시퀀스: 모든 id 가 `GENERATED ALWAYS AS IDENTITY` 라 시퀀스 권한 없이 추가된다 (test 에서 시퀀스 권한 0개로 확인).
- **주지 않는 것**: DELETE·TRUNCATE·REFERENCES·TRIGGER·MAINTAIN 전부, `users` INSERT(계정 추가는 관리 명령), `project_history` INSERT·`projects` 단계·상태·납기·보관 열 UPDATE(단계 변경 API 미연결), `customers.name` 등 업무 열 UPDATE, `customer_contacts` 쓰기, yoyo 표 4개 전부, 스키마·DB CREATE.
- 되돌리기 `0004_app_role_grants.rollback.sql`: `cosmoa_app` 의 권한만 회수한다 (역할은 남김, 데이터 변화 없음).

### 8-5. 실행 순서와 명령 (Windows CMD, 공통 DB 담당)

| 순서 | 명령 | 책임 | 하는 일 |
|---|---|---|---|
| 1 | `app-role init-group --target test` | 공통 권한 역할 생성 | `cosmoa_app` 생성 (NOLOGIN NOINHERIT, 관리 속성 없음, 표식). 이미 있으면 확인만 |
| 2 | `migrate --target test` | 업무 표 권한 | `0004` 적용. 1 이 안 되어 있으면 실패 |
| 3 | `app-role create-login --target test --role cosmoa_app_test` | 로그인 역할·비밀번호 | 비밀번호 숨김 입력 2번 → 로그인 역할 생성 + 표식 + `cosmoa_app` 멤버십(SET 불가). 1·2 가 안 되어 있으면 묻기 전에 거부. 이미 있으면 확인만 |
| 4 | `app-role check --target test --role cosmoa_app_test` | 확인 (읽기만) | 문제 0건이어야 완료 (종료 코드 0, 문제 있으면 3) |
| 5 | 앱 역할 풀링 주소를 Git 제외 `.env` 의 `TEST_APP_DATABASE_URL` 에 넣는다 | 로컬 설정 | 관리 역할 주소와 같은 호스트에 `-pooler`, 사용자 `cosmoa_app_test` |
| 6 | `test_app_role_integration.py` | 앱 연결 검증 | 8-6 |

```cmd
conda activate tdenv
cd C:\Users\user\Desktop\COSMOA
python -m src.common.db_admin test-marker check
python -m src.common.db_admin app-role init-group --target test
python -m src.common.db_admin migrate --target test --dry-run
python -m src.common.db_admin migrate --target test
python -m src.common.db_admin app-role create-login --target test --role cosmoa_app_test
python -m src.common.db_admin app-role check --target test --role cosmoa_app_test
python -m unittest discover -s src/common/tests -p "test_app_role_integration.py"
python -m src.common.db_admin app-role whoami --target test
```

- `app-role whoami --target dev|test` (읽기만): **앱이 실제로 쓰는 주소**(dev: `DATABASE_URL`, test: `TEST_APP_DATABASE_URL`)로 접속해 접속 역할 이름, 풀링 여부, endpoint 고정값 일치, 테스트 표식 유무, 관리 속성·소유 테이블 없음, `cosmoa_app` 권한 상속을 보여 준다. 비밀값은 출력하지 않는다. 관리 역할 주소면 문제로 표시한다 (종료 코드 3). 관리용 변수가 없는 팀원 PC 에서도 동작한다. 관리 주소로 자동 대체하지 않는다.

- 모든 `app-role` 명령은 기존 대상 확인을 그대로 거친다: 운영 환경 거부, test 는 endpoint 고정값 + DB 표식(endpoint·branch) 일치, dev 는 `DEV_DATABASE_ENDPOINT_ID` 일치·테스트 표식 없음. PostgreSQL 16 미만이면 거부한다.
- 비밀번호: 명령 인자·마이그레이션·Git·로그에 넣지 않는다. 대화형 터미널에서 숨김 입력으로 받고(16자 이상), 역할 이름은 `sql.Identifier`, 비밀번호는 `sql.Literal` 로 한 문장에 넣어 TLS 연결로 한 번 보낸다 (Neon 이 평문만 받음 — PostgreSQL 문서도 평문 비밀번호는 서버 로그에 남을 수 있다고 경고한다. 서버 로그는 Neon 관리 영역). 실패 메시지는 서버 기본 메시지만 쓰고 비밀번호를 가린다.
- 이번 test 적용(2026-10-21)에서는 3 번을 대화형으로 입력하지 않고, 스크립트가 무작위 비밀번호(`secrets.token_urlsafe(32)`)를 만들어 같은 함수 `create_app_login()` 으로 역할을 만든 뒤 `.env` 의 `TEST_APP_DATABASE_URL` 에만 기록했다 (화면·보고서 출력 없음, 기존 `DATABASE_URL`·`DATABASE_URL_DIRECT`·`TEST_DATABASE_URL` 은 그대로). 그 뒤 3 번 명령을 다시 실행해 "이미 있음, 변경 없음" 을 확인했다.
- 재실행해도 권한이 늘거나 역할이 중복되지 않는다: 1·3 은 변경 없음, 2 는 적용할 파일 없음.
- 역할 삭제 명령은 두지 않는다. 개발자 이탈 시 절차는 8-10.

### 8-6. test 적용·검증 결과 (2026-10-21, PostgreSQL 18.6)

**적용 기록**: `init-group` 생성 → 재실행 변경 없음 → `migrate` 로 `0004` 적용 → `rollback-last` 로 되돌림(권한 0 확인) → 재적용 → 재실행 시 적용할 파일 없음 → `cosmoa_app_test` 생성 → `create-login` 재실행 변경 없음 → `app-role check` 통과(문제 0건).

**역할·권한 확인 (`app-role check`)**: 두 역할 모두 관리 속성 없음·소유 객체 0, 로그인 역할의 멤버십은 `cosmoa_app` 하나(INHERIT, SET 불가), 관리 역할·`neon_superuser`·`pg_*` 상속·전환 불가, 표·열·시퀀스 권한이 8-4 기준과 일치, 스키마·DB CREATE 없음, 실행 가능한 SECURITY DEFINER 함수 없음.

**앱 연결 검증 (`src/common/tests/test_app_role_integration.py`, 8개 통과)** — 관리 역할 연결은 대상 확인·역할 확인·테스트 사용자 3명 준비에만 썼고, 앱 요청은 `configure_business_db()` 로 넣은 **앱 역할 풀링 연결**로만 실행했다 (연결마다 `current_user` 기록 → 모두 `cosmoa_app_test`).

| 허용 동작 (test_client) | 결과 | 금지 동작 (앱 역할 연결, 항상 롤백) | 결과 |
|---|---|---|---|
| 풀링 접속 인증 (`current_user`·`session_user`·endpoint·test 표식) | 통과 | `INSERT users`, `UPDATE users.email/name` | 거부 (42501) |
| 로그인·세션 확인(`/api/csrf-token`)·본인 비밀번호 변경 → 이전 비밀번호 거부·새 비밀번호 로그인 | 통과 | `UPDATE customers.name`, `UPDATE projects.stage/archived_at`, `INSERT project_history`, `INSERT customer_contacts` | 거부 (42501) |
| 고객사 생성·검색, 프로젝트 생성·조회·목록 (신규 기본값 트리거) | 통과 | 저장본 `UPDATE`·`DELETE`, `TRUNCATE tab_versions/version_links`, `DELETE customers` | 거부 (42501), 행 수 변화 없음 |
| 저장본 추가 2건(번호 트리거)·목록·불러오기 | 통과 | `CREATE TABLE`, `CREATE SCHEMA`, `DROP TABLE`, `ALTER TABLE … DISABLE TRIGGER`, `COMMENT ON TABLE`, `CREATE OR REPLACE FUNCTION` | 거부 (42501), 트리거 그대로 켜짐 |
| 개발요청서 저장 + 반영 출처(같은 트랜잭션 트리거) | 통과 | `SET ROLE <관리 역할>`·`SET ROLE cosmoa_app`, `SET session_replication_role`, `CREATE ROLE`, `ALTER ROLE … CREATEROLE`, `GRANT cosmoa_app TO <관리 역할>` | 거부 (42501) |
| 최종본 지정·해제(순서 트리거)·이력 | 통과 | `SET ROLE neon_superuser` | 거부 (Neon 확장 XX000 "It is not allowed to change role to neon_superuser") |
| | | yoyo 표 조회 | 거부 (42501) |
| | | `GRANT SELECT ON users TO PUBLIC`, `GRANT INSERT ON customers TO <관리 역할>` | 경고만, 실제 부여 없음 (GRANT OPTION 없음) |
| | | 트리거 함수 직접 호출 | 거부 (0A000) |

**관리 명령 확인 (관리 역할, 항상 롤백 — 역할이 남지 않음)**: 표식 없는 같은 이름 역할·SET 가능 멤버십·CREATEDB 속성·멤버십 없음은 모두 문제로 판정(인수 안 함). `0004` 의 확인 블록은 역할 없음·표식 없음·LOGIN 켬에서 실패.

**회귀**: 기존 공통 통합 테스트(관리 역할 `TEST_DATABASE_URL`)와 규제·개발요청서·챗봇 테스트 통과.

### 8-7. 앱 역할의 한계 — DB 에 직접 접속하면 가능한 것

앱 역할은 DDL·소유자 권한으로부터 구조와 추가만 규칙을 보호하는 장치이고, 사용자 간 접근 통제 장치가 아니다. 앱 역할 주소를 가진 사람이 앱을 거치지 않고 DB 에 직접 접속하면 아래는 **막지 못한다** (test 에서 롤백 트랜잭션으로 확인). 서버(세션·API 검사)가 막는 부분이다.

- `users` 의 **모든 행 `password_hash` 조회** (로그인 확인에 `SELECT` 가 필요하고 열 단위로 나누지 않음).
- **모든 행의 `password_hash` 수정** — 열 권한은 행을 구분하지 않는다. "본인만" 은 서버 세션이 막는다 (행 보안 정책 RLS 는 쓰지 않음).
- 고객사·프로젝트·저장본 추가 시 `created_by` 에 **다른 사용자 id** 를 넣을 수 있다 (DB 는 작성자를 확인하지 않음, 서버가 세션 사용자로 정함).
- 추가만 표에 행을 계속 추가할 수 있다 (수정·삭제는 불가).
- 임시 테이블 생성 (PUBLIC 기본 `TEMP`).
- 자기 DB 비밀번호 변경 (`ALTER ROLE <자기> PASSWORD` 는 PostgreSQL 이 본인에게 허용 — 주소만 바뀌고 권한은 늘지 않음. 검증에서 실행하지 않음).

→ 앱 역할 주소도 **비밀값**이다. 개발자별 역할로 나누면 유출 시 그 역할만 폐기·재발급하면 된다.

### 8-8. dev 적용 결과와 팀원 추가 절차

**dev 적용 기록 (2026-10-21, PostgreSQL 18.6)** — 모든 명령은 dev 대상 확인(`DEV_DATABASE_ENDPOINT_ID` 일치, 테스트 표식 없음)을 통과한 뒤 실행했다.

| 순서 | 명령 | 결과 |
|---|---|---|
| 0 | 적용 전 확인 (읽기만) | 0001~0003 적용·0004 대기, `cosmoa_app`·`cosmoa_app_yjh` 없음 (test 의 `cosmoa_app_test` 도 dev 에 없음 → 브랜치별 역할 확인), PM 최초 계정 1개, 업무 표 0행 |
| 1 | `app-role init-group --target dev` | `cosmoa_app` 생성. 재실행 시 변경 없음 |
| 2 | `migrate --target dev --dry-run` → `migrate --target dev` | `0004_app_role_grants` 적용. 재실행 시 적용할 파일 없음 |
| 3 | `app-role check --target dev` | 통과 (문제 0건) |
| 4 | 로그인 역할 `cosmoa_app_yjh` 생성 | 대화형 입력이 없는 환경이라 test 와 같은 방식(무작위 `secrets.token_urlsafe(32)` → `create_app_login()`)으로 생성. 비밀번호는 명령행·로그·보고서·Git 에 남기지 않음. `create-login` 재실행 시 "이미 있음, 변경 없음" |
| 5 | 풀링 인증 확인 (`.env` 변경 전) | 새 역할 풀링 주소로 접속 → `current_user`·`session_user` = `cosmoa_app_yjh`, endpoint 고정값 일치, 테스트 표식 없음. dev 관리 명령 대상 확인도 통과 |
| 6 | 로컬 `.env` | **`DATABASE_URL` 한 줄만** 이 역할의 풀링 주소로 교체 (같은 파일에 직접 기록, 백업 파일 없음). 나머지 28개 변수·줄 수·줄바꿈 동일 확인 |
| 7 | `app-role check --target dev --role cosmoa_app_yjh`, `app-role whoami --target dev` | 통과 — 관리 속성 없음, 소유 객체 0, 멤버십 `cosmoa_app` 하나(SET 불가), 표·열·시퀀스 권한 기준 일치, 앱 주소의 접속 역할 `cosmoa_app_yjh` |
| 8 | 보존 확인 (읽기만) | PM 최초 계정 id·생성 시각·비밀번호 해시 지문 동일, 업무 표 8개 행 수·최대 id 동일 |
| 9 | 앱 실행 (`python app.py`) | `/login` 200·CSRF 필드 있음, 정적 자원 4개 200, 로그인 전 보호 화면 302, 없는 이메일 로그인 시도 401("이메일 또는 비밀번호…" — 앱 역할로 `users` 조회 성공, 503 아님). PM 계정 로그인은 사용자 본인이 확인 (비밀번호를 모르므로 재설정·우회하지 않음) → **사용자가 dev 앱 역할로 기존 계정 로그인·홈·개발요청서 화면 정상 동작을 직접 확인** |

- dev 에서는 파괴적 권한 시험·통합 테스트를 실행하지 않았다 (금지 동작 검증은 test 8-6).
- PUBLIC `TEMP`·접속 수 제한은 바꾸지 않았다.

**팀원 추가 절차 (미실행 — 팀원 역할·대시보드 계정 미생성)**

1. 역할 이름을 정한다: `cosmoa_app_<이니셜>` (공통 권한은 모두 `cosmoa_app` 에서 받음).
2. 공통 DB 담당이 대화형 터미널에서 (비밀번호 숨김 입력, 16자 이상 — dev 전용 값)
   ```cmd
   python -m src.common.db_admin app-role create-login --target dev --role cosmoa_app_<이니셜>
   python -m src.common.db_admin app-role check --target dev --role cosmoa_app_<이니셜>
   ```
3. 그 역할의 **dev 풀링 주소**를 팀원에게 별도 경로로 전달 → 팀원 `.env` 의 `DATABASE_URL`. 팀원은 `app-role whoami --target dev` 로 자기 역할로 접속하는지 확인한다.
4. 대시보드 계정은 따로 만든다: `create-user --target dev …` (8-1).
5. 관리 역할 비밀번호를 이미 다른 사람에게 준 적이 있으면 Neon 에서 재설정한다.

- production: 배포 준비 단계에서 같은 순서 (PM). `0004` 는 production 에도 `cosmoa_app` 이 먼저 있어야 적용된다.
- 미정: PUBLIC `TEMP` 회수 여부, 역할별 접속 수 제한(`CONNECTION LIMIT`), dev 앱 역할 화면 확인 범위 (자동 테스트는 dev 에 연결하지 않음).

### 8-9. 새 마이그레이션 이후 권한 부여

- 테이블·열을 만들거나 앱이 새로 쓰는 표가 생기는 **마이그레이션 파일에 `cosmoa_app` 에 대한 GRANT 를 함께 적는다** (같은 PR, DB 담당 검토). 필요한 열만, 필요한 동작만. 같은 PR 에서 `db_admin.APP_TABLE_PRIVILEGES`·`APP_UPDATE_COLUMNS` 도 고친다 (`app-role check` 기준).
- `ALTER DEFAULT PRIVILEGES … GRANT INSERT, UPDATE …` 처럼 앞으로 만들 모든 표에 한꺼번에 주는 방식은 쓰지 않는다 (추가만 표·관리 표에도 쓰기 권한이 생김).
- 이미 적용한 `0004` 는 고치지 않는다. 권한 추가·회수는 새 파일로 한다.
- 기능별로 이후 필요한 권한 (그 기능 PR 에서 추가 — **지금 미리 주지 않음**)
  - 프로젝트 단계·상태·납기 변경 API: `UPDATE (stage, state, due_date) ON projects`, `INSERT ON project_history`
  - 고객사 수정·보관: `UPDATE (name, archived_at) ON customers` (프로젝트 보관도 같은 방식)
  - 고객사 담당자: `INSERT`, 필요한 열 `UPDATE` ON `customer_contacts`
  - 규제 메모(`regulatory_notes`, 수정 가능 표): 그 표 설계에 맞춘 INSERT·열 UPDATE (DELETE 여부는 미정)

### 8-10. 개발자 이탈 시 로그인 역할 정리 절차 (문서만 — 아직 실행한 적 없음)

공통 DB 담당이 **관리 역할**로 해당 브랜치(dev)에서 실행한다 (Neon SQL Editor 등). 단계마다 결과를 확인한 뒤 다음으로 간다. `<역할>` 은 `cosmoa_app_<이니셜>`.

1. **로그인 차단** — 새 접속을 막는다. 비밀번호는 바꾸지 않아도 된다.
   ```sql
   ALTER ROLE <역할> NOLOGIN;
   ```
2. **기존 연결 종료** — 풀러(PgBouncer)가 서버 연결을 잠시 들고 있을 수 있으므로 0행이 될 때까지 확인한다.
   ```sql
   SELECT pid, backend_start, state FROM pg_stat_activity WHERE usename = '<역할>';
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '<역할>';
   ```
   권한이 부족하다는 오류가 나면 Neon 콘솔에서 해당 브랜치 compute 를 재시작해 연결을 끊는다 (관리 역할의 `pg_signal_backend` 보유 여부는 실행 전 확인).
3. **권한 회수** — 공통 권한 멤버십을 뺀다. 이후 `app-role check --role <역할>` 은 "멤버십 없음" 을 문제로 보고한다 (정상).
   ```sql
   REVOKE cosmoa_app FROM <역할>;
   ```
4. **소유 객체·남은 권한 확인** — 둘 다 0 이어야 한다. 앱 역할은 CREATE 권한이 없으므로 정상이면 0. 0 이 아니면 **삭제하지 말고** 무엇인지 확인한다 (`REASSIGN OWNED` 여부는 공통 DB 담당이 판단).
   ```sql
   SELECT count(*) AS owned FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass AND refobjid = '<역할>'::regrole AND deptype = 'o';
   SELECT count(*) AS other FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass AND refobjid = '<역할>'::regrole AND deptype <> 'o';
   ```
5. **역할 정리**
   ```sql
   DROP ROLE <역할>;
   ```
6. **대시보드 계정은 별개다** (8-1). `users` 행은 작성자 기록이 참조하므로 지우지 않는다. 계정 비활성화 기능은 아직 없으므로, 로그인을 막으려면 `set-password --target dev --email <이메일>` 로 무작위 비밀번호를 설정한다 (기존 로그인 세션도 끝남). 비활성화 기능은 후속.
7. 그 개발자의 로컬 `.env` 주소는 더 이상 접속되지 않는다. 날짜·역할 이름·실행자를 작업 기록에 남긴다.
