/* ==========================================================================
   공통 프로젝트 선택 바 (고객사 / 프로젝트) — API: docs/api_contract.md 5장
   선택값은 같은 브라우저 탭 안에서 페이지를 옮겨도 유지됩니다 (sessionStorage).

   페이지 JS에서 사용:
     ProjectBar.current()         지금 고른 프로젝트 (없으면 null)
     ProjectBar.onChange(fn)      선택이 바뀌면 fn(project | null) 호출
     ProjectBar.setGuard(fn)      바꾸기 전에 fn(next | null) 확인. false 면 취소
   ========================================================================== */
(function () {
  "use strict";
  const barElement = document.getElementById("project-bar");
  if (!barElement) return;
  // 탭 담당자 템플릿을 고치지 않도록, base.html 이 그린 바를 각 탭의 제목 영역 바로 아래로 옮깁니다.
  const pageHeader = document.querySelector(".container .page-header");
  if (pageHeader) pageHeader.after(barElement);

  const STORAGE_KEY = "cosmoa.project";
  const stageNames = { proposal: "제안", development: "개발", order: "발주", production: "생산", shipping: "선적", completed: "완료" };
  const stateNames = { active: "진행", hold: "홀드", drop: "드롭" };
  const $ = (id) => document.getElementById("project-bar-" + id);
  const MORE = "more";

  let project = null, customer = null, customers = [], projects = [], projectNext = null;
  let customerRequest = 0, projectRequest = 0, searchTimer = null, creating = "project";
  let guard = () => true;
  const listeners = [];

  function apiMessage(result) {
    if (result.status === 401) return "로그인이 만료됐어요. 페이지를 새로 고친 뒤 다시 로그인해 주세요.";
    return (result.error && result.error.message) || "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
  }
  function showError(el, message) {
    el.textContent = message || "";
    el.hidden = !message;
  }
  const barError = (message) => showError($("error"), message);
  function modalError(message, focus) {
    showError($("modal-error"), message);
    if (focus) focus.focus();
  }

  function commit(next) {
    project = next;
    try { next ? sessionStorage.setItem(STORAGE_KEY, String(next.id)) : sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* 저장 불가 환경 무시 */ }
    $("project").title = next ? next.customer.name + " / " + next.name : "";
    listeners.forEach((fn) => fn(next));
  }

  // 같은 이름의 고객사가 있을 수 있어 그때만 id 를 붙여 구분합니다.
  function customerText(item) {
    return customers.some((other) => other.id !== item.id && other.name === item.name) ? item.name + " (#" + item.id + ")" : item.name;
  }
  function renderCustomers() {
    const list = $("customers");
    list.textContent = "";
    customers.forEach((item) => {
      const option = document.createElement("option");
      option.value = customerText(item);
      list.appendChild(option);
    });
  }
  function showCustomer() { $("customer").value = customer ? customerText(customer) : ""; }

  function renderProjects() {
    const el = $("project");
    el.disabled = !customer;
    $("project-new").disabled = !customer;
    el.textContent = "";
    el.add(new Option(!customer ? "먼저 고객사를 선택하세요" : projects.length ? "프로젝트를 선택하세요" : "프로젝트가 없어요 · 새 프로젝트를 만들어 주세요", ""));
    projects.forEach((item) => el.add(new Option(
      item.name + " · " + (stageNames[item.stage] || item.stage) + "/" + (stateNames[item.state] || item.state) + (item.due_date ? " · 납기 " + item.due_date : ""), String(item.id))));
    if (projectNext) el.add(new Option("프로젝트 더 보기…", MORE));
    el.value = project ? String(project.id) : "";
  }

  async function loadCustomers(query) {
    const request = ++customerRequest;
    const result = await Common.api("GET", "/api/customers?limit=100" + (query ? "&q=" + encodeURIComponent(query) : ""));
    if (request !== customerRequest) return;   // 그 사이 검색어가 바뀜
    if (!result.ok) return barError(apiMessage(result));
    customers = result.data.items;
    renderCustomers();
  }
  async function loadProjects(append) {
    const request = ++projectRequest, customerId = customer ? customer.id : null;
    if (!append) { projects = []; projectNext = null; }
    renderProjects();
    if (!customerId) return;
    const result = await Common.api("GET", "/api/customers/" + customerId + "/projects?limit=100" + (append && projectNext ? "&before=" + projectNext : ""));
    if (request !== projectRequest) return;   // 그 사이 다른 고객사를 고름
    if (!result.ok) return barError(apiMessage(result));
    projects = append ? projects.concat(result.data.items) : result.data.items;
    projectNext = result.data.next_before;
    if (project && project.customer.id === customerId && !projects.some((item) => item.id === project.id)) projects.unshift(project);
    renderProjects();
  }

  async function selectCustomer(next, confirmed) {
    barError("");
    if ((next ? next.id : null) === (customer ? customer.id : null)) { showCustomer(); return true; }
    if (project && !confirmed && !guard(null)) { showCustomer(); return false; }
    customer = next;
    showCustomer();
    if (project) commit(null);
    await loadProjects(false);
    return true;
  }
  function matchCustomer(text) {
    const exact = customers.find((item) => customerText(item) === text);
    if (exact) return exact;
    const same = customers.filter((item) => item.name.toLocaleLowerCase() === text.toLocaleLowerCase());
    return same.length === 1 ? same[0] : null;
  }

  // 입력 칸 하나로 검색과 선택을 합니다. 타이핑은 목록만 좁히고, 목록에서 고르거나 칸을 벗어날 때 확정합니다.
  $("customer").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    const text = event.target.value.trim();
    const picked = !event.inputType || event.inputType === "insertReplacementText";
    const match = picked && customers.find((item) => customerText(item) === text);
    if (match) { selectCustomer(match); return; }
    searchTimer = setTimeout(() => loadCustomers(text), 250);
  });
  $("customer").addEventListener("change", async (event) => {
    clearTimeout(searchTimer);
    const text = event.target.value.trim();
    if (!text) await selectCustomer(null);
    else {
      const match = matchCustomer(text);
      if (match) await selectCustomer(match);
      else showCustomer();   // 목록에 없는 이름은 확정하지 않고 되돌립니다.
    }
    loadCustomers("");
  });
  $("customer").addEventListener("focus", (event) => event.target.select());

  $("project").addEventListener("change", (event) => {
    barError("");
    if (event.target.value === MORE) { event.target.value = project ? String(project.id) : ""; loadProjects(true); return; }
    const next = projects.find((item) => item.id === Number(event.target.value)) || null;
    if (!guard(next)) { renderProjects(); return; }
    commit(next);
  });

  function openCreate(kind) {
    creating = kind;
    const isProject = kind === "project";
    $("modal-title").textContent = isProject ? "새 프로젝트" : "새 고객사";
    $("name-label").textContent = isProject ? "프로젝트(제품)명 *" : "고객사명 *";
    $("due-group").hidden = !isProject;
    $("name").value = $("due").value = "";
    modalError("");
    Common.openModal("project-bar-modal");
    $("name").focus();
  }
  async function saveCustomer(name) {
    const found = await Common.api("GET", "/api/customers?limit=100&q=" + encodeURIComponent(name));
    const same = found.ok && found.data.items.find((item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase());
    if (same && !confirm("같은 이름의 고객사 ‘" + same.name + "’가 이미 있어요. 그래도 새로 만들까요?")) return;
    if (project && !guard(null)) return;
    const result = await Common.api("POST", "/api/customers", { name });
    if (!result.ok) return modalError(apiMessage(result), $("name"));
    Common.closeModal("project-bar-modal");
    await loadCustomers("");
    await selectCustomer(result.data.customer, true);
    openCreate("project");   // 새 고객사에는 프로젝트가 없으므로 바로 만들 수 있게
  }
  async function saveProject(name) {
    if (!guard({ id: -1, name, customer })) return;
    const result = await Common.api("POST", "/api/customers/" + customer.id + "/projects", { name, due_date: $("due").value || null });
    if (!result.ok) return modalError(apiMessage(result), $("name"));
    Common.closeModal("project-bar-modal");
    commit(result.data.project);
    await loadProjects(false);
  }
  async function save() {
    const button = $("save");
    if (button.disabled) return;
    modalError("");
    const name = $("name").value.trim();
    if (!name) return modalError(creating === "project" ? "프로젝트(제품)명을 입력해 주세요." : "고객사명을 입력해 주세요.", $("name"));
    button.disabled = true;
    try { await (creating === "project" ? saveProject(name) : saveCustomer(name)); } finally { button.disabled = false; }
  }
  $("customer-new").addEventListener("click", () => openCreate("customer"));
  $("project-new").addEventListener("click", () => openCreate("project"));
  $("save").addEventListener("click", save);
  $("modal").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing && event.target.tagName === "INPUT") { event.preventDefault(); save(); }
  });

  async function init() {
    let stored = null;
    try { stored = Number(sessionStorage.getItem(STORAGE_KEY)) || null; } catch (e) { /* 저장 불가 환경 무시 */ }
    if (stored) {   // 페이지를 옮기거나 새로 고친 뒤 고른 프로젝트를 다시 확인 (없어졌거나 보관됐으면 선택 해제)
      const result = await Common.api("GET", "/api/projects/" + stored);
      if (result.ok && !result.data.project.archived) {
        customer = result.data.project.customer;
        commit(result.data.project);
      } else if (result.ok || result.status === 404) commit(null);
      else barError(apiMessage(result));
    }
    showCustomer();
    await Promise.all([loadCustomers(""), loadProjects(false)]);
    showCustomer();   // 동명 고객사 표시 반영
  }

  window.ProjectBar = {
    current: () => project,
    onChange: (fn) => { listeners.push(fn); },
    setGuard: (fn) => { guard = fn; },
  };
  init();
})();
