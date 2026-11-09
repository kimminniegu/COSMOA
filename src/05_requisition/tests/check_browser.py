"""실제 개발요청서 화면을 headless Edge(없으면 Chrome)에서 검사합니다. 업무 DB·외부 API 에 접속하지 않습니다.

    python src/05_requisition/tests/check_browser.py

화면(템플릿 본문 + JS)은 실제 파일을 쓰고, 공통 저장 API 와 프로젝트 바만 메모리 가짜로 바꿉니다.
일부 PC 에서 --dump-dom 출력이 비어 나오므로, 결과는 페이지가 이 스크립트의 로컬 서버로 직접 보냅니다.
"""
import http.server
import importlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app import app  # noqa: E402

schema = importlib.import_module("src.05_requisition.schema")
service = importlib.import_module("src.05_requisition.service")


def find_browsers():
    candidates = [Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
                  Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
                  Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"]
    return [path for path in candidates if path.exists()]


with app.test_request_context("/dev-request"):
    template = app.jinja_env.get_template("05_requisition/requisition.html")
    content = "".join(template.blocks["content"](template.new_context({
        "request_sections": schema.SECTIONS, "request_options": schema.page_options()})))
payload_js = (ROOT / "src/05_requisition/requisition_payload.js").read_text(encoding="utf-8")
main_js = (ROOT / "src/05_requisition/requisition.js").read_text(encoding="utf-8")

raw = {"is_development_request": True, "source_language": "en", "customer": "Auto customer",
       "product_name": "Auto product", "product_type": "립", "export_countries": ["미국"],
       "product_development": {"texture": "Auto texture", "viscosity": "thick cream", "viscosity_level": "very_thick"},
       "raw_extracted_data": {"commercial_data": [{"field_key": "MOQ", "source_value": "PRIVATE_SENTINEL", "source_page": "2"}]}}
raw["evidence"] = [{"field_key": key, "source_value": str(service.get_value(raw, key)), "needs_review": False}
                   for key in service.DATA_FIELDS if service.get_value(raw, key)]
fixture_document = service.normalize_result(raw, "brief.pdf", "", "auto", "ko", ["연구소", "공장"])

setup = r"""
const P = {id: 12, name: '세럼', customer: {id: 7, name: 'A사'}};
window.confirm = () => true;
window.__calls = []; window.__rows = []; window.__finals = []; window.__conflict = false;
const finalNow = () => {
  const last = __finals.at(-1);
  return last ? {final_history_id: last.id, action: last.action, version: last.action === 'set' ? {id: last.version_id} : null}
    : {final_history_id: null, action: null, version: null};
};
window.Common = {
  openModal: (id) => document.getElementById(id).classList.add('is-open'),
  closeModal: (id) => document.getElementById(id).classList.remove('is-open'),
  api: async (method, url, body) => {
    __calls.push({method, url, body});
    if (method === 'POST' && url.endsWith('/versions')) {
      const version = {id: 100 + __rows.length, project_id: 12, tab: 'requisition', version_no: __rows.length + 1, title: body.title, schema_version: 1,
        based_on_id: body.based_on_id, created_by: {id: 1, name: '나'}, created_at: new Date().toISOString(), payload: JSON.parse(JSON.stringify(body.payload))};
      __rows.push(version);
      return {ok: true, status: 201, data: {version, base: {is_stale: false}}};
    }
    if (method === 'GET' && url.includes('/versions?')) return {ok: true, status: 200, data: {
      items: __rows.slice().reverse().map((v) => ({...v, is_final: finalNow().version?.id === v.id})), next_before: null}};
    if (method === 'GET' && url.startsWith('/api/versions/')) return {ok: true, status: 200, data: {version: __rows.find((v) => v.id === Number(url.split('/').pop()))}};
    if (url.endsWith('/final') && method === 'GET') return {ok: true, status: 200, data: {final: finalNow()}};
    if (url.endsWith('/final')) {
      if (__conflict) { __conflict = false; __finals.push({id: 99, action: 'set', version_id: 100}); return {ok: false, status: 409, error: {code: 'final_conflict', message: 'x', current: finalNow()}}; }
      if (body.expected_final_history_id !== finalNow().final_history_id) throw new Error('expected_final_history_id mismatch');
      __finals.push({id: __finals.length + 1, action: body.action, version_id: body.version_id});
      return {ok: true, status: 200, data: {final: finalNow()}};
    }
    throw new Error('unexpected ' + method + ' ' + url);
  },
};
window.ProjectBar = {setGuard() {}, onChange(fn) { window.__projectChange = fn; }, current() { return null; }};
"""

checks = r"""
(async () => {
const by = (id) => document.getElementById('requisition-' + id);
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const wait = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));
const enter = (key, value) => { const el = by('input-' + key); el.value = value; el.dispatchEvent(new Event('input', {bubbles: true})); };
const submit = () => by('document').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
const pending = (key, value) => { by('input-' + key).value = value; };
const tag = (name) => { const el = document.querySelector('[data-texture-tag="' + name + '"]'); el.checked = true; el.dispatchEvent(new Event('input', {bubbles: true})); };
const fillRequired = () => { enter('request_source', '고객사 요청'); enter('sample_request_type', '신규 샘플'); enter('product_type', '립'); };
try {
  // 프로젝트 없이는 불러올 수 없음
  by('load').click();
  assert(!by('notice').hidden && by('notice').textContent.includes('프로젝트'), 'load requires a project');

  // 양식 구조
  by('manual').click();
  assert(!by('app').textContent.includes('전달 대상'), 'recipient controls removed');
  assert(!by('fields').textContent.includes('미생물') && !by('fields').textContent.includes('클레임'), 'excluded fields absent');
  assert(by('save-box').hidden, 'save box only on result');
  const tabs = by('section-tabs').querySelectorAll('[role="tab"]');
  assert(tabs.length === 5, 'five section tabs');
  assert(by('section-0').textContent.includes('요청 구분') && !by('section-0').textContent.includes('수출 금지 원료'), 'basic information');
  assert(by('section-1').textContent.includes('벤치마크 제품명') && by('section-1').textContent.includes('기타 요구사항'), 'development section');
  assert(by('section-2').textContent.includes('수출 금지 원료') && by('section-2').textContent.includes('컨셉원료 코멘트'), 'ingredient section');
  assert(by('section-3').textContent.includes('품질 확인 테스트 *'), 'quality test required');
  const band = by('input-product_development.viscosity_level');
  assert([...band.options].some((o) => o.value === 'medium' && o.textContent === '중간 – 세럼·앰플') && !band.disabled, 'viscosity band options');
  assert(document.querySelectorAll('[data-texture-tag]').length === 6, 'texture tags');

  // 탭 이동·입력 유지·필수값
  by('input-export_countries').click();
  assert(!by('country-list').hidden, 'country dropdown opens');
  enter('customer', 'Retained customer');
  pending('buyer_prohibited_ingredients', 'Pending ingredient');
  tabs[4].click();
  assert(!by('section-4').hidden && by('section-0').hidden, 'reference tab visibility');
  tabs[4].dispatchEvent(new KeyboardEvent('keydown', {key: 'Home', bubbles: true}));
  assert(!by('section-0').hidden, 'keyboard tab navigation');
  assert(by('input-customer').value === 'Retained customer', 'values retained across tabs');
  assert(by('input-buyer_prohibited_ingredients').value === 'Pending ingredient', 'pending chip retained');
  pending('buyer_prohibited_ingredients', '');
  enter('customer', '');
  tabs[4].click();
  submit();
  assert(!by('section-0').hidden && !by('notice').hidden, 'validation opens missing field tab');
  enter('customer', 'Browser customer'); enter('request_source', '고객사 요청'); enter('product_name', 'Browser product');
  enter('sample_request_type', '신규 샘플'); enter('product_type', '기타');
  submit();
  assert(!by('notice').hidden, 'custom product type required');
  enter('product_type_custom', 'Custom type');
  pending('export_countries', '미국');
  enter('product_development.viscosity_level', 'medium'); enter('product_development.viscosity', '흐르지 않는 젤');
  tag('리치함'); enter('product_development.texture', 'Texture v1');
  pending('quality.tests', '안정도 시험');
  pending('buyer_prohibited_ingredients', 'Silica');
  submit();

  // 결과·수정 취소
  assert(by('title').textContent === '개발요청서', 'result screen: ' + by('notice').textContent);
  assert(!by('fields').querySelector('input,textarea,select'), 'read only');
  ['Silica', '안정도 시험', '중간 – 세럼·앰플', '바이어 원문: 흐르지 않는 젤', '리치함'].forEach((text) => assert(by('fields').textContent.includes(text), 'result shows ' + text));
  by('secondary').click(); enter('product_development.texture', 'Cancelled'); by('secondary').click();
  assert(by('fields').textContent.includes('Texture v1'), 'edit cancellation');
  by('secondary').click(); enter('product_development.texture', 'Texture v2'); submit();
  assert(by('fields').textContent.includes('Texture v2'), 'nested edit saved');

  // PDF — 인쇄 창만 막고 실제 문서를 검사
  const append = document.body.append.bind(document.body);
  document.body.append = (el) => {
    if (el.tagName === 'IFRAME') el.srcdoc = el.srcdoc.replace('<head>', '<head><script>window.print=()=>{};<\/script>');
    append(el);
  };
  submit();
  let frame = document.querySelector('.requisition-print-frame');
  assert(frame && frame.srcdoc.includes('Texture v2'), 'PDF latest values');
  const pdf = new DOMParser().parseFromString(frame.srcdoc, 'text/html');
  ['DEVELOPMENT', '연구소', 'Browser customer', '신규 샘플', '중간 – 세럼·앰플', '흐르지 않는 젤', '저장 전'].forEach((text) => {
    assert(pdf.body.textContent.includes(text), 'PDF shows ' + text);
  });
  assert(pdf.querySelectorAll('table.requirements thead').length === 4, 'all requirement tables');
  assert(pdf.querySelector('.doc-footer').textContent.includes('COSTD'), 'company footer');
  assert(!/전달 대상|미생물|클레임/.test(frame.srcdoc), 'excluded fields absent from PDF');
  await wait(60);

  // 자동변환 — AI 추정 구간은 확인 필요, 비공개 데이터 제외
  by('new').click();
  window.fetch = async () => ({ok: true, json: async () => ({document: window.fixtureDocument})});
  const files = new DataTransfer();
  files.items.add(new File(['%PDF-1.7 fixture'], 'brief.pdf', {type: 'application/pdf'}));
  by('file').files = files.files; by('file').dispatchEvent(new Event('change', {bubbles: true}));
  await wait(40);
  assert(by('title').textContent === '개발요청서', 'upload transitions to result');
  assert(by('fields').textContent.includes('Auto texture') && by('fields').textContent.includes('매우 되직함 – 크림'), 'automatic conversion values');
  assert(by('field-product_development.viscosity').textContent.includes('확인필요'), 'AI band needs review');
  assert(!by('fields').textContent.includes('PRIVATE_SENTINEL'), 'private data excluded from result');
  submit();
  frame = document.querySelector('.requisition-print-frame');
  assert(frame.srcdoc.includes('Auto texture') && !frame.srcdoc.includes('PRIVATE_SENTINEL'), 'automatic conversion PDF');
  await wait(60);

  // 저장·최종본·불러오기
  by('new').click();
  window.__projectChange(P);
  by('manual').click();
  fillRequired(); enter('product_name', '비타민 세럼'); pending('export_countries', '미국'); pending('quality.tests', '안정도 시험');
  enter('product_development.spf', 'SPF50+');
  submit();
  assert(by('save-status').textContent === '저장 전' && by('version-title').value === '비타민 세럼', 'unsaved state');
  by('version-save').click(); await wait();
  const first = __calls.find((call) => call.method === 'POST');
  assert(first.body.based_on_id === null && first.body.payload.context.project_id === 12 && !JSON.stringify(first.body).includes('data_url'), 'first save body');
  assert(by('save-status').textContent === 'v1' && by('version-save').disabled, 'saved state');
  by('version-final').click(); await wait();
  assert(by('save-status').textContent === 'v1 ★ 최종본', 'final label');
  by('secondary').click(); enter('product_development.spf', '');
  assert(!by('carryover-wrap').hidden && by('carryover').textContent.includes('SPF'), 'carryover warning');
  submit();
  assert(by('save-status').textContent.includes('이후 수정됨') && by('version-final').disabled && !by('version-save').disabled, 'dirty state');
  by('version-title').value = '두번째'; by('version-save').click(); await wait();
  assert(__rows[1].based_on_id === 100 && by('save-status').textContent === 'v2', 'second save');
  __conflict = true; by('version-final').click(); await wait();
  assert(by('version-feedback').textContent.includes('먼저'), 'final conflict');
  by('new').click(); await wait();
  by('load').click(); await wait();
  const radios = [...document.querySelectorAll('input[name=requisition-load-version]')];
  assert(radios.length === 2 && radios.find((radio) => radio.checked).value === '100', 'final selected by default');
  by('load-confirm').click(); await wait();
  assert(by('fields').textContent.includes('SPF50+') && by('save-status').textContent.startsWith('v1 ★'), 'loaded version');
  by('secondary').click(); enter('product_name', '새 이름'); submit();
  by('version-save').click(); await wait();
  assert(__rows[2].based_on_id === 100, 'based_on loaded version');
  document.body.dataset.testResult = 'PASS';
} catch (error) { document.body.dataset.testResult = 'FAIL: ' + error.message; }
})();
"""

reporter = ("const send=window.fetch.bind(window);"          # 자동변환 검사가 window.fetch 를 가짜로 바꿔도 결과는 보낼 수 있게
            "window.addEventListener('error',e=>send('/result?r='+encodeURIComponent('JS ERROR: '+e.message)));"
            "setInterval(()=>{const r=document.body&&document.body.dataset.testResult;"
            "if(r&&!window.__sent){window.__sent=1;send('/result?r='+encodeURIComponent(r))}},50);")
fixture_json = json.dumps(fixture_document, ensure_ascii=False).replace("</", "<\\/")
page = "".join(['<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body><script>', reporter, "</script>", content,
                "<script>window.fixtureDocument=", fixture_json, ";", setup, "</script><script>", payload_js, "</script><script>",
                main_js, "</script><script>", checks, "</script></body></html>"]).encode("utf-8")
results: queue.Queue = queue.Queue()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        report = self.path.startswith("/result")
        if report:
            results.put(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["r"][0])
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if not report:
            self.wfile.write(page)


def run_in(browser, port):
    profile = Path(tempfile.mkdtemp(prefix="requisition-browser-"))
    process = subprocess.Popen([str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                "--disable-extensions", f"--user-data-dir={profile}", f"http://127.0.0.1:{port}/"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return results.get(timeout=30)
    except queue.Empty:
        return None                      # 이 브라우저가 headless 로 응답하지 않음 — 다음 브라우저로
    finally:
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


def main():
    browsers = find_browsers()
    if not browsers:
        raise SystemExit("Edge 또는 Chrome 을 찾지 못했습니다.")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for browser in browsers:
            result = run_in(browser, server.server_port)
            if result is not None:
                print(f"{browser.name}: {result}")
                raise SystemExit(0 if result == "PASS" else 1)
            print(f"{browser.name}: 응답 없음")
    finally:
        server.shutdown()
    raise SystemExit("브라우저 결과를 받지 못했습니다.")


if __name__ == "__main__":
    main()
