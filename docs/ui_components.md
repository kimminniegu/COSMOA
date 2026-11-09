# UI Components — COSMOA

> **반복적으로 사용하는 UI 요소의 규격 문서입니다. (PM 관리)**
>
> - 공통 UI 요소는 각 담당자가 **새로 디자인하지 않고** 이 문서의 HTML 구조와 Class를 그대로 사용합니다.
> - 스타일은 `src/common/style.css`, 동작은 `src/common/common.js`에 구현되어 있습니다. 페이지 CSS에서 다시 정의하지 않습니다.
> - 색상·크기 등 Token은 `docs/design_system.md`를 따릅니다.
> - 여기에 없는 컴포넌트가 필요하면: 한 페이지에서만 쓰면 자기 폴더 CSS에(`<페이지>-` 접두사, Token은 Variable 사용), 여러 페이지에서 쓰면 PM에게 요청해 이 문서에 추가합니다.

**디자인 원본**: `docs/reference/main.dc.html`, `docs/reference/login.dc.html` (v1.0, 2026-09-21 반영)

**공통 원칙**

- Card·Button·Input에는 **Border가 없습니다.** 배경색 차이로 구분하고, Card에는 거의 보이지 않는 `--shadow-card`만 적용됩니다.
- **Input / Select / Tabs / Table / 회색 Button은 흰색 Card 안에** 배치합니다. 회색 페이지 배경 위에는 흰색 요소(`.card`, `.btn-surface`)만 놓습니다.
- Icon은 inline Line SVG(`stroke="currentColor"`, `stroke-width="2"`, 24×24 viewBox)만 사용합니다. Emoji 금지.
- 글자 굵기는 `--font-weight-regular`(본문) / `--font-weight-bold`(버튼·소제목) / `--font-weight-extrabold`(큰 제목·대표 수치) 3종만 사용합니다.
- 공통 상태 Class: `.is-active` `.is-selected` `.is-error` `.is-disabled` `.is-open` (+ 표준 `disabled` 속성)

---

## 1. Header

- **Desktop에는 상단 Header가 없습니다.** 페이지 상단은 `.page-header`(날짜 + 제목)로 시작합니다.
- ≤1024px에서만 상단 Bar(`.app-header`, 60px, 흰색)가 나타나며 햄버거 버튼과 로고를 표시합니다.
- **위치**: `src/common/base.html` — 담당자는 수정하지 않습니다.
- **CSS Class**: `.app-header` `.app-header__toggle` `.app-brand` `.app-brand__logo` `.app-brand__name` `.app-brand__sub`

## 2. Navigation

- **용도**: 페이지 간 이동. Sidebar 안에 위치
- **위치**: `src/common/base.html` — **메뉴 추가/변경은 PM만** 수행
- **CSS Class**: `.app-nav` `.app-nav__label` `.app-nav__link`
- **크기/여백**: 항목 높이 48px, 좌우 Padding 14px, radius 12px, Icon 20px + gap 12px, 15px / Regular, 항목 간격 4px
- **상태**: 기본 `#4E5968` / Hover → 배경 `surface-muted` / Active → `.is-active` 배경 `primary-soft` + 글자 `primary` + Bold (현재 URL 기준 자동 적용, `aria-current="page"`)
- 링크는 반드시 `url_for()` 사용: `href="{{ url_for('regulatory') }}"`

| 순서 | endpoint | URL | 메뉴명 |
|---|---|---|---|
| 1 | `home` | `/` | 홈 |
| 2 | `margin` | `/margin-calculator` | 원가·마진 시뮬레이션 |
| 3 | `dev_request` | `/dev-request` | 개발요청서 |
| 4 | `regulatory` | `/regulatory` | 국가별 인허가 규제 |
| 5 | `simulation` | `/ai-formulation` | AI 제형모델링 |

## 3. Sidebar

- **용도**: 좌측 고정 영역 — 로고 / 메뉴 / 사용자 영역(하단)
- **CSS Class**: `.app-sidebar` `.app-sidebar__head` `.app-sidebar__collapse` `.app-sidebar-backdrop` `.app-nav__text` `.app-user` `.app-user__avatar` `.app-user__name` `.app-user__team`
- **크기**: 너비 264px(펼침) / 80px(접힘), 전체 높이, 흰색, Padding 32px 20px, 블록 간격 40px
- **상태 (Desktop ≥1025px)**: 로고 옆 `[data-sidebar-collapse]` 버튼으로 접기/펼치기. 접히면 `<html class="is-sidebar-collapsed">`가 붙고 아래처럼 내용이 바뀝니다. 상태는 `localStorage("cosmoa.sidebar")`에 저장되어 페이지 이동·새로고침 후에도 유지됩니다.
  - 로고: 텍스트 숨김, 아이콘만 / "메뉴" 라벨 → 얇은 구분선 / 메뉴: 아이콘만 가운데 정렬, Hover 시 우측에 메뉴명 Tooltip(`data-label`) / 사용자 영역: 아바타만
  - 본문(`.app-main`)의 좌측 여백도 함께 줄어듭니다 (0.28s Transition)
  - 페이지 JS에서 강제로 바꿔야 할 때: `Common.setSidebarCollapsed(true | false)`
- **상태 (≤1024px)**: 숨김 → `[data-sidebar-toggle]` 클릭 시 `.is-open` (Drawer, 항상 펼친 모양). 배경 클릭 / ESC로 닫힘. 접기 버튼은 표시되지 않습니다.
- 사용자 영역(`.app-user`): 아바타 + 이름/소속 버튼(`.app-user__main`, `data-modal-open="app-user-modal"`) + 로그아웃 링크(`.app-user__logout`, `/logout`). 접힘 상태에서는 아바타와 로그아웃 아이콘만 세로로 표시됩니다.
- 내 계정 모달(`#app-user-modal`, `base.html`): 아바타·이름 클릭 시 열림. ① 로그인 정보 — 이메일·소속·로그인 시각·로그인 유지 여부(세션 `current_user`의 `logged_in_at`, `remember`), ② 대시보드 소개 — "COSTD · 화장품 ODM 해외영업 업무지원 플랫폼" 한 줄과 소개 문단, 기능 4가지(메뉴 순서·이름과 동일, `.app-about__features`), 회사 정보(회사명 COSTD · 전화 02-6000-5968 · 주소 서울특별시 강남구 영동대로 513 COEX(코엑스 전시장 4층) 스터디룸 3, `.app-about__list--company`). Footer에 로그아웃·닫기. Class 접두사 `app-about-`.
- 로그인 화면은 공통 Layout 을 쓰지 않는 독립 화면입니다: `src/common/login.html` + `login.css` (Class 접두사 `login-`). 좌측 소개 패널(`--color-background`) + 우측 400px 폼, ≤1024px 에서 1열. 소개 패널은 제목 + 기능 4가지(메뉴 순서·이름과 동일: 원가·마진 시뮬레이션, 개발요청서 생성·변환, 국가별 인허가 규제, AI 제형샘플)이며 설명 문단은 없음. "비밀번호 찾기"(`.login-form__link`)를 누르면 PM 문의 안내(`alert-info`, `#login-forgot-note`)가 폼 안에 펼쳐집니다(재설정 기능 없음).

## 4. Button

- **용도**: 사용자 액션. 한 영역에 Primary는 1개만 사용

```html
<button type="button" class="btn btn-primary">저장</button>
<button type="button" class="btn btn-soft">이어서 계산</button>
<button type="button" class="btn btn-secondary">취소</button>      <!-- Card 안 -->
<a class="btn btn-surface" href="{{ url_for('home') }}">← 홈으로</a> <!-- 페이지 배경 위 -->
<button type="button" class="btn btn-ghost">더보기</button>
<button type="button" class="btn btn-danger">삭제</button>
<button type="button" class="btn btn-surface btn-icon" aria-label="알림"><svg>…</svg></button>
```

| Class | 배경 / 글자 | 사용 위치 |
|---|---|---|
| `.btn-primary` | `#1B64DA` / 흰색 | 주요 액션 |
| `.btn-soft` | `#E8F3FF` / `#1B64DA` | 보조 강조 액션 |
| `.btn-secondary` | `#F2F4F6` / `#4E5968` | 흰색 Card 안의 일반 액션 |
| `.btn-surface` | 흰색 / `#4E5968` | 회색 페이지 배경 위의 일반 액션 |
| `.btn-ghost` | 투명 / `#6B7684` | 약한 액션 |
| `.btn-danger` | `#E42939` / 흰색 | 삭제 등 |

- **크기**: `.btn-sm` 36px·r10·14px / 기본 48px·r14·16px / `.btn-lg` 56px·r16·17px / `.btn-icon` 44×44·r12 / `.btn-block` 가로 100%
- **공통**: Border 없음, Bold, 좌우 Padding 20px
- **Hover**: Primary → `#1957C2`, 나머지 → 한 단계 진한 배경
- **Disabled**: `disabled` 또는 `.is-disabled` → 투명도 45%, 클릭 불가
- **Loading**: 버튼 안에 `<span class="spinner spinner-sm"></span>` + `disabled`

## 5. Card

- **용도**: 정보 묶음의 기본 컨테이너. 흰색, radius 24px, **Border 없음**, 미세 Shadow(`--shadow-card`, 공통 CSS에서 자동 적용)

```html
<div class="card">
  <div class="card-header">
    <div>
      <h3 class="card-title">제목</h3>
      <p class="card-subtitle">기준·출처 등 (선택)</p>
    </div>
    <!-- 우측 액션 (선택) -->
  </div>
  <div class="card-body">내용</div>
  <div class="card-footer"><a href="#">전체 보기</a></div>
</div>
```

- **CSS Class**: `.card` `.card-header` `.card-title` `.card-subtitle` `.card-body` `.card-footer` / 작은 Card `.card.card-sm`(radius 20px, Padding 18px)
- **크기/여백**: Padding 32px, Header ↔ Body 24px. Header와 Body 사이에 구분선 없음
- **Hover**: 클릭 가능한 Card(`<a class="card">` 또는 `.card.is-clickable`)만 → 2px 위로 이동
- **Selected**: `.card.is-selected` → 배경 `#191F28`, 글자 흰색 (여러 Card 중 하나를 선택하는 UI)
- **Card 안의 보조 요소**
  - `.stat-tile` > `.stat-tile__label` + `.stat-tile__value` — `#F9FAFB` 배경 r16의 작은 수치 패널
  - `.icon-tile` — 48×48 r14 `primary-soft` 배경의 Icon 박스

## 6. KPI Card

- **용도**: 핵심 수치 1개 표시

```html
<div class="card kpi-card">
  <p class="kpi-label">지표명 · 기준</p>
  <p class="kpi-value">1,234<span class="kpi-unit">원</span></p>
  <p class="kpi-delta is-up">▲ 0.32% 전일 대비</p>
</div>
```

- **CSS Class**: `.kpi-card` `.kpi-label` `.kpi-value`(32px) `.kpi-value-lg`(40px, 페이지 대표 수치) `.kpi-value.is-primary`(파란 강조) `.kpi-unit` `.kpi-delta`
- **상태**: `.kpi-delta.is-up` → **빨강**(상승) / `.is-down` → **파랑**(하락) / 없음 → Gray. `▲` `▼` 기호와 함께 표기
- **배치**: `.grid.grid-4` 등 안에 나열

## 7. Input

```html
<div class="form-group">
  <label class="form-label" for="field-id">라벨 <span class="is-required">*</span></label>
  <input class="form-control" type="text" id="field-id" placeholder="입력하세요">
  <p class="form-help">도움말 (선택)</p>
  <p class="form-error">오류 메시지 (오류 시에만 표시)</p>
</div>

<!-- 단위가 붙는 숫자 입력 -->
<div class="input-group">
  <input type="number" id="amount"><span class="input-group__suffix">USD</span>
</div>

<!-- Checkbox -->
<label class="form-check"><input type="checkbox"> 로그인 상태 유지</label>
```

- **CSS Class**: `.form-group` `.form-label` `.form-control` `.form-control-sm` `.form-help` `.form-error` / `.input-group` `.input-group__suffix` / `.form-check`
- **크기**: 높이 56px(`-sm` 44px), 좌우 Padding 18px, radius 14px, 17px, 배경 `#F2F4F6`, **Border 없음**. `.input-group`은 60px / 22px·Bold
- **Hover**: 배경 조금 진하게 / **Focus**: 흰 배경 + 1px `#3182F6` Border
- **Disabled**: `disabled` → 투명도 70% / **Error**: `.form-control.is-error`(빨간 Border + 연한 빨강 배경) + `.form-error`
- Label: 14px / Bold / `#4E5968`, Label ↔ Input 8px, 필드 간격 20px

## 8. Textarea

```html
<textarea class="form-control" rows="4"></textarea>
```

- Input과 동일한 Class·상태. 최소 높이 120px, 세로 방향만 resize

## 9. Select

```html
<select class="form-control">
  <option value="">선택하세요</option>
</select>
```

- Input과 동일한 Class·상태. 우측 화살표 Icon 자동 표시

## 10. Multi Select

- **용도**: 여러 값을 Chip으로 선택 (예: 국가 여러 개)

```html
<div class="multi-select">
  <span class="multi-select__chip">값 <button type="button" class="multi-select__remove" aria-label="삭제">×</button></span>
  <input class="multi-select__input" type="text" placeholder="추가">
</div>
```

- **CSS Class**: `.multi-select` `.multi-select__chip` `.multi-select__remove` `.multi-select__input`
- **크기**: 최소 높이 56px, Chip 32px Pill (`primary-soft` / `primary`)
- **상태**: Focus(자동) / `.is-error` / `.is-disabled`
- 스타일만 공통 제공합니다. Chip 추가·삭제 로직은 사용하는 페이지의 JS에서 구현합니다. 단순한 경우 `<select class="form-control" multiple>`도 사용 가능

## 11. File Upload

```html
<label class="file-upload">
  <input type="file">
  <span class="file-upload__title">파일을 끌어다 놓거나 클릭하여 선택</span>
  <span class="text-caption">허용 형식 / 최대 용량</span>
</label>
```

- **CSS Class**: `.file-upload` `.file-upload__title`
- **크기**: Padding 40px 20px, radius 20px, 점선 Border(이 컴포넌트만 예외적으로 Border 사용)
- **상태**: Hover / `.is-dragover`(드래그 중, 페이지 JS에서 토글) / `.is-error` / `.is-disabled`
- 업로드 처리 로직은 사용하는 페이지에서 구현합니다.

## 12. Table

```html
<div class="card">
  <div class="card-body">
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>항목</th><th class="is-numeric">수치</th></tr></thead>
        <tbody><tr><td>값</td><td class="is-numeric">1,234</td></tr></tbody>
      </table>
    </div>
  </div>
</div>
```

- **CSS Class**: `.table-wrap`(가로 스크롤) `.table` `.is-numeric`(우측 정렬 숫자)
- **여백**: Cell 14px 16px, 행 구분선 1px `#F2F4F6`, Header 14px / Bold / Gray (배경 없음)
- **Hover**: 행 배경 `surface-muted` / **Active**: `tr.is-active`
- 반드시 Card 안에 배치. 데이터 없음 → Table 대신 Empty State 표시

## 13. Tabs (Segmented Control)

```html
<div class="tabs" role="tablist">
  <button type="button" class="tab is-active" data-tab-target="panel-a">1개월</button>
  <button type="button" class="tab" data-tab-target="panel-b">3개월</button>
</div>
<div class="tab-panel is-active" id="panel-a">…</div>
<div class="tab-panel" id="panel-b">…</div>
```

- **모양**: 회색(`#F2F4F6`) r12 컨테이너 안에 Padding 4px, 활성 항목만 흰색 r9 + Bold. Card 안에서 사용
- **동작**: `data-tab-target`만 지정하면 `common.js`가 전환 처리 (추가 JS 불필요). Panel 없이 필터 버튼으로만 쓸 때는 `data-tab-target`을 생략하고 페이지 JS에서 `.is-active`를 직접 토글
- **상태**: `.is-active` / `disabled`
- Panel `id`는 페이지 접두사를 붙여 중복을 피합니다 (예: `regulatory-panel-a`)

## 14. Badge

```html
<span class="badge">기본</span>
<span class="badge badge-primary">Primary</span>
<span class="badge badge-success">완료</span>
<span class="badge badge-warning">주의</span>
<span class="badge badge-danger">오류</span>
<span class="badge badge-info">안내</span>
```

- **크기**: 높이 26px, 13px / Bold, Pill 형태, 연한 배경 + 진한 글자, Border 없음

## 15. Alert

```html
<div class="alert alert-info">
  <div>
    <p class="alert-title">제목 (선택)</p>
    <p>내용</p>
  </div>
</div>
```

- **CSS Class**: `.alert` + `.alert-info` `.alert-success` `.alert-warning` `.alert-danger`
- **모양**: 연한 색 배경, radius 16px, Padding 16px 20px, Border 없음. 제목만 상태 색상
- **용도**: 페이지/Section 안의 안내·경고 메시지

## 16. Modal

```html
<button type="button" class="btn btn-primary" data-modal-open="example-modal">열기</button>

<div class="modal-backdrop" id="example-modal">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="modal-header">
      <h2 class="modal-title">제목</h2>
      <button type="button" class="modal-close" data-modal-close aria-label="닫기">×</button>
    </div>
    <div class="modal-body">내용</div>
    <div class="modal-footer">
      <button type="button" class="btn btn-secondary" data-modal-close>취소</button>
      <button type="button" class="btn btn-primary">확인</button>
    </div>
  </div>
</div>
```

- **동작**: `data-modal-open="<id>"` 열기 / `data-modal-close`·배경 클릭·ESC 닫기 (`common.js`)
- **JS API**: `Common.openModal('id')`, `Common.closeModal('id')`
- **크기**: 기본 520px, `.modal-lg` 800px, radius 24px, Padding 32px, 구분선 없음
- Modal `id`는 페이지 접두사를 붙입니다 (예: `margin-result-modal`)

## 17. Loading

```html
<div class="loading"><span class="spinner"></span><p>불러오는 중이에요</p></div>
<div class="skeleton" style="height: 80px"></div>
```

- **CSS Class**: `.loading` `.spinner` `.spinner-sm` `.skeleton`
- API 호출 등 1초 이상 걸릴 수 있는 영역에 표시

## 18. Empty State

```html
<div class="state state-empty">
  <p class="state-title">아직 데이터가 없어요</p>
  <p>안내 문구</p>
  <!-- 필요 시 <button class="btn btn-soft">…</button> -->
</div>
```

## 19. Error State

```html
<div class="state state-error">
  <p class="state-title">불러오지 못했어요</p>
  <p>잠시 후 다시 시도해 주세요.</p>
  <button type="button" class="btn btn-secondary">다시 시도</button>
</div>
```

- 영역 전체가 실패했을 때 사용 (Card 안에 배치). 부분 오류·입력 오류는 Alert / `.form-error` 사용

## 20. 임시저장 — 공통 동작 (설계 단계·미구현)

> **화면·API·DB 모두 아직 없다.** 이 장은 탭들이 같이 지킬 **동작**만 정한다.
> **버튼 위치 — 확정(개발기준)**: 임시저장을 연결하는 각 탭의 **공통 저장 영역에서 정식 저장 버튼 옆**에 `임시저장` 버튼을 둔다 (20-1).
> 공통 저장 영역 자체의 화면 위치·HTML 구조·Class 는 프로젝트 선택·저장·불러오기·최종본과 함께 탭 담당자끼리 합의한 뒤 이 장에 추가한다 ([개발 안내](development.md) 9-1). 합의 전에는 새 공통 Class 를 만들지 않고 기존 Button·Badge·Alert·Modal·Loading 을 쓴다.
> 규칙 근거: [DB 규칙](db_rules.md) 3-7, [데이터 계약](data_contract.md) 8장, [API 계약](api_contract.md) 6장. 적용 순서: 개발요청서 먼저, 마진·모델링은 후속.

### 20-1. 임시저장 버튼 — 확정(개발기준)

- 첫 구현은 **수동 버튼**이다. 자동저장은 없다 (후속 검토, 20-9).
- **위치·이름**: 공통 저장 영역의 **정식 저장 버튼 옆**에 `임시저장` 이라는 이름으로 둔다. 두 버튼의 **용도를 구분**해 보여 준다 — 정식 저장은 새 버전을 남기고, 임시저장은 버전 없이 본인만 보는 작성 중 내용을 보관한다.
- 버튼 옆(공통 저장 영역 안)에 **마지막 임시저장 시간**을 표시한다 (20-2).
- **프로젝트를 선택하기 전에는 누를 수 없다** (`disabled`). 버튼 근처에 이유를 보여 준다 — 문구 예: "프로젝트를 선택하면 임시저장할 수 있어요." (20-7) 보관된 프로젝트라는 이유만으로는 막지 않는다.
- 누르면 Loading 상태(버튼 안 `.spinner-sm` + `disabled`)로 바꾸고, 끝나면 20-2 상태를 갱신한다.
- 실패해도 **작성 중인 화면 내용은 그대로 둔다.** 오류는 Alert 로 알리고 다시 누를 수 있게 한다. 크기 초과(413)는 잘라 저장하지 않았다는 사실을 알린다.
- 필수값이 비어 있어도 임시저장할 수 있다. 필수값 오류 표시는 정식 저장 때만 한다.
- 용도 구분 방법 (제안): 한 영역에 Primary 는 1개라는 Button 규칙(4장)에 따라 정식 저장을 Primary 로, 임시저장을 보조 버튼(`.btn-secondary`·`.btn-soft` 등)으로 둔다. 짧은 도움말 예: "버전 없이 나만 보는 임시 보관".

### 20-2. 저장 상태 표시 — 항목 확정(개발기준), 문구·모양은 제안

| 상태 | 표시 예 (제안) |
|---|---|
| 임시저장 없음 | 표시 없음 또는 "임시저장 없음" |
| 저장 중 | "임시저장 중…" |
| 임시저장됨 | "임시저장됨 · 14:05" (서버 `updated_at` 기준, 사용자 현지 시각) |
| 그 뒤 수정함 | "임시저장 이후 수정한 내용이 있어요" |
| 실패 | "임시저장하지 못했어요" + 이유 |

- **마지막 임시저장 시간은 반드시 표시**한다 — 확정(개발기준). 위 표의 "임시저장됨 · 14:05" 형식은 제안이다.
- 임시저장은 **정식 저장 버전처럼 보이지 않게** 한다. 버전 번호·★(최종본)·"저장됨" 같은 정식 저장 표현을 쓰지 않는다 ([데이터 계약](data_contract.md) 7장 "저장하지 않은 문서는 정식 저장 버전처럼 표시하지 않는다").
- 임시저장은 본인에게만 보인다. 다른 사람의 임시저장 여부를 보여 주지 않는다.

### 20-3. 복원 — 확정(개발기준)

- 내 임시저장이 있는 프로젝트·탭을 열면 **임시저장이 있다고 안내**한다. 복원은 **사용자가 고를 때만** 한다.
- **현재 작성 내용을 자동으로 덮어쓰지 않는다.**
- 복원하면 현재 입력이 바뀌는 경우(화면에 작성 중 내용이 있을 때) **확인을 받은 뒤** 바꾼다.
- 복원한 내용에도 원본 파일·참고자료 본문·참고 이미지는 없다 (저장하지 않음, [DB 규칙](db_rules.md) 6장). 정식 저장본 불러오기와 같은 안내를 보여 준다.
- 임시저장에는 편집 시작 저장본(`based_on_id`) 기록이 없다 (이번 범위에서 제외). 복원 화면에서 시작 저장본을 보여 주지 않는다.

제안 (문구·모양): Alert "임시저장한 내용이 있어요 (11-05 14:05)" + **[복원]** **[삭제]**. 고르지 않으면 임시저장은 그대로 남는다. 확인 문구 예: "지금 작성 중인 내용이 임시저장 내용으로 바뀌어요. 복원할까요?"

### 20-4. 사용자가 직접 삭제 — 확정(개발기준)

- 사용자가 임시저장 **삭제를 고르고 확인하면** 지운다. 확인 없이 지우지 않는다 (되돌릴 수 없음).
- 삭제해도 **현재 화면에 입력 중인 내용은 그대로 둔다.** 화면을 초기화하지 않는다.
- 삭제 확인 안내에 **"저장된 임시저장만 삭제되며, 현재 작성 중인 내용은 유지됩니다"** 라는 뜻을 분명히 담는다. (정확한 문구는 화면에서 다듬어도 되지만 이 의미는 빠뜨리지 않는다)
- 삭제 후 상태 표시는 "임시저장 없음"으로 바뀐다 (20-2). 남은 화면 내용은 다시 임시저장하거나 정식 저장할 수 있다.

### 20-5. 호환되지 않는 임시저장 — 확정(개발기준)

- 현재 화면에서 복원할 수 없으면(예: 지원하지 않는 `schema_version`) **복원할 수 없는 이유를 안내**한다.
- 사용자가 **삭제에 동의**하면 그 임시저장을 폐기하고 새로 작성할 수 있게 한다.
- **취소**하면 기존 임시저장을 그대로 둔다.
- 자동 삭제·자동 변환을 하지 않는다. 이전 내용의 변환·내보내기·별도 보기 기능은 이번 범위에서 제외한다 ([데이터 계약](data_contract.md) 8-4).

### 20-6. 여러 창 충돌 (409) — 확정(개발기준)

- 다른 창에서 더 최근에 임시저장해 서버가 409 로 거부하면, **현재 화면 입력을 그대로 둔다.** 지우거나 서버 내용으로 바꾸지 않는다 ([API 계약](api_contract.md) 6-4).
- 거부되었다는 사실을 안내한다. 문구 예 (제안): "다른 창에서 더 최근에 임시저장했어요. 지금 화면 내용은 그대로 있어요."
- 그다음 선택지(서버 내용 확인, 확인 후 덮어쓰기 등)는 **제안 단계**다. 정할 때도 덮어쓰기는 사용자가 확인한 경우만 허용한다.

### 20-7. 프로젝트 미선택·프로젝트 변경·보관 — 확정(개발기준)

- 임시저장은 탭 작성 내용의 **연결 프로젝트**에 저장한다. 화면에서 지금 고른 프로젝트가 아니다 ([API 계약](api_contract.md) 5-3).
- 연결 프로젝트가 없으면 버튼을 막고 안내한다 (20-1). 프로젝트 없이 작성 중이던 내용은 기존 규칙대로 프로젝트를 연결한 뒤 임시저장할 수 있다.
- 작성 중 다른 프로젝트로 바꾸는 확인·초기화 규칙은 그대로다 ([API 계약](api_contract.md) 5-3). 이전 프로젝트의 임시저장은 서버에 남는다 — 자동으로 지우지 않는다 ([DB 규칙](db_rules.md) 3-7: 지워지는 경우는 정식 저장 연동과 사용자 삭제뿐).
- 보관된 프로젝트에서도 임시저장 조회·저장·복원·삭제를 그대로 쓸 수 있다.

### 20-8. 정식 저장 후 — 확정(개발기준)

- 정식 저장이 성공하고 화면이 보낸 `draft_revision` 이 서버 번호와 같으면 서버가 임시저장을 지운다. 상태 표시는 "임시저장 없음"으로 바뀐다.
- 번호가 달라 지워지지 않았으면 더 최신 임시저장이 남아 있는 것이다. 이를 알린다 (문구는 [API 계약](api_contract.md) 6-5 제안).
- 정식 저장이 실패하면 임시저장은 남는다. 상태 표시를 바꾸지 않는다.

### 20-9. 자동저장 — 후속 검토

- 이번 범위가 아니다. "변경 시 30초 간격" 은 **검토안**이며 확정한 동작이 아니다. 도입하면 상태 표시(20-2)·충돌 처리([API 계약](api_contract.md) 6-4)와 함께 정한다.

---

## 페이지 구조 / 유틸리티

```html
{% extends "common/base.html" %}
{% block content %}
<div class="page-header">
  <div>
    <p class="page-eyebrow">날짜 등 (선택)</p>
    <h1 class="page-title">페이지 제목</h1>
    <p class="page-description">설명 (선택)</p>
  </div>
  <div class="page-actions"><!-- .btn-surface --></div>
</div>

<section class="section">
  <div class="section-header">
    <h2 class="section-title">Section 제목</h2>
    <span class="section-meta">출처 · 기준 시각 (선택)</span>
  </div>
  <div class="grid grid-3"> <!-- .card … --> </div>
</section>
{% endblock %}
```

| 분류 | Class |
|---|---|
| Grid | `.grid` + `.grid-2` `.grid-3` `.grid-4` `.grid-6` `.grid-2-1`(2:1), `.col-span-2` `.col-span-3` — 열 수는 **본문 폭** 기준으로 자동 축소(≤880px → 2열, ≤560px → 1열). Sidebar 접힘/펼침에도 반응. 항목 수가 유동적인 목록은 `.grid-auto`(최소 240px) / `.grid-auto-sm`(최소 168px): 본문이 넓어지면 열이 자동으로 늘어남 |
| 배치 | `.stack`(세로, gap 24px) `.row`(가로, gap 8px) |
| Spacing | `.mt-0/2/4/6/8` `.mb-0/2/4/6/8` |
| Text | `.text-secondary` `.text-caption` `.text-number` `.text-up`(빨강) `.text-down`(파랑) |
| 구현 전 표시 | `.placeholder` `.placeholder-title` (Card 안에 배치) |
