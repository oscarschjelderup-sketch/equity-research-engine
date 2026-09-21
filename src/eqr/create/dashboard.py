"""Self-contained interactive HTML dashboard (Chart.js via CDN, data embedded as JSON)."""
from __future__ import annotations

import json
from pathlib import Path

from .style import ACCENT_BLUE, GREEN, GREY, LIGHT_BLUE, NAVY, RED, hx

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root { --navy: __NAVY__; --blue: __BLUE__; --green: __GREEN__; --grey: __GREY__; --accent: __ACCENT__; --red: __RED__;
          --bg: #f4f6f8; --card: #ffffff; --ink: #1c2833; --muted: #6b7a88; --line: #e3e8ee; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: Arial, "Helvetica Neue", sans-serif; background: var(--bg); color: var(--ink); font-size: 14px; }
  header { background: var(--navy); color: #fff; padding: 22px 28px; display: flex; flex-wrap: wrap; gap: 18px 36px; align-items: flex-end; }
  header h1 { font-family: Cambria, Georgia, serif; font-weight: normal; margin: 0; font-size: 30px; }
  header .sub { opacity: .8; font-size: 13px; margin-top: 4px; }
  .badge { display: inline-block; padding: 6px 14px; border-radius: 4px; font-weight: bold; font-size: 18px; letter-spacing: .5px; }
  .badge.BUY { background: var(--green); } .badge.HOLD { background: var(--grey); color: #fff; } .badge.SELL { background: var(--red); }
  .badge.NOT-RATED { background: #5b6770; color: #fff; }
  .hero { display: flex; gap: 28px; }
  .hero div { text-align: left; } .hero .v { font-size: 22px; font-weight: bold; } .hero .l { font-size: 11px; opacity: .8; text-transform: uppercase; }
  nav { background: #fff; border-bottom: 1px solid var(--line); padding: 0 28px; display: flex; gap: 4px; overflow-x: auto; }
  nav button { background: none; border: none; border-bottom: 3px solid transparent; padding: 14px 16px; font-size: 14px; color: var(--muted); cursor: pointer; }
  nav button.active { color: var(--navy); border-bottom-color: var(--navy); font-weight: bold; }
  main { padding: 22px 28px 40px; }
  section { display: none; } section.active { display: block; }
  .grid { display: grid; gap: 16px; } .g2 { grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); } .g3 { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .tile { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; }
  .tile .l { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; } .tile .v { font-size: 20px; font-weight: bold; margin-top: 4px; color: var(--navy); }
  .tile .s { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 16px; }
  .card h3 { margin: 0 0 10px; font-size: 14px; color: var(--navy); border-bottom: 2px solid var(--navy); padding-bottom: 6px; }
  .chart { position: relative; height: 280px; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { background: var(--navy); color: #fff; font-weight: bold; } td:first-child, th:first-child { text-align: left; }
  tr.bold td { font-weight: bold; } tr.it td { font-style: italic; color: #444; }
  td.est { background: #f6f8fb; }
  .sens td { text-align: center; } .sens th:first-child { text-align: center; }
  .sens th, .sens td { font-size: 11px; padding: 5px 3px; }  /* 8 columns must fit a one-third-width card */
  ul.b { margin: 6px 0 0; padding-left: 18px; } ul.b li { margin-bottom: 6px; line-height: 1.4; }
  .wrap { overflow-x: auto; }
  .muted { color: var(--muted); font-size: 12px; }
  .up { color: var(--green); font-weight: bold; } .down { color: var(--red); font-weight: bold; }
  .sliders { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px 22px; align-items: end; }
  .sl label { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-bottom: 4px; } .sl label b { color: var(--navy); }
  .sl input[type=range] { width: 100%; accent-color: var(--navy); }
  .slout { display: flex; gap: 26px; align-items: center; grid-column: 1 / -1; border-top: 1px solid var(--line); padding-top: 12px; flex-wrap: wrap; }
  .slout .l { font-size: 11px; color: var(--muted); text-transform: uppercase; } .slout .v { font-size: 24px; font-weight: bold; color: var(--navy); } .slout .s { font-size: 12px; color: var(--muted); }
  button#s-reset { background: var(--navy); color: #fff; border: none; border-radius: 4px; padding: 8px 14px; cursor: pointer; font-size: 13px; }
  footer { padding: 14px 28px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); }
  @media (max-width: 600px) { header h1 { font-size: 22px; } .hero { flex-wrap: wrap; gap: 14px; } }
</style>
</head>
<body>
<header>
  <div>
    <h1 id="h-name"></h1>
    <div class="sub" id="h-sub"></div>
  </div>
  <div><span class="badge" id="h-rating"></span></div>
  <div class="hero">
    <div><div class="v" id="h-price"></div><div class="l">Share price</div></div>
    <div><div class="v" id="h-tp"></div><div class="l">Target price</div></div>
    <div><div class="v" id="h-upside"></div><div class="l">Upside</div></div>
    <div><div class="v" id="h-dcf"></div><div class="l">DCF value</div></div>
    <div><div class="v" id="h-mult"></div><div class="l">Multiples value</div></div>
  </div>
</header>
<nav id="tabs">
  <button data-tab="overview" class="active">Overview</button>
  <button data-tab="financials">Financials</button>
  <button data-tab="valuation">Valuation</button>
  <button data-tab="peers">Peers</button>
  <button data-tab="assumptions">Assumptions &amp; notes</button>
</nav>
<main>
  <section id="overview" class="active">
    <div class="tiles" id="tiles"></div>
    <div class="grid g2">
      <div class="card"><h3 id="t-perf">Share price vs index (rebased to 100)</h3><div class="chart"><canvas id="c-perf"></canvas></div></div>
      <div class="card"><h3>Revenue and EBITDA</h3><div class="chart"><canvas id="c-rev"></canvas></div></div>
      <div class="card"><h3>Margins</h3><div class="chart"><canvas id="c-margin"></canvas></div></div>
      <div class="card"><h3>Investment highlights</h3><ul class="b" id="l-highlights"></ul><h3 style="margin-top:14px">Key risks</h3><ul class="b" id="l-risks"></ul></div>
    </div>
  </section>
  <section id="financials">
    <div class="card wrap"><h3 id="t-fin">Financials</h3><table id="tbl-fin"></table></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card wrap"><h3>Multiples at current price</h3><table id="tbl-fwd"></table></div>
      <div class="card"><h3>Financial commentary</h3><ul class="b" id="l-commentary"></ul></div>
    </div>
  </section>
  <section id="valuation">
    <div class="tiles" id="tiles-val"></div>
    <div class="card" style="margin-bottom:16px">
      <h3>Interactive DCF – move the drivers and watch the value change</h3>
      <div class="sliders">
        <div class="sl"><label>WACC <b id="o-wacc"></b></label><input type="range" id="s-wacc"></div>
        <div class="sl"><label>Terminal growth <b id="o-g"></b></label><input type="range" id="s-g"></div>
        <div class="sl"><label>Revenue growth shift (all years) <b id="o-gs"></b></label><input type="range" id="s-gs"></div>
        <div class="sl"><label>EBITDA margin shift (all years) <b id="o-ms"></b></label><input type="range" id="s-ms"></div>
        <div class="slout">
          <div><div class="l">Fair value per share</div><div class="v" id="o-value"></div><div class="s" id="o-vs-base"></div></div>
          <div><div class="l">vs share price</div><div class="v" id="o-upside"></div><div class="s" id="o-tp"></div></div>
          <div><button id="s-reset">Reset to base case</button></div>
        </div>
      </div>
      <div class="muted" style="margin-top:8px">Recomputes the full operating forecast (revenue, margins, capex, working capital) and the DCF in your browser, with the same formulas as the engine and the Excel model.</div>
    </div>
    <div class="grid g2">
      <div class="card wrap"><h3>Scenarios</h3><table id="tbl-scen"></table><ul class="b" id="l-scen" style="margin-top:10px"></ul></div>
      <div class="card"><h3>What the share price implies (reverse DCF)</h3><div class="tiles" id="tiles-rev" style="margin-bottom:8px"></div><ul class="b" id="l-implied"></ul></div>
      <div class="card wrap"><h3>DCF sensitivity – value per share (rows: terminal growth, columns: WACC)</h3><table class="sens" id="tbl-sens"></table>
        <div class="muted" style="margin-top:8px">Green cells are above the current share price, red below. Base case highlighted.</div></div>
      <div class="card"><h3>Football field</h3><div class="chart" style="height:320px"><canvas id="c-ff"></canvas></div></div>
      <div class="card"><h3>Own multiples through time</h3><div class="chart" style="height:280px"><canvas id="c-hist"></canvas></div><div class="muted" id="t-hist" style="margin-top:6px"></div></div>
      <div class="card"><h3>Do the valuation anchors agree?</h3><div class="tiles" id="tiles-cc" style="margin-bottom:8px"></div><div id="t-cc" style="line-height:1.5"></div></div>
      <div class="card"><h3>Investment thesis</h3><ul class="b" id="l-thesis"></ul></div>
      <div class="card wrap"><h3>Multiple valuation</h3><ul class="b" id="l-mult"></ul><table id="tbl-impl" style="margin-top:10px"></table></div>
    </div>
  </section>
  <section id="peers">
    <div class="grid g2">
      <div class="card"><h3>EV/EBITDA vs revenue growth</h3><div class="chart" style="height:340px"><canvas id="c-scatter"></canvas></div></div>
      <div class="card"><h3>Peer statistics</h3><table id="tbl-stats"></table></div>
    </div>
    <div class="card wrap" style="margin-top:16px"><h3>Peer group</h3><table id="tbl-peers"></table></div>
  </section>
  <section id="assumptions">
    <div class="grid g2">
      <div class="card wrap"><h3>Forecast drivers</h3><table id="tbl-drivers"></table><ul class="b" id="l-notes"></ul></div>
      <div class="card"><h3>Cost of capital</h3><table id="tbl-wacc"></table></div>
      <div class="card"><h3>Opportunities, disruption, threats</h3><b>Opportunities</b><ul class="b" id="l-opp"></ul><b>Disruption</b><ul class="b" id="l-dis"></ul><b>Threats</b><ul class="b" id="l-thr"></ul></div>
      <div class="card"><h3>Method and data</h3><div id="d-method" class="muted" style="font-size:13px;line-height:1.5"></div></div>
    </div>
  </section>
</main>
<footer id="foot"></footer>
<script>
const D = __DATA__;
const NAVY = getComputedStyle(document.documentElement).getPropertyValue('--navy').trim();
const BLUE = getComputedStyle(document.documentElement).getPropertyValue('--blue').trim();
const GREEN = getComputedStyle(document.documentElement).getPropertyValue('--green').trim();
const GREY = getComputedStyle(document.documentElement).getPropertyValue('--grey').trim();
const RED = getComputedStyle(document.documentElement).getPropertyValue('--red').trim();
const ok = v => v !== null && v !== undefined && !Number.isNaN(v);
const fmtN = (v, d = 0) => ok(v) ? Number(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) : '–';
const fmtP = (v, d = 1, sign = false) => ok(v) ? ((sign && v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%') : '–';
const fmtX = v => ok(v) && v > 0 ? Number(v).toFixed(1) + 'x' : (ok(v) ? 'n.m.' : '–');
const md = s => String(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
const frame = f => { if (!f) return []; return f.index.map((ix, i) => { const o = {_index: ix}; f.columns.forEach((c, j) => o[c] = f.data[i][j]); return o; }); };
const el = id => document.getElementById(id);
const c = D.company, rec = D.recommendation, ccy = c.currency, pccy = c.price_currency || c.currency;

// ---------------- header
el('h-name').textContent = `${c.name} (${c.ticker})`;
el('h-sub').textContent = `${c.sector || ''} · ${c.country || ''} · as of ${D.as_of} · narrative: ${D.narrative_mode}` + (pccy !== ccy ? ` · accounts in ${ccy}, share price in ${pccy}` : '');
el('h-rating').textContent = rec.rating; el('h-rating').classList.add(rec.rating.replace(' ', '-'));
el('h-price').textContent = `${pccy} ${fmtN(c.price, 2)}`;
el('h-tp').textContent = `${pccy} ${fmtN(rec.target_price, 2)}`;
el('h-upside').textContent = fmtP(rec.upside, 0, true);
el('h-dcf').textContent = `${pccy} ${fmtN(rec.dcf_value, 2)}`;
el('h-mult').textContent = ok(rec.multiples_value) ? `${pccy} ${fmtN(rec.multiples_value, 2)}` : '–';

// ---------------- tabs
const showTab = name => {
  const btn = document.querySelector(`#tabs button[data-tab="${name}"]`);
  if (!btn) return;
  document.querySelectorAll('#tabs button').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('main section').forEach(x => x.classList.remove('active'));
  btn.classList.add('active'); el(name).classList.add('active');
  window.dispatchEvent(new Event('resize'));
};
document.querySelectorAll('#tabs button').forEach(b => b.addEventListener('click', () => { history.replaceState(null, '', '#' + b.dataset.tab); showTab(b.dataset.tab); }));
window.addEventListener('load', () => { const h = location.hash.replace('#', ''); if (h) showTab(h); });

// ---------------- overview tiles
const hist = frame(D.hist), fc = frame(D.forecast).filter(r => r._index !== 'TV'), comb = frame(D.combined);
const last = hist[hist.length - 1];
const tiles = [
  ['Market cap', `${ccy} ${fmtN(c.market_cap)}m`, `EV ${ccy} ${fmtN(c.enterprise_value)}m`],
  [`Revenue ${last._index}A`, `${ccy} ${fmtN(last.revenue)}m`, `${fmtP(last.growth)} growth`],
  ['EBITDA margin', fmtP(last.ebitda_margin), `EBIT margin ${fmtP(last.ebit_margin)}`],
  ['EV/EBITDA (LTM)', fmtX(D.comps.company.ev_ebitda), `Peer median ${fmtX((D.comps.stats['All|median'] || {}).ev_ebitda)}`],
  ['P/E (LTM)', fmtX(D.comps.company.pe), `Fwd P/E ${fmtX(D.comps.company.fwd_pe)}`],
  ['Net debt / EBITDA', fmtX(last.nd_to_ebitda), `Net debt ${ccy} ${fmtN(c.net_debt)}m`],
  ['FCF margin', fmtP(last.ufcf_margin), `UFCF ${ccy} ${fmtN(last.ufcf)}m`],
  ['Consensus target', ok((c.consensus_target || {}).mean) ? `${pccy} ${fmtN(c.consensus_target.mean, 2)}` : '–', `${(D.comps.company && D.company.consensus_target && D.company.consensus_target.high) ? 'range ' + fmtN(c.consensus_target.low, 0) + '–' + fmtN(c.consensus_target.high, 0) : ''}`],
];
el('tiles').innerHTML = tiles.map(t => `<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('');
el('l-highlights').innerHTML = (D.narrative.highlights || []).map(x => `<li>${md(x)}</li>`).join('');
el('l-risks').innerHTML = (D.narrative.risks || []).map(x => `<li>${md(x)}</li>`).join('');

// ---------------- charts (overview)
Chart.defaults.font.family = 'Arial'; Chart.defaults.font.size = 11; Chart.defaults.color = '#4a5563';
const baseOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } } };
const rel = frame(D.relative_performance);
if (rel.length) {
  el('t-perf').textContent = `Share price vs ${D.config.index_name || D.config.index} (rebased to 100)`;
  new Chart(el('c-perf'), { type: 'line', data: { labels: rel.map(r => String(r._index).slice(0, 7)), datasets: [
      { label: c.short_name, data: rel.map(r => r.stock), borderColor: NAVY, borderWidth: 2, pointRadius: 0, tension: .2 },
      { label: D.config.index_name || D.config.index, data: rel.map(r => r.index), borderColor: GREY, borderWidth: 1.5, pointRadius: 0, tension: .2 }]},
    options: { ...baseOpts, interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } }, y: { grid: { color: '#eef1f4' } } } } });
}
const labels = comb.filter(r => r._index !== 'TV').map(r => r._index);
const rows = comb.filter(r => r._index !== 'TV');
const isEst = l => l.endsWith('E');
new Chart(el('c-rev'), { type: 'bar', data: { labels, datasets: [
    { label: `Revenue (${c.units})`, data: rows.map(r => r.revenue), backgroundColor: labels.map(l => isEst(l) ? BLUE : NAVY) },
    { label: `EBITDA (${c.units})`, data: rows.map(r => r.ebitda), backgroundColor: '#BFC5CA' }]},
  options: { ...baseOpts, scales: { x: { grid: { display: false } }, y: { grid: { color: '#eef1f4' }, ticks: { callback: v => fmtN(v) } } },
    plugins: { ...baseOpts.plugins, tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtN(ctx.raw)}` } } } } });
new Chart(el('c-margin'), { type: 'line', data: { labels, datasets: [
    { label: 'EBITDA margin', data: rows.map(r => r.ebitda_margin * 100), borderColor: NAVY, backgroundColor: NAVY, borderWidth: 2, pointRadius: 3 },
    { label: 'EBIT margin', data: rows.map(r => r.ebit_margin * 100), borderColor: BLUE, backgroundColor: BLUE, borderWidth: 2, pointRadius: 3 },
    { label: 'FCF margin', data: rows.map(r => r.ufcf_margin * 100), borderColor: GREEN, backgroundColor: GREEN, borderWidth: 2, pointRadius: 3 }]},
  options: { ...baseOpts, scales: { x: { grid: { display: false } }, y: { grid: { color: '#eef1f4' }, ticks: { callback: v => v.toFixed(0) + '%' } } },
    plugins: { ...baseOpts.plugins, tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(1)}%` } } } } });

// ---------------- financials table
el('t-fin').textContent = `Financials (${c.units}, ${D.config.assumptions.lease_treatment === 'operating' ? 'pre-IFRS 16 basis' : 'reported basis'})`;
const spec = [['Revenue', 'revenue', fmtN, 'bold'], ['Growth', 'growth', fmtP, 'it'], ['EBITDA', 'ebitda', fmtN, 'bold'], ['Margin', 'ebitda_margin', fmtP, 'it'],
  ['EBIT', 'ebit', fmtN, 'bold'], ['Margin', 'ebit_margin', fmtP, 'it'], ['NOPAT', 'nopat', fmtN, 'bold'], ['Margin', 'nopat_margin', fmtP, 'it'],
  ['D&A', 'da', fmtN, ''], ['Capex', 'capex', fmtN, ''], ['Change in NWC', 'nwc_change', fmtN, ''], ['Unlevered FCF', 'ufcf', fmtN, 'bold'], ['FCF margin', 'ufcf_margin', fmtP, 'it']];
const allLabels = comb.map(r => r._index);
el('tbl-fin').innerHTML = `<tr><th>${c.units}</th>${allLabels.map(l => `<th>${l}</th>`).join('')}</tr>` +
  spec.map(s => `<tr class="${s[3]}"><td>${s[0]}</td>${comb.map(r => `<td class="${isEst(r._index) || r._index === 'TV' ? 'est' : ''}">${s[2](r[s[1]])}</td>`).join('')}</tr>`).join('');
const fwd = D.forward_multiples;
if (fwd) el('tbl-fwd').innerHTML = `<tr><th>Multiple</th>${fwd.columns.map(x => `<th>${x}</th>`).join('')}</tr>` +
  fwd.index.map((name, i) => `<tr><td>${name}</td>${fwd.data[i].map(v => `<td>${name.includes('yield') ? fmtP(v) : fmtX(v)}</td>`).join('')}</tr>`).join('');
el('l-commentary').innerHTML = (D.narrative.financial_commentary || []).map(x => `<li>${md(x)}</li>`).join('');

// ---------------- valuation
const dcf = D.dcf, w = D.wacc;
el('tiles-val').innerHTML = [
  ['Enterprise value (DCF)', `${ccy} ${fmtN(dcf.enterprise_value)}m`, `PV FCF ${fmtN(dcf.sum_pv_fcf)} + PV TV ${fmtN(dcf.pv_terminal)}`],
  ['Equity value', `${ccy} ${fmtN(dcf.equity_value)}m`, `Net debt ${fmtN(dcf.net_debt)}m`],
  ['Fair value per share', `${pccy} ${fmtN(dcf.value_per_share, 2)}`, `${fmtP(dcf.upside, 0, true)} vs price`],
  [rec.horizon_months ? '12-month target price' : 'Target price', `${pccy} ${fmtN(rec.target_price, 2)}`, `total return ${fmtP(rec.total_return, 0, true)} incl. DPS ${fmtN(rec.dps, 2)}`],
  ['WACC', fmtP(w.wacc, 2), `Ke ${fmtP(w.cost_of_equity, 1)} · Kd ${fmtP(w.cost_of_debt_after_tax, 1)} after tax`],
  ['Terminal growth', fmtP(dcf.terminal_growth, 2), `TV ${fmtP(dcf.tv_share_of_ev, 0)} of EV`],
  ['Implied exit EV/EBITDA', fmtX(dcf.implied_exit_ev_ebitda), `Beta ${fmtN(w.beta_used, 2)}`],
].map(t => `<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('');
// ---- interactive DCF (same arithmetic as eqr.analyze.forecast / dcf)
function dcfValue(wacc, g, gShift, mShift) {
  const dr = D.drivers; let prev = last.revenue, nopatLast = 0; const fcfs = [];
  dr.revenue_growth.forEach((gr, i) => {
    const rev = prev * (1 + gr + gShift), m = dr.ebitda_margin[i] + mShift;
    const ebitda = rev * m, da = rev * dr.da_pct, ebit = ebitda - da, nopat = ebit - Math.max(ebit, 0) * dr.tax_rate;
    const cp = (dr.capex_pct_path && dr.capex_pct_path.length) ? dr.capex_pct_path[Math.min(i, dr.capex_pct_path.length - 1)] : dr.capex_pct;
    fcfs.push(nopat + da - rev * cp - dr.nwc_pct * (rev - prev)); nopatLast = nopat; prev = rev;
  });
  if (wacc <= g) return NaN;
  const mid = D.config.assumptions.mid_year_convention ? 0.5 : 0, n = fcfs.length;
  let pv = 0; fcfs.forEach((f, i) => pv += f / Math.pow(1 + wacc, i + 1 - mid));
  const tcf = (dcf.terminal_method === 'value_driver' && dcf.ronic) ? nopatLast * (1 + g) * (1 - g / dcf.ronic) : fcfs[n - 1] * (1 + g);
  return (pv + tcf / (wacc - g) / Math.pow(1 + wacc, n) - c.net_debt - c.minorities) / D.shares_effective;
}
const sl = { wacc: el('s-wacc'), g: el('s-g'), gs: el('s-gs'), ms: el('s-ms') };
const setRange = (inp, min, max, step, val) => { inp.min = min; inp.max = max; inp.step = step; inp.value = val; };
function resetSliders() {
  setRange(sl.wacc, Math.max(w.wacc - 0.03, 0.03).toFixed(4), (w.wacc + 0.03).toFixed(4), 0.001, w.wacc.toFixed(4));
  setRange(sl.g, (dcf.terminal_growth - 0.015).toFixed(4), (dcf.terminal_growth + 0.015).toFixed(4), 0.0005, dcf.terminal_growth.toFixed(4));
  setRange(sl.gs, -0.05, 0.05, 0.0025, 0); setRange(sl.ms, -0.05, 0.05, 0.0025, 0); updateSliders();
}
function updateSliders() {
  const wv = +sl.wacc.value, gv = +sl.g.value, gs = +sl.gs.value, ms = +sl.ms.value;
  el('o-wacc').textContent = fmtP(wv, 2); el('o-g').textContent = fmtP(gv, 2);
  el('o-gs').textContent = fmtP(gs, 2, true); el('o-ms').textContent = fmtP(ms, 2, true);
  const v = dcfValue(wv, gv, gs, ms), base = dcf.value_per_share;
  el('o-value').textContent = ok(v) ? `${pccy} ${fmtN(v, 2)}` : 'n.m.';
  el('o-vs-base').textContent = ok(v) ? `${fmtP(v / base - 1, 0, true)} vs base case ${fmtN(base, 2)}` : 'WACC must exceed growth';
  const up = v / c.price - 1; el('o-upside').textContent = ok(v) ? fmtP(up, 0, true) : '–';
  el('o-upside').className = 'v ' + (up >= 0 ? 'up' : 'down');
  const m = rec.horizon_months || 0, ke = rec.cost_of_equity || 0;
  el('o-tp').textContent = ok(v) && m ? `12m target ${pccy} ${fmtN(v * Math.pow(1 + ke, m / 12) - (rec.dps || 0), 2)}` : '';
}
Object.values(sl).forEach(i => i.addEventListener('input', updateSliders));
el('s-reset').addEventListener('click', resetSliders); resetSliders();

// ---- scenarios and reverse DCF
const scen = D.scenarios || [];
el('tbl-scen').innerHTML = `<tr><th>Scenario</th><th>Prob.</th><th>Rev. CAGR</th><th>Margin</th><th>WACC</th><th>Value</th><th>vs price</th></tr>` +
  scen.map(x => `<tr><td>${x.name}</td><td>${fmtP(x.probability, 0)}</td><td>${fmtP(x.revenue_cagr)}</td><td>${fmtP(x.final_margin)}</td><td>${fmtP(x.wacc, 2)}</td><td>${fmtN(x.value_per_share, 2)}</td><td class="${x.upside >= 0 ? 'up' : 'down'}">${fmtP(x.upside, 0, true)}</td></tr>`).join('') +
  (ok(D.scenario_weighted_value) ? `<tr class="bold"><td>Weighted</td><td>100%</td><td colspan="3"></td><td>${fmtN(D.scenario_weighted_value, 2)}</td><td class="${D.scenario_weighted_value >= c.price ? 'up' : 'down'}">${fmtP(D.scenario_weighted_value / c.price - 1, 0, true)}</td></tr>` : '');
el('l-scen').innerHTML = (D.narrative.scenario_commentary || []).map(x => `<li>${md(x)}</li>`).join('');
const rv = D.reverse_dcf || {};
el('tiles-rev').innerHTML = [
  ['Implied WACC', ok(rv.implied_wacc) ? fmtP(rv.implied_wacc, 2) : 'n.a.', `ours ${fmtP(rv.base_wacc, 2)}`],
  ['Implied terminal growth', ok(rv.implied_terminal_growth) ? fmtP(rv.implied_terminal_growth, 2) : 'n.a.', `ours ${fmtP(rv.base_terminal_growth, 2)}`],
  ['Implied final-year margin', ok(rv.implied_final_margin) ? fmtP(rv.implied_final_margin) : 'n.a.', `ours ${fmtP(rv.base_final_margin)}`],
].map(t => `<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('');
el('l-implied').innerHTML = (D.narrative.market_implied || []).map(x => `<li>${md(x)}</li>`).join('') +
  `<li class="muted">Each figure solves for the single input that makes the DCF equal today's share price, holding the others at the base case.</li>`;

const s = dcf.sensitivity;
if (s) {
  const k = Math.floor(s.waccs.length / 2);
  const maxDev = Math.max(...s.values.flat().filter(ok).map(v => Math.abs(v / c.price - 1)), 0.01);
  const color = v => { if (!ok(v)) return ''; const d = v / c.price - 1; const a = Math.min(Math.abs(d) / maxDev, 1) * 0.55 + 0.08;
    return d >= 0 ? `rgba(64,112,97,${a})` : `rgba(192,57,43,${a})`; };
  el('tbl-sens').innerHTML = `<tr><th>g \\ WACC</th>${s.waccs.map(x => `<th>${fmtP(x, 2)}</th>`).join('')}</tr>` +
    s.growths.map((g, i) => `<tr><td style="background:${NAVY};color:#fff;font-weight:bold">${fmtP(g, 2)}</td>${s.values[i].map((v, j) =>
      `<td style="background:${color(v)};${i === k && j === k ? 'outline:2px solid ' + NAVY + ';font-weight:bold' : ''}">${fmtN(v, 1)}</td>`).join('')}</tr>`).join('');
}
const ff = D.football || [];
const linePlugin = { id: 'lines', afterDraw(chart) { const {ctx, chartArea: {top, bottom}, scales: {x}} = chart;
  [[c.price, RED, 'Price ' + fmtN(c.price, 2)], [rec.target_price, '#B8860B', 'TP ' + fmtN(rec.target_price, 2)]].forEach(([v, col, lab], idx) => {
    const px = x.getPixelForValue(v); ctx.save(); ctx.strokeStyle = col; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = col; ctx.font = 'bold 11px Arial';
    const right = (idx === 0) === (c.price >= rec.target_price);  // put the two labels on opposite sides of their lines
    ctx.textAlign = right ? 'left' : 'right'; ctx.fillText(lab, px + (right ? 4 : -4), top - 6); ctx.restore(); }); } };  // above the bars (layout padding)
const ffVals = ff.flatMap(b => [b.low, b.high]).concat([c.price, rec.target_price]).filter(ok);
const ffMin = Math.min(...ffVals), ffMax = Math.max(...ffVals), ffPad = (ffMax - ffMin) * 0.15 || 1;
new Chart(el('c-ff'), { type: 'bar', data: { labels: ff.map(b => b.label), datasets: [{ label: 'Range', data: ff.map(b => [b.low, b.high]), backgroundColor: NAVY, borderSkipped: false, barPercentage: .55 }] },
  options: { ...baseOpts, indexAxis: 'y', layout: { padding: { top: 20 } }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${fmtN(ctx.raw[0], 1)} – ${fmtN(ctx.raw[1], 1)}` } } },
    scales: { x: { min: Math.max(0, Math.floor(ffMin - ffPad)), max: Math.ceil(ffMax + ffPad), title: { display: true, text: `${pccy} per share` }, grid: { color: '#eef1f4' } },
              y: { grid: { display: false } } } }, plugins: [linePlugin] });
// ---- own multiples through time + cross-check
const mh = D.multiple_history;
if (mh && mh.dates && mh.dates.length) {
  const st = (mh.stats || {}).ev_ebitda || (mh.stats || {}).pe, useEv = !!(mh.stats || {}).ev_ebitda;
  const vals = useEv ? mh.ev_ebitda : mh.pe, name = useEv ? 'EV/EBITDA' : 'P/E';
  const flat = v => mh.dates.map(() => v);
  new Chart(el('c-hist'), { type: 'line', data: { labels: mh.dates.map(d => d.slice(0, 7)), datasets: [
      { label: `Trailing ${name}`, data: vals, borderColor: NAVY, borderWidth: 2, pointRadius: 0, tension: .15, spanGaps: true },
      { label: `Median ${fmtX(st.median)}`, data: flat(st.median), borderColor: GREY, borderDash: [6, 4], borderWidth: 1.3, pointRadius: 0 },
      { label: '25th pct', data: flat(st.p25), borderColor: BLUE, borderWidth: 1, pointRadius: 0 },
      { label: '75th pct', data: flat(st.p75), borderColor: BLUE, borderWidth: 1, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(129,176,192,0.22)' }]},
    options: { ...baseOpts, interaction: { mode: 'index', intersect: false }, scales: { x: { ticks: { maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
      y: { grid: { color: '#eef1f4' }, ticks: { callback: v => v.toFixed(0) + 'x' } } } } });
  el('t-hist').textContent = `${fmtX(st.current)} today vs a ${st.years.toFixed(1)}-year median of ${fmtX(st.median)}; ${fmtP(st.percentile, 0)} of weeks were cheaper.`;
} else { el('c-hist').parentElement.innerHTML = '<div class="muted">Not enough history with positive earnings to build a band.</div>'; }
const cc = D.crosscheck || {};
const ccColour = {high: GREEN, medium: '#B8860B', low: RED}[cc.agreement] || GREY;
el('tiles-cc').innerHTML = [
  ['Agreement', `<span style="color:${ccColour}">${(cc.agreement || 'n/a').toUpperCase()}</span>`, ok(cc.max_gap) ? `largest gap ${fmtP(cc.max_gap, 0)}` : ''],
  ['DCF vs peer multiples', ok(cc.dcf_vs_multiples) ? fmtP(cc.dcf_vs_multiples, 0, true) : 'n.a.', 'fair value today'],
  ['Our target vs consensus', ok(cc.target_vs_consensus) ? fmtP(cc.target_vs_consensus, 0, true) : 'n.a.', ok(cc.consensus_target) ? `${pccy} ${fmtN(cc.consensus_target, 2)}, ${cc.n_analysts || '?'} analysts` : ''],
].map(t => `<div class="tile"><div class="l">${t[0]}</div><div class="v">${t[1]}</div><div class="s">${t[2]}</div></div>`).join('');
el('t-cc').textContent = cc.message ? cc.message.charAt(0).toUpperCase() + cc.message.slice(1) + '.' : '';

el('l-thesis').innerHTML = (D.narrative.thesis || []).map(x => `<li>${md(x)}</li>`).join('');
el('l-mult').innerHTML = (D.narrative.multiples_commentary || []).map(x => `<li>${md(x)}</li>`).join('');
const impl = Object.values(D.comps.implied || {});
el('tbl-impl').innerHTML = `<tr><th>Multiple</th><th>Median</th><th>Implied</th><th>25–75th pct</th><th>vs price</th></tr>` +
  impl.map(v => `<tr><td>${v.label}</td><td>${fmtX(v.multiple)}</td><td>${fmtN(v.per_share, 2)}</td><td>${fmtN(v.low, 1)} – ${fmtN(v.high, 1)}</td><td class="${v.per_share >= c.price ? 'up' : 'down'}">${fmtP(v.per_share / c.price - 1, 0, true)}</td></tr>`).join('');

// ---------------- peers
const peers = D.comps.table || [];
const pts = peers.filter(p => ok(p.ev_ebitda) && ok(p.revenue_growth));
new Chart(el('c-scatter'), { type: 'scatter', data: { datasets: [
    { label: 'Peers', data: pts.map(p => ({x: p.revenue_growth * 100, y: p.ev_ebitda, name: p.name})), backgroundColor: BLUE, pointRadius: 6 },
    { label: c.short_name, data: [{x: last.growth * 100, y: D.comps.company.ev_ebitda, name: c.short_name}], backgroundColor: GREEN, pointRadius: 9 }]},
  options: { ...baseOpts, plugins: { ...baseOpts.plugins, tooltip: { callbacks: { label: ctx => `${ctx.raw.name}: ${ctx.raw.x.toFixed(1)}% growth, ${ctx.raw.y.toFixed(1)}x EV/EBITDA` } } },
    scales: { x: { title: { display: true, text: 'Revenue growth (last FY, %)' }, grid: { color: '#eef1f4' } }, y: { title: { display: true, text: 'EV/EBITDA (x)' }, grid: { color: '#eef1f4' } } } } });
const stats = D.comps.stats || {};
const statKeys = ['ev_sales', 'ev_ebitda', 'ev_ebit', 'pe', 'fwd_pe', 'revenue_growth', 'ebitda_margin'];
const statLabels = {ev_sales: 'EV/Sales', ev_ebitda: 'EV/EBITDA', ev_ebit: 'EV/EBIT', pe: 'P/E', fwd_pe: 'P/E (fwd)', revenue_growth: 'Rev. growth', ebitda_margin: 'EBITDA margin'};
const fmtStat = (k, v) => (k === 'revenue_growth' || k === 'ebitda_margin') ? fmtP(v) : fmtX(v);
el('tbl-stats').innerHTML = `<tr><th>Group / stat</th>${statKeys.map(k => `<th>${statLabels[k]}</th>`).join('')}</tr>` +
  Object.keys(stats).filter(k => k.endsWith('median') || k.endsWith('mean')).map(k => `<tr><td>${k.replace('|', ' – ')}</td>${statKeys.map(m => `<td>${fmtStat(m, stats[k][m])}</td>`).join('')}</tr>`).join('') +
  `<tr class="bold"><td>${c.short_name}</td>${statKeys.map(m => `<td>${m === 'revenue_growth' ? fmtP(last.growth) : m === 'ebitda_margin' ? fmtP(last.ebitda_margin) : fmtX(D.comps.company[m])}</td>`).join('')}</tr>`;
el('tbl-peers').innerHTML = `<tr><th>Company</th><th>Group</th><th>Mkt cap (${c.units})</th><th>EV (${c.units})</th><th>Rev. growth</th><th>EBITDA margin</th><th>EV/Sales</th><th>EV/EBITDA</th><th>EV/EBIT</th><th>P/E</th><th>P/E fwd</th></tr>` +
  peers.map(p => `<tr><td>${p.name} <span class="muted">${p.ticker}</span></td><td>${p.group}</td><td>${fmtN(p.market_cap)}</td><td>${fmtN(p.ev)}</td><td>${fmtP(p.revenue_growth)}</td><td>${fmtP(p.ebitda_margin)}</td><td>${fmtX(p.ev_sales)}</td><td>${fmtX(p.ev_ebitda)}</td><td>${fmtX(p.ev_ebit)}</td><td>${fmtX(p.pe)}</td><td>${fmtX(p.fwd_pe)}</td></tr>`).join('');

// ---------------- assumptions
const dr = D.drivers;
el('tbl-drivers').innerHTML = `<tr><th>Driver</th>${dr.years.map(y => `<th>${y}E</th>`).join('')}</tr>` +
  `<tr><td>Revenue growth</td>${dr.revenue_growth.map(v => `<td>${fmtP(v)}</td>`).join('')}</tr>` +
  `<tr><td>EBITDA margin</td>${dr.ebitda_margin.map(v => `<td>${fmtP(v)}</td>`).join('')}</tr>` +
  `<tr><td>D&A % revenue</td>${dr.years.map(() => `<td>${fmtP(dr.da_pct)}</td>`).join('')}</tr>` +
  `<tr><td>Capex % revenue</td>${dr.years.map((y, i) => `<td>${fmtP((dr.capex_pct_path && dr.capex_pct_path.length) ? dr.capex_pct_path[i] : dr.capex_pct)}</td>`).join('')}</tr>` +
  `<tr><td>Net working capital % revenue</td>${dr.years.map(() => `<td>${fmtP(dr.nwc_pct, 1)}</td>`).join('')}</tr>` +
  `<tr><td>Tax rate</td>${dr.years.map(() => `<td>${fmtP(dr.tax_rate)}</td>`).join('')}</tr>`;
el('l-notes').innerHTML = (dr.notes || []).map(x => `<li>${x}</li>`).join('') + `<li>Growth anchor: ${dr.growth_anchor}.</li>`;
el('tbl-wacc').innerHTML = [['Risk-free rate', fmtP(w.risk_free, 2)], ['Equity risk premium', fmtP(w.equity_risk_premium, 2)], ['Beta (raw / used)', `${fmtN(w.beta_raw, 2)} / ${fmtN(w.beta_used, 2)}`],
  ['Beta source', w.beta_source], ['Size premium', `${fmtP(w.size_premium, 2)} (${w.size_premium_source || 'config'})`], ['Cost of equity', fmtP(w.cost_of_equity, 2)], ['Cost of debt (pre-tax)', `${fmtP(w.cost_of_debt_pretax, 2)} (${w.cost_of_debt_source})`],
  ['Tax rate', fmtP(w.tax_rate, 1)], ['Weights (E / D)', `${fmtP(w.weight_equity, 0)} / ${fmtP(w.weight_debt, 0)}`], ['WACC', `<b>${fmtP(w.wacc, 2)}</b>`]]
  .map(r => `<tr><td>${r[0]}</td><td style="text-align:right">${r[1]}</td></tr>`).join('');
el('l-opp').innerHTML = (D.narrative.opportunities || []).map(x => `<li>${md(x)}</li>`).join('');
el('l-dis').innerHTML = (D.narrative.disruption || []).map(x => `<li>${md(x)}</li>`).join('');
el('l-thr').innerHTML = (D.narrative.threats || []).map(x => `<li>${md(x)}</li>`).join('');
el('d-method').innerHTML = `<p><b>Retrieve:</b> statements, prices, estimates and peers from Yahoo Finance (cached). <b>Analyze:</b> lease-adjusted historicals, driver-based forecast, CAPM WACC, FCFF DCF with Gordon terminal value, peer multiples on a consistent basis. <b>Create:</b> this dashboard, a PowerPoint case deck and an Excel model with live formulas.</p>
  <p>Lease treatment: <b>${D.config.assumptions.lease_treatment}</b> (lease rate ${fmtP(D.config.assumptions.lease_rate, 1)}). Recommendation thresholds: BUY ≥ ${fmtP(D.config.recommendation.buy_threshold, 0)}, SELL ≤ ${fmtP(D.config.recommendation.sell_threshold, 0)}. Target price method: ${rec.method}.</p>
  <p>${D.config.sources_note}. ${(D.warnings || []).length ? '<br><b>Warnings:</b> ' + D.warnings.join(' ') : ''}</p>`;
el('foot').textContent = `${D.config.brand.name} · ${D.config.brand.footer_note} · generated ${D.as_of}`;
</script>
</body>
</html>
"""


def build_dashboard(result, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    data = json.dumps(result.to_json_dict(), ensure_ascii=False, default=str)
    html = (TEMPLATE.replace("__DATA__", data.replace("</", "<\\/"))
            .replace("__TITLE__", f"{result.name} – Equity Research Dashboard")
            .replace("__NAVY__", hx(NAVY)).replace("__BLUE__", hx(LIGHT_BLUE)).replace("__GREEN__", hx(GREEN))
            .replace("__GREY__", hx(GREY)).replace("__ACCENT__", hx(ACCENT_BLUE)).replace("__RED__", hx(RED)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
