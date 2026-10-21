# COSMOA 팀원 시작 안내 (Windows CMD)

> 대상: 탭 담당 팀원. 명령은 **Windows 명령 프롬프트(CMD)** 기준이며, 저장소 루트(`COSMOA` 폴더)에서 실행합니다.
> 규칙 원문은 [README](../README.md)(담당 폴더·Git·충돌 파일), [개발 안내](development.md)(9장 팀 공통 규칙, 10장 구현 현황), [DB 규칙](db_rules.md)(7장 마이그레이션)에 있습니다. 이 문서는 시작 순서만 정리합니다.

---

## 0. 시작 전에 확인 — 준비 필요 항목

아래가 준비되기 전에는 일부 단계를 진행할 수 없습니다. PM(공통 DB 담당)이 준비 여부를 공지합니다.

| 항목 | 현재 상태 | 영향 |
|---|---|---|
| 공통 기반이 `develop` 에 병합 | **아직 아님** (작업은 `feature/common_foundation`) | 병합 전에 `develop` 에서 만든 브랜치에는 로그인 DB 연결·고객사·프로젝트·저장 API 가 없음 |
| 팀원 계정 | **명령 구현됨** (`create-user`, 공통 DB 담당이 실행 — 6장). 실제 팀원 계정은 아직 만들지 않음 | 계정을 받기 전에는 로그인 확인(4장)을 할 수 없음. **`create-first-user` 는 팀원용이 아닙니다** (최초 1회, 계정이 있으면 거부) |
| 본인 비밀번호 변경 | **구현됨** — 로그인 후 "내 계정" → [비밀번호 변경] (`/account/password`) | 첫 비밀번호를 받으면 바로 바꿉니다 (4장) |
| 앱용 DB 접속 역할 분리 | **test·dev 적용 완료** — [DB 규칙](db_rules.md) 8장. 공통 DB 담당이 dev 앱 역할로 로그인·홈·개발요청서 화면 확인. **팀원용 역할은 아직 미생성** | 팀원마다 **본인 전용 앱 역할**(`cosmoa_app_<이니셜>`) 주소만 받음. 받은 뒤 `python -m src.common.db_admin app-role whoami --target dev` 로 확인 |
| 테스트 DB 초기화 명령 | **없음** | 테스트 데이터가 계속 쌓임 (6장) |
| 탭 저장 화면 연결 | **후속** — 공통 저장 API(저장·불러오기·최종본)는 구현됨, 각 탭의 저장 UI 연결은 아직 | 화면에서 만든 탭 내용은 아직 업무 DB 에 저장되지 않음. 공통 UI 배치 합의(7장) 후 탭별로 연결 |
| production(배포) | **미적용** — 업무 DB·앱 역할 모두 | 배포 준비 전. production 접속·적용은 PM 만 |

---

## 1. Python 환경과 패키지

권장: **Python 3.10** (배포 Docker 이미지 `python:3.10.21`, 기존 팀 환경 conda `tdenv` 와 같음).

conda 를 쓰는 경우 (Anaconda Prompt 또는 conda 가 설정된 CMD):

```bat
conda create -n tdenv python=3.10
conda activate tdenv
pip install -r requirements.txt
```

conda 가 없으면 Python 3.10 을 설치한 뒤 저장소 안 `.venv` 를 씁니다 (`.venv/` 는 Git 에서 제외됨):

```bat
py -3.10 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

- 패키지는 **가상환경 안에만** 설치합니다. 새 패키지가 필요하면 `requirements.txt` 에 한 줄 추가하고 PR 에 적습니다 (README 「설치 및 실행」).
- 업무 DB 패키지(`psycopg[binary]`, `psycopg-pool`, `yoyo-migrations`)는 `requirements.txt` 에 들어 있습니다.
- 선택: 공통 JS 테스트(`test_common_js.py`, `test_contract.py` 의 화면 payload 부분)는 **Node.js** 가 있을 때만 실행되고, 없으면 건너뜁니다.
- 규제 OCR(Tesseract)·한글 폰트는 README 「4. 식약처 DB와 OCR·PDF 준비」를 따릅니다. 없어도 앱은 실행됩니다.

## 2. 브랜치 만들기

작업 흐름은 `feature/*` → `develop` → `main` 입니다. (README 「Git 작업 시 주의사항」)

```bat
git fetch origin
git switch develop
git pull origin develop
git switch -c feature/<영역>
```

- `<영역>` 은 snake_case 로 씁니다. 예: `feature/regulatory`, `feature/margin`, `feature/sample`, `feature/requisition` (README 의 예시와 같은 이름 사용). 파일·폴더 이름도 snake_case — 예외·이름 변경 절차는 [개발 안내](development.md) 9-3.
- **0장의 "공통 기반 `develop` 병합" 이 끝난 뒤** 위 순서로 시작합니다. 그 전에 만든 브랜치는 병합 후 `git pull origin develop` 으로 받아 충돌을 해결합니다.
- `develop`·`main` 에 직접 커밋하지 않습니다. 커밋 전 `git status` 로 자기 폴더 밖 파일이 바뀌지 않았는지 확인합니다.

## 3. `.env` 설정

`.env` 는 Git 에 올라가지 않습니다. 없을 때만 예시를 복사합니다 (이미 있으면 덮어쓰지 말고 빠진 항목만 추가).

```bat
if not exist .env copy .env.example .env
```

일반 팀원이 채우는 항목:

| 변수 | 값 | 비고 |
|---|---|---|
| `FLASK_SECRET_KEY` | 본인이 만든 임의 문자열 | 로컬 세션 서명용. 비워 두면 개발용 기본값 사용 |
| `DATABASE_URL` | PM 에게 **개별 전달** 받은 dev **앱 역할**(본인 전용 `cosmoa_app_<이니셜>`) 풀링 주소 | 로그인에 필수. 공유 dev DB(개발 전용 비밀번호·테스트용 데이터만). 팀원 역할 생성(0장) 전에는 배포하지 않음. 이 주소도 비밀값 — 다른 사람과 같이 쓰지 않음 |
| `HOME_CACHE_DB_PATH` | 그대로 (`instance/cosmoa.db`) | 홈 캐시 SQLite |
| `MFDS_DB_PATH` | `data/regulatory/mfds_use_restriction.sqlite` | 식약처 규제 DB (README 4) |
| 기능별 외부 API 키 | 자기 기능에 필요한 것만 | README 「3. .env 설정」 표. 없으면 5장 범위만 확인 가능 |

**두 가지 계정을 받습니다 — 서로 별개입니다** ([DB 규칙](db_rules.md) 8-1)
- **대시보드 계정**: COSMOA 화면 로그인용 이메일·비밀번호 (`users` 표, 4장). 본인이 화면에서 비밀번호를 바꿉니다.
- **DB 앱 역할 주소**: 로컬 앱이 DB 에 접속할 때 쓰는 `DATABASE_URL` 안의 DB 계정. 고객사·프로젝트·저장본 추가와 조회만 할 수 있고, 표 삭제·수정·트리거 끄기·계정 추가는 DB 가 거부합니다. 바꾸거나 잊으면 공통 DB 담당에게 재발급을 요청합니다.

일반 팀원은 **받지 않아도 되는 항목** (공통 DB 담당 전용, 필수 아님): `DATABASE_URL_DIRECT`(관리 역할 직접 주소), `DEV_DATABASE_ENDPOINT_ID`, `TEST_DATABASE_URL`, `TEST_DATABASE_ENDPOINT_ID`, `TEST_APP_DATABASE_URL`(test 앱 역할 검증용). 비워 두어도 앱 실행·로그인·기능별 테스트에는 지장이 없습니다. 업무 DB 통합 테스트를 직접 돌려야 하면 PM 과 먼저 조율합니다 (6장).

**비밀값 규칙**
- 실제 값은 본인 `.env` 에만 둡니다. 코드·문서·`.env.example`·커밋·PR·이슈·채팅 캡처에 쓰지 않습니다.
- `.env.example` 에는 변수 **이름과 설명만** 추가합니다.
- 실수로 올렸다면 바로 PM 에게 알리고 해당 키·비밀번호를 재발급합니다. (Git 기록에서 지워도 이미 노출된 것으로 봅니다)
- 챗봇 연결용 `CHATBOT_SECRET` 은 본인이 만든 긴 임의 문자열을 메인·챗봇 서버에 같게 넣습니다 (주소·예시 값 재사용 금지, README 3).

## 4. 앱 실행과 로그인 확인

```bat
python app.py
```

브라우저에서 http://127.0.0.1:5000 → 로그인 화면.

- 로그인 계정은 업무 DB(dev) `users` 에 있습니다. 공통 DB 담당이 `create-user` 로 계정을 만들고 **첫 비밀번호를 별도 경로**(직접 전달 등, 채팅·메일 본문에 남기지 않음)로 알려 줍니다. 계정을 받기 전에는 로그인 화면 표시까지만 확인합니다.
- **첫 로그인 후 바로 비밀번호를 바꿉니다**: 왼쪽 아래 사용자 이름 → "내 계정" → [비밀번호 변경]. 현재 비밀번호·새 비밀번호(8자 이상, 현재와 다르게)·확인을 입력합니다.
  - 바꾼 브라우저는 로그인이 유지되고(보안 토큰은 새로 발급), **다른 기기·브라우저의 기존 로그인은 다음 화면 이동 때 로그아웃**됩니다.
  - 다른 사람의 비밀번호는 바꿀 수 없습니다. 비밀번호를 잊으면 공통 DB 담당에게 재설정(`set-password`)을 요청합니다 (재설정해도 기존 로그인은 모두 끝남).
- "일시적으로 연결할 수 없습니다" 가 보이면 `DATABASE_URL` 이 없거나 잘못된 것입니다 (비밀번호 오류와 다른 문구).
- 로그인 폼은 CSRF 토큰을 씁니다. 로그인 화면을 연 뒤 세션이 바뀌면(다른 탭에서 로그아웃, 브라우저 재시작 등) "보안 확인 시간이 지났어요" 가 나옵니다. 새로 고침 후 다시 로그인합니다.
- 서버 시작 시 테이블·계정·데모 데이터를 만들지 않습니다.

## 5. 외부 API 키 없이 확인할 수 있는 범위

| 확인 가능 | 키가 필요해 확인 불가(오류 안내가 나옴) |
|---|---|
| 로그인 화면 표시, (계정이 있으면) 로그인·로그아웃 | 개발요청서 **파일 자동변환**, 제형 문서 AI 분석 (`OPENAI_API_KEY`) |
| 개발요청서 프로젝트 선택·고객사·프로젝트 생성 (dev 에 실제로 생성됨 — 7장) | AI 챗봇 답변 (챗봇 서버 + `OPENAI_API_KEY`, `CHATBOT_URL`·`CHATBOT_SECRET`) |
| 개발요청서 **직접 작성**·수정·결과·인쇄/PDF, FIX 칸 | 성분 검색 등 외부 규제 API (`RAPIDAPI_*`) |
| 식약처 규제 DB 조회 (`MFDS_DB_PATH` 설정 시) | 홈 환율·수출입·뉴스 등 외부 데이터 (`EXIM_API_KEY`, `DATA_GO_KR_KEY` 등) |
| 기능별 자동 테스트 (외부 API 는 모의 응답, 업무 DB 대신 메모리 사용자) | |

기능별 자동 테스트 (DB·외부 API 키 불필요):

```bat
python -m unittest discover -s src/02_regulatory/tests -p "test_*.py"
python -m unittest discover -s src/05_requisition/tests -p "test_*.py"
python -m unittest discover -s src/06_chatbot/tests -p "test_*.py"
```

- 테스트 통과는 실제 외부 서비스 연결 성공을 뜻하지 않습니다. 규제 테스트 1개(`test_real_records`)는 로컬 수집 DB 가 있을 때만 실행되고, OCR 테스트는 Tesseract 가 있을 때만 실행됩니다.
- 실제 AI 호출은 사용료가 발생합니다.

## 6. DB 관련 명령 — 누가 실행하나

명령 형식은 `python -m src.common.db_admin <명령> ...` 입니다 (전체 설명: [개발 안내](development.md) 5-2). 모든 명령은 운영 환경에서 거부되고, 접속 주소·비밀번호를 출력하지 않습니다.

| 명령 | 실행하는 사람 | 비고 |
|---|---|---|
| `python app.py`, 기능별 테스트 (5장) | **모든 팀원** | `DATABASE_URL` 만 필요 (테스트는 그것도 불필요) |
| `status --target dev` / `status --target test` | 공통 DB 담당 | 읽기만 하지만 `DATABASE_URL_DIRECT`·endpoint 고정값 등 관리 정보가 필요 |
| `migrate --target test` / `migrate --target dev` (`--dry-run`) | **공통 DB 담당만** | 마이그레이션 PR 승인 후, test → dev 순서 ([DB 규칙](db_rules.md) 7장) |
| `rollback-last --target test` | **공통 DB 담당만** | 테스트 DB 전용 (dev 는 명령이 거부). 다른 사람의 테스트를 깨뜨림 |
| `test-marker init` / `test-marker check` | **공통 DB 담당만** (`check` 는 읽기만) | 테스트 브랜치를 새로 만들 때만 `init` |
| `create-first-user --target dev` | **공통 DB 담당만, 최초 1회** | 계정이 하나라도 있으면 거부. 팀원 계정용이 아님 |
| `create-user --target dev --email … --name … [--team …] --by <담당자 이메일>` | **공통 DB 담당만** | 팀원 계정 추가. 담당자 본인 비밀번호와 새 계정 비밀번호(2번)를 숨김 입력. `created_by` 에 담당자 계정 기록. 같은 이메일(대소문자 무시)이면 거부 |
| `set-password --target dev` | 공통 DB 담당만 | 비밀번호 분실 시 재설정. 평소 변경은 팀원 본인이 화면에서 |
| 비밀번호 변경 화면 `/account/password` | **모든 팀원** (본인 계정만) | 4장 |
| `app-role init-group` / `create-login --role …` / `check` (`--target test\|dev`) | **공통 DB 담당만** | 앱용 PostgreSQL 접속 역할 (대시보드 계정과 별개). 로그인 역할 비밀번호는 숨김 입력. 순서·검증: [DB 규칙](db_rules.md) 8-5 |
| 업무 DB 통합 테스트 `src/common/tests/test_*_integration.py` | 공통 DB 담당 (팀원은 조율 후) | `TEST_DATABASE_URL`·`TEST_DATABASE_ENDPOINT_ID` 필요 (앱 역할 검증은 `TEST_APP_DATABASE_URL` 도 필요, 없으면 건너뜀). 아래 "테스트 DB 공동 사용" |

**공유 dev DB 규칙**
- dev 는 모든 팀원이 함께 쓰는 개발 DB 입니다. **테스트 초기화, 데이터 일괄 삭제, Neon 콘솔·SQL 로 테이블 직접 변경을 하지 않습니다.** 업무 테이블 변경은 마이그레이션 파일 + PR + 공통 DB 담당 승인으로만 합니다 ([DB 규칙](db_rules.md) 7장).
- 고객사·프로젝트·저장본은 **삭제 API 가 없고 DB 도 삭제를 막습니다.** 화면 확인용으로 만드는 데이터는 이름에 `[확인]` 처럼 표시해 구분합니다.
- 자동 테스트를 dev 에 연결하지 않습니다 (통합 테스트는 `TEST_DATABASE_URL` 만 사용하도록 막혀 있음).

**테스트 DB 공동 사용 — 충돌 가능성과 조율 기준**
- 통합 테스트는 실행할 때마다 고유 이름(무작위 표식)의 사용자·고객사·프로젝트·저장본을 **추가만** 하고, 자기가 만든 행만 확인합니다. 그래서 여러 사람이 **같은 코드로 동시에 실행해도 보통은 서로 영향을 주지 않습니다.**
- 충돌하는 경우
  - `migrate`·`rollback-last`·`test-marker init`(그리고 이후 생길 초기화)은 **테스트 DB 전체 구조를 바꿉니다.** 실행 중인 다른 사람의 테스트가 실패하므로 공통 DB 담당만, 공지 후 실행합니다.
  - 스키마를 바꾸는 PR 을 개발 중일 때 그 마이그레이션을 공용 테스트 DB 에 먼저 적용하면, 아직 그 코드를 받지 않은 사람의 테스트가 상태 불일치로 멈춥니다. → 적용은 PR 검토 후 공통 DB 담당이 합니다. 병행 개발이 필요하면 별도 Neon 테스트 브랜치(endpoint·표식 설정 필요)를 공통 DB 담당에게 요청합니다.
  - 손으로 넣은 데이터(이름 규칙 없는 사용자 등)는 일부 테스트의 확인 조건과 겹칠 수 있습니다. → 테스트 DB 에 수동 데이터를 넣지 않습니다.
- 테스트 데이터는 계속 쌓입니다 (초기화 명령 없음). 이전 단계 테스트가 남긴 데이터도 있으므로 테스트 DB 의 행 수·내용을 기준으로 판단하지 않습니다.

## 7. 공통 기반과 탭 작업 시 지킬 것

- 프로젝트 선택·저장·불러오기·최종본의 **공통 위치·표시 방식은 탭 연결 전에 담당자끼리 합의**합니다. 현재 개발요청서 상단의 프로젝트 선택 영역은 기능 검증용 초기 배치입니다 ([개발 안내](development.md) 9-1).
- 저장 API·고객사·프로젝트 API 를 쓸 때는 `Common.api()` 를 사용합니다 (CSRF 토큰 자동, CSRF 거부 때만 1회 재전송 — [API 계약](api_contract.md) 1-2).
- 공통 파일(`src/common/`, `docs/`, `db/`, `app.py` 의 PM 영역, `README.md`, `requirements.txt` 등) 변경은 PM·관련 담당자와 조율합니다 (README 「충돌 가능성이 높은 파일」).
- 탭 저장 형식은 [데이터 계약](data_contract.md) 3장의 기록 항목을 바탕으로 담당자가 제안하고, 확정되면 서버 검증(`src/common/payloads.py` 의 `SCHEMAS`)에 올립니다. 개발요청서 v1(`src/05_requisition/contract.py`)이 예시입니다.
