/* 개발요청서 저장용 payload 만들기 — 저장 계약 v1 (docs/data_contract.md 4장, 서버 검증 src/05_requisition/contract.py)
   - 인쇄/PDF 는 화면 문서를 그대로 쓰고, 저장 payload 는 여기서 계약에 있는 값만 골라 새로 만듭니다.
   - 원본 파일·참고자료 본문(data_url)·원문 보존 데이터(raw_extracted_data)·화면 상태는 넣지 않습니다.
   - 고객사·프로젝트는 요청서의 **연결 프로젝트**(화면에서 지금 고른 프로젝트가 아님)의 id 로 넣습니다.
   - 브라우저에서는 window.RequisitionPayload, Node 테스트에서는 module.exports 로 씁니다. */
(function (root) {
  "use strict";
  var SCHEMA_VERSION = 1;
  var INPUT_SOURCES = ["auto", "user_edited"];

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }

  // 계약의 빈 구조(input_defaults)에 있는 키만, 화면 문서의 값으로 채웁니다. 없는 값은 빈 값.
  function pick(defaults, source) {
    var out = {};
    Object.keys(defaults).forEach(function (key) {
      var fallback = defaults[key], value = isObject(source) ? source[key] : undefined;
      out[key] = isObject(fallback) ? pick(fallback, value) : clone(value === undefined || value === null ? fallback : value);
    });
    return out;
  }

  function leafPaths(tree, prefix) {
    return Object.keys(tree).reduce(function (paths, key) {
      var path = (prefix || "") + key;
      return paths.concat(isObject(tree[key]) ? leafPaths(tree[key], path + ".") : [path]);
    }, []);
  }

  function build(doc, project, options) {
    if (!doc) return { error: "작성 중인 요청서가 없어요." };
    if (!project || !project.id || !project.customer || !project.customer.id) {
      return { error: "요청서를 프로젝트에 연결해야 저장할 수 있어요." };
    }
    var allowed = leafPaths(options.input_defaults).concat(["customer"]);
    var meta = {
      field_provenance: (doc.field_provenance || []).filter(function (item) {
        return allowed.indexOf(item.field_key) >= 0;          // 참고자료 등 입력 칸이 아닌 출처는 빼고
      }).map(function (item) {
        return {
          field_key: item.field_key,
          source_value: String(item.source_value == null ? "" : item.source_value),
          source_page: String(item.source_page == null ? "" : item.source_page),
          input_source: INPUT_SOURCES.indexOf(item.input_source) >= 0 ? item.input_source : "user_edited",
          review_status: item.review_status,
          user_value: item.user_value === undefined ? null : clone(item.user_value),
        };
      }),
      reference_files: (doc.reference_files || []).map(function (file) {   // 메타데이터만 (본문 data_url 제외)
        return { name: String(file.name || ""), size: Number(file.size) || 0, type: String(file.type || "") };
      }),
    };
    if (doc.legacy && doc.legacy.target_price_tier) meta.legacy_fields = { target_price_tier: doc.legacy.target_price_tier };
    return {
      schema_version: SCHEMA_VERSION,
      payload: {
        context: {
          customer_id: project.customer.id, customer_name: project.customer.name,
          project_id: project.id, project_name: project.name,
          creation_method: doc.creation_method, source_language: doc.source_language || "",
          target_language: doc.target_language || "ko", source_file_name: doc.source_file || "",
        },
        inputs: pick(options.input_defaults, doc),
        outputs: {},
        meta: meta,
      },
    };
  }

  var api = { build: build, schemaVersion: SCHEMA_VERSION, inputPaths: function (options) { return leafPaths(options.input_defaults); } };
  root.RequisitionPayload = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
