/* ==========================================================================
   AI 챗봇 위젯 (담당자 F) — 우하단 플로팅 채팅. 명세: src/06_chatbot/chatbot.md 7·12장
   - 대화 기록·열림 상태는 sessionStorage 에 두어 페이지 이동 후에도 이어집니다. (탭을 닫으면 사라짐)
   - 서버 호출은 /api/chatbot/message 하나. 답변 생성·도구 호출은 서버가 처리합니다.
   - 성분 후보 선택 카드: 서버가 돌려준 choices(offer_id·후보 순번·표시 정보만, 후보 key 없음)를 답변 아래에 그립니다.
     사용자가 국가와 후보 버튼을 누를 때만 {selection: {offer_id, index, market}} 을 보내고, 서버가 이 대화의 최신 목록과 대조해 조회합니다.
     대화마다 conversation_id(임의 값)를 두고 '대화 지우기' 때 새로 만듭니다. 새 목록이 오면 이전 카드는 비활성화합니다.
   - 전역 변수를 만들지 않도록 IIFE 안에 작성합니다.
   ========================================================================== */
(function () {
  "use strict";

  var root = document.getElementById("chatbot");
  if (!root) return;

  var endpoint = root.getAttribute("data-endpoint");
  var loginUrl = root.getAttribute("data-login") || "/login";
  var launcher = document.getElementById("chatbot-launcher");
  var panel = document.getElementById("chatbot-panel");
  var closeBtn = document.getElementById("chatbot-close");
  var clearBtn = document.getElementById("chatbot-clear");
  var body = document.getElementById("chatbot-messages");
  var empty = document.getElementById("chatbot-empty");
  var form = document.getElementById("chatbot-form");
  var input = document.getElementById("chatbot-input");
  var sendBtn = document.getElementById("chatbot-send");

  var KEY_MESSAGES = "cosmoa.chatbot.messages";
  var KEY_OPEN = "cosmoa.chatbot.open";
  var KEY_CONV = "cosmoa.chatbot.conversation";
  var MAX_HISTORY = 30;
  var messages = [];
  var pending = false;
  var conversationId = null;

  function newConversationId() {
    var bytes = new Uint8Array(16), out = "";
    try { window.crypto.getRandomValues(bytes); } catch (e) { for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256); }
    for (var j = 0; j < bytes.length; j++) out += ("0" + bytes[j].toString(16)).slice(-2);
    conversationId = out;
    try { sessionStorage.setItem(KEY_CONV, out); } catch (e) { /* 저장 불가 환경 무시 */ }
  }

  /* 저장 / 복원 ---------------------------------------------------------- */
  function load() {
    try {
      var raw = sessionStorage.getItem(KEY_MESSAGES);
      var parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) messages = parsed.filter(function (m) { return m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string"; });
    } catch (e) { messages = []; }
    try { conversationId = sessionStorage.getItem(KEY_CONV); } catch (e) { conversationId = null; }
    if (!conversationId || !/^[A-Za-z0-9_-]{16,64}$/.test(conversationId)) newConversationId();
  }
  function save() {
    try { sessionStorage.setItem(KEY_MESSAGES, JSON.stringify(messages.slice(-MAX_HISTORY))); } catch (e) { /* 저장 불가 환경 무시 */ }
  }

  /* 본문 → 안전한 HTML (escape 후 **굵게**, "- " 목록, 링크만 변환) ---------- */
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function inline(s) {
    s = escapeHtml(s);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(https?:\/\/[^\s<]+[^\s<.,)\]])/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    return s;
  }
  function format(text) {
    var lines = text.split("\n"), html = "", list = [];
    function flush() {
      if (list.length) { html += "<ul>" + list.map(function (l) { return "<li>" + inline(l) + "</li>"; }).join("") + "</ul>"; list = []; }
    }
    lines.forEach(function (line) {
      var m = /^\s*[-•]\s+(.*)$/.exec(line);
      if (m) { list.push(m[1]); return; }
      flush();
      html += (html && !/<\/ul>$/.test(html) ? "\n" : "") + inline(line);
    });
    flush();
    return html;
  }

  /* 그리기 --------------------------------------------------------------- */
  function bubble(role, text, extraClass) {
    var wrap = document.createElement("div");
    wrap.className = "chatbot__msg chatbot__msg--" + role + (extraClass ? " " + extraClass : "");
    var b = document.createElement("div");
    b.className = "chatbot__bubble";
    b.innerHTML = format(text);
    wrap.appendChild(b);
    return wrap;
  }
  function render() {
    body.querySelectorAll(".chatbot__msg, .chatbot__pending, .chatbot__choice").forEach(function (n) { n.remove(); });
    empty.hidden = messages.length > 0;
    messages.forEach(function (m) {
      body.appendChild(bubble(m.role, m.content));
      if (m.role === "assistant" && Array.isArray(m.choices)) m.choices.forEach(function (c) { body.appendChild(choiceCard(c)); });
    });
    scrollBottom();
  }

  /* 성분 후보 선택 카드 — 모든 값은 textContent 로만 넣는다 ---------------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function marketLabel(c, code) {
    var m = (c.markets || []).filter(function (x) { return x.code === code; })[0];
    return m ? m.label : code;
  }
  function markChoicesStale() {
    messages.forEach(function (m) { if (Array.isArray(m.choices)) m.choices.forEach(function (c) { c.stale = true; }); });
  }
  function choiceCard(c) {
    var card = el("div", "chatbot__choice" + (c.stale ? " is-stale" : ""));
    var items = c.items || [];
    var title = c.kind === "link"
      ? "규제 성분 연결 확인 — ‘" + ((c.origin && (c.origin.kr_name || c.origin.eng_name)) || "선택한 성분") + "’과 연결할 규제 성분을 골라 주세요"
      : "‘" + (c.query || "") + "’ 후보 " + (c.returned || items.length) + "건 — 국가와 성분을 직접 골라 주세요";
    card.appendChild(el("p", "chatbot__choice-title", title));
    if (c.truncated) card.appendChild(el("p", "chatbot__choice-note", "전체 " + c.total + "건 중 " + c.returned + "건만 표시했어요. 원하는 성분이 없으면 더 구체적으로 검색해 주세요."));
    if (c.kind === "link" && c.origin && c.origin.link_conflict) card.appendChild(el("p", "chatbot__choice-note", c.origin.link_conflict));

    var hint = el("p", "chatbot__choice-hint", "국가를 먼저 선택해 주세요.");
    hint.hidden = true;
    var select = null;
    if (c.market_fixed) {
      card.appendChild(el("p", "chatbot__choice-note", "조회 국가: " + marketLabel(c, c.market)));
    } else {
      var row = el("label", "chatbot__choice-market");
      row.appendChild(el("span", null, "국가"));
      select = el("select", "form-control form-control-sm");
      select.appendChild(new Option("국가 선택", ""));
      (c.markets || []).forEach(function (m) { select.appendChild(new Option(m.label + " (" + m.code + ")", m.code)); });
      select.value = c.picked_market || c.market || "";
      select.disabled = !!c.stale;
      select.addEventListener("change", function () { c.picked_market = select.value; save(); hint.hidden = true; });
      row.appendChild(select);
      card.appendChild(row);
    }

    var list = el("ul", "chatbot__choice-list");
    items.forEach(function (it) {
      var li = el("li");
      var btn = el("button", "chatbot__choice-btn");
      btn.type = "button";
      btn.disabled = !!c.stale || pending;
      var name = el("span", "chatbot__choice-name", it.kr_name || it.eng_name || "이름 미제공");
      if (it.kr_name && it.eng_name) name.appendChild(el("span", "chatbot__choice-eng", " (" + it.eng_name + ")"));
      btn.appendChild(name);
      var meta = el("span", "chatbot__choice-meta");
      meta.appendChild(el("span", "badge " + (it.source === "규제정보" ? "badge-warning" : "badge-primary"), it.source || "출처 미상"));
      meta.appendChild(el("span", null, it.match || ""));
      btn.appendChild(meta);
      btn.addEventListener("click", function () {
        if (c.stale || pending) return;
        var market = c.market_fixed ? c.market : (select ? select.value : "");
        if (!market) { hint.hidden = false; if (select) select.focus(); return; }
        var label = (it.kr_name || it.eng_name || "선택한 성분") + (it.kr_name && it.eng_name ? " (" + it.eng_name + ")" : "");
        send("[후보 선택] " + label + " · " + (it.source || "") + " · " + marketLabel(c, market) + " 규제 조회",
             { offer_id: c.offer_id, index: it.index, market: market });
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    card.appendChild(list);
    card.appendChild(hint);
    if (c.stale) card.appendChild(el("p", "chatbot__choice-note", "이전 후보 목록이에요. 최신 목록에서 골라 주세요."));
    return card;
  }
  function scrollBottom() { body.scrollTop = body.scrollHeight; }

  function showPending() {
    var el = document.createElement("div");
    el.className = "chatbot__pending";
    el.id = "chatbot-pending";
    el.innerHTML = '<span class="spinner spinner-sm"></span> 답변을 준비하고 있어요';
    body.appendChild(el);
    scrollBottom();
  }
  function hidePending() {
    var el = document.getElementById("chatbot-pending");
    if (el) el.remove();
  }
  function showError(text) {
    body.appendChild(bubble("assistant", text, "chatbot__msg--error"));
    scrollBottom();
  }

  /* 열기 / 닫기 ---------------------------------------------------------- */
  function setOpen(open) {
    root.classList.toggle("is-open", open);
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    launcher.setAttribute("aria-label", open ? "AI 비서 닫기" : "AI 비서 열기");
    try { sessionStorage.setItem(KEY_OPEN, open ? "1" : "0"); } catch (e) { /* 무시 */ }
    if (open) { render(); setTimeout(function () { input.focus(); }, 50); }
  }

  /* 전송 ----------------------------------------------------------------- */
  function autosize() {
    input.style.height = "44px";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }
  function setPending(on) {
    pending = on;
    sendBtn.disabled = on;
    input.disabled = on;
    body.querySelectorAll(".chatbot__choice:not(.is-stale) .chatbot__choice-btn").forEach(function (b) { b.disabled = on; });
    if (on) showPending(); else hidePending();
  }

  function send(text, selection) {
    text = (text || "").trim();
    if (!text || pending) return;
    messages.push({ role: "user", content: text });
    messages = messages.slice(-MAX_HISTORY);
    save();
    render();
    input.value = "";
    autosize();
    setPending(true);

    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        messages: messages.map(function (m) { return { role: m.role, content: m.content }; }),   // 선택 카드는 보내지 않음
        conversation_id: conversationId,
        selection: selection || null,
      }),
    }).then(function (res) {
      return res.json().catch(function () { return { ok: false, error: "서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요." }; })
        .then(function (data) { return { status: res.status, data: data }; });
    }).then(function (r) {
      setPending(false);
      if (r.status === 401) {
        showError("로그인이 만료됐어요. 다시 로그인해 주세요: " + location.origin + loginUrl);
        return;
      }
      if (!r.data || !r.data.ok || typeof r.data.reply !== "string") {
        showError((r.data && r.data.error) || "답변을 받지 못했어요. 잠시 후 다시 시도해 주세요.");
        return;
      }
      var choices = Array.isArray(r.data.choices) ? r.data.choices : [];
      if (r.data.choices_reset || choices.length) markChoicesStale();      // 새 목록이 오거나 서버가 선택을 해제하면 이전 카드는 비활성
      messages.push({ role: "assistant", content: r.data.reply, choices: choices });
      messages = messages.slice(-MAX_HISTORY);
      save();
      render();
    }).catch(function () {
      setPending(false);
      showError("서버에 연결하지 못했어요. 네트워크를 확인한 뒤 다시 시도해 주세요.");
    }).then(function () { input.focus(); });
  }

  /* 이벤트 --------------------------------------------------------------- */
  launcher.addEventListener("click", function () { setOpen(panel.hidden); });
  closeBtn.addEventListener("click", function () { setOpen(false); });
  clearBtn.addEventListener("click", function () {
    if (pending) return;
    messages = [];
    newConversationId();                 // 새 대화 — 이전 대화의 후보 선택 상태와 섞이지 않게
    save();
    render();
    input.focus();
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden && !document.querySelector(".modal-backdrop.is-open")) setOpen(false);
  });

  /* 시작 ----------------------------------------------------------------- */
  load();
  var wasOpen = false;
  try { wasOpen = sessionStorage.getItem(KEY_OPEN) === "1"; } catch (e) { /* 무시 */ }
  if (wasOpen) setOpen(true);
})();
