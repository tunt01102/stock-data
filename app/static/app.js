/* Front-end logic. Vanilla JS + Chart.js (bundled). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let LANG = "vi";
const S = { overview: null, stock: null, stockT: null, range: 0, cmp: [], cmpRange: 0, macro: null, settings: null, charts: {} };

/* ---------------- i18n ---------------- */
function t(k, vars) {
  let s = (I18N[LANG] && I18N[LANG][k]) ?? I18N.vi[k] ?? k;
  if (vars) for (const [a, b] of Object.entries(vars)) s = s.replaceAll("{" + a + "}", b);
  return s;
}
function applyI18n() {
  document.documentElement.lang = LANG;
  $$("[data-i18n]").forEach(el => el.textContent = t(el.dataset.i18n));
  $$("[data-i18n-html]").forEach(el => el.innerHTML = t(el.dataset.i18nHtml));
  $$("[data-i18n-ph]").forEach(el => el.placeholder = t(el.dataset.i18nPh));
}
function ex(key) { const e = EXPL[key]; return e ? (e[LANG] || e.vi) : null; }
function info(key) { return ex(key) ? `<span class="info" data-ex="${key}">i</span>` : ""; }

/* ---------------- formatting ---------------- */
const loc = () => (LANG === "vi" ? "vi-VN" : "en-US");
function num(v, d = 2) {
  if (v === null || v === undefined || v === "" || isNaN(+v)) return "–";
  return (+v).toLocaleString(loc(), { minimumFractionDigits: d, maximumFractionDigits: d });
}
function pct(v, d = 1, sign = true) {
  if (v === null || v === undefined || isNaN(+v)) return "–";
  const s = (sign && v > 0 ? "+" : "") + num(v, d) + "%";
  return `<span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${s}</span>`;
}
function bn(v) { return v === null || v === undefined ? "–" : num(v / 1e9, 0); }
function dmy(iso) { if (!iso) return "–"; const [y, m, d] = iso.slice(0, 10).split("-"); return d ? `${d}/${m}/${y}` : iso; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
const SERIES = () => [1, 2, 3, 4, 5, 6, 7, 8].map(i => css("--s" + i));

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { status: r.status, body: j });
  return j;
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

/* ---------------- groups ---------------- */
function groupOf(seg) {
  const s = (seg || "").toLowerCase();
  if (s.includes("công nghiệp") || s.includes("kcn")) return "g_kcn";
  if (s.includes("môi giới") || s.includes("dịch vụ")) return "g_srv";
  if (/(đa ngành|hạ tầng|năng lượng|ô tô|thương mại|nghỉ dưỡng)/.test(s)) return "g_div";
  return "g_res";
}
const GROUPS = ["g_res", "g_kcn", "g_srv", "g_div"];
function fillGroupSelect(sel) {
  sel.innerHTML = `<option value="">${t("group_all")}</option>` + GROUPS.map(g => `<option value="${g}">${t(g)}</option>`).join("");
}

/* ---------------- tooltip for explanations ---------------- */
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-ex]"); const tip = $("#tip");
  if (!el) { tip.classList.add("hidden"); return; }
  const x = ex(el.dataset.ex); if (!x) return;
  tip.innerHTML = `<b>${esc(x[0])}</b><br><code>${esc(x[1])}</code><br>${esc(x[2])}`;
  tip.classList.remove("hidden");
  const r = el.getBoundingClientRect();
  tip.style.left = Math.min(r.left, innerWidth - 400) + "px";
  tip.style.top = (r.bottom + 6 + 200 > innerHeight ? r.top - tip.offsetHeight - 6 : r.bottom + 6) + "px";
});

/* ---------------- freshness banner ---------------- */
function renderFresh(f) {
  const b = $("#freshBanner");
  if (!f) return;
  b.classList.remove("hidden");
  const errs = Object.keys(f.last_check_errors || {});
  const refreshErr = Object.values(f.last_refresh || {}).flatMap(x => Object.keys(x.errors || {}));
  if (!f.data_last) { b.className = "banner"; b.innerHTML = `<span class="big">${t("no_data")}</span>`; return; }
  if (f.stale) {
    b.className = "banner";
    b.innerHTML = `<span class="big">${t("stale_banner", { d: `<span class="stale-mark">${dmy(f.data_last)}</span>`, e: dmy(f.expected) })}</span><br>${t("stale_hint")}` +
      (errs.length || refreshErr.length ? `<br>${t("last_errors", { x: esc([...new Set([...errs, ...refreshErr])].slice(0, 12).join(", ")) })}` : "");
  } else {
    b.className = "banner ok";
    b.innerHTML = t("fresh_banner", { d: `<b>${dmy(f.data_last)}</b>` }) +
      (refreshErr.length ? ` <span class="badge bad">${t("last_errors", { x: esc(refreshErr.slice(0, 12).join(", ")) })}</span>` : "");
  }
}

/* ---------------- refresh job ---------------- */
let jobTimer = null;
async function startRefresh() {
  try { await post("/api/refresh", { what: "all" }); }
  catch (e) { if (e.status !== 409) { alert(e.message); return; } }
  pollJob();
}
async function pollJob() {
  clearTimeout(jobTimer);
  let j; try { j = await api("/api/job"); } catch { return; }
  const bar = $("#jobBar");
  if (j.running) {
    bar.classList.remove("hidden"); $("#btnRefresh").disabled = true;
    $("#jobText").textContent = t("job_running", { d: j.done, t: j.total, c: j.current });
    $("#jobProg").style.width = (j.total ? (100 * j.done / j.total) : 0) + "%";
    $("#jobLog").textContent = (j.log || []).slice(-40).join("\n");
    jobTimer = setTimeout(pollJob, 1500);
    S.wasRunning = true;
  } else {
    $("#btnRefresh").disabled = false;
    if (S.wasRunning) {
      S.wasRunning = false;
      const n = Object.keys(j.errors || {}).length;
      $("#jobText").innerHTML = n ? `<span class="badge bad">${t("job_done_err", { n })}</span> ${esc(Object.entries(j.errors).slice(0, 6).map(([k, v]) => k + ": " + v.slice(0, 90)).join(" | "))}` : t("job_done", { f: (j.finished || "").slice(11, 19) });
      $("#jobProg").style.width = "100%";
      $("#jobLog").textContent = (j.log || []).join("\n");
      S.overview = null; S.macro = null; S.stock = null;
      loadTab(currentTab());
      setTimeout(() => { if (!S.wasRunning) bar.classList.add("hidden"); }, n ? 60000 : 8000);
    }
  }
}

/* ---------------- tabs ---------------- */
function currentTab() { return ($(".tabs button.active") || {}).dataset?.tab || "overview"; }
function showTab(name) {
  $$(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + name));
  try { localStorage.setItem("tab", name); } catch {}
  loadTab(name);
}
async function loadTab(name) {
  try {
    if (name === "overview") await renderOverview();
    if (name === "stock") await renderStock();
    if (name === "compare") await renderCompare();
    if (name === "macro") await renderMacro();
    if (name === "download") await renderDownload();
    if (name === "settings") await renderSettings();
    if (name === "glossary") renderGlossary();
  } catch (e) { console.error(e); }
}

/* ---------------- charts helpers ---------------- */
function chartDefaults() {
  Chart.defaults.color = css("--text2");
  Chart.defaults.borderColor = css("--grid");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.animation = false;
  Chart.defaults.locale = loc();
  Chart.defaults.plugins.tooltip.mode = "index";
  Chart.defaults.plugins.tooltip.intersect = false;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 4;
  Chart.defaults.elements.line.borderWidth = 2;
}
function mkChart(id, cfg) {
  if (S.charts[id]) S.charts[id].destroy();
  const ctx = document.getElementById(id);
  if (!ctx) return;
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false } }, cfg.options || {});
  S.charts[id] = new Chart(ctx, cfg);
  return S.charts[id];
}
/* vertical marker line (e.g. HOSE listing date) */
const vlinePlugin = {
  id: "vline",
  afterDraw(chart, _a, opts) {
    if (!opts || !opts.label) return;
    const labels = chart.data.labels; const i = labels.findIndex(d => d >= opts.label);
    if (i <= 0) return;
    const x = chart.scales.x.getPixelForValue(i); const { top, bottom } = chart.chartArea;
    const c = chart.ctx; c.save(); c.strokeStyle = css("--text2"); c.setLineDash([4, 4]); c.lineWidth = 1;
    c.beginPath(); c.moveTo(x, top); c.lineTo(x, bottom); c.stroke();
    c.setLineDash([]); c.fillStyle = css("--text2"); c.font = "11px sans-serif"; c.fillText(opts.text || "", x + 4, top + 12); c.restore();
  },
};
Chart.register(vlinePlugin);
function xTicks(n = 8) { return { maxTicksLimit: n, autoSkip: true, maxRotation: 0, callback(v) { const l = this.getLabelForValue(v); return l && l.length === 10 ? dmy(l).slice(3) : l; } }; }

/* ================= OVERVIEW ================= */
const OV_COLS = [
  ["stt", "col_stt", r => r.stt, null],
  ["ticker", "col_ticker", r => r.ticker, null, "l"],
  ["name", "col_name", r => r.name || "", null, "l"],
  ["segment", "col_seg", r => r.segment || "", null, "l"],
  ["open", "col_open", r => r.metrics.open, "open"],
  ["close", "col_close", r => r.metrics.close, "close"],
  ["chg_1d", "col_1d", r => r.metrics.chg_1d, "chg"],
  ["chg_1m", "col_1m", r => r.metrics.chg_1m, "chg"],
  ["chg_ytd", "col_ytd", r => r.metrics.chg_ytd, "ytd"],
  ["chg_all", "col_all", r => r.metrics.chg_all, "chg"],
  ["da", "col_da", r => r.fund.debt_to_assets, "da"],
  ["de", "col_de", r => r.fund.debt_to_equity, "de"],
  ["ta", "col_ta", r => r.fund.total_assets, "ta"],
  ["rg", "col_rg", r => r.fund.revenue_growth_yoy, "rg"],
  ["ca", "col_ca", r => r.fund.cash_to_assets, "ca"],
  ["roa", "col_roa", r => r.fund.roa, "roa"],
  ["roe", "col_roe", r => r.fund.roe, "roe"],
  ["eps", "col_eps", r => r.fund.eps, "eps"],
  ["pe", "col_pe", r => r.fund.pe_now, "pe"],
  ["q", "col_q", r => r.fund.fiscal_date || "", null],
  ["date", "col_date", r => r.metrics.last_date || "", null],
];
let ovSort = { k: "stt", dir: 1 };
const OV_FIXED = ["stt", "ticker"];
const OV_PRESETS = { cols_basic: ["name", "close", "chg_1d", "chg_1m", "chg_ytd", "date"],
  cols_fin: ["close", "chg_1d", "chg_ytd", "da", "de", "ta", "rg", "ca", "roa", "roe", "eps", "pe"] };
let ovHidden = new Set();
try { ovHidden = new Set(JSON.parse(localStorage.getItem("ovHidden") || "[]")); } catch {}
function saveHidden() { try { localStorage.setItem("ovHidden", JSON.stringify([...ovHidden])); } catch {} }
function renderColPanel() {
  const p = $("#ovColsPanel");
  p.innerHTML = `<div class="row"><button data-preset="all">${t("cols_all")}</button><button data-preset="cols_basic">${t("cols_basic")}</button><button data-preset="cols_fin">${t("cols_fin")}</button></div>` +
    OV_COLS.filter(c => !OV_FIXED.includes(c[0])).map(c => `<label><input type="checkbox" data-col="${c[0]}" ${ovHidden.has(c[0]) ? "" : "checked"}> ${t(c[1])}</label>`).join("") +
    `<label><input type="checkbox" data-col="xcheck" ${ovHidden.has("xcheck") ? "" : "checked"}> ${t("xcheck")}</label><div class="row note">${t("cols_note")}</div>`;
}
async function renderOverview() {
  if (!S.overview) S.overview = await api("/api/overview");
  const { tickers, fresh } = S.overview;
  renderFresh(fresh);
  const market = fresh.data_last;
  const q = $("#ovSearch").value.trim().toLowerCase(), g = $("#ovGroup").value, hideVic = $("#ovHideVic").checked;
  let rows = tickers.filter(r => (!q || r.ticker.toLowerCase().includes(q) || (r.name || "").toLowerCase().includes(q)) &&
    (!g || groupOf(r.segment) === g) && !(hideVic && r.ticker === "VIC"));
  const col = OV_COLS.find(c => c[0] === ovSort.k);
  rows.sort((a, b) => { const x = col[2](a), y = col[2](b); if (x == null || x === "") return 1; if (y == null || y === "") return -1; return (x > y ? 1 : x < y ? -1 : 0) * ovSort.dir; });
  // cards
  const up = tickers.filter(r => r.metrics.chg_1d > 0).length, dn = tickers.filter(r => r.metrics.chg_1d < 0).length;
  const staleT = tickers.filter(r => !r.metrics.last_date || r.metrics.last_date < market);
  let xok = 0, xbad = 0;
  tickers.forEach(r => { const x = r.status.xcheck; if (x) { xok += x.ok; xbad += x.mismatch; } });
  $("#ovCards").innerHTML = [
    [t("c_count"), tickers.length, ""],
    [t("c_last"), fresh.stale ? `<span class="stale-mark">${dmy(market)}</span>` : dmy(market), fresh.stale ? t("st_stale") : ""],
    [t("c_up"), `<span class="pos">${up}</span> / <span class="neg">${dn}</span>`, ""],
    [t("c_stale_t"), staleT.length ? `<span class="neg">${staleT.length}</span>` : "0", staleT.map(r => r.ticker).join(", ")],
    [t("c_xcheck"), xok + xbad ? num(100 * xok / (xok + xbad), 1) + "%" : "–", xok + xbad ? `${xbad} LECH / ${xok + xbad}` : ""],
  ].map(([l, v, h]) => `<div class="card"><div class="lbl">${l}</div><div class="val">${v}</div><div class="hint">${esc(h)}</div></div>`).join("");
  // table
  const vis = k => !ovHidden.has(k);
  const stk = k => k === "stt" ? " stk stk0" : k === "ticker" ? " stk stk1" : "";
  const head = "<tr>" + OV_COLS.filter(c => vis(c[0])).map(c => `<th class="${(c[4] || "") + stk(c[0])}" data-k="${c[0]}">${t(c[1])} ${c[3] ? info(c[3]) : ""}${ovSort.k === c[0] ? (ovSort.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("") + (vis("xcheck") ? `<th>${t("xcheck")}</th>` : "") + "</tr>";
  const body = rows.map(r => {
    const m = r.metrics, f = r.fund, st = !m.last_date || m.last_date < market;
    const x = r.status.xcheck;
    const xb = x ? (x.mismatch ? `<span class="badge bad">${x.mismatch} LECH</span>` : `<span class="badge ok">OK</span>`) : `<span class="badge na">NA</span>`;
    const cells = {
      stt: `<td class="stk stk0">${r.stt}</td>`,
      ticker: `<td class="l stk stk1"><b>${r.ticker}</b>${r.note ? ' <span class="badge cur" title="' + esc(r.note) + '">!</span>' : ""}</td>`,
      name: `<td class="l">${esc(r.name || "—")}</td>`, segment: `<td class="l">${esc(r.segment || "")}</td>`,
      open: `<td>${num(m.open)}</td>`, close: `<td><b>${num(m.close)}</b></td>`, chg_1d: `<td>${pct(m.chg_1d, 2)}</td>`,
      chg_1m: `<td>${pct(m.chg_1m)}</td>`, chg_ytd: `<td>${pct(m.chg_ytd)}</td>`, chg_all: `<td>${pct(m.chg_all, 0)}</td>`,
      da: `<td>${f.debt_to_assets == null ? "–" : num(f.debt_to_assets, 1) + "%"}</td>`, de: `<td>${num(f.debt_to_equity, 2)}</td>`,
      ta: `<td>${bn(f.total_assets)}</td>`, rg: `<td>${pct(f.revenue_growth_yoy, 0)}</td>`,
      ca: `<td>${f.cash_to_assets == null ? "–" : num(f.cash_to_assets, 1) + "%"}</td>`, roa: `<td>${pct(f.roa, 1, false)}</td>`,
      roe: `<td>${pct(f.roe, 1, false)}</td>`, eps: `<td>${num(f.eps, 0)}</td>`, pe: `<td>${f.pe_now ? num(f.pe_now, 1) : "–"}</td>`,
      q: `<td>${f.fiscal_date ? f.fiscal_date.slice(0, 7) : "–"}</td>`,
      date: `<td>${st ? `<span class="badge stale">${dmy(m.last_date)}</span>` : dmy(m.last_date)}</td>`,
    };
    return `<tr class="click" data-t="${r.ticker}">` + OV_COLS.filter(c => vis(c[0])).map(c => cells[c[0]]).join("") + (vis("xcheck") ? `<td>${xb}</td>` : "") + "</tr>";
  }).join("");
  $("#ovTable").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  // spreadsheet issues (shown as-is, never silently "fixed")
  const issues = [];
  tickers.forEach(r => {
    if (!r.name) issues.push(`<b>${r.ticker}</b>: ${LANG === "vi" ? "dòng " + r.stt + " không có tên doanh nghiệp trong file Excel." : "row " + r.stt + " has no company name in the Excel file."}`);
    if (r.note) issues.push(`<b>${r.ticker}</b>: ${LANG === "vi" ? "ghi chú trong file" : "note in file"}: “${esc(r.note)}”`);
  });
  if (tickers.find(r => r.ticker === "NVT" && /Năm Bảy Bảy/i.test(r.name || "")))
    issues.push(LANG === "vi" ? "<b>NVT</b>: file ghi tên “CTCP Đầu tư Năm Bảy Bảy”, nhưng đây là tên của mã <b>NBB</b>. NVT là CTCP Bất động sản Du lịch Ninh Vân Bay. Ứng dụng giữ nguyên tên theo file, vui lòng kiểm tra lại." :
      "<b>NVT</b>: the file names it “Nam Bay Bay Investment JSC”, which is <b>NBB</b>'s name; NVT is Ninh Van Bay Travel Real Estate JSC. The app keeps the file's names; please check.");
  const late = tickers.filter(r => r.listed && r.listed > "2018-01-02").map(r => `${r.ticker} (${dmy(r.listed)})`);
  if (late.length) issues.push((LANG === "vi" ? "Niêm yết HOSE sau 01/2018 – dữ liệu trước ngày niêm yết là từ UPCoM/HNX (nếu có): " : "Listed on HOSE after 01/2018 – earlier data is from UPCoM/HNX (if any): ") + late.join(", "));
  $("#dataIssues").innerHTML = `<b>${t("issues_title")}</b><ul>${issues.map(i => `<li>${i}</li>`).join("")}</ul>`;
}

/* ================= STOCK ================= */
async function renderStock() {
  if (!S.overview) S.overview = await api("/api/overview");
  const sel = $("#stSel");
  if (!sel.options.length) {
    sel.innerHTML = S.overview.tickers.map(r => `<option value="${r.ticker}">${r.ticker} – ${esc(r.name || "")}</option>`).join("");
  }
  const tk = S.stockT || sel.value; sel.value = tk;
  if (!S.stock || S.stock.meta.ticker !== tk) S.stock = await api("/api/stock/" + tk);
  S.stockT = tk;
  drawStock();
}
function sliceRange(arr, n) { return n ? arr.slice(-n) : arr; }
function drawStock() {
  const d = S.stock, m = d.metrics, meta = d.meta, fresh = S.overview.fresh;
  const P = d.prices, N = S.range;
  const market = fresh.data_last;
  const stale = m.last_date && market && m.last_date < market;
  // header
  const firstHose = P.floor.findIndex(f => f === "HOSE");
  const preFloor = [...new Set(P.floor.slice(0, Math.max(firstHose, 0)).filter(Boolean))].join("/");
  $("#stHead").innerHTML = `<div class="head"><div><h2>${meta.ticker} – ${esc(meta.name || "—")}</h2>
    <div class="kv"><span>${t("segment")}: <b>${esc(meta.segment || "")}</b></span><span>${t("listed")}: <b>${dmy(meta.listed)}</b></span>
    <span>${t("data_from")}: <b>${dmy(m.first_date)}</b> → <b>${stale ? `<span class="stale-mark">${dmy(m.last_date)}</span>` : dmy(m.last_date)}</b></span></div>
    ${meta.note ? `<div class="note warn">${esc(meta.note)}</div>` : ""}
    ${preFloor ? `<div class="note">${t("floor_note", { f: esc(preFloor) })}</div>` : ""}</div>
    <div class="kv">${t("sources")}: ${Object.entries(d.sources).map(([k, u]) => `<a href="${u}" target="_blank" rel="noopener">${k}</a>`).join(" · ")}</div></div>
    ${stale ? `<div class="banner">${t("stock_stale", { d: dmy(m.last_date), m: dmy(market) })}</div>` : ""}`;
  // metric cards
  const fl = d.fund_latest || {};
  const cards = [
    ["close", t("m_close"), num(m.close), dmy(m.last_date)], ["open", t("m_open"), num(m.open), ""],
    ["chg", t("m_1w"), pct(m.chg_1w), ""], ["chg", t("m_1m"), pct(m.chg_1m), ""], ["chg", t("m_3m"), pct(m.chg_3m), ""],
    ["ytd", t("m_ytd"), pct(m.chg_ytd), ""], ["chg", t("m_1y"), pct(m.chg_1y), ""], ["chg", t("m_all"), pct(m.chg_all), dmy(m.first_date)],
    ["cagr", t("m_cagr"), pct(m.cagr), ""], ["vol", t("m_vol"), m.volatility ? num(m.volatility, 1) + "%" : "–", ""],
    ["mdd", t("m_mdd"), pct(m.max_drawdown), `${dmy(m.mdd_from)} → ${dmy(m.mdd_to)}`], ["beta", t("m_beta"), num(m.beta_1y, 2), "vs VN-Index"],
    ["ma", t("m_ma"), `${num(m.ma20, 1)} / ${num(m.ma50, 1)} / ${num(m.ma200, 1)}`, ""], ["w52", t("m_52"), `${num(m.high_52w, 1)} / ${num(m.low_52w, 1)}`, ""],
    ["pe", t("pe_now"), fl.pe_now ? num(fl.pe_now, 1) : "–", fl.eps ? "EPS " + num(fl.eps, 0) : ""],
  ];
  $("#stCards").innerHTML = cards.map(([k, l, v, h]) => `<div class="card"><div class="lbl">${l} ${info(k)}</div><div class="val">${v}</div><div class="hint">${esc(h)}</div></div>`).join("");
  // price chart
  const C = SERIES();
  const dates = P.date, adj = P.adj_close.map(Number);
  const ma = n => adj.map((_, i) => i + 1 >= n ? adj.slice(i + 1 - n, i + 1).reduce((a, b) => a + b, 0) / n : null);
  const lab = sliceRange(dates, N);
  const ds = [
    { label: LANG === "vi" ? "Giá đóng cửa (điều chỉnh)" : "Close (adjusted)", data: sliceRange(adj, N), borderColor: C[0] },
    { label: "MA20", data: sliceRange(ma(20), N), borderColor: C[1], borderWidth: 1.5 },
    { label: "MA50", data: sliceRange(ma(50), N), borderColor: C[2], borderWidth: 1.5 },
    { label: "MA200", data: sliceRange(ma(200), N), borderColor: C[6], borderWidth: 1.5 },
  ];
  if ($("#stRaw").checked) ds.push({ label: LANG === "vi" ? "Giá đóng cửa gốc" : "Close (raw)", data: sliceRange(P.close.map(Number), N), borderColor: C[3], borderDash: [5, 3] });
  mkChart("cPrice", { type: "line", data: { labels: lab, datasets: ds },
    options: { scales: { x: { ticks: xTicks(10), grid: { display: false } }, y: { title: { display: true, text: LANG === "vi" ? "nghìn đồng" : "thousand VND" } } },
      plugins: { vline: { label: meta.listed, text: "HOSE" }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y)}` } } } } });
  mkChart("cVol", { type: "bar", data: { labels: lab, datasets: [{ label: t("chart_volume"), data: sliceRange(P.volume.map(Number), N), backgroundColor: C[0], borderRadius: 0 }] },
    options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => num(c.parsed.y, 0) } } }, scales: { x: { ticks: xTicks(6), grid: { display: false } }, y: { ticks: { callback: v => num(v / 1e6, 1) + "M" } } } } });
  // relative to index
  const idx = Object.fromEntries(d.index.date.map((x, i) => [x, +d.index.close[i]]));
  const lab2 = lab.filter(x => idx[x]); const a0 = adj[dates.indexOf(lab2[0])], i0 = idx[lab2[0]];
  const amap = Object.fromEntries(dates.map((x, i) => [x, adj[i]]));
  mkChart("cRel", { type: "line", data: { labels: lab2, datasets: [
    { label: meta.ticker, data: lab2.map(x => 100 * amap[x] / a0), borderColor: C[0] },
    { label: "VN-Index", data: lab2.map(x => 100 * idx[x] / i0), borderColor: C[1] }] },
    options: { scales: { x: { ticks: xTicks(6), grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y, 1)}` } } } } });
  drawFund();
  drawXcheck();
  $("#stAI").classList.toggle("hidden", !(S.settings && S.settings.configured.length));
}
function drawFund() {
  const d = S.stock, F = d.fund || [];
  const C = SERIES();
  $("#fundNote").innerHTML = F.length ? t("fund_src", { l: `<a href="${d.fund_source}" target="_blank" rel="noopener">dstock.vndirect.com.vn</a>`, q: F[F.length - 1].fiscal_date }) : `<span class="badge bad">${t("fund_none")}</span>`;
  const defs = [["da", "f_da", "debt_to_assets"], ["de", "f_de", "debt_to_equity"], ["ta", "f_ta", "total_assets", 1e9], ["rg", "f_rg", "revenue_growth_yoy"],
    ["ca", "f_ca", "cash_to_assets"], ["roa", "f_roa", "roa"], ["roe", "f_roe", "roe"], ["eps", "f_eps", "eps"], ["pe", "f_pe", "pe"]];
  const box = $("#fundCharts");
  box.innerHTML = defs.map(([k, l]) => `<div class="panel"><h3>${t(l)} ${info(k)}</h3><div class="chartbox"><canvas id="cf_${k}"></canvas></div></div>`).join("");
  const F2 = F.filter(r => r.fiscal_date >= "2018-01-01");
  const labs = F2.map(r => { const [y, mo] = r.fiscal_date.split("-"); return "Q" + Math.ceil(+mo / 3) + "/" + y.slice(2); });
  defs.forEach(([k, l, field, div], i) => {
    const vals = F2.map(r => r[field] == null ? null : r[field] / (div || 1));
    const missing = vals.every(v => v == null);
    if (missing) { $("#cf_" + k).parentElement.innerHTML = `<p class="note">${LANG === "vi" ? "Nguồn chưa có số liệu" : "No data from source"}</p>`; return; }
    mkChart("cf_" + k, { type: "bar", data: { labels: labs, datasets: [{ label: t(l), data: vals,
      backgroundColor: vals.map(v => v != null && v < 0 ? css("--s8") : C[0]), borderRadius: 2, maxBarThickness: 18 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => num(c.parsed.y, k === "eps" || k === "ta" ? 0 : 2) } } },
        scales: { x: { ticks: { maxTicksLimit: 9, maxRotation: 0 }, grid: { display: false } } } } });
  });
  const cols = [["fiscal_date", "Quý", null], ["total_assets", t("col_ta"), "bn"], ["liabilities", LANG === "vi" ? "Nợ phải trả (tỷ)" : "Liabilities (bn)", "bn"],
    ["equity", LANG === "vi" ? "Vốn CSH (tỷ)" : "Equity (bn)", "bn"], ["cash", LANG === "vi" ? "Tiền (tỷ)" : "Cash (bn)", "bn"],
    ["net_revenue", LANG === "vi" ? "Doanh thu thuần (tỷ)" : "Net revenue (bn)", "bn"], ["npat", LANG === "vi" ? "LNST (tỷ)" : "Net profit (bn)", "bn"],
    ["debt_to_assets", t("col_da"), "p"], ["debt_to_equity", t("col_de"), 2], ["cash_to_assets", t("col_ca"), "p"],
    ["revenue_growth_yoy", t("col_rg") + " YoY", "pc"], ["revenue_growth_ttm", t("col_rg") + " TTM", "pc"], ["roa", "ROA", "p"], ["roe", "ROE", "p"],
    ["eps", "EPS", 0], ["close_at_quarter", LANG === "vi" ? "Giá cuối quý" : "Quarter-end price", 2], ["pe", "P/E", 1]];
  const fmt = (v, f) => f === "bn" ? bn(v) : f === "p" ? (v == null ? "–" : num(v, 1) + "%") : f === "pc" ? pct(v, 1) : f === null ? v : num(v, f);
  $("#fundTable").innerHTML = `<thead><tr>${cols.map(c => `<th>${c[1]}</th>`).join("")}</tr></thead><tbody>` +
    F.slice().reverse().map(r => `<tr>${cols.map(c => `<td>${fmt(r[c[0]], c[2])}</td>`).join("")}</tr>`).join("") + "</tbody>";
}
function drawXcheck() {
  const x = S.stock.xcheck, st = S.stock.status || {};
  $("#xcBody").innerHTML = `<p>${t("xc_summary", { ok: x.ok, bad: x.mismatch, na: x.na })}</p><p class="note">${t("xc_rule")}</p>` +
    (st.errors && Object.keys(st.errors).length ? `<p><span class="badge bad">${esc(Object.entries(st.errors).map(([k, v]) => k + ": " + v).join(" | "))}</span></p>` : "") +
    (x.examples.length ? `<p>${t("xc_recent")}</p><table class="grid small"><tbody>${x.examples.slice().reverse().map(e => `<tr><td class="l">${dmy(e.date)}</td><td class="l">${esc(e.note)}</td></tr>`).join("")}</tbody></table>` : "");
}

/* ================= COMPARE ================= */
async function renderCompare() {
  if (!S.overview) S.overview = await api("/api/overview");
  if (!S.cmp.length) S.cmp = ["VHM", "KDH", "NLG", "KBC"];
  const g = $("#cmpGroup").value;
  const C = SERIES();
  $("#cmpChips").innerHTML = S.overview.tickers.filter(r => !g || groupOf(r.segment) === g).map(r => {
    const i = S.cmp.indexOf(r.ticker);
    return `<span class="chip ${i >= 0 ? "on" : ""}" data-t="${r.ticker}">${i >= 0 ? `<span class="sw" style="background:${C[i]}"></span>` : ""}${r.ticker}</span>`;
  }).join("");
  const data = S.cmp.length ? await api("/api/series?tickers=" + S.cmp.join(",")) : {};
  // common dates = union, then rebase each at first date in range
  const all = [...new Set(Object.values(data).flatMap(a => a.map(p => p[0])))].sort();
  const lab = S.cmpRange ? all.slice(-S.cmpRange) : all;
  const ds = S.cmp.map((tk, i) => {
    const m = Object.fromEntries((data[tk] || []).map(p => [p[0], +p[1]]));
    const first = lab.find(d => m[d]); const base = m[first];
    return { label: tk, data: lab.map(d => m[d] ? 100 * m[d] / base : null), borderColor: C[i], spanGaps: true };
  });
  mkChart("cCmp", { type: "line", data: { labels: lab, datasets: ds },
    options: { scales: { x: { ticks: xTicks(10), grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y, 1)}` } } } } });
  const rows = S.overview.tickers.filter(r => S.cmp.includes(r.ticker));
  const cols = [["col_ticker", r => `<b>${r.ticker}</b>`], ["col_close", r => num(r.metrics.close)], ["m_1y", r => pct(r.metrics.chg_1y)], ["m_cagr", r => pct(r.metrics.cagr)],
    ["m_vol", r => num(r.metrics.volatility, 1) + "%"], ["m_mdd", r => pct(r.metrics.max_drawdown)], ["m_beta", r => num(r.metrics.beta_1y, 2)],
    ["col_da", r => num(r.fund.debt_to_assets, 1) + "%"], ["col_de", r => num(r.fund.debt_to_equity, 2)], ["col_roe", r => pct(r.fund.roe, 1, false)], ["col_pe", r => r.fund.pe_now ? num(r.fund.pe_now, 1) : "–"]];
  $("#cmpTable").innerHTML = `<thead><tr>${cols.map(c => `<th>${t(c[0])}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

/* ================= MACRO ================= */
function xbadge(x) { return !x || x === "NA" ? `<span class="badge na">NA</span>` : x === "OK" ? `<span class="badge ok">OK</span>` : `<span class="badge bad">${esc(x)}</span>`; }
function monthsBetween(p, today) { const [y, m] = p.split("-").map(Number); const [Y, M] = today.split("-").map(Number); return (Y - y) * 12 + (M - m); }
async function renderMacro() {
  if (!S.macro) S.macro = await api("/api/macro");
  const M = S.macro, today = M.fresh.today, C = SERIES(), st = M.status || {};
  renderFresh(M.fresh);
  const grid = $("#macroGrid");
  const card = (key, title, body, foot) => `<div class="panel"><h3>${title} ${info(key)}</h3>${body}<div class="chartbox"><canvas id="cm_${key}"></canvas></div>${foot || ""}</div>`;
  const staleNote = (name, last, maxLag) => {
    const s = st[name];
    if (s && !s.ok) return `<div class="banner">${t("mk_err", { e: esc(s.error || ""), p: last || "–" })}</div>`;
    if (last && monthsBetween(last.slice(0, 7), today) > maxLag) return `<div class="banner">${t("mk_stale", { p: last })}</div>`;
    return "";
  };
  const last = a => a && a.length ? a[a.length - 1] : null;
  const link = (u, txt) => `<a href="${u}" target="_blank" rel="noopener">${esc(txt)}</a>`;
  const cpiL = last(M.cpi), fxL = last(M.fx), goldL = last(M.gold);
  const sjcRows = (M.gold_sjc || []).filter(r => r.value), sjcL = last(sjcRows);
  let goldChk = null;  // official NSO gold price index (y/y) vs SJC bar price change (y/y), latest month with both
  (M.nso_cpi || []).slice().reverse().some(r => {
    const a = sjcRows.find(x => x.period === r.period), y0 = `${+r.period.slice(0, 4) - 1}${r.period.slice(4)}`, b = sjcRows.find(x => x.period === y0);
    if (r.gold_idx_yoy && a && b) { goldChk = { p: r.period, nso: +r.gold_idx_yoy, sjc: (a.value / b.value - 1) * 100, url: r.source_url }; return true; }
    return false; });
  const sbvRows = (M.sbv && M.sbv.rows) || [], sbvL = last(sbvRows);
  const gq = ((M.gdp_quarterly && M.gdp_quarterly.rows) || []).filter(r => /Q/.test(r.period)), gy = ((M.gdp_quarterly && M.gdp_quarterly.rows) || []).filter(r => !/Q/.test(r.period));
  const gqL = last(gq);
  const cpiChecks = M.cpi_annual && M.cpi_annual.rows ? Object.values(M.cpi_annual.rows).filter(r => r && r.year) : [];
  const fxT = M.fx_today && !M.fx_today.error ? M.fx_today : null;
  const sbvLive = M.sbv_live || null, cen = sbvLive && sbvLive.fx && sbvLive.fx.central_rate ? sbvLive.fx : null;
  const fxDiff = fxT && fxL ? (fxT.transfer / +fxL.value - 1) * 100 : null;
  grid.innerHTML = [
    card("cpi", t("mk_cpi"), staleNote("nso", cpiL && cpiL.period, 99) + staleNote("cpi", cpiL && cpiL.period, 3) +
      `<div class="kv"><span>${t("latest")}: <b>${cpiL ? num(cpiL.value, 2) + "%" : "–"}</b> (${cpiL ? cpiL.period : "–"})</span><span>${t("xcheck")}: ${xbadge(cpiL && cpiL.xcheck)}</span></div>`,
      `<div class="kv"><span>${t("source")}: ${cpiL ? link(cpiL.source_url, cpiL.source) : "–"}</span></div>
       <details><summary>${t("rows_by_source")}</summary><table class="grid small"><thead><tr><th>${t("period")}</th><th>NSO / ${t("latest")}</th><th>IMF</th><th>${t("xcheck")}</th><th class="l">${t("source")}</th></tr></thead><tbody>${M.cpi.slice().reverse().map(r => `<tr><td>${r.period}</td><td>${num(r.value, 2)}%</td><td>${r.xcheck_value ? num(r.xcheck_value, 2) + "%" : "–"}</td><td>${xbadge(r.xcheck)}</td><td class="l">${link(r.source_url, r.source.startsWith("Cục") ? "NSO" : "IMF")}</td></tr>`).join("")}</tbody></table></details>
       <details><summary>${t("cpi_check")}</summary><table class="grid small"><thead><tr><th>${t("year")}</th><th>World Bank</th><th>IMF</th><th>${t("xcheck")}</th></tr></thead><tbody>${cpiChecks.map(r => `<tr><td>${r.year}</td><td>${num(r.worldbank)}%</td><td>${num(r.imf_avg)}%</td><td>${xbadge(r.status)}</td></tr>`).join("")}</tbody></table></details>
       <p class="caption">${t("source")}: ${link(M.links.nso, "Cục Thống kê (NSO)")} (${LANG === "vi" ? "chính" : "primary"}) · ${link(M.links.imf_cpi, "IMF CPI")} · ${link(M.links.wb_cpi, "World Bank")}</p>`),
    card("sbv", t("mk_sbv"), `<div class="kv"><span>${t("refi")}: <b>${sbvL ? num(sbvL.refinancing_rate, 2) + "%" : "–"}</b></span><span>${t("redis")}: <b>${sbvL ? num(sbvL.rediscount_rate, 2) + "%" : "–"}</b></span>
      <span>${sbvL ? dmy(sbvL.effective_date) : ""}</span><span class="badge cur">${t("curated")} · ${t("checked_on", { d: dmy(M.sbv && M.sbv.as_of) })}</span></div>
      ${sbvLive && sbvLive.rates && sbvLive.rates.refinancing_rate != null ? `<div class="kv"><span>${link(M.links.sbv_rates, t("sbv_live"))}: <b>${num(sbvLive.rates.refinancing_rate, 2)}% / ${num(sbvLive.rates.rediscount_rate, 2)}%</b> (${esc(sbvLive.rates.decision || "")})</span>
        <span>${xbadge(sbvL && +sbvL.refinancing_rate === sbvLive.rates.refinancing_rate && +sbvL.rediscount_rate === sbvLive.rates.rediscount_rate ? "OK" : "LECH")} ${t("vs_curated")}</span>
        ${sbvLive.rates.interbank_overnight != null ? `<span>${t("interbank")}: <b>${num(sbvLive.rates.interbank_overnight, 2)}%</b> (${dmy(sbvLive.rates.interbank_date)})</span>` : ""}</div>` : ""}`,
      `<details><summary>${LANG === "vi" ? "Các lần điều chỉnh và văn bản gốc" : "Rate changes and source documents"}</summary><table class="grid small"><tbody>${sbvRows.slice().reverse().map(r => `<tr><td>${dmy(r.effective_date)}</td><td>${num(r.refinancing_rate, 2)}%</td><td>${num(r.rediscount_rate, 2)}%</td><td class="l wrap">${r.official_url ? link(r.official_url, (r.decision || "") + " – " + t("official_link")) + " · " : ""}${link(r.source_url, r.official_url ? t("other_link") : (r.decision || r.source_title))}</td></tr>`).join("")}</tbody></table></details>
       <p class="caption">${t("source")}: ${link(M.links.sbv, "Ngân hàng Nhà nước")}${M.sbv && M.sbv.note ? " · " + esc(M.sbv.note.slice(0, 260)) : ""}</p>`),
    card("vnindex", t("mk_vnindex"), (M.fresh.stale && M.vnindex_last ? `<div class="banner">${t("stale_banner", { d: dmy(M.vnindex_last.date), e: dmy(M.fresh.expected) })}</div>` : "") + `<div class="kv"><span>${t("latest")}: <b>${M.vnindex_last ? num(M.vnindex_last.close, 2) : "–"}</b> (${M.vnindex_last ? dmy(M.vnindex_last.date) : "–"})</span>
      <span>${t("xcheck")}: ${xbadge(M.vnindex_last && M.vnindex_last.xcheck)}</span></div>`,
      `<p class="caption">${t("source")}: ${link("https://dchart.vndirect.com.vn/?symbol=VNINDEX", "VNDirect")} · ${LANG === "vi" ? "đối chiếu" : "checked vs"} ${link("https://iboard.ssi.com.vn/", "SSI")}, ${link("https://banggia.dnse.com.vn/", "DNSE")} · ${link("https://www.hsx.vn/", "HOSE")}</p>`),
    card("gdp", t("mk_gdp"), staleNote("gdp", gqL ? gqL.period : null, 99) + `<div class="kv"><span>${t("quarterly")}: <b>${gqL ? num(gqL.gdp_yoy_pct, 2) + "%" : "–"}</b> (${gqL ? gqL.period : "–"}) ${gqL ? link(gqL.source_url, "NSO") : ""}</span>
      <span class="badge cur">${t("curated")} · ${t("checked_on", { d: dmy(M.gdp_quarterly && M.gdp_quarterly.as_of) })}</span></div>`,
      `<details><summary>${t("gdp_check")}</summary><table class="grid small"><thead><tr><th>${t("year")}</th><th>World Bank</th><th>NSO</th><th>${t("xcheck")}</th></tr></thead><tbody>${(M.gdp_annual || []).map(r => `<tr><td>${r.period}</td><td>${num(r.value)}%</td><td>${r.xcheck_value ? num(r.xcheck_value) + "%" : "–"}</td><td>${xbadge(r.xcheck)}</td></tr>`).join("")}</tbody></table>
       <table class="grid small"><tbody>${gq.slice().reverse().map(r => `<tr><td>${r.period}</td><td>${num(r.gdp_yoy_pct)}%</td><td class="l wrap">${link(r.source_url, r.source_title)}</td></tr>`).join("")}</tbody></table></details>
       <p class="caption">${t("source")}: ${link(M.links.nso, "Cục Thống kê (NSO)")} · ${link(M.links.wb_gdp, "World Bank")}. ${M.gdp_quarterly && M.gdp_quarterly.note ? esc(M.gdp_quarterly.note.slice(0, 300)) : ""}</p>`),
    card("fx", t("mk_fx"), staleNote("fx", fxL && fxL.period, 3) + staleNote("sbv", null, 99) +
      (cen ? `<div class="kv"><span>${link(M.links.sbv_fx, t("central"))}: <b>${num(cen.central_rate, 0)}</b> (${dmy(cen.date)}, ${esc(cen.notice || "")})</span>
        ${fxL ? `<span>IMF ${fxL.period}: ${xbadge(Math.abs(cen.central_rate / +fxL.value - 1) <= 0.03 ? "OK" : "LECH")}</span>` : ""}
        ${fxT ? `<span>Vietcombank: ${xbadge(fxT.sell <= cen.central_rate * 1.05 + 1 && fxT.buy >= cen.central_rate * 0.95 - 1 ? "OK" : "LECH")} (${LANG === "vi" ? "trong biên độ ±5%" : "within ±5% band"})</span>` : ""}</div>` : "") +
      `<div class="kv"><span>${t("latest")} IMF: <b>${fxL ? num(fxL.value, 0) : "–"}</b> (${fxL ? fxL.period : "–"})</span>
      ${fxT ? `<span>${t("vcb_today", { b: num(fxT.buy, 0), t: num(fxT.transfer, 0), s: num(fxT.sell, 0) })}</span><span>${t("xcheck")}: ${xbadge(Math.abs(fxDiff) <= 3 ? "OK" : "LECH " + num(fxDiff, 1) + "%")}</span>` : `<span class="badge bad">Vietcombank: ${esc((M.fx_today && M.fx_today.error) || "NA")}</span>`}</div>`,
      `<p class="caption">${t("source")}: ${link(M.links.sbv_fx, "Ngân hàng Nhà nước (tỷ giá trung tâm)")} · ${link(M.links.imf_er, "IMF Exchange Rates")} (${LANG === "vi" ? "lịch sử tháng, số liệu gốc NHNN" : "monthly history, from SBV"}) · ${link(M.links.wb_fx, "World Bank")} · ${link(M.links.vcb, "Vietcombank")}</p>`),
    card("gold", t("mk_gold"), staleNote("gold", goldL && goldL.period, 3) + staleNote("sjc", sjcL && sjcL.period, 2) +
      `<div class="kv"><span>${t("gold_sjc")}: <b>${sjcL ? num(sjcL.value, 1) : "–"}</b> (${sjcL ? dmy(sjcL.date) : "–"}) ${sjcL ? link(sjcL.source_url, "webgia") : ""}</span>
       <span>${t("gold_world")}: <b>${goldL ? num(goldL.vnd_per_luong, 1) : "–"}</b> (${goldL ? goldL.period : "–"}; ${goldL ? num(goldL.value, 0) : "–"} USD/oz)</span>
       ${sjcL && sjcL.premium_pct ? `<span>${t("gold_prem")}: <b>${num(sjcL.premium_pct, 1)}%</b> ${xbadge(sjcL.xcheck)}</span>` : ""}</div>`,
      (goldChk ? `<div class="kv"><span>${link(goldChk.url, t("gold_idx"))} ${goldChk.p}: <b>${num(goldChk.nso, 2)}%</b></span><span>${t("sjc_yoy")}: <b>${num(goldChk.sjc, 2)}%</b></span><span>${xbadge(Math.abs(goldChk.nso - goldChk.sjc) <= 10 ? "OK" : "LECH")}</span></div>` : "") +
      `<p class="caption">${t("gold_prem_note")}</p><p class="caption">${t("source")}: ${link(M.links.imf_pcps, "IMF Primary Commodity Prices")} · ${link(M.links.webgia, "webgia.com")} (${LANG === "vi" ? "dẫn nguồn" : "citing"} ${link(M.links.sjc, "SJC")})${goldL && goldL.xcheck_source ? " · " + esc(goldL.xcheck_source) : ""}</p>`),
  ].join("");
  const opt = (unit, d = 1) => ({ plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y, d)}${unit}` } } }, scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } } } });
  mkChart("cm_cpi", { type: "line", data: { labels: M.cpi.map(r => r.period), datasets: [{ label: "CPI YoY", data: M.cpi.map(r => +r.value), borderColor: C[0] }] }, options: opt("%", 2) });
  // step chart of SBV rates over monthly timeline
  const months = []; for (let y = 2018; y <= +today.slice(0, 4); y++) for (let m = 1; m <= 12; m++) { const p = `${y}-${String(m).padStart(2, "0")}`; if (p <= today.slice(0, 7)) months.push(p); }
  const rateAt = (p, f) => { let v = null; sbvRows.forEach(r => { if (r.effective_date.slice(0, 7) <= p) v = r[f]; }); return v; };
  mkChart("cm_sbv", { type: "line", data: { labels: months, datasets: [
    { label: t("refi"), data: months.map(p => rateAt(p, "refinancing_rate")), borderColor: C[0], stepped: true },
    { label: t("redis"), data: months.map(p => rateAt(p, "rediscount_rate")), borderColor: C[1], stepped: true }] },
    options: Object.assign(opt("%", 2), { plugins: { legend: { display: true }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y, 2)}%` } } } }) });
  mkChart("cm_vnindex", { type: "line", data: { labels: M.vnindex.map(r => r.period), datasets: [{ label: "VN-Index", data: M.vnindex.map(r => r.value), borderColor: C[0] }] }, options: opt("", 2) });
  mkChart("cm_gdp", { type: "bar", data: { labels: gq.map(r => r.period), datasets: [{ label: "GDP YoY", data: gq.map(r => r.gdp_yoy_pct), backgroundColor: gq.map(r => r.gdp_yoy_pct < 0 ? css("--s8") : C[0]), borderRadius: 2, maxBarThickness: 14 }] }, options: opt("%", 2) });
  mkChart("cm_fx", { type: "line", data: { labels: M.fx.map(r => r.period), datasets: [{ label: "VND/USD", data: M.fx.map(r => +r.value), borderColor: C[0] }] }, options: opt("", 0) });
  const sjcMap = Object.fromEntries(sjcRows.map(r => [r.period, +r.value]));
  mkChart("cm_gold", { type: "line", data: { labels: M.gold.map(r => r.period), datasets: [
    { label: t("gold_sjc"), data: M.gold.map(r => sjcMap[r.period] ?? null), borderColor: C[1], spanGaps: true },
    { label: t("gold_world"), data: M.gold.map(r => r.vnd_per_luong === "" ? null : +r.vnd_per_luong), borderColor: C[0] }] },
    options: Object.assign(opt("", 1), { plugins: { legend: { display: true }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${num(c.parsed.y, 1)}` } } } }) });
  // legal
  const L = (M.legal && M.legal.rows) || [];
  $("#legalTable").innerHTML = `<thead><tr><th class="l">${t("doc_issued")}</th><th class="l">${t("doc_eff")}</th><th class="l">${t("doc_no")}</th><th class="l">${t("doc_title")}</th><th class="l">${t("doc_sum")}</th></tr></thead><tbody>` +
    L.slice().sort((a, b) => (b.date_issued || "").localeCompare(a.date_issued || "")).map(r => `<tr><td class="l">${dmy(r.date_issued)}</td><td class="l">${dmy(r.effective_date)}</td><td class="l">${r.official_url ? link(r.official_url, r.number) + `<br><small>${link(r.official_url, t("official_link"))} · ${link(r.source_url, t("other_link"))}</small>` : link(r.source_url, r.number)}</td>
      <td class="l wrap">${esc(LANG === "vi" ? r.title_vi : r.title_en || r.title_vi)}</td><td class="l wrap">${esc(LANG === "vi" ? r.summary_vi : r.summary_en || r.summary_vi)}</td></tr>`).join("") +
    `</tbody>`;
  $("#legalTable").insertAdjacentHTML("afterend", "");
  $("#mAI").classList.toggle("hidden", !(S.settings && S.settings.configured.length));
}

/* ================= DOWNLOAD ================= */
let dlSel = new Set();
async function renderDownload() {
  if (!S.overview) S.overview = await api("/api/overview");
  $("#dlGroups").innerHTML = GROUPS.map(g => `<button data-g="${g}">+ ${t(g)}</button>`).join(" ");
  $("#dlChips").innerHTML = S.overview.tickers.map(r => `<span class="chip ${dlSel.has(r.ticker) ? "on" : ""}" data-t="${r.ticker}" title="${esc(r.name || "")}">${r.ticker}</span>`).join("");
  $("#dlCount").textContent = t("dl_selected", { n: dlSel.size });
}
function download(url) { const a = document.createElement("a"); a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); }

/* ================= SETTINGS ================= */
const PROVIDERS = [["claude", "Claude (Anthropic)", "https://console.anthropic.com/settings/keys"], ["gemini", "Gemini (Google)", "https://aistudio.google.com/app/apikey"], ["openai", "OpenAI", "https://platform.openai.com/api-keys"]];
async function renderSettings() {
  S.settings = await api("/api/settings");
  const s = S.settings;
  $("#setProviders").innerHTML = PROVIDERS.map(([k, name, url]) => `<div class="provider"><b>${name}</b>
    <input type="password" data-key="${k}" placeholder="${s.keys[k] || "API key"}" autocomplete="off">
    <input data-model="${k}" value="${esc(s.models[k] || "")}" title="model"></div>
    <div class="note" style="margin-left:118px">${LANG === "vi" ? "Lấy key tại" : "Get a key at"} <a href="${url}" target="_blank" rel="noopener">${url}</a> ${s.keys[k] ? `· <span class="badge ok">${s.keys[k]}</span> <a href="#" data-del="${k}">${LANG === "vi" ? "xoá" : "remove"}</a>` : ""}</div>`).join("");
  $("#setProvider").innerHTML = `<option value="">${t("none")}</option>` + PROVIDERS.map(([k, n]) => `<option value="${k}" ${s.provider === k ? "selected" : ""}>${n}</option>`).join("");
  const st = await api("/api/status");
  $("#setAbout").innerHTML = `<div class="kv"><span>Version <b>${st.version}</b></span><span>${t("c_last")}: <b>${dmy(st.fresh.data_last)}</b></span><span>${LANG === "vi" ? "Lần kiểm tra cuối" : "Last check"}: <b>${esc(st.fresh.last_check || "–")}</b></span></div>
    <p class="note">${LANG === "vi" ? "Mỗi lần mở ứng dụng, dữ liệu mới sẽ được tự động tải thêm (nếu có internet). Bạn cũng có thể bấm “Làm mới dữ liệu” bất cứ lúc nào. Ứng dụng chỉ chạy trên máy này (127.0.0.1), không chia sẻ ra ngoài." : "Each time the app starts it fetches missing days automatically (if online). You can also click “Refresh data” at any time. The app only listens on this computer (127.0.0.1)."}</p>`;
}
async function saveSettings(extra) {
  const keys = {}, models = {};
  $$("[data-key]").forEach(i => { if (i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
  $$("[data-model]").forEach(i => models[i.dataset.model] = i.value.trim());
  let provider = $("#setProvider").value;
  if (!provider) { const k = Object.keys(keys)[0]; if (k) provider = k; }
  S.settings = await post("/api/settings", Object.assign({ keys, models, provider, lang: LANG }, extra || {}));
  $("#setMsg").textContent = t("saved");
  renderSettings();
}
async function askAI(boxQ, boxA, body) {
  const q = $(boxQ).value.trim() || $(boxQ).placeholder;
  $(boxA).textContent = t("ai_wait");
  try { const r = await post("/api/ai", Object.assign({ question: q, lang: LANG }, body)); $(boxA).textContent = r.answer + `\n\n— ${r.model}`; }
  catch (e) { $(boxA).innerHTML = `<span class="badge bad">${esc(e.message)}</span>`; }
}

/* ================= GLOSSARY ================= */
function renderGlossary() {
  const order = ["close", "open", "adj", "volume", "chg", "ytd", "cagr", "vol", "mdd", "beta", "ma", "w52", "da", "de", "ta", "rg", "ca", "roa", "roe", "eps", "pe", "cpi", "sbv", "vnindex", "gdp", "fx", "gold"];
  const intro = LANG === "vi" ? `<div class="gl"><h4>Cách đọc dữ liệu</h4><ul>
    <li>Giá cổ phiếu tính bằng <b>nghìn đồng</b> (29,5 = 29.500 đ). Số liệu tài chính tính bằng đồng, hiển thị theo <b>tỷ đồng</b>.</li>
    <li><b>Giá gốc</b> là giá giao dịch thực tế; <b>giá điều chỉnh</b> loại bỏ ảnh hưởng của cổ tức/chia tách. Các % tăng giảm dùng giá điều chỉnh.</li>
    <li>Số liệu tài chính lấy từ báo cáo tài chính hợp nhất theo quý. “4 quý” (TTM) = cộng 4 quý gần nhất để có số của 12 tháng.</li>
    <li><b>Đối chiếu chéo</b>: mỗi phiên giá được so với SSI, VPS, CafeF; chỉ số vĩ mô được so giữa IMF, World Bank, Cục Thống kê, Vietcombank. “OK” = khớp, “LECH” = có chênh lệch (xem chi tiết), “NA” = chưa có nguồn thứ hai.</li>
    <li>Ô <span class="stale-mark">màu đỏ</span> = dữ liệu cũ, chưa cập nhật được tới phiên/kỳ mới nhất.</li></ul></div>` :
    `<div class="gl"><h4>How to read the data</h4><ul><li>Prices in <b>thousand VND</b>; financials shown in <b>billion VND</b>.</li><li><b>Raw</b> = traded price; <b>adjusted</b> removes dividend/split effects. % changes use adjusted prices.</li><li>Financials are consolidated quarterly statements; TTM = sum of the last 4 quarters.</li><li><b>Cross-check</b>: each session is compared with SSI, VPS, CafeF; macro figures across IMF, World Bank, NSO, Vietcombank.</li><li><span class="stale-mark">Red</span> = stale data.</li></ul></div>`;
  $("#glossary").innerHTML = intro + order.map(k => { const x = ex(k); return `<div class="gl"><h4>${esc(x[0])}</h4><p><b>${LANG === "vi" ? "Công thức" : "Formula"}:</b> <code>${esc(x[1])}</code></p><p>${esc(x[2])}</p></div>`; }).join("");
}

/* ================= events ================= */
function bind() {
  $("#tabs").addEventListener("click", e => { const b = e.target.closest("button[data-tab]"); if (b) showTab(b.dataset.tab); });
  $("#btnRefresh").onclick = startRefresh;
  $("#jobDetails").onclick = e => { e.preventDefault(); $("#jobLog").classList.toggle("hidden"); };
  $("#langSel").onchange = e => { LANG = e.target.value; try { localStorage.setItem("lang", LANG); } catch {} applyI18n(); chartDefaults(); fillGroupSelect($("#ovGroup")); fillGroupSelect($("#cmpGroup")); loadTab(currentTab()); };
  $("#btnTheme").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const nxt = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = nxt;
    try { localStorage.setItem("theme", nxt); } catch {}
    chartDefaults(); loadTab(currentTab());
  };
  ["#ovSearch", "#ovGroup", "#ovHideVic"].forEach(s => $(s).addEventListener("input", renderOverview));
  $("#ovColsBtn").onclick = e => { e.stopPropagation(); renderColPanel(); $("#ovColsPanel").classList.toggle("hidden"); };
  document.addEventListener("click", e => { if (!e.target.closest(".colpick")) $("#ovColsPanel").classList.add("hidden"); });
  $("#ovColsPanel").addEventListener("click", e => {
    const b = e.target.closest("button[data-preset]"); if (!b) return;
    const all = OV_COLS.map(c => c[0]).concat("xcheck").filter(k => !OV_FIXED.includes(k));
    ovHidden = new Set(b.dataset.preset === "all" ? [] : all.filter(k => !OV_PRESETS[b.dataset.preset].includes(k)));
    saveHidden(); renderColPanel(); renderOverview();
  });
  $("#ovColsPanel").addEventListener("change", e => { const c = e.target.dataset.col; if (!c) return;
    e.target.checked ? ovHidden.delete(c) : ovHidden.add(c); saveHidden(); renderOverview(); });
  $("#ovTable").addEventListener("click", e => {
    const th = e.target.closest("th[data-k]"); if (th) { ovSort = { k: th.dataset.k, dir: ovSort.k === th.dataset.k ? -ovSort.dir : 1 }; renderOverview(); return; }
    const tr = e.target.closest("tr[data-t]"); if (tr) { S.stockT = tr.dataset.t; showTab("stock"); }
  });
  $("#stSel").onchange = e => { S.stockT = e.target.value; renderStock(); };
  $("#stRange").onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("#stRange button").forEach(x => x.classList.toggle("on", x === b)); S.range = +b.dataset.r; drawStock(); };
  $("#stRaw").onchange = drawStock;
  $("#cmpGroup").onchange = renderCompare;
  $("#cmpRange").onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("#cmpRange button").forEach(x => x.classList.toggle("on", x === b)); S.cmpRange = +b.dataset.r; renderCompare(); };
  $("#cmpChips").onclick = e => { const c = e.target.closest(".chip"); if (!c) return; const tk = c.dataset.t; const i = S.cmp.indexOf(tk);
    if (i >= 0) S.cmp.splice(i, 1); else if (S.cmp.length < 8) S.cmp.push(tk); renderCompare(); };
  $("#dlChips").onclick = e => { const c = e.target.closest(".chip"); if (!c) return; const tk = c.dataset.t; dlSel.has(tk) ? dlSel.delete(tk) : dlSel.add(tk); renderDownload(); };
  $("#tab-download").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.sel === "all") { S.overview.tickers.forEach(r => dlSel.add(r.ticker)); renderDownload(); }
    if (b.dataset.sel === "none") { dlSel.clear(); renderDownload(); }
    if (b.dataset.g) { S.overview.tickers.filter(r => groupOf(r.segment) === b.dataset.g).forEach(r => dlSel.add(r.ticker)); renderDownload(); }
  });
  $("#dlBtn").onclick = () => { if (!dlSel.size) { alert(t("dl_selected", { n: 0 })); return; }
    const all = dlSel.size === S.overview.tickers.length; download(`/api/download?kind=${$("#dlKind").value}&tickers=${all ? "ALL" : [...dlSel].join(",")}`); };
  $("#dlMacro").onclick = () => download("/api/download?kind=macro");
  $("#dlIndex").onclick = () => download("/api/download?kind=prices&tickers=VNINDEX");
  $("#setSave").onclick = () => saveSettings();
  $("#setTest").onclick = async () => { await saveSettings(); $("#setMsg").textContent = t("ai_wait");
    try { const r = await post("/api/ai", { question: LANG === "vi" ? "Trả lời đúng 1 câu: kết nối thành công." : "Reply in one sentence: connection works.", lang: LANG }); $("#setMsg").textContent = "✓ " + r.model + ": " + r.answer.slice(0, 120); }
    catch (e) { $("#setMsg").innerHTML = `<span class="badge bad">${esc(e.message)}</span>`; } };
  $("#setProviders").addEventListener("click", async e => { const a = e.target.closest("[data-del]"); if (!a) return; e.preventDefault();
    const keys = {}; keys[a.dataset.del] = ""; S.settings = await post("/api/settings", { keys }); renderSettings(); });
  $("#stAIbtn").onclick = () => askAI("#stAIq", "#stAIans", { ticker: S.stockT });
  $("#mAIbtn").onclick = () => askAI("#mAIq", "#mAIans", { macro: true });
}

/* ================= init ================= */
(async function init() {
  try { const th = localStorage.getItem("theme"); if (th) document.documentElement.dataset.theme = th; LANG = localStorage.getItem("lang") || "vi"; } catch {}
  $("#langSel").value = LANG;
  applyI18n(); chartDefaults(); bind();
  fillGroupSelect($("#ovGroup")); fillGroupSelect($("#cmpGroup"));
  try { S.settings = await api("/api/settings"); } catch {}
  let tab = "overview"; try { tab = localStorage.getItem("tab") || "overview"; } catch {}
  showTab(tab);
  pollJob();
  setInterval(() => { if (!S.wasRunning) pollJob(); }, 10000);
})();
