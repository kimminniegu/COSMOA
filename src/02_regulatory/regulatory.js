/* 국가별 인허가 규제 전용 JavaScript (담당자 B)
   이 페이지에서만 필요한 로직만 작성합니다.
   다른 페이지의 JS를 수정하거나 의존하지 않습니다. 공통 동작(탭·Modal)은 src/common/common.js 를 그대로 사용합니다.

   직접 검색 (식약처 수집 DB 전용 — K뷰티 API 를 호출하지 않습니다)
   - 성분명(한글명·영문명·이명·CAS) + 시장. 후보는 /api/regulatory/search (성분정보·규제정보 두 DB, 출처별로 따로, 합치지 않음)
   - 자동완성: 앞뒤 공백 제거 후 2글자 이상이면 입력이 멈춘 뒤 300ms 후 후보 조회 → 검색창 아래 최대 10개 (서버 정렬 그대로)
     · 한글 조합(IME composition) 중에는 요청하지 않고 조합이 끝난 뒤 조건을 다시 확인합니다
     · 현재 입력에 대응하는 최신 응답만 반영하고, 이전 검색어의 늦은 응답과 닫힌 목록에 도착한 응답은 무시합니다
     · 후보가 잘렸으면(truncated) 전체 후보 수·정확 일치 수를 안내합니다. 보이는 후보가 하나여도 유일한 성분으로 다루지 않습니다
   - 후보 선택(클릭 · ↑↓ + Enter)은 성분만 고르고 규제 조회를 실행하지 않습니다. 후보가 하나여도 자동 선택·자동 조회하지 않습니다
   - 검색어를 수정하면 선택을 해제합니다. 선택은 서버가 준 후보 key 로만 기억합니다 (key·내부 id 는 화면에 표시하지 않음)
   - 선택한 상태에서 검색 버튼 → /api/regulatory/lookup?key=&country= — 서버가 key 를 다시 검증하고 규제 DB 를 읽습니다
     (브라우저는 이름·CAS 를 보내지 않음). 수집본이 바뀐 key(stale_key)는 선택을 해제하고 다시 검색하도록 안내합니다
   - 결과 상태: 규제 기록 조회됨(found) / 선택 국가 기록 없음(no_market_record) / 규제 성분 연결 확인 필요(link_required) /
     규제 성분 연결 미확인(not_linked) / 오류. 기록이 없다고 사용 가능·안전·규제 없음으로 표시하지 않습니다.
   파일로 일괄 조회 (이번 단계: 업로드 → 시트 선택 → 성분 추출 → 확인·수정)
   - POST /api/regulatory/extract 로 텍스트 PDF·.xlsx 를 보내 성분명·함량(문서에 있을 때만)을 받아 표로 표시합니다
   - 여러 시트면 서버가 sheet_required 를 돌려주고, 시트를 고르면 같은 파일을 sheet 와 함께 다시 보냅니다
   - 표에서 성분명·함량 수정, 행 추가·삭제, 조회 포함 체크. 원문값은 별도로 남겨 둡니다
   - 처리 중 / 완료 / 실패(형식 미지원·읽기 실패·제한 초과) / 추출 결과 없음을 구분합니다
   성분 확인·규제 일괄 조회 (3단계 — 식약처 수집 DB 전용, K뷰티 API 를 호출하지 않습니다)
   - '성분 확인' → 조회 포함·미선택 행의 성분명으로 /api/regulatory/search 를 순차 호출 (같은 검색어는 한 작업 안에서 1회, 결과 공유·선택은 행별).
     자동 선택 없음. exact_total 이 1 이고 한글명·표준명·영문명 정확 일치일 때만 '추천'(선택 아님) — 행의 '추천 후보 선택' 또는
     '추천 N건 선택 완료'를 눌러야 조회 대상. 그 외는 행의 select 로 직접 선택. 검색 결과 없음·검색 오류는 따로 표시
   - '선택 성분 규제 조회' → 선택 완료 행만 /api/regulatory/lookup?key=&country= 를 (key, 시장)당 1회 순차 호출 (이름·CAS 를 보내지 않음).
     stale_key·not_found → 그 행 선택 해제·다시 검색 / DB 이용 불가 → 중단하고 남은 행은 같은 이유로 미조회 / 일시 오류 행만 '실패 항목 재시도'.
     늦은 응답은 순번(batchSeq·matchSeq)과 '아직 같은 key 를 선택한 행인지'로 걸러 수정·삭제·제외된 행과 새 파일을 덮어쓰지 않습니다
   - 결과 표: 성분명(원문·선택 후보·조회한 규제 성분·연결 근거)·선택 시장·조회 상태(직접 검색과 같은 문구)·규제 유형·상세.
     성분 연결 확인 필요 행은 규제 후보를 직접 고르면 그 행만 다시 조회. 함량은 문서 참고값만, 적합 판정 없음
   OCR (이번 단계): PNG·JPG 와 텍스트 없는 PDF 쪽은 서버가 로컬 Tesseract 로 읽어 같은 표에 연결. OCR 행은 '확인 필요(OCR)' 로 표시,
     OCR 미설치는 서버 503(ocr_unavailable) + 설치 안내를 그대로 보여 주고 텍스트 PDF·Excel 은 계속 동작.
   미구현(후속): 중간 포함 검색, 함량 기준 비교(검토 상태). */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  function show(el, on) { if (el) el.hidden = !on; }

  function setText(el, text) { if (el) el.textContent = text == null || text === "" ? "—" : String(text); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function badge(text, variant) {
    return el("span", "badge" + (variant ? " badge-" + variant : ""), text);
  }

  function replaceChildren(node, child) {
    if (!node) return;
    node.innerHTML = "";
    if (child) node.appendChild(child);
  }

  function formatTime(iso) {
    if (!iso) return "—";
    return String(iso).replace("T", " ");
  }

  /* 한국시간(KST) 표시. 시간대 정보가 있는 ISO 문자열만 변환하고, 시간대가 없는 값(API 레코드 updated_at 등)은 그대로 두고 표기한다 */
  var KST_FMT = null;
  try { KST_FMT = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); } catch (e) { KST_FMT = null; }
  function formatKst(iso) {
    if (!iso) return "—";
    var s = String(iso);
    if (!/(Z|[+-]\d\d:?\d\d)$/.test(s)) return formatTime(s) + " (시간대 미표기)";
    var d = new Date(s);
    if (isNaN(d.getTime()) || !KST_FMT) return formatTime(s);
    return KST_FMT.format(d).replace("T", " ") + " KST";
  }

  /* 출처별 날짜·갱신 안내 (직접 검색·일괄 조회·상세가 공유). 시각을 만들어내지 않는다 */
  function acquiredText(res) {
    if (!res) return "—";
    if (res.source === "mfds") return res.acquired_at ? formatKst(res.acquired_at) + " (수집 완료 시각, DB 기록)" : "수집 시각 미기록";
    return res.acquired_at || res.queried_at ? formatKst(res.acquired_at || res.queried_at) + " (API 응답 확보 시각)" : "—";
  }
  function refreshText(res) {
    if (!res) return "—";
    if (res.source === "mfds") return res.refresh_policy || "수동 재수집 (자동 갱신 없음)";
    return res.refresh_policy || "갱신 주기 확인 필요";
  }

  /* 준비 중 안내 (파일 탭 등 미구현 기능) ----------------------------------- */
  var devNotice = $("regulatory-dev-notice");

  function notReady(what) {
    if (!devNotice) return;
    var body = $("regulatory-dev-notice-body");
    if (body) { body.textContent = what + " 기능은 아직 준비 중이에요."; show(body, true); }
    devNotice.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* 서버 API 호출 ------------------------------------------------------------
     실패는 { kind, message, http_status? } 객체로 통일합니다. 서버 응답의 error 는 비밀값을 담지 않습니다. */
  function apiGet(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!body || typeof body !== "object") {
          throw { kind: "invalid_response", message: "서버 응답을 해석하지 못했어요. 잠시 후 다시 시도해 주세요." };
        }
        if (!res.ok || body.ok === false) {
          throw body.error || { kind: "http", message: "요청에 실패했어요 (HTTP " + res.status + ")." };
        }
        return body;
      });
    }, function () {
      throw { kind: "network", message: "서버에 연결하지 못했어요. 네트워크 상태를 확인해 주세요." };
    });
  }

  function apiPost(url, formData) {
    return fetch(url, { method: "POST", body: formData, headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!body || typeof body !== "object") {
          throw { kind: "invalid_response", message: "서버 응답을 해석하지 못했어요. 잠시 후 다시 시도해 주세요." };
        }
        if (!res.ok || body.ok === false) {
          throw body.error || { kind: "http", message: "요청에 실패했어요 (HTTP " + res.status + ")." };
        }
        return body;
      });
    }, function () {
      throw { kind: "network", message: "서버에 연결하지 못했어요. 네트워크 상태를 확인해 주세요." };
    });
  }

  /* 상세 Modal 을 body 바로 아래로 옮긴다 -------------------------------------
     공통 레이아웃의 main.container 에는 container-type: inline-size 와 진입 애니메이션(transform)이 있어
     그 안의 position: fixed 요소는 뷰포트가 아니라 컨테이너(페이지 전체 높이) 기준으로 배치된다.
     그러면 배경은 화면을 다 덮지만 Modal 창은 긴 페이지의 세로 정중앙(화면 밖)에 그려진다.
     공통 common.js 는 id 로 Modal 을 찾으므로 위치를 옮겨도 열기·닫기·ESC·배경 클릭은 그대로 동작한다. (공통 파일 수정 없음) */
  var detailModal = $("regulatory-detail-modal");
  if (detailModal && detailModal.parentNode !== document.body) document.body.appendChild(detailModal);

  /* 상세 Modal 접근성 보완 — 공통 common.js 는 열기·닫기·ESC·배경 클릭만 담당하므로, 이 Modal 에 한해
     열 때 닫기 버튼으로 포커스 이동·스크롤 맨 위, Tab 순환, 닫은 뒤 연 버튼으로 포커스 복귀를 페이지 JS 에서 처리한다 (공통 파일 수정 없음).
     공통 리스너가 먼저 등록되어 같은 클릭에서 Modal 이 열린 뒤 아래 리스너가 실행되지만, 안전하게 다음 틱에 포커스를 옮긴다 */
  var detailOpener = null;
  if (detailModal) {
    document.addEventListener("click", function (e) {
      var opener = e.target.closest('[data-modal-open="regulatory-detail-modal"]');
      if (!opener) return;
      detailOpener = opener;
      setTimeout(function () {
        if (!detailModal.classList.contains("is-open")) return;
        var body = detailModal.querySelector(".modal-body");
        if (body) body.scrollTop = 0;
        var close = detailModal.querySelector(".modal-close");
        if (close) close.focus();
      }, 0);
    });
    detailModal.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var focusable = Array.prototype.filter.call(
        detailModal.querySelectorAll('a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'),
        function (n) { return n.offsetParent !== null; });
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    if (window.MutationObserver) {
      new MutationObserver(function () {
        if (detailModal.classList.contains("is-open") || !detailOpener) return;
        var target = detailOpener;
        detailOpener = null;
        if (document.body.contains(target) && typeof target.focus === "function") target.focus();
      }).observe(detailModal, { attributes: true, attributeFilter: ["class"] });
    }
  }

  /* ==========================================================================
     직접 검색: 상태
     ========================================================================== */
  var searchForm = $("regulatory-search-form");
  var input = $("regulatory-search-ingredient");
  var marketSelect = $("regulatory-search-market");
  var submitBtn = $("regulatory-search-submit");
  var submitLabel = submitBtn ? submitBtn.textContent : "";
  var optionsList = $("regulatory-autocomplete-options");
  var selectedLine = $("regulatory-search-selected");

  var state = {
    selected: null,       // 사용자가 고른 후보 { key, source, kr_name, eng_name, cas, matched, ... } (/api/regulatory/search 응답 그대로)
    selectedText: "",     // 선택 당시 검색창 표시값 — 수정되면 선택 해제
    matchMethod: "",      // "후보 선택 (클릭)" | "후보 선택 (키보드)" | "연결 후보 선택" — 자동 확정 없음
    searchMeta: null,     // 마지막 후보 응답의 total/truncated/counts (안내 문구용)
    candidates: [],
    activeIndex: -1,
    listOpen: false,
    lookupSeq: 0,         // 늦게 도착한 이전 응답 무시용 (검색 버튼 흐름)
    acSeq: 0,             // 자동완성 요청 순번 — 입력 변경·닫기 때마다 증가시켜 이전 응답을 무시
    acTimer: null,        // 300ms 디바운스 타이머
    composing: false,     // 한글 조합(IME) 중
    resultKey: null,      // 표시 중인 결과의 조건 키(후보 key|시장) — 현재 입력과 다르면 '이전 조건' 안내
    candidatesQuery: "",  // 현재 후보 목록이 어떤 검색어(정규화)로 받은 것인지 — 다른 검색어로 제출하면 재검색
    lastSingle: null,     // 마지막 직접 검색 결과 {res, ctx, err} — '규제 원문·출처 보기' 를 누를 때 Modal 을 다시 채운다
  };

  /* 조회 출처 표시 이름. 직접 검색·파일 일괄 조회 모두 식약처 수집 DB(mfds)만 쓴다 (3단계, 출처 선택 radio 제거).
     api 항목은 상세 Modal 의 이전 K뷰티 응답 표시 분기용으로만 남아 있다 — 4단계에서 삭제 */
  var SOURCE_LABEL = { mfds: "식약처 수집 DB", api: "K뷰티 API (RapidAPI)" };

  /* 후보 출처·일치 근거 표시 — 직접 검색·파일 성분 확인 공통 (key·내부 id·해시는 표시하지 않는다) */
  var CANDIDATE_SOURCE_LABEL = { mfds_ingredients: "성분정보", mfds_restriction: "규제정보" };
  var MATCH_LEVEL_LABEL = { exact: "정확 일치", prefix: "앞부분 일치", contains: "포함 일치" };
  var MATCH_FIELD_LABEL = { INGR_KOR_NAME: "한글명", INGR_STD_NAME: "표준명", INGR_ENG_NAME: "영문명", INGR_SYNONYM: "이명", NOTICE_INGR_NAME: "고시원료명", CAS_NO: "CAS" };
  function candidateSourceLabel(c) { return (c && CANDIDATE_SOURCE_LABEL[c.source]) || "출처 미상"; }
  function matchBasisText(c) {
    var m = c && c.matched && c.matched[0];
    if (!m) return "";
    return (MATCH_FIELD_LABEL[m.field] || m.field) + " " + (MATCH_LEVEL_LABEL[m.level] || m.level) + (m.via === "item" ? " (나열된 이름 중 하나)" : "") +
      (m.field !== "INGR_KOR_NAME" && m.field !== "INGR_STD_NAME" && m.field !== "INGR_ENG_NAME" ? " · " + String(m.value || "").replace(/\s+/g, " ").slice(0, 60) : "");
  }
  function candidateName(c) { return (c && ((c.kr_name || "").trim() || (c.eng_name || "").trim())) || "이름 미제공"; }

  var AC_MIN_LENGTH = 2;    // 자동완성 최소 글자 수 (앞뒤 공백 제거 후)
  var AC_DEBOUNCE_MS = 300; // 입력이 멈춘 뒤 대기 시간

  function normalize(text) { return (text || "").trim().toLowerCase(); }

  function marketLabel(code) {
    if (!marketSelect) return code;
    for (var i = 0; i < marketSelect.options.length; i++) {
      if (marketSelect.options[i].value === code) return marketSelect.options[i].text;
    }
    return code;
  }

  function setBusy(on, label) {
    if (!submitBtn) return;
    submitBtn.disabled = on;
    submitBtn.innerHTML = "";
    if (on) {
      submitBtn.appendChild(el("span", "spinner spinner-sm"));
      submitBtn.appendChild(document.createTextNode(" " + (label || "조회 중")));
    } else {
      submitBtn.textContent = submitLabel;
    }
  }

  /* 후보 목록: closed | loading | empty | error | list — 한 상태만 표시 */
  function setAutocomplete(st) {
    var list = $("regulatory-autocomplete-list");
    if (!list) return;
    var open = st !== "closed";
    if (!open) { state.acSeq++; clearTimeout(state.acTimer); }   // 닫힌 목록이 진행 중 응답으로 다시 열리지 않게
    state.listOpen = open;
    show(list, open);
    if (input) input.setAttribute("aria-expanded", String(open));
    list.querySelectorAll("[data-ac-state]").forEach(function (node) {
      show(node, open && node.getAttribute("data-ac-state") === st);
    });
    if (!open) setActive(-1);
  }

  function setActive(index) {
    state.activeIndex = index;
    if (!optionsList) return;
    var items = optionsList.querySelectorAll(".regulatory-autocomplete__option");
    items.forEach(function (li, i) {
      var active = i === index;
      li.classList.toggle("is-active", active);
      li.setAttribute("aria-selected", String(active));
      if (active) {
        if (input) input.setAttribute("aria-activedescendant", li.id);
        if (li.scrollIntoView) li.scrollIntoView({ block: "nearest" });
      }
    });
    if (index < 0 && input) input.removeAttribute("aria-activedescendant");
  }

  function renderCandidates(candidates) {
    if (!optionsList) return;
    optionsList.innerHTML = "";
    candidates.forEach(function (c, i) {
      var li = el("li", "regulatory-autocomplete__option");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.setAttribute("data-index", String(i));
      li.id = "regulatory-autocomplete-option-" + i;
      // 원문 한글명·영문명 (만들어 내지 않음) + 출처 배지 + 일치 근거. 같은 이름이 두 출처에 있어도 따로 표시
      var head = el("span", "regulatory-autocomplete__head");
      head.appendChild(el("span", "regulatory-autocomplete__kr", (c.kr_name || "").trim() || "한글명 미제공"));
      head.appendChild(badge(candidateSourceLabel(c), c.source === "mfds_restriction" ? "warning" : "primary"));
      li.appendChild(head);
      if ((c.eng_name || "").trim()) li.appendChild(el("span", "regulatory-autocomplete__inci", c.eng_name.trim()));
      var basis = matchBasisText(c);
      if (basis) li.appendChild(el("span", "regulatory-autocomplete__basis", basis));
      li.addEventListener("mousedown", function (e) { e.preventDefault(); });
      li.addEventListener("click", function () { selectCandidate(i, "후보 선택 (클릭)"); });
      optionsList.appendChild(li);
    });
  }

  /* 후보 목록 안내 — 잘림·정확 일치 수. 보이는 후보 수만으로 '유일한 성분'처럼 보이지 않게 전체 수를 함께 적는다 */
  function renderCandidateHint(body, extra) {
    var hint = $("regulatory-autocomplete-hint");
    if (!hint) return;
    var parts = [];
    if (body && body.truncated) parts.push("후보 " + body.total + "건 중 " + body.returned + "건만 표시했어요. 검색어를 더 구체적으로 입력해 주세요.");
    else if (body) parts.push("후보 " + body.total + "건");
    if (body && body.counts) {
      var ex = [];
      Object.keys(CANDIDATE_SOURCE_LABEL).forEach(function (s) {
        if (body.counts[s] && body.counts[s].exact) ex.push(CANDIDATE_SOURCE_LABEL[s] + " " + body.counts[s].exact + "건");
      });
      parts.push(ex.length ? "정확 일치: " + ex.join(" · ") : "정확 일치 없음");
    }
    parts.push(extra || "후보를 직접 선택해 주세요 (↑↓ 이동 · Enter 선택 · Esc 닫기)");
    hint.textContent = parts.join(" · ");
  }

  function applyCandidates(body, query) {
    state.candidates = body.candidates || [];
    state.candidatesQuery = normalize(query);
    state.searchMeta = { total: body.total, returned: body.returned, truncated: body.truncated, counts: body.counts };
    if (!state.candidates.length) { setAutocomplete("empty"); return false; }
    renderCandidates(state.candidates);
    renderCandidateHint(body);
    setAutocomplete("list");
    setActive(-1);                                         // 활성 후보 없음 — Enter·검색 버튼이 임의 후보를 고르지 않게
    return true;
  }

  function searchUrl(query) { return "/api/regulatory/search?q=" + encodeURIComponent(query); }

  function clearSelection() {
    state.selected = null;
    state.selectedText = "";
    state.matchMethod = "";
    show(selectedLine, false);
  }

  function selectCandidate(index, method) {
    pickCandidate(state.candidates[index], method);
  }

  /* 사용자가 명시적으로 고른 후보만 선택한다 (자동완성 목록 · 결과 카드의 연결 후보 버튼) */
  function pickCandidate(c, method) {
    if (!c || !c.key) return;
    state.selected = c;
    state.matchMethod = method;
    var display = candidateName(c);
    if (input) input.value = display;
    state.selectedText = display;
    setAutocomplete("closed");
    if (selectedLine) {
      var eng = (c.eng_name || "").trim();
      selectedLine.textContent = "선택한 성분: " + display + (c.kr_name && eng ? " (" + eng + ")" : "") + " · " + candidateSourceLabel(c) +
        " — 검색 버튼을 누르면 선택한 시장의 규제를 조회해요.";
      show(selectedLine, true);
    }
    refreshStale();
    if (input) input.focus();
  }

  /* 현재 입력 조건 키. 표시 중인 결과의 키와 다를 때만 '이전 조건의 결과' 안내 */
  function conditionKey(ctx) {
    return [ctx.selected ? ctx.selected.key : "", ctx.marketCode, ctx.source].join("|");
  }

  function refreshStale() {
    var notice = $("regulatory-stale-notice");
    if (!notice) return;
    if (state.resultKey == null) { show(notice, false); return; }
    show(notice, conditionKey(currentContext()) !== state.resultKey);
  }

  /* ==========================================================================
     직접 검색: 흐름
     ========================================================================== */
  function validateForm() {
    var ingredientEmpty = !input || !input.value.trim();
    var marketEmpty = !marketSelect || !marketSelect.value;
    if (input) input.classList.toggle("is-error", ingredientEmpty);
    var ingErr = $("regulatory-search-ingredient-error");
    if (ingErr && ingredientEmpty) ingErr.textContent = "성분명을 입력해 주세요.";
    show(ingErr, ingredientEmpty);
    if (marketSelect) marketSelect.classList.toggle("is-error", marketEmpty);
    show($("regulatory-search-market-error"), marketEmpty);
    return !(ingredientEmpty || marketEmpty);
  }

  /* 검색 버튼(선택 전) → 후보만 보여 준다. 정확 일치 후보가 하나여도 자동 선택·자동 조회하지 않는다 */
  function fetchCandidates(query) {
    setAutocomplete("loading");
    setBusy(true, "후보 찾는 중");
    var seq = ++state.lookupSeq;
    state.acSeq++;                                          // 진행 중인 자동완성 응답이 이 목록을 덮지 않게
    var acSeqAtStart = state.acSeq;
    apiGet(searchUrl(query)).then(function (body) {
      if (seq !== state.lookupSeq || acSeqAtStart !== state.acSeq) { if (seq === state.lookupSeq) setBusy(false); return; }
      setBusy(false);
      if (!input || input.value.trim() !== query) return;  // 응답 도착 전에 검색어가 바뀜 → 무시
      if (applyCandidates(body, query)) renderCandidateHint(body, "검색 전에 목록에서 성분을 직접 선택해 주세요 (↑↓ 이동 · Enter 선택 · Esc 닫기)");
    }).catch(function (err) {
      if (seq !== state.lookupSeq) return;
      setBusy(false);
      if (acSeqAtStart !== state.acSeq) return;            // 그 사이 입력이 바뀌었거나 목록이 닫힘
      var msg = $("regulatory-autocomplete-error-text");
      if (msg) msg.textContent = "후보를 불러오지 못했어요. " + (err && err.message ? err.message : "잠시 후 다시 시도해 주세요.");
      setAutocomplete("error");
    });
  }

  /* 자동완성 (입력 중) — 검색 버튼을 비활성화하지 않고 목록 안에서만 로딩·없음·오류를 표시 */
  function fetchAutocomplete(query) {
    var seq = ++state.acSeq;
    setAutocomplete("loading");
    apiGet(searchUrl(query)).then(function (body) {
      if (seq !== state.acSeq) return;                       // 입력이 바뀌었거나 목록이 닫힘 → 무시
      if (!input || input.value.trim() !== query) return;    // 현재 검색어와 다른 응답 → 무시
      applyCandidates(body, query);
    }).catch(function (err) {
      if (seq !== state.acSeq) return;
      var msg = $("regulatory-autocomplete-error-text");
      if (msg) msg.textContent = "후보를 불러오지 못했어요. " + (err && err.message ? err.message : "잠시 후 다시 시도해 주세요.");
      setAutocomplete("error");
    });
  }

  /* 입력 변경 → 조합 중이면 대기, 2글자 미만이면 닫기, 그 외 300ms 후 조회 */
  function scheduleAutocomplete() {
    clearTimeout(state.acTimer);
    state.acSeq++;                                            // 이전 검색어의 진행 중 요청 무효화
    if (state.composing) return;
    var query = input ? input.value.trim() : "";
    if (query.length < AC_MIN_LENGTH) { setAutocomplete("closed"); return; }
    state.acTimer = setTimeout(function () {
      if (state.composing) return;
      if (!input || input.value.trim() !== query) return;
      fetchAutocomplete(query);
    }, AC_DEBOUNCE_MS);
  }

  function currentContext() {
    return {
      inputRaw: input ? input.value : "",
      marketCode: marketSelect ? marketSelect.value : "",
      marketLabel: marketLabel(marketSelect ? marketSelect.value : ""),
      selected: state.selected,
      matchMethod: state.matchMethod,
      source: "mfds",                       // 직접 검색은 식약처 수집 DB 고정 (K뷰티 API 호출 없음)
    };
  }

  /* 선택한 후보 key + 시장 → 서버가 key 를 검증하고 규제 DB 를 조회. 이름·CAS 는 보내지 않는다 */
  function lookupUrl(sel, market) {
    return "/api/regulatory/lookup?key=" + encodeURIComponent(sel.key) + "&country=" + encodeURIComponent(market);
  }

  var RESELECT_KINDS = { stale_key: true, not_found: true };   // 수집본이 바뀌었거나 없는 후보 — 이전 선택으로 계속 조회하지 않는다

  function runLookup() {
    if (!state.selected || !state.selected.key || !marketSelect || !marketSelect.value) return;
    var ctx = currentContext();
    setAutocomplete("closed");
    setBusy(true, "규제 조회 중");
    setResult("loading");
    var seq = ++state.lookupSeq;
    apiGet(lookupUrl(state.selected, ctx.marketCode)).then(function (body) {
      if (seq !== state.lookupSeq) return;   // 늦게 도착한 이전 응답 무시
      setBusy(false);
      renderSingle(body, ctx);
    }).catch(function (err) {
      if (seq !== state.lookupSeq) return;
      setBusy(false);
      if (err && RESELECT_KINDS[err.kind]) {
        clearSelection();                    // 다시 검색·선택하도록 (재시도 버튼도 이전 key 를 쓰지 않음)
        state.candidates = []; state.candidatesQuery = "";   // 이전 수집본의 후보 목록도 다시 쓰지 않는다
      }
      renderError(err, ctx);
    });
  }

  if (searchForm) {
    searchForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!validateForm()) return;
      var query = input.value.trim();
      clearTimeout(state.acTimer);
      if (state.selected && state.selectedText === input.value) {
        runLookup();                 // 사용자가 고른 후보 → 규제 조회
        return;
      }
      clearSelection();
      if (query.length < AC_MIN_LENGTH) {
        var short = $("regulatory-search-ingredient-error");
        if (short) { short.textContent = "성분명을 " + AC_MIN_LENGTH + "글자 이상 입력해 주세요."; show(short, true); }
        return;
      }
      // 현재 검색어의 후보 목록이 열려 있으면 다시 요청하지 않고 선택을 안내만 한다 (정확 일치가 하나여도 자동 선택하지 않음)
      if (state.listOpen && state.candidates.length && state.candidatesQuery === normalize(query)) {
        renderCandidateHint(state.searchMeta, "검색 전에 목록에서 성분을 직접 선택해 주세요 (↑↓ 이동 · Enter 선택 · Esc 닫기)");
        return;
      }
      fetchCandidates(query);        // 선택 전 → 후보만 보여 줌 (규제 조회 아님)
    });
  }

  if (input) {
    input.addEventListener("compositionstart", function () { state.composing = true; });
    input.addEventListener("compositionend", function () {
      state.composing = false;
      scheduleAutocomplete();        // 조합 완료 후 길이·대기 조건을 다시 적용
    });
    input.addEventListener("input", function (e) {
      input.classList.remove("is-error");
      show($("regulatory-search-ingredient-error"), false);
      if (input.value !== state.selectedText) { clearSelection(); refreshStale(); }
      if (e && e.isComposing) { state.composing = true; return; }   // 일부 브라우저는 compositionstart 전에 input 을 먼저 보냄
      scheduleAutocomplete();
    });
    input.addEventListener("keydown", function (e) {
      if (e.isComposing || e.keyCode === 229) return;                // 조합 중 키 입력은 목록 조작으로 쓰지 않음
      if (e.key === "Escape") { setAutocomplete("closed"); return; }
      if (!state.listOpen || !state.candidates.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((state.activeIndex + 1) % state.candidates.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((state.activeIndex - 1 + state.candidates.length) % state.candidates.length);
      } else if (e.key === "Enter") {
        // 활성 후보가 있으면 선택용 Enter — 폼 제출(규제 조회)로 이어지지 않음. 활성 후보가 없으면 폼 제출(검색 버튼과 동일)
        if (state.activeIndex >= 0) {
          e.preventDefault();
          selectCandidate(state.activeIndex, "후보 선택 (키보드)");
        }
      }
    });
    document.addEventListener("click", function (e) {
      if (e.target.closest(".regulatory-autocomplete")) return;
      setAutocomplete("closed");
    });
  }

  if (marketSelect) {
    marketSelect.addEventListener("change", function () {
      marketSelect.classList.remove("is-error");
      show($("regulatory-search-market-error"), false);
      refreshStale();
    });
  }

  var retryBtn = $("regulatory-result-retry");
  if (retryBtn) {
    retryBtn.addEventListener("click", function () {
      if (state.selected && marketSelect && marketSelect.value) runLookup();
      else setResult("hidden");
    });
  }

  /* ==========================================================================
     규제 조건 원문(limit_condition) 표시
     - 원문이 "* 【태그】 라벨 : 값" 블록 구조이면 블록별로 나누고, 언어(영문 위 → 한국어 아래)별로 적용 제품 / 최대 농도 / 사용 조건·주의 문구 / 기타 원문 으로 묶습니다.
     - 값 안의 "(a) … (b) …" 항목은 표기를 유지한 채 줄로 나눕니다. 글자 표기가 적용 제품과 최대 농도의 대응 관계입니다.
     - 블록 하나라도 "라벨 : 값" 으로 읽을 수 없으면 나누지 않고 원문 전체를 그대로 표시합니다.
     - 수치·단위·조건을 요약·환산·재해석하지 않으며, 특정 성분에 맞춘 규칙을 두지 않습니다.
     ========================================================================== */
  var CONDITION_GROUPS = [
    { key: "product", title: "적용 제품·부위", re: /product\s*type|body\s*part|제품\s*유형|사용\s*부위/i },
    { key: "concentration", title: "최대 농도", re: /max(?:imum|\.)?\s*concentration|최대\s*농도/i },
    { key: "conditions", title: "사용 조건·주의 문구", re: /conditions?\s*of\s*use|warning|사용\s*조건|주의/i },
  ];

  function parseConditionText(raw) {
    var text = String(raw || "").replace(/\r\n/g, "\n").trim();
    if (!text || !/^\*\s/.test(text)) return null;
    // 블록 경계: 줄 첫머리의 "* " 와, 식약처 원문처럼 줄바꿈 없이 이어지는 " * 【태그】" (머리글이 앞 블록 값에 섞이지 않게)
    var chunks = text.split(/\n(?=\*\s)|\s+(?=\*\s*【)/);
    var blocks = [];
    for (var i = 0; i < chunks.length; i++) {
      var body = chunks[i].replace(/^\*\s*/, "").trim();
      var tag = null;
      var tagMatch = body.match(/^【([^】]*)】\s*/);
      if (tagMatch) { tag = tagMatch[1].trim(); body = body.slice(tagMatch[0].length); }
      var sep = body.match(/^([^:\n]{1,80}?)\s*:\s*([\s\S]+)$/);
      if (!sep) return null;                       // 구조 불확실 → 원문 그대로
      var label = sep[1].trim();
      var value = sep[2].trim();
      var items = value.split(/\s*(?=\([a-z]\)\s)/).map(function (s) { return s.trim(); }).filter(Boolean);
      var group = "other";
      for (var g = 0; g < CONDITION_GROUPS.length; g++) {
        if (CONDITION_GROUPS[g].re.test(label)) { group = CONDITION_GROUPS[g].key; break; }
      }
      // 언어: 라벨(없으면 태그·값)에 한글이 있으면 한국어, 아니면 영문. 한국어 문장 속 영문 성분명·단위는 분리하지 않는다.
      var probe = label || tag || value;
      var lang = /[가-힣]/.test(probe) ? "ko" : "en";
      blocks.push({ tag: tag, label: label, value: value, items: items, group: group, lang: lang, lettered: items.length > 1 && /^\([a-z]\)/.test(items[0]) });
    }
    return blocks.length ? blocks : null;
  }

  function renderRawText(raw, note) {
    var wrap = el("div", "regulatory-cond-raw");
    if (note) wrap.appendChild(el("p", "text-caption text-secondary", note));
    wrap.appendChild(el("pre", "regulatory-cond-raw__text", String(raw)));
    return wrap;
  }

  var CONDITION_LANG_LABEL = { en: "영문 원문", ko: "한국어 제공 내용" };
  var CONDITION_GROUP_TITLE = { product: "적용 제품·부위", concentration: "최대 농도", conditions: "사용 조건·주의 문구", other: "제한사항" };
  var CIRCLED = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"];

  /* 블록 하나 = 한 언어의 원문 값. 표시용 머리글(【Restrictions】/【제한】)과 항목 제목과 겹치는 라벨은 반복하지 않고,
     값(수치·단위·RE 같은 기준·예외 조건·경고 문구·(a)(b) 대응)은 그대로 둔다. ‘제한사항’(분류 불확실)은 원문 라벨을 값 앞에 남겨 내용을 잃지 않는다 */
  function renderConditionBlock(block, keepLabel) {
    var node = el("div", "regulatory-cond-block");
    node.setAttribute("data-lang", block.lang);
    // ‘제한사항’(분류 불확실)은 언어를 단정하지 않고 ‘원문’으로 표시
    node.appendChild(el("p", "regulatory-cond-block__label", keepLabel ? "원문" : (CONDITION_LANG_LABEL[block.lang] || block.lang)));
    var prefix = keepLabel && block.label ? block.label + " : " : "";
    if (block.items.length > 1) {
      var ul = el("ul", "regulatory-cond-items");
      block.items.forEach(function (it, i) { ul.appendChild(el("li", null, (i === 0 ? prefix : "") + it)); });
      node.appendChild(ul);
    } else {
      node.appendChild(el("p", "regulatory-cond-block__value", prefix + block.value));
    }
    return node;
  }

  /* 항목(적용 제품·부위 → 최대 농도 → 사용 조건·주의 문구 → 제한사항)별로 묶고, 항목 안에서 영문 원문 위 · 한국어 제공 내용 아래.
     분류가 불확실한 블록은 ‘제한사항’에 원문 라벨과 함께 누락 없이 둔다. 반환값: (a)(b) 대응 표기가 있는 항목 수 */
  function renderConditionGroups(blocks, container) {
    var order = CONDITION_GROUPS.map(function (g) { return g.key; }).concat(["other"]);
    var lettered = 0, n = 0;
    order.forEach(function (key) {
      var inGroup = blocks.filter(function (b) { return b.group === key; });
      if (!inGroup.length) return;
      var grp = el("section", "regulatory-cond-group");
      grp.setAttribute("data-group", key);          // 스타일 구분용 (최대 농도 강조 등). 내용·순서는 바꾸지 않는다
      grp.appendChild(el("h4", "regulatory-cond-group__title", (CIRCLED[n] ? CIRCLED[n] + " " : "") + CONDITION_GROUP_TITLE[key]));
      n++;
      var hasLettered = false;
      ["en", "ko"].forEach(function (lang) {
        inGroup.filter(function (b) { return b.lang === lang; }).forEach(function (b) {
          grp.appendChild(renderConditionBlock(b, key === "other"));
          if (b.lettered) hasLettered = true;
        });
      });
      if (hasLettered) lettered++;
      container.appendChild(grp);
    });
    return lettered;
  }

  /* 구조를 확실히 나누기 어려운 원문은 ‘제한사항’ 항목에 그대로 */
  function renderRawGroup(raw, note) {
    var grp = el("section", "regulatory-cond-group");
    grp.setAttribute("data-group", "other");
    grp.appendChild(el("h4", "regulatory-cond-group__title", CONDITION_GROUP_TITLE.other));
    grp.appendChild(renderRawText(raw, note));
    return grp;
  }

  function renderConditionEntry(entry, index, total) {
    var wrap = el("div", "regulatory-cond-entry");
    if (total > 1) {
      wrap.appendChild(el("p", "regulatory-cond-entry__title",
        "규제 항목 " + (index + 1) + " / " + total + (entry.regulate_type ? " · " + entry.regulate_type : "") + (entry.country ? " · " + entry.country : "")));
    }
    var raw = entry.limit_condition;
    if (!raw) {
      var rt = entry.regulate_type || "";
      wrap.appendChild(el("p", "text-caption text-secondary",
        rt.indexOf("금지") >= 0 && rt.indexOf("한도") < 0
          ? "규제 유형 ‘" + rt + "’ — 원문에 별도 제한 조건이 없어요. (제한 없음이 아니라 금지 항목이에요)"
          : (entry.limit_missing || rt.indexOf("한도") >= 0 ? "상세 제한사항 미제공 (규제 유형 ‘" + rt + "’)" : "규제 조건 원문이 제공되지 않았어요.")));
    } else {
      var blocks = parseConditionText(raw);
      if (!blocks) {
        wrap.appendChild(renderRawGroup(raw, "원문 구분이 확실하지 않아 그대로 표시했어요."));
      } else {
        // 항목별로 묶되 문장은 재배치만 하고 번역·요약하지 않는다. 최대 농도는 짝이 되는 적용 제품 조건과 함께 읽도록 (a)(b) 표기를 유지한다.
        var lettered = renderConditionGroups(blocks, wrap);
        if (lettered > 1) {
          wrap.appendChild(el("p", "text-caption text-secondary regulatory-cond-note", "(a)·(b) 같은 표기는 원문 그대로이며 적용 제품과 최대 농도 등 항목 사이의 대응 관계예요. 최대 농도는 짝이 되는 제품 조건과 함께 읽어 주세요."));
        }
      }
    }
    if (entry.proviso) {
      var pv = el("section", "regulatory-cond-group");
      pv.setAttribute("data-group", "proviso");
      pv.appendChild(el("h4", "regulatory-cond-group__title", "단서 조항 (원문)"));
      pv.appendChild(renderRawText(entry.proviso));
      wrap.appendChild(pv);
    }
    return wrap;
  }

  /* 규제 조건을 지정한 컨테이너에 렌더링 (직접 검색 카드와 상세 Modal 이 공유) */
  function renderConditionsInto(res, section, body, note, rawHint) {
    if (!section || !body) return;
    body.innerHTML = "";
    var entries = (res && res.entries) || [];
    if (!entries.length) { show(section, false); return; }
    entries.forEach(function (e, i) { body.appendChild(renderConditionEntry(e, i, entries.length)); });
    var structured = entries.some(function (e) { return !!parseConditionText(e.limit_condition); });
    setText(note, (structured
      ? "원문을 항목별로 묶어 영문 원문 위·한국어 제공 내용 아래로 표시했어요. 번역·요약 없이 수치·단위·조건은 원문 그대로이며 ‘Restrictions/제한’ 머리글만 생략했어요."
      : "원문 그대로예요.") + (rawHint ? " " + rawHint : ""));
    show(section, true);
  }

  function renderConditions(res) {
    renderConditionsInto(res, $("regulatory-single-conditions"), $("regulatory-single-conditions-body"), $("regulatory-single-conditions-note"), "전체 원문은 ‘규제 원문·출처 보기’에서 볼 수 있어요.");
  }

  /* ==========================================================================
     결과 렌더링 (직접 검색 카드 + 상세 Modal)
     ========================================================================== */
  // 조회됨은 허용·안전처럼 보이지 않도록 중립(기본) 배지. 미확인·보류는 warning, 오류는 danger.
  var LOOKUP_LABEL = {
    found: { text: "규제 정보 조회됨", variant: "" },
    no_data: { text: "규제 데이터 미확인", variant: "warning" },
    not_listed: { text: "규제 목록 미등재", variant: "warning" },
    link_required: { text: "성분 연결 확인 필요", variant: "warning" },
    no_market_record: { text: "선택 국가 기록 없음", variant: "warning" },     // 직접 검색: 규제 성분은 연결됐지만 선택 시장 레코드 없음
    not_linked: { text: "규제 성분 연결 미확인", variant: "warning" },        // 직접 검색: 성분정보 후보와 이름이 정확히 일치하는 규제 성분 없음
    reselect: { text: "후보 다시 선택 필요", variant: "warning" },            // 직접 검색: 수집본이 바뀐 후보 key (stale_key·not_found)
    hold: { text: "판단 보류 (미확인 응답)", variant: "warning" },
    api_error: { text: "API 오류", variant: "danger" },
    access: { text: "접근 제한", variant: "danger" },
    source_unavailable: { text: "출처 이용 불가", variant: "danger" },
  };
  /* 식약처 DB 응답의 not_listed 는 '해당 출처에서 일치 항목 없음' — K뷰티 API 의 '규제 목록 미등재' 와 문구를 구분한다 */
  function statusLabel(status, res) {
    var m = LOOKUP_LABEL[status] || { text: "미조회", variant: "" };
    if (res && res.source === "mfds" && status === "not_listed") return { text: "출처에서 일치 항목 없음", variant: "warning" };
    return m;
  }
  var DB_KINDS = { db_missing: "DB 미설치 (수집 DB 없음)", db_incomplete: "수집 미완료 (완료된 수집 없음)", db_error: "DB 읽기 오류" };
  function sourceText(res) {
    if (!res) return "—";
    if (res.source === "mfds") return res.regulation_source ? "규제정보 — " + res.regulation_source.label : "식약처 수집 DB";
    return SOURCE_LABEL.api;
  }
  /* 직접 검색: 사용자가 고른 후보의 출처·수집 시각 (규제 조회 출처·시각과 따로 표시) */
  function ingredientSourceText(res) {
    var s = res && res.ingredient_source;
    if (!s) return "—";
    return (CANDIDATE_SOURCE_LABEL[s.source] || "출처 미상") + " — " + s.label + " · " + (s.collected_at ? formatKst(s.collected_at) + " 수집 완료 (원천 갱신일 아님)" : "수집 시각 미기록");
  }
  var LINK_BASIS_TEXT = { direct: "규제정보 후보를 직접 선택 (이름을 다시 매칭하지 않음)", linked: "성분정보 → 규제정보 이름 직접 정확 일치", ambiguous: "연결 확인 필요", none: "이름이 정확히 일치하는 규제 성분 없음" };
  function linkBasisText(res) {
    var l = res && res.link;
    if (!l) return "—";
    var basis = l.status !== "direct" && l.basis && l.basis.length ? " (" + l.basis.join(" · ") + ")" : "";   // direct 는 문구와 근거가 같아 반복하지 않음
    var target = res.matched_identity && res.matched_identity.std_name ? " → 규제 성분 ‘" + res.matched_identity.std_name + (res.matched_identity.eng_name ? " (" + res.matched_identity.eng_name + ")" : "") + "’" : "";
    return (LINK_BASIS_TEXT[l.status] || l.status) + basis + target + (l.conflict ? " · " + l.conflict : "");
  }

  /* 오류 종류 → 화면 분류. access/auth/rate_limit 은 '접근 제한', 나머지는 'API 오류' */
  var ACCESS_KINDS = { access: "요금제(구독)·인증 확인 필요", auth: "인증 실패", rate_limit: "호출 한도 초과" };
  function errorCategory(err) {
    if (err && DB_KINDS[err.kind]) return "source_unavailable";     // DB 미설치·미완료·읽기 오류 — 미등재로 표시하지 않는다
    if (err && RESELECT_KINDS[err.kind]) return "reselect";          // 직접 검색: 수집본이 바뀐 후보 — 다시 검색·선택
    return err && ACCESS_KINDS[err.kind] ? "access" : "api_error";
  }
  function errorBadge(err) {
    var cat = errorCategory(err);
    if (cat === "source_unavailable") return badge("출처 이용 불가 · " + DB_KINDS[err.kind], "danger");
    if (cat === "reselect") return badge(LOOKUP_LABEL.reselect.text, "warning");
    return badge(cat === "access" ? "접근 제한 · " + ACCESS_KINDS[err.kind] : "API 오류", "danger");
  }

  /* 데이터 없음 응답의 이유를 쉬운 한국어로. 확인된 문구만 근거로 쓰고 의미를 단정하지 않는다 */
  function noDataReason(res) {
    if (!res) return "";
    if (res.source === "mfds") {
      if (res.lookup_status === "no_market_record") return "규제정보에 이 성분 기록은 있지만 선택한 시장의 기록은 없어요" + (res.markets_listed && res.markets_listed.length ? " (기록이 있는 국가: " + res.markets_listed.join(", ") + ")" : "") + ". 허용·안전·규제 없음을 뜻하지 않아요.";
      if (res.lookup_status === "not_linked") return "성분정보에서 고른 성분과 이름이 정확히 일치하는 규제정보 항목을 찾지 못했어요. 허용·안전·규제 없음을 뜻하지 않아요. 이명·포함 일치·유사한 이름으로는 연결하지 않았어요." + (res.related && res.related.length ? " 관련 항목 " + res.related.length + "건은 적용 여부 확인이 필요해요." : "");
      if (res.lookup_status === "link_required" && res.link) return "성분정보에서 고른 성분을 규제정보의 성분 하나로 연결할 수 없어요. " + (res.link_conflict || "") + " 아래 후보 중 맞는 규제 성분을 직접 선택하거나 다시 검색해 주세요.";
      if (res.lookup_status === "not_listed") return "식약처 수집 DB 에서 이름·CAS 가 정확히 일치하는 항목을 찾지 못했어요. 허용·안전·규제 없음을 뜻하지 않아요." + (res.related && res.related.length ? " 관련 항목 " + res.related.length + "건은 적용 여부 확인이 필요해요." : "");
      if (res.lookup_status === "link_required") return "이름·CAS 로 하나의 항목으로 확정할 수 없어요. " + (res.link_conflict || "") + " 후보를 확인해 주세요.";
      return "";
    }
    if (res.lookup_status === "not_listed") return "API 소스에 이 성분의 제한·금지 항목이 없다고 안내했어요. 허용·안전을 뜻하지 않아요.";
    if (res.lookup_status === "no_data") {
      return res.note_mentions_plan
        ? "선택한 시장의 항목이 없어요. API 안내문에 ‘현재 요금제 밖 시장에만 항목이 있다’는 문구가 있어요 (요금제 범위는 관리자 확인 필요)."
        : "선택한 시장의 항목이 API 소스에 없어요. 다른 시장 항목 유무는 아래 API 안내를 참고하세요.";
    }
    return "";
  }

  function lookupBadge(status, res) {
    var m = statusLabel(status, res);
    return badge(m.text, m.variant);
  }

  /* 식약처 공식 조회 페이지(사용제한 원료) 작은 텍스트 링크 — 조회되지 않은 행·항목에만 붙인다.
     regulatory.html 의 버튼·매크로와 같은 주소. 검색어 전달 방식이 확인되지 않아 쿼리를 붙이지 않고, 새 탭으로 열어 화면 상태를 유지한다.
     상태(미등재·매칭 미확정·API 오류 등)는 기존 배지·사유 그대로 두고 링크만 더한다 */
  var MFDS_RESTRICTION_URL = "https://nedrug.mfds.go.kr/pbp/CCBDF01";
  function mfdsTextLink() {
    var a = el("a", "regulatory-mfds-textlink", "식약처에서 추가 확인 ");
    a.href = MFDS_RESTRICTION_URL; a.target = "_blank"; a.rel = "noopener noreferrer";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "regulatory-mfds-icon"); svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("width", "14"); svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M7 3.5H4a1.5 1.5 0 0 0-1.5 1.5v7A1.5 1.5 0 0 0 4 13.5h7a1.5 1.5 0 0 0 1.5-1.5V9M9.5 2.5h4v4M13.5 2.5 7.5 8.5");
    path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor"); path.setAttribute("stroke-width", "1.5"); path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path); a.appendChild(svg);
    a.appendChild(el("span", "regulatory-sr-only", "(새 탭에서 열림)"));
    return a;
  }

  /* 관련 항목 목록 요소 (염류·유도체·성분군 — 확정 규제와 분리) */
  function relatedList(res, ul) {
    if (!ul) return 0;
    ul.innerHTML = "";
    var items = (res && res.related) || [];
    items.forEach(function (r) {
      ul.appendChild(el("li", null, (r.std_name || "") + (r.eng_name ? " (" + r.eng_name + ")" : "") + " · " + (r.country || "") + " · " + (r.regulate_type || "") + " · " + (r.matched_in || "") + " 포함 일치"));
    });
    return items.length;
  }

  /* 연결 후보 목록. onPick 이 있고 후보에 서버가 준 key 가 있으면(직접 검색) '이 규제 성분으로 조회' 버튼을 붙인다 — 사용자가 명시적으로 고를 때만 조회 */
  function candidateList(res, ul, onPick) {
    if (!ul) return 0;
    ul.innerHTML = "";
    var items = (res && res.link_candidates) || [];
    items.forEach(function (c) {
      var li = el("li", null, (c.std_name || "") + (c.eng_name ? " (" + c.eng_name + ")" : "") + (c.cas && c.cas.length ? " · CAS " + c.cas.join(", ") : "") + " · 근거: " + ((c.basis || []).join("·") || "—") + " · 등록 국가: " + ((c.markets || []).join(", ") || "—"));
      if (onPick && c.key) {
        var b = el("button", "btn btn-ghost btn-sm regulatory-link-pick", "이 규제 성분으로 조회");
        b.type = "button";
        b.addEventListener("click", function () { onPick(c); });
        li.appendChild(document.createTextNode(" "));
        li.appendChild(b);
      }
      ul.appendChild(li);
    });
    return items.length;
  }

  function ingredientKr(res, ctx) {
    var ing = (res && res.ingredient) || ctx.selected || {};
    var eng = ing.inci_name || ing.eng_name;
    return ing.kr_name || eng || (ing.code != null ? "code " + ing.code : "이름 미제공");
  }

  function ingredientInci(res, ctx) {
    var ing = (res && res.ingredient) || ctx.selected || {};
    var eng = ing.inci_name || ing.eng_name;
    return ing.kr_name && eng ? eng : "";
  }

  function ingredientFull(res, ctx) {
    var inci = ingredientInci(res, ctx);
    return ingredientKr(res, ctx) + (inci ? " (" + inci + ")" : "");
  }

  function scopeText(res, ctx) {
    if (!res) return "—";
    var code = (res.country && res.country.code) || ctx.marketCode;
    var resolved = res.country && res.country.resolved;
    var listed = res.markets_listed && res.markets_listed.length ? res.markets_listed.join(", ") : "";
    // 등재 시장 목록은 응답을 준 출처의 성분 기준 정보다. K뷰티 API 목록을 식약처 DB 의 제공 범위처럼 보이지 않게 출처를 함께 적는다
    return "시장 코드 " + code + (resolved ? " (" + resolved + ")" : "") +
      (listed ? (res.source === "mfds" ? " · 식약처 DB 에 이 성분 레코드가 있는 국가: " : " · K뷰티 API 에 이 성분이 등재된 시장: ") + listed : "");
  }

  function joinEntries(res, key) {
    if (!res || !res.entries || !res.entries.length) return "";
    return res.entries.map(function (e) { return e[key] || ""; }).filter(Boolean).join("\n\n");
  }

  function detailNode(key) { return document.querySelector('#regulatory-detail-modal [data-detail="' + key + '"]'); }
  function detailItem(key, on) { show(document.querySelector('#regulatory-detail-modal [data-detail-item="' + key + '"]'), on); }

  /* 출처 설명 — 같은 공공데이터 안내 주소가 원시 URL 과 링크로 두 번 보이지 않게 링크 하나로 정리한다. 안내 페이지이며 개별 법령 원문 링크가 아님을 유지 */
  function sourceDescriptionNode(res) {
    var node = el("span");
    if (!res || !res.data_source) { node.textContent = "미제공"; return node; }
    var text = String(res.data_source);
    if (res.source === "mfds" && res.source_page) {
      var cut = text.indexOf("안내 페이지:");
      if (cut >= 0 && text.indexOf(res.source_page) >= 0) text = text.slice(0, cut).trim();
      node.appendChild(document.createTextNode(text + " "));
      var link = el("a", null, "공공데이터포털 안내 페이지"); link.href = res.source_page; link.target = "_blank"; link.rel = "noopener noreferrer";
      node.appendChild(link);
      node.appendChild(document.createTextNode(" (공공데이터 안내 페이지이며 개별 법령 원문 링크가 아니에요)"));
    } else {
      node.textContent = text;
    }
    return node;
  }

  function collectionRunText(res) {
    var run = res && res.collection_run;
    if (!run) return "";
    return "실행 #" + run.run_id + " · 상태 " + (run.status || "—") + " · " + (run.records != null ? run.records + "건" : "건수 미기록") +
      " · 시작 " + formatKst(run.started_at) + " · 완료 " + formatKst(run.finished_at);
  }

  /* 다른 성분을 열 때 이전 성분의 펼침·스크롤 상태가 남지 않게 초기화 */
  function resetDetailModalView() {
    if (!detailModal) return;
    Array.prototype.forEach.call(detailModal.querySelectorAll("details"), function (d) { d.open = false; });
    var body = detailModal.querySelector(".modal-body");
    if (body) body.scrollTop = 0;
  }

  /* 상세 Modal 채우기 — 위: 성분·시장·조회 상태·규제 구분·문서 함량(참고) / 본문: 주요 규제 조건 / 관련 항목(건수) / 접힌 상세 3종 / 간결한 출처.
     API 호출·매칭·판정 로직 없이 응답 값을 배치만 한다. ‘규제 정보 조회됨’은 허용·적합 판정이 아님을 함께 적는다 */
  function fillModal(res, ctx, err) {
    var set = function (key, value) {
      var node = detailNode(key);
      if (!node) return;
      if (value && value.nodeType) replaceChildren(node, value);
      else setText(node, value);
    };
    var sel = ctx.selected || {};
    var entries = (res && res.entries) || [];
    var types = [];
    entries.forEach(function (e) { var t = e.regulate_type || "구분 미제공"; if (types.indexOf(t) < 0) types.push(t); });

    /* ① 성분과 조회 결과 */
    setText($("regulatory-detail-title"), "성분 상세");
    set("head-kr", ingredientKr(res, ctx));
    set("head-inci", ingredientInci(res, ctx) || "영문명 미제공");
    var meta = el("span", "regulatory-detail-head__meta-inner");
    meta.appendChild(el("span", "regulatory-detail-head__market", ctx.marketLabel || "—"));
    meta.appendChild(el("span", "regulatory-detail-head__sep", "/"));
    meta.appendChild(res ? lookupBadge(res.lookup_status, res) : errorBadge(err));
    if (types.length) {
      meta.appendChild(el("span", "regulatory-detail-head__sep", "/"));
      meta.appendChild(el("span", "regulatory-detail-head__type", types.join(", ")));
    }
    set("head-meta", meta);
    var amountNode = detailNode("head-amount");
    if (ctx.amountRef) setText(amountNode, "문서 함량: " + ctx.amountRef + " · 적합 여부는 판정하지 않아요.");
    show(amountNode, !!ctx.amountRef);
    var reason = "";
    if (err) reason = (err.message || "요청에 실패했어요.") + (err.kind ? " (오류 종류: " + err.kind + (err.http_status ? ", 외부 API HTTP " + err.http_status : "") + ")" : "");
    else if (res && res.lookup_status === "found") reason = "규제 항목 " + entries.length + "건" + (res.source === "mfds" ? " (조건별 레코드 모두 표시)" : "") + " · 조회됨은 사용 허용·적합 판정이 아니에요.";
    else if (res && res.lookup_status === "hold") reason = "응답 상태값 ‘" + (res.result_status || "—") + "’은 확인된 값이 아니에요. 임의로 해석하지 않았어요.";
    else if (res) reason = noDataReason(res);
    var reasonNode = detailNode("head-reason");
    setText(reasonNode, reason);
    show(reasonNode, !!reason);

    /* 성분 연결 후보 (식약처 DB 매칭 미확정) — 접지 않고 표시 */
    var candCount = candidateList(res, $("regulatory-detail-candidates-list"));
    show($("regulatory-detail-candidates"), !!(res && res.lookup_status === "link_required" && candCount));

    /* ② 주요 규제 조건 */
    renderConditionsInto(res, $("regulatory-detail-conditions-section"), $("regulatory-detail-conditions"), $("regulatory-detail-conditions-note"), "전체 원문은 아래 ‘전체 원문·고시 정보’에서 볼 수 있어요.");

    /* ③ 관련 항목 — 건수·확인 필요는 항상 보이고 목록만 접힘 */
    var relCount = relatedList(res, $("regulatory-detail-related-list"));
    setText($("regulatory-detail-related-summary"), "관련 항목 " + relCount + "건 · 적용 여부 확인 필요");
    show($("regulatory-detail-related-section"), relCount > 0);

    /* ④-1 입력·매칭 근거 */
    set("input-raw", ctx.inputRaw);
    set("input-market", ctx.marketLabel);
    // 직접 검색·파일 행 선택(sel.key)은 출처로 표시하고 key 자체는 표시하지 않는다. sel.code 분기는 이전 K뷰티 후보용 — 화면에서 더 이상 만들지 않음 (4단계 삭제)
    set("match-name", sel.key ? ingredientFull(res, ctx) + " · " + candidateSourceLabel(sel)
      : (sel.code != null ? ingredientFull(res, ctx) + " · code " + sel.code : "매칭 전"));
    set("match-method", ctx.matchMethod || "—");
    set("link-basis", res && res.link ? linkBasisText(res) : (res && res.source === "mfds"
      ? ((res.link_basis && res.link_basis.length ? res.link_basis.join("·") : "—") + (res.matched_identity ? " → " + res.matched_identity.std_name + (res.matched_identity.eng_name ? " (" + res.matched_identity.eng_name + ")" : "") : "") + (res.link_conflict ? " · " + res.link_conflict : ""))
      : (res ? "해당 없음 (K뷰티 API 는 성분 code 로 조회)" : "해당 없음")));
    set("match-updated", sel.key
      ? (res && res.ingredient_source ? ingredientSourceText(res) : (sel.snapshot && sel.snapshot.collected_at ? candidateSourceLabel(sel) + " · " + formatKst(sel.snapshot.collected_at) + " 수집 완료 (원천 갱신일 아님)" : "미제공"))
      : (sel.record_updated_at ? formatKst(sel.record_updated_at) + " — API 성분 레코드의 updated_at 이며 규제 자료 갱신일이 아니에요." : "미제공"));
    set("input-location", ctx.location || "해당 없음");

    /* ④-2 전체 원문·고시 정보 */
    set("lookup-notice-name", joinEntries(res, "notice_ingr_name") || (res ? "미제공" : "—"));
    set("lookup-raw", joinEntries(res, "limit_condition") || (res && res.lookup_status === "found" ? "미제공" : (res ? "규제 데이터 없음 (응답 상태값: " + (res.result_status || "—") + ")" : "—")));
    set("lookup-proviso", joinEntries(res, "proviso") || (res ? "미제공" : "—"));
    set("lookup-note", res && res.result_note ? res.result_note : "없음");
    set("lookup-result-status", res ? res.result_status : (err && err.kind ? "오류 종류: " + err.kind : "—"));
    set("lookup-scope", scopeText(res, ctx));

    /* ④-3 출처·날짜 상세 — 의미가 다른 날짜는 합치지 않고, 같은 수집 완료 기록을 가리키는 수집 시각은 아래 확보 시각 한 번만 */
    set("source", sourceDescriptionNode(res));
    set("disclaimer", res && res.disclaimer ? res.disclaimer : "미제공");
    set("refresh-policy", res ? refreshText(res) + (res.refresh_basis ? " — " + res.refresh_basis : "") : "—");
    var collectedDiffers = !!(res && res.source === "mfds" && res.collected_at && res.collected_at !== res.acquired_at);
    detailItem("collected-at", collectedDiffers);
    set("collected-at", collectedDiffers ? formatKst(res.collected_at) + " (수집 완료 시각, DB 기록 — 확보 시각과 다른 값)" : "해당 없음");
    var runText = collectionRunText(res);
    detailItem("collection-run", !!runText);
    set("collection-run", runText || "해당 없음");
    set("source-updated", res && res.source_updated_at ? res.source_updated_at : "미제공");
    set("law-dates", res && res.law_dates ? res.law_dates : "미제공");
    set("queried-at", (res && res.queried_at ? formatKst(res.queried_at) : "—") + (res && res.source === "mfds" ? " (DB 를 읽은 시각)" : (res ? " (외부 API 응답을 받은 시각)" : "")));
    set("verified-at", "미실시");

    /* ⑤ 간결한 출처 */
    set("foot-source", res ? sourceText(res) : (SOURCE_LABEL[ctx.source] || (err && err.source === "mfds" ? SOURCE_LABEL.mfds : "—")));
    set("foot-acquired", acquiredText(res));

    resetDetailModalView();
  }

  function renderSingle(res, ctx) {
    state.resultKey = conditionKey(ctx);
    setText($("regulatory-result-time"), formatKst(res.acquired_at || res.queried_at));
    setText($("regulatory-single-name"), ingredientKr(res, ctx));
    setText($("regulatory-single-inci"), ingredientInci(res, ctx) || "영문명 미제공");
    setText($("regulatory-single-market"), ctx.marketLabel);

    var st = res.lookup_status;
    replaceChildren($("regulatory-single-status"), lookupBadge(st, res));
    var statusNote = "";
    if (st === "found") statusNote = "규제 항목 " + res.entries.length + "건" + (res.source === "mfds" ? " (조건별 레코드 모두 표시)" : " 반환");
    else if (st === "no_data" || st === "not_listed" || st === "link_required" || st === "no_market_record" || st === "not_linked") statusNote = "응답 상태값: " + (res.result_status || "—");
    else statusNote = "응답 상태값: " + (res.result_status || "—") + " (확인되지 않은 값)";
    setText($("regulatory-single-status-note"), statusNote);

    var types = res.entries.map(function (e) { return e.regulate_type || "구분 미제공"; });
    setText($("regulatory-single-type"), res.entries.length ? types.join(", ") : "—");
    var TYPE_NOTE = { no_data: "시장 항목 없음", no_market_record: "선택 국가 기록 없음", not_linked: "규제 성분 연결 미확인", link_required: "성분 연결 확인 필요" };
    setText($("regulatory-single-type-note"), res.entries.length
      ? "원문 표기"
      : (TYPE_NOTE[st] || (st === "not_listed" ? (res.source === "mfds" ? "출처에서 일치 항목 없음" : "목록 미등재") : "판단 보류")));

    var noData = st === "no_data" || st === "not_listed" || st === "no_market_record" || st === "not_linked";
    show($("regulatory-single-nodata"), noData);
    var NODATA_TITLE = {
      not_listed: res.source === "mfds" ? "식약처 수집 DB 에서 일치하는 규제 항목을 찾지 못했어요" : "API 규제 목록에 이 성분이 등재되어 있지 않아요",
      no_market_record: "규제정보에 이 성분은 있지만 선택한 시장의 기록이 없어요",
      not_linked: "고른 성분과 연결되는 규제정보 성분을 확인하지 못했어요",
    };
    setText($("regulatory-single-nodata-title"), NODATA_TITLE[st] || "선택한 시장의 규제 데이터가 확인되지 않았어요");
    show($("regulatory-single-link"), st === "link_required");
    setText($("regulatory-single-link-note"), noDataReason(res) || "—");
    // 직접 검색: 연결 후보마다 '이 규제 성분으로 조회' — 사용자가 고른 규제정보 후보로 다시 조회한다 (자동 선택 없음)
    candidateList(res, $("regulatory-single-link-candidates"), function (c) {
      pickCandidate({ key: c.key, source: c.source, kr_name: c.std_name, eng_name: c.eng_name, cas: (c.cas || []).join(", "), matched: [] }, "연결 후보 선택");
      runLookup();
    });
    setText($("regulatory-single-ingredient-source"), res.ingredient_source ? ingredientSourceText(res) : "—");
    setText($("regulatory-single-link-basis"), res.link ? linkBasisText(res) : "—");
    var relN = relatedList(res, $("regulatory-single-related-list"));
    show($("regulatory-single-related"), relN > 0);
    setText($("regulatory-single-related-note"), relN ? "이름을 포함하는 항목 " + relN + "건 (염류·유도체·성분군 등). 확정 규제가 아니며 적용 여부는 직접 확인해 주세요." : "");
    setText($("regulatory-single-source"), sourceText(res));
    setText($("regulatory-single-acquired"), acquiredText(res));
    setText($("regulatory-single-refresh"), refreshText(res));
    setText($("regulatory-single-srcdate"), res.source_updated_at ? formatKst(res.source_updated_at) : "미제공");
    setText($("regulatory-single-lawdate"), res.law_dates ? res.law_dates : "미제공");
    setText($("regulatory-single-nodata-body"), (noDataReason(res) || "허용되거나 안전하다는 뜻은 아니에요.") + " 다른 자료로 추가 확인이 필요해요.");
    var nodataNote = $("regulatory-single-nodata-note");
    var noteLabel = res.source === "mfds" ? "조회 안내: " : "API 안내(원문): ";
    if (nodataNote) { setText(nodataNote, res.result_note ? noteLabel + res.result_note : ""); show(nodataNote, !!res.result_note); }
    show($("regulatory-single-hold"), res.lookup_status === "hold");
    setText($("regulatory-single-hold-note"), "응답 상태값 '" + (res.result_status || "—") + "'은 확인된 값이 아니에요. 임의로 해석하지 않았어요.");
    show($("regulatory-asean-notice"), ctx.marketCode === "ASEAN");

    renderConditions(res);
    setText($("regulatory-single-scope"), scopeText(res, ctx));

    state.lastSingle = { res: res, ctx: ctx, err: null };
    fillModal(res, ctx, null);
    setResult("single");
  }

  /* 직접 검색 카드의 '규제 원문·출처 보기' — 상세 Modal 은 일괄 조회와 공유하므로 열기 직전에 마지막 직접 검색 결과로 다시 채운다 */
  var singleDetailBtn = document.querySelector('#regulatory-result-single [data-modal-open="regulatory-detail-modal"]');
  if (singleDetailBtn) {
    singleDetailBtn.addEventListener("click", function () {
      if (state.lastSingle) fillModal(state.lastSingle.res, state.lastSingle.ctx, state.lastSingle.err);
    });
  }

  function renderError(err, ctx) {
    state.resultKey = conditionKey(ctx);
    setText($("regulatory-result-time"), "—");
    var reselect = errorCategory(err) === "reselect";
    setText($("regulatory-result-error-reason"), ((err && err.message) || "잠시 후 다시 시도해 주세요.") +
      (reselect ? " 이전 선택은 해제했어요. 성분명을 다시 검색해 후보를 선택해 주세요." : ""));
    var category = errorCategory(err) === "access" ? "접근 제한 (" + ACCESS_KINDS[err.kind] + ")"
      : (errorCategory(err) === "source_unavailable" ? "출처 이용 불가 (" + DB_KINDS[err.kind] + (err.source && CANDIDATE_SOURCE_LABEL[err.source] ? " · " + CANDIDATE_SOURCE_LABEL[err.source] : "") + ")"
      : (reselect ? LOOKUP_LABEL.reselect.text
      : (err && err.kind === "validation" ? "입력 확인" : (err && err.kind === "network" ? "연결 실패" : "API 오류"))));
    setText($("regulatory-single-source"), "조회 출처: " + (SOURCE_LABEL[ctx.source] || ctx.source || "—"));
    setText($("regulatory-single-acquired"), "—"); setText($("regulatory-single-refresh"), "—");
    setText($("regulatory-result-error-kind"),
      category + " · 오류 종류: " + ((err && err.kind) || "unknown") +
      (err && err.http_status ? " · 외부 API HTTP " + err.http_status : "") + " · 입력한 조건은 그대로 남아 있어요.");
    state.lastSingle = { res: null, ctx: ctx, err: err };
    fillModal(null, ctx, err);
    setResult("error");
  }

  /* ==========================================================================
     파일로 일괄 조회 — 업로드 → (시트 선택) → 성분 추출 → 확인·수정   (규제 일괄 조회는 다음 단계, 호출하지 않음)
     ========================================================================== */
  var fileForm = $("regulatory-file-form");
  var fileInput = $("regulatory-file-input");
  var dropzone = $("regulatory-file-dropzone");
  var fileSubmit = $("regulatory-file-submit");
  var fileSubmitLabel = fileSubmit ? fileSubmit.textContent : "";
  var reviewBody = $("regulatory-review-body");

  var FILE_OK_EXT = /\.(pdf|xlsx|png|jpe?g)$/i;
  var FILE_NOT_YET_EXT = /\.(gif|webp|tiff?|bmp|heic|xls|csv|docx?|hwp|txt)$/i;
  var FILE_MAX_BYTES = 10 * 1024 * 1024;
  var UNSUPPORTED_MESSAGE = "현재 텍스트 PDF · 스캔 PDF · PNG/JPG 이미지 · Excel(.xlsx)만 지원합니다.";
  var ERROR_KIND_LABEL = { validation: "입력 확인", limit: "제한 초과", unsupported: "형식 미지원", unreadable: "읽기 실패", network: "연결 실패", http: "서버 오류", invalid_response: "응답 오류",
                           ocr_unavailable: "OCR 준비 안 됨 (서버 설치 필요)", ocr_timeout: "OCR 시간 초과", ocr_failed: "OCR 처리 실패" };

  // items: 서버 추출값(name_raw/amount_raw/location/needs_review/review_reasons) + 화면 편집값(name/amount/include/user_added)
  var fileState = { seq: 0, items: [], nextId: 1, sheets: [], selectedSheet: null, lastFile: null, emptyResult: false,
                    selectedFile: null,   // 브라우저에서 고른 파일 (카드 표시·선택 창 취소 시 복원용)
                    doc: null,            // 추출 응답의 document_market / document_use / scope / kind
                    matching: false,      // 성분 확인 진행 중 (중복 실행 방지)
                    looking: false,       // 규제 조회 진행 중
                    matchSeq: 0,          // 늦게 도착한 이전 후보 검색 응답 무시 (새 파일·시트·다시 업로드·새 확인 작업)
                    batchSeq: 0,          // 늦게 도착한 이전 조회 응답 무시
                    batchResultKey: null, // 표시 중인 일괄 결과의 조건 키 (시장 + 행별 검색어·선택 key)
                    batchStaleSeen: false,// 마지막 일괄 조회 중 stale_key 를 만났는지 (수집본 변경 → 재조회 필요 안내)
                    batchMarket: null };  // 표시 중인 결과의 시장 코드

  function currentFile() { return fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null; }

  function setFileBusy(on, label) {
    if (!fileSubmit) return;
    fileSubmit.disabled = on;
    fileSubmit.innerHTML = "";
    if (on) {
      fileSubmit.appendChild(el("span", "spinner spinner-sm"));
      fileSubmit.appendChild(document.createTextNode(" " + (label || "처리 중")));
    } else {
      fileSubmit.textContent = fileSubmitLabel;
    }
    var confirmBtn = $("regulatory-sheet-confirm");
    if (confirmBtn) confirmBtn.disabled = on;
  }

  function showFileError(err) {
    var box = $("regulatory-file-result-error");
    if (!box) return;
    var kind = (err && err.kind) || "unknown";
    setText($("regulatory-file-error-title"), kind === "unsupported" ? "아직 지원하지 않는 파일이에요"
      : (kind === "ocr_unavailable" ? "이미지 인식(OCR)이 서버에 준비되지 않았어요" : (kind === "ocr_timeout" ? "이미지 인식(OCR) 시간이 초과됐어요" : "파일을 처리하지 못했어요")));
    setText($("regulatory-file-error-message"), (err && err.message) || "잠시 후 다시 시도해 주세요.");
    setText($("regulatory-file-error-kind"), "오류 종류: " + (ERROR_KIND_LABEL[kind] || kind) + " · 파일을 바꾸거나 수정한 뒤 다시 분석해 주세요.");
    show(box, true);
  }

  function hideFileError() { show($("regulatory-file-result-error"), false); }

  /* ---- 선택된 파일 카드 -------------------------------------------------------
     업로드 영역 안에서 안내(label) ↔ 카드(파일명·형식·용량·상태·버튼)를 바꿔 보여 준다. 상태는 실제 처리 단계와 같다:
       selected  브라우저에서 파일만 고른 상태 (서버 전송 전)      invalid  확장자·용량이 맞지 않음 (전송하지 않음)
       busy      '파일 분석'을 눌러 /api/regulatory/extract 진행 중  sheet    서버가 시트 목록만 돌려줌 (시트 선택 대기)
       done      추출 성공 응답을 받음                            warning  파일은 읽었지만 성분 표 없음
       error     서버 처리 실패 (사유는 아래 오류 안내에)
     진행률은 서버가 주지 않으므로 표시하지 않는다. busy 동안은 파일 변경·해제를 막아 늦은 응답이 새 파일 상태를 덮어쓰지 않게 한다. */
  var fileCard = $("regulatory-file-card"), fileIdle = $("regulatory-file-idle");
  var fileChangeBtn = $("regulatory-file-change"), fileClearBtn = $("regulatory-file-clear");
  var SVG_NS = "http://www.w3.org/2000/svg";
  var FILE_ICON_PATHS = {
    pdf:   ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5", "M9 13h6", "M9 17h6"],
    xlsx:  ["M4 5h16v14H4z", "M4 10h16", "M4 15h16", "M10 5v14"],
    image: ["M4 5h16v14H4z", "m4 16 4-4 4 4 3-3 5 5", "M16 9h.01"],
    file:  ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5"]
  };
  var STATUS_ICON_PATHS = {
    check: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "m8.5 12 2.5 2.5 4.5-5"],
    alert: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 8v4", "M12 16h.01"],
    list:  ["M8 6h12", "M8 12h12", "M8 18h12", "M4 6h.01", "M4 12h.01", "M4 18h.01"]
  };
  var FILE_STATUS_CLASS = { selected: "is-selected", invalid: "is-error", busy: "is-busy", sheet: "is-selected", done: "is-done", warning: "is-warning", error: "is-error" };
  var FILE_STATUS_ICON = { selected: "check", invalid: "alert", busy: null, sheet: "list", done: "check", warning: "alert", error: "alert" };

  function lineIcon(paths, size) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", size); svg.setAttribute("height", size);
    svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
    paths.forEach(function (d) { var p = document.createElementNS(SVG_NS, "path"); p.setAttribute("d", d); svg.appendChild(p); });
    return svg;
  }

  function fileKindOf(name) {
    if (/\.pdf$/i.test(name)) return "pdf";
    if (/\.xlsx$/i.test(name)) return "xlsx";
    if (/\.(png|jpe?g)$/i.test(name)) return "image";
    return "file";
  }

  function fileTypeLabel(name) {
    var ext = (name.match(/\.([a-z0-9]+)$/i) || [])[1] || "";
    var kind = fileKindOf(name);
    if (kind === "pdf") return "PDF 문서";
    if (kind === "xlsx") return "Excel 통합 문서 (XLSX)";
    if (kind === "image") return ext.toUpperCase() + " 이미지";
    return ext ? ext.toUpperCase() + " 파일" : "형식 미확인";
  }

  function formatBytes(n) {
    if (!(n >= 0)) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n < 100 * 1024 ? (n / 1024).toFixed(1) : Math.round(n / 1024)) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }

  /* 업로드 전 확인: 확장자·용량. 서버도 같은 검증을 다시 한다. 문제 없으면 null */
  function clientFileError(f) {
    if (FILE_NOT_YET_EXT.test(f.name) || !FILE_OK_EXT.test(f.name)) return { kind: "unsupported", message: UNSUPPORTED_MESSAGE };
    if (f.size > FILE_MAX_BYTES) return { kind: "limit", message: "파일이 너무 커요. 10 MB 이하 파일을 올려 주세요." };
    return null;
  }

  function showFileCard(f) {
    if (!fileCard) return;
    var name = $("regulatory-file-card-name");
    if (name) { name.textContent = f.name; name.title = f.name; }              // textContent 로만 넣어 파일명을 안전한 글자로 출력
    setText($("regulatory-file-card-meta"), fileTypeLabel(f.name) + " · " + formatBytes(f.size));
    replaceChildren($("regulatory-file-card-icon"), lineIcon(FILE_ICON_PATHS[fileKindOf(f.name)], 22));
    if (dropzone) { dropzone.classList.add("has-file"); dropzone.classList.remove("is-error"); }
    show(fileIdle, false);
    show(fileCard, true);
  }

  function hideFileCard() {
    if (dropzone) dropzone.classList.remove("has-file", "is-invalid");
    show(fileCard, false);
    show(fileIdle, true);
  }

  function setFileCardStatus(state, text) {
    var status = $("regulatory-file-card-status");
    if (!status) return;
    status.className = "regulatory-file-card__status " + (FILE_STATUS_CLASS[state] || "");
    status.innerHTML = "";
    if (state === "busy") status.appendChild(el("span", "spinner spinner-sm"));
    else if (FILE_STATUS_ICON[state]) status.appendChild(lineIcon(STATUS_ICON_PATHS[FILE_STATUS_ICON[state]], 16));
    status.appendChild(el("span", null, text));
    var busy = state === "busy";
    if (fileChangeBtn) fileChangeBtn.disabled = busy;
    if (fileClearBtn) fileClearBtn.disabled = busy;
    if (fileInput) fileInput.disabled = busy;                                   // 진행 중에는 키보드·클릭으로도 파일을 바꾸지 못하게
    if (dropzone) dropzone.classList.toggle("is-invalid", state === "invalid");
  }

  /* 선택 창을 취소하면 일부 브라우저는 기존 선택을 비운다 → 직전 유효 파일을 되돌린다 (되돌리지 못하면 false) */
  function restoreInputFile(f) {
    try {
      var dt = new DataTransfer();
      dt.items.add(f);
      fileInput.files = dt.files;
      return fileInput.files.length === 1;
    } catch (e) { return false; }
  }

  /* 새로 고른 파일을 화면에 반영한다. 다른 파일이면 이전 파일의 시트·추출·매칭·조회 결과를 모두 지운다 (새 파일 결과로 보이지 않게) */
  function applySelectedFile(f) {
    hideFileError();
    show($("regulatory-file-error"), false);
    fileState.sheets = []; fileState.selectedSheet = null;
    if (fileState.lastFile && f !== fileState.lastFile) { resetFileResults(); setFileStep("upload"); }
    fileState.selectedFile = f;
    showFileCard(f);
    var err = clientFileError(f);
    if (err) {
      setFileCardStatus("invalid", err.kind === "limit" ? "용량 초과 — 10 MB 이하 파일로 바꿔 주세요" : "지원하지 않는 형식 — PDF · XLSX · PNG/JPG 파일로 바꿔 주세요");
      showFileError(err);
    } else {
      setFileCardStatus("selected", "파일 선택 완료 — ‘파일 분석’을 누르면 서버로 보내 성분을 추출해요");
    }
  }

  /* 선택 해제. 결과가 있으면 함께 지운다. 같은 파일을 다시 골라도 change 가 나도록 값을 비운다 */
  function clearFileSelection(focusInput) {
    fileState.selectedFile = null;
    if (fileInput) { fileInput.disabled = false; fileInput.value = ""; }
    hideFileCard();
    hideFileError();
    show($("regulatory-file-error"), false);
    if (dropzone) dropzone.classList.remove("is-error");
    if (fileState.lastFile || fileState.items.length || fileState.sheets.length) { resetFileResults(); setFileStep("upload"); }
    fileState.sheets = []; fileState.selectedSheet = null;
    if (focusInput && fileInput) fileInput.focus();
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var f = currentFile();
      if (!f) {
        // 선택 창 취소: 기존 유효 선택 유지. 되돌릴 수 없는 환경이면 '선택 없음'을 그대로 보여 준다 (선택된 것처럼 두지 않음)
        if (fileState.selectedFile && restoreInputFile(fileState.selectedFile)) return;
        clearFileSelection(false);
        return;
      }
      if (f === fileState.selectedFile) return;
      applySelectedFile(f);
    });
  }
  if (fileChangeBtn) fileChangeBtn.addEventListener("click", function () { if (fileInput && !fileInput.disabled) fileInput.click(); });
  if (fileClearBtn) fileClearBtn.addEventListener("click", function () { if (!fileClearBtn.disabled) clearFileSelection(true); });

  if (dropzone) {
    ["dragenter", "dragover"].forEach(function (type) {
      dropzone.addEventListener(type, function (e) { e.preventDefault(); if (!(fileInput && fileInput.disabled)) dropzone.classList.add("is-dragover"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      dropzone.addEventListener(type, function (e) { e.preventDefault(); dropzone.classList.remove("is-dragover"); });
    });
    dropzone.addEventListener("drop", function (e) {
      if (!fileInput || fileInput.disabled) return;                               // 분석 진행 중에는 드롭으로도 바꾸지 않는다
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        var first = e.dataTransfer.files[0];
        if (!restoreInputFile(first)) fileInput.files = e.dataTransfer.files;    // 파일 1개만 (실패하면 목록 그대로)
        fileInput.dispatchEvent(new Event("change"));                            // 클릭 선택과 같은 경로
      }
    });
  }

  function validateFileForm() {
    var f = currentFile();
    var market = $("regulatory-file-market");
    var fileEmpty = !f;
    var marketEmpty = !market || !market.value;
    if (dropzone) dropzone.classList.toggle("is-error", fileEmpty);
    show($("regulatory-file-error"), fileEmpty);
    if (market) market.classList.toggle("is-error", marketEmpty);
    show($("regulatory-file-market-error"), marketEmpty);
    if (fileEmpty || marketEmpty) return false;
    var err = clientFileError(f);
    if (err) {
      setFileCardStatus("invalid", err.kind === "limit" ? "용량 초과 — 10 MB 이하 파일로 바꿔 주세요" : "지원하지 않는 형식 — PDF · XLSX · PNG/JPG 파일로 바꿔 주세요");
      showFileError(err);
      return false;
    }
    return true;
  }

  /* 서버로 전송 → 상태별 처리. sheet 를 주면 그 시트만 추출 */
  function startExtract(sheet) {
    var f = currentFile();
    if (!f) return;
    hideFileError();
    var seq = ++fileState.seq;
    // 이전 파일의 성분 확인·규제 조회가 진행 중이면 중단하고(순번 증가) 플래그·버튼을 정리한다. 결과가 새 표와 섞이지 않게 한다
    fileState.batchSeq++; fileState.matchSeq++;
    fileState.looking = false;
    if (fileState.matching) setMatchBusy(false);
    fileState.batchResultKey = null; fileState.batchMarket = null; fileState.batchStaleSeen = false;
    if ($("regulatory-result-batch") && !$("regulatory-result-batch").hidden) setResult("hidden");
    var fd = new FormData();
    fd.append("file", f, f.name);
    if (sheet) fd.append("sheet", sheet);
    setFileBusy(true, sheet ? "시트 추출 중" : "파일 분석 중");
    setFileStep("loading");
    var isImage = /\.(png|jpe?g)$/i.test(f.name);
    setText($("regulatory-file-loading-label"), sheet ? "선택한 시트에서 성분을 추출하는 중이에요"
      : (isImage ? "이미지를 인식(OCR)하는 중이에요 — 최대 25초 정도 걸릴 수 있어요" : "파일을 확인하고 성분을 추출하는 중이에요 (텍스트가 없는 쪽은 OCR 로 읽어요)"));
    setFileCardStatus("busy", sheet ? "시트 추출 중 — 서버에서 선택한 시트를 읽고 있어요"
      : (isImage ? "이미지 인식(OCR) 중 — 최대 25초 정도 걸릴 수 있어요" : "파일 분석 중 — 서버에서 성분을 추출하고 있어요"));
    apiPost("/api/regulatory/extract", fd).then(function (body) {
      if (seq !== fileState.seq) return;              // 그 사이 다른 파일·시트로 다시 보냈으면 무시
      setFileBusy(false);
      fileState.lastFile = f;
      if (body.status === "sheet_required") { renderSheets(body.sheets || []); setFileCardStatus("sheet", "파일 확인 완료 — 시트를 고르면 성분을 추출해요"); return; }
      renderReview(body);
      var n = (body.items || []).length;
      if (body.status === "extracted" && n) setFileCardStatus("done", "분석 완료 — 성분 " + n + "행을 추출했어요");
      else setFileCardStatus("warning", "분석 완료 — 성분 표를 찾지 못했어요 (아래 안내 참고)");
    }).catch(function (err) {
      if (seq !== fileState.seq) return;
      setFileBusy(false);
      // 실패하면 이전 파일의 확인 표(수정 내용 포함)를 그대로 되살린다. 새 결과로 바꾸지 않았음을 오류 안내로 알린다
      setFileStep(fileState.items.length ? "review" : "upload");
      showFileError(err);
      setFileCardStatus("error", "분석 실패 — 아래 오류 안내를 확인하고 파일을 바꾸거나 다시 시도해 주세요");
      updateLookupSummary();
    });
  }

  if (fileForm) {
    fileForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!validateFileForm()) return;
      startExtract(null);
    });
  }

  /* 시트 선택 */
  function renderSheets(sheets) {
    fileState.sheets = sheets;
    var select = $("regulatory-sheet-select");
    if (select) {
      select.innerHTML = "";
      var first = el("option", null, "선택하세요"); first.value = ""; select.appendChild(first);
      sheets.forEach(function (name) { var o = el("option", null, name); o.value = name; select.appendChild(o); });
      select.classList.remove("is-error");
    }
    setFileStep("sheet");
  }

  var sheetConfirm = $("regulatory-sheet-confirm");
  if (sheetConfirm) {
    sheetConfirm.addEventListener("click", function () {
      var select = $("regulatory-sheet-select");
      var name = select ? select.value : "";
      if (!name) { if (select) select.classList.add("is-error"); return; }
      fileState.selectedSheet = name;
      startExtract(name);
    });
  }

  /* 추출 결과 → 편집 가능한 표 */
  function renderReview(result) {
    fileState.items = (result.items || []).map(function (it) {
      return {
        id: it.id, name_raw: it.name_raw || "", amount_raw: it.amount_raw, amount_unit_hint: it.amount_unit_hint || null,
        role_raw: it.role_raw || null, location: it.location || "—", source: it.source || "text", inci_raw: it.inci_raw || null,
        needs_review: !!it.needs_review, review_reasons: it.review_reasons || [],
        name: it.name_raw || "", amount: it.amount_raw || "", include: true, user_added: false, edited: false,
        match: null, selected: null, result: null,   // match: 후보 검색 결과 / selected: 사용자가 고른 후보 / result: 규제 조회 결과 (행별)
      };
    });
    fileState.nextId = 1;
    fileState.doc = { kind: result.file && result.file.kind, scope: result.scope || {}, market: result.document_market || null, use: result.document_use || null };
    fileState.batchResultKey = null; fileState.batchMarket = null; fileState.batchStaleSeen = false;
    if (!$("regulatory-result-single") || $("regulatory-result-single").hidden) setResult("hidden");
    setText($("regulatory-match-progress"), MATCH_PROGRESS_DEFAULT);

    var scopeText = "";
    var sc = result.scope || {};
    if (result.file && result.file.kind === "pdf") scopeText = "처리 범위: " + (sc.processed || (sc.pages + "쪽")) + (sc.ocr_pages && sc.ocr_pages.length ? " · OCR " + sc.ocr_pages.map(function (p) { return p + "쪽"; }).join(", ") : "");
    else if (result.file && result.file.kind === "image") scopeText = "처리 범위: " + (sc.processed || "이미지") + " · OCR";
    else if (result.file && result.file.kind === "xlsx") scopeText = "처리 범위: 시트 ‘" + (sc.selected_sheet || "") + "’ (" + (sc.scanned_rows || 0) + "행 확인" + (sc.sheets > 1 ? ", 전체 " + sc.sheets + "개 시트 중" : "") + ")";
    setText($("regulatory-review-scope"), scopeText + (result.extracted_at ? " · 추출 시각 " + formatKst(result.extracted_at) : ""));

    var docMarket = $("regulatory-file-doc-market");
    if (docMarket) docMarket.textContent = result.document_market && result.document_market.text ? result.document_market.text + " (" + result.document_market.location + ")" : "미확인";

    var notesList = $("regulatory-review-notes");
    var notes = (result.notes || []).slice();
    if (result.document_use && result.document_use.text) notes.push("문서에 적힌 제품 유형·사용 조건: " + result.document_use.text + " (" + result.document_use.location + ")");
    if (notesList) { notesList.innerHTML = ""; notes.forEach(function (n) { notesList.appendChild(el("li", null, n)); }); }
    show($("regulatory-review-partial"), notes.length > 0);

    fileState.emptyResult = result.status === "empty";
    var emptyTitle = $("regulatory-file-empty-title"), emptyBody = $("regulatory-file-empty-body");
    var outcome = result.ocr && result.ocr.outcome;
    if (result.file && result.file.kind === "image") {
      setText(emptyTitle, outcome === "no_text" ? "이미지에서 글자를 인식하지 못했어요" : "글자는 읽었지만 성분 표 구조를 찾지 못했어요");
      setText(emptyBody, outcome === "no_text"
        ? "글자가 선명하고 기울어지지 않은 이미지를 다시 올려 주세요. 스캔 해상도를 높이면 도움이 돼요."
        : "‘한글 성분명 · INCI Name · 함량’ 같은 제목 줄이 있는 표가 필요해요. 제목 줄이 선명한 이미지를 올리거나 아래 ‘행 추가’로 직접 입력해 주세요.");
    } else if (result.file && result.file.kind === "xlsx") {
      setText(emptyTitle, "성분 표를 찾지 못했어요");
      setText(emptyBody, "이 시트에는 ‘INCI name · 성분명 · 원료명’ 같은 제목이 있는 표가 없었어요. 다른 시트를 고르거나 아래 ‘행 추가’로 직접 입력해 주세요.");
    } else {
      setText(emptyTitle, "성분 표를 찾지 못했어요");
      setText(emptyBody, "파일은 읽었지만 ‘INCI name · 성분명 · 원료명’ 같은 제목이 있는 표가 없었어요. 아래 ‘행 추가’로 직접 입력하거나 다른 파일을 올려 주세요.");
    }
    if (reviewBody) { reviewBody.innerHTML = ""; fileState.items.forEach(function (it) { reviewBody.appendChild(rowElement(it)); }); }
    setFileStep("review");
    updateReviewCount();
  }

  function statusBadge(it) {
    if (it.user_added) return badge("직접 입력", "warning");
    if (it.edited) return badge("수정됨", "");
    if (it.source === "ocr") return badge("확인 필요 (OCR)", "warning");
    if (it.needs_review) return badge("확인 필요", "warning");
    return badge("추출됨", "");
  }

  function rowElement(it) {
    var tr = el("tr");
    tr.setAttribute("data-row-id", it.id);

    var tdCheck = el("td");
    var check = el("input"); check.type = "checkbox"; check.checked = it.include; check.setAttribute("aria-label", "조회 포함");
    check.addEventListener("change", function () { it.include = check.checked; updateReviewCount(); });
    var checkWrap = el("label", "form-check"); checkWrap.appendChild(check); tdCheck.appendChild(checkWrap);
    tr.appendChild(tdCheck);

    var tdName = el("td");
    tdName.appendChild(el("p", "regulatory-review-origin", "원문: " + (it.user_added ? "(직접 입력)" : (it.name_raw || "(비어 있음)")) + (it.inci_raw ? " · " + it.inci_raw : "")));
    var nameInput = el("input", "form-control form-control-sm"); nameInput.type = "text"; nameInput.value = it.name;
    nameInput.placeholder = "성분명 (한글 또는 INCI)"; nameInput.setAttribute("aria-label", "성분명 수정");
    nameInput.addEventListener("input", function () {
      it.name = nameInput.value;
      if (!it.user_added && nameInput.value.trim() !== it.name_raw) it.edited = true; else it.edited = false;
      invalidateRow(it);                       // 성분명이 바뀌면 이전 매칭·조회 결과는 무효
      replaceChildren(statusCell, statusBadge(it));
      updateReviewCount();
    });
    tdName.appendChild(nameInput);
    tr.appendChild(tdName);

    var tdAmount = el("td");
    var originText = it.user_added ? "(직접 입력)" : (it.amount_raw == null ? "미기재" : it.amount_raw + (it.amount_unit_hint && !/[%％]|ppm|mg|g\//i.test(it.amount_raw) ? " (열 제목 단위: " + it.amount_unit_hint + ")" : ""));
    tdAmount.appendChild(el("p", "regulatory-review-origin", "원문: " + originText));
    var amountInput = el("input", "form-control form-control-sm"); amountInput.type = "text"; amountInput.value = it.amount;
    amountInput.placeholder = it.amount_raw == null ? "미기재 (비워 두면 미기재)" : "원문 유지"; amountInput.setAttribute("aria-label", "함량 수정");
    amountInput.addEventListener("input", function () { it.amount = amountInput.value; if (!it.user_added && amountInput.value.trim() !== (it.amount_raw || "")) it.edited = true; else it.edited = (it.name.trim() !== it.name_raw); replaceChildren(statusCell, statusBadge(it)); });
    tdAmount.appendChild(amountInput);
    tr.appendChild(tdAmount);

    // 원문 위치(it.location)·문서 비고(it.role_raw)는 화면 열에서 제외. 데이터는 유지되어 상세 Modal 의 '원문 위치'에 표시된다.

    var statusCell = el("td");
    statusCell.appendChild(statusBadge(it));
    if (it.review_reasons.length) statusCell.appendChild(el("p", "regulatory-review-reason", it.review_reasons.join(" ")));
    tr.appendChild(statusCell);

    var tdMatch = el("td", "regulatory-match");
    it._matchCell = tdMatch;
    renderMatchCell(it);
    tr.appendChild(tdMatch);

    var tdAct = el("td", "regulatory-col-action");
    var del = el("button", "btn btn-secondary btn-sm", "삭제"); del.type = "button"; del.setAttribute("aria-label", "행 삭제");
    del.addEventListener("click", function () {
      fileState.items = fileState.items.filter(function (x) { return x !== it; });
      if (tr.parentNode) tr.parentNode.removeChild(tr);
      updateReviewCount();               // 삭제 행은 조회 대상·결과 표에서 제외
    });
    tdAct.appendChild(del);
    tr.appendChild(tdAct);
    return tr;
  }

  function updateReviewCount() {
    var total = fileState.items.length;
    var included = fileState.items.filter(function (x) { return x.include; }).length;
    var review = fileState.items.filter(function (x) { return x.needs_review && !x.edited; }).length;
    setText($("regulatory-review-count"), total + "행 · 조회 포함 " + included + " · 확인 필요 " + review);
    // 서버가 '성분 표 없음'을 돌려준 경우에만 Empty State. 행을 직접 추가하면 숨기고, 모두 지우면 다시 보인다
    show($("regulatory-file-empty"), fileState.emptyResult && total === 0);
    updateLookupSummary();
  }

  /* ---------------- 성분 확인 (식약처 DB 후보 검색) · 행별 선택 ----------------
     직접 검색과 같은 /api/regulatory/search 를 쓴다 (K뷰티 API 호출 없음). 행 상태는 세 가지를 따로 보관한다:
       name_raw  추출 원문 (덮어쓰지 않음) · name  사용자가 고친 검색어 · selected  사용자가 고른 후보 { candidate, method, from }
     it.match = 마지막 후보 검색 결과: recommended | choose | not_found | error | research(수집본이 바뀐 key → 다시 검색)
     추천은 선택이 아니다 — '추천 후보 선택'(행) 또는 '추천 N건 선택 완료'를 누르기 전에는 조회 대상이 아니다.
     후보 key·내부 id·해시는 화면에 표시하지 않는다 (select option 의 값은 목록 순번) */
  var NAME_MATCH_FIELDS = { INGR_KOR_NAME: true, INGR_STD_NAME: true, INGR_ENG_NAME: true };
  var MATCH_PROGRESS_DEFAULT = "조회 포함 행의 성분명으로 성분정보·규제정보 후보를 찾아요. 자동으로 선택하지 않아요 — 행마다 후보를 고르거나 추천을 확인해 주세요.";
  function includedRows() { return fileState.items.filter(function (x) { return x.include && x.name.trim(); }); }
  function selectedRows() { return includedRows().filter(function (x) { return !!x.selected; }); }
  function recommendedRows() { return includedRows().filter(function (x) { return !x.selected && x.match && x.match.status === "recommended"; }); }
  function rowAlive(x) { return fileState.items.indexOf(x) >= 0; }

  /* 추천 기준: 제한 전 exact_total 이 정확히 1 이고, 그 후보가 한글명·표준명·영문명에서 정확 일치했을 때만.
     이명·고시원료명·CAS 만 일치했거나, 정확 일치가 여러 개(Water: 정제수·탄산수 / 같은 이름이 양쪽 DB)면 추천하지 않는다 */
  function recommendedCandidate(body) {
    if (!body || body.exact_total !== 1) return null;
    var ex = (body.candidates || []).filter(function (c) { return c.match === "exact"; });
    if (ex.length !== 1) return null;
    var byName = (ex[0].matched || []).some(function (m) { return m.level === "exact" && NAME_MATCH_FIELDS[m.field]; });
    return byName ? ex[0] : null;
  }

  function matchFromBody(body, q) {
    var cands = body.candidates || [];
    var m = { query: q, candidates: cands, total: body.total || 0, returned: body.returned != null ? body.returned : cands.length,
              truncated: !!body.truncated, exact_total: body.exact_total || 0, counts: body.counts || {}, recommended: null };
    if (!cands.length) { m.status = "not_found"; return m; }
    m.recommended = recommendedCandidate(body);
    m.status = m.recommended ? "recommended" : "choose";
    return m;
  }

  /* 성분명 수정 → 그 행의 후보·선택·결과를 모두 무효화 (다른 행은 그대로) */
  function invalidateRow(it) {
    it.match = null;
    it.selected = null;
    it.result = null;
    renderMatchCell(it);
    refreshBatchStale();
  }

  function selectRowCandidate(it, c, method, from) {
    it.selected = { candidate: c, method: method, from: from || null };
    it.result = null;                                    // 후보가 바뀌면 이전 결과는 이 행에 남기지 않는다
    renderMatchCell(it);
    updateLookupSummary();
  }

  function candidateOptionText(c) {
    var eng = (c.eng_name || "").trim();
    return candidateName(c) + ((c.kr_name || "").trim() && eng ? " (" + eng + ")" : "") + " · " + candidateSourceLabel(c) + (matchBasisText(c) ? " · " + matchBasisText(c) : "");
  }

  function candidateLine(c) {
    var p = el("p", "regulatory-match__name");
    p.appendChild(el("strong", null, candidateName(c)));
    var eng = (c.eng_name || "").trim();
    if ((c.kr_name || "").trim() && eng) p.appendChild(document.createTextNode(" (" + eng + ")"));
    p.appendChild(document.createTextNode(" "));
    p.appendChild(badge(candidateSourceLabel(c), c.source === "mfds_restriction" ? "warning" : "primary"));
    var basis = matchBasisText(c);
    if (basis) p.appendChild(el("span", "regulatory-match__basis", basis));
    return p;
  }

  function searchSummaryText(m) {
    var ex = [];
    Object.keys(CANDIDATE_SOURCE_LABEL).forEach(function (s) { if (m.counts[s] && m.counts[s].exact) ex.push(CANDIDATE_SOURCE_LABEL[s] + " " + m.counts[s].exact + "건"); });
    return (m.truncated ? "후보 " + m.total + "건 중 " + m.returned + "건만 표시 — 성분명을 더 구체적으로 수정해 주세요" : "후보 " + m.total + "건") +
      " · 정확 일치 " + (ex.length ? ex.join(" · ") : "없음");
  }

  function renderMatchCell(it) {
    var td = it._matchCell;
    if (!td) return;
    td.innerHTML = "";
    var m = it.match, s = it.selected;
    if (s) {
      td.appendChild(badge("선택 완료", ""));
      if (s.from) td.appendChild(el("p", "text-caption text-secondary", "처음 고른 원료: " + candidateName(s.from) + " · " + candidateSourceLabel(s.from)));
      td.appendChild(candidateLine(s.candidate));
      td.appendChild(el("p", "text-caption text-secondary", "선택 방식: " + s.method));
      var change = el("button", "btn btn-ghost btn-sm", "선택 변경"); change.type = "button";
      change.addEventListener("click", function () {
        if (fileState.looking) return;
        it.selected = null; it.result = null;          // 후보 목록(it.match)은 남겨 두고 다시 고르게 한다
        renderMatchCell(it); updateLookupSummary();
      });
      td.appendChild(change);
      return;
    }
    if (!m) { td.appendChild(el("span", "text-caption text-secondary", "성분 확인 전")); return; }
    if (m.status === "not_found") {
      td.appendChild(badge("검색 결과 없음", "warning"));
      td.appendChild(el("p", "regulatory-match__name", "성분정보·규제정보에서 ‘" + m.query + "’ 후보를 찾지 못했어요. 성분명을 수정한 뒤 다시 확인해 주세요. (규제 없음을 뜻하지 않아요)"));
      return;
    }
    if (m.status === "error") {
      td.appendChild(badge("검색 오류", "danger"));
      td.appendChild(el("p", "regulatory-match__name", ((m.err && m.err.message) || "후보를 불러오지 못했어요.") + (m.err && m.err.kind ? " (오류 종류: " + m.err.kind + ")" : "")));
      return;
    }
    if (m.status === "research") {
      td.appendChild(badge("후보 다시 검색 필요", "warning"));
      td.appendChild(el("p", "regulatory-match__name", m.message || "‘성분 확인’으로 다시 검색해 후보를 선택해 주세요."));
      return;
    }
    // recommended | choose — 사용자가 고르기 전에는 선택 상태가 아니다
    if (m.status === "recommended") {
      td.appendChild(badge("추천 · 선택 전", "warning"));
      td.appendChild(candidateLine(m.recommended));
      var ok = el("button", "btn btn-soft btn-sm", "추천 후보 선택"); ok.type = "button";
      ok.addEventListener("click", function () { if (fileState.looking || fileState.matching) return; selectRowCandidate(it, m.recommended, "추천 후보 확인 (행)"); });
      td.appendChild(ok);
    } else {
      td.appendChild(badge("후보 선택 필요", "warning"));
    }
    var sel = el("select", "form-control form-control-sm mt-2"); sel.setAttribute("aria-label", "후보 선택");
    var o0 = el("option", null, "후보 " + m.candidates.length + "개 중 선택하세요"); o0.value = ""; sel.appendChild(o0);
    m.candidates.forEach(function (c, i) { var o = el("option", null, candidateOptionText(c)); o.value = String(i); sel.appendChild(o); });
    sel.addEventListener("change", function () {
      var i = parseInt(sel.value, 10);
      if (fileState.looking || fileState.matching || isNaN(i) || !m.candidates[i]) return;
      selectRowCandidate(it, m.candidates[i], "후보 선택 (목록)");
    });
    td.appendChild(sel);
    td.appendChild(el("p", "text-caption text-secondary", searchSummaryText(m) + (m.status === "recommended" ? " · 추천은 선택 완료가 아니에요." : " · 임의로 고르지 않았어요.")));
  }

  function setMatchBusy(on, label) {
    fileState.matching = on;
    var btn = $("regulatory-review-match");
    if (btn) { btn.disabled = on; btn.textContent = on ? (label || "확인 중") : "성분 확인 (식약처 DB 후보 검색)"; }
    updateLookupSummary();
  }

  /* 조회 포함·미선택 행을 순서대로 검색. 같은 검색어(공백·대소문자 무시)는 이번 작업 안에서 한 번만 요청하고, 결과는 공유해도 선택은 행마다 따로 */
  function runMatching() {
    if (fileState.matching || fileState.looking) return;
    var rows = includedRows().filter(function (x) { return !x.selected; });
    var progress = $("regulatory-match-progress");
    if (!rows.length) { setText(progress, "검색할 행이 없어요. 조회 포함 행의 성분명을 입력했는지, 이미 모두 선택했는지 확인해 주세요."); return; }
    var seq = ++fileState.matchSeq;
    var cache = {};
    var done = 0, requests = 0;
    var stop = null;                                         // 검색 DB 이용 불가 → 남은 행은 같은 이유로 검색하지 않음
    setMatchBusy(true, "확인 중 0/" + rows.length);
    function writeMatch(it, q, m) {
      if (!rowAlive(it) || !it.include || it.selected || it.name.trim() !== q) return;   // 진행 중에 수정·삭제·제외·선택된 행은 덮어쓰지 않는다
      it.match = m;
      it.result = null;
      renderMatchCell(it);
    }
    function next(i) {
      if (seq !== fileState.matchSeq) return;               // 새 파일·시트·다시 업로드로 무효화
      if (i >= rows.length) {
        setMatchBusy(false);
        var inc = includedRows();
        var cnt = function (st) { return inc.filter(function (x) { return !x.selected && x.match && x.match.status === st; }).length; };
        setText(progress, "확인 완료 (검색 요청 " + requests + "회) — 추천 " + cnt("recommended") + " · 후보 선택 필요 " + cnt("choose") + " · 검색 결과 없음 " + cnt("not_found") +
          " · 검색 오류 " + cnt("error") + ". 추천도 직접 확인해야 조회 대상이 돼요.");
        return;
      }
      var it = rows[i];
      var q = it.name.trim();
      if (!rowAlive(it) || !it.include || !q || it.selected) { next(i + 1); return; }
      var finishRow = function () {
        done++;
        setMatchBusy(true, "확인 중 " + done + "/" + rows.length);
        setText(progress, "성분 확인 중 " + done + "/" + rows.length + " — " + q);
        next(i + 1);
      };
      if (stop) { writeMatch(it, q, { status: "error", query: q, err: { kind: stop.kind, source: stop.source, message: "검색 DB 를 쓸 수 없어(" + (DB_KINDS[stop.kind] || stop.kind) + ") 이 행은 검색하지 않았어요." } }); finishRow(); return; }
      if (q.length < AC_MIN_LENGTH) { writeMatch(it, q, { status: "error", query: q, err: { kind: "validation", message: "성분명을 " + AC_MIN_LENGTH + "글자 이상으로 수정해 주세요." } }); finishRow(); return; }
      var k = normalize(q);
      if (!cache[k]) {
        requests++;
        cache[k] = apiGet(searchUrl(q)).then(function (b) { return { body: b }; }, function (err) { return { error: err || { kind: "unknown", message: "후보 검색 실패" } }; });
      }
      cache[k].then(function (r) {
        if (seq !== fileState.matchSeq) return;
        if (r.error && DB_KINDS[r.error.kind]) stop = r.error;
        writeMatch(it, q, r.error ? { status: "error", query: q, err: r.error } : matchFromBody(r.body, q));
        finishRow();
      });
    }
    next(0);
  }

  var matchBtn = $("regulatory-review-match");
  if (matchBtn) matchBtn.addEventListener("click", runMatching);

  /* '추천 N건 선택 완료' — 지금 추천 조건을 충족하는 행만. 누르기 전에는 어떤 행도 선택하지 않는다 (모호·오류·결과 없음 행 제외) */
  var acceptBtn = $("regulatory-review-accept");
  if (acceptBtn) {
    acceptBtn.addEventListener("click", function () {
      if (fileState.looking || fileState.matching) return;
      var rows = recommendedRows();
      rows.forEach(function (x) { x.selected = { candidate: x.match.recommended, method: "추천 후보 확인 (일괄 버튼)", from: null }; x.result = null; renderMatchCell(x); });
      setText($("regulatory-match-progress"), "추천 " + rows.length + "건을 선택 완료했어요. 후보 선택이 필요한 행은 행마다 직접 골라 주세요.");
      updateLookupSummary();
    });
  }

  function updateLookupSummary() {
    var inc = includedRows();
    var sel = inc.filter(function (x) { return !!x.selected; }).length;
    var cnt = function (st) { return inc.filter(function (x) { return !x.selected && x.match && x.match.status === st; }).length; };
    var rec = cnt("recommended"), before = inc.filter(function (x) { return !x.selected && !x.match; }).length;
    var busy = fileState.looking || fileState.matching;
    var btn = $("regulatory-review-submit");
    if (btn) btn.disabled = busy || sel === 0;
    if (acceptBtn) { acceptBtn.disabled = busy || rec === 0; acceptBtn.textContent = "추천 " + rec + "건 선택 완료"; }
    var marketSel = $("regulatory-file-market");
    setText($("regulatory-lookup-summary"), "선택 완료 " + sel + " · 추천(선택 전) " + rec + " · 후보 선택 필요 " + cnt("choose") + " · 검색 결과 없음 " + cnt("not_found") +
      " · 검색 오류 " + cnt("error") + (cnt("research") ? " · 다시 검색 필요 " + cnt("research") : "") + (before ? " · 확인 전 " + before : "") + " — 조회 대상 " + sel +
      (sel ? (marketSel && marketSel.value ? " · 선택 시장: " + fileMarketLabel() : " · 국가/시장을 선택해 주세요.") : " (선택한 행만 조회해요)"));
    refreshBatchStale();
  }

  function fileMarketLabel() {
    var sel = $("regulatory-file-market");
    if (!sel) return "";
    for (var i = 0; i < sel.options.length; i++) if (sel.options[i].value === sel.value) return sel.options[i].text;
    return sel.value;
  }

  /* ---------------- 규제 일괄 조회 (/api/regulatory/lookup, key + 국가만) ---------------- */
  /* 조건 키: 시장 + 조회 포함 행마다 (행 id · 검색어 · 선택 key). 하나라도 바뀌면 '이전 조건의 결과' */
  function batchKey() {
    var market = $("regulatory-file-market") ? $("regulatory-file-market").value : "";
    return market + "|" + includedRows().map(function (x) { return x.id + ":" + normalize(x.name) + ":" + (x.selected ? x.selected.candidate.key : ""); }).join(",");
  }

  function refreshBatchStale() {
    var notice = $("regulatory-batch-stale");
    if (!notice) return;
    if (fileState.batchResultKey == null || fileState.looking) { show(notice, false); return; }
    show(notice, batchKey() !== fileState.batchResultKey);
  }

  var fileMarketSel = $("regulatory-file-market");
  if (fileMarketSel) fileMarketSel.addEventListener("change", function () { fileMarketSel.classList.remove("is-error"); show($("regulatory-file-market-error"), false); updateLookupSummary(); });

  /* 결과를 쓸 수 있는 행: 아직 표에 있고, 조회 포함이며, 같은 key 를 선택하고 있는 행만 (수정·삭제·제외·후보 변경된 행은 덮어쓰지 않음) */
  function rowAcceptsResult(x, key) { return rowAlive(x) && x.include && x.selected && x.selected.candidate.key === key; }

  function runBatchLookup(opts) {
    opts = opts || {};
    if (fileState.looking || fileState.matching) return;
    var marketSel = $("regulatory-file-market");
    var market = marketSel ? marketSel.value : "";
    if (!market) { if (marketSel) marketSel.classList.add("is-error"); show($("regulatory-file-market-error"), true); return; }
    var rows = opts.rows || selectedRows();
    // 재시도: 현재 조건(같은 시장·같은 key)이 유지되는 일시 오류 행만. 오래된 key(다시 선택 필요)는 선택이 해제돼 여기에 들어오지 않는다
    if (opts.retryOnly) rows = selectedRows().filter(function (x) { return x.result && x.result.retryable && x.result.market === market && x.result.key === x.selected.candidate.key; });
    rows = rows.filter(function (x) { return x.selected; });
    if (!rows.length) return;
    // 같은 (후보 key, 시장)은 한 번만 요청해 공유. 이름이 같아도 key 가 다르면 다른 성분으로 따로 조회
    var groups = {}, order = [];
    rows.forEach(function (x) {
      var key = x.selected.candidate.key;
      if (!groups[key]) { groups[key] = { key: key, rows: [] }; order.push(key); }
      groups[key].rows.push(x);
    });
    var seq = ++fileState.batchSeq;
    fileState.looking = true;
    fileState.batchMarket = market;
    if (!opts.rows || opts.retryOnly) fileState.batchStaleSeen = false;
    updateLookupSummary();
    setText($("regulatory-result-loading-label"), "규제 정보를 조회하는 중이에요 (0/" + order.length + ")");
    setResult("loading");
    setFileStep("lookup");
    var stop = null;                                         // DB 이용 불가 → 남은 행은 같은 이유로 조회하지 않음 (호출 한도 초과로 표시하지 않는다)
    function finish() {
      if (seq !== fileState.batchSeq) return;
      fileState.looking = false;
      fileState.batchResultKey = batchKey();
      renderBatch(market);
      updateLookupSummary();
      setFileStep("result");
    }
    function next(i) {
      if (seq !== fileState.batchSeq) return;               // 새 파일·시트·다시 업로드로 무효화 → 늦은 응답 무시
      if (i >= order.length) { finish(); return; }
      var g = groups[order[i]];
      if (stop) {
        g.rows.forEach(function (x) {
          if (rowAcceptsResult(x, g.key)) x.result = { status: "not_run", market: market, key: g.key, res: null, retryable: true,
            err: { kind: stop.kind, source: stop.source, message: "규제 DB 를 쓸 수 없어(" + (DB_KINDS[stop.kind] || stop.kind) + ") 이 행은 조회하지 않았어요. DB 를 복구한 뒤 ‘실패 항목 재시도’를 눌러 주세요." } };
        });
        next(i + 1); return;
      }
      apiGet(lookupUrl({ key: g.key }, market)).then(function (res) {
        if (seq !== fileState.batchSeq) return;
        g.rows.forEach(function (x) { if (rowAcceptsResult(x, g.key)) x.result = { status: res.lookup_status, market: market, key: g.key, res: res, err: null, retryable: false }; });
        setText($("regulatory-result-loading-label"), "규제 정보를 조회하는 중이에요 (" + (i + 1) + "/" + order.length + ")");
        next(i + 1);
      }).catch(function (err) {
        if (seq !== fileState.batchSeq) return;
        err = err || { kind: "unknown", message: "조회 실패" };
        g.rows.forEach(function (x) {
          if (!rowAcceptsResult(x, g.key)) return;
          if (RESELECT_KINDS[err.kind]) {
            // 수집본이 바뀐 key: 이 행의 선택과 이전 후보 목록을 버리고 다시 검색·선택하게 한다 (재시도 대상 아님)
            x.selected = null;
            x.match = { status: "research", query: x.name.trim(), message: "선택한 후보의 수집본이 바뀌었어요 (" + err.kind + "). ‘성분 확인’으로 다시 검색해 후보를 선택해 주세요." };
            x.result = { status: "reselect", market: market, key: g.key, res: null, err: err, retryable: false };
            renderMatchCell(x);
          } else {
            x.result = { status: "lookup_error", market: market, key: g.key, res: null, err: err, retryable: err.kind !== "validation" };
          }
        });
        if (RESELECT_KINDS[err.kind]) fileState.batchStaleSeen = true;
        if (DB_KINDS[err.kind]) stop = err;
        next(i + 1);
      });
    }
    next(0);
  }

  var lookupBtn = $("regulatory-review-submit");
  if (lookupBtn) lookupBtn.addEventListener("click", function () { runBatchLookup({}); });
  var retryFailedBtn = $("regulatory-retry-failed");
  if (retryFailedBtn) retryFailedBtn.addEventListener("click", function () { runBatchLookup({ retryOnly: true }); });

  /* 파일 행 상태 — 규제 결과 4종(found·no_market_record·link_required·not_linked)은 직접 검색과 같은 LOOKUP_LABEL 문구를 쓴다 */
  var FILE_ROW_LABEL = {
    unchecked: { text: "성분 확인 전 (미조회)", variant: "" },
    recommended: { text: "추천 · 선택 전 (미조회)", variant: "warning" },
    unselected: { text: "후보 선택 필요 (미조회)", variant: "warning" },
    search_empty: { text: "검색 결과 없음 (미조회)", variant: "warning" },
    search_error: { text: "검색 오류 (미조회)", variant: "danger" },
    research: { text: "후보 다시 검색 필요 (미조회)", variant: "warning" },
    reselect: { text: "후보 다시 선택 필요", variant: "warning" },
    pending: { text: "미조회", variant: "" },
    lookup_error: { text: "조회 오류", variant: "danger" },
  };
  var LOOKUP_RESULT_STATES = { found: true, no_market_record: true, link_required: true, not_linked: true };

  function rowStatus(x, market) {
    if (x.result && x.result.status === "reselect" && x.result.market === market && x.match && x.match.status === "research") return "reselect";
    if (!x.selected) {
      if (!x.match) return "unchecked";
      return { recommended: "recommended", choose: "unselected", not_found: "search_empty", error: "search_error", research: "research" }[x.match.status] || "unchecked";
    }
    if (!x.result || x.result.market !== market || x.result.key !== x.selected.candidate.key) return "pending";
    if (x.result.status === "lookup_error" || x.result.status === "not_run") return "lookup_error";
    return LOOKUP_RESULT_STATES[x.result.status] ? x.result.status : "lookup_error";
  }

  function rowLabel(st) { return LOOKUP_RESULT_STATES[st] ? LOOKUP_LABEL[st] : (FILE_ROW_LABEL[st] || FILE_ROW_LABEL.pending); }

  function batchContext(x, market) {
    return {
      inputRaw: x.name.trim() + (x.name.trim() !== x.name_raw && x.name_raw ? " (원문: " + x.name_raw + ")" : ""),
      marketCode: market,
      marketLabel: fileMarketLabel(),
      selected: x.selected ? x.selected.candidate : null,
      matchMethod: x.selected ? x.selected.method + (x.selected.from ? " · 처음 고른 원료: " + candidateName(x.selected.from) + " (" + candidateSourceLabel(x.selected.from) + ")" : "") : rowLabel(rowStatus(x, market)).text,
      amountRef: (x.amount || "").trim() || (x.amount_raw ? x.amount_raw : "") || "미기재",
      location: x.location,
      source: "mfds",
    };
  }

  function uniqueTimes(list) { var out = []; list.forEach(function (t) { if (t && out.indexOf(t) < 0) out.push(t); }); return out.sort(); }

  function renderBatch(market) {
    var rows = includedRows();
    var counts = { total: 0, found: 0, nomarket: 0, link: 0, error: 0, pending: 0 };
    var pendingBy = {};
    var body = $("regulatory-result-body");
    if (body) body.innerHTML = "";
    var reviewNames = [];
    var retryable = 0;
    rows.forEach(function (x) {
      var st = rowStatus(x, market);
      var res = x.result && x.result.res && rowAcceptsResult(x, x.result.key) && x.result.market === market ? x.result.res : null;
      counts.total++;
      if (st === "found") counts.found++;
      else if (st === "no_market_record") counts.nomarket++;
      else if (st === "link_required" || st === "not_linked") counts.link++;
      else if (st === "lookup_error") { counts.error++; if (x.result.retryable) retryable++; }
      else { counts.pending++; pendingBy[st] = (pendingBy[st] || 0) + 1; }
      if (st !== "found") reviewNames.push(x.name.trim());
      if (!body) return;
      var tr = el("tr");
      var tdName = el("td");
      tdName.appendChild(el("span", null, x.name.trim() || "(이름 없음)"));
      if (x.name_raw && x.name.trim() !== x.name_raw) tdName.appendChild(el("p", "regulatory-result__sub", "추출 원문: " + x.name_raw));
      if (x.selected) {
        var c = x.selected.candidate;
        tdName.appendChild(el("p", "regulatory-result__sub", "선택: " + candidateName(c) + ((c.kr_name || "").trim() && (c.eng_name || "").trim() ? " (" + c.eng_name.trim() + ")" : "") + " · " + candidateSourceLabel(c) +
          (x.selected.from ? " (처음 고른 원료: " + candidateName(x.selected.from) + " · " + candidateSourceLabel(x.selected.from) + ")" : "")));
      }
      if (res && res.matched_identity && res.matched_identity.std_name) tdName.appendChild(el("p", "regulatory-result__sub", "조회한 규제 성분: " + res.matched_identity.std_name + (res.matched_identity.eng_name ? " (" + res.matched_identity.eng_name + ")" : "")));
      if (res && res.link) tdName.appendChild(el("p", "regulatory-result__sub", "연결 근거: " + linkBasisText(res)));
      var amt = (x.amount || "").trim() || x.amount_raw;
      tdName.appendChild(el("p", "regulatory-result__sub", "문서 함량(참고): " + (amt || "미기재")));
      tr.appendChild(tdName);
      var tdMarket = el("td", null, fileMarketLabel());
      if (res && res.regulation_source) tdMarket.appendChild(el("p", "regulatory-result__sub", "규제정보 수집 " + formatKst(res.regulation_source.collected_at)));
      tr.appendChild(tdMarket);
      var tdStatus = el("td");
      var lab = rowLabel(st);
      tdStatus.appendChild(badge(lab.text, lab.variant));
      // 조회 오류의 원인 — DB 이용 불가는 '출처 이용 불가 · 이유'로 따로 표시 (호출 한도 초과로 바꾸지 않음)
      if (st === "lookup_error" && x.result.err && errorCategory(x.result.err) === "source_unavailable") tdStatus.appendChild(errorBadge(x.result.err));
      if ((st === "lookup_error" || st === "reselect") && x.result && x.result.err) tdStatus.appendChild(el("p", "regulatory-result__sub", (x.result.err.message || "") + (x.result.err.kind ? " (오류 종류: " + x.result.err.kind + ")" : "")));
      if (st === "search_error" && x.match && x.match.err) tdStatus.appendChild(el("p", "regulatory-result__sub", "검색 오류: " + (x.match.err.message || x.match.err.kind || "")));
      if ((st === "no_market_record" || st === "not_linked" || st === "link_required") && res) tdStatus.appendChild(el("p", "regulatory-result__sub", noDataReason(res)));
      if (st === "link_required" && res) {
        // 직접 검색과 같은 연결 후보 표시 — 고르면 이 행의 선택·결과만 바뀐다 (직접 검색 탭·다른 행 영향 없음)
        var ul = el("ul", "regulatory-notes");
        candidateList(res, ul, function (lc) {
          if (fileState.looking || fileState.matching || !rowAlive(x)) return;
          var from = x.selected ? (x.selected.from || x.selected.candidate) : null;
          selectRowCandidate(x, { key: lc.key, source: lc.source, kr_name: lc.std_name, eng_name: lc.eng_name, cas: (lc.cas || []).join(", "), matched: [] }, "연결 후보 선택 (규제정보)", from);
          runBatchLookup({ rows: [x] });
        });
        tdStatus.appendChild(ul);
      }
      if (st === "unselected" || st === "recommended") tdStatus.appendChild(el("p", "regulatory-result__sub", "위 표에서 후보를 선택하면 조회할 수 있어요."));
      if (res && res.related && res.related.length) tdStatus.appendChild(el("p", "regulatory-result__sub", "관련 항목 " + res.related.length + "건은 별도 (적용 여부 확인 필요 · 상세에서)"));
      if (st !== "found") { var linkP = el("p", "regulatory-result__sub"); linkP.appendChild(mfdsTextLink()); tdStatus.appendChild(linkP); }
      tr.appendChild(tdStatus);
      var types = res && res.entries ? res.entries.map(function (e) { return e.regulate_type || "구분 미제공"; }) : [];
      tr.appendChild(el("td", null, types.length ? types.join(", ") : "—"));
      var tdAct = el("td", "regulatory-col-action");
      if (x.result && x.result.market === market && (res || x.result.err)) {
        var btn = el("button", "btn btn-soft btn-sm", "상세"); btn.type = "button"; btn.setAttribute("data-modal-open", "regulatory-detail-modal");
        btn.addEventListener("click", function () { fillModal(res, batchContext(x, market), res ? null : x.result.err); });
        tdAct.appendChild(btn);
      } else {
        tdAct.appendChild(el("span", "text-caption text-secondary", "—"));
      }
      tr.appendChild(tdAct);
      body.appendChild(tr);
    });

    // 출처·수집 시각 — 성분정보(선택 후보)와 규제정보(조회 결과)를 따로. 규제정보 수집본이 둘 이상이면 같은 기준으로 보이지 않게 안내
    var resList = rows.map(function (x) { return x.result && x.result.market === market && x.result.res && rowAcceptsResult(x, x.result.key) ? x.result.res : null; }).filter(Boolean);
    // 성분정보 수집 시각은 '성분정보' 후보를 고른 행만 (규제정보 후보의 snapshot 은 규제 DB 수집 시각이라 섞지 않는다)
    var ingTimes = uniqueTimes(rows.map(function (x) {
      var c = x.selected && x.selected.candidate;
      if (c && c.source === "mfds_ingredients" && c.snapshot) return c.snapshot.collected_at;
      var f = x.selected && x.selected.from;
      return f && f.source === "mfds_ingredients" && f.snapshot ? f.snapshot.collected_at : null;
    }));
    var regTimes = uniqueTimes(resList.map(function (r) { return r.regulation_source ? r.regulation_source.collected_at : r.acquired_at; }));
    var regRuns = uniqueTimes(resList.map(function (r) { return r.collection_run ? r.collection_run.run_id + "|" + r.collection_run.started_at + "|" + r.collection_run.finished_at : null; }));
    var fmtTimes = function (ts) { return ts.length ? ts.map(formatKst).join(" / ") : "—"; };
    setText($("regulatory-result-time"), fmtTimes(regTimes));
    setText($("regulatory-batch-freshness"), "성분정보(식약처 화장품 원료성분정보 수집 DB) 수집 완료: " + fmtTimes(ingTimes) + " · 규제정보(식약처 화장품 사용제한 원료정보 수집 DB) 수집 완료: " + fmtTimes(regTimes) +
      " · 갱신 안내: 수동 재수집 (자동 갱신 없음) · 원천 자료 갱신일: 미제공 · 법령 개정·적용일: 미제공 · 수집 시각은 법령 개정일이나 최신성 보장을 의미하지 않습니다. (KST)");
    var snapIssue = fileState.batchStaleSeen || regRuns.length > 1 || ingTimes.length > 1;
    show($("regulatory-batch-snapshot"), snapIssue);
    setText($("regulatory-batch-snapshot-body"), (fileState.batchStaleSeen ? "조회 중 일부 후보의 수집본이 현재와 달라(stale_key) 선택을 해제했어요. " : "") +
      (regRuns.length > 1 || ingTimes.length > 1 ? "표의 결과가 서로 다른 수집본(성분정보 " + ingTimes.length + "개 · 규제정보 " + regRuns.length + "개 시각) 기준이에요. " : "") +
      "같은 기준의 결과로 비교하지 말고 ‘성분 확인’부터 다시 진행한 뒤 다시 조회해 주세요.");
    setText($("regulatory-cond-market"), fileMarketLabel());
    setText($("regulatory-cond-doc-country"), fileState.doc && fileState.doc.market ? fileState.doc.market.text : "미확인");
    setText($("regulatory-cond-product"), fileState.doc && fileState.doc.use ? fileState.doc.use.text : "미입력");
    var looked = counts.found + counts.nomarket + counts.link + counts.error;
    setText($("regulatory-cond-scope"), "시장 코드 " + market + " · 식약처 수집 DB (성분정보·규제정보) · 조회 포함 " + counts.total + "행 중 " + looked + "행 조회");
    setText($("regulatory-kpi-total"), String(counts.total));
    setText($("regulatory-kpi-found"), String(counts.found));
    setText($("regulatory-kpi-nomarket"), String(counts.nomarket));
    setText($("regulatory-kpi-link"), String(counts.link));
    setText($("regulatory-kpi-error"), String(counts.error));
    setText($("regulatory-kpi-pending"), String(counts.pending));

    show($("regulatory-partial-fail-notice"), counts.error > 0);
    setText($("regulatory-partial-fail-count"), String(counts.error));
    setText($("regulatory-partial-fail-reason"), retryable ? "현재 조건이 유지되는 실패 " + retryable + "건만 ‘실패 항목 재시도’로 다시 조회할 수 있어요." : "다시 시도할 수 있는 항목이 없어요. 원인을 확인해 주세요.");
    show($("regulatory-retry-failed"), retryable > 0);

    // 일부만 조회 — 미조회 행이 있으면 전체 검토가 끝난 것처럼 보이지 않게
    var PENDING_NAME = { unchecked: "성분 확인 전", recommended: "추천 확인 전", unselected: "후보 선택 필요", search_empty: "검색 결과 없음", search_error: "검색 오류", research: "다시 검색 필요", reselect: "다시 선택 필요", pending: "미조회" };
    show($("regulatory-batch-incomplete"), counts.pending > 0);
    setText($("regulatory-batch-incomplete-body"), "조회 포함 " + counts.total + "행 중 " + looked + "행만 조회했어요. 나머지 " + counts.pending + "행(" +
      Object.keys(pendingBy).map(function (k) { return (PENDING_NAME[k] || k) + " " + pendingBy[k]; }).join(" · ") + ")은 규제를 조회하지 않았어요 — 전체 성분 검토가 끝난 것이 아니에요.");

    var allNoData = rows.length > 0 && counts.found === 0 && counts.pending === 0 && counts.error === 0 && rows.every(function (x) { var st = rowStatus(x, market); return st === "no_market_record" || st === "not_linked"; });
    show($("regulatory-result-empty"), allNoData);
    var list = $("regulatory-empty-review-list");
    if (list) { list.innerHTML = ""; if (allNoData) reviewNames.forEach(function (n) { var li = el("li", null, n); li.appendChild(mfdsTextLink()); list.appendChild(li); }); }
    show($("regulatory-result-table-wrap"), rows.length > 0 && !allNoData);
    setResult("batch");
    refreshBatchStale();
  }

  var addRowBtn = $("regulatory-review-add");
  if (addRowBtn) {
    addRowBtn.addEventListener("click", function () {
      var it = { id: "u" + (fileState.nextId++), name_raw: "", amount_raw: null, amount_unit_hint: null, role_raw: null, location: "직접 입력", source: "user",
                 needs_review: true, review_reasons: ["직접 입력한 행이에요. 성분명을 확인해 주세요."], name: "", amount: "", include: true, user_added: true, edited: false, match: null, selected: null, result: null };
      fileState.items.push(it);
      if (reviewBody) { var tr = rowElement(it); reviewBody.appendChild(tr); var inp = tr.querySelector("input[type=text]"); if (inp) inp.focus(); }
      updateReviewCount();
    });
  }

  var reupload = $("regulatory-review-reupload");
  /* 파일 결과 초기화 — '다시 업로드', 선택 해제, 다른 파일 선택이 공유한다. 파일 선택 상태(카드·input)는 건드리지 않는다 */
  function resetFileResults() {
    fileState.seq++; fileState.batchSeq++; fileState.matchSeq++;   // 진행 중 응답(추출·후보 검색·조회) 무시
    fileState.items = []; fileState.sheets = []; fileState.selectedSheet = null; fileState.lastFile = null; fileState.emptyResult = false;
    fileState.matching = false; fileState.looking = false; fileState.batchResultKey = null; fileState.batchMarket = null; fileState.doc = null; fileState.batchStaleSeen = false;
    var rb = $("regulatory-result-body"); if (rb) rb.innerHTML = "";     // 이전 일괄 결과 표 비우기
    show($("regulatory-batch-stale"), false); show($("regulatory-partial-fail-notice"), false); show($("regulatory-retry-failed"), false);
    show($("regulatory-batch-incomplete"), false); show($("regulatory-batch-snapshot"), false);
    setFileBusy(false);
    setMatchBusy(false);
    setText($("regulatory-match-progress"), MATCH_PROGRESS_DEFAULT);
    if (!$("regulatory-result-single") || $("regulatory-result-single").hidden) setResult("hidden");
    if (reviewBody) reviewBody.innerHTML = "";
    var docMarket = $("regulatory-file-doc-market"); if (docMarket) docMarket.textContent = "미확인";
  }

  if (reupload) {
    reupload.addEventListener("click", function () {
      resetFileResults();
      hideFileError();
      setFileStep("upload");
      clearFileSelection(true);
    });
  }

  // 파일 단계: upload | loading | sheet | review — 한 블록만 표시. 4·5 단계 표시는 다음 단계에서 활성화
  function setFileStep(st) {
    show($("regulatory-file-loading"), st === "loading");
    show($("regulatory-sheet-block"), st === "sheet");
    var reviewVisible = st === "review" || st === "lookup" || st === "result";   // 조회 중·결과 단계에도 확인 표는 남겨 둔다
    show($("regulatory-review-block"), reviewVisible);
    if (!reviewVisible) { show($("regulatory-review-partial"), false); show($("regulatory-file-empty"), false); }
    show($("regulatory-excluded-block"), false);        // 사용 제외 성분 목록은 다음 단계

    var stepKey = { upload: "upload", loading: "upload", sheet: "sheet", review: "review", lookup: "lookup", result: "result" }[st] || "upload";
    var order = ["upload", "sheet", "review", "lookup", "result"];
    var idx = order.indexOf(stepKey);
    document.querySelectorAll(".regulatory-steps__item").forEach(function (li) {
      var i = order.indexOf(li.getAttribute("data-step"));
      li.classList.toggle("is-active", i === idx);
      li.classList.toggle("is-done", i < idx);
    });
  }

  /* ==========================================================================
     결과 영역 상태: hidden | loading | error | single | batch — 한 블록만 표시
     일부 실패 안내·실패 항목 재시도는 파일 일괄 조회에서 실제 실패 건이 있을 때만(후속 단계) 표시합니다.
     ========================================================================== */
  function setResult(st) {
    var section = $("regulatory-results");
    show(section, st !== "hidden");
    show($("regulatory-result-loading"), st === "loading");
    show($("regulatory-result-error"), st === "error");
    show($("regulatory-result-single"), st === "single");
    show($("regulatory-result-batch"), st === "batch");
    if (st !== "batch") {
      show($("regulatory-partial-fail-notice"), false);
      show($("regulatory-retry-failed"), false);
    }
    if (st === "hidden" || st === "loading" || st === "batch") { state.resultKey = null; }   // 일괄 결과 위에 직접 검색 안내가 뜨지 않게
    refreshStale();
    if (st !== "hidden" && section) section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
})();
