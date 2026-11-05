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
     홈의 모달 2개를 <body> 바로 아래로 옮겨 항상 화면 가운데에 뜨게 합니다. (common.js 는 document 위임이라 그대로 동작) */
  ["home-city-modal", "home-rate-modal"].forEach(function (id) {
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
  var NEWS_LIMIT = 6, REG_LIMIT = 5, DUE_LIMIT = 5;   // 홈의 뉴스 · 규제 · 오늘 챙길 것 표시 건수

  /* 1. 환율 띠 -------------------------------------------------------------- */
  function renderRates(r) {
    var box = $("home-rates-items"), meta = $("home-rates-meta");
    if (!r || !r.items || !r.items.length) {
      box.innerHTML = '<span class="home-error">' + esc((r && r.error) || "환율 정보를 불러오지 못했어요") + "</span>";
      meta.textContent = "";
      return;
    }
    box.innerHTML = r.items.map(function (it) {
      var unit = it.unit === 100 ? " <small>(100)</small>" : "";
      var title = it.name + (it.unit === 100 ? " · 100" + it.code + " 기준" : " · 1" + it.code + " 기준");
      var warn = "";
      if (it.warning) { /* 전일 대비 급변 — 서버 RATE_WARN_PCT 기준 (명세 13-1) */
        title += " · 전일 대비 " + it.change_text + " 변동, 값 확인 필요";
        warn = '<span class="home-rate__warn" role="img" aria-label="이상값 경고">!</span>';
      }
      return '<div class="home-rate' + (it.warning ? " is-warn" : "") + '" role="button" tabindex="0" data-code="' + esc(it.code) + '" title="' + esc(title + " · 누르면 상세 보기") + '">' +
        '<span class="home-rate__code">' + esc(it.code) + unit + warn + "</span>" +
        '<span class="home-rate__value"><span class="home-rate__rate">' + esc(it.rate_text) + "</span>" +
        '<span class="home-rate__change is-' + esc(it.direction) + '">' + arrow(it.direction) + " " + esc(it.change_text) + "</span></span></div>";
    }).join("");
    meta.textContent = "수출입은행 · " + r.date_text + " 기준";
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

  /* 2. 프로젝트 위젯 3종 (2-4): 오늘 챙길 것 · 프로젝트 현황 · 이번 주 일정 --------- */
  function dDayBadge(it) {
    var cls = it.d_day < 0 ? "badge-danger" : it.d_day === 0 ? "badge-warning" : "badge-primary";
    return '<span class="badge home-due__badge ' + cls + '">' + esc(it.d_day_text) + "</span>";
  }
  function holdBadge(it) { return it.state === "hold" ? '<span class="badge home-due__hold">' + esc(it.state_text) + "</span>" : ""; }
  function renderDueSoon(p) {
    var list = $("home-today-list"), meta = $("home-today-meta"), items = p.due_soon;
    meta.textContent = items.length ? items.length + "건" : "";
    if (!items.length) {
      list.innerHTML = '<li class="home-list__empty">' + (p.total ? "3일 안에 다가오는 납기가 없어요" : "등록된 프로젝트가 없어요") + "</li>";
      return;
    }
    var more = items.length - DUE_LIMIT;
    list.innerHTML = items.slice(0, DUE_LIMIT).map(function (it) {
      return '<li class="home-due__item" title="' + esc("납기 " + it.due_date) + '">' + dDayBadge(it) +
        '<span class="home-due__text"><span class="home-due__name">' + esc(it.name) + "</span>" +
        '<span class="home-due__meta">' + esc(it.customer) + " · " + esc(it.stage_text) + "</span></span>" + holdBadge(it) + "</li>";
    }).join("") + (more > 0 ? '<li class="home-due__more">외 ' + more + "건</li>" : "");
  }
  function renderProjectStatus(p) {
    var box = $("home-projects-body"), link = box.getAttribute("data-create-url");
    $("home-projects-meta").textContent = p.total ? "전체 " + p.total + "건" : "";
    if (!p.total) {
      box.innerHTML = '<div class="state state-empty home-projects__empty"><p class="state-title">아직 프로젝트가 없어요</p>' +
        '<p>개발요청서 탭에서 고객사와 프로젝트를 만들 수 있어요.</p><a class="btn btn-soft btn-sm" href="' + esc(link) + '">개발요청서로 이동</a></div>';
      return;
    }
    box.innerHTML =
      '<div class="home-projects__counts">' + p.counts.map(function (c) {
        return '<div class="stat-tile home-projects__tile"><span class="stat-tile__label">' + esc(c.label) + '</span><span class="stat-tile__value">' + c.count + "</span></div>";
      }).join("") + "</div>" +
      '<p class="home-projects__caption">진행 중인 프로젝트의 단계</p>' +
      '<ol class="home-stages">' + p.stages.map(function (s) {
        return '<li class="home-stages__item' + (s.count ? " has-count" : "") + '"><span class="home-stages__count">' + s.count + '</span><span class="home-stages__label">' + esc(s.label) + "</span></li>";
      }).join("") + "</ol>";
  }
  function renderWeek(p) {
    $("home-week-meta").textContent = p.week.range_text + " · 납기일 기준";
    $("home-week-days").innerHTML = p.week.days.map(function (d) {
      var items = d.items.map(function (it) {
        return '<li class="home-week__item' + (it.state === "hold" ? " is-hold" : "") + '" title="' + esc(it.customer + " · " + it.name + " · " + it.stage_text + " · " + it.state_text) + '">' + esc(it.name) + "</li>";
      }).join("");
      return '<li class="home-week__day' + (d.is_today ? " is-today" : "") + '"><span class="home-week__date"><strong>' + esc(d.weekday) + "</strong> " + esc(d.label) + "</span>" +
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
  function loadProjects() {
    fetch("/api/home/projects", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (!p.ok) { renderProjectError(p.error); return; }
        renderDueSoon(p);
        renderProjectStatus(p);
        renderWeek(p);
      })
      .catch(function () { renderProjectError(); });
  }

  /* 3. 뉴스 목록 ------------------------------------------------------------ */
  function newsItem(it) {
    var badge = it.official ? "badge-info" : "";
    return '<li class="home-list__item"><a class="home-list__link" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="home-list__title"><span class="badge ' + badge + '">' + esc(it.source) + "</span>" + esc(it.title) + "</span>" +
      '<span class="home-list__meta">' + esc(it.time_text) + "</span></a></li>";
  }
  function renderNews(n) {
    var list = $("home-news-list"), meta = $("home-news-meta");
    if (!n || !n.items || !n.items.length) {
      list.innerHTML = '<li class="home-list__empty">' + esc((n && n.error) || "뉴스를 불러오는 중이에요") + "</li>";
      meta.textContent = "";
      return;
    }
    list.innerHTML = n.items.slice(0, NEWS_LIMIT).map(newsItem).join("");   // 최신순 NEWS_LIMIT 건만
    meta.textContent = n.updated_text || "";
  }

  /* 4. 규제 업데이트 ------------------------------------------------------- */
  function regItem(it) {
    return '<li class="home-list__item" data-published="' + esc(it.published_at) + '"><a class="home-list__link" href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="home-list__title"><span class="badge badge-primary">' + esc(it.country) + "</span>" + esc(it.title) + "</span>" +
      '<span class="home-list__meta">' + (it.is_new ? '<span class="badge badge-danger">NEW</span>' : "") + esc(it.source) + " · " + esc(it.time_text) + "</span></a></li>";
  }
  function renderRegs(r) {
    var list = $("home-reg-list"), meta = $("home-reg-meta");
    if (!r || !r.items || !r.items.length) {
      list.innerHTML = '<li class="home-list__empty">최근 규제 소식이 없어요</li>';
      meta.textContent = r && r.checked_text ? r.checked_text : "";
      return;
    }
    list.innerHTML = r.items.slice(0, REG_LIMIT).map(regItem).join("");     // 최신순 REG_LIMIT 건만
    meta.textContent = r.checked_text || "";
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
    var list = $("home-clock-list");
    var cities = currentCities();
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

  /* 8. 위젯 배치·설정 (2-3): 사용자별 localStorage. 업무 DB users.home_widgets 는 7단계에서 도입 예정 ---- */
  var WIDGET_NAMES = { today: "오늘 챙길 것", projects: "프로젝트 현황", week: "이번 주 일정", rates: "환율", clock: "바이어 현지 시각", news: "화장품 뉴스", regs: "규제 업데이트" };
  var SIZES = [[4, "1/3"], [6, "1/2"], [8, "2/3"], [12, "전체"]];
  var DEFAULT_LAYOUT = [
    { id: "today", size: 4 }, { id: "week", size: 8 },
    { id: "projects", size: 4 }, { id: "rates", size: 4 }, { id: "clock", size: 4 }, { id: "news", size: 12 },
  ];
  var ICONS = {
    grip: '<circle cx="9" cy="6" r="1"></circle><circle cx="15" cy="6" r="1"></circle><circle cx="9" cy="12" r="1"></circle><circle cx="15" cy="12" r="1"></circle><circle cx="9" cy="18" r="1"></circle><circle cx="15" cy="18" r="1"></circle>',
    left: '<path d="M15 6l-6 6 6 6"></path>', right: '<path d="M9 6l6 6-6 6"></path>', close: '<path d="M6 6l12 12M18 6L6 18"></path>',
  };
  function icon(name) {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }
  var grid = $("home-widgets"), layoutKey = "cosmoa.home.widgets." + ($("home").getAttribute("data-user-id") || "guest");
  var layout = [], editing = false, dragId = null;

  function cloneLayout(items) { return items.map(function (w) { return { id: w.id, size: w.size }; }); }
  function validSize(size) { return SIZES.some(function (s) { return s[0] === size; }); }
  function loadLayout() {   /* 저장값이 손상되었거나 없는 위젯이 있어도 화면이 깨지지 않게 걸러냅니다 */
    var saved = storage.getJSON(layoutKey), seen = {};
    if (!saved || !Array.isArray(saved.items)) return cloneLayout(DEFAULT_LAYOUT);
    return saved.items.filter(function (w) {
      if (!w || !WIDGET_NAMES[w.id] || !validSize(w.size) || seen[w.id]) return false;
      seen[w.id] = true;
      return true;
    }).map(function (w) { return { id: w.id, size: w.size }; });
  }
  function widgetEl(id) { return grid.querySelector('[data-widget="' + id + '"]'); }
  function indexOfWidget(id) { return layout.findIndex(function (w) { return w.id === id; }); }
  function applyLayout() {
    Object.keys(WIDGET_NAMES).forEach(function (id) { widgetEl(id).hidden = indexOfWidget(id) === -1; });
    layout.forEach(function (w) {
      var el = widgetEl(w.id);
      SIZES.forEach(function (s) { el.classList.toggle("home-widget--" + s[0], s[0] === w.size); });
      el.querySelectorAll("[data-widget-size]").forEach(function (b) {
        var on = Number(b.getAttribute("data-widget-size")) === w.size;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-selected", String(on));
      });
      grid.appendChild(el);
    });
    grid.appendChild($("home-widgets-empty"));
    $("home-widgets-empty").hidden = layout.length > 0;
    var hidden = Object.keys(WIDGET_NAMES).filter(function (id) { return indexOfWidget(id) === -1; });
    $("home-widget-add").innerHTML = hidden.length ? hidden.map(function (id) {
      return '<button class="btn btn-soft btn-sm" type="button" data-widget-add="' + id + '">+ ' + esc(WIDGET_NAMES[id]) + "</button>";
    }).join("") : '<span class="text-caption">모든 위젯을 표시하고 있어요</span>';
  }
  function commitLayout() { storage.setJSON(layoutKey, { v: 1, items: layout }); applyLayout(); }
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
    Object.keys(WIDGET_NAMES).forEach(function (id) { widgetEl(id).draggable = on; });
    if (!on) { toggle.focus(); clearDropMarks(); }
  }
  function clearDropMarks() {
    grid.querySelectorAll(".is-drop-before, .is-drop-after").forEach(function (el) { el.classList.remove("is-drop-before", "is-drop-after"); });
  }
  function dropAfter(target, e) { var r = target.getBoundingClientRect(); return e.clientX > r.left + r.width / 2; }
  function initWidgets() {
    Object.keys(WIDGET_NAMES).forEach(function (id) {
      var name = esc(WIDGET_NAMES[id]), tools = document.createElement("div");
      tools.className = "home-widget__tools";
      tools.innerHTML =
        '<span class="home-widget__grip" title="끌어서 옮기기">' + icon("grip") + "</span>" +
        '<button class="home-widget__tool" type="button" data-widget-move="-1" aria-label="' + name + ' 앞으로" title="앞으로">' + icon("left") + "</button>" +
        '<button class="home-widget__tool" type="button" data-widget-move="1" aria-label="' + name + ' 뒤로" title="뒤로">' + icon("right") + "</button>" +
        '<div class="tabs home-widget__sizes" role="tablist" aria-label="' + name + ' 크기">' + SIZES.map(function (s) {
          return '<button class="tab" type="button" role="tab" data-widget-size="' + s[0] + '" aria-selected="false">' + s[1] + "</button>";
        }).join("") + "</div>" +
        '<button class="home-widget__tool home-widget__remove" type="button" data-widget-remove aria-label="' + name + ' 숨기기" title="숨기기">' + icon("close") + "</button>";
      widgetEl(id).insertBefore(tools, widgetEl(id).firstChild);
    });
    layout = loadLayout();
    applyLayout();

    $("home-edit-toggle").addEventListener("click", function () { setEditing(true); $("home-edit-done").focus(); });
    $("home-edit-done").addEventListener("click", function () { setEditing(false); });
    $("home-edit-reset").addEventListener("click", function () { layout = cloneLayout(DEFAULT_LAYOUT); commitLayout(); });
    $("home-widget-add").addEventListener("click", function (e) {
      var b = e.target.closest("[data-widget-add]");
      if (!b) return;
      layout.push({ id: b.getAttribute("data-widget-add"), size: 6 });
      commitLayout();
      $("home-edit-done").focus();
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
      } else if (b.hasAttribute("data-widget-size")) {
        layout[indexOfWidget(id)].size = Number(b.getAttribute("data-widget-size"));
        commitLayout();
        b.focus();
      }
    });
    grid.addEventListener("dragstart", function (e) {
      var card = editing && e.target.closest && e.target.closest("[data-widget]");
      if (!card) return;
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
        cur.items = fresh.concat(cur.items).slice(0, 8);
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
