/* ==========================================================================
   공통 JavaScript (PM 관리)
   - Sidebar toggle, 공통 Modal, 공통 Tabs 등 모든 페이지가 공유하는 UI 동작만 둡니다.
   - 페이지 전용 로직은 각 담당자 폴더의 JS에 작성합니다.
   - 사용법은 docs/ui_components.md 참고 (data-* 속성 기반이라 JS 호출 없이도 동작).
   ========================================================================== */
(function () {
  "use strict";

  /* Sidebar toggle (Tablet / Mobile) -------------------------------------- */
  var sidebar = document.getElementById("app-sidebar");
  var backdrop = document.querySelector(".app-sidebar-backdrop");
  var toggle = document.querySelector("[data-sidebar-toggle]");

  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("is-open", open);
    if (backdrop) backdrop.classList.toggle("is-open", open);
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      setSidebar(!sidebar.classList.contains("is-open"));
    });
  }

  /* Sidebar 접기 / 펼치기 (Desktop) ----------------------------------------
     <html class="is-sidebar-collapsed"> 로 상태를 표현하고 localStorage("cosmoa.sidebar")에 저장합니다.
     base.html <head>의 inline script가 저장된 상태를 CSS 로드 전에 먼저 적용합니다. */
  var STORAGE_KEY = "cosmoa.sidebar";
  var root = document.documentElement;
  var collapseBtn = document.querySelector("[data-sidebar-collapse]");

  function syncCollapseButton() {
    if (!collapseBtn) return;
    var collapsed = root.classList.contains("is-sidebar-collapsed");
    collapseBtn.setAttribute("aria-expanded", String(!collapsed));
    collapseBtn.setAttribute("aria-label", collapsed ? "메뉴 펼치기" : "메뉴 접기");
    collapseBtn.title = collapsed ? "메뉴 펼치기" : "메뉴 접기";
  }

  function setCollapsed(collapsed) {
    root.classList.toggle("is-sidebar-collapsed", collapsed);
    try { localStorage.setItem(STORAGE_KEY, collapsed ? "collapsed" : "expanded"); } catch (e) { /* 저장 불가 환경 무시 */ }
    syncCollapseButton();
  }

  if (collapseBtn) {
    collapseBtn.addEventListener("click", function () {
      setCollapsed(!root.classList.contains("is-sidebar-collapsed"));
    });
    syncCollapseButton();
  }

  /* Modal ------------------------------------------------------------------
     열기 : <button data-modal-open="modal-id">
     닫기 : <button data-modal-close>  /  배경 클릭  /  ESC
     대상 : <div class="modal-backdrop" id="modal-id"> ... </div>            */
  function openModal(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.add("is-open");
    document.body.classList.add("is-modal-open");
  }

  function closeModal(el) {
    if (!el) return;
    el.classList.remove("is-open");
    if (!document.querySelector(".modal-backdrop.is-open")) {
      document.body.classList.remove("is-modal-open");
    }
  }

  /* Tabs -------------------------------------------------------------------
     <div class="tabs"><button class="tab" data-tab-target="panel-id">…</button></div>
     <div class="tab-panel" id="panel-id">…</div>                             */
  function activateTab(tab) {
    var tabs = tab.closest(".tabs");
    var target = document.getElementById(tab.getAttribute("data-tab-target"));
    if (!tabs || !target) return;
    tabs.querySelectorAll(".tab").forEach(function (t) {
      var active = t === tab;
      t.classList.toggle("is-active", active);
      t.setAttribute("aria-selected", String(active));
      var panel = document.getElementById(t.getAttribute("data-tab-target"));
      if (panel) panel.classList.toggle("is-active", active);
    });
  }

  document.addEventListener("click", function (e) {
    var opener = e.target.closest("[data-modal-open]");
    if (opener) { openModal(opener.getAttribute("data-modal-open")); return; }

    if (e.target.closest("[data-modal-close]")) { closeModal(e.target.closest(".modal-backdrop")); return; }
    if (e.target.classList.contains("modal-backdrop")) { closeModal(e.target); return; }

    if (e.target.closest("[data-sidebar-close]")) { setSidebar(false); return; }

    var tab = e.target.closest(".tab[data-tab-target]");
    if (tab && !tab.disabled) activateTab(tab);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var opened = document.querySelectorAll(".modal-backdrop.is-open");
    if (opened.length) closeModal(opened[opened.length - 1]);
    else setSidebar(false);
  });

  /* 업무 API JSON 요청 (docs/api_contract.md) ---------------------------------
     Common.api("GET", "/api/customers").then(function (r) { r.ok, r.status, r.data, r.error });
     변경 요청(POST 등)은 X-CSRF-Token 헤더를 자동으로 붙이고, 토큰이 만료돼 403 csrf_failed 면 새 토큰으로 한 번 다시 보냅니다.
     네트워크 오류도 reject 하지 않고 { ok: false, status: 0, error: { code: "network_error" } } 로 돌려줍니다. */
  var csrfToken = null;

  function fetchJson(method, url, body, headers) {
    var options = { method: method, credentials: "same-origin", headers: Object.assign({ Accept: "application/json" }, headers) };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        var error = data && data.ok === false ? (typeof data.error === "string" ? { code: "error", message: data.error } : data.error) : null;
        if (!res.ok && !error) error = { code: "http_" + res.status, message: "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요." };
        return { ok: res.ok, status: res.status, data: data, error: error };
      });
    }, function () {
      return { ok: false, status: 0, data: null, error: { code: "network_error", message: "서버에 연결하지 못했어요. 네트워크를 확인해 주세요." } };
    });
  }

  function getCsrfToken(refresh) {
    if (csrfToken && !refresh) return Promise.resolve(csrfToken);
    return fetchJson("GET", "/api/csrf-token").then(function (r) {
      csrfToken = r.ok ? r.data.csrf_token : null;
      return csrfToken;
    });
  }

  function api(method, url, body) {
    method = method.toUpperCase();
    if (method === "GET") return fetchJson(method, url);
    function send(refresh) {
      return getCsrfToken(refresh).then(function (token) {
        return fetchJson(method, url, body === undefined ? {} : body, token ? { "X-CSRF-Token": token } : {});
      });
    }
    return send(false).then(function (r) {
      return r.status === 403 && r.error && r.error.code === "csrf_failed" ? send(true) : r;
    });
  }

  /* 페이지 JS에서 사용할 수 있는 공통 API */
  window.Common = {
    openModal: openModal,
    closeModal: function (id) { closeModal(document.getElementById(id)); },
    setSidebarCollapsed: setCollapsed,
    api: api,
  };
})();
