(() => {
  "use strict";
  const $ = (id) => document.getElementById("requisition-" + id);
  const root = $("app");
  if (!root) return;
  // 선택값·빈 구조는 서버의 schema.py 와 같은 값을 받습니다 (저장 계약 v1 과 화면이 같은 구조를 쓰도록).
  const options = JSON.parse($("options").textContent);
  const types = options.product_types;
  const sections = JSON.parse($("schema").textContent);
  const definitions = sections.flatMap(([, fields]) => fields);
  const labels = Object.fromEntries(definitions.map(([key, label]) => [key, label]));
  const kinds = Object.fromEntries(definitions.map(([key, , kind]) => [key, kind]));
  labels.reference_notes = "기타사항";
  kinds.reference_notes = "textarea";
  const wideNoteFields = new Set(["company_description", "basic_notes", "ingredients.other_notes", "rnd_check_requests"]);
  const wideFields = new Set(["target_prices", "ingredients.concept", "product_development.container_reference"]);
  // 입력 칸 하나로 끝나지 않는 항목 (목록 편집·선택값+서술)
  const compositeFields = new Set(["target_prices", "ingredients.concept", "product_development.viscosity"]);
  const inputPaths = RequisitionPayload.inputPaths(options);
  const chipFields = definitions.filter(([, , kind]) => kind === "list").map(([key]) => key);
  const requiredFields = ["customer", "request_source", "product_name", "sample_request_type", "product_type", "export_countries", "quality.tests"];
  const get = (data, key) => key.split(".").reduce((value, part) => value?.[part], data);
  function set(data, key, value) {
    const parts = key.split("."), last = parts.pop();
    const parent = parts.reduce((obj, part) => (obj[part] ||= {}), data);
    parent[last] = value;
  }
  const countries = ["미국", "캐나다", "중국", "일본", "한국", "프랑스", "독일", "영국", "호주", "베트남", "태국", "인도네시아", "싱가포르", "인도", "아랍에미리트", "사우디아라비아"];
  const methods = { auto: "자동변환", auto_edited: "자동변환 후 수정", manual: "직접 작성", manual_edited: "직접 작성 후 수정" };
  let state = "upload", saved = null, draft = null, originalFile = null, controller = null;
  // project: 화면에서 선택한 프로젝트. documentProject: 지금 작성 중인 요청서가 연결된 프로젝트 (요청서를 시작할 때 정함).
  // 둘이 달라지지 않도록, 작성 중 프로젝트를 바꾸면 확인 후 요청서를 초기화합니다. (저장 연결은 3단계 다음 작업)
  let project = null, documentProject = null;
  let printFrame = null;
  let activeSection = 0;
  const sectionTitles = [...sections.map(([title]) => title), "05 참고자료"];
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const filled = (value) => Array.isArray(value) ? value.length > 0 : Boolean(String(value ?? "").trim());
  const editing = () => state === "edit" || state === "manual";
  const current = () => editing() ? draft : saved;
  const hasDocument = () => Boolean(saved || draft || originalFile) || state === "loading";
  // 빈 양식 = 저장 계약 v1 의 inputs 빈 구조 + 고객사 표시값 + 화면 정보. 문서 번호·버전은 두지 않습니다 (서버 version_no 기준).
  const blank = () => Object.assign(clone(options.input_defaults), {
    customer: documentProject ? documentProject.customer.name : "",
    creation_method: "manual", source_language: "", target_language: $("target-language").value,
    review_status: "needs_review", source_file: "", field_provenance: [], raw_extracted_data: {}, reference_files: [], legacy: {}
  });
  const amountText = (value) => Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 4 });
  const priceText = (prices) => (prices || []).map((item) => amountText(item.amount) + " " + item.currency).join(", ");
  function conceptText(items, separator = "\n") {
    return Object.entries(options.concept_kinds).map(([kind, title]) => {
      const rows = (items || []).filter((item) => item.kind === kind);
      return rows.length ? title + ": " + rows.map((item) => item.name +
        (item.must_contain === true ? " [함유 필수]" : item.must_contain === false ? " [함유 필수 아님]" : "") +
        (item.efficacy_tags.length ? " (효능: " + item.efficacy_tags.join(", ") + ")" : "")).join(", ") : "";
    }).filter(Boolean).join(separator);
  }
  function legacyNote(data) {
    const tier = data.legacy && data.legacy.target_price_tier;
    return tier ? '<p class="form-help requisition-legacy-note">원문 가격대 표기: ' + escape(options.legacy_price_tiers[tier] || tier) +
      ' — 금액으로 자동 변환하지 않았어요. 목표 가격대(금액·통화)를 직접 입력해 주세요.</p>' : "";
  }
  function notice(message = "") {
    $("notice").textContent = message;
    $("notice").hidden = !message;
  }
  function missing(data) {
    return requiredFields.filter((key) =>
      !filled(get(data, key)) || (key === "product_type" && data.product_type === "기타" && !filled(data.product_type_custom)));
  }
  function reviews(data) {
    const result = missing(data).map((key) => labels[key]);
    if (data.creation_method.startsWith("auto") && !data.target_prices.length) result.push("목표 가격대");
    (data.field_provenance || []).filter((item) => item.review_status === "needs_review").forEach((item) => {
      if (labels[item.field_key]) result.push(labels[item.field_key]);
    });
    return [...new Set(result)];
  }
  function fieldValue(data, key) {
    if (key === "product_type") {
      if (data.product_type === "기타") return data.product_type_custom || "";
      return data.product_type === "스킨케어" && data.product_type_detail ? "스킨케어 (" + data.product_type_detail + ")" : data.product_type;
    }
    if (key === "target_prices") return priceText(data.target_prices);
    if (key === "ingredients.concept") return conceptText(data.ingredients.concept);
    if (key === "product_development.viscosity") {
      return [data.product_development.viscosity_level, data.product_development.viscosity].filter(filled).join(" · ");
    }
    if (key === "buyer_prohibited_ingredients") return [...data[key], ...data.regulatory_restricted_ingredients].join(", ");
    const value = get(data, key);
    if (kinds[key] === "required") return value === true ? "필요" : value === false ? "불필요" : "";
    return Array.isArray(value) ? value.join(", ") : value;
  }
  function input(key, placeholder = "") {
    return '<input class="form-control" id="requisition-input-' + key + '" data-field="' + key + '" maxlength="10000" value="' + escape(get(current(), key)) + '" placeholder="' + escape(placeholder) + '">';
  }
  function chips(key, title) {
    const values = get(current(), key);
    const isCountry = key === "export_countries";
    return '<div class="requisition-chips">' + values.map((value, index) =>
      '<span class="multi-select__chip">' + escape(value) + '<button type="button" class="multi-select__remove" data-remove="' + key + '" data-index="' + index + '" aria-label="' + escape(value) + ' 삭제">×</button></span>').join("") +
      '</div><div class="requisition-chip-entry"><div class="requisition-chip-input"><input class="form-control form-control-sm" id="requisition-input-' + key + '" data-chip="' + key + '" maxlength="100" placeholder="' + title + '" aria-label="' + title + '"' + (isCountry ? ' role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="requisition-country-list" aria-describedby="requisition-country-help" autocomplete="off"' : "") + '>' +
      (isCountry ? '<div id="requisition-country-list" class="requisition-country-list" role="listbox" aria-label="수출 대상국" hidden></div>' : "") +
      '</div><button type="button" class="btn btn-secondary btn-sm" data-add="' + key + '">추가</button></div>' +
      (isCountry ? '<p class="form-help" id="requisition-country-help">목록에 없으면 ‘기타 (직접 입력)’를 선택해 국가명을 입력해 주세요.</p>' : "");
  }
  function field(key) {
    const data = current(), required = requiredFields.includes(key);
    const requiredMissing = !editing() && required && missing(data).includes(key);
    let control;
    if (!editing()) {
      let value = fieldValue(data, key);
      if (key === "buyer_prohibited_ingredients") {
        value = [data.buyer_prohibited_ingredients.length ? "바이어 지정: " + data.buyer_prohibited_ingredients.join(", ") : "",
          data.regulatory_restricted_ingredients.length ? "규제 검토 대상: " + data.regulatory_restricted_ingredients.join(", ") : ""].filter(Boolean).join("\n");
      }
      control = '<p class="requisition-field-value">' + escape(value || "") + "</p>";
      if (key === "target_prices") control += legacyNote(data);
    } else if (key === "customer" && documentProject) {
      control = '<p class="requisition-field-value" id="requisition-input-customer">' + escape(documentProject.customer.name) + '</p>' +
        '<p class="form-help">연결 프로젝트의 고객사예요 (고객사 id 로 연결). 바꾸려면 위에서 프로젝트를 변경해 주세요.</p>';
    } else if (key === "target_prices") {
      control = pricesEditor(data);
    } else if (key === "ingredients.concept") {
      control = conceptEditor(data);
    } else if (key === "product_development.viscosity") {
      control = viscosityEditor(data);
    } else if (key === "product_type") {
      control = '<select class="form-control" id="requisition-input-product_type" data-field="product_type" aria-required="true"><option value="">선택하세요</option>' +
        types.map((value) => '<option value="' + value + '"' + (data[key] === value ? " selected" : "") + ">" + (value === "기타" ? "기타 / 직접 입력" : value) + "</option>").join("") +
        '</select><div id="requisition-detail-wrap" class="mt-4"' + (data.product_type === "스킨케어" ? "" : " hidden") + '><label class="form-label" for="requisition-input-product_type_detail">스킨케어 세부 유형</label>' +
        '<select class="form-control" id="requisition-input-product_type_detail" data-field="product_type_detail"><option value="">선택 안 함</option>' +
        options.skincare_types.map((value) => '<option value="' + value + '"' + (data.product_type_detail === value ? " selected" : "") + ">" + value + "</option>").join("") + "</select></div>" +
        '<div id="requisition-custom-wrap" class="mt-4"' + (data.product_type === "기타" ? "" : " hidden") + '><label class="form-label" for="requisition-input-product_type_custom">제품 유형 직접 입력 *</label>' + input("product_type_custom", "제품 유형을 입력하세요") + "</div>";
    } else if (key === "request_source") {
      control = '<div class="requisition-choice-buttons" role="radiogroup" aria-label="요청 구분">' + ["고객사 요청", "자사기획"].map((value, index) =>
        '<label class="requisition-choice' + (data[key] === value ? ' is-selected' : '') + '"><input type="radio"' + (index === 0 ? ' id="requisition-input-request_source"' : '') + ' name="requisition-request-source" data-field="request_source" value="' + value + '"' + (data[key] === value ? ' checked' : '') + '><span>' + value + '</span></label>').join("") + "</div>";
    } else if (key === "sample_request_type") {
      control = '<div class="requisition-choice-buttons" role="radiogroup" aria-label="샘플 구분">' + ["신규 샘플", "개선 샘플"].map((value, index) =>
        '<label class="requisition-choice' + (data[key] === value ? ' is-selected' : '') + '"><input type="radio"' + (index === 0 ? ' id="requisition-input-sample_request_type"' : '') + ' name="requisition-sample-type" data-field="sample_request_type" value="' + value + '"' + (data[key] === value ? ' checked' : '') + '><span>' + value + '</span></label>').join("") + "</div>";
    } else if (kinds[key] === "required" || kinds[key] === "application") {
      const options = kinds[key] === "required" ? [["", "선택하세요"], ["true", "필요"], ["false", "불필요"]] : [["", "선택하세요"], ...["Leave-on", "Rinse-off", "기타", "확인 필요"].map((v) => [v, v])];
      control = '<select class="form-control" id="requisition-input-' + key + '" data-field="' + key + '">' + options.map(([value, label]) => '<option value="' + value + '"' + (String(get(data, key) ?? "") === value ? " selected" : "") + '>' + label + '</option>').join("") + '</select>';
    } else if (kinds[key] === "textarea") {
      control = '<textarea class="form-control" rows="4" maxlength="10000" id="requisition-input-' + key + '" data-field="' + key + '">' + escape(get(data, key)) + '</textarea>';
    } else if (chipFields.includes(key)) {
      control = chips(key, key === "export_countries" ? "국가 선택 또는 입력" : labels[key] + " 입력");
      if (key === "buyer_prohibited_ingredients") control += '<p class="form-help">바이어가 사용하지 말라고 지정한 원료를 입력해요.</p>' +
        (data.regulatory_restricted_ingredients.length ? '<p class="form-help">규제 검토 대상: ' + escape(data.regulatory_restricted_ingredients.join(", ")) + " · 규제 확인 필요</p>" : "");
    } else if (key === "product_development.spf" || key === "product_development.pa") {
      control = input(key, key.endsWith("spf") ? "예: SPF50+ (원문 표기 그대로)" : "예: PA++++ (원문 표기 그대로)");
    } else control = input(key, labels[key] + " 입력");
    if (editing() && key === "product_development.container_reference") {
      control += '<p class="form-help">용기 관련 참고값이에요. AI 제형 모델링의 용기 적합성(대체 권장 용기)은 이후 단계에서 이 칸에 참고값으로 반영돼요.</p>';
    }
    if (editing() && key === "rnd_check_requests") {
      control += '<p class="form-help">연구소에 확인을 요청할 사항이에요. 인허가 규제 확인사항 반영은 이후 단계에서 연결돼요.</p>';
    }
    const provenance = (data.field_provenance || []).find((item) => item.field_key === key);
    let reviewStatus = provenance ? provenance.review_status : "";
    if (requiredMissing) reviewStatus = "missing";
    else if (!editing() && !required && !filled(fieldValue(data, key)) && reviewStatus !== "not_applicable") reviewStatus = "needs_review";
    if (!editing() && reviewStatus) {
      if (reviewStatus === "not_applicable" && !required) control = '<p class="requisition-field-value">해당 없음</p>';
      control += '<small class="text-caption requisition-review-status requisition-review-status--' + escape(reviewStatus) + '">' + ({ confirmed: "✓ 확인 완료", needs_review: "⚠ 확인필요", missing: "미입력", not_applicable: "해당 없음", user_edited: "✓ 사용자 수정" }[reviewStatus] || "") + '</small>';
    }
    const labelled = editing() && !compositeFields.has(key) && !(key === "customer" && documentProject);
    return '<div class="form-group' + (wideNoteFields.has(key) ? ' requisition-field-wide requisition-field-note' : wideFields.has(key) ? ' requisition-field-wide' : '') + '" id="requisition-field-' + key + '">' +
      (labelled ? '<label class="form-label" for="requisition-input-' + key + '">' : '<p class="form-label">') +
      labels[key] + (required ? ' <span class="is-required" aria-label="필수">*</span>' : "") +
      (labelled ? "</label>" : "</p>") + '<div class="requisition-field-content">' + control +
      '<p class="form-error" id="requisition-error-' + key + '" hidden></p></div></div>';
  }
  function currencyOptions(selected) {
    const list = options.currencies.includes(selected) || !selected ? options.currencies : [...options.currencies, selected];
    return list.map((code) => '<option value="' + escape(code) + '"' + (code === selected ? " selected" : "") + ">" + escape(code) + "</option>").join("");
  }
  function pricesEditor(data) {
    return '<div class="requisition-rows">' + data.target_prices.map((item, index) => '<div class="requisition-row requisition-price-row">' +
      '<input class="form-control" type="number" inputmode="decimal" min="0" step="any" id="requisition-price-amount-' + index + '" data-price="' + index + '" data-prop="amount" value="' + escape(item.amount ?? "") + '" placeholder="금액" aria-label="목표 가격 ' + (index + 1) + ' 금액">' +
      '<select class="form-control" data-price="' + index + '" data-prop="currency" aria-label="목표 가격 ' + (index + 1) + ' 통화">' + currencyOptions(item.currency) + "</select>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-remove-price="' + index + '" aria-label="목표 가격 ' + (index + 1) + ' 삭제">삭제</button></div>').join("") + "</div>" +
      '<button type="button" class="btn btn-soft btn-sm" id="requisition-add-price" data-add-price>+ 가격대 추가</button>' + legacyNote(data) +
      '<p class="form-help">가격대마다 금액과 통화를 입력해요. 여러 가격대의 샘플을 함께 요청할 수 있어요.</p>';
  }
  function conceptRow(item, index) {
    const label = escape(item.name || "원료 " + (index + 1));
    return '<div class="requisition-row requisition-concept-row">' +
      '<input class="form-control" id="requisition-concept-name-' + index + '" data-concept="' + index + '" data-prop="name" maxlength="300" value="' + escape(item.name) + '" placeholder="원료명 (INCI 등)" aria-label="원료명">' +
      '<select class="form-control" data-concept="' + index + '" data-prop="must_contain" aria-label="' + label + ' 함유 필수 여부">' +
      [["", "함유 필수 여부 미확인"], ["true", "함유 필수"], ["false", "함유 필수 아님"]].map(([value, text]) =>
        '<option value="' + value + '"' + (String(item.must_contain ?? "") === value ? " selected" : "") + ">" + text + "</option>").join("") + "</select>" +
      '<input class="form-control" data-concept="' + index + '" data-prop="efficacy_tags" maxlength="600" value="' + escape(item.efficacy_tags.join(", ")) + '" placeholder="효능 태그 (쉼표로 구분)" aria-label="' + label + ' 효능 태그">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-remove-concept="' + index + '" aria-label="' + label + ' 삭제">삭제</button></div>';
  }
  function conceptEditor(data) {
    return Object.entries(options.concept_kinds).map(([kind, title]) => {
      const rows = data.ingredients.concept.map((item, index) => [item, index]).filter(([item]) => item.kind === kind);
      return '<div class="requisition-concept-group"><p class="requisition-concept-title">' + escape(title) + "</p>" +
        (rows.length ? '<div class="requisition-rows">' + rows.map(([item, index]) => conceptRow(item, index)).join("") + "</div>" : '<p class="form-help">아직 없어요.</p>') +
        '<button type="button" class="btn btn-soft btn-sm" id="requisition-add-concept-' + kind + '" data-add-concept="' + kind + '">+ ' + escape(title) + " 추가</button></div>";
    }).join("") + '<p class="form-help">함유 필수 여부를 모르면 ‘미확인’으로 두세요. 효능 태그는 쉼표로 구분해 자유롭게 입력해요.</p>';
  }
  function viscosityEditor(data) {
    const levels = options.viscosity_levels, level = data.product_development.viscosity_level;
    return '<select class="form-control" id="requisition-input-product_development.viscosity_level" data-field="product_development.viscosity_level" aria-label="점도 선택값"' + (levels.length ? "" : " disabled") + ">" +
      (levels.length ? '<option value="">선택 안 함</option>' + levels.map((value) => '<option value="' + escape(value) + '"' + (level === value ? " selected" : "") + ">" + escape(value) + "</option>").join("")
        : '<option value="">선택값 확정 전</option>') + "</select>" +
      '<input class="form-control mt-3" id="requisition-input-product_development.viscosity" data-field="product_development.viscosity" maxlength="10000" value="' + escape(data.product_development.viscosity) + '" placeholder="점도를 서술형으로 입력" aria-label="점도 서술">' +
      (levels.length ? "" : '<p class="form-help">점도 드롭다운 값 목록은 아직 확정 전이에요. 지금은 서술형으로 입력해 주세요.</p>');
  }
  $("section-tabs").innerHTML = sectionTitles.map((title, index) =>
    '<button type="button" class="tab" id="requisition-section-tab-' + index + '" role="tab" aria-controls="requisition-section-' + index + '" aria-selected="false" tabindex="-1" data-section="' + index + '">' + escape(title) + '</button>').join("");
  function selectSection(index, focus = false) {
    activeSection = index;
    sectionTitles.forEach((title, i) => {
      const active = i === index, tab = $("section-tab-" + i);
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      $("section-" + i).hidden = !active;
    });
    $("basic-title").textContent = sectionTitles[index];
    if (focus) $("section-tab-" + index).focus({ preventScroll: true });
  }
  $("section-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-section]");
    if (tab) selectSection(Number(tab.dataset.section));
  });
  $("section-tabs").addEventListener("keydown", (event) => {
    const tab = event.target.closest("[data-section]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = Number(tab.dataset.section), count = sectionTitles.length;
    const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + count) % count;
    selectSection(next, true);
  });
  function render() {
    if (!hasDocument()) documentProject = null;
    const choosingMode = state === "upload" || state === "manual";
    $("modes").hidden = !choosingMode;
    ["auto", "manual"].forEach((mode) => {
      const active = mode === "manual" ? state === "manual" : state === "upload";
      $(mode).classList.toggle("is-active", active);
      $(mode).setAttribute("aria-selected", String(active));
      $(mode).tabIndex = active ? 0 : -1;
    });
    $("upload").setAttribute("role", "tabpanel");
    $("upload").setAttribute("aria-labelledby", "requisition-auto");
    if (state === "manual") {
      $("document").setAttribute("role", "tabpanel");
      $("document").setAttribute("aria-labelledby", "requisition-manual");
    } else {
      $("document").removeAttribute("role");
      $("document").removeAttribute("aria-labelledby");
    }
    $("upload").hidden = state !== "upload";
    $("loading").hidden = state !== "loading";
    $("document").hidden = !["manual", "edit", "result"].includes(state);
    $("new").hidden = state !== "result";
    const headings = { upload: "개발요청서 분석", loading: "개발요청서 분석", result: "개발요청서", edit: "개발요청서 수정", manual: "개발요청서 직접 작성" };
    $("title").textContent = headings[state];
    $("description").textContent = state === "upload" || state === "loading" ? "바이어 요청서를 변환하거나 직접 작성하여 개발팀에 전달해요." :
      editing() ? "필수 항목을 입력하고 개발팀에 전달할 요청서를 완성해요." : "내용을 확인하고 필요하면 수정한 뒤 PDF로 저장해요.";
    if (state === "upload" || state === "loading") return;
    const data = current();
    $("fields").innerHTML = sections.map(([title, fields], index) => '<section class="requisition-section" id="requisition-section-' + index + '" role="tabpanel" aria-labelledby="requisition-section-tab-' + index + '" tabindex="0"><h2 class="card-title">' + escape(title) + '</h2><div class="requisition-fields">' + fields.map(([key]) => field(key)).join("") + '</div></section>').join("");
    selectSection(activeSection);
    renderReferences();
    $("panel-title").textContent = editing() ? "작성 상태" : "문서 정보";
    $("form-help").textContent = editing() ? "* 표시된 항목은 필수 입력이에요." : "개발에 필요한 핵심 정보를 확인해요.";
    $("secondary").textContent = state === "result" ? "수정" : state === "edit" ? "수정 취소" : "작성 취소";
    $("primary").textContent = state === "result" ? "인쇄 / PDF 저장" : state === "edit" ? "수정 완료" : "작성 완료";
    $("primary").hidden = false;
    $("erp").hidden = state !== "result";
    $("pdf-help").hidden = editing();
    updateSummary();
  }
  function updateSummary() {
    const data = current();
    if (!data) return;
    const required = missing(data), checks = reviews(data);
    $("document-project").textContent = documentProject ? projectLabel(documentProject) : "미연결 (프로젝트 선택 전 작성)";
    $("method").textContent = methods[data.creation_method];
    $("count-label").textContent = editing() ? "채운 항목" : "입력 완료";
    $("count").textContent = Object.keys(labels).filter((key) => filled(get(data, key)) && !(key === "product_type" && required.includes(key))).length + " / " + definitions.length;
    $("export-review").textContent = data.export_countries.length ? data.export_countries.join(", ") + " · ⚠ 규제 확인 필요" : "";
    $("missing-wrap").hidden = !editing() || !required.length;
    $("missing").textContent = required.map((key) => labels[key]).join(", ");
    $("review").textContent = checks.length ? checks.length + "건 · " + checks.join(", ") : "없음";
    data.review_status = required.length || checks.length || data.export_countries.length ? "needs_review" : "complete";
  }
  function transition(next) {
    state = next;
    notice();
    render();
    $("title").focus({ preventScroll: true });
    $("title").scrollIntoView({ block: "start", behavior: "instant" });
  }
  function markEdited(key) {
    let item = draft.field_provenance.find((entry) => entry.field_key === key);
    if (!item) {
      item = { field_key: key, source_value: "", translated_value: null, source_page: "", source_language: draft.source_language, target_language: draft.target_language };
      draft.field_provenance.push(item);
    }
    if (item) {
      item.user_value = clone(get(draft, key));
      item.input_source = "user_edited";
      item.review_status = "user_edited";
    }
  }
  function addChip(key) {
    const el = $("input-" + key), value = el.value.trim();
    if (!value) return;
    if (get(draft, key).length >= 50) return notice("한 항목에 최대 50개까지 추가할 수 있어요.");
    if (!get(draft, key).some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase())) get(draft, key).push(value);
    markEdited(key);
    if (key === "sample_request_type" || key === "request_source") render();
    $("field-" + key).outerHTML = field(key);
    updateSummary();
    $("input-" + key).focus();
  }
  function referenceMarkup(data, printable = false) {
    return (data.reference_files || []).map((file, index) => '<figure class="requisition-reference">' +
      (/^data:image\/(png|jpeg|webp);base64,/.test(file.data_url || "") ? '<img src="' + escape(file.data_url) + '" alt="' + escape(file.name) + '" style="max-width:100%;max-height:65mm">' : '') +
      '<figcaption>' + escape(file.name) + '</figcaption>' +
      (!printable ? '<a download="' + escape(file.name) + '" href="' + escape(file.data_url) + '">다운로드</a>' : '') +
      (!printable && editing() ? '<button type="button" class="btn btn-secondary btn-sm" data-remove-reference="' + index + '">삭제</button>' : '') + '</figure>').join("");
  }
  function renderReferences() {
    $("references").innerHTML = '<div class="requisition-reference-grid">' + referenceMarkup(current()) + '</div>' +
      (originalFile ? '<button type="button" class="btn btn-secondary" data-original-file>원본 RFP 다운로드</button>' : '') +
      (editing() ? '<div class="requisition-reference-upload"><div><p class="form-label">참고자료 추가</p><p class="form-help">PNG, JPG, WEBP, PDF, DOCX, XLSX · 파일당 5MB · 전체 20MB</p></div><input class="requisition-file-input" type="file" id="requisition-reference-input" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.docx,.xlsx"><label class="btn btn-soft" for="requisition-reference-input"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/></svg>파일 선택</label></div><p class="form-help requisition-reference-help">선택한 이미지는 PDF에 함께 표시되고, 문서는 파일명으로 표시돼요.</p>' : !(current().reference_files || []).length ? '<div class="requisition-reference-empty"><p>등록된 참고자료가 없어요.</p></div>' : '') +
      '<div class="form-group requisition-reference-notes requisition-field-note"><label class="form-label" for="requisition-input-reference_notes">기타사항</label><div class="requisition-field-content">' +
      (editing() ? '<textarea class="form-control" rows="4" maxlength="10000" id="requisition-input-reference_notes" data-field="reference_notes">' + escape(current().reference_notes || "") + '</textarea>' : '<p class="requisition-field-value">' + escape(current().reference_notes || "") + '</p>' + (!current().reference_notes ? '<small class="text-caption requisition-review-status requisition-review-status--needs_review">⚠ 확인필요</small>' : '')) + '</div></div>';
  }
  $("document").addEventListener("change", async (event) => {
    if (!editing()) return;
    if (event.target.id !== "requisition-reference-input") return;
    const activeDraft = draft;
    const files = [...event.target.files];
    $("primary").disabled = true;
    try {
      for (const file of files) {
        if (!/\.(png|jpe?g|webp|pdf|docx|xlsx)$/i.test(file.name) || !file.size || file.size > 5 * 1024 * 1024) throw new Error("참고자료 형식과 크기(최대 5MB)를 확인해 주세요.");
        if (activeDraft.reference_files.length >= 20 || activeDraft.reference_files.reduce((total, item) => total + item.size, 0) + file.size > 20 * 1024 * 1024) throw new Error("참고자료는 최대 20개, 전체 20MB까지 추가할 수 있어요.");
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error("참고자료를 읽지 못했어요."));
          reader.readAsDataURL(file);
        });
        if (draft !== activeDraft || !editing()) return;
        activeDraft.reference_files.push({ name: file.name, size: file.size, type: file.type || "", data_url: dataUrl });
      }
      markEdited("reference_files");
    } catch (error) { notice(error.message); }
    finally { $("primary").disabled = false; if (draft === activeDraft && editing()) renderReferences(); }
  });
  $("references").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove-reference]");
    if (remove && editing()) {
      draft.reference_files.splice(Number(remove.dataset.removeReference), 1);
      markEdited("reference_files");
      renderReferences();
    }
    if (event.target.closest("[data-original-file]") && originalFile) {
      const url = URL.createObjectURL(originalFile), link = document.createElement("a");
      link.href = url; link.download = originalFile.name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
  function closeCountries() {
    const el = $("input-export_countries"), list = $("country-list");
    if (!el || !list) return;
    list.hidden = true;
    el.setAttribute("aria-expanded", "false");
    el.removeAttribute("aria-activedescendant");
  }
  function showCountries() {
    const el = $("input-export_countries"), list = $("country-list");
    if (el.dataset.directEntry === "true") { closeCountries(); return; }
    const query = el.value.trim().toLocaleLowerCase();
    const options = countries.filter((name) => name.toLocaleLowerCase().includes(query) && !draft.export_countries.includes(name));
    list.innerHTML = options.map((name, index) => '<button type="button" class="requisition-country-option" role="option" tabindex="-1" aria-selected="false" id="requisition-country-option-' + index + '" data-country="' + escape(name) + '">' + escape(name) + '</button>').join("") +
      '<button type="button" class="requisition-country-option requisition-country-option--other" role="option" tabindex="-1" aria-selected="false" id="requisition-country-option-other" data-country-other>기타 (직접 입력)</button>';
    list.hidden = false;
    el.setAttribute("aria-expanded", "true");
    el.removeAttribute("aria-activedescendant");
  }
  function enableDirectCountryEntry() {
    const el = $("input-export_countries");
    el.value = "";
    el.dataset.directEntry = "true";
    el.placeholder = "수출국 직접 입력";
    el.setAttribute("aria-label", "기타 수출 대상국 직접 입력");
    closeCountries();
    el.focus();
  }
  ["focusin", "input", "click"].forEach((type) => {
    $("document").addEventListener(type, (event) => {
      if (editing() && event.target.dataset.chip === "export_countries") showCountries();
    });
  });
  $("document").addEventListener("focusout", (event) => {
    if (event.target.dataset.chip === "export_countries") closeCountries();
  });
  $("document").addEventListener("mousedown", (event) => {
    if (event.target.closest("[data-country], [data-country-other]")) event.preventDefault();
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#requisition-field-export_countries")) closeCountries();
  });
  $("document").addEventListener("input", (event) => {
    const el = event.target, key = el.dataset.field;
    if (editing() && el.dataset.price !== undefined) {
      const item = draft.target_prices[Number(el.dataset.price)];
      item[el.dataset.prop] = el.dataset.prop === "amount" ? (el.value === "" ? null : Number(el.value)) : el.value;
      markEdited("target_prices");
      updateSummary();
      return;
    }
    if (editing() && el.dataset.concept !== undefined) {
      const item = draft.ingredients.concept[Number(el.dataset.concept)], prop = el.dataset.prop;
      item[prop] = prop === "must_contain" ? (el.value === "" ? null : el.value === "true")
        : prop === "efficacy_tags" ? [...new Set(el.value.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))] : el.value;
      markEdited("ingredients.concept");
      updateSummary();
      return;
    }
    if (!editing() || !key) return;
    set(draft, key, kinds[key] === "required" ? (el.value === "" ? null : el.value === "true") : el.value);
    markEdited(key);
    if (key === "product_type") {
      $("custom-wrap").hidden = el.value !== "기타";
      if (el.value !== "기타") { draft.product_type_custom = ""; $("input-product_type_custom").value = ""; }
      $("detail-wrap").hidden = el.value !== "스킨케어";
      if (el.value !== "스킨케어") { draft.product_type_detail = ""; $("input-product_type_detail").value = ""; }
    }
    if (key === "product_type_detail") markEdited("product_type");
    if (key === "product_type_custom") markEdited("product_type");
    el.removeAttribute("aria-invalid");
    el.classList.remove("is-error");
    updateSummary();
  });
  $("document").addEventListener("click", (event) => {
    if (!editing()) return;
    if (event.target.closest("[data-country-other]")) {
      enableDirectCountryEntry();
      return;
    }
    const country = event.target.closest("[data-country]");
    if (country) {
      $("input-export_countries").value = country.dataset.country;
      addChip("export_countries");
      return;
    }
    const addPrice = event.target.closest("[data-add-price]"), removePrice = event.target.closest("[data-remove-price]");
    const addConcept = event.target.closest("[data-add-concept]"), removeConcept = event.target.closest("[data-remove-concept]");
    if (addPrice || removePrice || addConcept || removeConcept) {
      const key = addPrice || removePrice ? "target_prices" : "ingredients.concept";
      let focusId;
      if (addPrice) {
        if (draft.target_prices.length >= 10) return notice("목표 가격대는 10개까지 넣을 수 있어요.");
        draft.target_prices.push({ amount: null, currency: (draft.target_prices.at(-1) || {}).currency || options.currencies[0] });
        focusId = "requisition-price-amount-" + (draft.target_prices.length - 1);
      } else if (removePrice) draft.target_prices.splice(Number(removePrice.dataset.removePrice), 1);
      else if (addConcept) {
        if (draft.ingredients.concept.length >= 50) return notice("컨셉 원료는 50개까지 넣을 수 있어요.");
        draft.ingredients.concept.push({ name: "", kind: addConcept.dataset.addConcept, must_contain: null, efficacy_tags: [] });
        focusId = "requisition-concept-name-" + (draft.ingredients.concept.length - 1);
      } else draft.ingredients.concept.splice(Number(removeConcept.dataset.removeConcept), 1);
      markEdited(key);
      $("field-" + key).outerHTML = field(key);
      updateSummary();
      (document.getElementById(focusId) || $(addPrice || removePrice ? "add-price" : "add-concept-" + (addConcept ? addConcept.dataset.addConcept : "necessary"))).focus();
      return;
    }
    const add = event.target.closest("[data-add]"), remove = event.target.closest("[data-remove]");
    if (add) addChip(add.dataset.add);
    if (remove) {
      const key = remove.dataset.remove;
      get(draft, key).splice(Number(remove.dataset.index), 1);
      markEdited(key);
      const pendingValue = $("input-" + key).value;
      $("field-" + key).outerHTML = field(key);
      $("input-" + key).value = pendingValue;
      updateSummary();
      $("input-" + key).focus();
    }
  });
  $("document").addEventListener("keydown", (event) => {
    if (!editing() || event.isComposing || event.keyCode === 229) return;
    if (event.target.dataset.chip === "export_countries") {
      const el = event.target, list = $("country-list");
      if (event.key === "Escape") {
        event.preventDefault();
        if (el.dataset.directEntry === "true") {
          delete el.dataset.directEntry;
          el.value = "";
          el.placeholder = "국가 선택 또는 입력";
          el.setAttribute("aria-label", "국가 선택 또는 입력");
          showCountries();
        } else closeCountries();
        return;
      }
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        if (el.dataset.directEntry === "true") return;
        if (list.hidden) showCountries();
        const options = [...list.querySelectorAll("[role=option]")];
        if (!options.length) return;
        const currentIndex = options.findIndex((option) => option.id === el.getAttribute("aria-activedescendant"));
        const index = currentIndex < 0 ? (event.key === "ArrowDown" ? 0 : options.length - 1) :
          (currentIndex + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
        options.forEach((option, i) => option.setAttribute("aria-selected", String(i === index)));
        el.setAttribute("aria-activedescendant", options[index].id);
        options[index].scrollIntoView({ block: "nearest" });
        return;
      }
      if (event.key === "Enter" && !list.hidden) {
        const active = document.getElementById(el.getAttribute("aria-activedescendant"));
        if (active && active.hasAttribute("data-country-other")) {
          event.preventDefault();
          enableDirectCountryEntry();
          return;
        }
        if (active) el.value = active.dataset.country;
      }
    }
    if (event.key === "Enter" && event.target.dataset.chip && !event.isComposing) {
      event.preventDefault();
      addChip(event.target.dataset.chip);
    }
  });
  function selectMode(mode) {
    if (!["upload", "manual"].includes(state)) return;
    if (mode === "manual" && state !== "manual") {
      if (!hasDocument()) documentProject = project;
      draft = draft || blank();
      if (!draft.customer) draft.customer = $("setting-customer").value.trim();
      transition("manual");
    } else if (mode === "auto" && state === "manual") {
      chipFields.forEach((key) => {
        const value = $("input-" + key).value.trim();
        if (value && get(draft, key).length < 50 && !get(draft, key).includes(value)) get(draft, key).push(value);
      });
      transition("upload");
    }
    if (state === "upload") $(mode).focus({ preventScroll: true });
  }
  ["auto", "manual"].forEach((mode, index) => {
    $(mode).addEventListener("click", () => selectMode(mode));
    $(mode).addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? "auto" : event.key === "End" ? "manual" : ["auto", "manual"][1 - index];
      selectMode(next);
    });
  });
  $("secondary").addEventListener("click", () => {
    if (state === "result") { draft = clone(saved); transition("edit"); }
    else if (state === "edit") { draft = null; transition("result"); }
    else if (confirm("작성 중인 내용을 취소할까요?")) { draft = null; transition("upload"); }
  });
  $("new").addEventListener("click", () => {
    if (!confirm("새 요청서를 시작하면 현재 요청서가 지워져요. 계속할까요?")) return;
    saved = draft = originalFile = null;
    activeSection = 0;
    $("file").value = "";
    transition("upload");
  });
  $("erp").addEventListener("click", () => {
    alert("ERP 연동 기능은 현재 개발 중입니다.");
  });
  $("document").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state === "result") { await printPDF(); return; }
    // 추가 버튼을 누르지 않은 마지막 국가/원료도 완료 시 반영합니다.
    const pendingChips = chipFields.map((key) => [key, $("input-" + key).value.trim()]);
    for (const [key, value] of pendingChips) {
      if (!value) continue;
      $("input-" + key).value = value;
      addChip(key);
    }
    for (const key of ["customer", "product_name", "product_type_custom", "benchmark_product_name"]) draft[key] = draft[key].trim();
    const invalid = cleanLists(draft);
    if (invalid) {
      activeSection = sections.findIndex(([, fields]) => fields.some(([key]) => key === invalid[0]));
      render();
      $("field-" + invalid[0]).scrollIntoView({ block: "center" });
      (document.querySelector("#requisition-field-" + CSS.escape(invalid[0]) + " input, #requisition-field-" + CSS.escape(invalid[0]) + " button") || $("title")).focus();
      return notice(invalid[1]);
    }
    const absent = missing(draft);
    if (absent.length) {
      activeSection = sections.findIndex(([, fields]) => fields.some(([key]) => key === absent[0]));
      render();
      absent.forEach((key) => {
        const el = $("input-" + (key === "product_type" && draft.product_type === "기타" ? "product_type_custom" : key));
        el.classList.add("is-error");
        el.setAttribute("aria-invalid", "true");
        el.setAttribute("aria-describedby", "requisition-error-" + key);
        $("error-" + key).hidden = false;
        $("error-" + key).textContent = labels[key] + " 항목을 입력해 주세요.";
      });
      $("input-" + (absent[0] === "product_type" && draft.product_type === "기타" ? "product_type_custom" : absent[0])).focus();
      return notice("필수 항목을 확인해 주세요: " + absent.map((key) => labels[key]).join(", "));
    }
    if (state === "edit") {
      const keys = [...inputPaths, "customer", "reference_files"];
      if (keys.some((key) => JSON.stringify(get(draft, key)) !== JSON.stringify(get(saved, key)))) {
        draft.creation_method = saved.creation_method.startsWith("auto") ? "auto_edited" : "manual_edited";
      }
    }
    saved = clone(draft);
    draft = null;
    transition("result");
  });
  // 목표 가격대·컨셉 원료 정리: 빈 줄은 빼고, 잘못된 금액·중복은 알려 줍니다. [필드 키, 안내] 또는 null.
  function cleanLists(doc) {
    doc.target_prices = doc.target_prices.filter((item) => item.amount !== null && item.amount !== "");
    if (doc.target_prices.some((item) => !Number.isFinite(item.amount) || item.amount <= 0)) return ["target_prices", "목표 가격대 금액은 0보다 큰 숫자로 입력해 주세요."];
    const prices = doc.target_prices.map((item) => item.amount + " " + item.currency);
    if (new Set(prices).size !== prices.length) return ["target_prices", "같은 목표 가격대(금액·통화)가 두 번 들어 있어요."];
    doc.ingredients.concept = doc.ingredients.concept.map((item) => ({ ...item, name: item.name.trim() })).filter((item) => item.name);
    const names = doc.ingredients.concept.map((item) => item.name.toLocaleLowerCase());
    const duplicate = names.find((name, index) => names.indexOf(name) !== index);
    if (duplicate) return ["ingredients.concept", "같은 컨셉 원료가 두 번 들어 있어요 (필수·선호 중 하나로만): " + doc.ingredients.concept[names.indexOf(duplicate)].name];
    return null;
  }
  async function convert(files) {
    if (state !== "upload") return;
    notice();
    if (files.length !== 1) return notice("파일을 한 개씩 업로드해 주세요.");
    const file = files[0];
    if (!/\.(pdf|docx|xlsx|png|jpe?g|webp)$/i.test(file.name)) return notice("지원하지 않는 파일 형식이에요. PDF, DOCX, XLSX 또는 이미지를 선택해 주세요.");
    if (!file.size || file.size > 20 * 1024 * 1024) return notice("0바이트 파일은 사용할 수 없으며, 최대 용량은 20MB예요.");
    const selectedSourceLanguage = $("source-language").value;
    const sourceLanguage = selectedSourceLanguage === "other" ? $("source-language-other").value.trim() : selectedSourceLanguage;
    if (!sourceLanguage) {
      $("source-language-other").focus();
      return notice("원문 언어를 직접 입력해 주세요.");
    }
    const body = new FormData();
    body.append("file", file);
    body.append("customer", $("setting-customer").value.trim());
    body.append("source_language", sourceLanguage);
    body.append("target_language", $("target-language").value);
    if (!hasDocument()) documentProject = project;
    const requestController = new AbortController();
    controller = requestController;
    const timer = setTimeout(() => requestController.abort("timeout"), 150000);
    transition("loading");
    $("loading-file").textContent = file.name;
    try {
      const response = await fetch(root.dataset.convertUrl, { method: "POST", body, signal: requestController.signal });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "변환하지 못했어요. 잠시 후 다시 시도해 주세요.");
      if (controller !== requestController) return;
      saved = payload.document;
      if (documentProject) saved.customer = documentProject.customer.name;   // 고객사는 연결 프로젝트 기준 (원문 표기는 출처에 남음)
      originalFile = file; // 원본은 페이지 메모리에서만 보존합니다.
      transition("result");
    } catch (error) {
      if (controller !== requestController) return;
      transition("upload");
      notice(requestController.signal.aborted ? "변환 시간이 초과됐어요. 다시 업로드하거나 직접 작성해 주세요." : error instanceof SyntaxError ? "서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요." : error.message);
    } finally {
      clearTimeout(timer);
      if (controller === requestController) controller = null;
      $("file").value = "";
    }
  }
  $("source-language").addEventListener("change", () => {
    const direct = $("source-language").value === "other";
    $("source-language-other-wrap").hidden = !direct;
    if (direct) $("source-language-other").focus();
    else $("source-language-other").value = "";
    notice();
  });
  $("file").addEventListener("change", (event) => { if (event.target.files.length) convert([...event.target.files]); });
  $("drop").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("file").click(); }
  });
  $("cancel-convert").addEventListener("click", () => {
    if (controller) controller.abort();
    controller = null;
    $("file").value = "";
    transition("upload");
  });
  let dragDepth = 0;
  $("drop").addEventListener("dragenter", (event) => { event.preventDefault(); dragDepth++; $("drop").classList.add("is-dragover"); });
  $("drop").addEventListener("dragover", (event) => event.preventDefault());
  $("drop").addEventListener("dragleave", () => { if (--dragDepth <= 0) $("drop").classList.remove("is-dragover"); });
  $("drop").addEventListener("drop", (event) => {
    event.preventDefault(); dragDepth = 0; $("drop").classList.remove("is-dragover");
    convert([...event.dataTransfer.files]);
  });
  async function printPDF() {
    if (!saved || state !== "result") return;
    $("primary").disabled = true;
    try {
      const data = clone(saved);
      const date = new Date(), datePart = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("");
      const safePart = (value) => String(value || "Unknown").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "").replace(/\s+/g, "").slice(0, 70);
      const filename = "DevelopmentRequest_" + safePart(data.customer) + "_" + safePart(data.product_name) + "_" + datePart;
      const pdfValue = (key) => {
        const provenance = data.field_provenance.find((item) => item.field_key === key);
        if (provenance?.review_status === "not_applicable") return "해당 없음";
        return fieldValue(data, key) || "";
      };
      const prohibitedIngredients = [
          data.buyer_prohibited_ingredients.length ? "바이어 지정: " + data.buyer_prohibited_ingredients.join(", ") : "",
          data.regulatory_restricted_ingredients.length ? "규제 검토 대상: " + data.regulatory_restricted_ingredients.join(", ") : ""
        ].filter(Boolean).join("\n");
      const issuedDate = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join(".");
      const row = (label, value) => '<tr><th scope="row">' + escape(label) + '</th><td>' + escape(value) + '</td></tr>';
      const printableSection = ([title, fields]) => {
        const rows = fields.map(([key, label]) => [label, key === "buyer_prohibited_ingredients" ? prohibitedIngredients : fieldValue(data, key)])
          .filter(([, value]) => filled(value));
        return rows.length ? '<section><h2>' + escape(title) + '</h2><table class="requirements"><colgroup><col class="label-column"><col></colgroup><thead><tr><th scope="col">항목</th><th scope="col">요청 내용</th></tr></thead><tbody>' +
          rows.map(([label, value]) => row(label, value)).join('') + '</tbody></table></section>' : '';
      };
      const printableReferences = referenceMarkup(data, true);
      const printableReferenceNotes = filled(data.reference_notes) ? '<table class="requirements"><tbody>' + row("기타사항", data.reference_notes) + '</tbody></table>' : '';
      const referenceSection = printableReferences || printableReferenceNotes ? '<section class="references"><h2>05 참고자료</h2>' + printableReferences + printableReferenceNotes + '</section>' : '';
      /* 견적서(03_margin/margin_quote_document.html) PDF 와 같은 양식: 회사 머리글 + 파란 제목, 정보 2단, 조건 4칸, 파란 헤더 표, 서명, 꼬리글.
         회사 정보는 공통 레이아웃의 내 계정 모달(base.html)에서 읽어 견적서와 같은 값을 씁니다. */
      const companyCell = (label) => { const dt = [...document.querySelectorAll(".app-about__list--company dt")].find((el) => el.textContent.trim() === label); return dt ? dt.nextElementSibling.textContent.trim() : ""; };
      const company = { name: companyCell("회사명") || "COSTD", address: companyCell("주소"), phone: companyCell("전화") };
      const preparedBy = (document.querySelector(".app-user__name")?.textContent || "").trim();
      const printMeta = (label, value) => '<tr><td class="k">' + escape(label) + '</td><td>' + escape(value) + '</td></tr>';
      const termCell = (label, value) => '<td><p class="k">' + escape(label) + '</p>' + escape(filled(value) ? value : "-") + '</td>';
      const listText = (value) => Array.isArray(value) ? value.join(", ") : value;
      const printHtml =
        '<table class="brand"><tr><td style="width: 60%;"><span class="company">' + escape(company.name) + '</span>' +
          (company.address ? '<br><span class="muted">' + escape(company.address) + '</span>' : '') +
          (company.phone ? '<br><span class="muted">Tel. ' + escape(company.phone) + '</span>' : '') +
        '</td><td class="title">DEVELOPMENT<br>REQUEST</td></tr></table>' +
        '<table class="info"><tr><td style="width: 55%;"><span class="label">Request to</span><br><span class="bold" style="font-size: 11pt;">연구소 (R&amp;D Center)</span><br>제품 개발 요청서 · 연구소 전달용' +
          (filled(data.customer) ? '<br><span class="muted">고객사: ' + escape(data.customer) + '</span>' : '') + '</td>' +
          '<td><table class="meta">' + printMeta("Version", "저장 전 (서버 버전 없음)") + printMeta("Date", issuedDate) +
          printMeta("Product", data.product_name || "") + printMeta("Prepared by", preparedBy || "-") + printMeta("Method", methods[data.creation_method] || "미지정") + '</table></td></tr></table>' +
        '<table class="terms"><tr>' + termCell("샘플 구분", pdfValue("sample_request_type")) + termCell("제품 유형", pdfValue("product_type")) +
          termCell("목표 가격대", pdfValue("target_prices")) + termCell("수출 대상국", listText(fieldValue(data, "export_countries"))) + '</tr></table>' +
        sections.map(printableSection).join('') + referenceSection +
        '<table class="notes"><tr><td><p class="sub">Notes</p><ol>' +
          '<li>본 요청서의 항목은 바이어 요청 원본을 연구소 검토용으로 정리한 것이며, 원문과 다른 해석이 있을 수 있습니다.</li>' +
          '<li>"확인 필요"로 표시된 항목은 영업 담당자와 다시 확인한 뒤 개발을 진행해 주세요.</li>' +
          '<li>수출 대상국별 규제 적합성(금지·제한 원료, 표시사항)은 별도 확인이 필요합니다.</li></ol></td></tr></table>' +
        '<table class="sign"><tr><td class="line" style="width: 42%;">Prepared by<br><span class="bold">' + escape(preparedBy || company.name) + '</span><br><span class="muted">' + escape(company.name) + ' · Overseas Sales</span></td>' +
          '<td style="width: 16%;">&nbsp;</td><td class="line">Reviewed by<br><span class="bold">&nbsp;</span><br><span class="muted">R&amp;D Center · Signature / Date</span></td></tr></table>' +
        '<div class="doc-footer">' + escape(company.name) + ' &middot; Development Request &middot; 저장 전 문서 &middot; ' + issuedDate + '</div>';
      const printStyles = `
        @page { size: A4; margin: 16mm 15mm 20mm 15mm; }
        * { box-sizing: border-box; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
        body { margin: 0; color: #191f28; background: #fff; font: 9pt/1.4 "Malgun Gothic", "Apple SD Gothic Neo", Helvetica, Arial, sans-serif; }
        table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        td, th { vertical-align: top; overflow-wrap: anywhere; }
        p { margin: 0; }
        caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
        .muted { color: #6b7684; }
        .bold { font-weight: bold; }
        .brand { margin-bottom: 12pt; }
        .brand td { padding: 0 0 8pt; border-bottom: 2pt solid #1b64da; vertical-align: bottom; }
        .brand .company { font-size: 15pt; font-weight: bold; }
        .brand .title { font-size: 20pt; font-weight: bold; color: #1b64da; letter-spacing: 2pt; text-align: right; line-height: 1.1; }
        .label { font-size: 7.5pt; color: #6b7684; text-transform: uppercase; letter-spacing: 0.6pt; }
        .info td { padding: 0 0 8pt; }
        .meta td { padding: 1.5pt 0; }
        .meta .k { color: #6b7684; width: 26mm; }
        .terms { margin-bottom: 10pt; }
        .terms td { border: 0.5pt solid #d1d6db; padding: 4pt 6pt; width: 25%; white-space: pre-wrap; }
        .terms .k { font-size: 7.5pt; color: #6b7684; }
        section { margin-top: 8pt; }
        h2 { margin: 0 0 4pt; font-size: 9pt; font-weight: bold; break-after: avoid; }
        .requirements thead { display: table-header-group; }
        .requirements th { background: #1b64da; color: #ffffff; font-size: 8pt; font-weight: bold; padding: 5pt 6pt; text-align: left; }
        .requirements td, .requirements tbody th { border-bottom: 0.5pt solid #e5e8eb; padding: 5pt 6pt; text-align: left; }
        .requirements tbody th { background: transparent; color: #6b7684; font-size: 8pt; font-weight: bold; }
        .requirements td { white-space: pre-wrap; }
        .label-column { width: 36mm; }
        tr { break-inside: avoid; }
        .references .requisition-reference { margin: 0 0 6pt; padding: 6pt; border: 0.5pt solid #d1d6db; break-inside: avoid; }
        .references .requisition-reference img { display: block; margin: 0 auto 4pt; max-width: 100%; max-height: 90mm; object-fit: contain; }
        figcaption { font-size: 8pt; color: #6b7684; overflow-wrap: anywhere; }
        .empty-reference { margin: 0; padding: 6pt; border: 0.5pt solid #d1d6db; color: #6b7684; }
        .notes { margin-top: 12pt; }
        .notes td { padding: 0; }
        .sub { margin: 0 0 4pt; font-size: 9pt; font-weight: bold; }
        ol { margin: 2pt 0 0 12pt; padding: 0; }
        li { margin: 0 0 1.5pt; }
        .sign { margin-top: 26pt; break-inside: avoid; }
        .sign td { padding: 0; }
        .sign .line { border-top: 0.5pt solid #191f28; padding-top: 3pt; }
        .doc-footer { position: fixed; left: 0; right: 0; bottom: -12mm; font-size: 7pt; color: #8b95a1; text-align: center; }
      `;
      if (printFrame) printFrame.remove();
      const frame = document.createElement("iframe");
      printFrame = frame;
      frame.className = "requisition-print-frame";
      frame.title = "개발요청서 PDF 저장";
      const loaded = new Promise((resolve) => { frame.onload = resolve; });
      frame.srcdoc = '<!doctype html><html lang="' + escape(data.target_language) + '"><head><meta charset="utf-8"><title>' + escape(filename) +
        '</title><style>' + printStyles + '</style></head><body>' + printHtml + '</body></html>';
      document.body.append(frame);
      await loaded;
      await frame.contentDocument.fonts.ready;
      await Promise.all([...frame.contentDocument.images].map((img) => img.decode().catch(() => {})));
      frame.contentWindow.focus();
      frame.contentWindow.print();
    } catch {
      notice("인쇄 창을 열지 못했어요. 다시 시도해 주세요.");
    } finally {
      $("primary").disabled = false;
    }
  }
  window.addEventListener("beforeunload", (event) => {
    if (saved || editing() || state === "loading" || originalFile) { event.preventDefault(); event.returnValue = ""; }
  });
  /* 프로젝트 선택 (고객사 → 프로젝트) — API: docs/api_contract.md 5장 */
  const PROJECT_KEY = "cosmoa.requisition.project";
  const stageNames = { proposal: "제안", development: "개발", order: "발주", production: "생산", shipping: "선적", completed: "완료" };
  const stateNames = { active: "진행", hold: "홀드", drop: "드롭" };
  let customers = [], customerNext = null, projects = [], projectNext = null, selectedCustomerId = null;
  let customerQuery = "", customerRequest = 0, projectRequest = 0, searchTimer = null;
  const idOf = (item) => item ? item.id : null;
  function projectLabel(item) { return item.customer.name + " › " + item.name; }
  function projectMeta(item) {
    return "단계 " + (stageNames[item.stage] || item.stage) + " · 상태 " + (stateNames[item.state] || item.state) + " · " + (item.due_date ? "납기 " + item.due_date : "납기 미정");
  }
  function projectError(message = "", focus = null) {
    $("project-error").textContent = message;
    $("project-error").hidden = !message;
    if (focus) focus.focus();
  }
  function apiMessage(result) {
    if (result.status === 401) return "로그인이 만료됐어요. 페이지를 새로 고친 뒤 다시 로그인해 주세요.";
    return (result.error && result.error.message) || "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
  }
  function showPicker(open) {
    $("project-picker").hidden = !open;
    $("project-toggle").setAttribute("aria-expanded", String(open));
    $("project-toggle").textContent = open && project ? "닫기" : project ? "프로젝트 변경" : "프로젝트 선택";
    $("project-toggle").hidden = open && !project;
  }
  function renderProject() {
    $("project-current").textContent = project ? projectLabel(project) : "프로젝트를 선택하지 않았어요";
    $("project-meta").textContent = project ? projectMeta(project) : "고객사와 프로젝트를 선택하면 이 요청서가 그 프로젝트에 연결돼요.";
    $("project").classList.toggle("has-project", Boolean(project));
    showPicker(!$("project-picker").hidden || !project);
  }
  // 작성 중인 요청서가 다른 프로젝트로 넘어가지 않도록 바꾸기 전에 확인합니다. (상태는 바꾸지 않음)
  function projectChangeAllowed(next) {
    if (!hasDocument()) return true;
    if (documentProject) {
      return idOf(next) === documentProject.id || confirm("작성 중인 요청서는 ‘" + projectLabel(documentProject) + "’ 프로젝트에 연결돼 있어요.\n" +
        "프로젝트를 바꾸면 작성 중인 요청서와 원본 파일이 초기화돼요. 계속할까요?\n(내용이 필요하면 취소한 뒤 먼저 PDF로 저장해 주세요.)");
    }
    return !next || confirm("작성 중인 요청서를 ‘" + projectLabel(next) + "’ 프로젝트에 연결할까요?\n" +
      "고객사 칸은 연결 프로젝트의 고객사(‘" + next.customer.name + "’)로 바뀌어요.");
  }
  function commitProject(next) {
    if (hasDocument()) {
      if (documentProject && idOf(next) !== documentProject.id) {
        if (controller) controller.abort();
        controller = null;
        saved = draft = originalFile = null;
        activeSection = 0;
        $("file").value = "";
        transition("upload");   // render() 가 documentProject 를 비웁니다.
      } else if (!documentProject && next) {
        documentProject = next;
        for (const doc of [saved, draft]) if (doc) doc.customer = next.customer.name;   // 고객사는 연결 프로젝트 기준
        if (editing() || state === "result") render();
      }
    }
    project = next;
    try { next ? sessionStorage.setItem(PROJECT_KEY, String(next.id)) : sessionStorage.removeItem(PROJECT_KEY); } catch { /* 저장 불가 환경 무시 */ }
    syncSettingCustomer();
    renderProject();
    updateSummary();
  }
  // 변환 설정의 고객사: 프로젝트를 고르면 그 고객사(id 로 연결)로 고정하고, 이름을 따로 입력받지 않습니다.
  function syncSettingCustomer() {
    const el = $("setting-customer");
    if (project) {
      el.value = project.customer.name;
      el.readOnly = true;
      $("setting-customer-help").textContent = "선택한 프로젝트의 고객사로 변환해요. 바꾸려면 위에서 프로젝트를 변경해 주세요.";
    } else {
      if (el.readOnly) el.value = "";
      el.readOnly = false;
      $("setting-customer-help").textContent = "입력한 고객사를 우선 적용해요. 프로젝트를 고르면 그 고객사로 바뀌어요.";
    }
  }
  function fillSelect(el, items, placeholder, label, selected) {
    el.innerHTML = '<option value="">' + escape(placeholder) + "</option>" + items.map((item) =>
      '<option value="' + item.id + '"' + (item.id === selected ? " selected" : "") + ">" + escape(label(item)) + "</option>").join("");
  }
  function renderCustomers() {
    fillSelect($("customer-select"), customers, customers.length ? "고객사를 선택하세요" : "등록된 고객사가 없어요 · 새 고객사를 만들어 주세요", (item) => item.name, selectedCustomerId);
    $("customer-more").hidden = !customerNext;
  }
  function renderProjects() {
    const el = $("project-select");
    el.disabled = !selectedCustomerId;
    $("project-new").disabled = !selectedCustomerId;
    fillSelect(el, projects, !selectedCustomerId ? "먼저 고객사를 선택하세요" : projects.length ? "프로젝트를 선택하세요" : "프로젝트가 없어요 · 새 프로젝트를 만들어 주세요",
      (item) => item.name + " · " + (stageNames[item.stage] || item.stage) + "/" + (stateNames[item.state] || item.state) + (item.due_date ? " · 납기 " + item.due_date : ""), idOf(project));
    $("project-more").hidden = !projectNext;
  }
  async function loadCustomers(append = false) {
    const request = ++customerRequest;
    const keep = customers.find((item) => item.id === selectedCustomerId) || (project && project.customer);
    const result = await Common.api("GET", "/api/customers?limit=100" + (customerQuery ? "&q=" + encodeURIComponent(customerQuery) : "") +
      (append && customerNext ? "&after=" + customerNext : ""));
    if (request !== customerRequest) return;   // 그 사이 검색어가 바뀜
    if (!result.ok) return projectError(apiMessage(result));
    customers = append ? [...customers, ...result.data.items] : result.data.items;
    customerNext = result.data.next_after;
    if (keep && keep.id === selectedCustomerId && !customers.some((item) => item.id === keep.id)) customers.unshift(keep);   // 선택한 고객사는 검색과 상관없이 유지
    renderCustomers();
  }
  async function loadProjects(append = false) {
    const request = ++projectRequest, customerId = selectedCustomerId;
    if (!append) { projects = []; projectNext = null; }
    renderProjects();
    if (!customerId) return;
    const result = await Common.api("GET", "/api/customers/" + customerId + "/projects?limit=100" + (append && projectNext ? "&before=" + projectNext : ""));
    if (request !== projectRequest) return;   // 그 사이 다른 고객사를 고름
    if (!result.ok) return projectError(apiMessage(result));
    projects = append ? [...projects, ...result.data.items] : result.data.items;
    projectNext = result.data.next_before;
    if (project && project.customer.id === customerId && !projects.some((item) => item.id === project.id)) projects.unshift(project);
    renderProjects();
  }
  async function selectCustomer(customerId) {
    projectError();
    if (customerId === selectedCustomerId) return true;
    if (project && !projectChangeAllowed(null)) { renderCustomers(); return false; }
    selectedCustomerId = customerId;
    if (project) commitProject(null);
    toggleCreate("project", false);
    renderCustomers();
    await loadProjects();
    return true;
  }
  $("project-toggle").addEventListener("click", () => {
    showPicker($("project-picker").hidden);
    if (!$("project-picker").hidden) $("customer-select").focus();
  });
  $("customer-select").addEventListener("change", (event) => selectCustomer(Number(event.target.value) || null));
  $("project-select").addEventListener("change", (event) => {
    projectError();
    const next = projects.find((item) => item.id === Number(event.target.value)) || null;
    if (!projectChangeAllowed(next)) { renderProjects(); return; }
    commitProject(next);
    if (next) { showPicker(false); $("project-toggle").focus(); }
  });
  $("customer-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { customerQuery = $("customer-search").value.trim(); loadCustomers(); }, 250);
  });
  $("customer-more").addEventListener("click", () => loadCustomers(true));
  $("project-more").addEventListener("click", () => loadProjects(true));
  function toggleCreate(kind, open) {
    $(kind + "-create").hidden = !open;
    $(kind + "-new").setAttribute("aria-expanded", String(open));
    if (open) $(kind + "-name").focus();
    else { $(kind + "-name").value = ""; if (kind === "project") $("project-due").value = ""; }
  }
  $("customer-new").addEventListener("click", () => toggleCreate("customer", $("customer-create").hidden));
  $("project-new").addEventListener("click", () => toggleCreate("project", $("project-create").hidden));
  $("customer-cancel").addEventListener("click", () => toggleCreate("customer", false));
  $("project-cancel").addEventListener("click", () => toggleCreate("project", false));
  async function busy(button, task) {
    if (button.disabled) return;
    button.disabled = true;
    try { await task(); } finally { button.disabled = false; }
  }
  $("customer-save").addEventListener("click", () => busy($("customer-save"), async () => {
    projectError();
    const name = $("customer-name").value.trim();
    if (!name) return projectError("고객사명을 입력해 주세요.", $("customer-name"));
    const found = await Common.api("GET", "/api/customers?limit=100&q=" + encodeURIComponent(name));
    const same = found.ok && found.data.items.find((item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase());
    if (same && !confirm("같은 이름의 고객사 ‘" + same.name + "’가 이미 있어요. 그래도 새로 만들까요?")) return;
    if (project && !projectChangeAllowed(null)) return;
    const result = await Common.api("POST", "/api/customers", { name });
    if (!result.ok) return projectError(apiMessage(result), $("customer-name"));
    toggleCreate("customer", false);
    await loadCustomers();
    if (!customers.some((item) => item.id === result.data.customer.id)) customers.push(result.data.customer);
    await selectCustomer(result.data.customer.id);
    toggleCreate("project", true);   // 새 고객사에는 프로젝트가 없으므로 바로 만들 수 있게
  }));
  $("project-save").addEventListener("click", () => busy($("project-save"), async () => {
    projectError();
    const name = $("project-name").value.trim(), due = $("project-due").value;
    if (!selectedCustomerId) return projectError("먼저 고객사를 선택해 주세요.", $("customer-select"));
    if (!name) return projectError("프로젝트(제품)명을 입력해 주세요.", $("project-name"));
    const customer = customers.find((item) => item.id === selectedCustomerId) || { name: "" };
    if (!projectChangeAllowed({ id: -1, name, customer })) return;
    const result = await Common.api("POST", "/api/customers/" + selectedCustomerId + "/projects", { name, due_date: due || null });
    if (!result.ok) return projectError(apiMessage(result), $("project-name"));
    toggleCreate("project", false);
    commitProject(result.data.project);
    await loadProjects();
    showPicker(false);
    $("project-toggle").focus();
  }));
  ["customer", "project"].forEach((kind) => {
    $(kind + "-create").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing && event.target.tagName === "INPUT") { event.preventDefault(); $(kind + "-save").click(); }
      if (event.key === "Escape") { event.stopPropagation(); toggleCreate(kind, false); $(kind + "-new").focus(); }
    });
  });
  async function initProject() {
    let stored = null;
    try { stored = Number(sessionStorage.getItem(PROJECT_KEY)) || null; } catch { /* 저장 불가 환경 무시 */ }
    if (stored) {   // 새로 고침 후 같은 탭에서 고른 프로젝트를 다시 확인 (없어졌거나 보관됐으면 선택 해제)
      const result = await Common.api("GET", "/api/projects/" + stored);
      if (result.ok && !result.data.project.archived) {
        selectedCustomerId = result.data.project.customer.id;
        commitProject(result.data.project);
      } else if (result.ok || result.status === 404) commitProject(null);
      else projectError(apiMessage(result));
    }
    renderProject();
    await loadCustomers();
    await loadProjects();
  }
  // 저장용 payload (계약 v1) — 저장 버튼 연결(다음 작업)과 테스트에서 씁니다.
  // 화면에서 지금 고른 프로젝트가 아니라 요청서의 연결 프로젝트(documentProject)로 만듭니다.
  root.buildRequisitionPayload = () => RequisitionPayload.build(current(), documentProject, options);
  render();
  initProject();
})();
