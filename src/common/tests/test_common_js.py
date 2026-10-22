"""공통 JS 클라이언트(Common.api) 재전송 규칙 테스트 — Node.js 로 common.js 를 실제로 실행합니다 (서버·DB 접속 없음).

    python -m unittest discover -s src/common/tests -p "test_common_js.py"

- 변경 요청은 CSRF 검증에서 거부(403 csrf_failed)됐을 때만 새 토큰으로 **한 번** 다시 보냅니다.
- 네트워크 오류·503·다른 403·409 등은 다시 보내지 않습니다 (생성·저장 요청이 두 번 처리되지 않도록).
- Node.js 가 없으면 건너뜁니다.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]

SCRIPT = r"""
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const noop = () => {};
const element = null;
const documentStub = {
  getElementById: () => element, querySelector: () => element, querySelectorAll: () => [],
  addEventListener: noop, body: { classList: { add: noop, remove: noop } },
  documentElement: { classList: { contains: () => false, toggle: noop } },
};
(async () => {
  const cases = JSON.parse(process.argv[2]);
  const out = {};
  for (const [name, spec] of Object.entries(cases)) {
    const calls = [];
    const queue = spec.responses.slice();
    const sandbox = {
      window: {}, document: documentStub, localStorage: { setItem: noop }, console,
      fetch: async (url, options) => {
        calls.push({ url, method: options.method, token: (options.headers || {})["X-CSRF-Token"] || null });
        const next = queue.shift();
        if (!next) throw new Error("unexpected extra request: " + options.method + " " + url);
        if (next === "network") throw new TypeError("Failed to fetch");
        return { ok: next.status >= 200 && next.status < 300, status: next.status, json: async () => next.body };
      },
    };
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    try {
      const result = await sandbox.window.Common.api(spec.method, spec.url, spec.body);
      out[name] = { result: { ok: result.ok, status: result.status, code: result.error && result.error.code }, calls, left: queue.length };
    } catch (error) {
      out[name] = { thrown: String(error), calls };
    }
  }
  console.log(JSON.stringify(out));
})();
"""

TOKEN = lambda t: {"status": 200, "body": {"ok": True, "csrf_token": t, "header": "X-CSRF-Token"}}   # noqa: E731
CSRF_FAILED = {"status": 403, "body": {"ok": False, "error": {"code": "csrf_failed", "message": "토큰"}}}
CREATED = {"status": 201, "body": {"ok": True, "customer": {"id": 1}}}


@unittest.skipUnless(shutil.which("node"), "Node.js 없음 — 공통 JS 테스트 생략")
class CommonApiRetryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {
            "csrf_retry_once": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                "responses": [TOKEN("t1"), CSRF_FAILED, TOKEN("t2"), CREATED]},
            "csrf_retry_only_once": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                     "responses": [TOKEN("t1"), CSRF_FAILED, TOKEN("t2"), CSRF_FAILED]},
            "network_error_not_resent": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                         "responses": [TOKEN("t1"), "network"]},
            "unavailable_503_not_resent": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                           "responses": [TOKEN("t1"), {"status": 503, "body": {"ok": False, "error": {"code": "db_unavailable", "message": "x"}}}]},
            "other_403_not_resent": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                     "responses": [TOKEN("t1"), {"status": 403, "body": {"ok": False, "error": {"code": "forbidden", "message": "x"}}}]},
            "plain_403_without_json_not_resent": {"method": "POST", "url": "/api/customers", "body": {"name": "A"},
                                                  "responses": [TOKEN("t1"), {"status": 403, "body": None}]},
            "conflict_409_not_resent": {"method": "POST", "url": "/api/projects/1/tabs/requisition/final", "body": {},
                                        "responses": [TOKEN("t1"), {"status": 409, "body": {"ok": False, "error": {"code": "final_conflict", "message": "x"}}}]},
            "get_never_resent": {"method": "GET", "url": "/api/customers",
                                 "responses": [{"status": 403, "body": {"ok": False, "error": {"code": "csrf_failed", "message": "x"}}}]},
            "get_network_error": {"method": "GET", "url": "/api/customers", "responses": ["network"]},
        }
        run = subprocess.run(["node", "-e", SCRIPT, str(ROOT / "src/common/common.js"), json.dumps(cases)],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        if run.returncode != 0:
            raise AssertionError(run.stderr)
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def posts(self, name):
        return [c for c in self.out[name]["calls"] if c["method"] == "POST"]

    def test_csrf_failure_resent_once_with_new_token(self):
        case = self.out["csrf_retry_once"]
        self.assertEqual(case["result"], {"ok": True, "status": 201, "code": None})
        self.assertEqual([c["token"] for c in self.posts("csrf_retry_once")], ["t1", "t2"])
        self.assertEqual(case["left"], 0)

    def test_csrf_failure_twice_stops(self):
        case = self.out["csrf_retry_only_once"]
        self.assertEqual(len(self.posts("csrf_retry_only_once")), 2)
        self.assertEqual((case["result"]["status"], case["result"]["code"]), (403, "csrf_failed"))

    def test_other_failures_are_not_resent(self):
        for name, status, code in (("network_error_not_resent", 0, "network_error"),
                                   ("unavailable_503_not_resent", 503, "db_unavailable"),
                                   ("other_403_not_resent", 403, "forbidden"),
                                   ("plain_403_without_json_not_resent", 403, "http_403"),
                                   ("conflict_409_not_resent", 409, "final_conflict")):
            with self.subTest(name=name):
                case = self.out[name]
                self.assertNotIn("thrown", case)
                self.assertEqual(len(self.posts(name)), 1)                 # 변경 요청은 한 번만
                self.assertEqual((case["result"]["ok"], case["result"]["status"], case["result"]["code"]), (False, status, code))
                self.assertEqual(case["left"], 0)

    def test_get_is_never_resent(self):
        for name, status in (("get_never_resent", 403), ("get_network_error", 0)):
            with self.subTest(name=name):
                self.assertEqual(len(self.out[name]["calls"]), 1)
                self.assertEqual(self.out[name]["result"]["status"], status)


if __name__ == "__main__":
    unittest.main()
