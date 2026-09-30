"""One-page research note: the front page of a sell-side report.

A portfolio manager reads the front page and nothing else: rating and target, the investment case
in three bullets, where the analyst differs from consensus, the key figures table with multiples by
year, the catalysts and the risks. Everything comes from the analysis; nothing is typed by hand.
Written as print-ready HTML (A4) and turned into PDF by a headless browser (``render.html_to_pdf``).
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Template

from . import charts as _charts  # noqa: F401  (sets the matplotlib backend and house style)
from .style import DARK_GREY, GREY, LIGHT_GREY, NAVY, fmt_mult, fmt_num, fmt_pct, hx

TEMPLATE = Template(r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ name }} – research note</title>
<style>
  @page { size: A4; margin: 11mm 12mm 10mm 12mm; }
  :root { --navy: #003255; --blue: #81B0C0; --green: #407061; --red: #B03A2E; --grey: #8F9DA6; --light: #EEF1F4; --line: #D5DCE2; }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: #fff; color: #1d2733; font-family: Arial, Helvetica, sans-serif; font-size: 8.4pt; line-height: 1.32; }
  .page { width: 186mm; min-height: 270mm; margin: 0 auto; display: flex; flex-direction: column; }
  .bar { display: flex; justify-content: space-between; align-items: center; background: var(--navy); color: #fff; padding: 2.2mm 3mm;
         font-size: 7.8pt; letter-spacing: .3px; }
  .bar b { font-family: Cambria, Georgia, serif; font-size: 10pt; letter-spacing: 0; }
  .title { display: flex; justify-content: space-between; align-items: flex-end; margin: 3.5mm 0 1mm; }
  h1 { font-family: Cambria, Georgia, serif; font-size: 19pt; color: var(--navy); margin: 0; line-height: 1.1; }
  .sub { color: #52606d; font-size: 8pt; margin-top: .8mm; }
  .badge { font-weight: bold; color: #fff; padding: 1.6mm 4mm; border-radius: 1mm; font-size: 11pt; background: var(--grey); }
  .badge.BUY { background: var(--green); } .badge.SELL { background: var(--red); } .badge.HOLD { background: var(--grey); } .badge.NOT-RATED { background: #555; }
  h2 { font-family: Cambria, Georgia, serif; font-size: 11.5pt; color: var(--navy); margin: 1.5mm 0 2.5mm; line-height: 1.25; font-weight: bold;
       border-bottom: 1.4pt solid var(--navy); padding-bottom: 1.8mm; }
  .cols { display: grid; grid-template-columns: 1fr 60mm; gap: 5mm; }
  h3 { font-size: 8.6pt; color: var(--navy); margin: 2.6mm 0 1.2mm; text-transform: uppercase; letter-spacing: .4px;
       border-bottom: .6pt solid var(--line); padding-bottom: .8mm; }
  h3:first-child { margin-top: 0; }
  ul { margin: 0; padding-left: 3.6mm; } li { margin-bottom: 1.1mm; } li::marker { color: var(--navy); }
  .side { background: var(--light); padding: 3mm; }
  .rating { background: #fff; border: .6pt solid var(--line); padding: 2mm 2.5mm; margin-bottom: 2.5mm; }
  .rating .big { font-size: 15pt; font-weight: bold; color: var(--navy); }
  table { border-collapse: collapse; width: 100%; }
  td, th { padding: .75mm 1.2mm; text-align: right; white-space: nowrap; }
  td:first-child, th:first-child { text-align: left; }
  .kv td { border-bottom: .5pt solid var(--line); font-size: 7.6pt; padding: .55mm 1mm; } .kv td:first-child { color: #52606d; }
  .kf th { background: var(--navy); color: #fff; font-weight: bold; font-size: 7.8pt; }
  .kf td { border-bottom: .5pt solid var(--line); font-size: 7.8pt; padding: .5mm 1.2mm; }
  .kf td.e, .kf th.e { background: #F4F7FA; } .kf th.e { background: #1d4a6e; }
  .kf tr.sep td { border-top: .9pt solid var(--navy); }
  .cons th { background: var(--light); color: var(--navy); font-size: 7.6pt; border-bottom: .8pt solid var(--navy); }
  .cons td { border-bottom: .5pt solid var(--line); font-size: 7.8pt; }
  .up { color: var(--green); font-weight: bold; } .down { color: var(--red); font-weight: bold; }
  img { width: 100%; display: block; }
  .muted { color: #6b7785; font-size: 7pt; }
  .foot { margin-top: auto; border-top: .8pt solid var(--navy); padding-top: 1.5mm; display: flex; justify-content: space-between; gap: 6mm; }
  .foot .muted { font-size: 6.6pt; line-height: 1.3; }
</style></head>
<body><div class="page">
  <div class="bar"><b>{{ brand }}</b><span>EQUITY RESEARCH · COMPANY NOTE · {{ date }}</span></div>
  <div class="title">
    <div><h1>{{ name }}</h1><div class="sub">{{ ticker }} · {{ sector }}{% if country %} · {{ country }}{% endif %}</div></div>
    <div class="badge {{ rating_css }}">{{ rating }}</div>
  </div>
  <h2>{{ headline }}</h2>
  <div class="cols">
    <div>
      <h3>Investment case</h3>
      <ul>{% for b in thesis %}<li>{{ b }}</li>{% endfor %}</ul>
      {% if cons_rows %}
      <h3>Where we differ from consensus</h3>
      <table class="cons"><tr><th>Estimate</th><th>Ours</th><th>Consensus</th><th>Diff.</th><th>Range</th><th>n</th></tr>
      {% for c in cons_rows %}<tr><td>{{ c.label }}</td><td>{{ c.ours }}</td><td>{{ c.cons }}</td><td class="{{ c.css }}">{{ c.diff }}</td><td>{{ c.range }}</td><td>{{ c.n }}</td></tr>{% endfor %}
      </table>
      <ul style="margin-top:1.6mm">{% for b in consensus %}<li>{{ b }}</li>{% endfor %}</ul>
      {% endif %}
      <h3>Key risks</h3>
      <ul>{% for b in risks %}<li>{{ b }}</li>{% endfor %}</ul>
      {% if catalysts %}<h3>Catalysts</h3><ul>{% for b in catalysts %}<li>{{ b }}</li>{% endfor %}</ul>{% endif %}
    </div>
    <div class="side">
      <div class="rating">
        <div class="muted">12-month target price</div>
        <div class="big">{{ tp }}</div>
        <table class="kv" style="margin-top:1mm">
          <tr><td>Share price</td><td>{{ price }}</td></tr>
          <tr><td>Upside</td><td>{{ upside }}</td></tr>
          <tr><td>Total return incl. dividend</td><td>{{ total_return }}</td></tr>
          <tr><td>DCF fair value today</td><td>{{ fair }}</td></tr>
          <tr><td>Agreement of anchors</td><td>{{ agreement }}</td></tr>
        </table>
      </div>
      <h3>Key data</h3>
      <table class="kv">{% for k, v in key_data %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table>
      {% if chart %}<h3>Share price vs {{ index_name }}</h3><img src="data:image/png;base64,{{ chart }}" alt="Share price chart">{% endif %}
      {% if team %}<div class="muted" style="margin-top:2mm">Analysts: {{ team }}</div>{% endif %}
    </div>
  </div>
  <h3 style="margin-top:3mm">Key figures · multiples at today's share price and enterprise value</h3>
  <table class="kf">
    <tr><th>{{ units }}</th>{% for c in kf_cols %}<th class="{{ 'e' if c.endswith('E') else '' }}">{{ c }}</th>{% endfor %}</tr>
    {% for row in kf_rows %}<tr class="{{ row.css }}"><td>{{ row.label }}</td>{% for v, c in row.cells %}<td class="{{ 'e' if c.endswith('E') else '' }}">{{ v }}</td>{% endfor %}</tr>{% endfor %}
  </table>
  <div class="muted" style="margin-top:1mm">{{ kf_note }}</div>
  <div class="foot">
    <div class="muted">Sources: {{ sources }}. Valuation date {{ valuation_date }}; net debt as at {{ nd_date }}; multiples basis {{ basis }}.
      Rating on expected 12-month total return: BUY ≥ {{ buy }}, SELL ≤ {{ sell }}.</div>
    <div class="muted" style="text-align:right;min-width:52mm">For illustration only – not investment advice.<br>Generated by the Equity Research Engine.</div>
  </div>
</div></body></html>
""")


def _plain(text: str) -> str:
    """Narrative markup (``**bold**``) to HTML; everything else escaped."""
    esc = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)


def _date(v) -> str:
    return pd.Timestamp(v).strftime("%d.%m.%Y") if v else ""


def _chart_b64(result, path: Path) -> str | None:
    """Two-year share price vs the index, rebased to 100, sized for the note's side bar."""
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    rel = result.relative_performance()
    if rel is None or rel.empty:
        return None
    rel = rel[rel.index >= rel.index.max() - pd.DateOffset(years=2)]
    rel = rel / rel.iloc[0] * 100.0
    fig, ax = plt.subplots(figsize=(2.35, 1.35), dpi=220)
    ax.plot(rel.index, rel["index"], color=hx(GREY), linewidth=0.9, label=result.cfg.index_name or result.cfg.index)
    ax.plot(rel.index, rel["stock"], color=hx(NAVY), linewidth=1.2, label=result.cfg.display_short)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.tick_params(labelsize=5.2, length=2, colors=hx(DARK_GREY))
    ax.yaxis.grid(True, color=hx(LIGHT_GREY), linewidth=0.4)
    ax.legend(fontsize=5.2, frameon=False, loc="upper left", handlelength=1.2)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def build_note(result, out_path: str | Path, charts_dir: str | Path | None = None) -> Path:
    from markupsafe import Markup

    r = result
    out_path = Path(out_path)
    charts_dir = Path(charts_dir) if charts_dir else out_path.parent / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    rec, info, n = r.recommendation, r.snapshot.info, r.narrative
    pccy, ccy = r.price_currency, r.currency
    M = lambda items: [Markup(_plain(x)) for x in items]  # noqa: E731

    # ---- consensus rows
    cons_rows = []
    cv = r.consensus
    if cv is not None:
        for e in sorted(cv.estimates, key=lambda e: (e.metric != "EPS", e.year)):
            d = 2 if e.metric == "EPS" else 0
            unit = pccy if e.metric == "EPS" else f"{ccy}m"
            cons_rows.append({"label": f"{e.metric} {e.year}E ({unit})", "ours": fmt_num(e.ours, d), "cons": fmt_num(e.consensus, d),
                              "diff": fmt_pct(e.diff, 1, sign=True), "css": ("up" if (e.diff or 0) >= 0 else "down") if e.diff is not None and abs(e.diff) >= 0.05 else "",
                              "range": f"{fmt_num(e.low, d)}–{fmt_num(e.high, d)}", "n": e.n_analysts or "–"})

    # ---- key data
    shares_out = r.snapshot.shares_outstanding
    ff = info.get("floatShares")
    adv = info.get("averageVolume")
    lo, hi = info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")
    nxt = next((c for c in (cv.catalysts if cv else []) if "results" in c.event.lower()), None)
    L = r.latest
    key_data = [
        ("Ticker", r.cfg.ticker),
        (f"Market cap ({ccy}m)", fmt_num(r.market_cap)),
        (f"Enterprise value ({ccy}m)", fmt_num(r.enterprise_value)),
        (f"Net debt ({ccy}m)", fmt_num(r.net_debt)),
        ("Shares outstanding (m)", fmt_num(r.shares_real, 1)),
        ("Free float", fmt_pct(ff / shares_out, 0) if (ff and shares_out) else "–"),
        (f"Avg. daily turnover ({pccy}m)", fmt_num(adv * r.price / 1e6, 1) if adv else "–"),
        (f"52-week range ({pccy})", f"{fmt_num(lo, 2)}–{fmt_num(hi, 2)}" if (lo and hi) else "–"),
        ("Dividend yield", fmt_pct(rec.dps / r.price, 1) if (rec.dps and r.price) else "–"),
        ("WACC / terminal growth", f"{fmt_pct(r.wacc.wacc, 1)} / {fmt_pct(r.dcf.terminal_growth, 1)}"),
        ("Next results", _date(nxt.date) if nxt else "–"),
    ]

    # ---- key figures
    kf = r.key_figures()
    spec = [("Revenue", "Revenue", lambda v: fmt_num(v), ""), ("Growth", "Growth", lambda v: fmt_pct(v, 1, sign=True), ""),
            ("EBITDA (adj.)" if r.cfg.assumptions.lease_treatment == "operating" else "EBITDA", "EBITDA", lambda v: fmt_num(v), ""),
            ("EBITDA margin", "EBITDA margin", lambda v: fmt_pct(v, 1), ""), ("EBIT (adj.)" if r.cfg.assumptions.lease_treatment == "operating" else "EBIT", "EBIT",
                                                                               lambda v: fmt_num(v), ""),
            (f"EPS ({pccy})", "EPS", lambda v: fmt_num(v, 2), ""), ("EV/EBITDA", "EV/EBITDA", fmt_mult, "sep"), ("P/E", "P/E", fmt_mult, ""),
            ("FCF yield (unlevered)", "FCF yield", lambda v: fmt_pct(v, 1), "")]
    cols = list(kf.columns)
    kf_rows = [{"label": label, "css": css, "cells": [(fn(kf.loc[key, c]) if np.isfinite(kf.loc[key, c]) else "–", c) for c in cols]}
               for label, key, fn, css in spec]
    basis = "pre-IFRS 16 (rent above EBITDA, leases outside net debt)" if r.cfg.assumptions.lease_treatment == "operating" else "reported IFRS 16"
    kf_note = f"Accounts on a {basis} basis. A = reported (EPS: diluted, as reported); E = Equity Research Engine estimates."

    thesis = list(n.get("thesis", []))[:3]
    consensus_b = list(n.get("consensus", []))[:2]
    risks = list(n.get("risks", []))[:3]
    headline = n.get("valuation_subtitle") or n.get("valuation_headline") or ""
    cc = r.crosscheck
    html = TEMPLATE.render(
        brand=r.cfg.brand.name, date=_date(r.valuation_date or r.as_of), name=r.name, ticker=r.cfg.ticker,
        sector=r.cfg.sector_label or info.get("industry") or "", country=r.cfg.footprint or info.get("country") or "",
        rating=rec.rating, rating_css=rec.rating.replace(" ", "-"), headline=headline,
        thesis=M(thesis), consensus=M(consensus_b), risks=M(risks), catalysts=M(n.get("catalysts", [])[:3]),
        cons_rows=cons_rows, tp=f"{pccy} {fmt_num(rec.target_price, 2)}" if rec.rating != "NOT RATED" else "n.a.",
        price=f"{pccy} {fmt_num(r.price, 2)}", upside=fmt_pct(rec.upside, 0, sign=True), total_return=fmt_pct(rec.total_return, 0, sign=True),
        fair=f"{pccy} {fmt_num(rec.fair_value, 2)}", agreement=(cc.agreement.capitalize() if cc is not None else "n/a"),
        key_data=key_data, chart=_chart_b64(r, charts_dir / "note_perf.png"), index_name=r.cfg.index_name or r.cfg.index,
        team=", ".join(m.name for m in r.cfg.team) if r.cfg.team else r.cfg.brand.analyst,
        units=r.units_label, kf_cols=cols, kf_rows=kf_rows, kf_note=kf_note,
        sources=r.cfg.sources_note, valuation_date=_date(r.valuation_date), nd_date=_date(L.net_debt_date) if L is not None else "",
        basis=(L.basis if L is not None else f"FY{r.last_actual_year}"),
        buy=fmt_pct(r.cfg.recommendation.buy_threshold, 0, sign=True), sell=fmt_pct(r.cfg.recommendation.sell_threshold, 0, sign=True),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
