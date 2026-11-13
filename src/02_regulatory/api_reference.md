# 국가별 인허가 규제 — API 참고 문서

담당자 B. `/api/regulatory/` Route 계약을 기록한다. 기능 요구사항은 `regulatory.md`가 우선이며, 이 문서는 구현된 계약과 실제 확인한 응답만 다룬다.

- **규제 화면은 식약처 수집 DB 두 개(성분 DB·규제 DB)만 읽는다.** 외부 API 호출·API 키가 없고, K-Beauty API 키(`RAPIDAPI_*`)가 필요하지 않다.
- 처리 모듈 (app.py [B] 영역에서 파일 경로로 로드): `regulatory_search.py`(후보 검색·key 검증·성분 연결·조회) · `regulatory_mfds_lookup.py`(규제 DB 읽기, `MARKET_CODES`) · `regulatory_extract.py` / `regulatory_ocr.py`(파일 추출)
- DB: 규제 DB `MFDS_DB_PATH`(기본 `instance/regulatory/mfds_use_restriction.sqlite`, 배포용 사본 `data/regulatory/`) · 성분 DB `MFDS_INGREDIENT_DB_PATH`(기본 `instance/regulatory/mfds_ingredients.sqlite`, 저장소 미포함). 서버는 `mode=ro` 로 읽기만 하며 **앱 시작·요청 때 수집하지 않는다.**
- 수집: 별도 스크립트 `mfds_use_restriction.py`(규제 DB) · `mfds_ingredients.py`(성분 DB)를 사람이 실행한다. `MFDS_API_KEY` 는 이 수집에만 쓰고 화면 조회에는 필요 없다. 배포 환경의 성분 DB 준비는 별도 후속 작업이다.
- 규제 화면과 챗봇(`src/06_chatbot/tools.py`)은 같은 `regulatory_search` 를 직접 쓴다. K-Beauty API(RapidAPI) 모듈·응답 기록·테스트·설정은 4-3단계(2026-11-11)에 삭제했다 — 외부 규제 API 호출과 그 키는 없다.
- 테스트: `python -m unittest discover -s src/02_regulatory/tests -v` (외부 호출 없음)

## 1. 내부 Route (브라우저 → Flask)

규제 Route 는 아래 세 개뿐이다 — `/api/regulatory/search` · `/api/regulatory/lookup` · `/api/regulatory/extract` (모두 로그인 필요). 직접 검색·파일 탭이 같은 Route 를 쓴다.

> 이전 경로 `/api/regulatory/ingredients` · `/api/regulatory/regulations` 는 **4-1단계(2026-11-11)에 삭제**했다 (요청 시 404). 기록은 부록 A.

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
- 응답은 규제 DB 조회 결과 필드(`regulatory_mfds_lookup.lookup_by_identity`·`_common_result`: source·source_label·source_page·data_source·disclaimer·collected_at·acquired_at·queried_at·refresh_policy·law_dates(null)·source_updated_at(null)·collection_run·country·entries·related·markets_listed)에 더해 `selection`(고른 후보) · `link`{status·basis·identity·candidates·conflict} · `ingredient_source` / `regulation_source`(출처별 수집 시각 따로) · `regulation_ingredient`. `ingredient` 는 사용자가 고른 후보 이름이다. `related` 는 확정 규제와 분리된 포함 일치 항목.
- 국가 검증: `regulatory_mfds_lookup.MARKET_CODES` (KR · EU · US · CN · JP · ASEAN, 소문자 입력은 대문자로).
- `entries[]`: country·country_code·regulate_type(원문)·notice_ingr_name·proviso·limit_condition(원문 그대로)·limit_missing·source_type(`mfds`)·std_name·eng_name·cas·record_id·page_no. 같은 성분·시장의 조건별 레코드를 합치지 않고 모두 담는다.
- `entries[].limit_missing`: ‘한도’인데 `LIMIT_COND` 가 비어 있음(화면 ‘상세 제한사항 미제공’). ‘금지’+null 은 `limit_missing=false` 이며 금지 항목으로 표시.
- 시장 매핑: KR→한국, EU→EU(원본 ‘유럽’ 제외), US→미국, CN→중국, JP→일본, ASEAN→아세안.
- `collected_at` 과 `acquired_at` 은 DB `runs.finished_at`(수집 완료 시각)이며 원천 갱신일이 아니다(값이 없으면 `null` → 화면 ‘수집 시각 미기록’). `queried_at` 은 DB 를 읽은 시각. `refresh_policy` = "수동 재수집 (자동 갱신 없음)", `law_dates` = `null`. `source_page` 는 공공데이터 안내 페이지(개별 법령 원문 링크 아님)이며 그 페이지의 수정일을 갱신일로 쓰지 않는다.
- 오류: `validation` 400 (key·국가 누락·형식) · `stale_key` 409 (key 의 수집본이 현재와 다름 → 다시 검색·선택) · `not_found` 404 · `db_missing` / `db_incomplete` / `db_error` 503.

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

## 2. 외부 API — 없음

규제 화면·챗봇 모두 외부 규제 API 를 호출하지 않는다. 이전에 쓰던 K-Beauty Cosmetic Ingredients API(RapidAPI)의 호출 방식·응답 기록은 4-3단계(2026-11-11)에 코드와 함께 삭제했다 (필요하면 Git 이력의 커밋 `b68f5bb` 이전 판을 본다).

## 3. 화면 흐름 (직접 검색, 2단계 — 식약처 수집 DB 전용)

1. 성분명(한글명·영문명·이명·CAS) 입력 → 앞뒤 공백 제거 후 2글자 이상이고 한글 조합이 끝난 뒤 300ms 동안 입력이 없으면 `/api/regulatory/search` → 검색창 아래 후보 최대 10개 (로딩 / 후보 없음 / 후보 검색 실패 중 하나만 표시). 후보마다 한글명·영문명·출처 배지(**성분정보**·**규제정보**)·일치 근거(예: '영문명 정확 일치 (나열된 이름 중 하나)', '이명 정확 일치 · 원문'). 목록 머리에 전체 후보 수·출처별 정확 일치 수, 잘렸으면 'N건 중 10건만 표시 — 검색어를 구체적으로'. 입력이 바뀌거나 목록이 닫히면 진행 중 응답은 무시한다(`acSeq`). 직접 검색에는 출처 선택지·함량·제품 조건 입력이 없다.
2. 후보 클릭 또는 ↑↓ + Enter 로 성분 선택 → 목록 닫힘, 검색창 아래 "선택한 성분 · 출처" 표시. **이 단계에서 규제 조회는 하지 않는다.**
   - **후보가 하나이거나 정확 일치가 하나여도 자동 선택·자동 조회하지 않는다** (이전의 '정확 일치 자동 확정'은 직접 검색 2단계·파일 매칭 3단계에서 모두 제거). 선택 전 검색 버튼은 후보 목록만 열고 '목록에서 직접 선택' 안내를 보인다. 목록이 열릴 때 활성 후보는 없다.
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
9. **4-1단계에서 정리한 것 (2026-11-11)** — 규제 화면 범위. 챗봇은 10항(4-2단계)에서 전환했다.
   - app.py: `/api/regulatory/ingredients`·`/api/regulatory/regulations` Route 와 처리 함수, `_regulatory_error`, `regulatory_service` 로드 삭제. `/lookup` 국가 검증은 `regulatory_mfds_lookup.MARKET_CODES` 로 전환 (지원 시장 6개 그대로).
   - regulatory.js: `SOURCE_LABEL.api` · `LOOKUP_LABEL` 의 `no_data`·`access` · `ACCESS_KINDS` 와 접근 제한 분기 · `note_mentions_plan`(요금제 안내) · api 출처 분기(`acquiredText`·`refreshText`·`sourceText`·`scopeText`·`noDataReason`·`statusLabel`·`sourceDescriptionNode`·`renderSingle`) · 상세 창의 `sel.code`·`record_updated_at`·'K뷰티 API 는 성분 code 로 조회' · `ingredientKr` 의 code 표시 · 외부 API HTTP 상태 표시. `not_listed` 는 식약처 문구('출처에서 일치 항목 없음')로, `hold` 는 확인되지 않은 상태값 방어용으로 남김.
   - regulatory.html: 상세 창 라벨('조회 안내 문구'·'성분 후보 출처·수집 시각')과 주석. regulatory.css: 쓰지 않는 출처 선택 카드(`.regulatory-source*`) 스타일.
   - 테스트: 삭제한 Route 테스트 제거, 삭제 확인(404·외부 HTTP 0회) 추가. K-Beauty 정규화·HTTP 분류 테스트는 모듈을 직접 로드해 유지(4-1 당시 챗봇용, 다음 정리 단계에서 삭제).
10. **4-2단계(챗봇 전환, 2026-11-11) — 완료.** `src/06_chatbot/tools.py` 가 `regulatory_search.search`·`lookup_candidate`(`resolve_key`)와 `regulatory_mfds_lookup.MARKET_CODES` 를 직접 쓴다. 후보는 채팅창 선택 카드로 보여 주고, 서버가 (로그인 사용자, 대화)별 최신 후보 목록과 사용자의 버튼 선택을 대조한 뒤에만 조회한다. `server.py` 는 `RAPIDAPI_*` 대신 두 DB 의 실제 상태로 안내한다. 상세: `src/06_chatbot/chatbot.md` 7-1.
11. **4-3단계(2026-11-11)에 삭제·정리한 것**
   - 코드: `regulatory_service.py` · `regulatory_mfds_lookup.lookup()`·`identify()`·`cas_tokens()`·`CAS_RE` · `test_data/*.json`(K-Beauty 응답 기록 9건).
   - 테스트: `tests/test_regulatory_service.py` 를 나눠 화면·자산·소스 보호·Route 목록은 `test_regulatory_routes.py`, 추출·시트 선택·OCR 은 `test_regulatory_extract.py` 로 옮기고 K-Beauty 정규화·HTTP 분류 테스트만 삭제. `lookup()` 테스트는 `test_mfds_lookup.py` 에서 `lookup_by_identity` 기준으로 옮김.
   - 설정·문서: `.env.example`·README·`docs/deploy_render.md`·`docs/team_onboarding.md`·`regulatory.md`·`chatbot.md` 의 K-Beauty 설정 안내, 이 문서 2장·부록 A 의 K-Beauty 계약. 로컬 `.env` 의 `RAPIDAPI_KEY`·`RAPIDAPI_HOST` 항목 삭제.
   - 유지: `regulatory_mfds_lookup` 의 `MARKET_CODES`·`MARKET_TO_COUNTRY`·`COMPLETED`·`MfdsLookupError`·`lookup_by_identity`·`related_items`·`open_readonly`·`latest_completed_run`·`db_status`(현재 호출처 없음, K-Beauty 무관이라 남김)·`_common_result`·`_entry`·`_identity`·`norm_name`, `regulatory_search`·`regulatory_extract`·`regulatory_ocr` 전체.
12. **남은 일 (배포 단계)**: 배포용 성분 DB(`MFDS_INGREDIENT_DB_PATH`) 준비 · 운영 서버(Render 메인·챗봇)에서 `RAPIDAPI_KEY`·`RAPIDAPI_HOST` 환경변수 제거 — 4-3단계에서는 운영 설정을 바꾸지 않았다.

**공통 CSS 관련 PM 협의 사항**: `src/common/style.css`에 `[hidden] { display: none }` 규칙이 없어 `.loading`, `.state`, `.badge`, `.alert`처럼 class로 `display`를 지정하는 요소는 `hidden` 속성이 무시된다(로딩·오류·후보 상태가 동시에 보이던 원인). 공통 파일은 수정하지 않고 `regulatory.css`에서 이 페이지 영역(`#regulatory-panel-search`, `#regulatory-panel-file`, `#regulatory-results`, `#regulatory-detail-modal`)에만 `[hidden] { display: none !important }`를 적용했다. 공통 CSS에 같은 규칙을 추가하면 페이지 규칙은 제거해도 된다.


## 부록 A. 삭제 기록 (과거)

| 단계 | 삭제한 것 |
|---|---|
| 4-1 (2026-11-11) | Route `GET /api/regulatory/ingredients` (K-Beauty 성분 검색) · `GET /api/regulatory/regulations` (`source=api` K-Beauty 규제 조회 / `source=mfds` 이름·CAS 재매칭 조회) — 요청 시 404 |
| 4-3 (2026-11-11) | 위 Route 의 처리 모듈 `regulatory_service.py` · `regulatory_mfds_lookup.lookup()` 과 그 계약·응답 설명 · K-Beauty 응답 기록 `test_data/` |

이전 계약·응답 형식은 현재 동작이 아니다. 필요하면 Git 이력(커밋 `b68f5bb` 이전 판의 이 문서)을 본다.
