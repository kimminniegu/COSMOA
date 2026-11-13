# 배포용 식약처 DB (규제 DB · 성분 DB)

메인(Docker)·챗봇(Python) Render 서비스가 **읽기 전용**(`mode=ro`)으로 조회하는 배포용 사본 두 개입니다.
원본(수집 결과)은 로컬 `instance/regulatory/` (Git·Docker 제외)에 있고, 이 폴더의 파일은 원본을 **바이트 그대로 복사**한 것입니다.
서버는 시작·검색·조회 때 수집하거나 DB 를 만들지 않으며, `MFDS_API_KEY` 없이 조회합니다.

| 파일 | 역할 | 쓰는 곳 |
|---|---|---|
| `mfds_use_restriction.sqlite` | **규제 DB** — 국가별 사용제한·금지 원료 (규제 조회 결과의 근거) | 규제 화면 검색·조회, 챗봇 `search_ingredient`·선택 조회 |
| `mfds_ingredients.sqlite` | **성분 DB** — 화장품 원료 성분 사전 (한글명·영문명·이명·CAS 후보 검색) | 규제 화면 검색, 챗봇 `search_ingredient` |

두 DB 중 하나라도 없거나 완료된 수집본이 없으면 검색은 '검색 결과 없음'이 아니라 `db_missing`·`db_incomplete`·`db_error`(503) 오류를 냅니다. 다른 파일로 자동 대체하지 않습니다.

## 1. 규제 DB — `mfds_use_restriction.sqlite`

| 항목 | 값 |
|---|---|
| 출처 | 식품의약품안전처, 「화장품 사용제한 원료정보」 (공공데이터포털 https://www.data.go.kr/data/15111772/openapi.do) |
| 이용허락범위 | 제한 없음 (공공데이터포털 표시 기준, 2026-09-27 확인) |
| 수집본 | run 1 · `completed` · 시작 2026-11-09T08:52:13Z · **완료 2026-11-09T08:55:53Z** · `src/02_regulatory/mfds_use_restriction.py` |
| 건수 | 31,191건 (totalCount 처음·마지막 31,191, 312페이지) |
| 크기 | 47,161,344 bytes |
| SHA-256 | `bb4e2adf27d10cb8cc9f6810a23f4a97d3354f26bca5c48aa8f424ec9e2ed185` |
| 수집본 지문 (snapshot_id) | `a74e63a3d8a6f149` (후보 키 `mfds_restriction:<snapshot_id>:<id>` 에 들어감) |
| 내용 | `runs`(수집 기록, 인증키 없는 주소), `pages`(페이지별 응답 코드·해시), `records`(규제 원료 공공데이터) — 계정·개인정보·인증키 없음 |

## 2. 성분 DB — `mfds_ingredients.sqlite`

| 항목 | 값 |
|---|---|
| 출처 | 식품의약품안전처, 「화장품 원료성분정보」 (공공데이터포털 https://www.data.go.kr/data/15111774/openapi.do) |
| 이용허락범위 | 제한 없음 (공공데이터포털 표시 기준, `mfds_ingredients.py` 상단 기록) |
| 데이터셋 표시 | `meta.dataset = mfds_cosmetic_ingredients` (규제 DB 와 경로가 뒤바뀌면 `db_error`) |
| 수집본 | run 1 · `completed` · 시작 2026-11-09T09:13:19Z · **완료 2026-11-09T09:15:47Z** · `src/02_regulatory/mfds_ingredients.py` |
| 건수 | 21,968건 (totalCount 처음·마지막 21,968, 220페이지) |
| 크기 | 15,466,496 bytes |
| SHA-256 | `906e3555a190a9d32aaa7b746f787e46b25bbcfe9dd88b8bdeafb4f73fff4726` |
| 수집본 지문 (snapshot_id) | `e36457e0445f4c55` |
| 내용 | `meta`, `runs`, `pages`, `records`(원문 5개 필드 + raw_json) — 계정·개인정보·인증키 없음 |

> 수집 시각은 **데이터를 받은 시각**입니다. 법령 개정일이나 최신 규정 반영을 뜻하지 않습니다.

## 3. 경로

| 구분 | 규제 DB (`MFDS_DB_PATH`) | 성분 DB (`MFDS_INGREDIENT_DB_PATH`) |
|---|---|---|
| 원본 (로컬, Git 제외) | `instance/regulatory/mfds_use_restriction.sqlite` | `instance/regulatory/mfds_ingredients.sqlite` |
| 배포 사본 (저장소) | `data/regulatory/mfds_use_restriction.sqlite` | `data/regulatory/mfds_ingredients.sqlite` |
| 메인 (Docker) | `/app/data/regulatory/mfds_use_restriction.sqlite` (Dockerfile `ENV`) | `/app/data/regulatory/mfds_ingredients.sqlite` (Dockerfile `ENV`) |
| 챗봇 (Render Python) | `/opt/render/project/src/data/regulatory/mfds_use_restriction.sqlite` | `/opt/render/project/src/data/regulatory/mfds_ingredients.sqlite` |

- 챗봇은 Dockerfile 을 쓰지 않으므로 `ENV` 를 물려받지 않습니다. **두 변수를 챗봇 서비스 환경변수에 직접** 넣습니다 ([배포 안내 4장](../../docs/deploy_render.md)).
- 로컬 개발·수집 스크립트의 기본 경로는 `instance/regulatory/` 입니다 (변수를 비우면 그 경로).
- `.gitignore`·`.dockerignore` 는 모든 `*.db`·`*.sqlite` 를 제외하고 **위 두 배포 사본만** 예외로 포함합니다 (`instance/` 는 계속 제외).

## 4. 갱신 절차 (김민 PM·유정현)

1. 로컬에서 수집을 다시 실행해 `instance/regulatory/` 원본을 만든다. 수집기는 `MFDS_DB_PATH`·`MFDS_INGREDIENT_DB_PATH` 를 쓰므로 **로컬 원본 경로로 지정**해서 실행한다 (배포 사본에 직접 수집하지 않음). 서버는 자동으로 재수집하지 않는다.
2. 원본 확인: `status` 명령 또는 읽기 전용으로 `runs.status = completed`(또는 `completed_with_warnings`), `records_saved`, `PRAGMA integrity_check = ok`, 수집 중 프로세스·`-journal`/`-wal` 파일이 없는지.
3. 원본을 이 폴더로 **파일 그대로 복사**하고, 사본의 SHA-256 이 원본과 같은지·`integrity_check` 가 `ok` 인지 확인한다.
4. 위 표(수집본·건수·크기·SHA-256·snapshot_id)와 [배포 안내](../../docs/deploy_render.md) 3장 표를 새 값으로 고친다. 이전 값과 내용 차이를 아래 변경 기록에 남긴다.
5. 배포 사본 경로를 지정해 규제·챗봇 테스트와 대표 검색(Water·레티놀·페녹시에탄올)을 확인한다.
6. 커밋·푸시 후 **메인·챗봇 두 서비스를 같은 커밋으로** 재배포한다. 한쪽만 배포하면 두 서비스의 수집본(snapshot_id)이 달라진다.

- 재수집하면 내용이 같아도 snapshot_id 가 바뀌어, 이전 후보 키는 `stale_key`(409)가 된다. 화면·챗봇은 다시 검색하도록 안내한다.

## 5. 변경 기록

| 날짜 | 파일 | 내용 |
|---|---|---|
| 2026-11-13 (5-1단계) | 성분 DB | **새로 추가** — 2026-11-09 수집본 (21,968건) |
| 2026-11-13 (5-1단계) | 규제 DB | 2026-09-23 수집본(SHA-256 `e88d2e70…20d3aa`, snapshot `86a9368b10cc80ed`) → 2026-11-09 수집본으로 교체. **레코드 31,191건의 원문 값(raw_json 포함)과 312개 페이지 content_hash 는 이전과 모두 같음.** 바뀐 것은 수집 메타데이터(`runs.started_at`·`finished_at`, `pages`·`records` 의 `fetched_at`)뿐이고, 그에 따라 파일 SHA-256 과 snapshot_id 가 바뀜 (이전 후보 키는 stale_key) |
| 2026-09-23 | 규제 DB | 최초 배포 사본 (run 1, 2026-09-23T10:53:54Z, 31,191건) |
