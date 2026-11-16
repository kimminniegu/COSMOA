/* 배합 계산 및 Canvas 시연. 공통 UI와 전역 이름을 공유하지 않습니다. */
(() => {
'use strict';

const $ = id => document.getElementById('simulation-' + id);
const fmt = n => n.toLocaleString('ko-KR');
const theme = getComputedStyle(document.documentElement);
const token = name => theme.getPropertyValue(name).trim();

// 도움말은 한 번에 하나만 표시. 마우스, 키보드, 터치에서 같은 설명을 제공합니다.
let activeHelp = null;
let helpTimer;
function closeHelp() {
  clearTimeout(helpTimer);
  if (!activeHelp) return;
  activeHelp.panel.hidden = true;
  activeHelp.button.setAttribute('aria-expanded', 'false');
  activeHelp = null;
}
function openHelp(button) {
  clearTimeout(helpTimer);
  if (activeHelp?.button === button) return;
  closeHelp();
  const panel = document.getElementById(button.dataset.simulationHelp);
  panel.hidden = false;
  button.setAttribute('aria-expanded', 'true');
  activeHelp = { button, panel };
  // body에 두어 공통 container의 transform/contain 영향을 피합니다.
  document.body.append(panel);
  const rect = button.getBoundingClientRect();
  const bounds = panel.getBoundingClientRect();
  const left = Math.max(12, Math.min(rect.left, innerWidth - bounds.width - 12));
  const below = rect.bottom + 8;
  const top = below + bounds.height < innerHeight - 12 ? below : Math.max(12, rect.top - bounds.height - 8);
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
}
document.querySelectorAll('[data-simulation-help]').forEach(button => {
  const panel = document.getElementById(button.dataset.simulationHelp);
  button.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') openHelp(button); });
  button.addEventListener('pointerleave', () => { helpTimer = setTimeout(closeHelp, 180); });
  button.addEventListener('focus', () => openHelp(button));
  button.addEventListener('click', () => openHelp(button));
  button.addEventListener('blur', closeHelp);
  panel.addEventListener('pointerenter', () => clearTimeout(helpTimer));
  panel.addEventListener('pointerleave', closeHelp);
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeHelp(); });
document.addEventListener('pointerdown', event => {
  if (activeHelp && !activeHelp.button.contains(event.target) && !activeHelp.panel.contains(event.target)) closeHelp();
});
window.addEventListener('resize', closeHelp);
// 슬라이더 트랙을 기기 픽셀 정수로 맞춰, 125%·150% 배율에서도 네 트랙이 같은 굵기로 그려지게 합니다.
function snapSliderTrack() {
  const dpr = window.devicePixelRatio || 1;
  document.querySelector('.simulation-sliders').style.setProperty('--simulation-track', Math.max(1, Math.round(3 * dpr)) / dpr + 'px');
}
window.addEventListener('resize', snapSliderTrack);
snapSliderTrack();
window.addEventListener('scroll', closeHelp, true);

const PRESETS = {
  serum: { name: '세럼', a: 2.0, c: 0.20, o: 5, h: 8, pack: 'dropper' },
  ampoule: { name: '고농축 앰플', a: 3.0, c: 0.35, o: 8, h: 10, pack: 'dropper' },
  lotion: { name: '로션', a: 1.0, c: 0.45, o: 18, h: 8, pack: 'pump' },
  cream: { name: '영양 크림', a: 2.0, c: 0.80, o: 28, h: 10, pack: 'jar' }
};

// min~max 적합, low~high 주의, 그 밖은 부적합. ideal은 적합 구간 안에서 만점에 가까운 점도입니다.
const PACKS = {
  dropper: { name: '스포이드 (Dropper Pipette)', min: 500, max: 5000, low: 100, high: 8500, ideal: 2500, detail: '저·중점도 제형 (흡입/드롭 토출 제어)' },
  onetouch: { name: '원터치 디스펜서 보틀 (One-Touch Dispenser)', min: 50, max: 1500, low: 10, high: 4000, ideal: 470, detail: '극저·저점도 제형 (원터치 캡 토출)' },
  mist: { name: '파인 미스트 스프레이 (Fine Mist Spray)', min: 1, max: 300, low: 0, high: 800, ideal: 39, detail: '극저점도 제형 (미세 분사)' },
  pump: { name: '디스펜서 펌프 (Standard Dispenser Pump)', min: 800, max: 18000, low: 200, high: 28000, ideal: 5000, detail: '저·중점도 제형 (일반 펌핑)' },
  airless: { name: '에어리스 펌프 (Airless Pump)', min: 2000, max: 60000, low: 500, high: 80000, ideal: 15000, detail: '중·고점도 제형 (산화 방지 진공 토출)' },
  jar: { name: '크림 자 (Cream Jar)', min: 18000, max: Infinity, low: 9000, high: Infinity, ideal: 45000, detail: '고점도 제형 (단지형 용기)' }
};

const STATES = {
  excellent: { label: '적합 범위', color: 'var(--color-success)' },
  optimal: { label: '적합 범위', color: 'var(--color-primary)' },
  caution: { label: '주의', color: 'var(--color-warning)' },
  incompatible: { label: '부적합', color: 'var(--color-danger)' }
};

let current = null;
let appliedBrief = null; // 드롭다운의 '개발요청서' 항목이 가리키는 의뢰서
let briefLocked = false; // true면 의뢰서 분석값을 표시 (사용자가 조정하면 false)
let roll = null; // 적용 직후 표시값 롤링: { from: { v, flow, score }, t }
let shown = null; // 직전에 표시한 수치
let paused = matchMedia('(prefers-reduced-motion: reduce)').matches;

// 네 가지 배합비에 따른 기본 예측 점도식
function calculateViscosity(a, c, o, h) {
  return Math.round(80 + Math.pow(c * 10, 2.3) * 260 + o * o * 22 + h * 18 + a * 45);
}

// 4. 용기 적합도 평가 및 점수 산출
function evaluatePackage(v, key) {
  const p = PACKS[key];
  if (v >= p.min && v <= p.max) return 'optimal';
  if (v >= p.low && v <= p.high) return 'caution';
  return 'incompatible';
}

function calculateScore(v, key, state) {
  const p = PACKS[key];
  // 적합: 용기별 이상 점도(ideal)와의 로그 거리만큼 최대 10점 감점 (90~100점)
  if (state === 'optimal') {
    return 100 - Math.min(10, Math.round(Math.abs(Math.log10(Math.max(v, 1) / p.ideal)) * 12));
  }
  // 권장 범위를 벗어난 정도에 따라 결정적으로 감점합니다. (같은 배합은 항상 같은 점수)
  if (state === 'caution') {
    const t = v < p.min ? (p.min - v) / (p.min - p.low) : (v - p.max) / (p.high - p.max);
    return 75 - Math.round(Math.min(1, t) * 10);
  }
  const ratio = v < p.low ? p.low / v : v / p.high;
  return Math.max(5, Math.round(40 - 9 * Math.log2(ratio)));
}

function getEligiblePacks(v) {
  return Object.keys(PACKS).filter(key => evaluatePackage(v, key) === 'optimal');
}

function textureLabel(v) {
  return v < 2500 ? '묽은 워터리' : v < 9000 ? '산뜻한 점성' : v < 25000 ? '농축 리치' : '고밀도 밤(Balm)';
}

function packDiagnosis(v, key, state) {
  const packName = PACKS[key].name.split(' (')[0];
  return state === 'optimal'
    ? `${fmt(v)} cPs · ${packName}의 권장 점도 범위입니다. 실제 토출량과 안정성 시험으로 최종 확인하세요.`
    : v < PACKS[key].min
      ? `저점도 제형(${fmt(v)} cPs)으로 ${packName} 사용 시 누액·비산 가능성이 있습니다.`
      : `고점도 제형(${fmt(v)} cPs)으로 ${packName} 사용 시 흡입 불량·토출 저항 및 노즐 막힘 위험이 있습니다.`;
}

function packRisk(v, key, state) {
  return state === 'optimal'
    ? '예측 점도 기준 적합 범위 확인'
    : v < PACKS[key].min ? '저점도로 인한 누액·비산 가능성 확인' : '흡입 불량·토출 저항 및 노즐 막힘 가능성 확인';
}

// 추천 용기 버튼 UI 생성
const PACK_ICONS = {
  dropper: 'M8 3h4v5l2 3v6H6v-6l2-3z',
  onetouch: 'M7 3h6v3H7z M6 6h8v11H6z M9 3v-1h2v1',
  mist: 'M7 9h6v8H7z M9 9V6h2v3 M13 5.5h3 M13.5 3.5l2-1 M13.5 7.5l2 1',
  pump: 'M6 8h8v9H6z M10 8V3h6 M8 3h5',
  airless: 'M6 6h8v11H6z M8 6V3h4v3 M6 13h8',
  jar: 'M4 7h12v9H4z M3 4h14v3H3z'
};
const recommendationButtons = {};
for (const [key, p] of Object.entries(PACKS)) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn btn-secondary btn-sm simulation-pack-option';

  const group = document.createElement('span');
  const name = document.createElement('strong');
  const detail = document.createElement('small');
  const action = document.createElement('span');

  name.textContent = p.name.split(' (')[0];
  detail.textContent = p.detail;

  group.append(name, detail);
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 20 20');
  icon.setAttribute('aria-hidden', 'true');
  const outline = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  outline.setAttribute('d', PACK_ICONS[key]);
  icon.append(outline);
  button.append(icon, group, action);

  button.addEventListener('click', () => { testPack(key); markDirty(); });

  $('recommendations').append(button);
  recommendationButtons[key] = { button, action, detail };
}

const emptyMsg = document.createElement('p');
emptyMsg.className = 'text-caption';
emptyMsg.textContent = '적합 범위의 용기가 없습니다. 배합과 용기 사양을 함께 조정하세요.';
$('recommendations').append(emptyMsg);

// 동일한 배합·용기·점수로 연구소와 바이어용 리포트를 함께 생성합니다.
function generateReports(v, key, state, score, brief) {
  const name = PACKS[key].name.split(' (')[0];
  const names = (brief ? brief.recs : getEligiblePacks(v)).filter(candidate => candidate !== key).map(candidate => PACKS[candidate].name.split(' (')[0]).join(' 또는 ');
  const risk = brief ? brief.risk : packRisk(v, key, state);
  const report = `점도 ${fmt(v)} cPs · ${name}: ${risk} (호환도 ${score}점).`;
  const action = state === 'optimal'
    ? '현 용기 유지 후 실제 토출량·안정성 시험 권장.'
    : names ? `${names}로 패키징 변경 권장.` : '배합 점도와 용기 사양의 동시 재검토 권장.';
  const sales = state === 'optimal'
    ? `현재 제형의 예측 물성 기준으로 ${name} 적용을 검토해 볼 수 있습니다. 사용감과 토출 성능을 함께 고려한 구성을 제안드리며, 연구소 실측과 시험 후 확정됩니다.`
    : names ? `현재 배합의 사용감을 살리기 위해 ${names} 적용을 검토해 볼 수 있습니다. 용기 적합 여부는 연구소 실측과 시험 후 확정됩니다.`
    : '목표 사용감에 맞춘 배합과 전용 용기 사양을 함께 조정하는 방향을 검토해 볼 수 있습니다.';
  // 영문본: 해외 바이어·연구소 해외 담당에게 바로 붙여 넣을 수 있는 같은 내용
  const en = candidate => (PACKS[candidate].name.match(/\((.+)\)/) || [])[1] || PACKS[candidate].name;
  const nameEn = en(key);
  const namesEn = (brief ? brief.recs : getEligiblePacks(v)).filter(candidate => candidate !== key).map(en).join(' or ');
  const riskEn = state === 'optimal' ? 'predicted viscosity is within the suitable range'
    : v < PACKS[key].min ? 'low viscosity may cause leakage or splashing' : 'poor suction, dispensing resistance or nozzle clogging may occur';
  const enReport = `Viscosity ${fmt(v)} cPs · ${nameEn}: ${riskEn} (compatibility score ${score}).`;
  const enAction = state === 'optimal'
    ? 'Keep the current container and confirm dispensing volume and stability through lab testing.'
    : namesEn ? `Consider switching the packaging to ${namesEn}.` : 'Review the formula viscosity and the container specification together.';
  const enSales = state === 'optimal'
    ? `Based on the predicted properties of the current formula, ${nameEn} can be considered. We propose a configuration that balances skin feel and dispensing performance; final suitability will be confirmed through lab measurement and testing.`
    : namesEn ? `To preserve the intended skin feel, ${namesEn} can be considered. Container suitability will be confirmed through lab measurement and testing.`
    : 'We suggest reviewing the formula and a dedicated container specification together to match the target skin feel.';
  return { report, action, sales, en: { report: enReport, action: enAction, sales: enSales } };
}

// 바이어 제안 가이드 표시 언어 (ko / en)
let pitchLang = 'ko';
let lastReports = null;
const PITCH_TEXT = {
  ko: { rd: 'R&D 연구소 리포트', sales: '바이어 세일즈 피칭' },
  en: { rd: 'R&D Lab Report', sales: 'Buyer Sales Pitch' }
};
function renderPitch() {
  if (!lastReports) return;
  const r = pitchLang === 'en' ? lastReports.en : lastReports;
  $('rd-report').textContent = r.report;
  $('rd-action').textContent = r.action;
  $('pitch-script').textContent = r.sales;
  $('rd-title').textContent = PITCH_TEXT[pitchLang].rd;
  $('sales-title').textContent = PITCH_TEXT[pitchLang].sales;
  $('rd-report').lang = $('rd-action').lang = $('pitch-script').lang = pitchLang;
}

// 현재 슬라이더·용기·의뢰서 스펙으로 계산한 상태 (애니메이션 중간값이 아닌 최종값). 화면 표시와 저장이 함께 씁니다.
function computeState() {
  const a = +$('active').value;
  const c = +$('carb').value;
  const o = +$('oil').value;
  const h = +$('hum').value;
  const key = $('pack').value;
  // spec: 의뢰서 배합이 유지되는 동안의 분석값, brief: 요청 용기까지 같을 때의 분석 결과
  const spec = briefLocked && appliedBrief ? appliedBrief.result : null;
  const brief = spec && key === appliedBrief.pack ? spec : null;
  const v = spec ? spec.v : calculateViscosity(a, c, o, h);
  const liveState = evaluatePackage(v, key);
  const liveScore = calculateScore(v, key, liveState);
  const tone = brief ? brief.tone : liveState === 'optimal' && liveScore >= 95 ? 'excellent' : liveState;
  const water = Math.max(0, 100 - a - c - o - h);
  return {
    a, c, o, h, key, spec, brief, v, tone, water,
    state: tone === 'excellent' ? 'optimal' : tone,
    score: brief ? brief.score : liveScore,
    flow: spec ? spec.flow : Math.round(100 / (1 + v / 6500)),
    stated: Boolean(spec && appliedBrief.viscosityStated),
    stability: water < 45 || (o >= 20 && c < 0.2) ? 'unstable' : water < 60 || (o >= 12 && c < 0.2) ? 'review' : 'stable',
    texture: spec ? spec.texture : textureLabel(v),
    label: brief ? brief.label : STATES[tone].label
  };
}

// 종합 상태 업데이트
function update() {
  const s = computeState();
  const { a, c, o, h, key, spec, brief, tone, state, water } = s;
  let { v, flow, score } = s;
  if (roll) {
    const mix = (from, to) => from + (to - from) * roll.t;
    v = Math.round(mix(roll.from.v, v));
    flow = Math.round(mix(roll.from.flow, flow));
    score = Math.round(mix(roll.from.score, score));
  }
  shown = { v, flow, score };
  current ={ a, c, o, h, v, state, score, flow, water };
  updateBriefBadge();


  ['active', 'carb', 'oil', 'hum'].forEach(id => {
    const slider = $(id);
    slider.style.setProperty('--simulation-progress', `${(slider.value - slider.min) / (slider.max - slider.min) * 100}%`);
  });

  $('active-out').textContent = a.toFixed(1) + '\%';
  $('carb-out').textContent = c.toFixed(2) + '%';
  $('oil-out').textContent = o.toFixed(0) + '%';$('hum-out').textContent = h.toFixed(0) + '%';

  $('viscosity').textContent = fmt(v);
  $('flow').textContent = flow + ' / 100';
  $('flow-gauge').value = flow;
  const parts = { active: a, carb: c, oil: o, hum: h, water };
  Object.entries(parts).forEach(([id, pct]) => {
    $('formula-' + id).style.flexGrow = pct;
    $('formula-' + id).hidden = pct <= 0;
  });
  $('formula-total').textContent = Object.values(parts).reduce((sum, pct) => sum + pct, 0).toFixed(1) + '%';
  $('formula-bar').setAttribute('aria-label', `유효 ${a}%, 점증제 ${c}%, 오일 ${o}%, 보습 ${h}%, 정제수 ${water.toFixed(2)}%`);
  const { stability } = s;
  $('formula-badge').dataset.state = stability;
  $('formula-badge').textContent = { stable: '안정', review: '검토', unstable: '주의' }[stability];
  $('formula-badge').dataset.en = { stable: 'Stable', review: 'Review', unstable: 'Unstable' }[stability];
  $('lab-flow').textContent = `${flow} / 100`;
  $('lab-cycle').textContent = `${(.9 / (1 + v / 9000) + .08).toFixed(2)} /s`;

  $('texture').textContent = s.texture;
  $('flow-caption').textContent = v < 9000 ? '빠른 유동성 · 얇은 퍼짐성' : v < 25000 ? '완만한 레벨링 · 보습 밀착' : '형태 유지 · 높은 응집력';


  $('status-card').className = 'simulation-status-card';
  const stateLabel = s.label;
  $('status-label').textContent = stateLabel;
  $('status-card').dataset.state = tone;
  $('status-icon').textContent = { excellent: '✓', optimal: '✓', caution: '!', incompatible: '×' }[tone];
  $('status-score').textContent = score;
  $('score-ring').style.setProperty('--simulation-score', `${score}%`);
  $('score-ring').setAttribute('aria-label', `예측 호환도 ${score}점 / 100, ${stateLabel}`);
  $('diagnosis').textContent = brief ? brief.diagnosis : packDiagnosis(v, key, state);

  // 권장 대체 용기 버튼 갱신 (요청 용기 분석 중에는 분석 결과의 권장 용기를 표시)
  const eligible = brief ? brief.recs : getEligiblePacks(v);
  for (const [k, { button, action, detail }] of Object.entries(recommendationButtons)) {
    const spec = PACKS[k];
    const range = Number.isFinite(spec.max) ? `${fmt(spec.min)}–${fmt(spec.max)}` : `${fmt(spec.min)} 이상`;
    detail.textContent = `${range} cPs`;
    button.title = `권장 범위: ${range} cPs. ${spec.detail}`;
    button.hidden = !eligible.includes(k);
    button.style.display = button.hidden ? 'none' : '';
    button.setAttribute('aria-pressed', String(k === key));
    button.className = `btn ${k === key ? 'btn-soft' : 'btn-secondary'} btn-sm simulation-pack-option`;
    action.textContent = k === key ? '선택됨' : '선택 →';
  }
  emptyMsg.hidden = eligible.length > 0;

  // 기술 영업 피칭 가이드 업데이트
  lastReports = generateReports(v, key, state, score, brief);
  renderPitch();
  updateCompat();

  if (paused) drawScene();
}

function loadPreset() {
  const p = $('preset').value === 'brief' ? appliedBrief : PRESETS[$('preset').value];
  briefLocked = $('preset').value === 'brief';
  $('active').value = p.a;
  $('carb').value = p.c;
  $('oil').value = p.o;
  $('hum').value = p.h;
  $('pack').value = p.pack;


  update();
}

$('preset').addEventListener('change', () => { stopBriefAnimation(); loadPreset(); markDirty(); });
$('pack').addEventListener('change', () => { testPack($('pack').value); markDirty(); });

['active', 'carb', 'oil', 'hum'].forEach(id => {
  $(id).addEventListener('input', () => {
    briefLocked = false; // 사용자가 배합을 바꾸면 실시간 계산으로 전환
    update();
    markDirty();
  });
  // 적용 애니메이션 중 사용자가 직접 조작하면 사용자 조작을 우선합니다.
  $(id).addEventListener('pointerdown', stopBriefAnimation);
  $(id).addEventListener('keydown', stopBriefAnimation);
});

// 개발요청서 업로드 및 AI 분석: 파일 업로드 → OpenAI가 본문을 읽고 스펙·근거 추출 → 결과 확인 → 시뮬레이터 적용
// AI는 문서에서 목표 점도·배합 추정치·요청 용기를 읽고, 용기 호환도 점수는 이 파일의 4장 기준으로 계산합니다.
const SLIDERS = ['active', 'carb', 'oil', 'hum'];
const SLIDER_STEPS = Object.fromEntries(SLIDERS.map(id => [id, $(id).step]));
const briefModal = $('brief-modal');
const briefDialog = briefModal.querySelector('.modal');
let analyzeRequest = null; // 진행 중인 분석 요청: { controller, timer }
let pendingBrief = null; // 결과 확인 단계에서 적용을 기다리는 의뢰서
let briefFrame = 0;
let toastTimer = 0;
document.body.append(briefModal, $('toast')); // 페이지 container 밖에 두어 fixed 위치를 유지합니다.

function updateBriefBadge() {
  const badge = $('brief-badge');
  badge.hidden = !appliedBrief || $('preset').value !== 'brief';
  if (badge.hidden) return;
  badge.classList.toggle('is-edited', !briefLocked);
  $('brief-badge-text').textContent = briefLocked ? `${appliedBrief.code} 스펙 반영됨` : `${appliedBrief.code} 기준 · 수동 조정`;
  badge.title = briefLocked ? appliedBrief.file : `${appliedBrief.file}\n배합 또는 용기를 조정해 실시간 계산값을 표시하고 있습니다. 샘플 제형에서 개발요청서 항목을 다시 선택하면 분석값으로 돌아갑니다.`;
}
function setBriefStep(step) {
  briefDialog.dataset.step = step;
  briefModal.querySelectorAll('[data-step-panel]').forEach(panel => { panel.hidden = panel.dataset.stepPanel !== step; });
}
function cancelAnalyze() {
  if (!analyzeRequest) return;
  analyzeRequest.controller.abort();
  clearInterval(analyzeRequest.timer);
  analyzeRequest = null;
}
function showBriefError(message) {
  $('brief-error').textContent = message;
  $('brief-error').hidden = !message;
  $('brief-drop').classList.toggle('is-error', Boolean(message));
}
function resetBriefModal() {
  cancelAnalyze();
  pendingBrief = null;
  $('brief-file').value = '';
  showBriefError('');
  $('brief-drop').classList.remove('is-dragover');
  setBriefStep('select');
}

function handleBriefFile(file) {
  if (!file) return;
  const message = !/\.(pdf|docx)$/i.test(file.name) ? 'PDF 또는 Word(.docx) 파일만 업로드할 수 있어요.'
    : file.size > 20 * 1024 * 1024 ? '20MB 이하의 파일만 업로드할 수 있어요.' : '';
  showBriefError(message);
  if (!message) analyzeBrief(file);
}

async function analyzeBrief(file) {
  cancelAnalyze();
  briefModal.querySelectorAll('[data-brief-filename]').forEach(el => { el.textContent = file.name; });
  briefModal.querySelectorAll('[data-brief-file-icon]').forEach(el => { el.textContent = /\.docx$/i.test(file.name) ? 'DOC' : 'PDF'; });
  const started = Date.now();
  $('brief-elapsed').textContent = '0초';
  const request = { controller: new AbortController(), timer: setInterval(() => { $('brief-elapsed').textContent = `${Math.floor((Date.now() - started) / 1000)}초`; }, 1000) };
  analyzeRequest = request;
  setBriefStep('analyzing');
  const body = new FormData();
  body.append('file', file);
  let data;
  try {
    const response = await fetch(briefModal.dataset.analyzeUrl, { method: 'POST', body, signal: request.controller.signal });
    data = await response.json().catch(() => ({ error: '분석 결과를 받지 못했어요. 로그인 상태를 확인하고 다시 시도해 주세요.' }));
    if (!response.ok || data.error) throw new Error(data.error || '분석하지 못했어요. 잠시 후 다시 시도해 주세요.');
  } catch (error) {
    if (request.controller.signal.aborted) return; // 사용자가 모달을 닫았거나 다른 파일을 올림
    cancelAnalyze();
    setBriefStep('select');
    $('brief-file').value = '';
    showBriefError(error instanceof TypeError ? '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.' : error.message);
    return;
  }
  if (analyzeRequest !== request) return;
  cancelAnalyze();
  pendingBrief = buildBrief(data);
  renderBriefResult(data, pendingBrief);
  setBriefStep('result');
  $('brief-apply').focus();
}

// OpenAI가 읽은 스펙을 시뮬레이터 의뢰서로 바꿉니다. 점도가 문서에 없으면 추정 배합의 예측 점도식을 씁니다.
function buildBrief(data) {
  const f = data.formula;
  const quotes = [...data.evidence];
  if (data.viscosity.quote) quotes.unshift({ label: '목표 점도', quote: data.viscosity.quote, page: data.viscosity.page });
  return makeSpecBrief({
    kind: data.kind, formula: { a: f.active, c: f.carbomer, o: f.oil, h: f.humectant }, pack: data.pack,
    file: data.file, code: data.code, title: data.product_name ? `${data.code} · ${data.product_name}` : data.code,
    statedV: data.viscosity.value, texture: data.texture, basis: ['의뢰서 명시 점도', '추정 배합의 예측 점도'],
    evidence: quotes.slice(0, 6).map(q => ({ label: String(q.label || '').slice(0, 60), quote: String(q.quote || '').slice(0, 300), page: String(q.page || '').slice(0, 20) }))
  });
}

// 목표 스펙(의뢰서 파일 분석·개발요청서 저장본·모델링 저장본 복원 공통). 점도는 명시값이 있으면 그 값, 없으면 배합 예측식.
// 용기가 없으면 점도에 가장 잘 맞는 용기를 기준으로 삼습니다.
function makeSpecBrief({ kind = '', formula, pack = '', file = '', code = '', title = '', statedV = null, texture = '', basis = ['명시 점도', '배합의 예측 점도'], evidence = [] }) {
  const stated = typeof statedV === 'number' && statedV > 0;
  const v = stated ? Math.round(statedV) : calculateViscosity(formula.a, formula.c, formula.o, formula.h);
  const scoreOf = key => calculateScore(v, key, evaluatePackage(v, key));
  const target = PACKS[pack] ? pack : Object.keys(PACKS).reduce((best, key) => scoreOf(key) > scoreOf(best) ? key : best);
  const state = evaluatePackage(v, target);
  const score = calculateScore(v, target, state);
  const tone = state === 'optimal' && score >= 95 ? 'excellent' : state;
  return {
    kind, ...formula, pack: target, file, code, title, evidence, texture,
    viscosityStated: stated, packStated: Boolean(PACKS[pack]),
    result: {
      v, flow: Math.round(100 / (1 + v / 6500)), score, tone, label: STATES[tone].label,
      texture: texture || textureLabel(v),
      diagnosis: `${stated ? basis[0] : basis[1]} 기준. ${packDiagnosis(v, target, state)}`,
      risk: packRisk(v, target, state), recs: getEligiblePacks(v)
    }
  };
}

// 결과 확인 단계: 추출값과 문서 근거 문장을 보여줍니다. 문서 내용은 textContent로만 넣습니다.
function renderBriefResult(data, brief) {
  const el = (tag, text) => Object.assign(document.createElement(tag), { textContent: text ?? '' });
  const badge = (text, basis) => {
    const small = el('small', text);
    small.dataset.basis = basis;
    return small;
  };
  $('brief-summary').textContent = data.summary;
  const rows = [
    ['제품', [data.product_name, brief.kind].filter(Boolean).join(' · ')],
    ['목표 점도', `${fmt(brief.result.v)} cPs`, brief.viscosityStated ? badge('의뢰서 명시', 'stated') : badge('배합으로 추정', 'estimated')],
    ['추정 배합', `유효 ${brief.a}% · 점증 ${brief.c}% · 오일 ${brief.o}% · 보습 ${brief.h}%`, badge('AI 추정', 'estimated')],
    ['요청 용기', PACKS[brief.pack].name.split(' (')[0], brief.packStated ? badge('의뢰서 명시', 'stated') : badge('미지정 · 점도 기준 선택', 'estimated')],
    ['유효성분', data.actives.map(a => a.percent ? `${a.name} ${a.percent}` : a.name).join(', ') || '문서에 명시 없음'],
    ['질감', brief.result.texture],
    ['용기 호환도', `${brief.result.score}점 · ${brief.result.label}`]
  ];
  $('brief-spec').replaceChildren(...rows.flatMap(([label, value, tag]) => {
    const dd = el('dd', value);
    if (tag) dd.append(tag);
    return [el('dt', label), dd];
  }));
  const quotes = [...data.evidence];
  if (data.viscosity.quote) quotes.unshift({ label: '목표 점도', quote: data.viscosity.quote, page: data.viscosity.page });
  if (data.pack_quote) quotes.push({ label: '요청 용기', quote: data.pack_quote, page: '' });
  const seen = new Set();
  const items = quotes.filter(q => !seen.has(q.quote) && seen.add(q.quote)).map(q => {
    const li = el('li');
    li.append(el('b', q.label), el('q', q.quote));
    if (q.page) li.append(el('span', `p.${String(q.page).replace(/^p\.?\s*/i, '')}`));
    return li;
  });
  $('brief-evidence').replaceChildren(...(items.length ? items : [el('li', '문서에서 직접 인용할 근거를 찾지 못했어요. 추정값을 확인한 뒤 적용하세요.')]));
  $('brief-basis').textContent = data.formula_basis ? `배합 추정 근거: ${data.formula_basis}` : '';
}

function stopBriefAnimation() {
  if (!briefFrame) return;
  cancelAnimationFrame(briefFrame);
  briefFrame = 0;
  roll = null;
  SLIDERS.forEach(id => { $(id).step = SLIDER_STEPS[id]; });
}
function flashViscosity() {
  const box = $('viscosity').parentElement;
  box.classList.remove('is-flash');
  void box.offsetWidth;
  box.classList.add('is-flash');
}
// tone: 'success'(체크 아이콘) / 'notice'(느낌표 아이콘, 확인이 필요한 안내). 안내가 길면 duration 을 늘립니다.
function showToast(title, detail, { tone = 'success', duration = 3200 } = {}) {
  const toast = $('toast');
  $('toast-title').textContent = title;
  $('toast-detail').textContent = detail || '';
  toast.dataset.tone = tone;
  toast.hidden = false;
  toast.classList.remove('is-visible');
  void toast.offsetWidth;
  toast.classList.add('is-visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('is-visible'), duration);
}
// 표시값(점도·유동성·점수)을 duration 동안 직전 값에서 새 값으로 롤링합니다. sliders가 있으면 함께 이동합니다.
let pendingSliders = null;
function startRoll(duration, sliders, onDone) {
  // 배합 적용 롤링 중에 용기를 바꾸면 배합 이동은 끝까지 이어갑니다.
  sliders = sliders || (briefFrame ? pendingSliders : null);
  stopBriefAnimation();
  pendingSliders = sliders;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) duration = 0;
  const from = SLIDERS.map(id => +$(id).value);
  const start = performance.now();
  roll = { from: { ...shown }, t: 0 };
  if (sliders) SLIDERS.forEach(id => { $(id).step = 'any'; });
  const step = now => {
    // rAF 타임스탬프는 start보다 앞설 수 있으므로 0~1로 고정합니다.
    const t = duration ? Math.min(1, Math.max(0, (now - start) / duration)) : 1;
    const eased = 1 - Math.pow(1 - t, 3);
    if (sliders) SLIDERS.forEach((id, i) => { $(id).value = from[i] + (sliders[i] - from[i]) * eased; });
    if (t < 1) {
      roll.t = eased;
      update();
      briefFrame = requestAnimationFrame(step);
      return;
    }
    briefFrame = 0;
    roll = null;
    pendingSliders = null;
    if (sliders) SLIDERS.forEach((id, i) => { $(id).step = SLIDER_STEPS[id]; $(id).value = sliders[i]; });
    update();
    onDone?.();
  };
  briefFrame = requestAnimationFrame(step);
}
// 대체 용기 칩·드롭다운: 배합(의뢰서 점도 포함)은 그대로 두고 궁합 점수만 0.3초 카운트업합니다.
function testPack(key) {
  $('pack').value = key;
  const ring = $('score-ring');
  ring.classList.remove('is-slosh');
  void ring.offsetWidth;
  ring.classList.add('is-slosh');
  startRoll(300);
}
// 모달을 닫고 슬라이더·지표·점수를 0.5초 동안 새 값으로 롤링 전환합니다.
function applyBrief(brief) {
  cancelAnalyze();
  window.Common.closeModal('simulation-brief-modal');
  work.method = 'brief_upload';
  applySpec(brief);
  markDirty();
  showToast(`${brief.code} 의뢰서 스펙 동기화됨`, `${brief.kind} 제형 · 목표 점도 ${fmt(brief.result.v)} cPs · 호환도 ${brief.result.score}점`);
}
// 샘플 제형 드롭다운의 '개발요청서' 항목을 이 스펙으로 바꾸고 배합·용기를 롤링 전환합니다.
function setBriefOption(brief) {
  appliedBrief = brief;
  let option = $('preset').querySelector('option[value=brief]');
  if (!brief) { option?.remove(); return; }
  if (!option) option = $('preset').appendChild(Object.assign(document.createElement('option'), { value: 'brief' }));
  option.textContent = `개발요청서 · ${brief.title}`;
}
function applySpec(brief) {
  setBriefOption(brief);
  $('preset').value = 'brief';
  $('pack').value = brief.pack;
  briefLocked = true;
  startRoll(500, [brief.a, brief.c, brief.o, brief.h], flashViscosity);
}

$('brief-open').addEventListener('click', () => {
  resetBriefModal();
  requestAnimationFrame(() => $('brief-drop').focus());
});
$('brief-file').addEventListener('change', event => handleBriefFile(event.target.files[0]));
$('brief-drop').tabIndex = 0;
$('brief-drop').addEventListener('keydown', event => {
  if (event.target !== $('brief-drop') || (event.key !== 'Enter' && event.key !== ' ')) return;
  event.preventDefault();
  $('brief-file').click();
});
['dragenter', 'dragover'].forEach(type => $('brief-drop').addEventListener(type, event => {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
  $('brief-drop').classList.add('is-dragover');
}));
$('brief-drop').addEventListener('dragleave', event => {
  if (!$('brief-drop').contains(event.relatedTarget)) $('brief-drop').classList.remove('is-dragover');
});
$('brief-drop').addEventListener('drop', event => {
  event.preventDefault();
  $('brief-drop').classList.remove('is-dragover');
  handleBriefFile(event.dataTransfer.files[0]);
});
$('brief-apply').addEventListener('click', () => { if (pendingBrief) applyBrief(pendingBrief); });
$('brief-retry').addEventListener('click', () => {
  resetBriefModal();
  requestAnimationFrame(() => $('brief-drop').focus());
});
// 분석 중 모달을 닫으면 진행 중인 분석 요청을 취소합니다.
new MutationObserver(() => { if (!briefModal.classList.contains('is-open')) cancelAnalyze(); })
  .observe(briefModal, { attributes: true, attributeFilter: ['class'] });
setBriefStep('select');

$('reset').addEventListener('click', () => {
  stopBriefAnimation();
  briefLocked = false;
  $('preset').value = 'ampoule';
  phase = 0;
  loadPreset();
  markDirty();
});

// 섹션별 복사 (R&D 리포트 / 바이어 세일즈 피칭) — 지금 보이는 언어로 복사합니다.
document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', () => {
  const text = button.dataset.copyTarget === 'rd' ? `${$('rd-report').textContent}
${$('rd-action').textContent}` : $('pitch-script').textContent;
  Promise.resolve().then(() => navigator.clipboard.writeText(text)).then(() => {
    button.classList.add('is-copied');
    button.title = '복사했어요';
    setTimeout(() => { button.classList.remove('is-copied'); button.title = '복사'; }, 1600);
  }).catch(() => showToast('복사하지 못했어요', '브라우저 권한을 확인한 뒤 다시 시도해 주세요.', { tone: 'notice' }));
}));

// 가이드 언어 전환 (한국어 / English) — 복사 아이콘은 지금 보이는 언어로 복사합니다.
document.querySelectorAll('[data-pitch-lang]').forEach(tab => tab.addEventListener('click', () => {
  pitchLang = tab.dataset.pitchLang;
  document.querySelectorAll('[data-pitch-lang]').forEach(other => {
    other.classList.toggle('is-active', other === tab);
    other.setAttribute('aria-pressed', String(other === tab));
  });
  renderPitch();
}));

// 목표 점도로 맞추기: 다른 배합은 그대로 두고 점증제(카보머) 함량만 조절해 가장 가까운 값을 찾습니다.
function fitCarbomer(target) {
  const a = +$('active').value, o = +$('oil').value, h = +$('hum').value;
  let best = 0, gap = Infinity;
  for (let i = 0; i <= 100; i++) {
    const c = i / 100;
    const d = Math.abs(calculateViscosity(a, c, o, h) - target);
    if (d < gap) { gap = d; best = c; }
  }
  return { c: best, v: calculateViscosity(a, best, o, h), min: calculateViscosity(a, 0, o, h), max: calculateViscosity(a, 1, o, h) };
}
function readTarget() {
  const t = Number($('target-input').value);
  return $('target-input').value.trim() !== '' && Number.isFinite(t) && t >= 1 && t <= 100000 ? t : null;
}
function showTargetHint(message) {
  const hint = $('target-hint');
  hint.textContent = message || '';
  hint.hidden = !message;
}
// 값을 입력하고 Enter(또는 칸을 벗어날 때) 점증제만 조절해 가장 가까운 값으로 맞춥니다.
function applyTarget(t) {
  const fit = fitCarbomer(t);
  stopBriefAnimation();
  briefLocked = false;
  $('carb').value = fit.c;
  update();
  markDirty();
  showTargetHint(Math.abs(fit.v - t) / t > 0.05 ? `점증제로는 ${fmt(fit.min)}~${fmt(fit.max)} cPs까지 가능해요` : '');
}
$('target-input').addEventListener('input', () => showTargetHint(''));
$('target-input').addEventListener('change', () => {
  const t = readTarget();
  if (t != null) applyTarget(t);
});
$('target-form').addEventListener('submit', event => {
  event.preventDefault();
  const t = readTarget();
  if (t != null) applyTarget(t);
});

// 용기 용량·내용물 호환 참고: 일반적인 구성 범위와 원료 특성만 안내합니다 (확정 판단 아님).
const PACK_VOLUME = { dropper: [10, 50], onetouch: [30, 200], mist: [30, 200], pump: [30, 250], airless: [15, 100], jar: [10, 100] };
const SENSITIVE_RE = /레티놀|retinol|아스코빅|ascorbic|비타민\s*c|vitamin\s*c/i;
const ALCOHOL_RE = /에탄올|알코올|ethanol|alcohol/i;
function updateCompat() {
  const notes = [];
  const key = $('pack').value;
  const volume = Number($('volume').value);
  const range = PACK_VOLUME[key];
  if ($('volume').value.trim() !== '' && volume > 0 && range && (volume < range[0] || volume > range[1])) {
    notes.push(`${PACKS[key].name.split(' (')[0]}는 보통 ${range[0]}~${range[1]}mL 구성이 많아요. ${volume}mL는 용기 사양을 따로 확인해 주세요.`);
  }
  const names = concepts.map(item => item.name);
  const sensitive = names.find(name => SENSITIVE_RE.test(name));
  if (sensitive && key !== 'airless') notes.push(`${sensitive}은(는) 산화·광에 민감해 차광 또는 에어리스 용기 확인이 필요해요.`);
  if (names.some(name => ALCOHOL_RE.test(name))) notes.push('알코올 계열 원료는 펌프·노즐 패킹 소재 호환 확인이 필요해요.');
  if (+$('oil').value >= 15) notes.push('유상 성분이 많아 PET·PS 등 용기 소재와의 호환 시험이 필요해요.');
  const node = $('compat');
  node.textContent = notes.join('\n');
  node.hidden = notes.length === 0;
}
$('volume').addEventListener('input', () => { updateCompat(); markDirty(); });

/* ==========================================================================
   프로젝트 연결 · 저장 · 불러오기 · 최종본 (simulation.md 9장)
   공통 API: docs/api_contract.md 2장, 프로젝트 선택은 공통 프로젝트 바(ProjectBar)를 씁니다.
   ========================================================================== */
const CALC_VERSION = 'sim-calc-1';
const SCHEMA_VERSION = 1;
const PRESET_KEYS = ['serum', 'ampoule', 'lotion', 'cream', 'brief'];
const bar = window.ProjectBar || null;
const work = {
  linked: null,      // 연결 프로젝트 — 처음 저장하거나 불러올 때 정해지고, 저장은 항상 이 프로젝트로 합니다.
  version: null,     // 지금 화면의 기준 모델링 저장본 { id, version_no, title, project_id }
  final: null,       // 연결 프로젝트의 현재 모델링 최종본 기록 (GET .../final 의 final)
  requisition: null, // 불러온 개발요청서 { version_id, version_no, title, texture, viscosity }
  method: 'manual',  // context.creation_method
  dirty: false
};
let concepts = [];   // 컨셉원료 코멘트 [{ name, comment, info, source }]
let overallComment = '';

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};
const projectLabel = project => `${project.customer.name} › ${project.name}`;
const apiMessage = r => r.status === 401 ? '로그인이 만료됐어요. 페이지를 새로 고친 뒤 다시 로그인해 주세요.'
  : (r.data && typeof r.data.error === 'string' && r.data.error) || r.error?.message || '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.';
const formatDate = iso => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};
function setError(id, message) {
  const node = $(id);
  node.textContent = message || '';
  node.hidden = !message;
}
function setBusy(button, busy, label) {
  button.disabled = busy;
  if (busy) {
    button.dataset.label = button.textContent;
    button.replaceChildren(el('span', 'spinner spinner-sm'), document.createTextNode(` ${label || button.textContent}`));
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
  }
}
document.body.append($('save-modal'), $('load-modal'), $('compare-modal'), $('concept-modal'));

function markDirty() {
  work.dirty = true;
  renderStatus();
}
function renderStatus() {
  const chip = $('version-chip');
  const isFinal = Boolean(work.version && work.final?.version?.id === work.version.id);
  chip.textContent = work.version
    ? `v${work.version.version_no}${isFinal ? ' · ★ 최종본' : ''}${work.dirty ? ' · 수정 중' : ''}`
    : '저장 전';
  chip.dataset.state = isFinal ? 'final' : work.version ? 'saved' : 'draft';
  chip.title = work.version
    ? `${work.version.title || '이름 없음'}${work.linked ? ` · ${projectLabel(work.linked)}` : ''}`
    : '아직 저장하지 않은 모델링이에요. 버전 번호는 저장할 때 서버가 정해요.';
  const toggle = $('final-toggle');
  toggle.disabled = !work.version || !work.linked;
  toggle.textContent = isFinal ? '최종본 해제' : '최종본 지정';
  toggle.title = toggle.disabled ? '저장하거나 불러온 모델링 저장본이 있을 때 지정할 수 있어요' : '';
}

// 배합·코멘트·불러온 요청서를 기본 프리셋으로 되돌립니다 (연결된 작업 중 다른 프로젝트로 바꿀 때).
function resetWork() {
  stopBriefAnimation();
  setBriefOption(null);
  briefLocked = false;
  $('preset').value = 'ampoule';
  loadPreset();
  concepts = [];
  overallComment = '';
  $('volume').value = '';
  Object.assign(work, { linked: null, version: null, final: null, requisition: null, method: 'manual', dirty: false });
  renderConcepts();
  renderStatus();
}
// 롤링 전환 중이면 최종값으로 바로 옮깁니다 (저장값이 애니메이션 중간값이 되지 않게).
function settleAnimation() {
  if (!briefFrame) return;
  const sliders = pendingSliders;
  stopBriefAnimation();
  if (sliders) SLIDERS.forEach((id, i) => { $(id).value = sliders[i]; });
  update();
}

// 9-1 프로젝트 연결: 연결된 작업 중 다른 프로젝트를 고르면 확인 후 초기화, 연결 전 작업 중이면 확인 후 그대로 연결.
let pendingProjectAction = null;
if (bar) {
  bar.setGuard(next => {
    pendingProjectAction = null;
    if (work.linked && (!next || next.id !== work.linked.id)) {
      if (!confirm(`이 모델링은 「${projectLabel(work.linked)}」 프로젝트에 연결되어 있어요.\n다른 프로젝트로 바꾸면 배합·코멘트·불러온 개발요청서가 초기화돼요. 바꿀까요?`)) return false;
      pendingProjectAction = 'reset';
    } else if (!work.linked && work.dirty && next) {
      if (!confirm(`작업 중인 배합·코멘트를 「${next.name}」 프로젝트에 연결할까요?\n지금 내용은 그대로 유지돼요.`)) return false;
      pendingProjectAction = 'link';
    }
    return true;
  });
  bar.onChange(project => {
    const action = pendingProjectAction;
    pendingProjectAction = null;
    if (action === 'reset') resetWork();
    if (action === 'link' && project) {
      work.linked = project;
      refreshFinal();
    }
    renderStatus();
  });
}
const currentProject = () => work.linked || bar?.current() || null;

// ---- 저장 payload (9-2, tab = simulation, schema_version = 1) ----
function buildPayload(project) {
  settleAnimation();
  const s = computeState();
  const round = (n, d) => Math.round(n * 10 ** d) / 10 ** d;
  const reports = generateReports(s.v, s.key, s.state, s.score, s.brief);
  const brief = appliedBrief;
  return {
    context: {
      customer_id: project.customer.id, customer_name: project.customer.name,
      project_id: project.id, project_name: project.name,
      source_requisition: work.requisition ? { version_id: work.requisition.version_id, version_no: work.requisition.version_no, title: work.requisition.title } : null,
      brief_file_name: brief?.file || '',
      creation_method: work.method
    },
    inputs: {
      preset: $('preset').value,
      formula: { active: s.a, carbomer: s.c, oil: s.o, humectant: s.h },
      package: s.key,
      package_volume_ml: Number($('volume').value) > 0 ? Math.round(Number($('volume').value)) : null,
      target_spec: brief ? {
        title: brief.title, code: brief.code, kind: brief.kind, applied: briefLocked,
        formula: { active: brief.a, carbomer: brief.c, oil: brief.o, humectant: brief.h },
        package: brief.pack, package_stated: brief.packStated,
        viscosity_cps: brief.viscosityStated ? brief.result.v : null, texture: brief.texture || ''
      } : null,
      concept_comments: concepts.map(item => ({ name: item.name, comment: item.comment, info: item.info, source: item.source })),
      comment: overallComment
    },
    outputs: {
      predicted_viscosity_cps: s.v,
      viscosity_basis: s.stated ? 'stated' : 'formula',
      total_ratio: { active: s.a, carbomer: s.c, oil: s.o, humectant: s.h, water: round(s.water, 2), total: 100 },
      texture: s.texture,
      flow_index: s.flow,
      stability: s.stability,
      package_fit: { package: s.key, state: s.tone, score: s.score, label: s.label, diagnosis: s.brief ? s.brief.diagnosis : packDiagnosis(s.v, s.key, s.state) },
      recommended_packages: s.brief ? [...s.brief.recs] : getEligiblePacks(s.v),
      buyer_guide: { rd_report: reports.report, rd_action: reports.action, sales_pitch: reports.sales }
    },
    meta: {
      brief_evidence: brief?.evidence || [],
      calc_version: CALC_VERSION
    }
  };
}

// ---- 저장 ----
function defaultTitle(project) {
  const base = work.requisition?.title || appliedBrief?.title || project?.name || '제형';
  return `${base} 모델링`.slice(0, 200);
}
$('save-open').addEventListener('click', () => {
  const project = currentProject();
  setError('save-error', '');
  $('save-submit').disabled = !project;
  $('save-name').disabled = !project;
  if (!project) {
    $('save-project').textContent = '';
    setError('save-error', '먼저 화면 위 프로젝트 바에서 고객사와 프로젝트를 선택해 주세요. 저장은 프로젝트 단위로 해요.');
  } else {
    $('save-project').textContent = `연결 프로젝트: ${projectLabel(project)}${work.linked ? '' : ' — 처음 저장하면 이 프로젝트가 이 모델링의 연결 프로젝트가 돼요.'}`;
    $('save-name').value = work.version?.title || defaultTitle(project);
  }
  window.Common.openModal('simulation-save-modal');
  requestAnimationFrame(() => (project ? $('save-name') : $('save-modal').querySelector('[data-modal-close]')).focus());
});
async function submitSave() {
  const project = currentProject();
  const button = $('save-submit');
  if (!project || button.disabled) return;
  const title = $('save-name').value.trim();
  if (!title) { setError('save-error', '저장본 이름을 입력해 주세요.'); $('save-name').focus(); return; }
  setError('save-error', '');
  const body = { schema_version: SCHEMA_VERSION, title, payload: buildPayload(project) };
  if (work.version && work.version.project_id === project.id) body.based_on_id = work.version.id;
  setBusy(button, true, '저장 중');
  const r = await window.Common.api('POST', `/api/projects/${project.id}/tabs/simulation/versions`, body);
  setBusy(button, false);
  if (!r.ok) { setError('save-error', apiMessage(r)); return; }
  const saved = r.data.version;
  work.linked = project;
  work.version = { id: saved.id, version_no: saved.version_no, title: saved.title, project_id: saved.project_id };
  work.dirty = false;
  window.Common.closeModal('simulation-save-modal');
  const base = r.data.base;
  showToast(`v${saved.version_no} 저장됨`, base?.is_stale
    ? `v${base.based_on_version_no}에서 시작해 저장했어요. 그 사이 v${base.latest_version_no_before_save}까지 저장본이 있었어요.`
    : `${saved.title} · ${projectLabel(project)}`, { duration: base?.is_stale ? 6000 : 3200 });
  await refreshFinal();
}
$('save-submit').addEventListener('click', submitSave);
$('save-name').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); submitSave(); }
});

// ---- 최종본 (9-4) ----
async function refreshFinal() {
  const project = work.linked;
  if (!project) { work.final = null; renderStatus(); return; }
  const r = await window.Common.api('GET', `/api/projects/${project.id}/tabs/simulation/final`);
  if (r.ok && work.linked === project) work.final = r.data.final;
  renderStatus();
}
$('final-toggle').addEventListener('click', async () => {
  const button = $('final-toggle');
  if (!work.version || !work.linked || button.disabled) return;
  const isFinal = work.final?.version?.id === work.version.id;
  const expected = work.final ? work.final.final_history_id : null;
  const body = isFinal
    ? { action: 'unset', expected_final_history_id: expected }
    : { action: 'set', version_id: work.version.id, expected_final_history_id: expected ?? null };
  setBusy(button, true);
  const r = await window.Common.api('POST', `/api/projects/${work.linked.id}/tabs/simulation/final`, body);
  setBusy(button, false);
  if (r.ok) {
    work.final = r.data.final;
    renderStatus();
    showToast(isFinal ? '최종본을 해제했어요' : `v${work.version.version_no}을 최종본으로 지정했어요`,
      isFinal ? '' : '개발요청서에서 모델링을 불러올 때 기본으로 선택돼요. 발송 기록과는 별개예요.');
    return;
  }
  if (r.status === 409 && r.error?.current) {
    // 다른 사람이 먼저 바꿨으면 작업 내용은 그대로 두고 바뀐 상태만 보여 줍니다.
    work.final = r.error.current;
    renderStatus();
    const now = work.final.version ? `지금 최종본은 v${work.final.version.version_no}이에요.` : '지금은 최종본이 없어요.';
    showToast('다른 사용자가 먼저 최종본을 바꿨어요', `${now} 확인한 뒤 다시 지정해 주세요.`, { tone: 'notice', duration: 6000 });
    return;
  }
  renderStatus();
  showToast('최종본을 바꾸지 못했어요', apiMessage(r), { tone: 'notice', duration: 6000 });
});

// ---- 불러오기 (9-3) ----
let loadTab = 'simulation';
const loadLists = { simulation: [], requisition: [] };
const loadSelection = { simulation: null, requisition: null };
let loadRequest = 0;

function renderLoadList(tab) {
  const list = $(`load-list-${tab}`);
  const items = loadLists[tab];
  if (!items.length) {
    const empty = el('li', 'state state-empty');
    empty.append(el('p', 'state-title', tab === 'simulation' ? '저장한 모델링이 없어요' : '저장한 개발요청서가 없어요'),
      el('p', null, tab === 'simulation' ? '배합을 조절한 뒤 [저장]하면 여기에 쌓여요.' : '개발요청서 탭에서 요청서를 저장하면 불러올 수 있어요.'));
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...items.map(item => {
    const li = el('li', 'simulation-version-item');
    const label = el('label');
    const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `simulation-load-${tab}`, value: String(item.id) });
    radio.checked = loadSelection[tab] === item.id;
    radio.addEventListener('change', () => { loadSelection[tab] = item.id; syncLoadSubmit(); });
    const main = el('span', 'simulation-version-main');
    const head = el('span', 'simulation-version-head');
    head.append(el('strong', null, `v${item.version_no}`), el('span', 'simulation-version-title', item.title || '이름 없음'));
    if (item.is_final) head.append(el('span', 'badge badge-primary', '★ 최종본'));
    main.append(head, el('small', 'text-caption', [item.created_by?.name, formatDate(item.created_at)].filter(Boolean).join(' · ')));
    label.append(radio, main);
    li.append(label);
    return li;
  }));
}
function syncLoadSubmit() {
  $('load-submit').disabled = !loadSelection[loadTab];
}
async function fetchLoadList(project, tab, request) {
  const r = await window.Common.api('GET', `/api/projects/${project.id}/tabs/${tab}/versions?limit=50`);
  if (request !== loadRequest) return;
  if (!r.ok) { setError('load-error', apiMessage(r)); return; }
  loadLists[tab] = r.data.items;
  // 개발요청서는 최종본이 기본 선택 (FIX)
  if (tab === 'requisition') loadSelection.requisition = (r.data.items.find(item => item.is_final) || {}).id || null;
  renderLoadList(tab);
  syncLoadSubmit();
}
$('load-open').addEventListener('click', () => {
  const project = currentProject();
  const request = ++loadRequest;
  setError('load-error', '');
  loadSelection.simulation = loadSelection.requisition = null;
  ['simulation', 'requisition'].forEach(tab => {
    loadLists[tab] = [];
    $(`load-list-${tab}`).replaceChildren(el('li', 'loading', '불러오는 중이에요'));
  });
  syncLoadSubmit();
  window.Common.openModal('simulation-load-modal');
  if (!project) {
    $('load-project').textContent = '';
    ['simulation', 'requisition'].forEach(tab => $(`load-list-${tab}`).replaceChildren());
    setError('load-error', '먼저 화면 위 프로젝트 바에서 고객사와 프로젝트를 선택해 주세요.');
    return;
  }
  $('load-project').textContent = projectLabel(project);
  fetchLoadList(project, 'simulation', request);
  fetchLoadList(project, 'requisition', request);
});
$('load-modal').querySelectorAll('[data-load-tab]').forEach(tab => tab.addEventListener('click', () => {
  loadTab = tab.dataset.loadTab;
  syncLoadSubmit();
}));
$('load-submit').addEventListener('click', async () => {
  const id = loadSelection[loadTab];
  const project = currentProject();
  if (!id || !project) return;
  if (work.dirty && !confirm('지금 작업 중인 내용이 불러온 내용으로 바뀌어요. 불러올까요?')) return;
  const button = $('load-submit');
  setBusy(button, true, '불러오는 중');
  const r = await window.Common.api('GET', `/api/versions/${id}`);
  setBusy(button, false);
  syncLoadSubmit();
  if (!r.ok) { setError('load-error', apiMessage(r)); return; }
  const version = r.data.version;
  const payload = version.payload || {};
  if (version.project_id !== project.id || version.tab !== loadTab || typeof payload.inputs !== 'object' || !payload.inputs) {
    setError('load-error', '이 저장본은 불러올 수 없는 형식이에요.');
    return;
  }
  window.Common.closeModal('simulation-load-modal');
  if (loadTab === 'simulation') restoreModeling(version, project);
  else applyRequisition(version, project);
});

const num = (value, fallback) => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);
const str = (value, max) => (typeof value === 'string' ? value.slice(0, max) : '');

// ---- 비교: 현재 작업과 저장본(또는 저장본끼리)을 나란히 봅니다. 읽기 전용이라 DB에 쓰지 않습니다. ----
const stabilityOf = (water, o, c) => (water < 45 || (o >= 20 && c < 0.2) ? 'unstable' : water < 60 || (o >= 12 && c < 0.2) ? 'review' : 'stable');
const COMPARE_ROWS = [
  ['예측 점도', s => `${fmt(s.v)} cPs`],
  ['예상 질감', s => s.texture],
  ['상대 유동성', s => `${s.flow} / 100`],
  ['유효 활성 성분', s => `${s.a}%`],
  ['점증제 (카보머)', s => `${s.c}%`],
  ['유상 오일 성분', s => `${s.o}%`],
  ['수분 유지 성분', s => `${s.h}%`],
  ['정제수', s => `${Number(s.water.toFixed(2))}%`],
  ['용기', s => PACKS[s.key].name.split(' (')[0]],
  ['용기 호환도', s => `${s.score}점 · ${s.label}`],
  ['포뮬러 안정성', s => ({ stable: '안정', review: '검토', unstable: '주의' })[s.stability]],
  ['컨셉원료', s => (s.concepts.length ? s.concepts.map(item => item.name).join(', ') : '없음')]
];
function snapshotFromState(s) {
  return { a: s.a, c: s.c, o: s.o, h: s.h, key: s.key, v: s.v, score: s.score, label: s.label, flow: s.flow, texture: s.texture, stability: s.stability, water: s.water, concepts };
}
function snapshotFromPayload(payload) {
  const inputs = payload.inputs || {}, outputs = payload.outputs || {}, f = inputs.formula || {};
  const a = num(f.active, 0), c = num(f.carbomer, 0), o = num(f.oil, 0), h = num(f.humectant, 0);
  const key = PACKS[inputs.package] ? inputs.package : 'dropper';
  const stated = outputs.viscosity_basis === 'stated' && typeof outputs.predicted_viscosity_cps === 'number';
  const v = stated ? outputs.predicted_viscosity_cps : calculateViscosity(a, c, o, h);
  const state = evaluatePackage(v, key);
  const score = calculateScore(v, key, state);
  const tone = state === 'optimal' && score >= 95 ? 'excellent' : state;
  const water = Math.max(0, 100 - a - c - o - h);
  return {
    a, c, o, h, key, v, score, label: STATES[tone].label, flow: Math.round(100 / (1 + v / 6500)), water,
    texture: stated && typeof outputs.texture === 'string' ? outputs.texture : textureLabel(v),
    stability: stabilityOf(water, o, c), concepts: sanitizeConcepts(inputs.concept_comments)
  };
}
const compareCache = new Map();
let compareItems = [];
let compareRender = 0;
let compareOpenRequest = 0;
async function compareSnapshot(value, project) {
  if (value === 'current') { settleAnimation(); return { title: '현재 작업 중', snap: snapshotFromState(computeState()) }; }
  const item = compareItems.find(entry => String(entry.id) === value);
  const title = item ? `v${item.version_no} ${item.title || '이름 없음'}` : '저장본';
  if (!compareCache.has(value)) {
    const r = await window.Common.api('GET', `/api/versions/${value}`);
    if (!r.ok) throw new Error(apiMessage(r));
    const version = r.data.version;
    if (version.project_id !== project.id || version.tab !== 'simulation' || !version.payload || typeof version.payload.inputs !== 'object') {
      throw new Error('이 저장본은 비교할 수 없는 형식이에요.');
    }
    compareCache.set(value, snapshotFromPayload(version.payload));
  }
  return { title, snap: compareCache.get(value) };
}
async function renderCompare() {
  const project = currentProject();
  const table = $('compare-table');
  const request = ++compareRender;
  setError('compare-error', '');
  if (!project || $('compare-a').value === '' || $('compare-b').value === '') { table.replaceChildren(); return; }
  table.replaceChildren(el('caption', 'text-caption', '불러오는 중이에요'));
  try {
    const [a, b] = await Promise.all([compareSnapshot($('compare-a').value, project), compareSnapshot($('compare-b').value, project)]);
    if (request !== compareRender) return;
    const head = el('tr');
    head.append(el('th', null, '항목'), el('th', null, `A · ${a.title}`), el('th', null, `B · ${b.title}`));
    const rows = COMPARE_ROWS.map(([label, read]) => {
      const left = read(a.snap), right = read(b.snap);
      const tr = el('tr', left === right ? '' : 'is-diff');
      tr.append(el('th', null, label), el('td', null, left), el('td', null, right));
      return tr;
    });
    const thead = el('thead'), tbody = el('tbody');
    thead.append(head);
    tbody.append(...rows);
    table.replaceChildren(thead, tbody);
  } catch (error) {
    if (request !== compareRender) return;
    table.replaceChildren();
    setError('compare-error', error.message || '비교하지 못했어요. 잠시 후 다시 시도해 주세요.');
  }
}
function fillCompareSelects(defaultB) {
  const options = [['current', '현재 작업 중'], ...compareItems.map(item => [String(item.id), `v${item.version_no} · ${item.title || '이름 없음'}${item.is_final ? ' ★' : ''}`])];
  ['a', 'b'].forEach(side => $(`compare-${side}`).replaceChildren(...options.map(([value, text]) => Object.assign(document.createElement('option'), { value, textContent: text }))));
  $('compare-a').value = 'current';
  $('compare-b').value = defaultB;
}
$('compare-open').addEventListener('click', async () => {
  const project = currentProject();
  const request = ++compareOpenRequest;
  compareItems = [];
  fillCompareSelects('current');
  $('compare-table').replaceChildren();
  setError('compare-error', '');
  window.Common.openModal('simulation-compare-modal');
  if (!project) {
    $('compare-project').textContent = '';
    setError('compare-error', '먼저 화면 위 프로젝트 바에서 고객사와 프로젝트를 선택해 주세요.');
    return;
  }
  $('compare-project').textContent = projectLabel(project);
  const r = await window.Common.api('GET', `/api/projects/${project.id}/tabs/simulation/versions?limit=50`);
  if (request !== compareOpenRequest) return;
  if (!r.ok) { setError('compare-error', apiMessage(r)); return; }
  compareItems = r.data.items;
  if (!compareItems.length) { setError('compare-error', '비교할 저장본이 없어요. 배합을 저장하면 여기서 나란히 볼 수 있어요.'); return; }
  const preferred = compareItems.find(item => item.is_final) || compareItems[0];
  fillCompareSelects(String(preferred.id));
  renderCompare();
});
$('compare-a').addEventListener('change', renderCompare);
$('compare-b').addEventListener('change', renderCompare);

// (1) 모델링 저장본 복원: 저장된 inputs 로 다시 계산하고, 저장 당시 결과와 다르면 함께 안내합니다.
function restoreModeling(version, project) {
  const { context = {}, inputs, outputs = {} } = version.payload;
  stopBriefAnimation();
  const spec = inputs.target_spec && typeof inputs.target_spec === 'object' ? inputs.target_spec : null;
  setBriefOption(spec ? makeSpecBrief({
    kind: str(spec.kind, 40), code: str(spec.code, 40), title: str(spec.title, 200) || '저장된 스펙', file: str(context.brief_file_name, 200),
    formula: { a: num(spec.formula?.active, 0), c: num(spec.formula?.carbomer, 0), o: num(spec.formula?.oil, 0), h: num(spec.formula?.humectant, 0) },
    pack: spec.package_stated ? str(spec.package, 20) : '', statedV: num(spec.viscosity_cps, null), texture: str(spec.texture, 200),
    basis: ['의뢰서 명시 점도', '배합의 예측 점도'], evidence: Array.isArray(version.payload.meta?.brief_evidence) ? version.payload.meta.brief_evidence.slice(0, 6) : []
  }) : null);
  const preset = PRESET_KEYS.includes(inputs.preset) && (inputs.preset !== 'brief' || appliedBrief) ? inputs.preset : 'ampoule';
  $('preset').value = preset;
  briefLocked = preset === 'brief' && Boolean(spec?.applied);
  const f = inputs.formula || {};
  SLIDERS.forEach((id, i) => { $(id).value = num([f.active, f.carbomer, f.oil, f.humectant][i], +$(id).value); });
  if (PACKS[inputs.package]) $('pack').value = inputs.package;
  const savedVolume = num(inputs.package_volume_ml, null);
  $('volume').value = savedVolume == null ? '' : String(savedVolume);
  concepts = sanitizeConcepts(inputs.concept_comments);
  overallComment = str(inputs.comment, 3000);
  const req = context.source_requisition;
  work.requisition = req && typeof req === 'object' ? { version_id: req.version_id, version_no: req.version_no, title: str(req.title, 200), texture: '', viscosity: '' } : null;
  Object.assign(work, {
    linked: project, method: ['manual', 'brief_upload', 'requisition_load'].includes(context.creation_method) ? context.creation_method : 'manual',
    version: { id: version.id, version_no: version.version_no, title: version.title, project_id: version.project_id }, dirty: false
  });
  update();
  renderConcepts();
  refreshFinal();
  const now = computeState();
  const diffs = [];
  if (num(outputs.predicted_viscosity_cps, now.v) !== now.v) diffs.push(`예측 점도 ${fmt(outputs.predicted_viscosity_cps)} cPs`);
  if (num(outputs.package_fit?.score, now.score) !== now.score) diffs.push(`호환도 ${outputs.package_fit.score}점`);
  if (typeof outputs.texture === 'string' && outputs.texture !== now.texture) diffs.push(`질감 ${outputs.texture}`);
  const notes = [];
  if (diffs.length) notes.push(`저장 당시 결과와 달라요 (계산식 변경 등) — 저장 당시: ${diffs.join(' · ')}`);
  if (context.brief_file_name) notes.push('의뢰서 원본 파일은 저장하지 않아 복원되지 않아요.');
  showToast(`v${version.version_no} 불러옴 · ${version.title || '이름 없음'}`, notes.join(' ') || projectLabel(project),
    { tone: diffs.length ? 'notice' : 'success', duration: notes.length ? 9000 : 3200 });
}

// (2) 개발요청서 저장본 불러오기: 요청서 payload 를 읽어 제형·용기를 바로 시뮬레이션합니다 (PDF 재업로드 없음).
const DETAIL_PRESETS = { 세럼: 'serum', 앰플: 'ampoule', 로션: 'lotion', 크림: 'cream' };
const PACK_WORDS = [
  ['airless', /에어리스|airless/i], ['onetouch', /원\s*터치|one[\s-]?touch/i], ['dropper', /스포이드|드롭퍼|dropper|pipette/i],
  ['mist', /미스트|스프레이|mist|spray/i], ['jar', /크림\s*자|단지|(^|[^가-힣])자([^가-힣]|$)|jar|tub/i], ['pump', /펌프|디스펜서|pump|dispenser/i]
];
function matchPack(text) {
  return (PACK_WORDS.find(([, re]) => re.test(text || '')) || [''])[0];
}
// "12,000 cPs", "8,000~12,000 mPa·s" 처럼 단위가 붙은 숫자만 목표 점도로 씁니다 (범위는 가운데 값).
function parseCps(text) {
  const match = /(\d[\d,]*(?:\.\d+)?)\s*(?:(?:~|-|–|to)\s*(\d[\d,]*(?:\.\d+)?)\s*)?(?:cps|cp|mpa\s*[·.]?\s*s)\b/i.exec(text || '');
  if (!match) return null;
  const low = parseFloat(match[1].replace(/,/g, ''));
  const high = match[2] ? parseFloat(match[2].replace(/,/g, '')) : low;
  const value = (low + high) / 2;
  return value > 0 ? Math.min(200000, Math.round(value)) : null;
}
function applyRequisition(version, project) {
  const inputs = version.payload.inputs;
  const pd = inputs.product_development && typeof inputs.product_development === 'object' ? inputs.product_development : {};
  const detail = str(inputs.product_type_detail, 20);
  const preset = PRESETS[DETAIL_PRESETS[detail]];
  // 요청서에는 배합 수치가 없으므로 세부 유형 프리셋(없으면 현재 배합)에서 시작합니다.
  const formula = preset ? { a: preset.a, c: preset.c, o: preset.o, h: preset.h } : { a: +$('active').value, c: +$('carb').value, o: +$('oil').value, h: +$('hum').value };
  const title = str(version.title, 200) || str(inputs.product_name, 200) || '개발요청서';
  const texture = str(pd.texture, 200);
  const viscosity = str(pd.viscosity, 300);
  const brief = makeSpecBrief({
    kind: detail || str(inputs.product_type, 20), formula, pack: matchPack(pd.container_reference),
    code: `요청서 v${version.version_no}`, title: `${title} v${version.version_no}`,
    statedV: parseCps(viscosity), texture, basis: ['개발요청서 명시 점도', `${preset ? detail + ' 프리셋' : '현재'} 배합의 예측 점도`]
  });
  // 컨셉 원료는 코멘트 목록에 미리 채웁니다 (이미 있는 원료는 그대로 둠).
  const concept = Array.isArray(inputs.ingredients?.concept) ? inputs.ingredients.concept : [];
  let added = 0;
  concept.forEach(item => {
    const name = str(item?.name, 100).trim();
    if (!name || findConcept(name) || concepts.length >= CONCEPT_MAX) return;
    const kind = item.kind === 'necessary' ? '필수 원료' : item.kind === 'ideal' ? '선호 원료' : '컨셉 원료';
    const must = item.must_contain === true ? ' · 함유 필수' : item.must_contain === false ? ' · 함유 필수 아님' : '';
    const tags = Array.isArray(item.efficacy_tags) ? item.efficacy_tags.filter(tag => typeof tag === 'string' && tag.trim()).map(tag => tag.slice(0, 30)).slice(0, 6) : [];
    concepts.push({ name, comment: `개발요청서 ${kind}${must}`, info: tags.length ? { summary: '', properties: '', efficacy_tags: tags, caution: '' } : null, source: 'requisition' });
    added += 1;
  });
  work.requisition = { version_id: version.id, version_no: version.version_no, title, texture, viscosity };
  work.linked = project;
  work.method = 'requisition_load';
  applySpec(brief);
  renderConcepts();
  markDirty();
  refreshFinal();
  const container = brief.packStated ? PACKS[brief.pack].name.split(' (')[0] : '요청 용기 없음 · 점도 기준 선택';
  showToast(`개발요청서 v${version.version_no} 불러옴`,
    `${brief.viscosityStated ? `목표 점도 ${fmt(brief.result.v)} cPs` : '점도 수치 없음 · 프리셋 배합 기준'} · ${container}${added ? ` · 컨셉 원료 ${added}개 추가` : ''}`, { duration: 5000 });
}

/* ==========================================================================
   컨셉원료 코멘트 창 (simulation.md 8장)
   자주 쓰는 원료는 이 목록에서만 정의합니다. 정보는 일반적인 참고 설명이며 함량·규제 판단이 아닙니다.
   ========================================================================== */
const CONCEPT_MAX = 30;
const CONCEPT_PRESETS = [
  { name: '나이아신아마이드', inci: 'Niacinamide', summary: '비타민 B3 계열의 수용성 원료예요.', properties: '물에 잘 녹고 비교적 안정해 다양한 제형에 쓰기 쉬워요.', efficacy_tags: ['미백', '피지 조절', '장벽'], caution: '고함량에서 따끔함·홍조가 있을 수 있어요. 기능성 함량 기준은 인허가 규제 탭에서 확인하세요.' },
  { name: '아데노신', inci: 'Adenosine', summary: '세포 에너지 대사와 관련된 뉴클레오사이드 원료예요.', properties: '수용성이고 소량으로 배합되며 제형 사용감에 주는 영향이 적어요.', efficacy_tags: ['주름개선', '탄력'], caution: '기능성 함량 기준은 국가별로 다르니 인허가 규제 탭에서 확인하세요.' },
  { name: '레티놀', inci: 'Retinol', summary: '비타민 A 계열의 지용성 원료예요.', properties: '빛·산소·열에 약해 캡슐화 원료나 차광·에어리스 용기를 함께 검토해요.', efficacy_tags: ['주름개선', '탄력', '피부결'], caution: '자극(붉어짐·각질)이 생길 수 있고 국가별 사용 제한이 있어요. 인허가 규제 탭에서 확인하세요.' },
  { name: '아스코빅애시드', inci: 'Ascorbic Acid', summary: '순수 비타민 C 원료예요.', properties: '수용성이고 산화·변색이 쉬워 낮은 pH와 산소 차단 용기가 필요해요.', efficacy_tags: ['미백', '항산화'], caution: '산성 제형이라 따끔할 수 있고, 갈변 등 안정성 확인이 필요해요.' },
  { name: '히알루론산', inci: 'Sodium Hyaluronate', summary: '수분을 붙잡는 다당류 보습 원료예요.', properties: '분자량에 따라 사용감이 달라지고, 함량을 높이면 점도가 올라가요.', efficacy_tags: ['보습'], caution: '고함량에서 끈적임·밀림이 생길 수 있어요.' },
  { name: '세라마이드', inci: 'Ceramide NP', summary: '피부 장벽을 이루는 지질 성분을 닮은 원료예요.', properties: '물에 잘 녹지 않아 유상 또는 리포좀 등 분산 처방이 필요해요.', efficacy_tags: ['보습', '장벽'], caution: '결정이 석출되지 않도록 처방 안정성 확인이 필요해요.' },
  { name: '펩타이드', inci: 'Peptides', summary: '아미노산이 이어진 원료군이에요 (종류가 많아요).', properties: '대부분 수용성이고 소량 배합해요. 원료마다 컨셉과 단가 차이가 커요.', efficacy_tags: ['탄력', '주름개선'], caution: '구체적인 펩타이드 종류와 근거 자료를 원료사에 확인하세요.' },
  { name: '병풀추출물(시카)', inci: 'Centella Asiatica Extract', summary: '병풀에서 얻은 추출물로 시카 컨셉의 대표 원료예요.', properties: '추출물이라 색·향이 날 수 있고, 지표 성분 함량이 원료마다 달라요.', efficacy_tags: ['진정', '장벽'], caution: '마데카소사이드 등 지표 성분 표기 방식은 원료 규격으로 확인하세요.' },
  { name: 'PDRN', inci: 'Sodium DNA', summary: '연어 등에서 얻은 DNA 단편 원료예요.', properties: '수용성이고 소량 배합해요. 원료 출처와 등급이 다양해요.', efficacy_tags: ['재생', '진정'], caution: '동물 유래 원료라 비건·할랄 요구가 있는 바이어에게는 사전 확인이 필요해요.' },
  { name: '판테놀', inci: 'Panthenol', summary: '프로비타민 B5 원료예요.', properties: '수용성이고 안정해 토너부터 크림까지 넓게 써요.', efficacy_tags: ['보습', '진정'], caution: '고함량에서 끈적임이 생길 수 있어요.' }
];
const SOURCE_LABELS = { preset: '자주 쓰는 원료', ai_search: 'AI 검색', ai_recommend: 'AI 추천', manual: '직접 입력', requisition: '개발요청서' };
let conceptMode = 'name';
let conceptRequest = 0;

// 효능 태그 카테고리별 색 (공통 Badge 색만 사용). 위에서부터 먼저 맞는 것을 씁니다.
const TAG_TONES = [
  ['badge-warning', /미백|브라이트|톤|광채|잡티|항산화|비타민/],
  ['badge-success', /진정|재생|시카|트러블|회복|항염|흔적/],
  ['badge-danger', /주름|탄력|안티|리프팅|노화|모공/],
  ['badge-primary', /보습|장벽|수분|보호|유수분/]
];
const tagBadge = tag => el('span', `badge ${(TAG_TONES.find(([, re]) => re.test(tag)) || [''])[0]}`.trim(), tag);
const findConcept = name => concepts.find(item => item.name.toLocaleLowerCase() === name.trim().toLocaleLowerCase());
function cleanInfo(info) {
  if (!info || typeof info !== 'object') return null;
  return {
    summary: str(info.summary, 300), properties: str(info.properties, 300), caution: str(info.caution, 300),
    efficacy_tags: Array.isArray(info.efficacy_tags) ? info.efficacy_tags.filter(tag => typeof tag === 'string' && tag.trim()).map(tag => tag.slice(0, 30)).slice(0, 6) : []
  };
}
function sanitizeConcepts(list) {
  if (!Array.isArray(list)) return [];
  const result = [];
  list.forEach(item => {
    const name = str(item?.name, 100).trim();
    if (!name || result.some(other => other.name.toLocaleLowerCase() === name.toLocaleLowerCase()) || result.length >= CONCEPT_MAX) return;
    result.push({ name, comment: str(item.comment, 1000), info: cleanInfo(item.info), source: SOURCE_LABELS[item.source] ? item.source : 'manual' });
  });
  return result;
}
function addConcept(name, info, source) {
  name = name.trim().slice(0, 100);
  if (!name) return;
  const existing = findConcept(name);
  if (!existing) {
    if (concepts.length >= CONCEPT_MAX) { showConceptError(`컨셉원료는 ${CONCEPT_MAX}개까지 추가할 수 있어요.`); return; }
    concepts.push({ name, comment: '', info: cleanInfo(info), source });
    markDirty();
    renderConcepts();
  }
  const item = $('concept-list').querySelector(`[data-concept-name="${CSS.escape((existing || findConcept(name)).name)}"]`);
  item?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  item?.querySelector('textarea')?.focus({ preventScroll: true });
}
function showConceptError(message) {
  const box = $('concept-error');
  box.querySelector('p').textContent = message || '';
  box.hidden = !message;
}
function infoBlock(info, source) {
  const block = el('div', 'simulation-concept-info');
  if (source === 'ai_search' || source === 'ai_recommend') block.append(el('span', 'badge badge-warning', 'AI 요약 · 확인 필요'));
  if (info.summary) block.append(el('p', null, info.summary));
  if (info.properties) block.append(el('p', null, `특성 · ${info.properties}`));
  if (info.efficacy_tags.length) {
    const tags = el('div', 'simulation-concept-tags');
    info.efficacy_tags.forEach(tag => tags.append(tagBadge(tag)));
    block.append(tags);
  }
  if (info.caution) block.append(el('p', 'simulation-concept-caution', `주의 · ${info.caution}`));
  return block;
}
function renderConcepts() {
  // 자주 쓰는 원료 칩: 이미 추가한 원료는 눌린 상태로 표시
  $('concept-presets').querySelectorAll('button').forEach(button => {
    const added = Boolean(findConcept(button.dataset.name));
    button.setAttribute('aria-pressed', String(added));
    button.className = `btn ${added ? 'btn-soft' : 'btn-secondary'} btn-sm`;
  });
  $('concept-count').textContent = concepts.length ? `${concepts.length}개` : '';
  updateCompat();
  $('concept-list').replaceChildren(...(concepts.length ? concepts.map((item, index) => {
    const li = el('li', 'simulation-concept-item');
    li.dataset.conceptName = item.name;
    const head = el('div', 'simulation-concept-item-head');
    const name = el('strong', null, item.name);
    const remove = el('button', 'btn btn-ghost btn-sm', '삭제');
    remove.type = 'button';
    remove.setAttribute('aria-label', `${item.name} 삭제`);
    remove.addEventListener('click', () => { concepts.splice(index, 1); markDirty(); renderConcepts(); });
    head.append(name, el('span', 'badge', SOURCE_LABELS[item.source]), remove);
    li.append(head);
    if (item.info) li.append(infoBlock(item.info, item.source));
    const note = el('textarea', 'form-control form-control-sm');
    note.rows = 2;
    note.maxLength = 1000;
    note.placeholder = '이 원료에 대한 코멘트 (바이어 요구, 연구소 전달 사항 등)';
    note.setAttribute('aria-label', `${item.name} 코멘트`);
    note.value = item.comment;
    note.addEventListener('input', () => { item.comment = note.value; markDirty(); renderConceptSummary(); });
    li.append(note);
    return li;
  }) : [el('li', 'text-caption', '아직 추가한 원료가 없어요.')]));
  if ($('concept-comment').value !== overallComment) $('concept-comment').value = overallComment;
  // AI 결과 카드의 [코멘트에 추가] 버튼 상태도 맞춥니다.
  $('concept-results').querySelectorAll('[data-add-name]').forEach(button => {
    const added = Boolean(findConcept(button.dataset.addName));
    button.disabled = added;
    button.textContent = added ? '추가됨' : '코멘트에 추가';
  });
  renderConceptSummary();
}
// 하단 카드: 추가한 원료 칩과 전체 코멘트 미리보기
function renderConceptSummary() {
  const note = $('requisition-note');
  note.hidden = !work.requisition;
  if (work.requisition) {
    const target = [work.requisition.texture && `목표 질감 ${work.requisition.texture}`, work.requisition.viscosity && `점도 ${work.requisition.viscosity}`].filter(Boolean).join(' · ');
    note.textContent = `불러온 개발요청서 · ${work.requisition.title} (v${work.requisition.version_no})${target ? ` — ${target}` : ''}`;
  }
  // 원료마다 카드 한 장: 이름·출처 / 효능 태그 / 내 코멘트. 원료 설명·주의는 카드에 펼치지 않고
  // 마우스를 올리면(title) 보이며, 누르면 편집 모달에서 그 원료(전체 정보)로 이동합니다.
  $('concept-chips').replaceChildren(...concepts.map(item => {
    const li = el('li');
    const card = el('button', 'simulation-concept-card');
    card.type = 'button';
    card.dataset.source = item.source;
    card.setAttribute('aria-label', `${item.name} 코멘트 편집`);
    const head = el('span', 'simulation-concept-card-head');
    // 한 줄: 원료명 · 효능 태그 · (오른쪽) 출처
    head.append(el('strong', null, item.name));
    const tags = item.info?.efficacy_tags || [];
    if (tags.length) {
      const row = el('span', 'simulation-concept-tags');
      tags.slice(0, 3).forEach(tag => row.append(tagBadge(tag)));
      head.append(row);
    }
    head.append(el('span', 'simulation-concept-card-source', SOURCE_LABELS[item.source]));
    card.append(head);
    if (item.comment) card.append(el('span', 'simulation-concept-card-comment', item.comment));
    card.title = [item.info?.summary, item.info?.caution && `주의 · ${item.info.caution}`, '눌러서 코멘트 편집'].filter(Boolean).join('\n');
    card.addEventListener('click', () => {
      window.Common.openModal('simulation-concept-modal');
      requestAnimationFrame(() => {
        const target = $('concept-list').querySelector(`[data-concept-name="${CSS.escape(item.name)}"]`);
        target?.scrollIntoView({ block: 'center' });
        target?.querySelector('textarea')?.focus({ preventScroll: true });
      });
    });
    li.append(card);
    return li;
  }));
  $('concept-overall').textContent = overallComment;
  $('concept-overall').hidden = !overallComment;
  $('concept-empty').hidden = Boolean(concepts.length || overallComment);
  $('concept-open').textContent = concepts.length || overallComment ? '코멘트 편집' : '코멘트 작성';
}

CONCEPT_PRESETS.forEach(preset => {
  const button = el('button', 'btn btn-secondary btn-sm', preset.name);
  button.type = 'button';
  button.dataset.name = preset.name;
  button.title = `${preset.inci} · ${preset.efficacy_tags.join(', ')}`;
  button.addEventListener('click', () => addConcept(preset.name, preset, 'preset'));
  $('concept-presets').append(button);
});
$('concept-modal').querySelectorAll('[data-concept-mode]').forEach(tab => tab.addEventListener('click', () => {
  conceptMode = tab.dataset.conceptMode;
  $('concept-modal').querySelectorAll('[data-concept-mode]').forEach(other => {
    other.classList.toggle('is-active', other === tab);
    other.setAttribute('aria-pressed', String(other === tab));
  });
  $('concept-query').placeholder = conceptMode === 'name' ? '예: 나이아신아마이드' : '예: 미백, 탄력, 재생';
  $('concept-query').focus();
}));
$('concept-search').addEventListener('submit', async event => {
  event.preventDefault();
  const query = $('concept-query').value.trim();
  const button = $('concept-search-btn');
  if (button.disabled) return;
  if (!query) { showConceptError(conceptMode === 'name' ? '원료명을 입력해 주세요.' : '원하는 기능 키워드를 입력해 주세요.'); $('concept-query').focus(); return; }
  showConceptError('');
  const request = ++conceptRequest;
  const mode = conceptMode;
  setBusy(button, true, '검색 중');
  $('concept-results').replaceChildren(el('div', 'loading', 'AI가 원료 정보를 정리하고 있어요'));
  const r = await window.Common.api('POST', $('brief-modal').dataset.ingredientUrl, { query, mode });
  if (request !== conceptRequest) return;
  setBusy(button, false);
  if (!r.ok) {
    $('concept-results').replaceChildren();
    showConceptError(r.status === 404 && !(r.data && r.data.error)
      ? 'AI 검색이 아직 서버에 연결되지 않았어요. 자주 쓰는 원료나 직접 입력은 지금도 쓸 수 있어요.'
      : apiMessage(r));
    return;
  }
  const items = Array.isArray(r.data.items) ? r.data.items : [];
  const source = mode === 'name' ? 'ai_search' : 'ai_recommend';
  if (!items.length) {
    $('concept-results').replaceChildren(el('p', 'text-caption', r.data.note || '검색 결과를 찾지 못했어요.'));
    return;
  }
  $('concept-results').replaceChildren(...items.map(item => {
    const info = cleanInfo(item);
    const card = el('article', 'simulation-concept-result');
    const head = el('div', 'simulation-concept-item-head');
    head.append(el('strong', null, str(item.name, 100)));
    if (item.inci) head.append(el('small', 'text-caption', str(item.inci, 150)));
    const add = el('button', 'btn btn-soft btn-sm', '코멘트에 추가');
    add.type = 'button';
    add.dataset.addName = str(item.name, 100);
    add.addEventListener('click', () => addConcept(add.dataset.addName, info, source));
    head.append(add);
    card.append(head, infoBlock(info, source));
    return card;
  }));
  if (r.data.note) $('concept-results').append(el('p', 'text-caption', r.data.note));
  renderConcepts();
});
$('concept-manual').addEventListener('submit', event => {
  event.preventDefault();
  const name = $('concept-manual-name').value.trim();
  if (!name) { $('concept-manual-name').focus(); return; }
  addConcept(name, null, 'manual');
  $('concept-manual-name').value = '';
});
$('concept-comment').addEventListener('input', event => {
  overallComment = event.target.value;
  markDirty();
  renderConceptSummary();
});
$('concept-open').addEventListener('click', () => {
  showConceptError('');
  requestAnimationFrame(() => $('concept-query').focus());
});
renderConcepts();
renderStatus();

// Canvas lighting layers retain the original viscosity-driven animation.
const canvas=$('canvas'),ctx=canvas.getContext('2d');let width=0,height=0,phase=0,last=0,frame=0;
// Uniform logical coordinates preserve proportions on every viewport.
function resize() {
  const bounds = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(bounds.width * dpr);
  canvas.height = Math.round(bounds.height * dpr);
  width = 560;
  height = 420;
  // 스포이드 윗단(y 32)부터 바닥 눈금 글자(y 395)까지만 맞춰, 위아래 빈 여백 없이 스포이드와 샬레를 최대한 크게 그립니다.
  const top = 20, bottom = 405;
  const scale = Math.min(bounds.width / width, bounds.height / (bottom - top));
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale,
    (bounds.width - width * scale) / 2 * dpr,
    ((bounds.height - (bottom - top) * scale) / 2 - top * scale) * dpr);
  drawScene();
}
// Layered transmission, edge depth and a soft key light for clear serum.
function paintSerum(path, x, y, rx, ry) {
 ctx.save();
 ctx.shadowColor='rgba(30,90,130,.12)';ctx.shadowBlur=7;ctx.shadowOffsetY=3;
 const body=ctx.createLinearGradient(x-rx,y-ry,x+rx,y+ry);
 body.addColorStop(0,'rgba(56,149,209,.62)');
 body.addColorStop(.22,'rgba(125,211,252,.48)');
 body.addColorStop(.48,'rgba(224,247,255,.24)');
 body.addColorStop(.75,'rgba(56,189,248,.53)');
 body.addColorStop(1,'rgba(29,112,175,.72)');
 ctx.fillStyle=body;ctx.fill(path);ctx.shadowBlur=0;ctx.shadowOffsetY=0;
 ctx.clip(path);
 const light=ctx.createRadialGradient(x-rx*.32,y-ry*.4,0,x-rx*.32,y-ry*.4,rx*.9);
 light.addColorStop(0,'rgba(255,255,255,.92)');light.addColorStop(.35,'rgba(255,255,255,.48)');light.addColorStop(1,'rgba(255,255,255,0)');
 ctx.save();ctx.translate(x-rx*.32,y-ry*.4);ctx.scale(1,Math.max(.25,ry/rx*.5));
 ctx.translate(-x+rx*.32,-y+ry*.4);ctx.fillStyle=light;ctx.fillRect(x-rx*3,y-rx*3,rx*6,rx*6);ctx.restore();
 ctx.strokeStyle='rgba(239,251,255,.75)';ctx.lineWidth=1.2;ctx.stroke(path);
 ctx.restore();
}
// 제곱근 스케일: 저점도는 얇고 넓게, 초고점도는 좁고 두터운 돔. 30,000 cPs 이상은 팁에서 떨어지지 않습니다.
function geometry(){
 const thick=Math.min(1,Math.sqrt(Math.max(0,current.v)/50000));
 return {thick,energy:1-thick,dropTime:.58+thick*.16,hanging:current.v>=30000,spread:110*(1-thick*.65),domeHeight:3+thick*45};
}
// 착지 반응. 저점도는 크라운·비산 방울·여러 겹 파문과 출렁임, 고점도는 튐 없이 쌓였다 천천히 합쳐집니다.
// 좌표는 착지점(웅덩이 꼭대기) 기준이며 실측 유체 해석이 아닌 시연용 표현입니다.
let impact=null;
function spawnImpact(){
 const {thick,energy}=geometry(),drops=[];
 const count=thick<.6?Math.round(energy*energy*16):0;
 for(let i=0;i<count;i++){
  const side=i%2?1:-1;
  drops.push({x:side*(3+Math.random()*8),y:0,vx:side*(40+Math.random()*130)*energy,vy:-(110+Math.random()*240)*energy**1.5,r:1+Math.random()*2.2*energy,land:-1});
 }
 impact={age:0,drops};
}
function stepImpact(dt){
 if(!impact)return;
 const {spread,domeHeight}=geometry();
 impact.age+=dt;
 for(const d of impact.drops){
  if(d.land>=0)continue;
  d.vy+=900*dt;d.x+=d.vx*dt;d.y+=d.vy*dt;
  // 웅덩이 안이면 수면 높이에서, 밖이면 샬레 바닥에서 멈춥니다.
  const inside=Math.abs(d.x)<spread,surface=inside?domeHeight*(1-(d.x/spread)**2):0;
  if(d.vy>0&&d.y>=domeHeight-surface){d.y=domeHeight-surface;d.inside=inside;d.land=impact.age;}
 }
 if(impact.age>5)impact=null;
}
function drawScene(){
 if(!current||!width||!height)return;
 ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.restore();
 const x=width/2,tip=130,floor=height*.8;
 const {thick,energy,dropTime,hanging,spread:restSpread,domeHeight:restDome}=geometry();
 const maxNeck=(floor-tip-restDome)*(.18+thick*.3);
 // 이미 고인 액체의 반응: 저점도는 움푹 꺼졌다 튀어 오르며 출렁이고, 고점도는 거의 움직이지 않습니다.
 const age=impact?impact.age:9;
 const wobble=energy>.3?-(4+restDome*.15)*energy*Math.exp(-age*(3+thick*10))*Math.cos(age*(18-thick*14)):0;
 const pulse=.08*energy*Math.exp(-age*2.5)*(1-Math.exp(-age*14));
 const spread=restSpread*(1+pulse),domeHeight=Math.max(1.5,restDome+wobble);
 // Faint reference scales are illustrative, not a calibrated measurement.
 ctx.save();ctx.strokeStyle='#e2e8f0';ctx.fillStyle='#94a3b8';ctx.lineWidth=.7;ctx.font='9px monospace';
 const rulerX=x-100;
 ctx.beginPath();ctx.moveTo(rulerX,140);ctx.lineTo(rulerX,300);
 for(let i=0;i<=8;i++){const yy=140+i*20;ctx.moveTo(rulerX,yy);ctx.lineTo(rulerX+(i%2?5:10),yy);if(i%2===0)ctx.fillText(`${(i*.05).toFixed(1)}`,rulerX-25,yy+3);}
 ctx.stroke();ctx.fillText('mL REF',rulerX-25,125);
 ctx.beginPath();ctx.setLineDash([2,7]);ctx.moveTo(x,145);ctx.lineTo(x,floor-55);ctx.stroke();ctx.setLineDash([]);
 for(const yy of [160,250]){ctx.beginPath();ctx.moveTo(x+88,yy);ctx.lineTo(x+98,yy);ctx.moveTo(x+93,yy-5);ctx.lineTo(x+93,yy+5);ctx.stroke();}
 ctx.beginPath();for(let i=-5;i<=5;i++){const xx=x+i*20;ctx.moveTo(xx,floor+40);ctx.lineTo(xx,floor+40+(i%5===0?7:4));}ctx.stroke();ctx.fillText('0',x-3,floor+59);ctx.fillText('10 mm REF',x+70,floor+59);
 // Clear quartz dish: back rim, glass sidewall and a refracted front lip.
 const plate=ctx.createLinearGradient(0,floor-9,0,floor+30);
 plate.addColorStop(0,'rgba(255,255,255,.72)');plate.addColorStop(.55,'rgba(210,227,238,.18)');plate.addColorStop(1,'rgba(155,184,205,.32)');
 ctx.fillStyle=plate;ctx.beginPath();ctx.ellipse(x,floor+11,135,23,0,0,Math.PI*2);ctx.fill();
 ctx.strokeStyle='rgba(148,175,195,.4)';ctx.lineWidth=1;ctx.stroke();
 ctx.beginPath();ctx.ellipse(x,floor+3,135,23,0,0,Math.PI*2);ctx.fillStyle='rgba(255,255,255,.32)';ctx.fill();ctx.stroke();
 ctx.beginPath();ctx.ellipse(x,floor+4,127,19,0,0,Math.PI);ctx.strokeStyle='rgba(255,255,255,.95)';ctx.lineWidth=2;ctx.stroke();ctx.restore();
 // Contact shadow grounds the serum on the quartz surface.
 ctx.save();ctx.translate(x,floor+8);ctx.scale(1,.18);
 const shadow=ctx.createRadialGradient(0,0,spread*.12,0,0,spread*1.2);
 shadow.addColorStop(0,'rgba(41,75,98,.19)');shadow.addColorStop(.65,'rgba(41,75,98,.06)');shadow.addColorStop(1,'rgba(41,75,98,0)');
 ctx.fillStyle=shadow;ctx.fillRect(-spread*1.2,-spread*1.2,spread*2.4,spread*2.4);ctx.restore();
 // A convex surface-tension profile, with a refracted lower meniscus.
 const pool=new Path2D();
 pool.moveTo(x-spread,floor);
 pool.bezierCurveTo(x-spread*.9,floor-domeHeight*.7,x-spread*.45,floor-domeHeight,x,floor-domeHeight);
 pool.bezierCurveTo(x+spread*.5,floor-domeHeight,x+spread*.92,floor-domeHeight*.64,x+spread,floor);
 pool.bezierCurveTo(x+spread*.85,floor+14,x-spread*.82,floor+14,x-spread,floor);
 pool.closePath();
 paintSerum(pool,x,floor-domeHeight*.35,spread,domeHeight);
 ctx.save();ctx.clip(pool);
 const base=ctx.createLinearGradient(0,floor-3,0,floor+12);
 base.addColorStop(0,'rgba(56,189,248,0)');base.addColorStop(.7,'rgba(30,117,174,.24)');base.addColorStop(1,'rgba(224,247,255,.8)');
 ctx.fillStyle=base;ctx.fillRect(x-spread,floor-3,spread*2,16);
 ctx.beginPath();ctx.ellipse(x-spread*.23,floor-domeHeight*.69,spread*.38,Math.max(2,domeHeight*.09),-.06,0,Math.PI*2);
 ctx.fillStyle='rgba(255,255,255,.66)';ctx.fill();
 ctx.beginPath();ctx.moveTo(x-spread*.8,floor+1);ctx.bezierCurveTo(x-spread*.35,floor+8,x+spread*.5,floor+8,x+spread*.86,floor-1);
 ctx.strokeStyle='rgba(213,245,255,.88)';ctx.lineWidth=1.4;ctx.stroke();
 // 파문: 점도가 낮을수록 빠르고 여러 겹으로 멀리 퍼지며, 높을수록 한 겹이 짧게 사라집니다.
 if(impact){
  const rings=energy>.6?3:energy>.3?2:1;
  for(let j=0;j<rings;j++){
   const a=age-j*.12;if(a<=0)continue;
   const r=a*(40+260*energy);if(r>=spread)continue;
   const alpha=(1-r/spread)*(.2+energy*.5)*Math.exp(-a*thick*3);
   ctx.beginPath();ctx.ellipse(x,floor-domeHeight*.35,r,r*.16+1.5,0,0,Math.PI*2);
   ctx.strokeStyle=`rgba(255,255,255,${alpha})`;ctx.lineWidth=1.2;ctx.stroke();
   ctx.beginPath();ctx.ellipse(x,floor-domeHeight*.35+1.5,r,r*.16+1.5,0,0,Math.PI);
   ctx.strokeStyle=`rgba(29,112,175,${alpha*.45})`;ctx.lineWidth=1;ctx.stroke();
  }
  // 웅덩이에 다시 떨어진 비산 방울이 만드는 작은 파문
  for(const d of impact.drops){
   if(d.land<0||!d.inside)continue;
   const a=age-d.land;if(a>.4)continue;
   ctx.beginPath();ctx.ellipse(x+d.x,floor-domeHeight+d.y,2+a*40,.6+a*6,0,0,Math.PI*2);
   ctx.strokeStyle=`rgba(255,255,255,${(1-a/.4)*.6})`;ctx.lineWidth=.8;ctx.stroke();
  }
 }
 ctx.restore();
 if(impact){
  const top=floor-domeHeight;
  // 고점도: 방울이 튀지 않고 수면 위에 쌓였다가 점도에 비례한 시간 동안 천천히 퍼지며 합쳐집니다.
  if(thick>.3){
   const merge=1-Math.exp(-age/(.2+thick*1.8)),rd=12-thick*3;
   const bw=rd*(1.1+merge*1.8),bh=rd*(.4+thick*1.2)*(1-merge);
   if(bh>.5){
    const mound=new Path2D();
    mound.moveTo(x-bw,top+2);
    mound.bezierCurveTo(x-bw*.7,top+2-bh*.9,x-bw*.35,top+2-bh,x,top+2-bh);
    mound.bezierCurveTo(x+bw*.35,top+2-bh,x+bw*.7,top+2-bh*.9,x+bw,top+2);
    mound.quadraticCurveTo(x,top+5,x-bw,top+2);mound.closePath();
    paintSerum(mound,x,top+2-bh*.5,bw,bh*.5+1);
    // 겹쳐 쌓인 경계선이 합쳐지는 동안 점점 옅어집니다.
    ctx.beginPath();ctx.ellipse(x,top+2,bw*.8,1.6,0,0,Math.PI);
    ctx.strokeStyle=`rgba(29,112,175,${(1-merge)*.35})`;ctx.lineWidth=1;ctx.stroke();
   }
  }
  // 저점도: 착지 직후 수면이 왕관 모양으로 솟았다 가라앉습니다.
  if(energy>.55&&age<.32){
   const k=age/.32,cr=6+k*34*energy,ch=26*energy**1.5*Math.sin(Math.PI*k),spikes=8;
   if(ch>1){
    const crown=new Path2D();crown.moveTo(x-cr,top);
    for(let i=0;i<=spikes;i++){
     const px=x-cr+2*cr*i/spikes,lift=ch*(i%2?1:.55)*(.55+.45*Math.sin(Math.PI*i/spikes));
     crown.lineTo(px,top-lift);
    }
    crown.lineTo(x+cr,top);crown.quadraticCurveTo(x,top+4,x-cr,top);crown.closePath();
    ctx.save();ctx.globalAlpha=1-k*.5;paintSerum(crown,x,top-ch*.5,cr,ch*.5);ctx.restore();
   }
  }
  // 튀어 오른 방울은 날아가는 방향으로 늘어나고, 샬레 바닥에 떨어진 방울은 작은 비드로 남았다 사라집니다.
  for(const d of impact.drops){
   const px=x+d.x,py=top+d.y;
   if(d.land<0){
    const stretch=Math.min(1.8,1+Math.hypot(d.vx,d.vy)/400),angle=Math.atan2(d.vy,d.vx);
    ctx.save();ctx.translate(px,py);ctx.rotate(angle);
    ctx.beginPath();ctx.ellipse(0,0,d.r*stretch,d.r,0,0,Math.PI*2);
    ctx.fillStyle='rgba(56,149,209,.6)';ctx.fill();
    ctx.beginPath();ctx.ellipse(-d.r*.3,-d.r*.3,d.r*.35,d.r*.3,0,0,Math.PI*2);ctx.fillStyle='rgba(255,255,255,.85)';ctx.fill();
    ctx.restore();
   }else if(!d.inside){
    const a=age-d.land,fade=Math.max(0,1-a/2.5);if(!fade)continue;
    ctx.beginPath();ctx.ellipse(px,floor-d.r*.4,d.r*1.3,d.r*.55,0,0,Math.PI*2);
    ctx.fillStyle=`rgba(56,149,209,${.5*fade})`;ctx.fill();
    ctx.beginPath();ctx.ellipse(px-d.r*.4,floor-d.r*.6,d.r*.4,d.r*.18,0,0,Math.PI*2);ctx.fillStyle=`rgba(255,255,255,${.8*fade})`;ctx.fill();
   }
  }
 }
 // The 98px nozzle is 1.86 times the reference length, with a smooth taper.
 const nozzle=ctx.createLinearGradient(x-15,0,x+15,0);
 nozzle.addColorStop(0,'#52677b');nozzle.addColorStop(.18,'#a5b7c6');nozzle.addColorStop(.38,'#edf4f8');nozzle.addColorStop(.54,'#b5c6d3');nozzle.addColorStop(.82,'#6d859b');nozzle.addColorStop(1,'#3e556c');
 ctx.fillStyle=nozzle;ctx.beginPath();ctx.moveTo(x-15,32);ctx.lineTo(x+15,32);ctx.lineTo(x+15,76);
 ctx.bezierCurveTo(x+15,96,x+5,108,x+4,tip);ctx.quadraticCurveTo(x,tip+2,x-4,tip);
 ctx.bezierCurveTo(x-5,108,x-15,96,x-15,76);ctx.closePath();ctx.fill();
 ctx.beginPath();ctx.moveTo(x-7,36);ctx.lineTo(x-7,76);ctx.bezierCurveTo(x-7,95,x-2,108,x-2,tip-5);
 ctx.strokeStyle='rgba(255,255,255,.62)';ctx.lineWidth=1.2;ctx.stroke();
 ctx.beginPath();ctx.ellipse(x,tip,3.7,1.5,0,0,Math.PI*2);ctx.fillStyle='rgba(47,117,153,.55)';ctx.fill();
 // Preserve necking and gravity-driven motion; the landing follows the dome.
 const drop=new Path2D();let cy,rx,ry;
 if(hanging||phase<dropTime){
 // 매달린 방울은 늘어났다 되돌아오기를 반복합니다.
 const t=hanging?(1-Math.cos(phase*Math.PI*2))/2*.75:phase/dropTime,neck=8+t*maxNeck,r=7+t*8;
 cy=tip+neck;rx=r;ry=r;
 drop.moveTo(x-3,tip);drop.bezierCurveTo(x-2,tip+neck*.5,x-r,cy-r,x-r,cy);
 drop.arc(x,cy,r,Math.PI,0,true);drop.bezierCurveTo(x+r,cy-r,x+2,tip+neck*.5,x+3,tip);drop.closePath();
 }else{
 const t=(phase-dropTime)/(1-dropTime);
 rx=12-thick*3;ry=12+thick*4;
 cy=tip+maxNeck+(floor-restDome-tip-maxNeck)*t*t;
 drop.ellipse(x,cy,rx,ry,0,0,Math.PI*2);
 }
 paintSerum(drop,x,cy,rx,ry);
 ctx.save();ctx.clip(drop);ctx.beginPath();ctx.ellipse(x-rx*.32,cy-ry*.3,Math.max(1,rx*.17),ry*.38,.25,0,Math.PI*2);
 ctx.fillStyle='rgba(255,255,255,.82)';ctx.fill();ctx.restore();
}
function tick(time){frame=0;if(paused||document.hidden){last=0;return;}const dt=last?Math.min((time-last)/1000,.05):0;last=time;const next=(phase+dt*(.9/(1+current.v/9000)+.08))%1;if(next<phase&&!geometry().hanging)spawnImpact();phase=next;stepImpact(dt);drawScene();frame=requestAnimationFrame(tick);}
function start(){if(!paused&&!document.hidden&&!frame)frame=requestAnimationFrame(tick);}
function motionLabel(){$('lab-status').textContent=paused?'Ⅱ PAUSED':'● ANALYZING';{const label=paused?'시연 재생':'시연 일시정지';$('motion').title=label;$('motion').setAttribute('aria-label',label);}$('motion').setAttribute('aria-pressed',String(paused));}
$('motion').addEventListener('click',()=>{paused=!paused;motionLabel();if(paused){cancelAnimationFrame(frame);frame=0;last=0;}else start();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;last=0;}else start();});
loadPreset();motionLabel();new ResizeObserver(resize).observe(canvas);resize();start();

})();
