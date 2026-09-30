"""Peer multiples (trading comparables) and multiple-implied valuation.

Every multiple is built the same way for the target and each peer:

* EV = market cap + net debt from the latest balance sheet (same lease basis as the model) + minorities,
  **in the reporting currency**: Yahoo quotes the market cap in the listing currency, so it is converted
  first (Bakkafrost trades in NOK and reports in DKK; a NOK market cap over DKK EBITDA is wrong by a third).
* LTM revenue, EBITDA and EBIT (see ``ltm.py``); trailing twelve-month EPS for P/E.
* Forward: consensus revenue and EPS calendarised to the next twelve months (see ``multiples.py``),
  giving NTM EV/Sales, NTM P/E, P/E on FY0 and FY1, consensus EPS growth and PEG; NTM EV/EBITDA is a
  *proxy* – NTM revenue at the LTM margin – because Yahoo carries no EBITDA consensus.
* Quality: levered FCF yield after lease payments, and the dividend yield.

Statistics (mean, median, quartiles) are computed per group and for the full set. Implied values apply
the pooled median to the target's own metric and bridge to equity value per share; the 25th–75th
percentile range feeds the football field. The regression-implied value is in ``CompsResult.regression``.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import CompanyConfig, PeerConfig
from ..retrieve import Snapshot
from .historicals import last_fy_metrics
from .ltm import latest_figures
from .multiples import ForwardEstimates, RegressionResult, consensus_forward, multiples_regression

MULTIPLES = ["ev_sales", "ev_ebitda", "ev_ebit", "pe", "fwd_pe", "ev_sales_ntm", "ev_ebitda_ntm", "pe_fy0", "pe_fy1", "peg", "fcf_yield", "div_yield"]
MULTIPLE_LABELS = {"ev_sales": "EV/Sales", "ev_ebitda": "EV/EBITDA", "ev_ebit": "EV/EBIT", "pe": "P/E", "fwd_pe": "P/E (NTM)",
                   "ev_sales_ntm": "EV/Sales (NTM)", "ev_ebitda_ntm": "EV/EBITDA (NTM, at LTM margin)", "pe_fy0": "P/E (FY0)", "pe_fy1": "P/E (FY1)",
                   "peg": "PEG", "fcf_yield": "FCF yield", "div_yield": "Dividend yield"}
STAT_KEYS = MULTIPLES + ["revenue_growth", "ebitda_margin", "ebit_margin", "growth_fwd", "eps_growth"]


@dataclass
class ImpliedValue:
    multiple_key: str
    label: str
    multiple: float
    per_share: float
    low_multiple: float
    high_multiple: float
    low: float
    high: float
    basis: str


@dataclass
class CompsResult:
    table: pd.DataFrame
    stats: pd.DataFrame
    company: dict[str, float | None]
    implied: dict[str, ImpliedValue] = field(default_factory=dict)
    company_currency: str = "USD"
    regression: RegressionResult | None = None

    def as_dict(self) -> dict:
        tbl = self.table.replace([np.inf, -np.inf], np.nan)
        return {
            "table": tbl.astype(object).where(tbl.notna(), None).to_dict(orient="records"),
            "stats": {str(k): {str(c): (None if pd.isna(v) else float(v)) for c, v in row.items()} for k, row in self.stats.iterrows()},
            "company": {k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else v) for k, v in self.company.items()},
            "implied": {k: vars(v) for k, v in self.implied.items()},
            "regression": self.regression.as_dict() if self.regression is not None else None,
        }


def _mult(numerator: float | None, denominator: float | None, cap: float = 60.0) -> float | None:
    if not numerator or not denominator or denominator <= 0:
        return None
    v = numerator / denominator
    return float(v) if 0 < v < cap else None  # outside the band = not meaningful


def _pos(v, cap: float = 200.0) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) and 0 < f < cap else None


def _yield(numerator: float | None, denominator: float | None, cap: float = 0.25) -> float | None:
    """A yield in (-cap, cap); wider values are data errors (Grieg's 145% 'dividend yield' on Yahoo)."""
    if numerator is None or not denominator or denominator <= 0:
        return None
    v = numerator / denominator
    return float(v) if -cap < v < cap else None


def forward_multiples(fwd: ForwardEstimates | None, *, price_listing: float | None, ev: float | None, mcap: float | None,
                      ltm_margin: float | None, divisor: float = 1.0) -> dict[str, float | None]:
    """NTM and fiscal-year multiples from calendarised consensus (EV and revenue in the reporting currency, EPS and price in the listing currency)."""
    out = {k: None for k in ("ev_sales_ntm", "ev_ebitda_ntm", "fwd_pe", "pe_fy0", "pe_fy1", "peg", "growth_fwd", "eps_growth", "eps_ntm")}
    if fwd is None:
        return out
    rev_ntm = fwd.revenue_ntm / divisor if fwd.revenue_ntm else None
    out["ev_sales_ntm"] = _mult(ev, rev_ntm, cap=30.0)
    if rev_ntm and ltm_margin and ltm_margin > 0:
        out["ev_ebitda_ntm"] = _mult(ev, rev_ntm * ltm_margin)
    out["eps_ntm"] = fwd.eps_ntm
    out["fwd_pe"] = _mult(price_listing, fwd.eps_ntm, cap=80.0)
    out["pe_fy0"] = _mult(price_listing, fwd.eps_fy0, cap=80.0)
    out["pe_fy1"] = _mult(price_listing, fwd.eps_fy1, cap=80.0)
    out["growth_fwd"] = fwd.revenue_growth_fy1
    out["eps_growth"] = fwd.eps_growth_fy1
    if out["fwd_pe"] and fwd.eps_growth_fy1 and fwd.eps_growth_fy1 > 0.02:
        out["peg"] = _mult(out["fwd_pe"], fwd.eps_growth_fy1 * 100, cap=10.0)
    return out


def _peer_row(peer: PeerConfig, snap: Snapshot, treatment: str, lease_rate: float, fx_to_target: float, divisor: float,
              quarterly_balance: pd.DataFrame | None = None, fx_listing_to_reporting: float = 1.0,
              valuation_date: dt.date | None = None) -> dict:
    m = last_fy_metrics(snap, treatment=treatment, lease_rate=lease_rate)
    info = snap.info
    price_listing = snap.price
    if price_listing is not None and snap.price_currency == "GBp":
        price_listing /= 100.0
    mcap_listing = snap.market_cap
    mcap = mcap_listing * fx_listing_to_reporting if mcap_listing else None  # reporting currency, like the statements
    latest = latest_figures(m, m["fy_end"], snap.quarterly_income, quarterly_balance, treatment=treatment) if (m and m.get("fy_end") is not None) else None
    nd = latest.net_debt if latest is not None and latest.net_debt is not None else (m.get("net_debt") or 0.0)
    mi = latest.minority if latest is not None and latest.minority is not None else (m.get("minority") or 0.0)
    ev = (mcap + nd + mi) if (mcap and m) else None
    ev_rep = (mcap + (m.get("net_debt_incl_leases") or 0.0)) if (mcap and m) else None
    rev = latest.revenue if latest is not None else m.get("revenue")
    ebitda = latest.ebitda if latest is not None else m.get("ebitda")
    ebit = latest.ebit if latest is not None else m.get("ebit")
    debt = m.get("debt")
    margin = (ebitda / rev) if (ebitda is not None and rev) else m.get("ebitda_margin")
    fwd = consensus_forward(snap.revenue_estimate, snap.earnings_estimate, m.get("fy_end"), valuation_date, m.get("revenue"),
                            fx_listing_to_reporting=fx_listing_to_reporting) if (valuation_date is not None and m) else None
    f = forward_multiples(fwd, price_listing=price_listing, ev=ev, mcap=mcap, ltm_margin=margin)
    fcf = None
    if m.get("ocf") is not None and m.get("capex") is not None:
        fcf = m["ocf"] + m["capex"] - (m.get("lease_principal") or 0.0 if treatment == "operating" else 0.0)
    div_rate = _pos(info.get("dividendRate"), 1e9)  # Yahoo quotes it in the listing currency (pounds, not pence, for London)
    row = {
        "ticker": peer.ticker,
        "name": peer.name or str(info.get("shortName") or info.get("longName") or peer.ticker),
        "group": peer.group,
        "currency": snap.currency,
        "listing_currency": "GBP" if snap.price_currency == "GBp" else snap.price_currency,
        "fx_listing_to_reporting": fx_listing_to_reporting,
        "fiscal_year": m.get("fiscal_year"),
        "fy_end": m["fy_end"].date().isoformat() if m.get("fy_end") is not None else None,
        "basis": latest.basis if latest is not None else (f"FY{m.get('fiscal_year')}" if m else None),
        "market_cap": (mcap * fx_to_target / divisor) if mcap else None,
        "ev": (ev * fx_to_target / divisor) if ev else None,
        "revenue_growth": m.get("rev_growth"),
        "ebitda_margin": margin,
        "ebit_margin": (ebit / rev) if (ebit is not None and rev) else m.get("ebit_margin"),
        "ev_sales": _mult(ev, rev),
        "ev_ebitda": _mult(ev, ebitda),
        "ev_ebit": _mult(ev, ebit),
        "ev_ebitda_reported": _mult(ev_rep, m.get("ebitda_reported")),
        "pe": _pos(info.get("trailingPE"), 80),
        "fwd_pe": f["fwd_pe"] if f["fwd_pe"] is not None else _pos(info.get("forwardPE"), 80),
        "fwd_pe_source": "NTM consensus" if f["fwd_pe"] is not None else ("Yahoo forward P/E" if _pos(info.get("forwardPE"), 80) else None),
        "ev_sales_ntm": f["ev_sales_ntm"],
        "ev_ebitda_ntm": f["ev_ebitda_ntm"],
        "pe_fy0": f["pe_fy0"],
        "pe_fy1": f["pe_fy1"],
        "peg": f["peg"],
        "growth_fwd": f["growth_fwd"],
        "eps_growth": f["eps_growth"],
        "growth_reg": f["growth_fwd"] if f["growth_fwd"] is not None else m.get("rev_growth"),
        "n_analysts": fwd.n_revenue if fwd is not None else None,
        "ntm_weight_fy0": fwd.weight_fy0 if fwd is not None else None,
        "estimates_currency": fwd.estimates_currency if fwd is not None else None,
        "fcf_yield": _yield(fcf, mcap),
        "div_yield": _yield(div_rate, price_listing, cap=0.20),
        "beta": _pos(info.get("beta"), 5.0),
        "debt_to_equity": (max(debt, 0.0) / mcap) if (debt is not None and mcap) else None,
    }
    return row


def build_comps(
    cfg: CompanyConfig,
    company_snap: Snapshot,
    peer_snaps: dict[str, Snapshot],
    fx_rates: dict[str, float],
    *,
    company_metrics: dict[str, float | None],
    net_debt: float,
    minorities: float,
    shares: float,
    price: float | None,
    forward_eps: float | None = None,
    peer_balances: dict[str, pd.DataFrame | None] | None = None,
    peer_fx_listing: dict[str, float] | None = None,
    valuation_date: dt.date | None = None,
    company_forward: dict[str, float | None] | None = None,
) -> CompsResult:
    """``company_metrics``: revenue, ebitda, ebit (LTM, model units), eps (trailing, listing currency), and optionally
    growth (last FY), fcf (levered, model units) and div_yield. ``company_forward``: the target's own forward multiples
    (from ``forward_multiples``); ``forward_eps`` (NTM EPS, listing currency) is kept for callers without it."""
    rows = []
    for peer in cfg.peers:
        snap = peer_snaps.get(peer.ticker)
        if snap is None:
            continue
        fx = fx_rates.get(snap.currency, 1.0)
        try:
            rows.append(_peer_row(peer, snap, cfg.assumptions.lease_treatment, cfg.assumptions.lease_rate, fx, cfg.units_divisor,
                                  (peer_balances or {}).get(peer.ticker), (peer_fx_listing or {}).get(peer.ticker, 1.0), valuation_date))
        except Exception:
            continue
    table = pd.DataFrame(rows)
    stats_rows: dict[str, dict] = {}
    if not table.empty:
        for group, sub in [("All", table)] + [(g, table[table["group"] == g]) for g in table["group"].unique()]:
            for stat in ("mean", "median", "p25", "p75"):
                vals = {}
                for m in STAT_KEYS:
                    s = pd.to_numeric(sub[m], errors="coerce").dropna() if m in sub else pd.Series(dtype=float)
                    if s.empty:
                        vals[m] = np.nan
                    elif stat == "mean":
                        vals[m] = float(s.mean())
                    elif stat == "median":
                        vals[m] = float(s.median())
                    elif stat == "p25":
                        vals[m] = float(s.quantile(0.25))
                    else:
                        vals[m] = float(s.quantile(0.75))
                stats_rows[f"{group}|{stat}"] = vals
    stats = pd.DataFrame(stats_rows).T if stats_rows else pd.DataFrame(columns=STAT_KEYS)

    # ---- company's own multiples --------------------------------------------
    mcap = (price * shares) if (price and shares) else None
    ev = (mcap + net_debt + minorities) if mcap is not None else None
    cm = company_metrics
    cf = company_forward or {}
    fwd_eps = cf.get("eps_ntm") if cf.get("eps_ntm") else forward_eps
    company = {
        "market_cap": mcap,
        "ev": ev,
        "ev_sales": (ev / cm["revenue"]) if (ev and cm.get("revenue")) else None,
        "ev_ebitda": (ev / cm["ebitda"]) if (ev and cm.get("ebitda")) else None,
        "ev_ebit": (ev / cm["ebit"]) if (ev and cm.get("ebit")) else None,
        "pe": (price / cm["eps"]) if (price and cm.get("eps") and cm["eps"] > 0) else None,
        "fwd_pe": (price / fwd_eps) if (price and fwd_eps and fwd_eps > 0) else None,
        "ev_sales_ntm": cf.get("ev_sales_ntm"), "ev_ebitda_ntm": cf.get("ev_ebitda_ntm"), "pe_fy0": cf.get("pe_fy0"), "pe_fy1": cf.get("pe_fy1"),
        "peg": cf.get("peg"), "growth_fwd": cf.get("growth_fwd"), "eps_growth": cf.get("eps_growth"),
        "fcf_yield": _yield(cm.get("fcf"), mcap), "div_yield": cm.get("div_yield"),
        "ebitda_margin": (cm["ebitda"] / cm["revenue"]) if (cm.get("ebitda") is not None and cm.get("revenue")) else None,
        "revenue_growth": cm.get("growth"),
    }

    # ---- implied values from peer medians ------------------------------------
    implied: dict[str, ImpliedValue] = {}
    if not stats.empty and "All|median" in stats.index:
        med, p25, p75 = stats.loc["All|median"], stats.loc["All|p25"], stats.loc["All|p75"]

        def ev_based(key: str, metric: float | None, basis: str):
            if metric is None or metric <= 0 or pd.isna(med[key]):
                return
            def per_share(mult: float) -> float:
                return (mult * metric - net_debt - minorities) / shares
            implied[key] = ImpliedValue(key, MULTIPLE_LABELS[key], float(med[key]), per_share(float(med[key])),
                                        float(p25[key]), float(p75[key]), per_share(float(p25[key])), per_share(float(p75[key])), basis)

        def eps_based(key: str, eps: float | None, basis: str):
            if eps and eps > 0 and not pd.isna(med[key]):
                implied[key] = ImpliedValue(key, MULTIPLE_LABELS[key], float(med[key]), float(med[key]) * eps, float(p25[key]), float(p75[key]),
                                            float(p25[key]) * eps, float(p75[key]) * eps, basis)

        ev_based("ev_ebitda", cm.get("ebitda"), "LTM EBITDA x peer median")
        ev_based("ev_ebit", cm.get("ebit"), "LTM EBIT x peer median")
        ev_based("ev_sales", cm.get("revenue"), "LTM revenue x peer median")
        ev_based("ev_sales_ntm", cf.get("revenue_ntm"), "NTM consensus revenue x peer median")
        eps_based("pe", cm.get("eps"), "Trailing EPS x peer median")
        eps_based("fwd_pe", fwd_eps, "NTM consensus EPS x peer median")

    # ---- regression of EV/EBITDA on growth and margin --------------------------
    target = {"ev_ebitda": company["ev_ebitda"], "ebitda_margin": company["ebitda_margin"],
              "growth_reg": cf.get("growth_fwd") if cf.get("growth_fwd") is not None else cm.get("growth")}
    regression = multiples_regression(table, target, ebitda=cm.get("ebitda"), net_debt=net_debt, minorities=minorities, shares=shares)
    return CompsResult(table=table, stats=stats, company=company, implied=implied, company_currency=company_snap.currency, regression=regression)
