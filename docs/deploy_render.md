# Render 배포 안내 (공통 개발 문서) — 무료 서비스 2개, 발표·시연용

> ⚠ **갱신 전 문서.** 로그인이 업무 DB(Neon PostgreSQL) `users` 로 바뀌었습니다. 아래의 `COSMOA_DEMO_*`·`instance/cosmoa.db` 계정 안내는 **예전 방식**입니다.
> production 브랜치에는 아직 마이그레이션·계정이 없고 배포 환경변수(`DATABASE_URL` 등)도 정해지지 않아 **지금 상태로는 배포 준비가 끝나지 않았습니다.** 절차는 [개발 안내](development.md) 의 다음 단계에서 정합니다.

### 0. 준비 현황 — "배포 파일 준비"와 "운영 적용"은 다르다 (2026-11-13, 5-1단계)

| 항목 | 저장소·배포 파일 | 운영(Render) 적용 |
|---|---|---|
| 식약처 규제 DB·성분 DB 배포 사본 (`data/regulatory/`, 3장) | **준비됨** — 2026-11-09 수집본 두 개, Git·Docker 포함 규칙, Dockerfile `ENV` | **미적용** — 실제 배포·챗봇 환경변수 입력 전 |
| 챗봇 `MFDS_DB_PATH`·`MFDS_INGREDIENT_DB_PATH` (4장) | 값 확정 | **미입력** |
| `RAPIDAPI_KEY`·`RAPIDAPI_HOST` 제거 (4장) | 코드·안내에서 삭제됨 | **미확인** — 다음 운영 배포 때 메인·챗봇 양쪽에서 제거 |

**배포 전에 남은 공통 전제조건** (식약처 SQLite 준비와 별개 — 이것들이 끝나야 배포 가능)
1. 업무 DB(Neon) **production** 브랜치 마이그레이션(0001~0004)·앱 역할 — 미적용 (공통 DB 담당 중 실행 담당자, `db_rules.md` 7-5. 시점은 김민 PM 과 결정)
2. 운영 로그인 계정 준비 — 로그인이 업무 DB `users` 로 바뀌었으므로 아래 `COSMOA_DEMO_*` 방식 대신 production 첫 계정 생성 절차가 필요 (미정)
3. 운영 환경변수 확정 — `DATABASE_URL`(운영 앱 역할 풀링 주소) 등 업무 DB 변수, 운영용 `FLASK_SECRET_KEY`·`CHATBOT_SECRET` 새 값
4. 실제 OpenAI 연동 확인 — 챗봇 답변·개발요청서 변환은 지금까지 가짜 응답으로만 검증됨 (6장 6번)

메인 대시보드와 AI 챗봇을 **같은 저장소·같은 커밋**에서 Render **Free** 웹 서비스 2개로 배포한다.
영구 디스크·SSH·Shell 은 쓰지 않는다. 추가 호스팅 비용이 없다.

```
브라우저 ──> 메인 (app.py, Docker, Free) ── POST https://<챗봇>.onrender.com/chat + X-Chatbot-Secret ──> 챗봇 (src/06_chatbot/server.py, Python, Free)
```

- 두 서비스는 파일을 공유하지 않는다. 식약처 규제 DB·성분 DB 는 **배포 파일에 포함**돼 각자 읽는다 (같은 커밋이면 같은 수집본).
- `.env` 는 배포에 쓰지 않는다. 값은 Render 서비스별 **Environment** 에만 넣는다. (`.env`·`instance/` 는 Git·Docker 이미지 모두 제외)
- 두 서비스의 Region 을 같게 둔다 (예: Singapore).

---

## 1. 메인 서비스

| 항목 | 값 |
|---|---|
| Runtime (Language) | Docker |
| Instance Type | **Free** |
| Root Directory | (비움 — 저장소 루트) |
| Dockerfile Path | `./Dockerfile` (Docker Build Context: 저장소 루트) |
| Docker Command | (비움 — Dockerfile `CMD` 사용) |
| Python 버전 | Dockerfile 기반 이미지 `python:3.10.21-slim-bookworm` 로 고정 (`PYTHON_VERSION` 불필요) |
| Health Check Path | `/login` |
| Disk | 없음 |

`Dockerfile` 이 하는 일
- Tesseract + 한국어·영어 언어 데이터 (규제 OCR), 나눔 폰트 (마진 견적서 PDF 한글)
- `COSMOA_ENV=production` → `.env` 미로딩, `FLASK_SECRET_KEY` 필수, debug 끔, 보안 쿠키, 공개 기본 비밀번호로 계정 생성 안 함
- `MFDS_DB_PATH=/app/data/regulatory/mfds_use_restriction.sqlite`, `MFDS_INGREDIENT_DB_PATH=/app/data/regulatory/mfds_ingredients.sqlite` (이미지에 포함된 식약처 규제 DB·성분 DB)
- 실행: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 150`

## 2. 챗봇 서비스

| 항목 | 값 |
|---|---|
| Runtime (Language) | Python 3 |
| Instance Type | **Free** |
| Root Directory | (비움 — 저장소 루트) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn "src.06_chatbot.server:app" --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --graceful-timeout 30 --access-logfile -` |
| Python 버전 | 환경변수 `PYTHON_VERSION=3.10.21` |
| Health Check Path | `/health` |
| Disk | 없음 |

- 챗봇은 Tesseract·한글 폰트가 필요 없다. `requirements.txt` 전체를 설치해도 동작에는 문제없다.
- Render Python 서비스의 저장소 위치는 `/opt/render/project/src` 이다. 식약처 DB 경로는 4장 표를 따른다.
- 챗봇은 Dockerfile 의 `ENV` 를 물려받지 않는다. `MFDS_DB_PATH`·`MFDS_INGREDIENT_DB_PATH` **두 개 모두** 챗봇 환경변수에 넣는다 (비우면 코드 기본값 `instance/regulatory/…` 을 찾다가 'DB 미설치' 오류).

## 3. 데이터 — 무엇이 유지되고 무엇이 초기화되나

Free 서비스는 **재배포·재시작·절전(15분 무요청) 때마다 로컬 파일이 사라진다.**

| 데이터 | 위치 | 무료 환경에서 |
|---|---|---|
| 식약처 규제 DB·성분 DB (읽기 전용) | 저장소 `data/regulatory/mfds_use_restriction.sqlite`, `data/regulatory/mfds_ingredients.sqlite` | **배포 파일에 포함 → 항상 같은 파일.** 서버가 재수집하지 않음 |
| 계정 (`users`) | 메인 `instance/cosmoa.db` | 초기화됨. 시작할 때 `COSMOA_DEMO_*` 로 시연 계정을 다시 만듦 |
| 홈 캐시 (환율·뉴스·규제 소식·수출입) | 메인 `instance/cosmoa.db`, 챗봇 `instance/cosmoa.db` | 초기화됨. 화면·챗봇 요청이 오면 기존 흐름대로 API 로 다시 수집 |
| 업로드·생성 파일 (규제 스캔, 개발요청서, 견적서 PDF) | 임시 파일·메모리 | 저장하지 않음 (영향 없음) |

- **시연 중 만든 계정·비밀번호 변경은 유지되지 않는다.** 로그인은 항상 `COSMOA_DEMO_*` 계정으로 한다.
  비밀번호를 바꾸려면 Render 에서 `COSMOA_DEMO_PASSWORD` 를 바꾸고 재배포한다 (새 DB 에 새 값으로 생성).
- 로그인 세션은 쿠키에 있고 `FLASK_SECRET_KEY` 가 고정이므로, 서버가 절전 후 깨어나도 로그인 상태는 유지된다.
- 캐시가 빈 직후에는 홈·챗봇에 잠시 "수집 중" 이 보이고, 수출입(공공데이터포털) 등 API 호출이 몰린다.
  절전에서 깰 때마다 반복되므로 발표 직전 준비(7장)로 미리 채워 둔다.

### 식약처 규제 DB · 성분 DB

| 항목 | 규제 DB | 성분 DB |
|---|---|---|
| 배포 파일 | `data/regulatory/mfds_use_restriction.sqlite` | `data/regulatory/mfds_ingredients.sqlite` |
| 역할 | 국가별 사용제한·금지 원료 (규제 조회) | 성분 사전 (한글명·영문명·이명·CAS 후보 검색) |
| 출처·이용조건 | 식약처 「화장품 사용제한 원료정보」, 공공데이터포털 이용허락범위 **제한 없음** | 식약처 「화장품 원료성분정보」, 공공데이터포털 이용허락범위 **제한 없음** |
| 수집본 | run 1, completed, 완료 2026-11-09T08:55:53Z | run 1, completed, 완료 2026-11-09T09:15:47Z |
| 건수 | 31,191건 | 21,968건 |
| SHA-256 | `bb4e2adf27d10cb8cc9f6810a23f4a97d3354f26bca5c48aa8f424ec9e2ed185` | `906e3555a190a9d32aaa7b746f787e46b25bbcfe9dd88b8bdeafb4f73fff4726` |

- 두 파일 모두 로컬 원본 `instance/regulatory/…`(Git 제외)의 바이트 그대로 사본이다. 수집 기록·페이지 해시·공공데이터만 있고 계정·개인정보·인증키 없음.
- 수집 시각은 데이터를 받은 시각이며 법령 개정일·최신성 보장이 아니다.
- 조회는 `mode=ro` (읽기 전용)로만 연다. 서버 시작·절전 복귀·검색 때 재수집하거나 DB 를 만들지 않는다 → 서버에 `MFDS_API_KEY` 불필요.
- `.gitignore`·`.dockerignore` 는 모든 `*.db`·`*.sqlite` 를 제외하고 **이 두 파일만** 예외로 포함한다 (`instance/`·`.env`·업무 DB·캐시 DB·업로드는 계속 제외).
- 갱신 절차·변경 기록은 `data/regulatory/README.md`. 갱신 후 두 서비스를 **같은 커밋**으로 배포한다.

## 4. 환경변수

실제 값은 Render Environment 에만 넣는다. 이름·설명은 `.env.example` 참고.

| 구분 | 이름 | 값·메모 |
|---|---|---|
| **메인** | `FLASK_SECRET_KEY` | 필수. 고정된 긴 난수 (`python -c "import secrets; print(secrets.token_hex(32))"`). 비어 있으면 서버가 시작하지 않음 |
| | `COSMOA_DEMO_EMAIL`, `COSMOA_DEMO_PASSWORD` | 필수. 시연 계정. 비어 있거나 공개 기본 비밀번호면 계정을 만들지 않음 |
| | `COSMOA_DEMO_NAME`, `COSMOA_DEMO_TEAM` | 권장. 화면·챗봇 메일 서명에 쓰임 |
| | `CHATBOT_URL` | `https://<챗봇 서비스 이름>.onrender.com` (끝 `/` 없이) |
| | `MFDS_DB_PATH` | `/app/data/regulatory/mfds_use_restriction.sqlite` (Dockerfile 기본값과 같음) |
| | `MFDS_INGREDIENT_DB_PATH` | `/app/data/regulatory/mfds_ingredients.sqlite` (Dockerfile 기본값과 같음, 2026-11-13 이미지에 포함) |
| | `REQUISITION_OPENAI_MODEL` | 선택 |
| **챗봇** | `PYTHON_VERSION` | `3.10.21` |
| | `MFDS_DB_PATH` | **필수** `/opt/render/project/src/data/regulatory/mfds_use_restriction.sqlite` (Dockerfile ENV 를 물려받지 않음) |
| | `MFDS_INGREDIENT_DB_PATH` | **필수** `/opt/render/project/src/data/regulatory/mfds_ingredients.sqlite` |
| | `CHATBOT_OPENAI_MODEL` | 선택, 기본 gpt-4.1 |
| **양쪽** | `OPENAI_API_KEY` | 메인은 개발요청서 자동변환, 챗봇은 답변 생성. **메인에서 빼지 않는다** |
| | `CHATBOT_SECRET` | 두 서비스에 **같은 값**. 운영 전용으로 새로 만든 긴 임의 문자열 (로컬 값·주소·예시 값 재사용 금지) |
| | `EXIM_API_KEY`, `DATA_GO_KR_KEY` | 홈 데이터 (두 서비스가 각자 수집) |
| **넣지 않음 (정리 대상)** | `RAPIDAPI_KEY`, `RAPIDAPI_HOST` | K-Beauty API 용 — 2026-11-11 코드·설정 안내에서 삭제. 이미 운영 서비스에 있으면 다음 배포 점검 때 메인·챗봇 양쪽에서 제거 (이번에는 운영 값을 바꾸지 않음) |
| | `COSMETIC_HS_CODES`, `KOTRA_NEWS_URL` | 선택 |
| **넣지 않음** | `TESSERACT_CMD`, `TESSDATA_PREFIX` | 로컬 Windows 경로. Docker 는 PATH·기본 tessdata 사용 |
| | `FLASK_DEBUG`, `FLASK_PORT`, `CHATBOT_PORT` | Gunicorn 에서 쓰지 않음 (포트는 Render `PORT`). `FLASK_DEBUG` 는 챗봇 debug 를 켜므로 넣지 않는다 |
| | `CHATBOT_DB_PATH` | 기본값(챗봇 `instance/cosmoa.db`) 사용 |
| | `MFDS_API_KEY` | 서버에서 재수집하지 않으므로 불필요 — 두 서비스 모두 배포 DB 만 읽어 키 없이 조회 |

## 5. 시간 제한

| 구간 | 제한 | 초과 시 화면 |
|---|---|---|
| 메인 → 챗봇 중계 | 연결 5초 + 응답 대기 90초 (`app.py`) | 504 "AI 비서 응답이 지연되고 있어요" |
| 챗봇 → OpenAI | 호출 1회 소켓 60초, 도구 왕복 최대 7회 | 챗봇 안에서는 전체 상한 없음 → 메인이 90초에 504 |
| 개발요청서 → OpenAI | 소켓 120초 (`src/05_requisition/service.py`) | 브라우저가 150초에 중단하고 안내 |
| Gunicorn `--timeout` | 메인 150 / 챗봇 120 | gthread(`--threads`) 에서는 worker 생존 확인 시간이라 **요청 시간 상한이 아님** |

- worker 는 1개다. 홈 데이터 수집 중복 방지가 프로세스 안에서만 동작하기 때문이다. 챗봇은 여기에 더해 **성분 후보 선택 상태(`SelectionStore`)가 서버 메모리에 있어** worker 를 늘리면 선택 버튼이 다른 worker 로 가서 실패한다 (`chatbot.md` 7-1). `--preload` 는 쓰지 않는다.
- 챗봇이 잠들어 있으면 깨어나는 데 약 1분이 걸린다. 여기에 답변 시간이 더해져 90초를 넘기면 504 가 난다 → 7장 준비 순서로 미리 깨운다.
- 후속 개선(담당자 F): `run_chat` 에 전체 처리 시간 상한(예: 80초)을 두어 메인이 끊은 뒤에도 OpenAI 호출이 계속되지 않게 한다.

## 6. 배포 순서와 확인

`/health` 200 이나 로그인 성공은 **서버가 떴다는 뜻일 뿐**, 외부 API 연동 성공이 아니다. 6번의 실제 조회까지 확인한다.

1. **챗봇 배포** — 2장 설정, 환경변수: 챗봇 + 양쪽.
2. **챗봇 상태 확인** — `https://<챗봇>.onrender.com/health`
   - 200 이면 서버 실행만 확인된 것
   - 본문 `configured: true` (OpenAI 키·시크릿이 **있음**), `sources.mfds_restriction_db`·`sources.mfds_ingredient_db: true` (식약처 규제 DB·성분 DB 를 **실제로 열어 완료된 수집본 확인**). 둘 다 배포 파일에 포함되어 있으므로 하나라도 `false` 면 챗봇 `MFDS_*_DB_PATH` 값(4장)을 확인
   - `exim_rates`·`trade_stats` 는 키가 **있는지만** 본다 (키가 맞는지는 6번에서 확인)
3. **메인 배포** — 1장 설정, 환경변수: 메인 + 양쪽. `CHATBOT_URL` 은 2번 주소, `CHATBOT_SECRET` 은 챗봇과 같은 값.
4. 메인 로그에 `데모 계정을 만들지 않았습니다` 경고가 없는지 확인 → `/login` 에서 `COSMOA_DEMO_*` 계정으로 로그인.
5. **규제 조회** — 규제 화면에서 성분 조회, 출처가 식약처 DB 로 표시되는지.
6. **실제 연동 확인**
   - 홈 환율·수출입이 채워지는지 (처음에는 "수집 중" 후 새로고침)
   - 챗봇에 환율 질문 → 답변에 기준일·출처, 챗봇 로그에 `도구 호출: get_exchange_rates`
   - 챗봇에 성분 규제 질문 → 식약처 DB 기준 답변
   - 개발요청서 파일 변환 (메인 `OPENAI_API_KEY`) — OpenAI 사용료 발생
   - 규제 화면 스캔 이미지 OCR (한글·영문), 마진 견적서 PDF 의 한글
7. **이름 변경 호환성 확인** (파일 이름 snake_case 통일, [개발 안내](development.md) 9-3)
   - 로그인·각 페이지의 아이콘(`/assets/common/img/apple_touch_icon.png`)이 200 인지.
   - 이전 주소 `/assets/common/img/apple-touch-icon.png` 는 **404** 다 (저장소 안 참조는 모두 새 주소). 이전 주소를 쓰는 외부 링크·저장된 홈 화면 아이콘이 있어 유지가 필요하면, 배포 전에 별도 우회 경로를 둘지 결정한다 (현재 없음).
   - `/assets/02_regulatory/samples/…` 의 시연 파일 이름도 바뀌었다. 시연 자료에 파일 주소를 적어 두었다면 새 이름으로 고친다.

오류 문구와 원인
| 챗봇 창 문구 | 원인 |
|---|---|
| AI 비서가 아직 연결되지 않았어요 (503) | 메인 `CHATBOT_URL` / `CHATBOT_SECRET` 없음 |
| 인증되지 않은 요청이에요 (401) | 두 서비스의 `CHATBOT_SECRET` 이 다름 |
| AI 비서가 아직 설정되지 않았어요 (503) | 챗봇 `OPENAI_API_KEY` 없음 |
| AI 비서 서버에 연결하지 못했어요 (502) | `CHATBOT_URL` 오타, 챗봇 서비스 중지·정지 |
| AI 비서 응답이 지연되고 있어요 (504) | 챗봇이 깨어나는 중이거나 답변이 90초 초과 → 잠시 후 다시 |

## 7. 발표 직전 준비 순서 (시작 10~15분 전)

절전 방지용 주기 호출(cron·외부 핑)은 두지 않는다. 발표 직전에 직접 깨운다.

1. 브라우저에서 `https://<챗봇>.onrender.com/health` 를 연다 → Render 로딩 화면 후 JSON 이 보이면 챗봇 준비 완료 (약 1분).
2. 메인 주소를 연다 → 로그인 화면이 뜰 때까지 기다린다 (약 1분).
3. 시연 계정으로 로그인 → 홈에서 환율·뉴스·수출입이 채워질 때까지 새로고침 (캐시가 비어 있으면 수집에 수십 초).
4. 규제 화면에서 시연할 성분을 한 번 조회한다.
5. 챗봇에 시연할 질문(환율·규제)을 한 번 보내 답변을 받는다. (챗봇 캐시도 이때 채워짐)
6. 발표 중 15분 넘게 한 서비스를 쓰지 않으면 다시 잠든다. 챗봇 시연 직전에 5번을 한 번 더 해 둔다.

## 8. 무료 한도와 과금 방지

Hobby 워크스페이스 기준 (2026-09-27 Render 문서 확인, https://render.com/docs/free)

| 항목 | 한도 | 넘으면 |
|---|---|---|
| Free 인스턴스 시간 | 워크스페이스당 월 750시간 (잠든 시간은 제외) | 그 달 남은 기간 **모든 Free 서비스 정지** (과금 없음) |
| 빌드 파이프라인 | 월 500분 | 결제수단이 있으면 추가 과금, 없거나 지출 한도에 닿으면 새 빌드만 막힘 |
| 아웃바운드 트래픽 | 월 5 GB | 결제수단이 있으면 GB당 과금, 없으면 Free 서비스 정지 |
| 기타 | 15분 무요청 시 절전·복귀 약 1분, 언제든 재시작 가능, 로컬 파일 초기화, 인스턴스 1개 | — |

- 두 서비스가 계속 깨어 있으면 월 약 1,440시간이 되어 750시간을 넘는다. 시연 기간에만 사용하고 평소에는 잠들게 둔다.
- **과금 방지**
  - 워크스페이스에 결제수단을 등록하지 않는다 → 한도를 넘어도 과금 대신 정지·빌드 중단.
  - 결제수단을 등록했다면 Workspace Settings → Build Pipeline → **Set spend limit** 을 `$0` 으로 둔다.
  - 서비스 Instance Type 이 **Free** 인지 생성 후 다시 확인한다 (새 서비스 기본값이 유료일 수 있음).
  - 사용량은 Billing → Monthly Included Usage 에서 확인, 한도 근접 시 메일이 온다.
- **빌드 시간 절약**: 저장소에 푸시할 때마다 두 서비스가 모두 빌드된다 (Docker 빌드는 수 분). 발표 준비 기간에는 두 서비스의 **Auto-Deploy 를 Off** 로 두고 필요할 때 **Manual Deploy** 로 같은 커밋을 배포한다.
