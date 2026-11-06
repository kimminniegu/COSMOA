/* Home 전용 JavaScript (담당자 A) — 명세: src/01_home/home.md
   - 서버가 #home-data 에 넣어 준 JSON으로 화면을 그리고, 갱신 중인 구역은 /api/home/data 를 다시 불러 그립니다.
   - 위젯 배치·크기·표시 여부는 사용자별로 localStorage 에 저장합니다. (2-3)
   - 프로젝트 위젯 3종은 /api/home/projects 를 따로 불러와, 업무 DB 가 느리거나 실패해도 나머지 위젯은 그대로 나옵니다. (2-4)
   - 바이어 현지 시각은 브라우저에서 계산합니다. (7장)
   - 규제 새 소식은 10분마다 /api/home/regulations 로 확인합니다. (8-3) */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var dataEl = $("home-data");
  if (!dataEl) return;

  /* localStorage — 저장 불가 환경에서도 동작하도록 감쌉니다 (state 보다 먼저 정의) */
  var storage = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    getJSON: function (k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    setJSON: function (k, v) { storage.set(k, JSON.stringify(v)); },
  };

  /* 공통 .container 가 container-type(레이아웃 격리)을 써서 그 안의 position:fixed 모달이 본문 스크롤을 따라 움직입니다.
     홈의 모달 3개를 <body> 바로 아래로 옮겨 항상 화면 가운데에 뜨게 합니다. (common.js 는 document 위임이라 그대로 동작) */
  ["home-city-modal", "home-rate-modal", "home-widget-modal"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el && el.parentNode !== document.body) document.body.appendChild(el);
  });

  var state = {
    data: JSON.parse(dataEl.textContent || "{}"),
    clockMode: storage.get("cosmoa.clock.mode") || "top_export",
    customCities: storage.getJSON("cosmoa.clock.cities") || null,
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function arrow(direction) { return direction === "up" ? "▲" : direction === "down" ? "▼" : "–"; }

  /* 1. 환율 위젯: 서버는 저장된 통화 전부를 보내고, 표시할 통화·순서는 위젯 설정(codes)으로 고릅니다 ------ */
  function renderRates(r) {
    var o = opt("rates"), box = $("home-rates-items"), meta = $("home-rates-meta");
    if (!r || !r.items || !r.items.length) {
      box.innerHTML = '<span class="home-error">' + esc((r && r.error) || "환율 정보를 불러오지 못했어요") + "</span>";
      meta.textContent = "";
      return;
    }
    meta.textContent = "수출입은행 · " + r.date_text + " 기준";
    var byCode = {};
    r.items.forEach(function (it) { byCode[it.code] = it; });
    var items = o.codes.map(function (c) { return byCode[c]; }).filter(Boolean);
    if (!items.length) {
      box.innerHTML = '<span class="home-error">위젯 설정에서 표시할 통화를 골라 주세요</span>';
      return;
    }
    var cols = Math.min(items.length, 4);
    box.style.setProperty("--home-rate-cols", cols);
    box.innerHTML = items.map(function (it, i) {
      var unit = it.unit === 100 ? " <small>(100)</small>" : "";
      var title = it.name + (it.unit === 100 ? " · 100" + it.code + " 기준" : " · 1" + it.code + " 기준");
      var warn = "";
      if (it.warning) { /* 전일 대비 급변 — 서버 RATE_WARN_PCT 기준 (명세 13-1) */
        title += " · 전일 대비 " + it.change_text + " 변동, 값 확인 필요";
        warn = '<span class="home-rate__warn" role="img" aria-label="이상값 경고">!</span>';
      }
      return '<div class="home-rate' + (it.warning ? " is-warn" : "") + (i % cols === 0 ? " is-row-start" : "") + '" role="button" tabindex="0" data-code="' + esc(it.code) + '" title="' + esc(title + " · 누르면 상세 보기") + '">' +
        '<span class="home-rate__code">' + esc(it.code) + unit + warn + "</span>" +
        '<span class="home-rate__value"><span class="home-rate__rate">' + esc(it.rate_text) + "</span>" +
        (o.change ? '<span class="home-rate__change is-' + esc(it.direction) + '">' + arrow(it.direction) + " " + esc(it.change_text) + "</span>" : "") + "</span></div>";
    }).join("");
  }

  /* 1-1. 환율 상세 모달 (4-4): 통화 클릭 → /api/home/rates/<code> ------------ */
  var rateCache = {};   // code → { at, data } (10분)
  function fmt(n, digits) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("ko-KR", { minimumFractionDigits: digits == null ? 2 : digits, maximumFractionDigits: digits == null ? 2 : digits });
  }
  /* 공통 꺾은선 차트: 세로축 눈금값(단위 포함)·격자선·마지막 값 표시·점별 툴팁. 홈 카드(12개월), 환율 상세(30일), 수출입 상세(월별)에서 같이 씁니다.
     o = { values:[숫자], labels:[문자], fmt:함수(값→"$1,250M"), aria:설명, zeroBase:0을 축에 포함할지, current:강조할 index, every:x 라벨 간격 } */
  /* 보기 좋은 눈금 (1·2·5 × 10^n 간격) — 축 값이 0, 500, 1,000 처럼 딱 떨어지게 */
  function niceNum(r, round) {
    if (r <= 0) return 1;
    var exp = Math.floor(Math.log(r) / Math.LN10), f = r / Math.pow(10, exp), nf;
    if (round) nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10; else nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }
  function niceTicks(lo, hi, count) {
    var step = niceNum(niceNum(hi - lo, false) / (count - 1), true) || 1;
    var nlo = Math.floor(lo / step) * step, nhi = Math.ceil(hi / step) * step;
    if (nhi === nlo) nhi = nlo + step;
    var t = []; for (var v = nhi; v >= nlo - step / 2; v -= step) t.push(Math.round(v * 1e6) / 1e6);
    return { lo: nlo, hi: nhi, ticks: t };
  }
  /* 공통 꺾은선 차트 — 차트 제목·단위 표기·범례·보기 좋은 눈금·격자·마지막 값·점 툴팁.
     o = { series:[{name, values, dashed}] (또는 values), labels, fmt, title, unit, xTitle, aria, zeroBase, current, every } */
  function lineChart(o) {
    var series = o.series || [{ name: o.name || "", values: o.values }];
    var main = series[0], v = main.values, n = v.length;
    if (n < 2) return '<p class="home-chart__none">표시할 자료가 부족해요</p>';
    var all = [];
    series.forEach(function (sr) { sr.values.forEach(function (x) { if (x != null && !isNaN(x)) all.push(x); }); });
    var vmin = Math.min.apply(null, all), vmax = Math.max.apply(null, all);
    var lo = o.zeroBase ? Math.min(0, vmin) : vmin, hi = o.zeroBase ? Math.max(0, vmax) : vmax;
    if (!o.zeroBase) { var pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.01 || 1; lo -= pad; hi += pad; }
    var nt = niceTicks(lo, hi, 4); lo = nt.lo; hi = nt.hi;
    var y = function (val) { return (1 - (val - lo) / (hi - lo)) * 100; };
    var step = 100 / (n - 1), base = y(o.zeroBase ? Math.max(0, lo) : lo);
    var toPts = function (vals) { return vals.map(function (val, i) { return val == null ? null : [i * step, y(val)]; }); };
    var toLine = function (pts) { return pts.filter(Boolean).map(function (p) { return p[0].toFixed(2) + "," + p[1].toFixed(2); }).join(" "); };
    var pts = toPts(v), line = toLine(pts);
    var area = "0," + base.toFixed(2) + " " + line + " 100," + base.toFixed(2);
    var grid = nt.ticks.map(function (t) { var yy = y(t).toFixed(2); return '<line class="home-chart__grid" x1="0" x2="100" y1="' + yy + '" y2="' + yy + '"></line>'; }).join("");
    var zero = lo < 0 && hi > 0 ? '<line class="home-chart__zero" x1="0" x2="100" y1="' + y(0).toFixed(2) + '" y2="' + y(0).toFixed(2) + '"></line>' : "";
    var others = series.slice(1).map(function (sr) {
      return '<polyline class="home-chart__line2' + (sr.dashed === false ? "" : " is-dashed") + '" points="' + toLine(toPts(sr.values)) + '"></polyline>';
    }).join("");
    var cur = o.current != null && o.current >= 0 ? o.current : n - 1;
    var hover = v.map(function (val, i) {
      var x0 = Math.max(0, (i - 0.5) * step), w = Math.min(100, (i + 0.5) * step) - x0;
      var tip = series.map(function (sr) { var x = sr.values[i]; return (sr.name ? sr.name + " " : "") + (x == null ? "—" : o.fmt(x)); }).join(" · ");
      return '<rect class="home-chart__hit" x="' + x0.toFixed(2) + '" y="0" width="' + w.toFixed(2) + '" height="100"><title>' + esc(o.labels[i] + " · " + tip) + "</title></rect>";
    }).join("");
    var every = o.every || Math.max(1, Math.ceil(n / 6));
    var xs = o.labels.map(function (l, i) {
      var show = (i % every === 0 || i === n - 1 || i === cur) &&
        (i === cur || Math.abs(i - cur) > 1) &&            /* 강조 라벨 바로 옆은 숨김 (겹침 방지) */
        (i === n - 1 || i === cur || n - 1 - i > 1);       /* 마지막 라벨 바로 옆도 숨김 */
      return '<small class="' + (i === cur ? "is-current" : "") + (show ? "" : " is-hidden") + '" style="left:' + (i * step).toFixed(2) + '%">' + esc(l) + "</small>";
    }).join("");
    var last = pts[cur];
    var lastPos = (last[1] < 32 ? " is-below" : "") + (last[0] < 18 ? " is-left" : "");
    var lastLabel = '<span class="home-chart__last' + lastPos + '" style="left:' + last[0].toFixed(2) + "%;top:" + last[1].toFixed(2) + '%">' + esc(o.fmt(v[cur])) + "</span>";
    var ys = nt.ticks.map(function (t) { return '<span style="top:' + y(t).toFixed(2) + '%">' + esc(o.fmt(t)) + "</span>"; }).join("");
    var head = o.title || o.unit ? '<div class="home-chart__head"><span class="home-chart__title">' + esc(o.title || "") + "</span>" +
      (o.unit ? '<span class="home-chart__unit">단위: ' + esc(o.unit) + "</span>" : "") + "</div>" : "";
    var legend = series.length > 1 || (series[0].name && o.legend !== false) ? '<div class="home-chart__legend">' + series.map(function (sr, i) {
      return '<span class="home-chart__key' + (i > 0 && sr.dashed !== false ? " is-dashed" : "") + '"><i></i>' + esc(sr.name) + "</span>";
    }).join("") + "</div>" : "";
    return '<div class="home-chart" role="img" aria-label="' + esc(o.aria || o.title || "") + '">' + head + legend +
      '<div class="home-chart__y">' + ys + "</div>" +
      '<div class="home-chart__plot"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">' + grid + zero +
        '<polygon class="home-tsum__area" points="' + area + '"></polygon>' + others +
        '<polyline class="home-tsum__line" points="' + line + '"></polyline>' +
        '<circle class="home-tsum__dot" cx="' + last[0].toFixed(2) + '" cy="' + last[1].toFixed(2) + '" r="3.5"></circle>' + hover +
      "</svg>" + lastLabel + "</div>" +
      '<div class="home-chart__x">' + xs + (o.xTitle ? '<em class="home-chart__xtitle">' + esc(o.xTitle) + "</em>" : "") + "</div></div>";
  }
  function rateChart(hist) {
    return lineChart({
      values: hist.map(function (h) { return Number(h.rate); }), labels: hist.map(function (h) { return h.label; }),
      fmt: function (v) { return v.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "원"; },
      name: "매매기준율", legend: false, title: "매매기준율 추이", unit: "원",
      aria: "최근 30영업일 매매기준율 추이", zeroBase: false, every: Math.ceil(hist.length / 4),
    });
  }
  function renderRateDetail(d) {
    var body = $("home-rate-body");
    $("home-rate-title").textContent = d.name ? d.name + " (" + d.code + ")" : "환율 상세";
    if (!d.ok) { body.innerHTML = '<span class="home-error">' + esc(d.error || "환율 정보를 불러오지 못했어요") + "</span>"; return; }
    var s = d.stats, chg = d.change == null ? "" :
      '<span class="home-rated__change is-' + esc(d.direction) + '">' + arrow(d.direction) + " " + esc(d.diff_text) + "원 (" + esc(d.change_text) + ")</span>";
    var warn = d.warning ? '<span class="badge badge-warning home-rated__warn">전일 대비 급변 · 값 확인 필요</span>' : "";
    var hist = d.history || [];
    var calc =
      '<div class="home-rated__section home-rated__calc">' +
        '<div class="home-rated__section-head"><span>환산 계산기</span><small>매매기준율 기준</small></div>' +
        '<div class="home-rated__calc-row">' +
          '<label class="home-rated__field"><span>' + esc(d.code) + '</span><input class="form-control form-control-sm home-rated__input" id="home-rate-fx" type="text" inputmode="decimal" autocomplete="off" value="1,000"></label>' +
          '<span class="home-rated__eq" aria-hidden="true">=</span>' +
          '<label class="home-rated__field"><span>KRW</span><input class="form-control form-control-sm home-rated__input" id="home-rate-krw" type="text" inputmode="decimal" autocomplete="off"></label>' +
        "</div>" +
        '<p class="form-help">실제 송금·환전 금액은 은행 우대율과 수수료에 따라 달라져요. 참고용으로만 사용해 주세요.</p>' +
      "</div>";
    body.innerHTML =
      '<div class="home-rated__col">' +
      '<div class="home-rated__head">' +
        '<div class="home-rated__main"><span class="home-rated__rate">' + esc(d.rate_text) + '<small>원</small></span>' + chg + "</div>" +
        '<p class="home-rated__sub">' + esc(d.unit_text) + " 기준 매매기준율 · 수출입은행 " + esc(d.date_text) + " 고시" +
          (d.prev_date_text ? " · 전일(" + esc(d.prev_date_text) + ") 대비" : "") + "</p>" + warn +
      "</div>" +
      '<div class="home-rated__tiles">' +
        '<div class="home-rated__tile"><span class="home-rated__label">송금 받으실 때</span><span class="home-rated__num">' + esc(d.ttb_text || "—") + '</span><small>TTB · 외화→원화</small></div>' +
        '<div class="home-rated__tile"><span class="home-rated__label">송금 보내실 때</span><span class="home-rated__num">' + esc(d.tts_text || "—") + '</span><small>TTS · 원화→외화</small></div>' +
        '<div class="home-rated__tile"><span class="home-rated__label">장부가격</span><span class="home-rated__num">' + esc(d.bkpr_text || "—") + '</span><small>' + (d.spread_text ? "스프레드 " + esc(d.spread_text) + "원" : "회계 기준") + "</small></div>" +
      "</div>" + calc + "</div>" +
      '<div class="home-rated__col">' +
      '<div class="home-rated__section">' +
        '<div class="home-rated__section-head"><span>최근 ' + s.points + "영업일 추이</span><small>" + esc(s.from_text) + " ~ " + esc(s.to_text) + "</small></div>" +
        rateChart(hist) +
        '<dl class="home-rated__stats">' +
          "<div><dt>최고</dt><dd>" + esc(s.high_text) + "<small>" + esc(s.high_date_text) + "</small></dd></div>" +
          "<div><dt>최저</dt><dd>" + esc(s.low_text) + "<small>" + esc(s.low_date_text) + "</small></dd></div>" +
          "<div><dt>평균</dt><dd>" + esc(s.mean_text) + "</dd></div>" +
          "<div><dt>기간 변동</dt><dd class=\"is-" + (s.period_change > 0 ? "up" : s.period_change < 0 ? "down" : "flat") + "\">" + (s.period_change == null ? "—" : (s.period_change > 0 ? "▲ " : s.period_change < 0 ? "▼ " : "") + Math.abs(s.period_change).toFixed(2) + "%") + "</dd></div>" +
          "<div><dt>변동성</dt><dd>" + (s.volatility == null ? "—" : s.volatility.toFixed(2) + "%") + "<small>일별 등락률 표준편차</small></dd></div>" +
        "</dl>" +
      "</div>" + "</div>";
    var per = d.rate / d.unit, fx = $("home-rate-fx"), krw = $("home-rate-krw");
    /* 회계 숫자 형식: 입력 중에도 천 단위 콤마를 붙이고, 계산에는 콤마를 뺀 값을 씁니다. 외화는 소수 2자리, 원화는 정수 */
    var formatField = function (el, maxDec) {
      var raw = el.value.replace(/[^\d.]/g, "");
      if (raw === "") { el.value = ""; return null; }
      var parts = raw.split("."), intPart = parts[0].replace(/^0+(?=\d)/, "") || "0";
      var dec = parts.length > 1 && maxDec > 0 ? parts.slice(1).join("").slice(0, maxDec) : null;
      el.value = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (dec !== null ? "." + dec : "");
      return Number(intPart + (dec ? "." + dec : ""));
    };
    var sync = function (from) {
      if (from === "fx") { var a = formatField(fx, 2); krw.value = a == null ? "" : fmt(Math.round(a * per), 0); }
      else { var b = formatField(krw, 0); fx.value = b == null ? "" : fmt(b / per, 2); }
    };
    fx.addEventListener("input", function () { sync("fx"); });
    krw.addEventListener("input", function () { sync("krw"); });
    sync("fx");
  }
  function openRateDetail(code) {
    if (!window.Common || !window.Common.openModal) return;
    var body = $("home-rate-body"), src = $("home-rate-source");
    $("home-rate-title").textContent = code + " 환율 상세";
    body.innerHTML = '<span class="home-loading">불러오는 중이에요</span>';
    window.Common.openModal("home-rate-modal");
    var c = rateCache[code];
    if (c && Date.now() - c.at < 10 * 60 * 1000) { renderRateDetail(c.data); return; }
    fetch("/api/home/rates/" + encodeURIComponent(code), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) { rateCache[code] = { at: Date.now(), data: d }; if (d.source_url) src.href = d.source_url; }
        renderRateDetail(d);
      })
      .catch(function () { body.innerHTML = '<span class="home-error">환율 정보를 불러오지 못했어요</span>'; });
  }
  $("home-rates-items").addEventListener("click", function (e) {
    var el = e.target.closest(".home-rate[data-code]");
    if (el) openRateDetail(el.getAttribute("data-code"));
  });
  $("home-rates-items").addEventListener("keydown", function (e) {
    var el = e.target.closest(".home-rate[data-code]");
    if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openRateDetail(el.getAttribute("data-code")); }
  });

  /* 2. 프로젝트 위젯 3종 (2-4): 오늘 챙길 것 · 프로젝트 현황 · 이번 주 일정 ---------
     서버는 일정 대상 프로젝트 전체(items)를 보내고, 기간·홀드 포함 등은 위젯 설정에 따라 화면에서 거릅니다. */
  var projectData = null, projectError = null;
  function dDayBadge(it) {
    var cls = it.d_day < 0 ? "badge-danger" : it.d_day === 0 ? "badge-warning" : "badge-primary";
    return '<span class="badge home-due__badge ' + cls + '">' + esc(it.d_day_text) + "</span>";
  }
  function holdBadge(it) { return it.state === "hold" ? '<span class="badge home-due__hold">' + esc(it.state_text) + "</span>" : ""; }
  function addDays(iso, n) { var d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function weekdayIndex(iso) { return (new Date(iso + "T00:00:00Z").getUTCDay() + 6) % 7; }   // 0 = 월요일
  function shortDate(iso) { return Number(iso.slice(5, 7)) + "/" + Number(iso.slice(8, 10)); }
  function renderDueSoon(p) {
    var o = opt("today"), list = $("home-today-list"), meta = $("home-today-meta");
    $("home-today-sub").textContent = o.days === 1 ? "내일까지 납기" : "납기 " + o.days + "일 이내";
    var items = p.items.filter(function (it) {
      return it.d_day <= o.days && (o.overdue || it.d_day >= 0) && (o.hold || it.state !== "hold");
    });
    meta.textContent = items.length ? items.length + "건" : "";
    if (!items.length) {
      list.innerHTML = '<li class="home-list__empty">' + (p.total ? "기간 안에 다가오는 납기가 없어요" : "등록된 프로젝트가 없어요") + "</li>";
      return;
    }
    var more = items.length - o.limit;
    list.innerHTML = items.slice(0, o.limit).map(function (it) {
      return '<li class="home-due__item" title="' + esc(it.customer + " · " + it.name + " · 납기 " + it.due_date) + '">' + dDayBadge(it) +
        '<span class="home-due__text"><span class="home-due__name">' + esc(it.name) + "</span>" +
        (o.customer ? '<span class="home-due__meta">' + esc(it.customer) + " · " + esc(it.stage_text) + "</span>" : "") + "</span>" + holdBadge(it) + "</li>";
    }).join("") + (more > 0 ? '<li class="home-due__more">외 ' + more + "건</li>" : "");
  }
  var STAGE_SCOPES = { active: ["active"], open: ["active", "hold"], all: ["active", "hold", "drop"] };
  var STAGE_SCOPE_TEXT = { active: "진행 중인 프로젝트의 단계", open: "진행·홀드 프로젝트의 단계", all: "전체 프로젝트의 단계 (드롭 포함)" };
  function renderProjectStatus(p) {
    var o = opt("projects"), box = $("home-projects-body"), link = box.getAttribute("data-create-url");
    $("home-projects-meta").textContent = p.total ? "전체 " + p.total + "건" : "";
    if (!p.total) {
      box.innerHTML = '<div class="state state-empty home-projects__empty"><p class="state-title">아직 프로젝트가 없어요</p>' +
        '<p>개발요청서 탭에서 고객사와 프로젝트를 만들 수 있어요.</p><a class="btn btn-soft btn-sm" href="' + esc(link) + '">개발요청서로 이동</a></div>';
      return;
    }
    if (!o.counts && !o.stages) {
      box.innerHTML = '<p class="home-projects__caption">위젯 설정에서 표시할 항목을 골라 주세요</p>';
      return;
    }
    var states = STAGE_SCOPES[o.scope] || STAGE_SCOPES.active;
    box.innerHTML =
      (o.counts ? '<div class="home-projects__counts">' + p.counts.map(function (c) {
        return '<div class="stat-tile home-projects__tile"><span class="stat-tile__label">' + esc(c.label) + '</span><span class="stat-tile__value">' + c.count + "</span></div>";
      }).join("") + "</div>" : "") +
      (o.stages ? '<p class="home-projects__caption">' + esc(STAGE_SCOPE_TEXT[o.scope] || STAGE_SCOPE_TEXT.active) + "</p>" +
        '<ol class="home-stages">' + p.stages.map(function (s) {
          var n = states.reduce(function (sum, st) { return sum + ((s.by_state || {})[st] || 0); }, 0);
          return '<li class="home-stages__item' + (n ? " has-count" : "") + '"><span class="home-stages__count">' + n + '</span><span class="home-stages__label">' + esc(s.label) + "</span></li>";
        }).join("") + "</ol>" : "");
  }
  function renderWeek(p) {
    var o = opt("week"), box = $("home-week-days"), start = addDays(p.today, -weekdayIndex(p.today)), days = [];
    for (var i = 0; i < o.weeks * 7; i++) {
      if (o.weekend || i % 7 < 5) days.push(addDays(start, i));
    }
    box.style.setProperty("--home-week-cols", o.weekend ? 7 : 5);
    $("home-week-meta").textContent = shortDate(days[0]) + " ~ " + shortDate(days[days.length - 1]) + " · 납기일 기준";
    box.innerHTML = days.map(function (iso) {
      var items = p.items.filter(function (it) { return it.due_date === iso && (o.hold || it.state !== "hold"); }).map(function (it) {
        return '<li class="home-week__item' + (it.state === "hold" ? " is-hold" : "") + '" title="' + esc(it.customer + " · " + it.name + " · " + it.stage_text + " · " + it.state_text) + '">' + esc(it.name) + "</li>";
      }).join("");
      return '<li class="home-week__day' + (iso === p.today ? " is-today" : "") + (iso < p.today ? " is-past" : "") + '"><span class="home-week__date"><strong>' +
        "월화수목금토일".charAt(weekdayIndex(iso)) + "</strong> " + shortDate(iso) + "</span>" +
        (items ? '<ul class="home-week__items">' + items + "</ul>" : '<span class="home-week__none">–</span>') + "</li>";
    }).join("");
  }
  function renderProjectError(message) {
    var msg = '<span class="home-error">' + esc(message || "프로젝트 정보를 불러오지 못했어요") + "</span>";
    $("home-today-list").innerHTML = '<li class="home-list__empty">' + msg + "</li>";
    $("home-projects-body").innerHTML = msg;
    $("home-week-days").innerHTML = '<li class="home-week__error">' + msg + "</li>";
    ["home-today-meta", "home-projects-meta", "home-week-meta"].forEach(function (id) { $(id).textContent = ""; });
  }
  function renderProjects() {   /* 설정을 바꿀 때도 다시 불러오지 않고 받아 둔 값으로 다시 그립니다 */
    if (projectError !== null) { renderProjectError(projectError); return; }
    if (!projectData) return;
    renderDueSoon(projectData);
    renderProjectStatus(projectData);
    renderWeek(projectData);
  }
  function loadProjects() {
    fetch("/api/home/projects", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (p.ok) { projectData = p; projectError = null; } else { projectError = p.error || ""; }
        renderProjects();
      })
      .catch(function () { projectError = ""; renderProjects(); });
  }

  /* 3. 뉴스 목록: 매체·건수·시간·제목 줄 수는 위젯 설정 ---------------------------- */
  function newsItem(it, o) {
    var badge = it.official ? "badge-info" : "";
    return '<li class="home-list__item"><a class="home-list__link" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="home-list__title"><span class="badge ' + badge + '">' + esc(it.source) + "</span>" + esc(it.title) + "</span>" +
      (o.time ? '<span class="home-list__meta">' + esc(it.time_text) + "</span>" : "") + "</a></li>";
  }
  function renderNews(n) {
    var o = opt("news"), list = $("home-news-list"), meta = $("home-news-meta");
    list.classList.toggle("is-two-line", !!o.twoLine);
    if (!n || !n.items || !n.items.length) {
      list.innerHTML = '<li class="home-list__empty">' + esc((n && n.error) || "뉴스를 불러오는 중이에요") + "</li>";
      meta.textContent = "";
      return;
    }
    var items = n.items.filter(function (it) { return !o.sources.length || o.sources.indexOf(it.source) !== -1; });
    list.innerHTML = items.length ? items.slice(0, o.limit).map(function (it) { return newsItem(it, o); }).join("")
      : '<li class="home-list__empty">선택한 매체의 최근 기사가 없어요</li>';
    meta.textContent = n.updated_text || "";
  }

  /* 4. 규제 업데이트: 국가·건수·새 소식만은 위젯 설정 ------------------------------ */
  function regItem(it) {
    return '<li class="home-list__item" data-published="' + esc(it.published_at) + '"><a class="home-list__link" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="home-list__title"><span class="badge badge-primary">' + esc(it.country) + "</span>" + esc(it.title) + "</span>" +
      '<span class="home-list__meta">' + (it.is_new ? '<span class="badge badge-danger">NEW</span>' : "") + esc(it.source) + " · " + esc(it.time_text) + "</span></a></li>";
  }
  function renderRegs(r) {
    var o = opt("regs"), list = $("home-reg-list"), meta = $("home-reg-meta");
    meta.textContent = r && r.checked_text ? r.checked_text : "";
    var items = (r && r.items || []).filter(function (it) {
      return (!o.countries.length || o.countries.indexOf(it.country) !== -1) && (!o.newOnly || it.is_new);
    });
    list.innerHTML = items.length ? items.slice(0, o.limit).map(regItem).join("")
      : '<li class="home-list__empty">' + (r && r.items && r.items.length ? "설정한 조건에 맞는 규제 소식이 없어요" : "최근 규제 소식이 없어요") + "</li>";
  }

  /* 6. 바이어 현지 시각 (7장) --------------------------------------------- */
  function partsIn(tz, date) {
    var f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "2-digit", minute: "2-digit", weekday: "short", hour12: false });
    var p = {};
    f.formatToParts(date).forEach(function (x) { p[x.type] = x.value; });
    return { hour: Number(p.hour) % 24, minute: p.minute, weekday: p.weekday };
  }
  function offsetHours(tz, date) {
    var local = new Date(date.toLocaleString("en-US", { timeZone: tz }));
    var seoul = new Date(date.toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
    return Math.round((local - seoul) / 3600000);
  }
  function statusOf(p) {
    if (p.weekday === "Sat" || p.weekday === "Sun") return { text: "주말", cls: "" };
    return p.hour >= 9 && p.hour < 18 ? { text: "업무 중", cls: "badge-success" } : { text: "업무 외", cls: "" };
  }
  function currentCities() {
    if (state.clockMode === "custom" && state.customCities && state.customCities.length) return state.customCities;
    return state.data.buyer_cities || [];
  }
  function renderClock() {
    var o = opt("clock"), list = $("home-clock-list"), card = list.closest("[data-widget]");
    var cities = currentCities().slice(0, o.count);
    card.classList.toggle("show-offset", !!o.offset);
    card.classList.toggle("show-status", !!o.status);
    list.style.setProperty("--home-clock-cols", Math.max(1, cities.length));
    if (!cities.length) { list.innerHTML = '<li class="home-clock__empty">표시할 도시가 없어요. "편집"에서 골라 주세요.</li>'; return; }
    var now = new Date();
    list.innerHTML = cities.map(function (c, i) {
      var p = partsIn(c.tz, now), s = statusOf(p), off = offsetHours(c.tz, now);
      var rank = state.clockMode === "top_export" && c.rank ? '<span class="home-clock__rank">' + c.rank + "</span>" : "";
      return '<li class="home-clock__row" title="' + esc(c.country + " · " + c.tz) + '">' +
        '<span class="home-clock__city">' + rank + esc(c.name) + '<span class="home-clock__code">' + esc(c.code) + "</span></span>" +
        '<span class="home-clock__time">' + String(p.hour).padStart(2, "0") + ":" + p.minute + "</span>" +
        '<span class="home-clock__offset">' + (off === 0 ? "±0h" : (off > 0 ? "+" : "−") + Math.abs(off) + "h") + "</span>" +
        '<span class="badge home-clock__status ' + s.cls + '">' + s.text + "</span></li>";
    }).join("");
  }
  function setClockMode(mode) {
    state.clockMode = mode;
    storage.set("cosmoa.clock.mode", mode);
    document.querySelectorAll("[data-clock-mode]").forEach(function (b) {
      var on = b.getAttribute("data-clock-mode") === mode;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", String(on));
    });
    $("home-clock-edit").hidden = mode !== "custom";
    if (mode === "custom" && !(state.customCities && state.customCities.length)) {
      // 처음 "내가 선택"으로 바꾸면 현재 수출 상위국 4곳이 미리 선택된 상태 (7-3)
      state.customCities = (state.data.buyer_cities || []).map(function (c) { return { code: c.code, country: c.country, name: c.name, tz: c.tz }; });
      storage.setJSON("cosmoa.clock.cities", state.customCities);
    }
    renderClock();
  }
  document.querySelectorAll("[data-clock-mode]").forEach(function (b) {
    b.addEventListener("click", function () { setClockMode(b.getAttribute("data-clock-mode")); });
  });

  /* 도시 편집 모달 (7-3) */
  var picked = [];
  function renderCityOptions(filter) {
    var q = (filter || "").trim().toLowerCase();
    var opts = (state.data.city_options || []).filter(function (o) {
      return !q || (o.country + o.name + o.code).toLowerCase().indexOf(q) !== -1;
    });
    $("home-city-count").textContent = picked.length + " / 4";
    $("home-city-options").innerHTML = opts.map(function (o) {
      var idx = picked.findIndex(function (p) { return p.tz === o.tz && p.name === o.name; });
      var on = idx !== -1, full = picked.length >= 4 && !on;
      return '<li><label class="home-city-option' + (full ? " is-disabled" : "") + '">' +
        '<input type="checkbox" data-tz="' + esc(o.tz) + '" data-name="' + esc(o.name) + '"' + (on ? " checked" : "") + (full ? " disabled" : "") + ">" +
        "<span>" + esc(o.country) + " · " + esc(o.name) + "</span>" +
        "<small>" + (on ? (idx + 1) + "번째" : esc(o.code)) + "</small></label></li>";
    }).join("") || '<li class="home-list__empty">검색 결과가 없어요</li>';
  }
  $("home-clock-edit").addEventListener("click", function () {
    picked = (state.customCities || []).slice();
    $("home-city-search").value = "";
    renderCityOptions("");
    setTimeout(function () { $("home-city-search").focus(); }, 50);
  });
  $("home-city-search").addEventListener("input", function (e) { renderCityOptions(e.target.value); });
  $("home-city-options").addEventListener("change", function (e) {
    var cb = e.target.closest("input[type=checkbox]");
    if (!cb) return;
    var tz = cb.getAttribute("data-tz"), name = cb.getAttribute("data-name");
    var opt = (state.data.city_options || []).find(function (o) { return o.tz === tz && o.name === name; });
    if (cb.checked && opt && picked.length < 4) picked.push({ code: opt.code, country: opt.country, name: opt.name, tz: opt.tz });
    else picked = picked.filter(function (p) { return !(p.tz === tz && p.name === name); });
    renderCityOptions($("home-city-search").value);
  });
  $("home-city-save").addEventListener("click", function () {
    state.customCities = picked.slice();
    storage.setJSON("cosmoa.clock.cities", state.customCities);
    renderClock();
    window.Common.closeModal("home-city-modal");
  });

  /* 8. 위젯 배치·설정 (2-3): 사용자별 localStorage. 업무 DB users.home_widgets 는 7단계에서 도입 예정 ----
     배치 항목 = { id, size: 가로 3~12칸, h: 높이 px (0 = 내용에 맞춤), o: 위젯별 이름·표시 설정 } */
  function nums(list, unit) { return list.map(function (n) { return [n, n + unit]; }); }
  function dataOptions(list) { return (list || []).map(function (v) { return [v, v]; }); }
  var WIDGETS = {
    today: { name: "오늘 챙길 것", size: 4, def: { days: 3, limit: 5, overdue: true, hold: true, customer: true }, fields: [
      { key: "days", label: "납기 기준", type: "select", options: [[1, "내일까지"], [3, "3일 이내"], [7, "7일 이내"], [14, "14일 이내"], [30, "30일 이내"]] },
      { key: "limit", label: "최대 표시 건수", type: "select", options: nums([3, 5, 8, 10, 15, 20], "건") },
      { key: "overdue", label: "납기가 지난 프로젝트 포함", type: "check" },
      { key: "hold", label: "홀드 프로젝트 포함", type: "check" },
      { key: "customer", label: "고객사·단계 표시", type: "check" },
    ] },
    week: { name: "이번 주 일정", size: 8, def: { weeks: 1, weekend: true, hold: true }, fields: [
      { key: "weeks", label: "기간", type: "select", options: [[1, "이번 주"], [2, "2주 (다음 주까지)"], [4, "4주"]] },
      { key: "weekend", label: "토·일 표시", type: "check" },
      { key: "hold", label: "홀드 프로젝트 포함", type: "check" },
    ] },
    projects: { name: "프로젝트 현황", size: 4, def: { counts: true, stages: true, scope: "active" }, fields: [
      { key: "counts", label: "상태별 건수 (진행·홀드·드롭)", type: "check" },
      { key: "stages", label: "단계별 건수", type: "check" },
      { key: "scope", label: "단계별 건수 대상", type: "select", options: [["active", "진행 중인 프로젝트"], ["open", "진행 + 홀드"], ["all", "전체 (드롭 포함)"]] },
    ] },
    rates: { name: "환율", size: 4, def: { codes: ["USD", "JPY", "CNH"], change: true }, fields: [
      { key: "codes", label: "표시 통화 (최대 8개)", type: "multi", max: 8,
        options: function () { return ((state.data.rates && state.data.rates.items) || []).map(function (it) { return [it.code, it.code + " · " + it.name]; }); } },
      { key: "change", label: "전일 대비 등락 표시", type: "check" },
    ] },
    clock: { name: "바이어 현지 시각", size: 4, def: { count: 4, offset: false, status: false }, fields: [
      { key: "count", label: "표시 도시 수", type: "select", options: nums([1, 2, 3, 4], "곳") },
      { key: "offset", label: "한국과의 시차 표시", type: "check" },
      { key: "status", label: "업무 상태 표시 (업무 중 · 업무 외 · 주말)", type: "check" },
    ] },
    news: { name: "화장품 뉴스", size: 12, def: { limit: 6, sources: [], time: true, twoLine: false }, fields: [
      { key: "limit", label: "표시 건수", type: "select", options: nums([3, 6, 10, 15, 20, 30], "건") },
      { key: "sources", label: "매체 (고르지 않으면 전체)", type: "multi", allowEmpty: true, options: function () { return dataOptions(state.data.news_sources); } },
      { key: "time", label: "게시 시간 표시", type: "check" },
      { key: "twoLine", label: "제목을 두 줄까지 표시", type: "check" },
    ] },
    regs: { name: "규제 업데이트", size: 6, def: { limit: 5, countries: [], newOnly: false }, fields: [
      { key: "limit", label: "표시 건수", type: "select", options: nums([3, 5, 10, 15, 20, 30], "건") },
      { key: "countries", label: "국가 (고르지 않으면 전체)", type: "multi", allowEmpty: true, options: function () { return dataOptions(state.data.reg_countries); } },
      { key: "newOnly", label: "24시간 이내 새 소식만", type: "check" },
    ] },
  };
  var WIDGET_IDS = Object.keys(WIDGETS);
  var DEFAULT_LAYOUT = [["today", 4], ["week", 8], ["projects", 4], ["rates", 4], ["clock", 4], ["news", 12]]
    .map(function (a) { return { id: a[0], size: a[1], h: 0, o: {} }; });
  var MIN_SPAN = 3, MIN_H = 140, MAX_H = 1600, HEIGHTS = [0, 200, 280, 360, 480, 640, 800];
  var WIDTH_NAMES = { 3: "1/4", 4: "1/3", 6: "1/2", 8: "2/3", 9: "3/4", 12: "전체" };
  var ICONS = {
    grip: '<circle cx="9" cy="6" r="1"></circle><circle cx="15" cy="6" r="1"></circle><circle cx="9" cy="12" r="1"></circle><circle cx="15" cy="12" r="1"></circle><circle cx="9" cy="18" r="1"></circle><circle cx="15" cy="18" r="1"></circle>',
    left: '<path d="M15 6l-6 6 6 6"></path>', right: '<path d="M9 6l6 6-6 6"></path>', close: '<path d="M6 6l12 12M18 6L6 18"></path>',
    settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"></path>',
    resize: '<path d="M21 13l-8 8M21 6L6 21"></path>',
  };
  function icon(name) {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }
  var grid = $("home-widgets"), layoutKey = "cosmoa.home.widgets." + ($("home").getAttribute("data-user-id") || "guest");
  var layout = [], editing = false, dragId = null, resizing = null, settingsId = null;

  function widgetEl(id) { return grid.querySelector('[data-widget="' + id + '"]'); }
  function indexOfWidget(id) { return layout.findIndex(function (w) { return w.id === id; }); }
  function findItem(id) { return layout[indexOfWidget(id)] || null; }
  function opt(id) {   /* 기본값 위에 저장된 설정을 얹은 값. 배치를 읽기 전에도 기본값으로 동작 */
    var w = layout && findItem(id), def = WIDGETS[id].def, out = {};
    Object.keys(def).forEach(function (k) { out[k] = w && w.o[k] !== undefined ? w.o[k] : def[k]; });
    return out;
  }
  function widthText(n) { return (WIDTH_NAMES[n] ? WIDTH_NAMES[n] + " · " : "") + n + "/12칸"; }
  function sizeText(w) { return (WIDTH_NAMES[w.size] || w.size + "/12") + " · " + (w.h ? w.h + "px" : "높이 자동"); }
  function cleanSize(v) { return typeof v === "number" && v % 1 === 0 && v >= MIN_SPAN && v <= 12 ? v : null; }
  function cleanHeight(v) { return typeof v === "number" && v % 1 === 0 && v >= MIN_H && v <= MAX_H ? v : 0; }
  function cleanOpts(id, o) {   /* 저장값·입력값 검증: 알 수 없는 키·값은 버리고 기본값을 씀 */
    var out = {};
    if (!o || typeof o !== "object") return out;
    if (typeof o.title === "string" && o.title.trim()) out.title = o.title.trim().slice(0, 30);
    WIDGETS[id].fields.forEach(function (f) {
      var v = o[f.key];
      if (f.type === "check" && typeof v === "boolean") out[f.key] = v;
      else if (f.type === "select" && f.options.some(function (op) { return op[0] === v; })) out[f.key] = v;
      else if (f.type === "multi" && Array.isArray(v)) {
        var seen = {}, list = v.filter(function (s) { return typeof s === "string" && !seen[s] && (seen[s] = true); }).slice(0, f.max || 50);
        if (list.length || f.allowEmpty) out[f.key] = list;
      }
    });
    return out;
  }
  function cloneLayout(items) {
    return items.map(function (w) { return { id: w.id, size: w.size, h: w.h || 0, o: JSON.parse(JSON.stringify(w.o || {})) }; });
  }
  function loadLayout() {   /* 저장값이 손상되었거나 없는 위젯이 있어도 화면이 깨지지 않게 걸러냅니다 (v1 형식도 읽음) */
    var saved = storage.getJSON(layoutKey), seen = {};
    if (!saved || !Array.isArray(saved.items)) return cloneLayout(DEFAULT_LAYOUT);
    return saved.items.filter(function (w) {
      if (!w || !WIDGETS[w.id] || !cleanSize(w.size) || seen[w.id]) return false;
      seen[w.id] = true;
      return true;
    }).map(function (w) { return { id: w.id, size: w.size, h: cleanHeight(w.h), o: cleanOpts(w.id, w.o) }; });
  }
  function applySize(w) {   /* 크기만 반영 (끌어서 조절하는 중에는 DOM 순서를 건드리지 않음) */
    var el = widgetEl(w.id);
    for (var n = MIN_SPAN; n <= 12; n++) el.classList.toggle("home-widget--" + n, n === w.size);
    el.classList.toggle("is-fixed", w.h > 0);
    el.style.height = w.h > 0 ? w.h + "px" : "";
    el.querySelector(".home-widget__size").textContent = sizeText(w);
  }
  function applyLayout() {
    WIDGET_IDS.forEach(function (id) { widgetEl(id).hidden = indexOfWidget(id) === -1; });
    layout.forEach(function (w) {
      var el = widgetEl(w.id);
      applySize(w);
      el.querySelector("[data-widget-title]").textContent = w.o.title || WIDGETS[w.id].name;
      grid.appendChild(el);
    });
    grid.appendChild($("home-widgets-empty"));
    $("home-widgets-empty").hidden = layout.length > 0;
    var hidden = WIDGET_IDS.filter(function (id) { return indexOfWidget(id) === -1; });
    $("home-widget-add").innerHTML = hidden.length ? hidden.map(function (id) {
      return '<button class="btn btn-soft btn-sm" type="button" data-widget-add="' + id + '">+ ' + esc(WIDGETS[id].name) + "</button>";
    }).join("") : '<span class="text-caption">모든 위젯을 표시하고 있어요</span>';
  }
  function commitLayout() {
    storage.setJSON(layoutKey, { v: 2, items: layout });
    applyLayout();
    renderAll();
    renderProjects();
  }
  function moveWidget(id, delta) {
    var from = indexOfWidget(id), to = from + delta;
    if (from === -1 || to < 0 || to >= layout.length) return;
    layout.splice(to, 0, layout.splice(from, 1)[0]);
    commitLayout();
  }
  function dropWidget(id, targetId, after) {
    if (id === targetId) return;
    var moved = layout.splice(indexOfWidget(id), 1)[0];
    layout.splice(indexOfWidget(targetId) + (after ? 1 : 0), 0, moved);
    commitLayout();
  }
  function setEditing(on) {
    editing = on;
    grid.classList.toggle("is-editing", on);
    $("home-editbar").hidden = !on;
    var toggle = $("home-edit-toggle");
    toggle.hidden = on;
    WIDGET_IDS.forEach(function (id) { widgetEl(id).draggable = on; });
    if (!on) { toggle.focus(); clearDropMarks(); }
  }
  function clearDropMarks() {
    grid.querySelectorAll(".is-drop-before, .is-drop-after").forEach(function (el) { el.classList.remove("is-drop-before", "is-drop-after"); });
  }
  function dropAfter(target, e) { var r = target.getBoundingClientRect(); return e.clientX > r.left + r.width / 2; }

  /* 8-1. 모서리 끌기로 크기 조절: 가로는 12칸 격자에 맞추고, 세로는 20px 단위. 두 번 누르면 높이 자동. 화살표 키도 지원 */
  function startResize(e, handle) {
    var card = handle.closest("[data-widget]"), w = findItem(card.getAttribute("data-widget"));
    e.preventDefault();
    card.draggable = false;
    card.classList.add("is-resizing");
    resizing = { w: w, card: card, handle: handle, left: card.getBoundingClientRect().left, y: e.clientY, startH: w.h };
    handle.setPointerCapture(e.pointerId);
  }
  function moveResize(e) {
    var r = resizing;
    if (!r) return;
    var gap = parseFloat(getComputedStyle(grid).columnGap) || 0, col = (grid.clientWidth - 11 * gap) / 12;
    var span = Math.max(MIN_SPAN, Math.min(12, Math.round((e.clientX - r.left + gap) / (col + gap))));
    var h = r.w.h;
    if (r.startH || Math.abs(e.clientY - r.y) > 8) {
      h = Math.max(MIN_H, Math.min(MAX_H, Math.round((e.clientY - r.card.getBoundingClientRect().top) / 20) * 20));
    }
    if (span !== r.w.size || h !== r.w.h) { r.w.size = span; r.w.h = h; applySize(r.w); }
  }
  function endResize() {
    if (!resizing) return;
    resizing.card.classList.remove("is-resizing");
    resizing.card.draggable = editing;
    resizing = null;
    commitLayout();
  }
  function keyResize(e, handle) {
    var card = handle.closest("[data-widget]"), w = findItem(card.getAttribute("data-widget"));
    var keys = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }, k = keys[e.key];
    if (!k) return;
    e.preventDefault();
    w.size = Math.max(MIN_SPAN, Math.min(12, w.size + k[0]));
    if (k[1]) w.h = Math.max(MIN_H, Math.min(MAX_H, Math.round((w.h || card.offsetHeight) / 20) * 20 + k[1]));
    commitLayout();
    handle.focus();
  }

  /* 8-2. 위젯 설정 창: 이름 · 너비 · 높이 · 위젯별 표시 내용 */
  function fieldHtml(f, value) {
    var id = "home-wset-" + f.key;
    if (f.type === "check") {
      return '<label class="form-check home-wset__check"><input type="checkbox" id="' + id + '" data-field="' + f.key + '"' + (value ? " checked" : "") + "> " + esc(f.label) + "</label>";
    }
    if (f.type === "select") {
      return '<div class="form-group home-wset__group"><label class="form-label" for="' + id + '">' + esc(f.label) + "</label>" +
        '<select class="form-control form-control-sm" id="' + id + '" data-field="' + f.key + '">' + f.options.map(function (op) {
          return '<option value="' + esc(op[0]) + '"' + (op[0] === value ? " selected" : "") + ">" + esc(op[1]) + "</option>";
        }).join("") + "</select></div>";
    }
    var options = f.options();
    return '<fieldset class="home-wset__multi" data-field="' + f.key + '" data-max="' + (f.max || 0) + '"><legend class="form-label">' + esc(f.label) + "</legend>" +
      (options.length ? '<div class="home-wset__options">' + options.map(function (op) {
        return '<label class="form-check"><input type="checkbox" value="' + esc(op[0]) + '"' + (value.indexOf(op[0]) !== -1 ? " checked" : "") + "> " + esc(op[1]) + "</label>";
      }).join("") + "</div>" : '<p class="form-help">아직 불러온 데이터가 없어요. 잠시 후 다시 열어 주세요.</p>') + "</fieldset>";
  }
  function syncMultiLimits() {   /* 최대 개수를 채우면 나머지 선택지를 잠급니다 */
    $("home-widget-form").querySelectorAll(".home-wset__multi").forEach(function (fs) {
      var max = Number(fs.getAttribute("data-max")), boxes = fs.querySelectorAll("input"), n = fs.querySelectorAll("input:checked").length;
      boxes.forEach(function (b) { b.disabled = max > 0 && n >= max && !b.checked; });
    });
  }
  function openSettings(id) {
    var w = findItem(id), spec = WIDGETS[id], o = opt(id), widths = [];
    settingsId = id;
    for (var n = MIN_SPAN; n <= 12; n++) widths.push([n, widthText(n)]);
    var heights = HEIGHTS.indexOf(w.h) === -1 ? HEIGHTS.concat([w.h]).sort(function (a, b) { return a - b; }) : HEIGHTS;
    $("home-widget-modal-title").textContent = spec.name + " 설정";
    $("home-widget-form").innerHTML =
      '<div class="form-group home-wset__group"><label class="form-label" for="home-wset-title">위젯 이름</label>' +
        '<input class="form-control form-control-sm" id="home-wset-title" type="text" maxlength="30" autocomplete="off" placeholder="' + esc(spec.name) + '" value="' + esc(w.o.title || "") + '"></div>' +
      '<div class="home-wset__pair">' +
        fieldHtml({ key: "size", label: "너비", type: "select", options: widths }, w.size) +
        fieldHtml({ key: "h", label: "높이", type: "select", options: heights.map(function (h) { return [h, h ? h + "px" : "자동 (내용에 맞춤)"]; }) }, w.h) +
      "</div>" +
      '<p class="form-help home-wset__help">높이를 정하면 넘치는 내용은 위젯 안에서 스크롤돼요. 편집 중 위젯 오른쪽 아래 모서리를 끌어서도 바꿀 수 있어요.</p>' +
      '<p class="home-wset__section">표시 내용</p>' +
      spec.fields.map(function (f) { return fieldHtml(f, o[f.key]); }).join("");
    syncMultiLimits();
    window.Common.openModal("home-widget-modal");
    setTimeout(function () { $("home-wset-title").focus(); }, 50);
  }
  function saveSettings() {
    var w = findItem(settingsId);
    if (!w) return;
    var form = $("home-widget-form"), raw = { title: $("home-wset-title").value };
    w.size = cleanSize(Number(form.querySelector('[data-field="size"]').value)) || w.size;
    w.h = cleanHeight(Number(form.querySelector('[data-field="h"]').value));
    WIDGETS[settingsId].fields.forEach(function (f) {
      var el = form.querySelector('[data-field="' + f.key + '"]');
      if (f.type === "check") raw[f.key] = el.checked;
      else if (f.type === "select") {
        var match = f.options.filter(function (op) { return String(op[0]) === el.value; })[0];
        if (match) raw[f.key] = match[0];
      } else raw[f.key] = [].map.call(el.querySelectorAll("input:checked"), function (c) { return c.value; });
    });
    w.o = cleanOpts(settingsId, raw);
    commitLayout();
    window.Common.closeModal("home-widget-modal");
  }

  function initWidgets() {
    WIDGET_IDS.forEach(function (id) {
      var name = esc(WIDGETS[id].name), card = widgetEl(id), tools = document.createElement("div"), handle = document.createElement("button");
      tools.className = "home-widget__tools";
      tools.innerHTML =
        '<span class="home-widget__grip" title="끌어서 옮기기">' + icon("grip") + "</span>" +
        '<button class="home-widget__tool" type="button" data-widget-move="-1" aria-label="' + name + ' 앞으로" title="앞으로">' + icon("left") + "</button>" +
        '<button class="home-widget__tool" type="button" data-widget-move="1" aria-label="' + name + ' 뒤로" title="뒤로">' + icon("right") + "</button>" +
        '<span class="home-widget__size"></span>' +
        '<button class="home-widget__tool home-widget__settings" type="button" data-widget-settings aria-label="' + name + ' 설정" title="이름·크기·표시 내용 설정">' + icon("settings") + "</button>" +
        '<button class="home-widget__tool" type="button" data-widget-remove aria-label="' + name + ' 숨기기" title="숨기기">' + icon("close") + "</button>";
      handle.type = "button";
      handle.className = "home-widget__resize";
      handle.setAttribute("data-widget-resize", "");
      handle.setAttribute("aria-label", name + " 크기 조절 (화살표 키: 너비·높이, 두 번 누르면 높이 자동)");
      handle.title = "끌어서 크기 조절 · 두 번 누르면 높이 자동";
      handle.innerHTML = icon("resize");
      card.insertBefore(tools, card.firstChild);
      card.appendChild(handle);
    });
    layout = loadLayout();
    applyLayout();

    $("home-edit-toggle").addEventListener("click", function () { setEditing(true); $("home-edit-done").focus(); });
    $("home-edit-done").addEventListener("click", function () { setEditing(false); });
    $("home-edit-reset").addEventListener("click", function () { layout = cloneLayout(DEFAULT_LAYOUT); commitLayout(); });
    $("home-widget-add").addEventListener("click", function (e) {
      var b = e.target.closest("[data-widget-add]");
      if (!b) return;
      var id = b.getAttribute("data-widget-add");
      layout.push({ id: id, size: WIDGETS[id].size, h: 0, o: {} });
      commitLayout();
      $("home-edit-done").focus();
    });
    $("home-widget-save").addEventListener("click", saveSettings);
    $("home-widget-form").addEventListener("submit", function (e) { e.preventDefault(); saveSettings(); });
    $("home-widget-form").addEventListener("change", syncMultiLimits);
    $("home-widget-default").addEventListener("click", function () {
      var w = findItem(settingsId);
      if (!w) return;
      w.size = WIDGETS[settingsId].size;
      w.h = 0;
      w.o = {};
      commitLayout();
      window.Common.closeModal("home-widget-modal");
    });
    grid.addEventListener("click", function (e) {
      var card = e.target.closest("[data-widget]"), b = e.target.closest("button");
      if (!editing || !card || !b || !b.closest(".home-widget__tools")) return;
      var id = card.getAttribute("data-widget");
      if (b.hasAttribute("data-widget-remove")) {
        layout.splice(indexOfWidget(id), 1);
        commitLayout();
        $("home-edit-done").focus();
      } else if (b.hasAttribute("data-widget-move")) {
        moveWidget(id, Number(b.getAttribute("data-widget-move")));
        b.focus();
      } else if (b.hasAttribute("data-widget-settings")) {
        openSettings(id);
      }
    });
    grid.addEventListener("pointerdown", function (e) {
      var handle = editing && e.target.closest("[data-widget-resize]");
      if (handle && e.button === 0) startResize(e, handle);
    });
    grid.addEventListener("pointermove", moveResize);
    grid.addEventListener("pointerup", endResize);
    grid.addEventListener("pointercancel", endResize);
    grid.addEventListener("dblclick", function (e) {
      var handle = editing && e.target.closest("[data-widget-resize]");
      if (!handle) return;
      findItem(handle.closest("[data-widget]").getAttribute("data-widget")).h = 0;
      commitLayout();
    });
    grid.addEventListener("keydown", function (e) {
      var handle = editing && e.target.closest("[data-widget-resize]");
      if (handle) keyResize(e, handle);
    });
    grid.addEventListener("dragstart", function (e) {
      var card = editing && !resizing && e.target.closest && e.target.closest("[data-widget]");
      if (!card || e.target.closest("[data-widget-resize]")) { if (editing) e.preventDefault(); return; }
      dragId = card.getAttribute("data-widget");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", dragId);
      card.classList.add("is-dragging");
    });
    grid.addEventListener("dragover", function (e) {
      if (!dragId) return;
      e.preventDefault();
      clearDropMarks();
      var target = e.target.closest("[data-widget]");
      if (target && target.getAttribute("data-widget") !== dragId) target.classList.add(dropAfter(target, e) ? "is-drop-after" : "is-drop-before");
    });
    grid.addEventListener("drop", function (e) {
      if (!dragId) return;
      e.preventDefault();
      var target = e.target.closest("[data-widget]");
      if (target) dropWidget(dragId, target.getAttribute("data-widget"), dropAfter(target, e));
    });
    grid.addEventListener("dragend", function () {
      if (dragId) widgetEl(dragId).classList.remove("is-dragging");
      dragId = null;
      clearDropMarks();
    });
  }

  /* 7. 그리기 + 갱신 -------------------------------------------------------- */
  function renderAll() {
    var d = state.data;
    renderRates(d.rates);
    renderNews(d.news);
    renderRegs(d.regulations);
    renderClock();
  }

  function needsMore(d) {
    return (d.refreshing && d.refreshing.length) ||
      !(d.news && d.news.items && d.news.items.length) ||
      !(d.regulations && d.regulations.items && d.regulations.items.length);
  }

  var pollCount = 0;
  function pollData() {
    if (pollCount++ > 20) return;  // 최대 약 3분간만 재시도
    fetch("/api/home/data", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        state.data = d;
        renderAll();
        if (needsMore(d)) setTimeout(pollData, 8000);
      })
      .catch(function () { setTimeout(pollData, 15000); });
  }

  /* 규제 새 소식 확인 (8-3): 10분마다 */
  function pollRegulations() {
    var since = state.data.regulations && state.data.regulations.latest_at;
    var url = "/api/home/regulations" + (since ? "?since=" + encodeURIComponent(since) : "");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (r) {
        if (!r || !r.items || !r.items.length) return;
        var cur = state.data.regulations || { items: [] };
        var urls = {};
        cur.items.forEach(function (it) { urls[it.url] = true; });
        var fresh = r.items.filter(function (it) { return !urls[it.url]; });
        if (!fresh.length) return;
        cur.items = fresh.concat(cur.items).slice(0, 30);
        cur.latest_at = r.latest_at || cur.latest_at;
        cur.checked_text = r.checked_text || cur.checked_text;
        state.data.regulations = cur;
        renderRegs(cur);
      })
      .catch(function () { /* 다음 주기에 다시 */ });
  }

  /* 시작 */
  setClockMode(state.clockMode);
  initWidgets();
  renderAll();
  loadProjects();
  if (needsMore(state.data)) setTimeout(pollData, 4000);
  setInterval(pollRegulations, 10 * 60 * 1000);

  // 매 분 0초에 맞춰 현지 시각 갱신 (7-1)
  setTimeout(function () { renderClock(); setInterval(renderClock, 60000); }, (60 - new Date().getSeconds()) * 1000);
})();
