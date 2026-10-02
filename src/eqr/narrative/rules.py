"""Deterministic narrative: every sentence is derived from a number in the analysis.

Text uses ``**bold**`` markup for the lead-in of each bullet; renderers split it
into bold/regular runs. The analyst can override any block from the YAML
``narrative:`` section (same keys).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..create.style import fmt_leverage, fmt_mult, fmt_num, fmt_pct

NARRATIVE_KEYS = [
    "cover_tagline", "company_subtitle", "company_headline", "highlights", "management_note",
    "market_subtitle", "market_headline", "opportunities", "disruption", "threats",
    "financials_subtitle", "financial_commentary", "valuation_subtitle", "valuation_headline", "thesis", "multiples_commentary",
    "market_implied", "scenario_commentary", "risks", "consensus", "catalysts", "multiples_depth",
]


def _multiples_depth(r, name: str, pccy: str) -> list[str]:
    """Forward multiples, the regression and quality metrics against the peer group – pure arithmetic, locked for Claude."""
    c, stats, reg = r.comps.company, r.comps.stats, r.comps.regression
    if r.comps.table.empty:
        return []
    med = stats.loc["All|median"] if "All|median" in stats.index else None

    def m(key):
        v = med[key] if (med is not None and key in med.index) else None
        return float(v) if _ok(v) else None

    out = []
    if _ok(c.get("fwd_pe")) or _ok(c.get("ev_sales_ntm")):
        parts = []
        if _ok(c.get("fwd_pe")):
            parts.append(f"{fmt_mult(c['fwd_pe'])} P/E" + (f" (peers {fmt_mult(m('fwd_pe'))})" if m("fwd_pe") else ""))
        if _ok(c.get("ev_sales_ntm")):
            parts.append(f"{fmt_mult(c['ev_sales_ntm'])} EV/Sales" + (f" (peers {fmt_mult(m('ev_sales_ntm'))})" if m("ev_sales_ntm") else ""))
        if _ok(c.get("ev_ebitda_ntm")):
            parts.append(f"{fmt_mult(c['ev_ebitda_ntm'])} EV/EBITDA at the LTM margin" + (f" (peers {fmt_mult(m('ev_ebitda_ntm'))})" if m("ev_ebitda_ntm") else ""))
        peg = f"; PEG {fmt_num(c['peg'], 2)} vs {fmt_num(m('peg'), 2)}" if (_ok(c.get("peg")) and m("peg")) else ""
        out.append(f"**On next-twelve-month consensus** {name} trades at " + ", ".join(parts) + peg)
    if reg is not None:
        strength = ("weak: multiples in this group are set by something the regression does not see – leverage, geography, liquidity or the cycle"
                    if reg.r2 < 0.15 else ("moderate" if reg.r2 < 0.5 else "strong"))
        out.append(f"**Growth and margin explain {fmt_pct(reg.r2, 0)} of the dispersion in peer EV/EBITDA** ({reg.n} peers): fundamentals justify "
                   f"{fmt_mult(reg.fitted_target)} against the {fmt_mult(reg.peer_median)} median ({fmt_pct(reg.explained, 0, sign=True)}); "
                   f"the actual {fmt_mult(reg.actual_target)} leaves {fmt_pct(reg.unexplained, 0, sign=True)} unexplained. Evidence {strength}")
        if reg.r2 >= 0.15 and reg.implied_value_per_share:
            out.append(f"**Regression-implied value {pccy} {fmt_num(reg.implied_value_per_share, 2)}** per share "
                       f"({pccy} {fmt_num(reg.low, 0)}–{fmt_num(reg.high, 0)} within one residual standard deviation)")
    q = []
    if _ok(c.get("fcf_yield")):
        q.append(f"{fmt_pct(c['fcf_yield'])} levered FCF yield" + (f" vs {fmt_pct(m('fcf_yield'))} for peers" if m("fcf_yield") is not None else ""))
    if _ok(c.get("div_yield")):
        q.append(f"{fmt_pct(c['div_yield'])} dividend yield" + (f" vs {fmt_pct(m('div_yield'))}" if m("div_yield") is not None else ""))
    if q:
        out.append("**Cash and payout:** " + "; ".join(q))
    if _ok(c.get("eps_growth")) and m("eps_growth") is not None:
        out.append(f"**Consensus EPS growth FY1:** {fmt_pct(c['eps_growth'], 0, sign=True)} for {name} vs {fmt_pct(m('eps_growth'), 0, sign=True)} "
                   f"for the peer median – the growth the forward multiple is buying")
    return out[:5]


def _consensus_bullets(r, name: str, pccy: str, ccy: str) -> list[str]:
    """Variant perception, estimate momentum and the tension between the two, from ``r.consensus``."""
    cv = getattr(r, "consensus", None)
    if cv is None or not cv.estimates:
        return [f"**Consensus:** {cv.note}"] if (cv is not None and cv.note) else []
    out = []
    eps = [e for e in cv.estimates if e.metric == "EPS" and e.diff is not None]
    if eps:
        e0 = eps[0]
        side = "above" if e0.diff >= 0 else "below"
        rng = " – outside the range of estimates" if e0.outside_range else ""
        later = "; " + ", ".join(f"{e.year}E {fmt_pct(e.diff, 0, sign=True)}" for e in eps[1:]) if len(eps) > 1 else ""
        explicit = r.forecast[r.forecast.index != "TV"]
        m0 = float(explicit["ebitda_margin"].iloc[0])
        out.append(f"**EPS {e0.year}E {pccy} {fmt_num(e0.ours, 2)} vs consensus {pccy} {fmt_num(e0.consensus, 2)} ({fmt_pct(e0.diff, 0, sign=True)}):** "
                   f"we are {side} the {e0.n_analysts or ''} analysts{rng}{later}; our view rests on a {fmt_pct(m0)} {e0.year}E EBITDA margin "
                   f"and a {fmt_pct(r.drivers.tax_rate, 0)} tax rate")
    rev = [e for e in cv.estimates if e.metric == "Revenue" and e.diff is not None]
    if rev:
        e0 = rev[0]
        anchored = "consensus" in (r.drivers.growth_anchor or "")
        out.append(f"**Revenue {e0.year}E {ccy} {fmt_num(e0.ours)}m vs consensus {ccy} {fmt_num(e0.consensus)}m ({fmt_pct(e0.diff, 1, sign=True)})"
                   + (":** in line by construction – our growth is anchored on consensus, so the differentiated view sits in margins"
                      if anchored and abs(e0.diff) < 0.02 else ":** our growth view differs from the street"))
    revs = [x for x in cv.revisions if x.change_90d is not None]
    if revs:
        parts = ", ".join(f"{x.year}E {fmt_pct(x.change_90d, 1, sign=True)}" for x in revs)
        ups = sum(x.up_30d or 0 for x in cv.revisions)
        downs = sum(x.down_30d or 0 for x in cv.revisions)
        out.append(f"**Estimate momentum {cv.momentum}:** consensus EPS over the last 90 days {parts}; {ups} upward and {downs} downward "
                   f"revisions in the last 30 days")
    rating = r.recommendation.rating
    if (rating == "BUY" and cv.momentum == "negative") or (rating == "SELL" and cv.momentum == "positive"):
        direction = "falling" if cv.momentum == "negative" else "rising"
        out.append(f"**Tension:** our {rating} runs against {direction} consensus estimates – shares rarely re-rate before revisions turn, "
                   f"so the timing of the case depends on the next reports")
    elif eps and ((rating == "BUY" and eps[0].diff < -0.05) or (rating == "SELL" and eps[0].diff > 0.05)):
        out.append(f"**Valuation, not earnings, carries the {rating}:** our {eps[0].year}E EPS is {'below' if eps[0].diff < 0 else 'above'} "
                   f"consensus, so the case rests on the multiple the market pays, not on an earnings surprise")
    return out[:4]


def _catalyst_bullets(r, pccy: str) -> list[str]:
    cv = getattr(r, "consensus", None)
    if cv is None:
        return []
    out = []
    for k in cv.catalysts[:3]:
        d = pd.Timestamp(k.date).strftime("%d.%m.%Y")
        out.append(f"**{d} – {k.event}**" + (f": {k.detail}" if k.detail else ""))
    return out


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def _cagr(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 2 or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return None
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / (len(s) - 1)) - 1)


def _median(stats: pd.DataFrame, key: str) -> float | None:
    if stats is None or stats.empty or "All|median" not in stats.index or key not in stats.columns:
        return None
    v = stats.loc["All|median", key]
    return float(v) if _ok(v) else None


def _oil_risk(oil, pccy: str) -> str:
    """One measured sentence about oil exposure — including when the measurement is that there is none."""
    spans_zero = oil.total_lo <= 0 <= oil.total_hi
    partial_sig = oil.partial_p < 0.05
    where = f"{oil.weeks} weeks to {oil.sample.get('end', '')}"

    if partial_sig and oil.beta_partial < 0:
        cost = (f"a higher oil price has been a cost: holding the index fixed, the share has moved "
                f"{oil.beta_partial:+.2f}% per 1% move in Brent")
    elif partial_sig and oil.beta_partial > 0:
        cost = f"that is oil risk beyond the index's own ({oil.beta_partial:+.2f}% per 1%, holding the index fixed)"
    else:
        cost = "the exposure it has is the index's own, not the company's"

    if spans_zero:
        return (f"**Oil price:** no measurable direct exposure — the share has moved {oil.beta_total:+.2f}% per 1% move in "
                f"Brent over the {oil.window}, an interval of {oil.total_lo:+.2f} to {oil.total_hi:+.2f} that spans zero "
                f"({where}); {cost}")

    down = oil.downside
    if down is None:
        return (f"**Oil price:** the share has moved {oil.beta_total:+.2f}% per 1% move in Brent over the {oil.window} "
                f"(interval {oil.total_lo:+.2f} to {oil.total_hi:+.2f}, {where}); {cost}")

    direction = "fall" if down.expected < 0 else "rise"
    band = sorted((abs(down.lo), abs(down.hi)))
    hit = ">99" if down.p_same_sign > 0.995 else format(down.p_same_sign * 100, ".0f")
    moved = f"{abs(down.expected):.1%}"
    article = "an" if moved[0] in "8" else "a"          # "an 8.4% fall", "a 10.3% fall"
    return (f"**Oil price:** a {abs(down.brent):.0%} fall in Brent has come with {article} {moved} {direction} in "
            f"the share ({band[0]:.1%} to {band[1]:.1%} interval, {where}); {cost}. Oil explains "
            f"{oil.variance_explained:.0%} of weekly variance and the move goes that way {hit}% of the time")


def build_rule_narrative(result) -> dict[str, Any]:
    r = result
    cfg = r.cfg
    h, f = r.hist, r.forecast
    ccy = r.currency
    pccy = r.price_currency  # listing currency for per-share values
    name = cfg.display_short
    rec = r.recommendation
    first_year, last_year = int(h.index[0]), int(h.index[-1])
    last = h.iloc[-1]
    rev_cagr = _cagr(h["revenue"])
    m_first, m_last = float(h["ebitda_margin"].iloc[0]), float(h["ebitda_margin"].iloc[-1])
    ebit_m = float(last["ebit_margin"])
    nd_ebitda = float(last["nd_to_ebitda"]) if _ok(last["nd_to_ebitda"]) else None
    fcf_conv = float(last["fcf_conversion"]) if _ok(last["fcf_conversion"]) else None
    roic = float(last["roic"]) if _ok(last["roic"]) else None
    explicit = f[f.index != "TV"]
    f_first, f_last = explicit.iloc[0], explicit.iloc[-1]
    fy1 = int(explicit.index[0])
    fyN = int(explicit.index[-1])
    med_ev_ebitda = _median(r.comps.stats, "ev_ebitda")
    med_pe = _median(r.comps.stats, "pe")
    own_ev_ebitda = r.comps.company.get("ev_ebitda")
    own_pe = r.comps.company.get("pe")
    upside_word = "upside" if rec.upside >= 0 else "downside"
    rating_phrase = {"BUY": "We recommend a BUY", "SELL": "We recommend a SELL", "HOLD": "We recommend a HOLD",
                     "NOT RATED": "We do not rate the stock: the DCF equity value is not positive"}[rec.rating]
    info = r.snapshot.info
    consensus = r.snapshot.price_targets or {}
    n_analysts = info.get("numberOfAnalystOpinions")
    basis = "pre-IFRS 16" if cfg.assumptions.lease_treatment == "operating" else "reported (IFRS 16)"

    def disc(own, med):
        if not (_ok(own) and _ok(med)) or not med:
            return None
        return own / med - 1

    ev_disc = disc(own_ev_ebitda, med_ev_ebitda)
    pe_disc = disc(own_pe, med_pe)

    highlights = []
    if rev_cagr is not None:
        highlights.append(f"**Consistent growth:** revenue compounded at {fmt_pct(rev_cagr)} p.a. over {first_year}–{last_year}, "
                          f"reaching {ccy} {fmt_num(last['revenue'])}m")
    highlights.append(f"**Margin profile:** {basis} EBITDA margin of {fmt_pct(m_last)} in {last_year}A "
                      f"({'up' if m_last >= m_first else 'down'} from {fmt_pct(m_first)} in {first_year}A), EBIT margin {fmt_pct(ebit_m)}")
    if fcf_conv is not None:
        lead = "Cash generative" if fcf_conv >= 0.4 else ("Cash conversion" if fcf_conv >= 0.15 else "Weak cash conversion")
        avg_conv = h["fcf_conversion"].replace([np.inf, -np.inf], np.nan).dropna().mean()
        extra = f" (average {fmt_pct(avg_conv, 0)} over {first_year}–{last_year})" if fcf_conv < 0.4 and _ok(avg_conv) else ""
        highlights.append(f"**{lead}:** unlevered FCF of {ccy} {fmt_num(last['ufcf'])}m in {last_year}A, "
                          f"{fmt_pct(fcf_conv, 0)} of EBITDA{extra}, ROIC {fmt_pct(roic, 0) if roic is not None else 'n.a.'}")
    if nd_ebitda is not None and r.net_debt < 0:
        highlights.append(f"**Balance sheet:** net cash of {ccy} {fmt_num(-r.net_debt)}m, no financial leverage")
    elif nd_ebitda is not None:
        lev = "conservative" if nd_ebitda < 1.5 else ("moderate" if nd_ebitda < 3 else "elevated")
        highlights.append(f"**Balance sheet:** net debt of {ccy} {fmt_num(r.net_debt)}m equals {fmt_mult(nd_ebitda)} EBITDA, a {lev} leverage level")

    nc = getattr(r.drivers, "nowcast", None)
    if nc:
        year1 = (f"**{fy1}E is built on the {nc['quarters_reported']} reported quarter{'s' if nc['quarters_reported'] > 1 else ''}:** revenue "
                 f"{fmt_pct(nc['growth_ytd'], sign=True)} year-to-date at a {fmt_pct(nc['margin_ytd'])} EBITDA margin ({fmt_pct(nc['margin_prior_ytd'])} a year "
                 f"earlier); the rest of the year at {fmt_pct(nc['growth_remaining'], sign=True)} growth on last year's seasonal margins gives {ccy} "
                 f"{fmt_num(f_first['revenue'])}m ({fmt_pct(f_first['growth'], sign=True)}) and a {fmt_pct(f_first['ebitda_margin'])} margin; growth then "
                 f"follows {r.drivers.growth_anchor} and fades to {fmt_pct(r.drivers.terminal_growth)} by {fyN}E")
    else:
        year1 = (f"**We forecast {fy1}E revenue of {ccy} {fmt_num(f_first['revenue'])}m ({fmt_pct(f_first['growth'], sign=True)})**, anchored on "
                 f"{r.drivers.growth_anchor}, fading to {fmt_pct(r.drivers.terminal_growth)} terminal growth by {fyN}E")
    commentary = [
        f"**{name} grew revenue by {fmt_pct(last['growth'])} in {last_year}A** to {ccy} {fmt_num(last['revenue'])}m, "
        f"with {basis} EBITDA of {ccy} {fmt_num(last['ebitda'])}m ({fmt_pct(m_last)} margin)",
        year1,
        f"**EBITDA margin path:** {fmt_pct(f_first['ebitda_margin'])} in {fy1}E to {fmt_pct(f_last['ebitda_margin'])} in {fyN}E; "
        f"D&A {fmt_pct(r.drivers.da_pct)} and capex {fmt_pct(r.drivers.capex_at(0))}"
        + (f" normalising to {fmt_pct(r.drivers.capex_at(99))}" if abs(r.drivers.capex_at(99) - r.drivers.capex_at(0)) > 0.002 else "")
        + f" of revenue; tax rate {fmt_pct(r.drivers.tax_rate, 0)}",
        f"**Unlevered FCF** rises from {ccy} {fmt_num(f_first['ufcf'])}m to {ccy} {fmt_num(f_last['ufcf'])}m over the forecast period "
        f"({fmt_pct(f_last['ufcf_margin'])} FCF margin in {fyN}E)",
    ]
    if _ok(own_ev_ebitda) and med_ev_ebitda:
        commentary.append(f"**Valuation vs peers:** {name} trades at {fmt_mult(own_ev_ebitda)} LTM EV/EBITDA versus a peer median of "
                          f"{fmt_mult(med_ev_ebitda)} ({fmt_pct(ev_disc, 0, sign=True)}) and {fmt_mult(own_pe)} P/E versus {fmt_mult(med_pe)}")
    if consensus.get("mean") and n_analysts:
        commentary.append(f"**Street view:** consensus target of {pccy} {fmt_num(consensus['mean'], 2)} across {n_analysts} analysts "
                          f"({fmt_pct(consensus['mean'] / r.price - 1, 0, sign=True)} vs current price)")

    thesis = [
        f"**DCF value of {pccy} {fmt_num(rec.dcf_value, 2)} per share** (WACC {fmt_pct(r.wacc.wacc)}, terminal growth {fmt_pct(r.wacc and r.drivers.terminal_growth)}); "
        f"terminal value is {fmt_pct(r.dcf.tv_share_of_ev, 0)} of EV, implying {fmt_mult(r.dcf.implied_exit_ev_ebitda)} exit EV/EBITDA",
    ]
    if rec.multiples_value is not None:
        thesis.append(f"**Peer multiples imply {pccy} {fmt_num(rec.multiples_value, 2)}** per share (median of EV/EBITDA, EV/EBIT and P/E-based values)")
    sc = {s.name.lower(): s for s in (r.scenarios or [])}
    if {"bear", "bull"} <= set(sc) and r.scenario_weighted_value is not None:
        thesis.append(f"**Scenarios:** bear {pccy} {fmt_num(sc['bear'].value_per_share, 0)} / base {pccy} {fmt_num(rec.dcf_value, 0)} / bull "
                      f"{pccy} {fmt_num(sc['bull'].value_per_share, 0)}; probability-weighted {pccy} {fmt_num(r.scenario_weighted_value, 2)}")
    else:
        thesis.append(f"**Operating momentum:** {fmt_pct(f_first['growth'])} revenue growth and {fmt_pct(f_first['ebitda_margin'])} EBITDA margin expected in {fy1}E")
    if rec.horizon_months:
        vd = getattr(r, "valuation_date", None)
        vd_txt = f" (valued at {vd:%d.%m.%Y})" if vd else ""
        thesis.append(f"**12-month target price {pccy} {fmt_num(rec.target_price, 2)}:** fair value {pccy} {fmt_num(rec.fair_value, 2)}{vd_txt} rolled forward at the "
                      f"{fmt_pct(rec.cost_of_equity)} cost of equity less {pccy} {fmt_num(rec.dps, 2)} dividend; expected total return "
                      f"{fmt_pct(rec.total_return, 0, sign=True)}, rating {rec.rating}")
    else:
        thesis.append(f"**Target price {pccy} {fmt_num(rec.target_price, 2)}** ({fmt_pct(rec.upside, 0, sign=True)} {upside_word}) based on {rec.method}; rating {rec.rating}")

    # what the current share price implies (reverse DCF)
    market_implied = []
    rv = r.reverse_dcf
    if rv is not None:
        if rv.implied_wacc is not None:
            gap = rv.implied_wacc - rv.base_wacc
            view = "in line with" if abs(gap) < 0.005 else ("above" if gap > 0 else "below")
            market_implied.append(f"**Market-implied WACC {fmt_pct(rv.implied_wacc)}**, {view} our {fmt_pct(rv.base_wacc)}: "
                                  f"the price discounts our cash flows at {fmt_pct(abs(gap) * 100, 0).replace('%', 'bp')} "
                                  f"{'more' if gap > 0 else 'less'} than we do")
        if rv.implied_final_margin is not None:
            market_implied.append(f"**Market-implied margin:** at our WACC the price is consistent with a {fyN}E EBITDA margin of "
                                  f"{fmt_pct(rv.implied_final_margin)} versus {fmt_pct(rv.base_final_margin)} in our base case")
        elif rv.implied_terminal_growth is not None:
            market_implied.append(f"**Market-implied terminal growth {fmt_pct(rv.implied_terminal_growth)}** versus {fmt_pct(rv.base_terminal_growth)} in our base case")
    cc = getattr(r, "crosscheck", None)
    if cc is not None and cc.agreement in {"low", "medium"}:
        market_implied.append(f"**Cross-check – {cc.agreement} agreement:** {cc.message}")
    scenario_commentary = [
        f"**{s.name} ({fmt_pct(s.probability, 0)}):** {s.note or 'base-case drivers'}; revenue CAGR {fmt_pct(s.revenue_cagr)}, "
        f"{fyN}E margin {fmt_pct(s.final_margin)}, WACC {fmt_pct(s.wacc)} gives {pccy} {fmt_num(s.value_per_share, 2)} "
        f"({fmt_pct(s.upside, 0, sign=True)} vs price)" for s in (r.scenarios or [])
    ]

    multiples_commentary = []
    if ev_disc is not None:
        word = "discount" if ev_disc < 0 else "premium"
        multiples_commentary.append(f"**{'Trading at a ' + word}:** {fmt_mult(own_ev_ebitda)} EV/EBITDA vs {fmt_mult(med_ev_ebitda)} peer median "
                                    f"({fmt_pct(abs(ev_disc), 0)} {word})")
    if pe_disc is not None:
        fwd_own, fwd_med = r.comps.company.get("fwd_pe"), _median(r.comps.stats, "fwd_pe")
        fwd_txt = f"; {fmt_mult(fwd_own)} vs {fmt_mult(fwd_med)} on next-twelve-month consensus" if (_ok(fwd_own) and fwd_med) else ""
        multiples_commentary.append(f"**Earnings multiple:** {fmt_mult(own_pe)} trailing P/E vs {fmt_mult(med_pe)} for peers ({fmt_pct(pe_disc, 0, sign=True)}){fwd_txt}")
    mh = getattr(r, "multiple_history", None)
    if mh is not None and "ev_ebitda" in mh.stats:
        st = mh.stats["ev_ebitda"]
        rel = "above" if st["current"] > st["median"] else "below"
        multiples_commentary.append(f"**Versus own history:** {fmt_mult(st['current'])} trailing EV/EBITDA is {rel} the {st['years']:.1f}-year median of "
                                    f"{fmt_mult(st['median'])} ({fmt_pct(st['percentile'], 0)} of weeks were cheaper)")
    for key in ("ev_ebitda", "pe"):
        iv = r.comps.implied.get(key)
        if iv is not None:
            multiples_commentary.append(f"**{iv.label}-implied value:** {pccy} {fmt_num(iv.per_share, 2)} at the peer median of {fmt_mult(iv.multiple)} "
                                        f"(range {fmt_num(iv.low, 0)}–{fmt_num(iv.high, 0)} across the 25th–75th percentile)")
    if not r.comps.table.empty:
        g_med = _median(r.comps.stats, "revenue_growth")
        m_med = _median(r.comps.stats, "ebitda_margin")
        if g_med is not None and m_med is not None:
            multiples_commentary.append(f"**Operating comparison:** peers grow {fmt_pct(g_med)} with {fmt_pct(m_med)} EBITDA margins, "
                                        f"vs {fmt_pct(last['growth'])} and {fmt_pct(m_last)} for {name}")
    else:
        multiples_commentary.append(f"**No peer group configured.** Add tickers under peers: in configs/{cfg.ticker}.yaml to enable "
                                    f"trading comparables and the multiple-implied valuation")
        if consensus.get("mean"):
            multiples_commentary.append(f"**Consensus cross-check:** the street's mean target of {pccy} {fmt_num(consensus['mean'], 2)} "
                                        f"({fmt_pct(consensus['mean'] / r.price - 1, 0, sign=True)}) versus our {pccy} {fmt_num(rec.target_price, 2)}")

    risks = []
    if nd_ebitda is not None and nd_ebitda > 2:
        risks.append(f"**Leverage:** net debt of {fmt_mult(nd_ebitda)} EBITDA limits flexibility if margins compress")
    tornado = [v for v in (getattr(r, "value_drivers", None) or []) if _ok(v.value_down) and _ok(v.value_up)]
    if len(tornado) >= 2:
        t0, t1 = tornado[0], tornado[1]

        def short(driver: str) -> str:  # "EBITDA margin (all years)" -> "EBITDA margin", "Revenue growth" -> "revenue growth"
            s = driver.split(" (")[0].split(",")[0]
            return s[0].lower() + s[1:] if len(s) > 1 and s[1].islower() else s

        risks.append(f"**Value drivers:** {short(t0.driver)} {t0.shock} moves fair value to {pccy} {fmt_num(min(t0.value_down, t0.value_up), 1)}–"
                     f"{fmt_num(max(t0.value_down, t0.value_up), 1)}, {short(t1.driver)} {t1.shock} to {pccy} "
                     f"{fmt_num(min(t1.value_down, t1.value_up), 1)}–{fmt_num(max(t1.value_down, t1.value_up), 1)} (base {pccy} {fmt_num(t0.base, 2)})")
    else:
        risks.append(f"**Valuation sensitivity:** a 50bp higher WACC lowers the DCF value to {pccy} "
                     f"{fmt_num(_sens(r, +1, 0), 2)}; 25bp lower terminal growth to {pccy} {fmt_num(_sens(r, 0, -1), 2)}")
    risks.append(f"**Execution:** the case assumes {fmt_pct(f_first['growth'])} growth in {fy1}E and margins of {fmt_pct(f_last['ebitda_margin'])} by {fyN}E; "
                 f"a return to the {first_year}–{last_year} average margin of {fmt_pct(h['ebitda_margin'].mean())} would cut fair value")
    oil = getattr(r, "oil", None)
    if oil is not None:
        risks.insert(0, _oil_risk(oil, pccy))
    risks.append("**Macro:** consumer spending, interest rates and FX can move revenue and the discount rate simultaneously")

    fwd = r.forward_multiples
    fwd_txt = ""
    if fwd is not None and "EV/EBITDA" in fwd.index and fwd.shape[1] > 1:
        fwd_txt = f"; {fmt_mult(fwd.iloc[:, 1]['EV/EBITDA'])} {fwd.columns[1]} EV/EBITDA"

    narrative = {
        "cover_tagline": cfg.tagline or f"{rec.rating}: {fmt_pct(rec.upside, 0, sign=True)} to our {pccy} {fmt_num(rec.target_price, 2)} target",
        "company_subtitle": f"{r.name} – {cfg.sector_label or info.get('industry') or 'company'} in {cfg.footprint or info.get('country') or ''}".strip(" –"),
        "company_headline": f"{fmt_pct(rev_cagr) if rev_cagr is not None else 'Steady'} revenue CAGR, {fmt_pct(m_last)} EBITDA margin and "
                            f"{('a net cash balance sheet' if r.net_debt < 0 else fmt_leverage(nd_ebitda) + ' net debt/EBITDA') if nd_ebitda is not None else 'n.a. leverage'} — market cap {ccy} {fmt_num(r.market_cap / 1000, 1)}bn",
        "highlights": highlights[:4],
        "management_note": "",
        "market_subtitle": cfg.narrative.get("market_subtitle") or f"{name} versus its peer group: growth, profitability and the drivers behind the case",
        "market_headline": cfg.narrative.get("market_headline") or "Peer benchmarking on a consistent basis",
        "opportunities": cfg.market.opportunities or [
            f"**Growth runway:** consensus expects {fmt_pct(f_first['growth'])} revenue growth in {fy1}E",
            f"**Operating leverage:** every 1pp of EBITDA margin is worth roughly {ccy} {fmt_num(f_last['revenue'] * 0.01)}m of EBITDA in {fyN}E",
        ],
        "disruption": cfg.market.disruption or ["**Business model shifts** in the sector may change the competitive set"],
        "threats": cfg.market.threats or risks[-1:],
        "financials_subtitle": f"{name} financials, {basis} basis ({r.units_label})",
        "financial_commentary": commentary[:6],
        "valuation_subtitle": (f"{rating_phrase}. Our {'12-month ' if rec.horizon_months else ''}target price of {pccy} {fmt_num(rec.target_price, 2)} "
                               f"implies {fmt_pct(rec.upside, 0, sign=True)} {upside_word}"
                               + (f" and a {fmt_pct(rec.total_return, 0, sign=True)} total return including dividend" if rec.dps else "") + f"{fwd_txt}."),
        "valuation_headline": (f"DCF fair value {pccy} {fmt_num(rec.dcf_value, 2)}, peer multiples "
                               f"{pccy + ' ' + fmt_num(rec.multiples_value, 2) if rec.multiples_value else 'n.a.'}"
                               + (f", scenario-weighted {pccy} {fmt_num(r.scenario_weighted_value, 2)}" if r.scenario_weighted_value is not None else "")
                               + f" versus a share price of {pccy} {fmt_num(r.price, 2)} — {rec.rating}"),
        "market_implied": market_implied[:3],
        "scenario_commentary": scenario_commentary[:4],
        "thesis": thesis[:4],
        "multiples_commentary": multiples_commentary[:4],
        "risks": risks[:4],
        "consensus": _consensus_bullets(r, name, pccy, ccy),
        "catalysts": _catalyst_bullets(r, pccy),
        "multiples_depth": _multiples_depth(r, name, pccy),
    }
    # analyst overrides from YAML (same keys)
    for key, value in (cfg.narrative or {}).items():
        if key in narrative and value:
            narrative[key] = value
    return narrative


def _sens(r, d_wacc: int, d_growth: int) -> float | None:
    s = r.dcf.sensitivity
    if s is None:
        return None
    k = len(s) // 2
    try:
        v = s.iloc[k + d_growth, k + d_wacc]
    except IndexError:
        return None
    return float(v) if _ok(v) else None
