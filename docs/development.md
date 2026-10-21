# COSMOA 재개발 개발 안내 (PM)

> **상태: 재개발 진행 중 — 1단계(공통 DB 기반)·로그인 전환·2단계(공통 저장 엔진·API)·3-1단계(고객사·프로젝트 생성·조회, 개발요청서 프로젝트 선택)·3-2단계(개발요청서 FIX 필드·저장 계약 v1) 완료. 저장·불러오기·최종본 화면 연결은 아직 없음.**
> **팀 개발 시작**: 공통 규칙 9장, 구현 현황·인계 10장, 시작 순서 [팀원 시작 안내](team_onboarding.md).
> **구현됨**: 업무 DB 연결 모듈(`src/common/db.py`), 첫 마이그레이션(`db/migrations/0001_core.sql`, test·dev 적용), 테스트 DB 식별 장치, 관리 명령(`src/common/db_admin.py`), 업무 DB 테스트. (5장)
> **로그인 전환 완료**: 로그인 계정은 업무 DB `users`(PostgreSQL). SQLite 계정·데모 계정 자동 생성은 제거. (2-1, 5-2)
> **2단계 완료**: `tab_versions`·`final_history`·`version_links`(0003, test·dev 적용), 저장 엔진(`src/common/versions*.py`, `payloads.py`), 공통 API — [API 계약](api_contract.md). 화면 연결은 아직 없음.
> **3-2단계 완료**: 개발요청서 FIX 필드(목표 가격대 금액·통화, SPF/PA, 컨셉 원료 필수·선호·함유 필수·효능 태그, R&D 확인 요청사항, 용기 참고값, 스킨케어 세부 유형, 점도 선택+서술)와 저장 계약 v1 서버 검증(`fully_validated: true`)·화면 payload. 로그인 폼 CSRF. 저장 버튼 연결 전. ([데이터 계약](data_contract.md) 4장)
> **3-1단계 완료**: 고객사·프로젝트 생성·조회 API(`src/common/projects_api.py`, [API 계약](api_contract.md) 5장), 개발요청서 상단 프로젝트 선택(고객사 → 프로젝트, 없으면 생성). 스키마 변경 없음.
> **아직 아님**: 저장 버튼·불러오기·최종본 화면 연결(3단계 다음 작업), 고객사·프로젝트 수정·보관 화면, **production 적용·배포 준비**(production 브랜치에 마이그레이션·계정 없음). `구현 예정`으로 표시한 항목은 현재 저장소에서 동작하지 않는다.
> 현재 실제로 동작하는 화면 실행 방법은 [README](../README.md)를 따른다.
>
> 함께 보는 문서
> - [DB 규칙](db_rules.md) — 테이블 목록·구현 단계, 저장·최종본·반영 출처·동시 작업 규칙, 파일 제외 정책, 마이그레이션 규칙
> - [데이터 계약](data_contract.md) — 고객사·프로젝트 필드, `tab_versions`·payload 구조, 개발요청서 저장 JSON 예시

---

## 0. 근거와 표기

### 0-1. 적용 우선순위

| 순위 | 근거 | 다루는 것 |
|---|---|---|
| 1 | **10.19 회의 수정안 (최신 FIX)** | 최신 업무 요구사항 |
| 2 | PM 공통 개발 기준 (이 문서·`db_rules.md`·`data_contract.md` 의 "확정(개발기준)") | 구현 방식과 보완 규칙 |
| 3 | DB 최종안 팀개발용 (기본 설계, 18개 테이블안) | 기본 DB 설계 |
| 4 | 기존 문서·코드 | 현재 구현 |

- 원본 회의록·DB 최종안은 PM 이 보관하며 **저장소에 포함하지 않는다.** 팀원이 개발에 필요한 확정 내용은 모두 이 `docs/` 문서들에 옮겨 적었다.
- FIX 와 충돌하지 않는 기존 설계는 유지한다.

### 0-2. 표기

| 표기 | 뜻 |
|---|---|
| **확정(FIX)** | 10.19 수정안에 명시된 요구사항 |
| **확정(개발기준)** | PM 이 정한 구현 방식·규칙 |
| **기본설계** | DB 최종안의 설계. FIX·개발기준과 충돌하지 않아 유지 |
| **제안** | 구현을 위한 제안. 구현 전 PM 확인 후 확정 |
| **미정** | 아직 정해지지 않음. 구현 중 임의로 확정하지 않는다 |

---

## 1. 재개발 목표 — 전체 개발 범위

### 1-1. 공통 원칙 — 확정(개발기준)

1. 기존 Flask 서버와 화면 기능을 유지한다. 기존 페이지·API URL 과 공통 레이아웃은 바꾸지 않는다.
2. 사용자·고객사·프로젝트·탭 저장본을 **업무 DB(Neon PostgreSQL)** 에서 관리한다.
3. 네 탭(`regulatory`, `margin`, `simulation`, `requisition`)이 함께 쓰는 **공통 저장·불러오기·버전·최종본** 기능을 만든다.
4. 다른 탭 저장본의 내용을 실제 반영해 저장할 때 **출처와 당시 값**을 남긴다.
5. 홈 캐시·식약처 DB 는 SQLite 로 분리해 유지한다.

### 1-2. 영역별 요구사항 — 확정(FIX)

**프로젝트**
- 하나의 프로젝트 = **단일 제품**.
- 단계: `제안 → 개발 → 발주 → 생산 → 선적 → 완료`.
- 상태: `진행 / 홀드 / 드롭`. 홀드·드롭은 **사유를 남긴다.** 홀드는 다시 진행할 수 있다.
- 일정의 핵심은 **납기일**. 납기일 D-day 중심으로 일정을 보여준다.
- 연락 내역을 프로젝트별로 한 곳에 모은다.
- 각 탭에서 사용자가 지정한 **최종본**이 프로젝트 화면에 자동으로 표시된다.
- 샘플 현황: 바이어에게 요청받은 수량, 보낸 수량, 날짜 정도를 기입한다.

**홈**
- 사용자 맞춤형 위젯: 오늘 챙길 것, 프로젝트 현황, **이번 주 일정**, 환율, 바이어 현지시각, 화장품 뉴스 등. 사용자가 배치·설정한다.
- 수출입 통계는 홈에서 **제외**. 환율은 주요 3개국 정도. 뉴스는 매체별 탭 없이 한 목록으로 통합.

**개발요청서**
- 목표 가격대 **복수 선택** (예: 1,300·1,500·1,800원). 가격대별 샘플을 동시에 요청할 수 있다.
- 개발요청서 이름(파일명)을 붙이고 **버전별로 저장**한다. 불러와 수정한 뒤 **새 버전으로 저장**한다.
- **문서 버전과 샘플 개발 차수는 따로 관리**한다. 요청서 저장 시 차수를 자동으로 올리지 않는다. 차수는 **연구소에 신규·수정 샘플을 의뢰하는 건** 기준으로만 매긴다. 같은 차수 안에 여러 가격대 샘플이 있을 수 있고, 개별 샘플은 **Lab No.** 로 구분한다.
- 최종본으로 지정하면 개발 진행 현황에 ★ 로 표시하고, 다른 탭에서 불러올 때 **기본값으로 선택**된다.
- 바이어 피드백: 샘플(Lab No.)별 바이어 의견, 연구소 전달용 요청 내용, 바이어 반응(선호·보통·불만)을 기록한다. 하단에 **차수별 이력 타임라인**을 두고 각 차수 샘플별 피드백과 관련 요청서 버전을 연결해 표시한다. 중복 요청 시 경고한다.
- 차수 반복 시 누락 방지: **SPF/PA 칸** 추가, 컨셉 원료를 **필수/선호로 분리**하고 **함유 필수 여부·효능 태그** 기록, 이전 차수에 있던 값이 빠지면 경고.
- 세부 수정: 제품 유형 중 스킨케어를 토너·스킨·세럼·앰플·크림·로션으로 세분화. 점도는 서술형 작성 + 드롭다운.
- 원가·마진, 인허가 규제 저장본 불러오기: 기본 노출 값은 **각 탭의 최종본**. 같은 프로젝트의 다른 저장본도 선택해 불러올 수 있다. 불러온 저장본은 옆 패널에 요약 표시.

**탭 간 반영 (→ 개발요청서)**

| 출처 탭 | 반영 내용 | 반영 위치 | 반영하지 않는 것 |
|---|---|---|---|
| 원가·마진 | 체크한 **사양 변경(VE)** 내용 (변경 사양·요청 사항 문구) | `03 원료 요구사항 – 기타사항` | **단가·마진 수치** |
| 인허가 규제 | 성분·국가별 규제 결과와 담당자 메모 중 선택한 항목 | `R&D 확인 요청사항` | 조회 결과 전체 |
| AI 제형 모델링 | 예상 질감·예측 점도 / 컨셉원료 코멘트 / 용기 적합성(대체 권장 용기, 참고값) | 02 텍스처·점도 칸 / 03 컨셉 원료 / 용기 칸 | **배합 조절 수치(처방 영역)** |

- 원가·마진 흐름: 마진 탭에서 시뮬레이션 후 [저장] → 개발요청서에서 이전 버전 불러오기 → 상단 **'원료 대체 변동 사항 감지 배너'** → [변경사항 반영하여 수정] → `03 원료 요구사항 – 기타사항` 에 VE 반영 문구 자동 추가 → 새 버전 저장·PDF 발행. 반영 여부는 마진 탭에서 **체크한 사양 변경 값**으로 판단한다.
  - 문구 예: `[견적 사양 변경 (VE) 반영] 변경 사양: … / 요청 사항: …`
- 인허가 규제: 저장된 확인사항 중 필요한 항목을 선택해 `R&D 확인 요청사항` 에 반영한다. **이후 메모를 수정해도 이미 전달한 개발요청서 내용은 유지**된다. 개발요청서 ↔ 인허가 규제 **양방향** 불러오기.

**인허가 규제**
- 조회 내역 전체를 자동 저장하지 않고, **사용자가 필요한 성분·규제 정보를 선택해 프로젝트에 저장**한다.
- 선택한 성분 규제 정보에 **확인사항 메모**를 자유롭게 작성한다. 조회 결과와 메모는 구분한다. **조회 결과 없이 메모만** 작성할 수도 있다. (예: 비건 회사, 할랄 국가)
- 기록 항목: 연결 프로젝트, 선택한 성분명, 대상 국가, 선택한 규제 내용, 조회 출처 및 조회일, 담당자 메모, 작성자 및 작성일. 필요하면 관련 개발요청서 또는 샘플 수정 요청과 연결.

**AI 제형 모델링** (개인적인 사전 검토 용도)
- 컨셉원료 코멘트 창: 서술형 작성 + 자주 쓰는 컨셉원료 예시 클릭(또는 드롭다운) + 원료 정보·특성·효능 표시. 구현 방식(드롭다운 확인 후 AI 검색 / 기능 키워드로 AI 추천)은 **미정** (직접 작업해 본 뒤 선택).
- 모델링에서 저장한 제형·코멘트를 개발요청서로 연동한다.
- 기존 개발요청서를 모델링 탭으로 **불러와** 제형·용기 적합성을 시뮬레이션한다.
- 기록 항목: 개발요청서 번호(제목), 예측 점도, 배합 조절 항목과 수치, 총 배합 비율, 예상 질감, 상대 유동성, 용기 적합성(대체 권장 용기 포함), 컨셉원료 코멘트, 바이어 제안 가이드(R&D 연구소 리포트, 바이어 세일즈 피칭).

**원가·마진**
- [저장] 시 탭 내 모든 요소를 저장한다.
- 원료 등급 대체 선택 시 개발요청서 갱신·연동 (위 표).
- 새 버전 저장 후 PDF 발행. 그룹웨어 연동은 **미정** (FIX 에 "추후 ?" 로만 기재).

### 1-3. 구현 원칙 보완 — 확정(개발기준)

- 저장된 개발요청서는 모델링 탭에서 **구조화된 저장 데이터(payload)** 로 불러온다. PDF 를 다시 업로드해 추출하는 과정을 기본 경로로 삼지 않는다.
- 최종본 지정은 **발송 사실과 다르다.** 현재 연구소·고객에게 문서를 발송한 기록은 구현 범위에 없으므로 "발송 이력을 관리한다"고 표시하지 않는다. (샘플 실물 발송 수량·날짜 기록은 샘플 현황 기능으로 별도)
- 이번 주 일정 위젯은 요구사항에 포함한다. 납기일 외 일정을 직접 등록하는 기능을 둘지에 따라 별도 `project_events` 테이블 필요 여부를 판단한다. (**미정**)
- 규제 확인사항은 수정 가능한 프로젝트별 메모(`regulatory_notes`)로 관리한다. 규제 탭 저장본을 따로 만들지 않아도 고른 메모를 개발요청서에 반영할 수 있고, 반영 기록은 요청서 저장 시 `version_links` 에 남긴다. (`db_rules.md` 5-1)

---

## 2. 구현 단계

| 단계 | 내용 | 주요 테이블 | 범위 |
|---|---|---|---|
| 0 | 개발 기준·문서 정리 | – | 완료 |
| 1 | DB 연결·마이그레이션 도구, 공통 기반 | `users`, `customers`, `customer_contacts`, `projects`, `project_history` | **구현 완료** — 테이블은 test·dev 적용. 화면·로그인 연결은 하지 않음 (2-1) |
| 2 | 공통 저장 엔진: 저장(새 버전)·목록·불러오기·최종본 지정/변경/해제·이력, 변경 금지 트리거 | `tab_versions`, `final_history`, `version_links`(구조) | **구현 완료** — `0003_versioning` test·dev 적용, API·테스트. 화면 연결 없음 |
| 3 | **개발요청서 한 탭에 먼저 연결해 검증** | (위 테이블 사용) | **첫 구현** — 3-1(고객사·프로젝트 생성·조회 API, 프로젝트 선택 화면)·3-2(FIX 필드·저장 계약 v1) 구현 완료. 저장·불러오기·최종본 버튼 연결은 다음 |
| 4 | 나머지 탭(규제·마진·모델링) 연결 + 보조 테이블 | `requisition_ingredients`, `cost_spec_changes`, `regulatory_notes`, `version_links.source_note_id` | 후속 |
| 5 | 개발 차수·샘플·피드백 | `dev_rounds`, `sample_requests`, `lab_samples`, `sample_shipments`, `sample_feedback`, `feedback_version_links` | 후속 |
| 6 | 탭 간 반영 (감지 배너, 규제 ↔ 요청서, 모델링 ↔ 요청서, 마진 → 요청서) | `version_links` 실사용 | 후속 |
| 7 | 프로젝트 화면 마무리·홈 위젯 | `contact_logs`, `users.home_widgets`, (`project_events` 필요 시) | 후속 |

- 기본설계는 2단계 이후 네 탭을 동시에 연결하는 순서였으나, **확정(개발기준)** 에 따라 개발요청서 한 탭으로 먼저 검증한 뒤 나머지 탭을 연결한다. 공통 구조와 API 는 처음부터 네 탭을 받는다.
- **확정(개발기준)** 첫 구현은 프로젝트·탭별 **하나의 버전 흐름**으로 진행한다. 같은 프로젝트·탭에 저장본(버전)은 여러 개 쌓이지만, 그 위에 여러 문서를 따로 묶는 기능(예: 한 프로젝트의 개발요청서 A·B 를 별도 시리즈로 관리)은 만들지 않는다. 저장본 `title` 은 각 버전의 이름이며 묶음 기준이 아니다.
- **확정(개발기준)** 개발요청서의 FIX 필드 변경(목표 가격대 복수, SPF/PA, 컨셉 원료 구조, R&D 확인 요청사항, 용기 칸, 제품 유형 세분화, 점도 드롭다운)은 **3단계에 포함**한다. 3단계 전에는 개발요청서 저장본이 없으므로 FIX 구조를 첫 `schema_version = 1` 로 정하고, v1→v2 변환은 만들지 않는다. (`data_contract.md` 4장)

### 2-1. 1단계 구현 결과와 다음 단계

**구현 완료 (1단계)**

| 항목 | 내용 |
|---|---|
| 연결 모듈 `src/common/db.py` | psycopg 3 연결 풀(`psycopg_pool`), `dict_row`, `Database.transaction()` (정상 종료 커밋·예외 롤백). import 만으로 접속하지 않음. 접속 주소는 생성자로 주입 (`Database.from_env("DATABASE_URL")` / 테스트는 `"TEST_DATABASE_URL"`). 오류 메시지의 비밀번호·주소·호스트를 가림 |
| 마이그레이션 `db/migrations/0001_core.sql` | 1단계 5개 테이블, CHECK·FK, `project_history` 추가만 트리거, 고객사·프로젝트 삭제 금지(보관), 프로젝트 변경 시 같은 트랜잭션 이력 필수(커밋 시 검사). 되돌리기 `0001_core.rollback.sql` (테스트 DB 확인용) |
| 마이그레이션 `db/migrations/0002_project_rules.sql` | 이력의 트랜잭션 식별을 `project_history.xact_id`(`pg_current_xact_id()`, 서버 기록)로 교체, 신규 프로젝트는 `proposal`/`active` 로만 생성 |
| 프로젝트 도우미 `src/common/projects.py` | `create_project()` — 기본 단계·상태로 생성(납기일 입력 가능). `change_project()` — 행 잠금 → 수정 → 항목별 이력 추가 (같은 트랜잭션) |
| 관리 명령 `src/common/db_admin.py` | 테스트 DB 표식 설정·확인, 마이그레이션 상태·적용·되돌리기(테스트 전용), 최초 계정 생성 (5장) |
| 테스트 `src/common/tests/` | 단위(접속 없음)·통합(테스트 DB 전용)·로그인 통합(test DB + Flask test_client) (5-4) |
| **로그인 전환** `src/common/auth.py`, `app.py` | 아래 "로그인 전환 내용" |

**로그인 전환 내용 — 구현됨**

- 계정 조회·비밀번호 확인은 업무 DB `users` + werkzeug `check_password_hash`. 로그인 화면·URL·`safe_next` 는 그대로. SQLite `users` 자동 생성·데모 계정 자동 생성 제거. **업무 DB 연결 실패 시 SQLite 로 대체하지 않는다.**
- DB 장애·미설정은 `AuthUnavailable` → 로그인 화면/페이지는 503 + "일시적으로 연결할 수 없습니다", `/api/` 는 JSON 503. 비밀번호 오류(401)와 구분하고 접속 정보는 응답·로그에 넣지 않는다.
- 세션 형식 v2: `session["auth"] = {v: 2, uid, remember, at, csrf, pw}` 만 저장 (해시·이메일 등 사용자 정보는 세션에 두지 않음). `pw` 는 비밀번호 해시를 앱 비밀키로 HMAC 한 지문 앞부분이다 — 비밀번호가 바뀌면(본인 변경·관리 명령 재설정) 지문이 달라져 **다른 기기·브라우저의 기존 세션은 다음 요청에서 로그아웃**된다. 본인이 화면에서 바꾼 브라우저는 세션을 새로 만들어(CSRF 토큰 교체) 로그인을 이어 간다. `pw` 가 없는 이전 세션(이 기능 전 로그인)도 한 번 다시 로그인한다. 세션 쿠키 방식이라 서버에서 세션을 개별 목록으로 끊는 기능은 없다. 요청마다 DB 에서 사용자 존재를 확인하되 **요청당 1번**(`flask.g` 캐시). DB 에 없는 사용자·예전 SQLite 세션(`session["user"]`)·형식이 다른 세션은 지우고 다시 로그인.
- `@login_required`: 페이지는 `/login?next=…` 이동, `/api/`·JSON 요청은 JSON 401.
- `app.py`: 시작 시 `Database.from_env("DATABASE_URL")` 객체만 만들고(접속은 첫 로그인 때, 풀은 프로세스에 하나), `configure_business_db(db)` 로 테스트가 test DB 를 주입. 업무 테이블 생성·마이그레이션은 하지 않는다. 홈 캐시는 `HOME_CACHE_DB_PATH`.
- `app.py` import 는 dev DB 에 접속하지 않고, 외부 데이터 갱신·백그라운드 작업도 시작하지 않는다 (홈 갱신은 홈 요청 때 시작 — 기존과 같음).
- 기능 테스트용 `src/common/testing.py` `login_as()` — 메모리 사용자로 세션 v2 를 만들어 dev DB 에 접속하지 않는다. 규제·개발요청서·챗봇 테스트의 예전 `session["user"]` 주입을 이것으로 바꿨다 (각 1곳).
- 로컬 SQLite 계정 이전: 이 PC 에는 기존 `instance/cosmoa.db` 가 없었다(전환 전 확인). 자동 이전·삭제는 하지 않는다. 다른 팀원 PC 나 배포 환경의 이전 필요 여부는 별도 확인 (8장).

**아직 하지 않은 것 (다음 단계)**

- **production 적용·배포 준비**: production 브랜치 마이그레이션 절차(PM), 배포 환경변수, 운영 첫 계정, `docs/deploy_render.md` 갱신 (현재 "갱신 전" 표시)
- ~~팀원 계정 추가 방법~~ → 구현됨: `create-user` 관리 명령(5-2), 본인 비밀번호 변경 화면 `/account/password`
- ~~고객사·프로젝트 생성·조회 API·선택 화면~~ → **3-1 구현 완료** (아래 2-2)
- 3단계 나머지: 개발요청서 화면에 저장·불러오기·최종본 연결 (`Common.api` 사용, 요청서의 연결 프로젝트로 저장), 개발요청서 v1 세부 필드 확정
- 고객사·프로젝트 수정·보관 API·화면, 프로젝트 화면 (7단계)

### 2-1-1. 3-1단계 구현 결과 — 고객사·프로젝트 생성·조회, 개발요청서 프로젝트 선택

| 항목 | 내용 |
|---|---|
| API `src/common/projects_api.py` | 고객사 목록(검색·페이지)·생성·조회, 고객사별 프로젝트 목록·생성, 프로젝트 조회. 인증·CSRF·오류 형식은 저장 API 와 공유(`versions_api.apply_api_policy`). [API 계약](api_contract.md) 5장 |
| 업무 규칙 `src/common/projects_service.py` | 입력 검증(이름 1~200자·제어 문자 불가, 납기 `YYYY-MM-DD`/null), 고객사 공유 잠금 후 존재·보관 확인, 페이지 크기 최대 100. 프로젝트 생성은 `create_project()` (proposal/active 시작) |
| SQL `src/common/projects.py` | `create_customer()`, 고객사·프로젝트 조회 함수 추가. 기존 `create_project()`·`change_project()` 유지 |
| 공통 클라이언트 `src/common/common.js` | `Common.api()` — JSON 요청, CSRF 토큰 자동·만료 시 1회 재시도 |
| 개발요청서 화면 `src/05_requisition/requisition.*` | 상단 ‘연결 프로젝트’ 카드(고객사 검색·선택 → 프로젝트 선택, 새 고객사·새 프로젝트), 문서 정보 패널의 연결 프로젝트. 작성 중 변경 시 확인·초기화 규칙 ([API 계약](api_contract.md) 5-3). 기존 작성·변환·수정·PDF 흐름 유지 |
| 저장 엔진 `src/common/versions.py` | DB 오류 → API 오류 변환을 `business_transaction()` 으로 분리해 고객사·프로젝트 API 와 함께 사용 (동작 변화 없음) |
| 스키마 | **변경 없음** — 0001·0002 의 `customers`·`projects` 로 충분. 새 마이그레이션 없음 |

### 2-1-2. 3-2단계 구현 결과 — 개발요청서 FIX 필드·저장 계약 v1

| 항목 | 내용 |
|---|---|
| 필드 정의 `src/05_requisition/schema.py` | 화면·자동변환·PDF·저장 계약이 함께 쓰는 칸·선택값·빈 구조. FIX 칸 추가, 점도 선택값은 비워 둠(미정) |
| 저장 계약 `src/05_requisition/contract.py` | v1 서버 검증(필수 키·필수값·빈 값·자료형·허용값·모르는 키). `payloads.py` 의 requisition v1 을 `full` 로 연결 |
| 예시 `db/schemas/requisition.v1.example.json` | 문서 예시(데이터 계약 4-2)와 같은 내용, 서버 검증 통과 |
| 저장 엔진 `versions.py`·`versions_repo.py` | 개발요청서 v1 은 `context.project_id`·`customer_id` 를 저장 대상 프로젝트와 대조, 이름 사본은 DB 값으로 저장 |
| 자동변환 `service.py` | 결과를 직접 작성과 같은 문서 구조로. 세부 유형·SPF·PA 추출(근거 있을 때만), 목표 가격대 금액은 채우지 않고 이전 low/mid/high 는 참고로만, 컨셉 원료는 이전 목록에서 kind 만 |
| 화면 `requisition.js`·`requisition_payload.js`·`.html`·`.css` | FIX 칸 편집·결과·PDF, 고객사 칸은 연결 프로젝트 기준(입력칸 아님), 저장 전 표시(클라이언트 버전·문서 번호 제거), 저장용 payload 생성(요청서의 연결 프로젝트 id) |
| 로그인 폼 CSRF `auth.py`·`login.html`·`app.py` | 로그인 전 세션 토큰 + hidden 필드, 비밀번호 확인 전 검사 |
| `Common.api` 재전송 규칙 | CSRF 거부(403 `csrf_failed`)만 1회 재전송 — 테스트로 고정 (`test_common_js.py`) |
| 스키마(DB) | 변경 없음 |

### 2-2. 첫 구현 범위에서 하지 않는 것

- 규제·마진·모델링 화면에 저장 기능 연결 (4단계)
- 개발 차수·샘플·피드백 (5단계)
- 원본 업로드 파일·참고자료 파일 본문의 영구 저장 (정책상 하지 않음)
- 같은 프로젝트·탭 안에서 여러 문서를 별도로 묶는 기능 (하나의 버전 흐름만)
- 문서 발송 기록, 그룹웨어 연동
- 실제 운영 권한 체계
- 기존 SQLite 계정 이전 (필요 여부 별도 검토)

---

## 3. 현재 구현과 계획

| 영역 | 현재 구현 (동작 중) | 재개발 계획 (구현 예정) |
|---|---|---|
| 웹 서버 | Flask, Render 에서 Gunicorn | 변경 없음 |
| DB 접근 | SQL 직접 작성 (`sqlite3`) | SQL 직접 작성 유지 (psycopg 3). ORM 사용 안 함 |
| 계정 `users` | **업무 DB `users`(PostgreSQL)로 로그인 — 전환 완료.** (예전: SQLite `instance/cosmoa.db`, 시작 시 테이블·데모 계정 생성 → 제거) | 최초 계정은 관리 명령 `create-first-user` 로만 만든다(시스템 작업, `created_by` NULL). 서버 시작 시 데모 계정을 자동 생성하지 않는다. production 은 미적용 |
| 고객사·프로젝트 | **업무 DB — 생성·조회 API, 개발요청서 프로젝트 선택 (3-1)** | 수정·보관, 프로젝트 화면 (7단계) |
| 탭 저장본 | 없음 (개발요청서·마진은 페이지 메모리) | 업무 DB `tab_versions` (추가만) |
| 개발요청서 `version` | 화면에서 수정 시 1씩 증가 | 서버 `version_no` 기준으로 맞춤 (`data_contract.md` 7장) |
| 홈 캐시 | SQLite `HOME_CACHE_DB_PATH` (기본 `instance/cosmoa.db`) — 분리 완료 | 변경 없음 |
| 식약처 규제 DB | 읽기 전용 SQLite | 변경 없음 |
| 챗봇 서버 캐시 | `CHATBOT_DB_PATH` | 변경 없음 |
| 테이블 생성·변경 | 서버 시작 시 `CREATE TABLE IF NOT EXISTS` | 업무 테이블은 **yoyo 마이그레이션으로만** |

---

## 4. 공통 환경 — 확정(개발기준)

### 4-1. 구성

| 항목 | 기준 |
|---|---|
| 업무 DB | Neon PostgreSQL |
| 연결 | psycopg 3 + psycopg_pool, `dict_row`, SQL 직접 작성, 매개변수(`%s`) 바인딩 — `src/common/db.py` |
| 마이그레이션 | yoyo-migrations, 파일 위치 `db/migrations/`. psycopg 3 백엔드 주소 형식은 `postgresql+psycopg://` (yoyo 공식 문서·9.0.0 확인). 관리 명령이 `.env` 원본 주소를 실행 중에만 이 형식으로 바꿔 쓴다 |
| payload 형식 정의 | `db/schemas/<탭>.v<번호>.json` (JSON Schema, 기본설계) — 구현 예정 |
| 시드 데이터 | `db/seed.sql` (기본설계: 예시 고객사·프로젝트·저장본) — 구현 예정, 테스트·개발 DB 전용 |
| 시간 | DB 는 `timestamptz`(UTC 기준 저장), 화면에서 한국·바이어 현지 시각으로 변환 (기본설계) |
| Python | 3.10 (conda `tdenv`, 기존과 동일) |
| PostgreSQL | Neon PostgreSQL 18, AWS Oregon (us-west-2) |

### 4-2. 환경변수

실제 값은 본인 `.env` 또는 배포 환경변수에만 넣는다. **문서·코드·`.env.example`·커밋·PR·로그에 실제 접속정보를 쓰지 않는다.**

| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | 애플리케이션용 연결 (Neon 풀링 연결). **앱 로그인 역할**(`cosmoa_app_<이니셜>`) 주소 ([DB 규칙](db_rules.md) 8장). 확인: `app-role whoami --target dev` |
| `DATABASE_URL_DIRECT` | 마이그레이션·관리 명령용 직접 연결 (관리 역할) |
| `TEST_DATABASE_URL` | 테스트 전용 직접 연결(test 브랜치, 관리 역할). 테스트 스키마 준비와 테스트 실행에 모두 이 값만 사용 |
| `TEST_APP_DATABASE_URL` | (공통 DB 담당만) test 브랜치 **앱 로그인 역할**(`cosmoa_app_test`) 풀링 연결. 앱 역할 검증 테스트(`test_app_role_integration.py`)만 사용. 같은 test endpoint·DB 의 `-pooler` 주소이고 사용자가 `cosmoa_app_…` 이어야 함 |
| `TEST_DATABASE_ENDPOINT_ID` | 테스트로 허용할 Neon endpoint id (`ep-…`, `TEST_DATABASE_URL` 호스트의 첫 부분). 테스트 DB 식별에 사용 |
| `DEV_DATABASE_ENDPOINT_ID` | 개발용으로 허용할 Neon endpoint id (`ep-…`, `DATABASE_URL_DIRECT` 호스트의 첫 부분). `--target dev` 관리 명령이 확인 |
| `HOME_CACHE_DB_PATH` | 홈 캐시 SQLite 경로. 생략 시 기존 `instance/cosmoa.db`. 상대 경로는 저장소 루트 기준 |

- **로컬 실행(로그인)에 필요한 최소 값**: `DATABASE_URL`(dev 풀링 주소). 관리 명령은 `DATABASE_URL_DIRECT`·`DEV_DATABASE_ENDPOINT_ID` 도 필요하다. `COSMOA_DEMO_*` 는 더 이상 쓰지 않는다.

- **`DATABASE_URL` 과 `DATABASE_URL_DIRECT` 는 같은 환경의 같은 DB 를 가리켜야 한다.** (연결 방식만 풀링/직접으로 다름) 개발 환경의 `DATABASE_URL` 과 운영 환경의 `DATABASE_URL_DIRECT` 를 섞어 쓰지 않는다.
- 테스트 스키마 준비와 테스트 실행은 **`TEST_DATABASE_URL` 만 대상**으로 한다. 값이 없으면 업무 DB 테스트를 실행하지 않으며, **`DATABASE_URL`·`DATABASE_URL_DIRECT` 로 자동 대체하지 않는다.**
- **테스트 DB 보호 — 확정(개발기준)**: 연결 주소 문자열이 개발·운영 주소와 다른지만으로 테스트 DB 라고 판단하지 않는다. 풀링 주소와 직접 연결 주소처럼 문자열이 달라도 같은 DB 를 가리킬 수 있다.
  - 스키마 초기화·마이그레이션·테스트 전에 `TEST_DATABASE_URL` 로 **접속해 DB 가 돌려주는 식별 정보**로 테스트 대상인지 확인한다.
  - 테스트 대상임을 확인할 수 없으면(식별 정보 없음·조회 실패·값 불일치) 초기화와 데이터 정리를 **거부**하고 중단한다.
  - **식별 방법 — 확정(개발기준), 구현됨** (`src/common/db_admin.py`). 아래를 **모두** 통과해야 마이그레이션·되돌리기·테스트를 진행한다.
    1. `TEST_DATABASE_ENDPOINT_ID` 가 설정되어 있고, `TEST_DATABASE_URL` 호스트의 endpoint 가 이 값과 같다. 직접 연결 주소다.
    2. `TEST_DATABASE_URL` 의 endpoint 가 `DATABASE_URL`·`DATABASE_URL_DIRECT` 의 endpoint 와 다르다.
    3. 접속 후 DB 가 보고하는 `neon.endpoint_id` 가 허용 값과 같다.
    4. DB 내부 표식(`COMMENT ON DATABASE` 값 `cosmoa-test-db v1 endpoint=<ep> branch=<br>`)이 있고, 표식의 endpoint·branch 가 DB 가 보고하는 현재 `neon.endpoint_id`·`neon.branch_id` 와 같다. → 표식이 다른 브랜치로 복제되어도 endpoint·branch 가 달라 실패한다.
  - 표식은 **초기 설정 명령**(`test-marker init`)으로만 만든다. 이 명령은 `TEST_DATABASE_URL` 대상에만 쓰며, 다른 설명이 이미 있으면 덮어쓰지 않는다. 확인 명령(`test-marker check`)·테스트·마이그레이션은 표식이 없으면 **거부**하고 자동으로 만들지 않는다.
  - `dev` 대상(`DATABASE_URL_DIRECT`) 작업은 아래를 **모두** 통과해야 진행한다.
    1. `DEV_DATABASE_ENDPOINT_ID` 가 설정되어 있고 `DATABASE_URL_DIRECT`(직접 연결)의 endpoint 와 같다.
    2. `DATABASE_URL` 이 설정되어 있고 같은 endpoint·DB 를 가리킨다.
    3. 접속 후 DB 가 보고하는 `neon.endpoint_id` 가 고정값과 같다.
    4. 테스트 endpoint(`TEST_DATABASE_ENDPOINT_ID`)가 아니고, 테스트 표식이 없다.
  - **운영 환경(`COSMOA_ENV=production` 또는 Render)에서는 모든 관리 명령(개발·테스트용)을 거부**한다. 운영 적용 명령은 아직 없다.
  - 테스트 브랜치를 다시 만들면 endpoint 가 바뀌므로 `TEST_DATABASE_ENDPOINT_ID` 와 표식을 PM 이 다시 설정한다.
- Neon 은 SSL 연결(`sslmode=require`, `channel_binding=require`)을 사용한다.
- **Neon 브랜치 구성 — 확정** (프로젝트 COSMOA, AWS Oregon)

| Neon 브랜치 | 용도 | 부모 | 접속 |
|---|---|---|---|
| `production` | 운영·시연 | – | PM 만. 배포 환경변수로만 사용. 로컬 `.env` 에 넣지 않는다 |
| `dev` | 개발 통합 | production | `.env` 의 `DATABASE_URL`(풀링)·`DATABASE_URL_DIRECT`(직접) + `DEV_DATABASE_ENDPOINT_ID` |
| `test` | 자동 테스트 | production | `.env` 의 `TEST_DATABASE_URL`(직접) + `TEST_DATABASE_ENDPOINT_ID`. 테스트 표식 있음 |

  - Neon 브랜치는 만들 때 부모 데이터를 복사한다. 표식을 설정한 `test` 에서 다른 브랜치를 만들지 않는다.
  - Git 브랜치(`feature/*` → `develop` → `main`, README 「Git 작업 시 주의사항」)와 Neon 브랜치는 별개다.

### 4-3. 패키지 — 반영됨

`requirements.txt` 에 추가했다. (확인한 설치 버전: Python 3.10.21 `tdenv`)

| 패키지 | 범위 | 확인 버전 |
|---|---|---|
| `psycopg[binary]` | `>=3.2,<4` | 3.3.6 |
| `psycopg-pool` | `>=3.2,<4` | 3.3.3 |
| `yoyo-migrations` | `>=9.0,<10` | 9.0.0 |

- yoyo 9.0.0 은 Windows 에서 마이그레이션 파일을 시스템 인코딩(cp949)으로 읽는 부분이 있어, 관리 명령이 yoyo 모듈 안에서만 UTF-8 로 읽도록 보정한다. 마이그레이션 파일은 UTF-8 로 저장한다.

---

## 5. 실행·검증 절차

### 5-1. 현재 (동작 중)

README 의 「설치 및 실행」·「검증 방법」을 따른다.

### 5-2. 업무 DB 관리 명령 — 구현됨

저장소 루트에서 `conda activate tdenv` 후 실행한다. 모든 명령은 서버 실행과 분리되어 있고, 접속 주소·비밀번호·endpoint id 를 출력하지 않는다.

1. 설치·설정
   ```powershell
   pip install -r requirements.txt
   # .env 에 4-2 의 변수 설정 (값은 PM 에게 별도 전달받음, .env.example 참고)
   ```
2. 테스트 DB 표식 — PM 이 test 브랜치를 만든 뒤 **한 번만** 설정. 확인은 언제든 가능
   ```powershell
   python -m src.common.db_admin test-marker init    # TEST_DATABASE_URL 대상에만 표식 설정 (이미 있으면 변경 없음)
   python -m src.common.db_admin test-marker check   # 허용 endpoint + 표식 일치 확인 (읽기만)
   ```
3. 마이그레이션 — 대상(`--target`)을 반드시 지정한다. `test` → `TEST_DATABASE_URL`, `dev` → `DATABASE_URL_DIRECT`. 다른 주소로 대체하지 않는다.
   ```powershell
   python -m src.common.db_admin status  --target test             # 적용·대기 파일, 테이블 상태 (읽기만)
   python -m src.common.db_admin migrate --target test --dry-run   # 적용할 파일만 확인
   python -m src.common.db_admin migrate --target test
   python -m src.common.db_admin rollback-last --target test       # 되돌리기 확인 (테스트 DB 전용)
   python -m src.common.db_admin migrate --target dev              # 테스트 통과 후
   ```
   - 적용 전에 DB 의 `public` 테이블·적용 기록을 저장소 마이그레이션과 비교한다. 마이그레이션에 없는 테이블, 미적용인데 이미 있는 테이블, 적용 기록과 다른 상태가 있으면 **삭제·덮어쓰기 없이 거부하고 상황을 출력**한다.
   - 이미 적용한 파일은 다시 실행되지 않는다 (yoyo `_yoyo_migration` 기록).
   - 운영(production) 적용 명령은 아직 두지 않는다. 운영 적용 절차는 PM 이 배포 단계에서 정한다.
4. 최초 계정 — 계정이 하나도 없을 때만 만든다 (시스템 작업, `users.created_by` NULL)
   ```powershell
   python -m src.common.db_admin create-first-user --target dev --email <이메일> --name <이름> [--team <팀>]
   ```
   - 비밀번호는 화면에 표시되지 않는 입력으로 두 번 받는다 (8자 이상). 명령 인자·로그·문서에 남기지 않는다.
   - 비밀번호를 묻기 전에 대상 확인·`users` 테이블·기존 계정 여부를 먼저 확인한다. 계정이 있으면 거부한다.
   - 해시는 기존 로그인과 같은 werkzeug `generate_password_hash` 를 쓴다. DB 도 해시 형식이 아니면 거부한다.
   - Windows 에서는 대화형 터미널(PowerShell 등)에서 실행한다. 비밀번호를 파이프로 넘기지 않는다.
   - 만든 계정으로 바로 로그인할 수 있다 (`python app.py` → `/login`).
5. 팀원 계정 추가 — 이미 있는 계정 생성 담당자가 만든다 (`created_by` = 담당자 계정 id)
   ```powershell
   python -m src.common.db_admin create-user --target dev --email <이메일> --name <이름> [--team <팀>] --by <생성 담당자 이메일>
   ```
   - 비밀번호를 묻기 전에 대상 확인, 이메일 형식·정규화(소문자·앞뒤 공백 제거), 같은 이메일 계정, 담당자 계정 존재를 확인한다.
   - 숨김 입력 3번: 담당자 본인 비밀번호(확인용) → 새 계정 비밀번호 → 확인. 담당자 비밀번호가 틀리면 만들지 않는다. 해시는 로그인과 같은 werkzeug 방식.
   - 비밀번호·해시·접속 주소는 출력하지 않는다. 운영 환경에서는 거부(다른 명령과 같음).
   - 첫 비밀번호는 별도 경로로 전달하고, 팀원이 로그인 후 비밀번호 변경 화면에서 바로 바꾼다.
6. 기존 계정 비밀번호 재설정 — 계정이 있어야 하며, 비밀번호를 묻기 전에 계정 존재를 확인한다. 재설정하면 그 계정의 기존 로그인 세션은 모두 끝난다
   ```powershell
   python -m src.common.db_admin set-password --target dev --email <이메일>
   # 예전 명령 형식도 같은 처리로 연결: python -m src.common.auth set-password --target dev --email <이메일>
   ```
7. 앱용 PostgreSQL 접속 역할 — 대시보드 계정(4~6)과 별개인 **DB 계정**. 순서·검증·한계는 [DB 규칙](db_rules.md) 8-5~8-8
   ```cmd
   python -m src.common.db_admin app-role init-group   --target test                          :: 공통 권한 역할 cosmoa_app (NOLOGIN)
   python -m src.common.db_admin migrate              --target test                          :: 0004_app_role_grants (표 권한)
   python -m src.common.db_admin app-role create-login --target test --role cosmoa_app_test   :: 비밀번호 숨김 입력 2번 (16자 이상)
   python -m src.common.db_admin app-role check        --target test --role cosmoa_app_test   :: 읽기만, 문제 0건이어야 완료
   ```
   - 이미 있는 역할은 db_admin 표식·속성·멤버십이 맞을 때만 "변경 없음"으로 통과하고, 다르면 거부한다 (인수·비밀번호 변경 없음).
   - `0004` 는 `cosmoa_app` 이 먼저 있어야 적용된다 (없으면 실패). **test·dev 적용 완료 / production 미적용.** dev 로그인 역할은 `cosmoa_app_yjh`(현재 개발자)만 있고 팀원 역할은 미생성.
   - `app-role whoami --target dev` 로 `.env` 의 `DATABASE_URL` 이 실제로 어떤 역할로 접속하는지 확인한다 (읽기만, 비밀값 출력 없음).

- **Flask·Gunicorn 시작 시 마이그레이션을 자동 실행하지 않는다.** Dockerfile `CMD` 에도 넣지 않는다.
- 서버 시작 시 데모 계정을 자동 생성하지 않는다. 계정은 위 명령과 이후 계정 관리 기능으로만 만든다.
- 업무 DB 미설정·접속 실패·테이블 없음은 로그인 시 503("일시적으로 연결할 수 없습니다")으로 보이고, 서버 로그에 비밀값을 가린 원인이 남는다.

### 5-3. 적용 순서: 테스트 → 개발 → 운영

| 순서 | 대상 | 사용 변수 | 수행 | 확인 |
|---|---|---|---|---|
| 1 | 테스트 DB | `TEST_DATABASE_URL` | 마이그레이션 적용 → 업무 DB 테스트 실행 | 테스트 통과, 되돌리기 파일이 있다면 되돌리기·재적용 확인 |
| 2 | 개발 DB | 개발 환경의 `DATABASE_URL_DIRECT` | 마이그레이션 적용 → 서버 실행 후 수동 확인 | 저장·불러오기·최종본 흐름 |
| 3 | 운영 DB | 운영 환경의 `DATABASE_URL_DIRECT` | **PM 이** 마이그레이션 적용 → 배포 | 배포 후 점검 |

- 각 단계는 앞 단계 확인 후 진행한다. 마이그레이션 PR 은 1단계 결과를 첨부한다.
- 테스트 DB 정리(초기화)는 테스트 DB 에서만 하며, 실행 전 4-2 의 식별 정보 확인을 통과해야 한다. 변경 금지 트리거가 있으므로 행 삭제가 아니라 스키마를 다시 만드는 방식을 쓴다. (방식은 구현 시 확정 — **초기화 명령은 아직 없다**. 현재 테스트 데이터는 test 브랜치에 남는다)

**마이그레이션 적용 기록**

| 파일 | test | dev | production |
|---|---|---|---|
| `0001_core` | 표식 설정 → 적용 → 되돌리기 → 재적용 → 통합 테스트 통과 | 테스트 통과 후 적용 | 미적용 (접속 안 함) |
| `0002_project_rules` | 적용 → 통합 테스트 통과 (기존 이력 12행은 `xact_id` NULL 그대로). 되돌리기는 실행하지 않음 (`xact_id` 열 삭제가 데이터 삭제라서) | 테스트 통과 후 적용 | 미적용 |
| `0003_versioning` | 적용 → (빈 테이블 상태에서) 되돌리기 → 재적용 → 저장 엔진·API·회귀 테스트 통과 | 테스트 통과 후 적용. 기존 계정 1개 유지, 데모 데이터 없음 | 미적용 |
| `0004_app_role_grants` | (2026-10-21) `app-role init-group` → 적용 → 되돌리기(권한만 회수) → 재적용 → `cosmoa_app_test` 생성 → `app-role check`·앱 역할 검증·회귀 테스트 통과 ([DB 규칙](db_rules.md) 8-6) | (2026-10-21) `app-role init-group` → dry-run → 적용 → `app-role check` 통과 → `cosmoa_app_yjh` 생성·풀링 인증 확인. 파괴적 시험·통합 테스트 없음, PM 계정·업무 데이터 보존 ([DB 규칙](db_rules.md) 8-8) | 미적용 |

- 두 DB 모두 재실행 시 적용할 파일 없음 확인. 0003 적용 시점에 dev 에는 PM 이 만든 첫 계정 외 데이터 없음 (이후 화면 확인으로 만든 고객사·프로젝트는 조회하지 않음).

### 5-3-1. 화면 확인 — 개발요청서 프로젝트 선택 (3-1)

`python app.py` → 로그인 → `/dev-request`. **dev DB 에 실제로 고객사·프로젝트가 만들어진다.** 확인용 데이터는 이름에 `[확인]` 등을 붙여 구분한다 (삭제 API 는 없고, 보관 기능도 아직 없다).

1. 처음에는 ‘프로젝트를 선택하지 않았어요’ 와 선택 영역이 보인다. 고객사가 없으면 목록에 ‘새 고객사를 만들어 주세요’.
2. [새 고객사] → 이름 입력 → [고객사 만들기] → 그 고객사가 선택되고 새 프로젝트 입력이 열린다.
3. 프로젝트(제품)명·납기일(선택) → [프로젝트 만들기] → 상단에 `고객사 › 프로젝트`, ‘단계 제안 · 상태 진행 · 납기 …’ 표시.
4. [직접 작성] → 오른쪽 문서 정보의 ‘연결 프로젝트’ 가 같은 프로젝트인지 확인.
5. 작성 중 [프로젝트 변경] → 다른 프로젝트 선택 → 확인 창에서 **취소** → 선택·입력 그대로. 다시 선택 후 **확인** → 요청서가 초기화되고 시작 화면.
6. 새로 고침 → 같은 프로젝트가 다시 선택되어 있다 (요청서 내용은 사라짐 — 기존과 같음).
7. 프로젝트 없이(다른 탭에서 새로 열기) 작성 → 프로젝트 선택 → ‘연결할까요?’ 확인 → 입력 유지한 채 연결.
8. 작성 완료 → 결과 → [인쇄 / PDF 저장] 이 기존처럼 동작.
9. 고객사 검색칸에 이름 일부를 입력하면 목록이 좁혀진다.

**3-2 FIX 필드 확인** (프로젝트를 고른 상태에서 [직접 작성])

1. 고객사 칸이 입력칸이 아니라 연결 프로젝트의 고객사로 표시된다. 변환 설정의 고객사도 같은 이름으로 잠긴다.
2. 제품 유형 ‘스킨케어’ → 세부 유형(토너·스킨·세럼·앰플·크림·로션)이 나타난다. 다른 유형으로 바꾸면 사라지고 값이 지워진다.
3. 목표 가격대 [+ 가격대 추가] 를 여러 번 → 금액·통화 입력. 빈 줄은 완료 시 빠지고, 0 이하 금액·같은 금액·통화 중복은 안내된다.
4. 02 탭: 점도(선택칸은 ‘선택값 확정 전’으로 비활성 + 서술 입력), SPF, PA, 용기 (참고값).
5. 03 탭: 컨셉 원료 — [+ 필수 원료 추가]/[+ 선호 원료 추가], 원료명·함유 필수 여부(미확인/필수/아님)·효능 태그(쉼표). R&D 확인 요청사항.
6. [작성 완료] → 결과 화면과 [인쇄 / PDF 저장] 미리보기에 위 값이 모두 보인다. 문서 정보 ‘문서 버전: 저장 전’, PDF ‘Version: 저장 전 (서버 버전 없음)’.
7. [수정] → 값 변경 → [수정 완료] 시 작성 방식이 ‘직접 작성 후 수정’ (화면 버전 번호는 없음).
8. 파일 자동변환은 OpenAI 를 실제로 호출한다(비용). 확인한다면: 원문에 ‘저가/중가/고가’ 표기가 있으면 목표 가격대가 비어 있고 ‘원문 가격대 표기 … 직접 입력’ 안내가 보인다.
9. 저장 버튼은 아직 없다. 개발자 도구 콘솔에서 `document.getElementById("requisition-app").buildRequisitionPayload()` 로 저장용 payload(파일 본문·원문 보존 데이터 없음)를 볼 수 있다.

### 5-4. 테스트

```powershell
python -m unittest discover -s src/common/tests -p "test_db_unit.py"          # DB 접속 없음
python -m unittest discover -s src/common/tests -p "test_db_integration.py"   # TEST_DATABASE_URL 전용
python -m unittest discover -s src/common/tests -p "test_auth_integration.py" # 로그인 — TEST_DATABASE_URL + Flask test_client
python -m unittest discover -s src/common/tests -p "test_versions_unit.py"   # 저장 payload 검증 (DB 접속 없음)
python -m unittest discover -s src/common/tests -p "test_versions_integration.py"  # 저장 엔진·API — TEST_DATABASE_URL 전용
python -m unittest discover -s src/common/tests -p "test_projects_unit.py"      # 고객사·프로젝트 입력 검증 (DB 접속 없음)
python -m unittest discover -s src/common/tests -p "test_projects_integration.py"  # 고객사·프로젝트 API — TEST_DATABASE_URL 전용
python -m unittest discover -s src/common/tests -p "test_common_js.py"           # Common.api 재전송 규칙 (Node.js, 접속 없음)
python -m unittest discover -s src/05_requisition/tests -p "test_contract.py"    # 개발요청서 저장 계약 v1·화면 payload (Node.js, 접속 없음)
```

- 고객사·프로젝트 API 통합 테스트가 확인하는 것: 생성·조회(작성자 = 세션 사용자, `proposal`/`active` 시작, 납기 입력·NULL), 고객사별 프로젝트 목록(다른 고객사 제외·최신순·페이지·보관 제외), 고객사 검색·이름순 페이지(`%`·`_` 글자 그대로), 페이지 크기 상한, 잘못된 입력(공백·201자·숫자·줄바꿈·없는 날짜·형식 오류·빈 날짜·누락·JSON 아님), 단계·상태·작성자·고객사 id 를 본문으로 보내면 거부, 없는 고객사 404(행 미생성)·보관 고객사 400, 미인증 401, CSRF 없음·틀림·다른 세션 403(행 미생성), 만든 프로젝트로 저장 API 사용, DB 장애 503(비밀값 없음).

- 통합 테스트는 `TEST_DATABASE_URL` 이 없으면 건너뛰고, 테스트 DB 식별(4-2)에 실패하거나 0001 이 적용되지 않았으면 멈춘다.
- 1단계 통합 테스트가 확인하는 것: 필수 FK·CHECK·NOT NULL, 납기일 NULL 허용·생성 시 납기일 입력, 신규 프로젝트를 홀드·드롭·기본 외 단계로 생성 거부, 홀드·드롭 사유 필수, 평문 비밀번호·대문자 이메일 거부, 시스템 계정(`created_by` NULL) 1개 제한, 고객사·프로젝트 삭제 거부(보관), 프로젝트 변경과 이력의 동시 커밋, 한 트랜잭션 안 여러 번 변경, 예외·이력 실패 시 함께 롤백, 이력 없는 직접 UPDATE 를 커밋 시 거부, 과거 트랜잭션 이력으로 새 변경 통과 불가, `xact_id` 를 서버가 기록(클라이언트 값 무시), `project_history` UPDATE·DELETE·TRUNCATE 거부, werkzeug 해시 저장·조회 후 `check_password_hash` 성공/실패, 마이그레이션 재실행 시 적용 없음.
- 단위 테스트(접속 없음)가 확인하는 것: 테스트·dev endpoint 고정 불일치·누락, 풀링/직접 주소 불일치, DB 보고 endpoint 불일치·dev 의 테스트 표식(모의 연결), 운영 환경(`COSMOA_ENV=production`·`RENDER`)에서 모든 관리 명령 거부(접속·비밀번호 입력 없이), 해시 형식과 DB CHECK 정규식 일치.
- DB 의 해시 CHECK 는 **형식만** 본다(평문 저장 방지). 실제 비밀번호 일치는 `check_password_hash` 로 확인한다.

아래는 이후 단계까지 포함한 전체 확인 목록이다.

- 기존 단위 테스트(`python -m unittest discover ...`)는 그대로 유지한다.
- 업무 DB 테스트에서 반드시 확인할 것 (기본설계 통합 검증 + 개발기준)
  - 같은 프로젝트·탭에 두 사람이 동시에 저장해도 `version_no` 가 겹치지 않는다.
  - 저장본·최종본 이력·반영 출처를 `UPDATE`·`DELETE` 하면 DB 가 거부한다.
  - **최종본·`based_on_id`**: 같은 프로젝트·같은 탭의 저장본만 허용한다. 같은 프로젝트라도 다른 탭의 저장본을 지정하면 DB 가 거부한다.
  - **반영 출처(`version_links`)**: 같은 프로젝트의 다른 탭 저장본을 출처로 연결할 수 있다. 규제 메모 출처(`source_version_id` NULL)도 같은 프로젝트의 메모만 연결된다. (메모 출처는 4단계 이후)
  - **다른 프로젝트**: 최종본·`based_on_id`·반영 출처(저장본·메모) 중 어느 것이든 다른 프로젝트 대상이면 DB 가 거부한다.
  - 최종본을 다른 사람이 먼저 바꾼 상태에서 변경 요청하면 409 와 현재 상태가 돌아온다.
  - 저장 → 최종본 지정 → 다른 탭에 반영 → 원본 수정 → **기존 요청서 내용이 그대로**인지.
  - 규제 메모를 반영해 요청서 저장 → 원본 메모 수정 → 저장된 요청서 payload 와 `version_links.applied_values` 가 그대로인지. (4단계 이후)
  - 프로젝트 단계·상태·납기일 수정과 `project_history` 추가가 함께 커밋되고, 하나가 실패하면 함께 취소되는지.
  - 일반 사용자 요청으로 만든 행의 `created_by` 가 NULL 로 저장되지 않는지.
  - 테스트 DB 식별 정보를 확인할 수 없으면 초기화를 거부하는지.
  - 요청서 저장·최종본 지정만으로 개발 차수가 오르지 않는다. (5단계 구현 후)
  - 저장 payload 에 `data_url`·파일 본문 base64 가 남지 않는다.

---

## 6. 사용자 범위

- **확정(개발기준) / 개발용 기본 정책**: 로그인한 팀 사용자는 모든 프로젝트와 저장본을 공유해 조회·저장할 수 있다.
- 저장본·최종본 이력·반영 기록의 작성자는 **서버의 로그인 세션 사용자**로 정한다. 요청 본문의 작성자 값은 사용하지 않는다.
- **시스템 작업 예외 — 확정(개발기준)**: 모든 `created_by` 가 기존 로그인 사용자를 요구하면 첫 계정을 만들 수 없다. 최초 계정 생성처럼 로그인 사용자가 없는 시스템 작업은 `created_by` 를 NULL 로 기록하고, 일반 사용자 작업은 항상 서버 로그인 사용자로 기록한다. 최초 계정을 만드는 실제 명령은 이후 구현 대상이다. (`db_rules.md` 3-5)
- ⚠ 실제 운영 권한(역할별 제한, 최종본 지정 권한 등)은 **별도 확정 항목**이다.

---

## 7. 기존 코드 재사용과 탭 연결 범위

### 7-1. 재사용

| 대상 | 재사용 방식 |
|---|---|
| `app.py` | Route 구조·담당자별 영역 유지. PM 영역에 DB 초기화·공통 저장 API 등록 추가 |
| `src/common/auth.py` | `login_required`, 세션, `safe_next`, werkzeug 비밀번호 해시 유지. 저장소만 업무 DB 로 교체 |
| `src/01_home/home_data.py` | 홈 캐시 SQLite 유지. 경로만 `HOME_CACHE_DB_PATH` 로 분리. FIX 홈 개편(수출입 제외·환율 3개국·뉴스 통합·위젯)은 후속 |
| `src/02_regulatory/regulatory_mfds_lookup.py` | 읽기 전용 SQLite 유지 |
| `src/05_requisition/schema.py` | `SECTIONS`/`FIELDS` 를 개발요청서 payload `inputs` 의 기준으로 사용 |
| `src/05_requisition/service.py` | 자동변환 API 유지. "원본 파일은 서버 디스크에 저장하지 않습니다" 주석·동작 유지 |
| `src/05_requisition/requisition.js` | 작성·수정·결과·인쇄 흐름 유지, 저장·불러오기 추가 |
| 공통 UI | `docs/design_system.md`, `docs/ui_components.md`, `src/common/style.css` |

### 7-2. 첫 구현에서 추가·수정할 파일 (1단계 항목 구현됨, 나머지 구현 예정)

| 파일 | 내용 |
|---|---|
| `requirements.txt`, `.env.example` | 패키지, 4-2 변수 이름 — **구현됨** |
| `db/migrations/*.sql` | 1·2단계 테이블, 변경 금지 트리거 — **구현됨** (`0001_core`, `0002_project_rules`, `0003_versioning`) |
| `src/common/db.py` | psycopg 3 연결·트랜잭션 도우미 — **구현됨** |
| `src/common/db_admin.py`, `src/common/projects.py`, `src/common/tests/` | 관리 명령(표식·마이그레이션·최초 계정), 프로젝트 변경 도우미, 업무 DB 테스트 — **구현됨** |
| `src/common/auth.py` | users 를 업무 DB 로 — **구현됨** |
| 공통 저장 모듈·API | 저장·목록·불러오기·최종본·이력 — **구현됨**: `versions_api.py`(Blueprint) / `versions.py`(업무 규칙) / `versions_repo.py`(SQL) / `payloads.py`(검증). [API 계약](api_contract.md) |
| `app.py` (PM 영역) | DB 초기화·홈 캐시 경로 분리 — **구현됨**, 공통 API 등록은 2단계 |
| `src/common/common.js` | 공통 JSON·CSRF 클라이언트 `Common.api` — **구현됨 (3-1)**. 저장·불러오기 화면 함수는 3단계 |
| `src/common/projects_api.py`, `projects_service.py` | 고객사·프로젝트 생성·조회 API — **구현됨 (3-1)** |

### 7-3. 개발요청서 연결 시 수정 (구현 예정, 공통 기반 작업 범위에 포함)

| 파일 | 내용 |
|---|---|
| `src/05_requisition/requisition.js` | 프로젝트 선택 — **구현됨 (3-1)**. 이후: 저장(새 버전)·버전 목록·불러오기·최종본, `based_on_id` 전달, 저장 전 `data_url` 제거, 불러온 저장본에 파일 본문이 없다는 안내, 미저장 문서를 정식 버전처럼 표시하지 않기, PDF 파일명 버전 = 서버 `version_no` |
| `src/05_requisition/schema.py` (필요 시 `service.py`) | FIX 필드 반영(목표 가격대 금액·통화 목록 등)과 자동변환 결과 형식 맞춤. 담당 E 와 합의 후 필요한 범위만 수정 |
| `src/05_requisition/requisition.html`, `requisition.css` | 저장·불러오기·버전·최종본 UI (공통 UI 규격, `requisition-` 접두사) |
| `src/05_requisition/tests/` | payload 정리·버전 표시 테스트 |
| `src/05_requisition/implementation.md`, `requisition.md` | 저장 범위·파일 정책·버전 기준 반영 |

### 7-4. 후속 탭 연결 (4·6단계)

- 규제(`src/02_regulatory/`): 선택 결과·메모를 `regulatory_notes` 에 저장, 메모만 저장, 요청서 ↔ 규제 양방향 불러오기
- 마진(`src/03_margin/`): 탭 전체 저장, 사양 변경 선택값, 요청서 반영 (수치 제외)
- 모델링(`src/04_simulation/`): 저장된 요청서 payload 불러오기, 허용 항목만 요청서 반영
- 각 탭 담당자와 payload 형식(`db/schemas/`)을 먼저 합의한다.

---

## 8. 미정·확인 대상

| 항목 | 상태 |
|---|---|
| Neon 브랜치 실제 구성 | **확정** — production / dev / test (4-2) |
| 테스트 DB 식별 방법 (4-2) | **확정·구현** — 허용 endpoint + DB 표식(endpoint·branch 일치). 테스트 DB 초기화 명령은 미구현 |
| 기존 SQLite 계정 이전 여부 | **별도 확인** — 이 PC 에는 기존 SQLite 계정 파일 없음. 다른 PC·배포 환경의 이전 필요 여부 확인 전까지 자동 이전·삭제하지 않음 |
| 최초 계정 생성 명령, 데모 계정 자동 생성 유지 여부 | **확정·구현** — `create-first-user`, `set-password`. 데모 계정 자동 생성 제거 |
| 팀원 계정 추가·본인 비밀번호 변경 | **구현됨** — `create-user`(5-2), `/account/password`. 실제 팀원 계정은 아직 없음. production 첫 계정은 배포 준비 단계 |
| 첫 로그인 시 비밀번호 변경 강제 | 미정 — 지금은 안내로만 (강제하려면 `users` 에 표시 열 추가 마이그레이션 필요) |
| 비밀번호 변경·로그인 시도 횟수 제한 | 미정 — 지금은 제한 없음 |
| 운영 권한 체계 | 별도 확정 |
| 개발요청서 FIX 필드의 키 이름·위치 | **확정·구현 (3-2)** — `data_contract.md` 4-3 매핑표 |
| 점도 드롭다운 값 목록 | **미정** — 구조만 구현, 값이 정해지면 `schema.VISCOSITY_LEVELS` 에 추가 |
| 컨셉 원료 효능 태그 목록 | **미정** — 지금은 자유 입력 |
| SPF·PA 입력 형식 (자유 입력 / 선택형) | **미정** — 지금은 원문 표기 그대로 자유 입력(50자) |
| 샘플 목표 가격대 vs 내부 Target Cost, AI 추출 여부, 연구소용 PDF 공개 범위 | **미정** — FIX 의 목표 가격대(샘플별 제안 가격, 예: 1,300·1,500·1,800원)와 바이어 파일의 Target Cost(원가·단가)는 같은 값인지 확인 필요. 지금은 자동변환이 금액을 채우지 않고(Target Cost 는 원문 보존 데이터에만, 저장 안 함), 사용자가 입력한 목표 가격대는 결과 화면·연구소용 PDF 에 그대로 표시된다. 기존 명세(requisition.md 13장)의 ‘연구소에 상세 Target Cost 비공개’ 와 함께 PDF 에 금액을 보일지 정해야 함 |
| 개발요청서 임시 저장(필수값 미입력 저장) | **미지원** — v1 은 필수값이 있어야 저장(400 `required_field`). 필요하면 정책을 정한 뒤 계약 변경 |
| 현재 계약과 호환되지 않는 저장본 구분·읽기 호환 | **해결안 제안 (미적용, 후속)** — 아래 8-1 |
| 각 탭 payload 세부 필드 (개발요청서 외) | 미정 — 탭 담당자 합의 |
| 규제 탭 저장본(`tab='regulatory'`)의 payload 구조·용도 | 미정 — 4단계 합의. 규제 메모는 `regulatory_notes` 로 확정 (`db_rules.md` 2-3) |
| 저장 payload 크기 상한 | **초기값 설정** (payload 256 KiB, 반영 기록 32 KiB, 출처 20개, 환경변수로 변경). 근거·측정: `api_contract.md` 4장. 마진·모델링 대표 데이터 확인 후 재검토 |
| `project_events` 필요 여부 | 미정 — 직접 일정 등록 범위에 따라 |
| 고객사명 중복 허용 여부 | **확정** — 허용. 화면은 같은 이름이 있으면 만들기 전에 확인 (고객사는 id 로 구분) |
| 로그인 화면(폼) CSRF 토큰 | **적용 (3-2)** — 로그인 전 세션 토큰 + hidden 필드 (`api_contract.md` 1-2) |
| 컨셉원료 AI 검색·추천 방식 | 미정 (FIX: 직접 작업 후 선택) |
| PDF 발행 후 그룹웨어 연동 | 미정 |
| 문서 발송 기록 | 범위 밖 (구현 전까지 관리한다고 표시하지 않음) |
| Neon 접속 역할 분리 | **test·dev 적용 완료 / production 미적용** (팀원 역할 미생성) — [DB 규칙](db_rules.md) 8장. dev 는 개발자별 로그인 역할(`cosmoa_app_<이니셜>`)이 `cosmoa_app` 권한을 받는 방식으로 확정. 남은 결정: PUBLIC `TEMP` 회수, 접속 수 제한, 역할 폐기 절차 (8-8) |
| Lab No. 고유 범위, 샘플 수량 단위 | 미정 (기본설계 기본값: 전체 고유, `unit` 칸) |

### 8-1. 현재 계약과 호환되지 않는 개발요청서 저장본

**확인한 사실**
- 2단계 코드는 개발요청서 `schema_version = 1` 을 **목표 가격대만 검사하는 부분 검사**로 받았다. 2단계 테스트는 이 수준에 맞춘 불완전한 payload(빈 `inputs`, `target_prices` 만 있는 것 등)를 `schema_version = 1` 로 저장했다.
- 3-2 에서 v1 을 전체 계약으로 바꿀 때 **번호는 1 그대로**다. 즉 같은 `schema_version = 1` 에 두 가지 모양이 있다.
- test DB 읽기 전용 확인 (식별 검증 통과, 2026-10-20): 개발요청서 저장본 42개 모두 `schema_version = 1`. 그중 **18개가 현재 계약 검사를 통과하지 못했다**(생성 03:44~06:26 UTC), 24개는 통과(06:54 UTC 이후). 시기로 보아 대부분 2단계 테스트가 남긴 것으로 보이지만, **검사 실패만으로 출처를 단정하지 않는다** — 손으로 넣은 데이터·다른 오류일 수도 있다. 데이터는 바꾸지 않았다.
- dev: 개발요청서 저장 화면이 없었으므로 API 를 직접 호출하지 않았다면 저장본이 없을 것으로 보지만 **조회하지 않았다**. production: 마이그레이션 미적용이라 없음.

**해결안 (권장, 미구현)**
1. 번호는 바꾸지 않는다. **정식 v1 = 3-2 계약**(`contract.py`)이고, 계약을 통과하지 못하는 저장본은 출처를 단정하지 않고 일반 명칭 **"현재 계약과 호환되지 않는 저장본"** 으로 다룬다. 원본은 그대로 보존한다. v2 로 올리면 정식 데이터가 없는데도 변환 코드가 필요해지고, 생성 시각으로 나누는 방식은 환경마다 기준이 달라 쓰지 않는다. 행 삭제·수정은 하지 않는다(추가만 트리거).
2. **읽을 때 계약을 다시 검사**한다: 불러오기·목록 API 가 저장본마다 계약 충족 여부를 함께 돌려주고, 화면은 호환되지 않는 저장본을 불러오기·최종본 지정·반영 출처 선택에서 빼거나 "현재 계약과 호환되지 않는 저장본 — 불러올 수 없음"으로 표시한다 (실패한 항목 경로는 상세로). 최종본 지정·반영 출처 API 도 거부한다. → **후속 작업** (저장·불러오기 화면 연결과 함께). 실제 읽기 호환 처리(변환해서 보여주기 등)를 할지도 그때 정한다.
3. dev 확인: 공통 DB 담당이 읽기 전용으로 dev 의 개발요청서 저장본 수·계약 충족 여부를 확인한다 (지금은 전용 명령이 없어 준비 필요).
4. test DB 의 호환되지 않는 행은 초기화 명령이 생기면 그때 정리한다. 현재 테스트는 자기가 만든 행만 확인하므로 영향이 없다. 데이터 삭제·변환·`schema_version` 변경은 하지 않는다.


---

## 9. 팀 개발 공통 규칙

파일·폴더·브랜치 이름 규칙은 9-3. 담당 폴더·Git 흐름·이름 접두사·충돌이 잦은 파일은 [README](../README.md) 「팀원별 담당 폴더」「개발 규칙」「Git 작업 시 주의사항」, 업무 DB 변경은 [DB 규칙](db_rules.md) 7장, 시작 순서·DB 명령 구분·테스트 DB 공동 사용은 [팀원 시작 안내](team_onboarding.md)를 따른다. 여기에는 그 문서들에 없는 규칙만 둔다.

### 9-1. 공통 UI (프로젝트 선택·저장·불러오기·최종본) — 확정(개발기준)

1. 개발요청서 상단의 **프로젝트 선택 영역 등 현재 배치는 기능 검증을 위한 초기 배치**다. 디자인·위치는 이후 공통 UI 정리 단계에서 바뀔 수 있다.
2. 각 탭을 공통 저장 기능에 연결하기 **전에** 프로젝트 선택·저장·불러오기·최종본의 **공통 위치와 표시 방식을 탭 담당자끼리 합의**한다. 합의 전에 탭마다 따로 배치하지 않는다. 합의 결과는 [공통 UI 규격](ui_components.md)에 올린다.
3. UI 를 바꿀 때도 다음 동작은 유지한다.
   - **프로젝트 연결**: 요청서·저장본은 작성을 시작할 때의 연결 프로젝트(id)로 저장한다. 화면에서 지금 고른 프로젝트와 혼동하지 않는다 ([API 계약](api_contract.md) 5-3).
   - **입력 보호**: 작성 중 프로젝트를 바꾸면 확인을 묻고, 확인할 때만 작성 내용을 초기화한다.
   - **CSRF**: 변경 요청은 `Common.api()` 로 보낸다 (토큰 자동, CSRF 거부 때만 1회 재전송).
   - **저장 동작**: 저장은 항상 새 버전 추가, 번호·작성자는 서버가 정함, 파일 본문 제외 ([DB 규칙](db_rules.md) 3·6장).
4. 공통 파일(`src/common/*`, `src/common/style.css`·`common.js`·`base.html`, `app.py` 의 PM 영역, `db/`, `docs/`) 변경은 PM 과 **영향을 받는 탭 담당자**와 조율한다. 공통 기반 작업이 탭 폴더를 고친 경우(이번에는 `src/05_requisition/`)도 그 탭 담당자가 검토한다 (10-3).
5. 현재 개발요청서의 프로젝트 선택 화면은 **최소 선택·생성 기능**이며, 이후 만들 **프로젝트 관리 탭(7단계)을 대체하지 않는다.** 프로젝트 수정·보관·단계/상태 변경·이력 화면은 그 탭의 범위다.

### 9-2. 업무 DB 공동 사용

- 공유 dev 에서는 테스트 초기화·데이터 일괄 삭제·임의 스키마 변경을 하지 않는다. 스키마 변경은 마이그레이션 + PR + DB 담당 승인 ([DB 규칙](db_rules.md) 7장).
- 테스트 DB 는 여러 사람이 함께 쓴다. 구조를 바꾸는 명령(`migrate`·`rollback-last`·`test-marker init`)은 공통 DB 담당만 공지 후 실행한다. 충돌 기준: [팀원 시작 안내](team_onboarding.md) 6장.

### 9-3. 파일·폴더·브랜치 이름 — snake_case — 확정(개발기준)

**규칙**
- 파일·폴더 이름은 **소문자 snake_case** (`a-z`, `0-9`, `_`). 확장자는 그대로 둔다. 숫자 접두어도 유지한다.
  - 예: `src/05_requisition/requisition_payload.js`, `src/common/img/apple_touch_icon.png`, `src/02_regulatory/test_data/regulations_5489_eu.json`
- 브랜치는 분류 접두어(`feature/` 등)를 유지하고 뒤쪽 이름을 snake_case 로 한다. `main`·`develop` 은 그대로.
  - 예: `feature/common_foundation`, `feature/regulatory`, `feature/requisition`
- 이번 통일의 범위는 **파일·폴더·브랜치 이름**이다. API URL, JSON 키, DB 테이블·열, 환경변수, 함수·클래스·CSS 선택자 이름은 이 규칙을 이유로 바꾸지 않는다. 제품·문서 코드(예: 시연 품목 `EU-SER-041`)처럼 이름이 아닌 식별값도 그대로 둔다.

**예외 (이름 유지)**

| 대상 | 이유 |
|---|---|
| `README.md`, `data/regulatory/README.md` | 저장소 표준 이름 — GitHub 가 폴더 첫 화면에 보여 줌 |
| `Dockerfile` | Docker 가 기본으로 찾는 이름 |
| `.gitignore`, `.gitattributes`, `.dockerignore`, `.env`, `.env.example` | 도구 설정 파일 이름 |
| 복합 접미사 `.rollback.sql`, `.v1.example.json`, `.dc.html` | 점(.)은 구분 기호다. `.rollback.sql` 은 yoyo 가 되돌리기 파일로 인식, `.v1.example.json` 은 스키마 버전·예시 구분, `.dc.html` 은 디자인 원본(`docs/reference/`) 형식 |
| `db/migrations/0001_core.sql` 등 기존 마이그레이션 | 파일명이 적용 기록(yoyo)의 식별자 — 바꾸면 다시 적용하려 함 (이미 snake_case) |
| `.git/`, `instance/`, `__pycache__/`, 가상환경(`tdenv/`, `.venv/`), 로그·DB·업로드 | Git 내부·생성 파일·로컬 데이터 |
| `local_reference/` 안의 파일 | 원본 회의록·DB 안의 **원래 제목**(저장소 밖 자료) — 폴더만 바꿈 |

**이름을 바꿀 때 함께 할 것**
1. 바꾸기 전에 참조를 찾는다 (`rg -n "<이전 이름>"`): Python import·파일 경로, 템플릿 `url_for('asset', filename=…)`, HTML·JS·CSS 경로, `Dockerfile`·`.dockerignore`·`.gitignore`, 테스트, `.env.example`, **모든 `.md`**(링크·인라인 코드·명령·폴더 트리·표).
2. 추적 파일은 `git mv` 로 바꾼다. Windows 에서 대소문자만 바뀌면 임시 이름을 거친다 (`git mv A.md tmp.md` → `git mv tmp.md a.md`).
3. 정확한 이전 이름만 새 이름으로 고친다 (전체 문자열 일괄 치환 금지). `/assets/<경로>` 로 공개되는 파일은 URL 도 바뀌므로 영향을 적는다.
4. 바꾼 뒤 이전 이름을 다시 검색하고, 관련 테스트를 돌린다.
5. 공통 경로(`src/common/`, `docs/`, `db/`, `app.py`, 설정 파일)나 다른 담당 폴더의 이름을 바꿀 때는 **관련 담당자와 먼저 조율**한다.

**이미 원격에 공유된 브랜치 이름 바꾸기** (브랜치 담당자가 직접, 팀에 먼저 공지)
1. 열린 PR 이 있으면 먼저 병합하거나, 새 이름으로 다시 열 계획을 공지한다.
2. 로컬: `git branch -m feature/old_name feature/new_name`
3. 원격: `git push -u origin feature/new_name` → 다른 사람이 새 이름으로 옮긴 것을 확인한 뒤 `git push origin --delete feature/old_name`
4. 같은 브랜치를 받은 팀원: `git fetch origin` → `git branch -m feature/old_name feature/new_name` → `git branch -u origin/feature/new_name`
5. 문서·설정에 적힌 브랜치 이름을 고친다. AI 도구는 push·원격 삭제를 하지 않는다 (README 「Git 작업 시 주의사항」).

**2026-10-20 적용 기록** (이전 이름 → 새 이름). 이전 경로가 남아 있지 않은지는 **현재 작업 트리·인덱스의 경로 기준**으로 확인했다. 과거 커밋 기록에는 이전 이름이 그대로 남는다(수정하지 않음).

| 종류 | 이전 이름 | 새 이름 |
|---|---|---|
| 브랜치 (로컬만, 원격에 없음) | `feature/common-foundation` | `feature/common_foundation` |
| 폴더 (Git 제외) | `local-reference/` | `local_reference/` (`.gitignore`·`.dockerignore` 에 추가, 이전 이름도 함께 제외) |
| 파일 | `src/05_requisition/IMPLEMENTATION.md` | `src/05_requisition/implementation.md` |
| 파일 | `src/common/img/apple-touch-icon.png` | `src/common/img/apple_touch_icon.png` (공개 URL `/assets/common/img/…` 도 바뀜 — 저장소 안 참조는 수정. 이전 URL 은 404 → **배포 전 호환성 확인 항목** ([Render 배포 안내](deploy_render.md) 6장 7번), 우회 경로는 만들지 않음) |
| 파일 | `src/02_regulatory/samples/EU-SER-041_development_brief_regulatory.pdf` | `…/samples/eu_ser_041_development_brief_regulatory.pdf` |
| 파일 | `src/02_regulatory/samples/KR_EU_CN_ASEAN_Hair_Color_Cream_Development_Brief.pdf` | `…/samples/kr_eu_cn_asean_hair_color_cream_development_brief.pdf` |
| 파일 | `src/02_regulatory/samples/KR_EU_CN_JP_ASEAN_Sun_Essence_Key_Ingredients.png` | `…/samples/kr_eu_cn_jp_asean_sun_essence_key_ingredients.png` |
| 파일 | `src/02_regulatory/samples/한국_EU_중국_아세안_두피샴푸_주요검토성분표.xlsx` (한글 이름) | `…/samples/kr_eu_cn_asean_scalp_shampoo_key_ingredients.xlsx` (내용 그대로, PM 결정에 따라 영문 이름으로) |
| 파일 | `src/02_regulatory/tests/fixtures/EU-SER-041_development_brief.pdf` | `…/fixtures/eu_ser_041_development_brief.pdf` |
| 파일 | `src/02_regulatory/test_data/regulations_1013_EU_plan_note.json`, `regulations_1941_EU_not_listed.json`, `regulations_5489_EU.json`, `regulations_5489_US.json` | `regulations_1013_eu_plan_note.json`, `regulations_1941_eu_not_listed.json`, `regulations_5489_eu.json`, `regulations_5489_us.json` |

---

## 10. 구현 현황과 인계 (2026-10-20 기준)

완료 여부는 **현재 저장소 코드** 기준이다. 서버만 있고 화면이 없는 기능은 "화면 미연결"로 적는다.

### 10-1. 공통 기반

| 기능 | 상태 | 코드 | 근거 문서 |
|---|---|---|---|
| 로그인 (업무 DB `users`, 세션 v2, 로그인 폼·API CSRF) | **구현됨** (dev). production 미적용 | `src/common/auth.py`, `login.html`, `app.py` | 2-1, [API 계약](api_contract.md) 1-2 |
| DB 연결·마이그레이션·관리 명령·테스트 DB 보호 | **구현됨** — 0001~0003 test·dev 적용 | `src/common/db.py`, `db_admin.py`, `db/migrations/` | 4-2, 5-2, 5-3 |
| 고객사·프로젝트 생성·조회 API | **구현됨**. 수정·보관·단계 변경 API 없음 | `src/common/projects*.py` | [API 계약](api_contract.md) 5장 |
| 저장본·최종본·반영 출처 API | **구현됨 (서버)**. 화면 연결 없음. 규제 메모 출처(`source_note_id`) 없음 | `src/common/versions*.py`, `payloads.py` | [API 계약](api_contract.md) 2~4장 |
| 공통 JS 요청 함수 `Common.api` | **구현됨** | `src/common/common.js` | [API 계약](api_contract.md) 1-2 |
| 팀원 계정 추가 (관리 명령) | **구현됨**. 실제 팀원 계정은 없음 | `src/common/db_admin.py` (`create-user`) | 5-2 |
| 본인 비밀번호 변경 | **구현됨** — 다른 기기 세션 종료 포함 | `src/common/auth.py`, `account_password.html`, `app.py` | 2-1 |
| 앱용 DB 역할 분리 | **test·dev 적용 완료 / production 미적용**. dev 는 현재 개발자 역할 `cosmoa_app_yjh` 만 있음(이 역할로 로그인·홈·개발요청서 화면 사용자 확인 완료), **팀원용 DB 역할·대시보드 계정 미생성** | `src/common/db_admin.py`(`app-role`), `db/migrations/0004_app_role_grants*.sql`, `src/common/tests/test_app_role_integration.py` | [DB 규칙](db_rules.md) 8장 |
| 테스트 DB 초기화 명령 | **없음** | – | 5-3 |
| production 적용·배포 문서 갱신 | **없음** (`deploy_render.md` "갱신 전") | – | 5-3 |

### 10-2. 탭별

| 탭 | 상태 |
|---|---|
| 개발요청서 | **구현됨**: 프로젝트 선택(3-1), FIX 필드·저장 계약 v1·저장용 payload 생성(3-2). **미구현**: 저장·불러오기·최종본 **화면 연결**, 저장 후 서버 `version_no` 표시·PDF 파일명 버전, 불러온 저장본의 파일 본문 없음 안내 |
| 규제·마진·모델링 | 기존 화면·계산 그대로. 저장 계약(payload 세부)·프로젝트 연결·저장 연결은 **후속**. 서버는 지금 `structure` 수준(네 칸·파일 제외·크기)만 검증 |
| 탭 간 반영 (VE 배너, 규제 ↔ 요청서, 모델링 ↔ 요청서) | **후속** (6단계) |
| 개발 차수·샘플·피드백 | **후속** (5단계) |
| 프로젝트 관리 탭, 홈 위젯 | **후속** (7단계). 개발요청서의 프로젝트 선택은 대체가 아님 (9-1) |
| 홈·챗봇 | 이번 공통 기반 작업에서 기능 변경 없음 (테스트의 로그인 방식만 `login_as` 로 교체) |

### 10-3. 공통 기반 작업이 수정한 파일 범위

| 구분 | 파일 | 내용 |
|---|---|---|
| 공통 (신규) | `src/common/db.py`, `db_admin.py`, `projects.py`, `projects_service.py`, `projects_api.py`, `versions.py`, `versions_repo.py`, `versions_api.py`, `payloads.py`, `testing.py`, `src/common/tests/*` | 업무 DB·관리 명령·API·테스트 |
| 공통 (수정·신규) | `src/common/auth.py`, `login.html`, `common.js`, `base.html`(내 계정 → 비밀번호 변경 링크), `account_password.html`(신규) | PG 로그인, CSRF, `Common.api`, 본인 비밀번호 변경·세션 지문 |
| DB·문서 | `db/migrations/0001~0004`(0004 는 test·dev 적용), `db/schemas/requisition.v1.example.json`, `docs/development.md`·`db_rules.md`·`data_contract.md`·`api_contract.md`·`team_onboarding.md`(신규), `docs/deploy_render.md`, `README.md` | |
| 설정 | `app.py`(PM 영역: DB 설정·API 등록·로그인 CSRF·개발요청서 페이지에 필드 정의 전달, [E] 영역: 필드 정의 모듈 import 1줄), `requirements.txt`, `.env.example`, `.gitignore`(`.venv/`), `Dockerfile`(주석) | |
| 개발요청서 (E 폴더 — **담당자 검토 필요**) | `schema.py`, `service.py`, `contract.py`(신규), `requisition.js`, `requisition_payload.js`(신규), `requisition.html`, `requisition.css`, `tests/test_requisition.py`, `tests/test_contract.py`(신규), `implementation.md`, `requisition.md`(13장 안내) | 프로젝트 선택, FIX 필드, 저장 계약 v1 |
| 다른 탭 테스트 | `src/02_regulatory/tests/test_mfds_lookup.py`, `test_regulatory_service.py`, `src/06_chatbot/tests/test_chatbot.py` | 각 1곳 — 예전 세션 주입을 `login_as` 로 교체. 기능 코드 변경 없음 |

### 10-4. 후속 작업 (담당자는 팀에서 정함)

| 영역 | 작업 |
|---|---|
| 공통 DB | 팀원별 앱 역할 생성·주소 전달([DB 규칙](db_rules.md) 8-8 — test·dev 공통 권한은 완료)·대시보드 팀원 계정 생성, 테스트 DB 초기화 명령, 현재 계약과 호환되지 않는 저장본 처리(8-1), dev 의 개발요청서 저장본 확인, production 적용 절차(역할 포함)·배포 문서 갱신 |
| 공통 UI | 프로젝트 선택·저장·불러오기·최종본 공통 위치·표시 방식 합의 (9-1) |
| 개발요청서 | 저장·불러오기·최종본 화면 연결 (`buildRequisitionPayload()` 사용), 저장 후 버전 표시·PDF 파일명, 미정 선택값 반영(8장) |
| 규제·마진·모델링 | 탭별 payload 계약 v1 제안·확정 → `payloads.SCHEMAS` 등록, 프로젝트 연결·저장 연결 (4단계), 규제 메모(`regulatory_notes`) |
| 이후 단계 | 탭 간 반영(6), 차수·샘플·피드백(5), 프로젝트 관리 탭·홈 위젯(7) |
