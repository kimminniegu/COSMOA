/* chatbot.js 를 최소 DOM 대역으로 실제 실행해 후보 선택 카드 흐름을 확인한다 (test_chatbot_regulatory.WidgetDomTest 가 사용).
   브라우저 확인을 대신하지 않는다 — 렌더링·스타일은 확인하지 않고, 버튼·요청 본문·상태 전환만 본다.
   사용: node widget_dom_harness.js <chatbot.js 경로> <응답 목록 JSON>  → 관찰 결과 JSON 을 stdout 으로 */
"use strict";
const vm = require("node:vm");
const fs = require("node:fs");
const { webcrypto } = require("node:crypto");

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null; this.className = ""; this._text = "";
    this.hidden = false; this.disabled = false; this.value = ""; this.type = ""; this.id = ""; this.attrs = {}; this.listeners = {};
    this.style = {}; this.scrollTop = 0; this.scrollHeight = 0;
    const self = this;
    this.classList = {
      toggle(c, on) { const s = new Set(self.className.split(/\s+/).filter(Boolean)); (on === undefined ? !s.has(c) : on) ? s.add(c) : s.delete(c); self.className = [...s].join(" "); },
      contains(c) { return self.className.split(/\s+/).includes(c); },
    };
  }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; } }
  set textContent(t) { this._text = String(t); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set innerHTML(h) { this._text = String(h).replace(/<[^>]+>/g, ""); this.children = []; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t) { (this.listeners[t] || []).forEach((f) => f({ preventDefault() {}, key: "", shiftKey: false })); }
  click() { if (!this.disabled) this.dispatch("click"); }
  focus() {} setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  has(cls) { return this.className.split(/\s+/).includes(cls); }
  querySelectorAll(sel) {
    const simple = (el, s) => {                                       // ".a" 또는 ".a:not(.b)"
      const m = /^\.([\w-]+)(?::not\(\.([\w-]+)\))?$/.exec(s.trim());
      return !!m && el.has(m[1]) && !(m[2] && el.has(m[2]));
    };
    const out = [];
    for (const part of sel.split(",")) {
      const chain = part.trim().split(/\s+/);
      for (const el of this.all()) {
        if (!simple(el, chain[chain.length - 1])) continue;
        if (chain.length === 1) { out.push(el); continue; }
        let p = el.parent, ok = false;
        while (p) { if (simple(p, chain[0])) { ok = true; break; } p = p.parent; }
        if (ok) out.push(el);
      }
    }
    return [...new Set(out)];
  }
}

const ids = {};
for (const id of ["chatbot", "chatbot-launcher", "chatbot-panel", "chatbot-close", "chatbot-clear", "chatbot-messages", "chatbot-empty",
                  "chatbot-form", "chatbot-input", "chatbot-send"]) { ids[id] = new El("div"); ids[id].id = id; }
ids["chatbot"].attrs["data-endpoint"] = "/api/chatbot/message";
ids["chatbot-panel"].hidden = true;
const store = new Map();
const requests = [];
const queue = JSON.parse(process.argv[3]);
const sandbox = {
  console, setTimeout, Promise, JSON, Math, Array, Uint8Array, Set,
  window: { crypto: webcrypto },
  location: { origin: "http://localhost" },
  sessionStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
  document: {
    getElementById: (id) => ids[id] || null, querySelector: () => null, addEventListener() {},
    createElement: (t) => new El(t),
  },
  Option: function (text, value) { const o = new El("option"); o.textContent = text; o.value = value; return o; },
  fetch: async (url, opts) => {
    requests.push(JSON.parse(opts.body));
    const next = queue.shift();
    if (!next) throw new Error("unexpected request");
    return { status: 200, json: async () => next };
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);

const tick = () => new Promise((r) => setTimeout(r, 0));
const body = ids["chatbot-messages"];
const cards = () => body.children.filter((c) => c.has("chatbot__choice"));
const buttons = (card) => card.all().filter((e) => e.has("chatbot__choice-btn"));
const selectOf = (card) => card.all().find((e) => e.tagName === "SELECT");
const hintOf = (card) => card.all().find((e) => e.has("chatbot__choice-hint"));

(async () => {
  const obs = {};
  ids["chatbot-launcher"].click();                                    // 열기
  ids["chatbot-input"].value = "Retinol 규제 알려줘";
  ids["chatbot-form"].dispatch("submit");
  for (let i = 0; i < 5; i++) await tick();
  obs.after_search = { requests: requests.length, cards: cards().length, buttons: buttons(cards()[0]).length,
                       text: cards()[0].textContent };
  buttons(cards()[0])[0].click();                                     // 국가 없이 클릭 → 요청 없음, 안내 표시
  obs.no_market = { requests: requests.length, hint_visible: !hintOf(cards()[0]).hidden };
  const sel = selectOf(cards()[0]); sel.value = "EU"; sel.dispatch("change");
  buttons(cards()[0])[0].click();
  for (let i = 0; i < 5; i++) await tick();
  obs.selection_request = requests[1];
  obs.after_link = { cards: cards().length, stale: cards().map((c) => c.has("is-stale")),
                     old_disabled: buttons(cards()[0]).every((b) => b.disabled), new_enabled: buttons(cards()[1]).every((b) => !b.disabled),
                     link_has_select: !!selectOf(cards()[1]) };
  buttons(cards()[0])[0].click();                                     // 이전 카드 클릭 → 무시
  obs.stale_click_requests = requests.length;
  buttons(cards()[1])[1].click();
  for (let i = 0; i < 5; i++) await tick();
  obs.link_request = requests[2];
  const conv1 = requests[0].conversation_id;
  ids["chatbot-clear"].click();                                       // 대화 지우기 → 새 대화 id
  ids["chatbot-input"].value = "안녕";
  ids["chatbot-form"].dispatch("submit");
  for (let i = 0; i < 5; i++) await tick();
  obs.conv_changed = requests[3].conversation_id !== conv1 && /^[0-9a-f]{32}$/.test(requests[3].conversation_id);
  obs.cards_after_clear = cards().length;
  obs.stored_has_key = /mfds_(ingredients|restriction):/.test(JSON.stringify([...store.values()]));
  process.stdout.write(JSON.stringify(obs));
})().catch((e) => { process.stdout.write(JSON.stringify({ error: String(e && e.stack || e) })); });
