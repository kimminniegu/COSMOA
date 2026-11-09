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
  const wideNoteFields = new Set(["company_description", "basic_notes", "ingredients.concept_notes", "ingredients.other_notes", "rnd_check_requests"]);
  const wideFields = new Set(["target_prices", "ingredients.concept", "product_development.container_reference", "product_development.viscosity", "product_development.texture", "product_development.appearance_sensory"]);
  // 입력 칸 하나로 끝나지 않는 항목 (목록 편집·선택값+서술)
  const compositeFields = new Set(["target_prices", "ingredients.concept", "product_development.viscosity", "product_development.texture"]);
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
  // 저장본 상태: currentVersion = 마지막으로 저장·불러온 버전, versionDirty = 그 뒤 내용이 바뀜, finalState = 프로젝트의 현재 최종본 기록
  let currentVersion = null, versionDirty = false, documentTitle = "", finalState = null, versionBusy = false;
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
  const bandText = (key) => {
    const band = options.viscosity_bands.find((item) => item.key === key);
    return band ? band.label + " – " + band.example : "";
  };
  const withBuyerText = (value, text) => [value, filled(text) ? "바이어 원문: " + text : ""].filter(filled).join("\n");
  const provenanceNeedsReview = (data, key) => (data.field_provenance || []).some((item) => item.field_key === key && item.review_status === "needs_review");
  // 구간 없이 원문만 있거나(예전 자유 서술 포함), AI 가 추정한 값을 아직 확인하지 않은 경우
  const viscosityNeedsReview = (data) => (filled(data.product_development.viscosity) && !data.product_development.viscosity_level) ||
    provenanceNeedsReview(data, "product_development.viscosity_level");
  const textureNeedsReview = (data) => provenanceNeedsReview(data, "product_development.texture_tags");
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
    if (viscosityNeedsReview(data)) result.push(labels["product_development.viscosity"]);
    if (textureNeedsReview(data)) result.push(labels["product_development.texture"]);
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
      return withBuyerText(bandText(data.product_development.viscosity_level), data.product_development.viscosity);
    }
    if (key === "product_development.texture") {
      return withBuyerText(data.product_development.texture_tags.join(", "), data.product_development.texture);
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
    } else if (key === "product_development.texture") {
      control = textureEditor(data);
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
    if (editing() && key === "ingredients.concept_notes") {
      control += '<p class="form-help">컨셉 원료에 대한 코멘트예요. AI 제형 모델링의 컨셉원료 코멘트는 이후 단계에서 이 칸에 반영돼요.</p>';
    }
    if (editing() && key === "rnd_check_requests") {
      control += '<p class="form-help">연구소에 확인을 요청할 사항이에요. 인허가 규제 확인사항 반영은 이후 단계에서 연결돼요.</p>';
    }
    const provenance = (data.field_provenance || []).find((item) => item.field_key === key);
    let reviewStatus = provenance ? provenance.review_status : "";
    if ((key === "product_development.viscosity" && viscosityNeedsReview(data)) || (key === "product_development.texture" && textureNeedsReview(data))) reviewStatus = "needs_review";
    if (requiredMissing) reviewStatus = "missing";
    if (!editing() && reviewStatus) {
      if (reviewStatus === "not_applicable" && !required) control = '<p class="requisition-field-value">해당 없음</p>';
      else if (reviewStatus === "needs_review" || reviewStatus === "missing") {   // 사람이 볼 필요가 있는 상태만 표시합니다.
        control += '<small class="text-caption requisition-review-status requisition-review-status--' + escape(reviewStatus) + '">' + (reviewStatus === "missing" ? "미입력" : "⚠ 확인필요") + '</small>';
      }
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
    const level = data.product_development.viscosity_level;
    return '<div class="requisition-composite"><select class="form-control" id="requisition-input-product_development.viscosity_level" data-field="product_development.viscosity_level" aria-label="점도 구간"><option value="">구간 선택 안 함</option>' +
      options.viscosity_bands.map((band) => '<option value="' + escape(band.key) + '"' + (level === band.key ? " selected" : "") + ">" + escape(bandText(band.key)) + "</option>").join("") + "</select>" +
      '<input class="form-control" id="requisition-input-product_development.viscosity" data-field="product_development.viscosity" maxlength="10000" value="' + escape(data.product_development.viscosity) + '" placeholder="바이어 원문 (표현 그대로)" aria-label="점도 바이어 원문"></div>' +
      '<p class="form-help">구간을 고르고, 바이어가 쓴 표현은 원문 칸에 그대로 남겨요.</p>';
  }
  function textureEditor(data) {
    const selected = data.product_development.texture_tags;
    return '<div class="requisition-options" role="group" aria-label="텍스처 태그">' + options.texture_tags.map((tag) =>
      '<label class="form-check"><input type="checkbox" data-texture-tag="' + escape(tag) + '"' + (selected.includes(tag) ? " checked" : "") + "> " + escape(tag) + "</label>").join("") + "</div>" +
      '<textarea class="form-control requisition-texture-text" rows="3" maxlength="10000" id="requisition-input-product_development.texture" data-field="product_development.texture" placeholder="바이어 원문 (표현 그대로)" aria-label="텍스처 바이어 원문">' + escape(data.product_development.texture) + "</textarea>";
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
    $("section-prev").hidden = index === 0;
    $("section-next").hidden = index === sectionTitles.length - 1;
    if (index > 0) $("section-prev").textContent = "← " + sectionTitles[index - 1];
    if (index < sectionTitles.length - 1) $("section-next").textContent = sectionTitles[index + 1] + " →";
    if (focus) $("section-tab-" + index).focus({ preventScroll: true });
  }
  $("section-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-section]");
    if (tab) selectSection(Number(tab.dataset.section));
  });
  [["section-prev", -1], ["section-next", 1]].forEach(([id, step]) => $(id).addEventListener("click", () => {
    selectSection(activeSection + step, true);
    $("section-tabs").scrollIntoView({ block: "start", behavior: "instant" });
  }));
  $("section-tabs").addEventListener("keydown", (event) => {
    const tab = event.target.closest("[data-section]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = Number(tab.dataset.section), count = sectionTitles.length;
    const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + count) % count;
    selectSection(next, true);
  });
  // 결과 화면에서는 비어 있는 선택 항목을 접어 입력된 내용과 확인이 필요한 항목만 보여 줍니다.
  function isHiddenEmpty(data, key) {
    if (editing() || requiredFields.includes(key) || filled(fieldValue(data, key)) || reviews(data).includes(labels[key])) return false;
    return !(data.field_provenance || []).some((item) => item.field_key === key && item.review_status === "not_applicable");
  }
  const visibleFields = (data, fields) => fields.filter(([key]) => !isHiddenEmpty(data, key));
  function emptyFieldsNote(data, fields) {
    const hidden = fields.filter(([key]) => isHiddenEmpty(data, key)).map(([, label]) => label);
    return hidden.length ? '<p class="text-caption requisition-empty-note">입력하지 않은 항목: ' + escape(hidden.join(", ")) + "</p>" : "";
  }
  function render() {
    if (!hasDocument()) { documentProject = null; clearVersion(); }
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
    $("load").hidden = state === "loading";
    $("save-box").hidden = state !== "result";
    const headings = { upload: "개발요청서 분석", loading: "개발요청서 분석", result: "개발요청서", edit: "개발요청서 수정", manual: "개발요청서 직접 작성" };
    $("title").textContent = headings[state];
    $("description").textContent = state === "upload" || state === "loading" ? "바이어 요청서를 변환하거나 직접 작성하여 개발팀에 전달해요." :
      editing() ? "필수 항목을 입력하고 개발팀에 전달할 요청서를 완성해요." : "내용을 확인하고 필요하면 수정한 뒤 PDF로 저장해요.";
    if (state === "upload" || state === "loading") return;
    const data = current();
    $("fields").innerHTML = sections.map(([title, fields], index) => '<section class="requisition-section" id="requisition-section-' + index + '" role="tabpanel" aria-labelledby="requisition-section-tab-' + index + '" tabindex="0"><h2 class="card-title">' + escape(title) + '</h2><div class="requisition-fields">' + visibleFields(data, fields).map(([key]) => field(key)).join("") + '</div>' + emptyFieldsNote(data, fields) + '</section>').join("");
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
    const gaps = state === "edit" ? RequisitionPayload.carryoverGaps(saved, data) : [];   // 임시 기준: 수정 시작 시점 문서
    $("carryover-wrap").hidden = !gaps.length;
    $("carryover").textContent = gaps.join(", ");
    renderVersion();
    // 누르면 해당 항목으로 이동합니다. 탭에는 항목별 건수를 표시합니다.
    $("review").innerHTML = checks.length ? checks.length + "건 · " + checks.map((label) => '<button type="button" class="requisition-review-link" data-review="' + escape(label) + '">' + escape(label) + "</button>").join("") : "없음";
    sections.forEach(([, fields], index) => {
      const count = fields.filter(([, label]) => checks.includes(label)).length, tab = $("section-tab-" + index);
      let badge = tab.querySelector(".requisition-tab-count");
      if (!count) { if (badge) badge.remove(); return; }
      if (!badge) { badge = document.createElement("span"); badge.className = "requisition-tab-count"; tab.append(badge); }
      badge.textContent = count;
      badge.setAttribute("aria-label", "확인 필요 " + count + "건");
    });
    data.review_status = required.length || checks.length || data.export_countries.length ? "needs_review" : "complete";
  }
  $("review").addEventListener("click", (event) => {
    const link = event.target.closest("[data-review]");
    if (!link) return;
    const index = sections.findIndex(([, fields]) => fields.some(([, label]) => label === link.dataset.review));
    const key = sections[index][1].find(([, label]) => label === link.dataset.review)[0];
    selectSection(index);
    $("field-" + key).scrollIntoView({ block: "center", behavior: "instant" });
    const control = $("field-" + key).querySelector("input:not([type=hidden]),select,textarea");
    if (control) control.focus({ preventScroll: true });
  });
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
      (!printable && file.data_url ? '<a download="' + escape(file.name) + '" href="' + escape(file.data_url) + '">다운로드</a>' : '') +
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
    if (editing() && el.dataset.textureTag !== undefined) {
      const checked = new Set(draft.product_development.texture_tags);
      if (el.checked) checked.add(el.dataset.textureTag); else checked.delete(el.dataset.textureTag);
      draft.product_development.texture_tags = options.texture_tags.filter((tag) => checked.has(tag));
      markEdited("product_development.texture_tags");
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
        versionDirty = true;
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
      const savedNo = currentVersion && !versionDirty ? currentVersion.version_no : null;   // 저장한 내용 그대로일 때만 버전 표시
      const filename = "DevelopmentRequest_" + safePart(data.customer) + "_" + safePart(data.product_name) + "_" + datePart + (savedNo ? "_v" + savedNo : "");
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
          '<td><table class="meta">' + printMeta("Version", savedNo ? "v" + savedNo : "저장 전 (서버 버전 없음)") + printMeta("Date", issuedDate) +
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
        '<div class="doc-footer">' + escape(company.name) + ' &middot; Development Request &middot; ' + (savedNo ? "v" + savedNo : "저장 전 문서") + ' &middot; ' + issuedDate + '</div>';
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
    const stored = currentVersion && !versionDirty && !originalFile && state === "result";   // 저장본과 같은 내용이면 잃을 것이 없음
    if (!stored && (saved || editing() || state === "loading" || originalFile)) { event.preventDefault(); event.returnValue = ""; }
  });
  /* 저장·불러오기·최종본 — 공통 저장 API (docs/api_contract.md 2장). 저장은 항상 새 버전이고 번호는 서버가 정합니다. */
  const REQUISITION_SCHEMA = RequisitionPayload.schemaVersion;
  const versionsUrl = (projectId) => "/api/projects/" + projectId + "/tabs/requisition/versions";
  const finalUrl = (projectId) => "/api/projects/" + projectId + "/tabs/requisition/final";
  const selectedProject = () => project || (window.ProjectBar ? ProjectBar.current() : null);
  const isCurrentFinal = () => Boolean(currentVersion && finalState && finalState.version && finalState.version.id === currentVersion.id);
  function clearVersion() {
    currentVersion = null; versionDirty = false; documentTitle = ""; finalState = null;
    $("version-title").value = "";
    versionFeedback();
  }
  function versionFeedback(message = "") {
    $("version-feedback").textContent = message;
    $("version-feedback").hidden = !message;
  }
  function renderVersion() {
    const isFinal = isCurrentFinal();
    $("save-status").textContent = currentVersion ? "v" + currentVersion.version_no + (isFinal ? " ★ 최종본" : "") + (versionDirty ? " · 이후 수정됨" : "") : "저장 전";
    $("save-help").textContent = !currentVersion ? "저장하면 프로젝트에 새 버전으로 남아요. 원본 파일과 참고자료 본문은 저장되지 않아요."
      : versionDirty ? "수정한 내용은 아직 저장되지 않았어요. 저장하면 새 버전으로 남아요." : "저장한 버전과 같은 내용이에요. 연구소 개발 차수는 저장으로 바뀌지 않아요.";
    if (state !== "result") return;
    if (document.activeElement !== $("version-title") && !$("version-title").value) $("version-title").value = documentTitle || saved.product_name || "";
    const unchanged = currentVersion && !versionDirty && $("version-title").value.trim() === (currentVersion.title || "");
    $("version-save").disabled = versionBusy || Boolean(unchanged);
    $("version-final").hidden = !currentVersion;
    $("version-final").disabled = versionBusy || versionDirty;
    $("version-final").textContent = isFinal ? "최종본 해제" : "최종본으로 지정";
  }
  // 응답이 늦게 도착해도 지금 문서의 프로젝트가 아니면 버립니다.
  async function refreshFinal() {
    const target = documentProject;
    if (!target) return false;
    const result = await Common.api("GET", finalUrl(target.id));
    if (target !== documentProject) return false;
    if (!result.ok) { versionFeedback(result.error.message); return false; }
    finalState = result.data.final;
    renderVersion();
    return true;
  }
  async function saveVersion() {
    if (state !== "result" || versionBusy) return;
    const title = $("version-title").value.trim();
    if (!title) { $("version-title").focus(); return versionFeedback("문서 이름을 입력해 주세요."); }
    const built = RequisitionPayload.build(saved, documentProject, options);
    if (built.error) return versionFeedback(built.error + " 위에서 프로젝트를 선택해 주세요.");
    versionBusy = true;
    versionFeedback("저장하고 있어요…");
    renderVersion();
    const target = documentProject;
    const result = await Common.api("POST", versionsUrl(target.id), {
      schema_version: built.schema_version, title, based_on_id: currentVersion ? currentVersion.id : null, payload: built.payload,
    });
    versionBusy = false;
    if (target !== documentProject) return;
    if (!result.ok) { versionFeedback("저장하지 못했어요. " + result.error.message); return renderVersion(); }
    currentVersion = result.data.version;
    versionDirty = false;
    documentTitle = title;
    const base = result.data.base || {};
    versionFeedback("v" + currentVersion.version_no + "로 저장했어요." + (base.is_stale
      ? " v" + base.based_on_version_no + "에서 시작했는데 그사이 v" + base.latest_version_no_before_save + "까지 저장돼 있었어요. 다른 버전의 내용을 확인해 주세요." : ""));
    renderVersion();
    await refreshFinal();
  }
  async function toggleFinal() {
    if (!currentVersion || versionBusy || versionDirty) return;
    versionBusy = true;
    renderVersion();
    const target = documentProject;
    const ready = finalState || await refreshFinal();
    let result = null;
    if (ready && target === documentProject) {
      const expected = finalState.final_history_id ?? null;
      result = await Common.api("POST", finalUrl(target.id), isCurrentFinal()
        ? { action: "unset", expected_final_history_id: expected }
        : { action: "set", version_id: currentVersion.id, expected_final_history_id: expected });
    }
    versionBusy = false;
    if (target !== documentProject) return;
    if (result && result.ok) {
      finalState = result.data.final;
      versionFeedback(isCurrentFinal() ? "최종본으로 지정했어요." : "최종본을 해제했어요.");
    } else if (result && result.status === 409) {
      finalState = result.error.current;                    // 입력은 그대로 두고 바뀐 상태만 보여 줍니다.
      versionFeedback("다른 사용자가 먼저 최종본을 바꿨어요. 현재 상태를 확인하고 다시 선택해 주세요.");
    } else if (result) versionFeedback("최종본을 변경하지 못했어요. " + result.error.message);
    renderVersion();
  }
  let loadTarget = null, loadBefore = null, loadRows = [], loadFinalId = null;
  function renderLoadList() {
    const checked = document.querySelector('input[name="requisition-load-version"]:checked');
    const selected = checked ? Number(checked.value) : loadFinalId || (loadRows[0] && loadRows[0].id);
    $("load-list").innerHTML = loadRows.map((item) => '<label class="requisition-load-item"><input type="radio" name="requisition-load-version" value="' + item.id + '"' + (item.id === selected ? " checked" : "") + '><span><strong>v' + item.version_no + (item.is_final ? " ★ 최종본" : "") + " · " + escape(item.title || "이름 없음") + "</strong><small>" +
      escape((item.created_by && item.created_by.name) || "") + " · " + escape(new Date(item.created_at).toLocaleString("ko-KR")) + "</small></span></label>").join("");
    $("load-more").hidden = !loadBefore;
    $("load-confirm").disabled = !loadRows.length;
  }
  async function fetchLoadPage() {
    const target = loadTarget;
    const result = await Common.api("GET", versionsUrl(target.id) + "?limit=50" + (loadBefore ? "&before=" + loadBefore : ""));
    if (target !== loadTarget) return;
    if (!result.ok) { $("load-status").textContent = result.error.message; return; }
    loadRows = loadRows.concat(result.data.items);
    loadBefore = result.data.next_before;
    const final = loadRows.find((item) => item.is_final);
    loadFinalId = final ? final.id : null;
    $("load-status").textContent = loadRows.length ? "‘" + projectLabel(target) + "’의 저장본이에요. 원본 파일과 참고 이미지는 복원되지 않아요." : "이 프로젝트에 저장된 요청서가 없어요.";
    renderLoadList();
  }
  function openLoad() {
    notice();
    const target = selectedProject();
    if (!target) return notice("저장본을 불러오려면 먼저 프로젝트를 선택해 주세요.");
    loadTarget = target; loadBefore = null; loadRows = []; loadFinalId = null;
    $("load-list").innerHTML = "";
    $("load-more").hidden = true;
    $("load-confirm").disabled = true;
    $("load-status").textContent = "저장본 목록을 불러오고 있어요…";
    Common.openModal("requisition-load-modal");
    fetchLoadPage();
  }
  async function confirmLoad() {
    const checked = document.querySelector('input[name="requisition-load-version"]:checked');
    if (!checked || !loadTarget) return;
    const target = loadTarget;
    const safe = !hasDocument() || (state === "result" && currentVersion && !versionDirty && !originalFile);
    if (!safe && !confirm("지금 작성 중인 내용이 불러온 저장본으로 바뀌어요. 계속할까요?")) return;
    $("load-confirm").disabled = true;
    const result = await Common.api("GET", "/api/versions/" + Number(checked.value));
    if (target !== loadTarget) return;
    if (!result.ok || result.data.version.schema_version !== REQUISITION_SCHEMA || result.data.version.tab !== "requisition" || result.data.version.project_id !== target.id) {
      $("load-confirm").disabled = false;
      $("load-status").textContent = result.ok ? "이 저장본은 현재 화면에서 불러올 수 없어요." : result.error.message;
      return;
    }
    const version = result.data.version;
    saved = RequisitionPayload.restore(version.payload, options);
    saved.customer = target.customer.name;
    draft = originalFile = null;
    documentProject = target;
    currentVersion = version;
    versionDirty = false;
    documentTitle = version.title || "";
    finalState = null;
    activeSection = 0;
    $("file").value = "";
    $("version-title").value = documentTitle;
    Common.closeModal("requisition-load-modal");
    transition("result");
    versionFeedback("v" + version.version_no + "을 불러왔어요." + (saved.reference_files.length || saved.source_file ? " 원본 파일과 참고자료 본문은 저장되지 않아 복원되지 않아요. 필요하면 수정에서 다시 첨부해 주세요." : ""));
    await refreshFinal();
  }
  document.body.append($("load-modal"));   // 페이지 container 밖에 두어 fixed 위치를 유지합니다.
  $("load").addEventListener("click", openLoad);
  $("load-more").addEventListener("click", fetchLoadPage);
  $("load-confirm").addEventListener("click", confirmLoad);
  $("version-save").addEventListener("click", saveVersion);
  $("version-final").addEventListener("click", toggleFinal);
  $("version-title").addEventListener("input", renderVersion);
  $("version-title").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); saveVersion(); }   // 양식 제출(PDF 인쇄)이 되지 않게
  });
  /* 프로젝트 연결 — 선택 UI 는 공통 프로젝트 바(common/project_bar.js)가 맡고, 여기서는 요청서 보호 규칙만 처리합니다. */
  const idOf = (item) => item ? item.id : null;
  function projectLabel(item) { return item.customer.name + " › " + item.name; }
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
  function applyProject(next) {
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
    syncSettingCustomer();
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
  if (window.ProjectBar) {
    ProjectBar.setGuard(projectChangeAllowed);
    ProjectBar.onChange(applyProject);
  }
  // 저장용 payload (계약 v1) — 저장 버튼과 테스트에서 씁니다.
  // 화면에서 지금 고른 프로젝트가 아니라 요청서의 연결 프로젝트(documentProject)로 만듭니다.
  root.buildRequisitionPayload = () => RequisitionPayload.build(current(), documentProject, options);
  render();
})();
