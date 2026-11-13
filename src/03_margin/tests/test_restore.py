"""마진 탭 저장본 수집·복원 테스트 — Node.js 로 margin.js 를 실제로 실행합니다 (서버·DB·브라우저 없음).

    python -m unittest discover -s src/03_margin/tests -p "test_restore.py"

- 사용자가 값을 바꾼 화면 A 에서 수집 → JSON 왕복 → 새 화면 B 에 복원 → 다시 수집한 결과가 입력·계산 결과 모두 같아야 합니다.
- 복원 규칙(margin.md 17.4)과 입력 오류 시 저장 불가, 요청서 전달 문구(17.5)를 확인합니다.
- 화면은 margin.html 의 id·초기값으로 만든 간단한 대역(fake DOM)이라 레이아웃·실제 브라우저 동작은 확인하지 않습니다.
- Node.js 가 없으면 건너뜁니다.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
MARGIN_DIR = ROOT / "src/03_margin"

SCRIPT = r"""
const vm = require("node:vm");
const fs = require("node:fs");
const assert = require("node:assert");
const dir = process.argv[1];
const source = fs.readFileSync(dir + "/margin.js", "utf8");
const html = fs.readFileSync(dir + "/margin.html", "utf8");

/* margin.html 에서 입력 요소의 id·종류·초기값과 버튼 묶음을 읽습니다. */
function parsePage() {
  const controls = {}, segs = {};
  const attr = (tag, name) => { const m = tag.match(new RegExp("\\b" + name + '="([^"]*)"')); return m ? m[1] : null; };
  for (const m of html.matchAll(/\{\{ field\('([^']+)', ('[^']*'|[-\d.]+)/g)) {
    controls["margin-" + m[1]] = { type: "number", value: m[2].replace(/'/g, "") };
  }
  for (const m of html.matchAll(/<(input|select|textarea)\b[^>]*>/g)) {
    const id = attr(m[0], "id");
    if (!id || id.includes("{{")) continue;
    controls[id] = { type: attr(m[0], "type") || m[1], value: attr(m[0], "value") || "", checked: / checked/.test(m[0]), max: attr(m[0], "max"), min: attr(m[0], "min") };
  }
  for (const m of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {   // 첫 옵션 또는 selected 옵션이 초기값
    const options = [...m[2].matchAll(/<option([^>]*)>([^<]*)/g)].map((o) => ({ value: o[2], selected: / selected/.test(o[1]) }));
    Object.assign(controls[attr(m[0], "id")], { type: "select", options: options.map((o) => o.value), value: (options.find((o) => o.selected) || options[0] || { value: "" }).value });
  }
  for (const m of html.matchAll(/id="(margin-seg-[^"]+)"[\s\S]*?<\/div>/g)) {
    segs[m[1]] = [...m[0].matchAll(/data-k="([^"]+)"/g)].map((k) => k[1]);
  }
  return { controls, segs };
}
const PAGE = parsePage();

function element(id, spec = {}) {
  const listeners = {}, classes = new Set();
  let value = spec.value == null ? "" : String(spec.value);
  let options = spec.options || [], inner = "";
  const el = {
    id, type: spec.type || "div", checked: !!spec.checked, disabled: false, hidden: false, title: "", placeholder: "",
    textContent: "", className: "", dataset: spec.dataset || {}, children: [], parentElement: null, scrollTop: 0, offsetHeight: 0,
    min: spec.min == null ? "0" : spec.min, max: spec.max == null ? "100" : spec.max,
    style: { setProperty() {}, removeProperty() {}, getPropertyValue: () => "" },
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c), toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); } },
    addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
    fire(name) { (listeners[name] || []).forEach((fn) => fn({ target: el })); },
    click() { el.fire("click"); },
    focus() {}, setAttribute() {}, appendChild() {}, remove() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 0 }),
    tabs: [], kids: [],
    querySelectorAll(sel) { return sel === ".tab" ? el.tabs : el.kids; },
    querySelector(sel) { const k = sel.match(/data-k="([^"]+)"/); return k ? el.tabs.find((t) => t.dataset.k === k[1]) : element("anon"); },
  };
  Object.defineProperty(el, "innerHTML", {
    get: () => inner,
    set(v) {
      inner = String(v);
      if (el.type === "select") {   // 브라우저처럼 옵션을 바꾸면 첫 옵션이 선택됩니다.
        options = [...inner.matchAll(/<option value="([^"]*)"/g)].map((o) => o[1]);
        value = options[0] || "";
      }
    },
  });
  Object.defineProperty(el, "value", {
    get: () => value,
    set(v) {
      value = String(v);
      if (el.type === "select" && !options.includes(value)) value = "";   // 없는 옵션은 선택되지 않습니다.
      if (el.type === "range") {   // 브라우저처럼 min·max 안으로 값을 자릅니다.
        const n = Math.min(parseFloat(el.max), Math.max(parseFloat(el.min), parseFloat(value)));
        value = String(n);
      }
    },
  });
  return el;
}

function bootPage(fetchImpl) {
  const els = {};
  const get = (id) => (els[id] = els[id] || element(id, PAGE.controls[id] || {}));
  Object.keys(PAGE.controls).forEach(get);
  Object.entries(PAGE.segs).forEach(([id, keys]) => {
    get(id).tabs = keys.map((k) => { const t = element("tab-" + k, { dataset: { k } }); return t; });
  });
  const inputIds = Object.keys(PAGE.controls);
  const isModal = (id) => id.startsWith("margin-q-");
  const asideIds = ["qty","inco","m2","m2min","raw","proc","pack","r-raw","r-proc","r-pack","m1","loss","sagup","logi","r-logi","freight","ins","cbm-ea","cbm-box","cbm-inland","cbm-lcl","cbm-preset"].map((k) => "margin-" + k);
  get("margin-inputs").kids = asideIds.map(get);
  get("margin-quote-modal").kids = inputIds.filter((id) => isModal(id) && PAGE.controls[id].type !== "select").map(get);
  const root = get("margin-app");
  root.dataset = { erpUrl: "/erp", fxUrl: "/fx", profileUrl: "/profile", pdfUrl: "/pdf" };
  const document = {
    getElementById: get, createElement: () => element("created"), activeElement: null,
    body: { appendChild() {} }, addEventListener() {},
  };
  const versions = [];
  const env = { guard: () => true, listeners: [], confirms: [], confirmAnswer: true, posts: [], failPost: false, holdPost: null, versions };
  const window = {
    addEventListener() {}, innerHeight: 900, scrollY: 0, prompt() {},
    confirm(message) { env.confirms.push(message); return env.confirmAnswer; },
    ProjectBar: { current: () => null, onChange: (fn) => env.listeners.push(fn), setGuard: (fn) => { env.guard = fn; } },
    Common: { api: async (method, url, body) => {
      if (method === "POST") {
        env.posts.push(JSON.parse(JSON.stringify(body)));
        if (env.holdPost) await env.holdPost;
        if (env.failPost) return { ok: false, status: 500, error: { message: "저장 실패" } };
        const version = { id: 100 + versions.length, version_no: versions.length + 1, payload: JSON.parse(JSON.stringify(body.payload)) };
        versions.unshift(version);
        return { ok: true, status: 201, data: { version } };
      }
      if (url.includes("?limit=1")) return { ok: true, status: 200, data: { items: versions.slice(0, 1) } };
      return { ok: true, status: 200, data: { version: versions.find((v) => url.endsWith("/" + v.id)) } };
    } },
  };
  const sandbox = {
    document, window, fetch: fetchImpl, console, Promise, Math, JSON, Date, Object, Number, String, Array, parseFloat, parseInt, isNaN,
    getComputedStyle: () => ({ position: "", top: "0", marginBottom: "0", paddingBottom: "0" }),
    setTimeout: (fn) => { fn(); return 0; }, clearTimeout() {}, setInterval: () => 0, navigator: {}, URL: {},
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  const $ = (id) => get("margin-" + id);
  return {
    $, root, env,
    select(next) {   // 공통 프로젝트 막대처럼 확인 후 알림
      if (!env.guard(next)) return false;
      env.listeners.forEach((fn) => fn(next));
      return true;
    },
    status: () => $("save-status").textContent,
    collect: () => JSON.parse(JSON.stringify(root.collectMarginPayload())),
    restore: (payload) => JSON.parse(JSON.stringify(root.restoreMarginPayload(payload))),
    type(id, v) { $(id).value = v; $(id).fire("input"); },
    check(id, on) { $(id).checked = on; $(id).fire("input"); },
    seg(id, k) { $(id).tabs.find((t) => t.dataset.k === k).click(); },
  };
}

const json = (body) => ({ ok: true, headers: { get: () => "application/json" }, json: async () => body });
const FX = { rate: 1400 };
const ERP = { raw: 1150, proc: 538, pack: 1485, rate_raw: 20, rate_proc: 10, rate_pack: 15, loss: 3, sagup: false, item_code: "EU-SER-041", item_name: "세럼 30ml", synced_at: "2026-11-09 13:10:00", product_en: "Serum 30ml",
  quote: { qty: 10000, incoterm: "FOB", m2: 20, m2min: 15, counter_pct: 5 }, logistics: { preset: "SERUM_30ML", rate_logi: 10 } };
function server(url) { return Promise.resolve(json(url.startsWith("/fx") ? FX : url.startsWith("/erp") ? ERP : {})); }
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((ok) => setImmediate(ok)); };

/* 첫 TTB 조회가 복원 뒤에 끝나는 가장 나쁜 경우로 새 화면을 띄웁니다. */
function freshPageWithSlowFx() {
  let release;
  const gate = new Promise((ok) => { release = ok; });
  const page = bootPage((url) => (url.startsWith("/fx") ? gate.then(() => json(FX)) : server(url)));
  page.releaseFx = async () => { release(); await flush(); };
  return page;
}
async function roundTrip(page) {
  const first = page.collect();
  assert.strictEqual(first.ok, true, JSON.stringify(first));
  const wire = JSON.parse(JSON.stringify(first.payload));
  const next = freshPageWithSlowFx();
  assert.deepStrictEqual(next.restore(wire), { ok: true });
  await next.releaseFx();
  const second = next.collect();
  assert.strictEqual(second.ok, true);
  assert.deepStrictEqual(second.payload, first.payload);
  return { first: first.payload, next };
}

const A = { id: 1, name: "프로젝트A", customer: { id: 7, name: "고객A" } };
const B = { id: 2, name: "프로젝트B", customer: { id: 8, name: "고객B" } };
const UNSAVED = "저장하지 않은 변경 있음";
async function linked(project = A) {
  const page = bootPage(server); await flush();
  page.select(project);
  return page;
}
async function save(page) { page.$("save").click(); await flush(); }
async function loadLatest(page) { page.$("load-latest").click(); await flush(); }

const TESTS = {
  async buttons_wait_for_project() {
    const page = bootPage(server); await flush();
    assert.strictEqual(page.$("save").disabled, true);
    assert.strictEqual(page.$("load-latest").disabled, true);
    await save(page);
    assert.strictEqual(page.env.posts.length, 0);
  },
  async auto_filled_values_are_not_changes() {
    const page = await linked();
    assert.strictEqual(page.status(), "변경 없음", "첫 TTB 자동 적용은 변경이 아닙니다");
    assert.notStrictEqual(page.$("fx").value, "1320");
  },
  async undo_returns_to_clean() {
    const page = await linked();
    const before = page.$("qty").value;
    page.type("qty", 7000);
    assert.strictEqual(page.status(), UNSAVED);
    page.type("qty", before);
    assert.strictEqual(page.status(), "변경 없음");
  },
  async first_selection_keeps_values() {
    const page = bootPage(server); await flush();
    page.type("qty", 7000);
    assert.strictEqual(page.select(A), true);
    assert.strictEqual(page.env.confirms.length, 0);
    assert.strictEqual(page.$("qty").value, "7000");
    assert.strictEqual(page.status(), UNSAVED);
  },
  async clean_change_resets_without_confirm() {
    const page = await linked();
    page.type("qty", 7000);
    await save(page);
    assert.strictEqual(page.select(B), true);
    assert.strictEqual(page.env.confirms.length, 0);
    assert.strictEqual(page.$("qty").value, "10000");
    assert.strictEqual(page.status(), "변경 없음");
    await save(page);
    assert.strictEqual(page.env.posts[1].based_on_id, null, "이전 프로젝트 저장본을 기준으로 보내면 안 됩니다");
  },
  async dirty_change_confirm_cancel_and_accept() {
    const page = await linked();
    page.type("qty", 7000);
    page.env.confirmAnswer = false;
    assert.strictEqual(page.select(B), false);
    assert.strictEqual(page.$("qty").value, "7000");
    assert.strictEqual(page.status(), UNSAVED);
    page.env.confirmAnswer = true;
    assert.strictEqual(page.select(null), true);
    assert.strictEqual(page.env.confirms.length, 2);
    assert.strictEqual(page.$("qty").value, "10000");
  },
  async reset_keeps_ttb_based_fx() {
    const page = await linked();
    const fx = page.$("fx").value;
    page.type("fx", 1500);
    page.select(B);
    assert.strictEqual(page.$("fx").value, fx);
    assert.strictEqual(page.status(), "변경 없음");
  },
  async save_sends_context_and_version_chain() {
    const page = await linked();
    page.type("qty", 7000);
    await save(page);
    const first = page.env.posts[0];
    assert.deepStrictEqual(first.payload.context, { customer_id: 7, customer_name: "고객A", project_id: 1, project_name: "프로젝트A" });
    assert.strictEqual(first.based_on_id, null);
    assert.strictEqual(page.status(), "v1 기준 · 변경 없음");
    page.type("qty", 8000);
    await save(page);
    assert.strictEqual(page.env.posts[1].based_on_id, 100);
    assert.strictEqual(page.status(), "v2 기준 · 변경 없음");
  },
  async failed_or_invalid_save_stays_unsaved() {
    const page = await linked();
    page.type("qty", 7000);
    page.env.failPost = true;
    await save(page);
    assert.strictEqual(page.status(), "저장 실패");
    page.type("qty", 7100);
    assert.strictEqual(page.status(), UNSAVED);
    page.env.failPost = false;
    page.type("qty", 0);
    await save(page);
    assert.strictEqual(page.env.posts.length, 1, "입력 오류면 요청을 보내지 않습니다");
  },
  async edit_during_save_stays_unsaved() {
    const page = await linked();
    page.type("qty", 7000);
    let release;
    page.env.holdPost = new Promise((ok) => { release = ok; });
    page.$("save").click();
    await flush();
    page.type("qty", 7500);
    release();
    await flush();
    assert.strictEqual(page.status(), UNSAVED);
  },
  async project_change_during_save_is_ignored() {
    const page = await linked();
    let release;
    page.env.holdPost = new Promise((ok) => { release = ok; });
    page.$("save").click();
    await flush();
    page.select(B);
    release();
    await flush();
    await save(page);
    assert.strictEqual(page.env.posts[1].based_on_id, null);
  },
  async load_latest_restores_and_confirms() {
    const page = await linked();
    await loadLatest(page);
    assert.strictEqual(page.status(), "아직 저장본이 없어요");
    page.type("qty", 7000);
    await save(page);
    page.type("qty", 9000);
    page.env.confirmAnswer = false;
    await loadLatest(page);
    assert.strictEqual(page.$("qty").value, "9000");
    assert.strictEqual(page.status(), UNSAVED);
    page.env.confirmAnswer = true;
    await loadLatest(page);
    assert.strictEqual(page.$("qty").value, "7000");
    assert.strictEqual(page.status(), "v1 기준 · 변경 없음");
  },
  async load_rejects_foreign_payload() {
    const page = await linked();
    page.env.versions.unshift({ id: 55, version_no: 1, payload: { inputs: { q: 1 } } });
    page.type("qty", 7000);
    await loadLatest(page);
    assert.strictEqual(page.status(), "불러올 수 없는 저장본이에요.");
    assert.strictEqual(page.$("qty").value, "7000");
  },
  async default_values() {
    const page = bootPage(server); await flush();
    const { first, next } = await roundTrip(page);
    assert.strictEqual(first.inputs.quote.base_fx, 1370);
    assert.strictEqual(next.$("fx").value, "1370");
  },
  async full_scenario() {
    const page = bootPage(server); await flush();
    page.type("qty", 7000);
    page.type("inco", "CIF");
    page.seg("seg-mmode", "markup");
    page.seg("seg-minput", "all");
    page.type("m1", 12.5);
    page.type("loss", 2);
    page.check("sagup", true);
    page.type("fx", 1402.5);
    page.type("freight", 2222);
    page.type("ins", 0.35);
    page.type("target", 2.31);
    page.type("item-floor", 4);
    ["coat", "box", "raw"].forEach((k) => page.check("ve-" + k, true));
    page.type("adj-raw", 15);
    page.seg("seg-moqmode", "block");
    page.type("moq", 6000);
    page.$("add-tier").click();
    page.type("qty-add", 33000); page.$("qty-add-btn").click();
    page.type("fx-settle-input", 1300);
    page.seg("seg-qmode", "open");
    page.seg("seg-absunit", "usd");
    page.check("abs-on", true);
    page.type("abs-c", 40); page.type("abs-l", 30);
    page.type("q-buyer-company", "Glow Beauty Inc.");
    page.type("q-contact-name", "담당자");
    page.type("q-no", "QT-OLD-07");
    page.type("q-product", "Serum");
    page.type("q-remarks", "비고");
    const { first, next } = await roundTrip(page);
    assert.strictEqual(next.$("fx").value, "1402.5", "TTB 자동 적용이 기준 환율을 덮어쓰면 안 됩니다");
    assert.strictEqual(next.$("abs-c").value, "40", "슬라이더 최대값 때문에 잘리면 안 됩니다");
    assert.strictEqual(next.$("adj-raw").value, "15");
    assert.strictEqual(next.$("q-no").value, "QT-OLD-07");
    assert.deepStrictEqual(first.inputs.reverse.adjust, { raw: 0.15 });
    assert.ok(first.inputs.tier.rows.some((row) => row.qty === 33000));
    assert.ok(!first.inputs.tier.rows.some((row) => row.qty === 7000), "임시 현재 주문 행은 저장하지 않습니다");
    assert.strictEqual(first.outputs.reverse.simulation_applied, true);
    assert.ok(first.outputs.quote.usd > 0 && first.outputs.fx_impact.settle_fx > 0 && first.outputs.tier.length > 0);
  },
  async custom_place_survives_incoterm_group_change() {
    const page = bootPage(server); await flush();
    page.type("inco", "CFR");
    page.$("q-place-sel").value = "__custom"; page.$("q-place-sel").fire("change");
    page.type("q-place", "Manila, Philippines");
    const { first, next } = await roundTrip(page);
    assert.strictEqual(first.inputs.document.named_place, "Manila, Philippines");
    assert.strictEqual(next.$("q-place").value, "Manila, Philippines");
  },
  async selected_port_survives() {
    const page = bootPage(server); await flush();
    page.type("inco", "FOB");
    page.$("q-place-sel").value = "Incheon, Korea"; page.$("q-place-sel").fire("change");
    const { next } = await roundTrip(page);
    assert.strictEqual(next.$("q-place").value, "Incheon, Korea");
  },
  async absorb_above_default_slider_max() {
    const fresh = bootPage(server); await flush();
    const defaultMax = Number(fresh.$("abs-c").max);
    const page = bootPage(server); await flush();
    page.type("m2", 40);
    page.check("abs-on", true);
    const high = Number(page.$("abs-c").max);
    assert.ok(high > defaultMax, "저장본의 최대값이 초기 화면보다 커야 순서를 검증할 수 있습니다");
    page.type("abs-c", high);
    const { next } = await roundTrip(page);
    assert.strictEqual(next.$("abs-c").value, String(high));
  },
  async logistics_auto_state() {
    const manual = bootPage(server); await flush();
    manual.type("logi", 777000);
    let result = await roundTrip(manual);
    assert.strictEqual(result.next.$("logi").value, "777000");
    assert.strictEqual(result.first.inputs.logistics.auto_logi, false);
    const auto = bootPage(server); await flush();
    auto.$("cbm-preset").value = "CREAM_50ML"; auto.$("cbm-preset").fire("input");
    auto.type("qty", 24000);
    result = await roundTrip(auto);
    assert.strictEqual(result.first.inputs.logistics.auto_logi, true);
    result.next.type("qty", 48000);
    assert.notStrictEqual(result.next.$("logi").value, String(result.first.inputs.logistics.logi_total), "복원 뒤에도 자동 반영이 이어져야 합니다");
  },
  async erp_status_restored() {
    const page = bootPage(server); await flush();
    page.$("erp-sync").click(); await flush();
    let result = await roundTrip(page);
    assert.strictEqual(result.first.inputs.cost.erp.item_code, "EU-SER-041");
    assert.ok(!("quote" in result.first.inputs.cost.erp.vals), "ERP 원본값은 비교에 필요한 값만 저장합니다");
    assert.ok(!result.next.$("erp-status").innerHTML.includes("수정됨"));
    page.type("raw", 1000);
    result = await roundTrip(page);
    assert.ok(result.next.$("erp-status").innerHTML.includes("수정됨"));
  },
  async error_state_is_not_collected() {
    const page = bootPage(server); await flush();
    page.type("qty", 0);
    const result = page.collect();
    assert.strictEqual(result.ok, false);
    assert.ok(result.error);
  },
  async requisition_handoff() {
    const page = bootPage(server); await flush();
    page.check("ve-coat", true);
    let out = page.collect().payload.outputs.requisition_ve;
    assert.deepStrictEqual([out.selected, out.change_spec_text, out.lab_request_text], [false, "", ""], "코팅 VE 는 요청서로 전달하지 않습니다");
    page.check("ve-raw", true);
    out = page.collect().payload.outputs.requisition_ve;
    assert.strictEqual(out.selected, true);
    assert.strictEqual(out.target_field, "ingredients.other_notes");
    assert.ok(!/\d/.test(out.change_spec_text + out.lab_request_text), "전달 문구에 수치가 들어가면 안 됩니다");
  },
  async invalid_payload_is_rejected_without_changes() {
    const page = bootPage(server); await flush();
    page.type("qty", 4321);
    const before = page.collect().payload;
    for (const bad of [null, {}, { inputs: { quote: {} } }]) assert.strictEqual(page.restore(bad).ok, false);
    assert.deepStrictEqual(page.collect().payload, before);
  },
  async existing_seg_click_still_works() {
    const page = bootPage(server); await flush();
    const before = page.collect().payload.outputs.quote.usd;
    page.seg("seg-mmode", "markup");
    assert.notStrictEqual(page.collect().payload.outputs.quote.usd, before);
    assert.strictEqual(page.$("seg-mmode").tabs[1].classList.contains("is-active"), true);
    assert.strictEqual(page.$("seg-mmode").tabs[0].classList.contains("is-active"), false);
  },
};

(async () => {
  const out = {};
  for (const [name, fn] of Object.entries(TESTS)) {
    try { await fn(); out[name] = "ok"; } catch (error) { out[name] = String(error && error.stack || error); }
  }
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "Node.js 필요")
class RestoreTest(unittest.TestCase):
    maxDiff = None

    def test_round_trip(self):
        done = subprocess.run(
            ["node", "-e", SCRIPT, str(MARGIN_DIR)],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        results = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertTrue(results, "실행된 테스트가 없습니다")
        for name, result in results.items():
            with self.subTest(name):
                self.assertEqual(result, "ok")


if __name__ == "__main__":
    unittest.main()
