# COSMOA AI 챗봇 명세서

| 항목 | 내용 |
|---|---|
| 프로젝트 | COSMOA (화장품 해외영업 업무지원 플랫폼) |
| 팀 | COSTD |
| 담당 범위 | 우하단 플로팅 AI 챗봇 (데이터 도구 호출 + 업무 비서) |
| 기술 스택 | Flask(독립 서버, Render 별도 배포), OpenAI Responses API(function calling), Vanilla JS 위젯 |
| 문서 버전 | v0.1 (2026-09-25) |

---

## 1. 페이지 목적

모든 화면의 우하단에 떠 있는 AI 비서다. 해외영업 담당자가 화면을 옮기지 않고 **환율·수출입·뉴스·규제·성분 규제**를 물어보고, **바이어 메일 초안·단가/환산 계산·문서 문구 정리** 같은 화장품 무역 업무를 도움받는다.

- 데이터 질문은 모델이 도구(function)를 호출해 **같은 저장소의 기존 모듈**에서 실제 값을 가져와 답한다. 지어내지 않는다.
- 화장품 무역과 관계없는 요청은 정중히 사양한다.
- 규제 답변은 참고 자료이며 허용·안전 판단이 아니라는 점을 항상 덧붙인다.

## 2. 담당 파일

```
src/06_chatbot/
├── chatbot.md              이 문서
├── server.py               독립 Flask 앱 (Render 별도 서비스). OpenAI 호출 + 도구 실행 반복
├── tools.py                도구 정의(JSON Schema, strict) + 실행. 기존 모듈 직접 import
├── chatbot_widget.html     위젯 템플릿 (base.html 마지막에 include)
├── chatbot.css             위젯 스타일 (chatbot- 접두사, 공통 Token 만 사용)
├── chatbot.js              위젯 동작 (IIFE, sessionStorage 로 대화 유지)
└── tests/test_chatbot.py   unittest (외부 API 호출 없음. 가짜 OpenAI 서버로 왕복 검증)
```

공용 파일에 덧붙인 것 (14장 참고): `app.py` [F] 영역, `src/common/base.html` include 1줄, `requirements.txt` gunicorn, `.env.example` CHATBOT_* 4개.

## 3. URL

| 서버 | 메서드 · URL | 설명 |
|---|---|---|
| COSMOA 본 서버 (app.py) | `POST /api/chatbot/message` | 위젯 → 중계. 로그인 세션 확인 후 챗봇 서버 `/chat` 으로 전달 (endpoint `chatbot_message`) |
| COSMOA 본 서버 | `GET /assets/06_chatbot/chatbot.css`, `chatbot.js` | 위젯 정적 파일 |
| 챗봇 서버 (server.py) | `GET /health` | 상태 확인 (Render Health Check 경로). `sources` 에 식약처 성분 DB·규제 DB 의 **실제 이용 가능 여부**(완료된 수집본 확인, 읽기 전용)와 환율·수출입 키의 **설정 여부**(값 없음)를 돌려줘 연결 문제를 바로 확인 |
| 챗봇 서버 | `POST /chat` | 헤더 `X-Chatbot-Secret` 일치 시에만 응답 |

브라우저는 챗봇 서버를 직접 호출하지 않는다. (CORS 없음, 시크릿은 서버끼리만 공유)

## 4. 사용자

로그인한 COSMOA 사용자 전원. 세션이 없으면 중계 Route 가 401 을 돌려주고 위젯이 재로그인을 안내한다. 로그인 화면(`login.html`)은 base.html 을 쓰지 않으므로 위젯이 없다.

## 5. 주요 기능

| 구분 | 기능 | 도구 |
|---|---|---|
| 데이터 조회 | 오늘 환율 · 전일 대비 · 환산 계산 | `get_exchange_rates` |
| | 화장품 수출입 실적 (월간, 12개월 추이, 상위국, 품목) | `get_trade_stats` |
| | 화장품 뉴스 검색 (수집 6개 매체 + 구글 뉴스) | `search_news` |
| | 해외 규제 소식 검색 (국가 필터) | `search_regulation_news` |
| | 성분 후보 검색 (식약처 성분 DB·규제 DB, 한글명·영문명·이명·고시원료명·CAS) → 채팅창에 선택 카드 | `search_ingredient` |
| | 사용자가 카드에서 고른 성분 × 국가 규제 조회 (식약처 규제 DB). **서버가 선택을 검증한 뒤 실행**, 모델 직접 호출은 거절 | `lookup_ingredient_regulation` |
| | 바이어 현지 시각 · 업무 시간 여부 | `get_local_time` |
| 업무 비서 | 바이어 메일·회신 초안(한/영), 견적·마진·환산 계산, 개발요청서·제안서 문구, 규제 용어 설명, 회의 요약 | 도구 없음 (모델) |
| 위젯 | 열기/닫기, 추천 질문 Chip, Enter 전송, 대화 지우기, 페이지 이동 후 대화 유지(탭 단위) | — |

## 6. 사용자 입력

| 입력 | 제한 | 처리 |
|---|---|---|
| 메시지 | 1건 4,000자, 대화 기록 최근 30건만 전송 | 앞뒤 공백 제거, 빈 메시지 무시 |
| 추천 질문 Chip | 고정 5개 | 클릭 시 해당 문장을 바로 전송 |
| 대화 지우기 | — | sessionStorage 기록 삭제, 빈 상태로. 대화 id 를 새로 만들어 이전 대화의 후보 선택 상태와 섞이지 않게 함 |
| 성분 후보 선택 카드 | 최신 카드만 선택 가능 | 국가 select(필수, 모델이 말한 국가는 기본값으로만) + 후보 버튼. 버튼을 눌러야 조회 요청(`selection`)이 나감. 이전 카드는 비활성 |

## 7. 처리 과정

```
브라우저 chatbot.js
  └─ POST /api/chatbot/message {messages:[{role, content}…], conversation_id, selection|null}   (같은 사이트, 세션 쿠키)
       └─ app.py chatbot_message : 세션 확인 → user{id, name, team}(세션 값) 추가 → POST {CHATBOT_URL}/chat (X-Chatbot-Secret)
            └─ server.py /chat : 시크릿 검증 → 메시지 검증 → run_chat()
                 ├─ selection 이 있으면 tools.run_selection() 으로 검증·조회 → 결과를 lookup_ingredient_regulation 의 function_call_output 으로 input 에 붙임
                 │    (검증 실패면 OpenAI 를 부르지 않고 "다시 검색" 안내만 반환)
                 ├─ OpenAI Responses API (instructions = system prompt + 현재 시각 + 사용자 + 출처 상태, tools = tools.TOOLS, store=false)
                 ├─ 응답에 function_call 이 있으면 tools.execute() 로 실행 → function_call_output 을 input 에 붙여 다시 호출
                 │    (최대 6회. 마지막 회차는 tool_choice=none 으로 답변만 받음)
                 └─ message 가 나오면 {"ok": true, "reply", "tools_used", "choices", "choices_reset"} 반환
       └─ 응답 상태코드·본문을 그대로 브라우저에 전달 → 위젯이 choices 를 선택 카드로 그림
```

- 대화 기록은 브라우저 sessionStorage 에만 있다 (`store: false`). 서버에 남는 것은 **성분 후보 선택 상태**뿐이다 (7-1).

### 7-1. 성분 후보 선택 (K-Beauty 제거 4-2단계, 2026-11-11)

규제 화면과 같은 원칙 — **검색 → 후보 표시 → 사용자 선택 → 선택 국가 규제 조회**. 검색·연결·판정은 `src/02_regulatory/regulatory_search.py` 의 `search`·`lookup_candidate`(내부에서 `resolve_key`)를 그대로 쓰고 챗봇에 별도 로직을 두지 않는다.

1. 모델이 `search_ingredient(query, market|null)` 호출 → 후보(최대 10개)를 찾는다. 후보 key 는 **서버 `SelectionStore` 에만** 저장하고, 모델에는 순번·한글명·영문명·출처(성분정보/규제정보)·일치 근거(표준명·영문명 / 이명 / 고시원료명 / CAS 구분)·total·exact_total·truncated 만, 브라우저에는 여기에 `offer_id`(임의 값)를 더한 선택 카드를 준다. 정확 일치가 하나여도 자동 확정·조회하지 않고, 출처가 다른 동명 후보를 합치지 않는다.
2. 사용자가 카드에서 국가를 고르고 후보 버튼을 누르면 위젯이 `selection {offer_id, index, market}` 을 보낸다. 서버는 (로그인 사용자 id, 대화 id) 의 **현재 유효한 목록**에서 offer_id·순번을 찾아 key 를 꺼내고, 그때만 `lookup_candidate(key, market)` 를 실행한다.
   - 목록 없음·다른 대화·다른 사용자·이전(교체된) 목록·만료·임의 offer_id·없는 순번·국가 미선택은 모두 거절 (조회·OpenAI 호출 없음). 브라우저가 key 를 보내도 쓰지 않는다 (중계 Route 가 offer_id·index·market 만 전달).
   - 모델이 `lookup_ingredient_regulation` 을 직접 호출하면 `selection_required` 만 돌려준다 (confirmed 같은 값을 만들어도 무시).
3. 결과 상태: 규제 정보 조회됨(found) / 선택 국가 기록 없음(no_market_record) / 성분 연결 확인 필요(link_required) / 규제 성분 연결 미확인(not_linked) / 조회 오류. 결과에 처음 고른 성분·조회한 규제 성분·연결 근거·국가·규제 원문·성분정보/규제정보 수집 시각(법령 개정일 아님)·참고 자료 안내를 담는다.
4. 성분 연결 확인 필요 → 연결 후보를 새 카드(국가 고정)로 보여 주고, 사용자가 고른 규제 성분으로 다시 조회한다. 처음 고른 성분과 연결 충돌 사유는 `first_selected` 로 보존한다.
5. `stale_key`·`not_found`(수집본 변경) → 그 대화의 선택 상태를 지우고 `choices_reset` 으로 이전 카드를 비활성화, 다시 검색하도록 안내. DB 누락·미완료·읽기 오류는 '출처 이용 불가'로, 검색 결과 없음(200, total 0)과 구분한다. 다른 출처·다른 성분으로 대체하지 않는다.
6. 상태 갱신: 한 요청에서 새 목록을 만들면 그 대화의 이전 목록은 모두 무효. '대화 지우기'는 새 대화 id. 상태는 서버 메모리(TTL 2시간, 워커 1개 전제)라 서버가 다시 시작되면 사라지고, 사용자는 다시 검색한다. 브라우저 기록에는 key 가 없고, 과거 답변의 이름·순번으로 조회할 수 없다.
- 도구 결과는 JSON 문자열(최대 7,000자)로 모델에 전달하고, 결과 안의 문장은 지시로 따르지 않도록 system prompt 에 명시한다. 길면 `fit_output()` 이 가장 긴 문자열부터 줄이고 목록 뒤 항목을 빼되 **항상 유효한 JSON** 을 유지하며, 줄인 경로를 `_output_truncated` 에 남긴다. 규제 조건은 최대 10건(`entries_total`·`entries_shown`·`entries_note`)이며 일부만 전달했으면 일부라고 답하게 한다.

## 8. 출력 결과

- 답변은 해요체 한국어(영어 질문은 영어). 채팅창 폭에 맞춰 표·제목·코드블록 없이, `- ` 목록과 `**굵게**` 만 쓴다.
- 위젯은 HTML 을 escape 한 뒤 `**굵게**`, `- 목록`, URL 링크만 변환해 표시한다. (모델 출력의 HTML 은 실행되지 않음)
- 숫자에는 기준일·출처를 함께 적는다. 규제 결과에는 "참고 자료, 최종 판단은 담당자·법령 원문 확인" 문구를 붙인다.

## 9. API / 외부 데이터

| 구분 | 출처 | 모듈 | 환경변수 |
|---|---|---|---|
| 모델 | OpenAI Responses API (`/v1/responses`, function calling, strict schema) | server.py (SDK 없이 urllib — 05_requisition 과 같은 방식) | `OPENAI_API_KEY`, `CHATBOT_OPENAI_MODEL`(기본 gpt-4.1) |
| 환율 · 수출입 · 뉴스 · 규제 소식 | 홈 데이터 캐시(SQLite) + 백그라운드 수집 | `src/01_home/home_data.py` 직접 import | `EXIM_API_KEY`, `DATA_GO_KR_KEY`, (선택) `KOTRA_NEWS_URL`, `COSMETIC_HS_CODES` |
| 성분 검색 · 규제 | 식약처 화장품 원료성분정보(성분 DB) + 사용제한 원료정보(규제 DB) 수집 DB (읽기 전용, 규제 화면과 같은 모듈) | `src/02_regulatory/regulatory_search.py` (`search`·`lookup_candidate`·`db_status`), 시장 코드 `regulatory_mfds_lookup.MARKET_CODES` | `MFDS_INGREDIENT_DB_PATH`, `MFDS_DB_PATH` (기본 instance/regulatory/). 외부 API·키 없음, 수집하지 않음 |

K-Beauty API(RapidAPI)는 4-2단계(2026-11-11)부터 챗봇에서 쓰지 않으며, 4-3단계에 모듈·설정을 삭제했다. 챗봇 서버에 `RAPIDAPI_*` 를 두지 않는다.

기존 모듈은 로그인 세션에 의존하지 않아 분리 없이 그대로 쓴다. 폴더명이 숫자로 시작하므로 `importlib.import_module` / `spec_from_file_location` 으로 불러온다.

## 10. 데이터 처리

- 도구 결과는 화면용 응답을 그대로 넘기지 않고 **모델에 필요한 필드만 축약**한다. (뉴스: 출처·제목·URL·시각, 규제: 국가·유형·고시명·제한조건·단서)
- 규제 원문(`limit_condition`, `proviso`, `result_note`, `disclaimer`)은 가공하지 않는다. `lookup_status` 가 not_listed 여도 "허용" 으로 바꾸지 않는다.
- 식약처 DB 가 없거나 수집 미완료·읽기 오류면(`db_missing`·`db_incomplete`·`db_error`) '출처 이용 불가'로 모델에 전달하고, 다른 출처로 **자동 전환하지 않는다**. system prompt 에 매 요청마다 성분 DB·규제 DB 의 실제 상태(`data_sources_status()`)를 넣는다. 서버 시작·질문 처리 중 식약처 데이터를 수집하지 않는다.
- 로컬 챗봇 서버는 시작할 때 `.env` 를 읽는다. 키를 나중에 추가했으면 서버를 다시 띄워야 한다 (debug 모드에서는 `.env` 저장 시 자동 재시작).
- 홈 캐시가 비어 있으면 환율은 즉시 1회 조회하고, 뉴스·규제·수출입은 백그라운드 수집을 시작한 뒤 "수집 중" 안내를 돌려준다.
- 챗봇 서버는 Render 에서 **본 서버와 디스크를 공유하지 않는다.** 캐시 DB(`CHATBOT_DB_PATH`)를 따로 두고 같은 수집 코드로 채운다. 로컬에서는 기본값이 `instance/cosmoa.db` 라 본 서버와 공유된다. 식약처 수집 DB 는 챗봇 서버에도 복사하거나 `MFDS_DB_PATH` 로 지정해야 조회된다.

## 11. 예외 처리

| 상황 | 상태 | 사용자에게 보이는 문구 (요지) |
|---|---|---|
| 로그인 세션 없음 | 401 | 로그인이 만료됐어요 + 로그인 링크 |
| 본 서버에 CHATBOT_URL / SECRET 없음 | 503 | AI 비서가 아직 연결되지 않았어요 |
| 시크릿 불일치 | 401 | 인증되지 않은 요청이에요 (브라우저에는 그대로 전달됨) |
| 챗봇 서버에 OPENAI_API_KEY 없음 | 503 | AI 비서가 아직 설정되지 않았어요 |
| OpenAI 401/403 · 404 · 429 · 크레딧 부족 | 503 | 인증 실패 / 모델 사용 불가 / 사용량 많음 / 크레딧 부족 (원문은 노출하지 않음) |
| 대화가 컨텍스트 한도 초과 | 413 | 대화를 지우고 다시 시작해 주세요 |
| 챗봇 서버 연결 실패 · 응답 지연(90초) | 502 · 504 | 연결하지 못했어요 / 지연되고 있어요 |
| 도구 실행 오류 | 200 | 모델이 결과의 오류 안내를 전달 (대화는 계속) |
| 후보 선택 검증 실패 (목록 없음·다른 대화·이전 목록·만료·잘못된 순번/국가) | 200 | "최신 후보 목록이 아니거나 만료된 선택이에요. 다시 검색해 주세요" (조회·OpenAI 호출 없음) |
| 선택 후보의 수집본 변경 (`stale_key`·`not_found`) | 200 | 후보 다시 선택 필요 — 이전 카드 비활성, 다시 검색 안내 |
| 식약처 DB 이용 불가 | 200 | 출처 이용 불가 (DB 미설치·수집 미완료·읽기 오류) — 검색 결과 없음과 구분 |
| 도구 호출 6회 초과 | 502 | 질문을 나눠서 다시 물어봐 주세요 |
| 요청 본문 256KB 초과 | 413 | 대화를 지우고 다시 시도 |

오류는 채팅창에 빨간 말풍선으로 보이며, 기록에는 저장하지 않는다.

## 12. UI 구성

| 요소 | 규격 |
|---|---|
| 위치 | `position: fixed`, 우하단 24px. z-index 는 Sidebar/Header 위, Modal(200) 아래 (190) |
| 런처 | 56px 원형 `--color-primary`, 흰 채팅 아이콘(inline SVG), `--shadow-overlay`. 열리면 × 아이콘 |
| 패널 | 380 × min(640px, 화면 높이) 흰색 Card, `--radius-2xl`, `--shadow-overlay`, 열릴 때 Modal 과 같은 0.28s 진입 |
| 헤더 | Icon Tile(primary-soft) + "AI 비서" + 부제, 대화 지우기·닫기 Icon Button |
| 빈 상태 | 안내 문구 + 추천 질문 Chip 5개 (Pill, primary-soft) |
| 말풍선 | 사용자: primary 배경 흰 글자 우측 / AI: `--color-background` 좌측 / 오류: danger-soft. 15px, 최대 폭 88% |
| 입력 | `textarea.form-control.form-control-sm` 44px(최대 120px 자동 확장) + `btn btn-primary btn-icon` 전송 |
| 로딩 | 공통 `.spinner.spinner-sm` + "답변을 준비하고 있어요" |
| Mobile ≤640px | 패널 전체 화면, 런처 숨김 |
| 접근성 | 런처 `aria-expanded/controls`, 패널 `role=dialog`, 메시지 영역 `aria-live=polite`, ESC 로 닫기(Modal 이 열려 있으면 Modal 우선) |
| 성분 선택 카드 | 답변 아래 흰 카드(`--border-default`, `--radius-lg`): 제목(검색어·건수), 잘림 안내, 국가 `select.form-control.form-control-sm`, 후보 버튼(이름·영문명 + 공통 `.badge` 출처 + 일치 근거). 이전 카드는 흐리게·비활성. 값은 모두 textContent 로 넣음 |

새 공통 컴포넌트는 만들지 않았다. Button·Input·Spinner 는 공통 Class 그대로, 나머지는 `chatbot-` 접두사.

## 13. Flask / app.py 연동

**본 서버 (app.py [F] 영역)**

```python
@app.route("/api/chatbot/message", methods=["POST"])   # 세션 확인 → requests.post(CHATBOT_URL + "/chat")
```
`.env`: `CHATBOT_URL`, `CHATBOT_SECRET` 두 개만 필요. OpenAI 키는 본 서버에 두지 않는다.

**챗봇 서버 (Render 별도 서비스, 같은 저장소)**

| 항목 | 값 |
|---|---|
| Root Directory | (비움 — 저장소 루트) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn "src.06_chatbot.server:app" --bind 0.0.0.0:$PORT --timeout 120` |
| Health Check Path | `/health` |
| 환경변수 | `OPENAI_API_KEY`, `CHATBOT_SECRET`(본 서버와 동일), `CHATBOT_OPENAI_MODEL`(선택), `EXIM_API_KEY`, `DATA_GO_KR_KEY`, (선택) `CHATBOT_DB_PATH`, `MFDS_DB_PATH`, `MFDS_INGREDIENT_DB_PATH`. K-Beauty(`RAPIDAPI_*`) 설정 없음. 성분 DB 는 아직 배포본에 없어 배포 환경 성분 검색은 '출처 이용 불가' — 별도 후속 작업 |
| 워커 | **1개** 유지 — 성분 후보 선택 상태가 서버 메모리에 있음 (7-1) |

**로컬 실행** (터미널 2개)

```bash
python src/06_chatbot/server.py     # 챗봇 서버, http://127.0.0.1:5100  (.env 의 OPENAI_API_KEY, CHATBOT_SECRET 사용)
python app.py                       # 본 서버. .env 에 CHATBOT_URL=http://127.0.0.1:5100, CHATBOT_SECRET=<같은 값>
```

로컬에서는 `.env` 하나를 두 서버가 함께 읽으므로 `OPENAI_API_KEY` 와 `CHATBOT_*` 를 모두 `.env` 에 두면 된다.

## 14. 수정 가능 파일

- `src/06_chatbot/` 전체
- `app.py` — `# [F] AI 챗봇` 주석 아래만
- `src/common/base.html` — `{% include "06_chatbot/chatbot_widget.html" ignore missing %}` 1줄 (PM 승인)
- `requirements.txt` 끝에 `gunicorn`, `.env.example` 끝에 `CHATBOT_*`

## 15. 수정 금지 영역

- `src/01_home/`, `src/02_regulatory/` 등 다른 담당자 모듈 — **import 만** 하고 고치지 않는다. 필요한 변경은 담당자에게 요청
- `app.py` 의 페이지 Route · 로그인 · 다른 담당자 영역
- `src/common/style.css`, `common.js`, `docs/*.md`, `README.md`

## 16. 완료 조건

- [x] 모든 페이지(로그인 제외) 우하단에 런처가 보이고, 열기/닫기/추천 Chip/Enter 전송/대화 지우기가 동작한다
- [x] 페이지를 이동해도 같은 탭에서는 대화가 유지된다 (sessionStorage)
- [x] 데이터 질문에 도구가 호출되고, 결과 기준일·출처가 답변에 포함된다 (가짜 OpenAI 로 왕복 검증)
- [x] 시크릿 불일치 401, 세션 없음 401, 설정 없음 503, OpenAI 오류는 원문 노출 없이 한글 안내
- [x] `python -m unittest src/06_chatbot/tests/test_chatbot.py` 통과 (외부 API 호출 없음)
- [x] 성분 규제: 검색 → 카드 선택 → 서버 검증 후 조회 (`tests/test_chatbot_regulatory.py`, 임시 DB·가짜 OpenAI·외부 HTTP 차단, 위젯은 Node 최소 DOM 대역으로 실행)
- [ ] 실제 브라우저·실제 OpenAI 로 성분 후보 선택 흐름 확인 (담당자 수행)
- [ ] Render 에 챗봇 서비스 배포 후 `/health` 200 확인, 본 서버 `.env` 에 `CHATBOT_URL` 연결 (담당자 수행)
- [ ] 실제 OpenAI 키로 환율·규제·메일 초안 3가지 시나리오 확인 (담당자 수행)

---

## 부록. README 반영 예정 내용 (PM 이 직접 반영)

README 는 PM 관리 파일이라 여기에만 적어 둔다. 반영 위치와 문구는 아래와 같다.

**프로젝트 구조 트리** (`src/` 아래)
```
    └── 06_chatbot/           server.py / tools.py / chatbot_widget.html / .css / .js / .md   [F] AI 챗봇 (Render 별도 서비스)
```

**페이지 URL 표**
```
| `/api/chatbot/message` | `chatbot_message` | 위젯 → 챗봇 서버 중계 (로그인 필요) | F |
```

**팀원별 담당 폴더 표**
```
| **F** | AI 챗봇 (우하단 위젯 + 별도 서버) | `src/06_chatbot/`, `app.py`의 `[F]` 영역 |
```

**.env 설정 블록** (본 서버에는 두 개만 필요. `OPENAI_API_KEY` 는 챗봇 서버에만)
```
CHATBOT_URL=          # 챗봇 서버 주소 (로컬 http://127.0.0.1:5100)
CHATBOT_SECRET=       # 본 서버 ↔ 챗봇 서버 공유 비밀값 (양쪽 동일)
```

**Git 작업 시 주의사항의 Branch 예시**에 `feature/chatbot` 추가.

**설치 및 실행**에 한 줄: 챗봇을 함께 쓰려면 터미널 하나에서 `python src/06_chatbot/server.py` 를 추가로 실행한다. (Render 설정은 이 문서 13장)
