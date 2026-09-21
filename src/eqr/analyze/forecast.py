"""Driver-based operating forecast.

Revenue growth fades from the near-term anchor (consensus if available, else the
historical CAGR) to the terminal growth rate. Margins and reinvestment ratios
either come from the config or are held at recent averages. Every driver is
exposed so the analyst can override it in YAML — the engine never hides an
assumption.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import CompanyConfig
from ..retrieve import Snapshot


@dataclass
class Drivers:
    years: list[int]
    revenue_growth: list[float]
    ebitda_margin: list[float]
    da_pct: float
    capex_pct: float
    nwc_pct: float
    tax_rate: float
    terminal_growth: float
    growth_anchor: str = ""
    notes: list[str] = field(default_factory=list)
    capex_pct_path: list[float] = field(default_factory=list)  # capex % of revenue per forecast year (may normalise towards D&A)
    tax_source: str = ""

    def capex_at(self, i: int) -> float:
        """Capex % of revenue in forecast year ``i`` (0-based); the terminal year uses the last value."""
        if not self.capex_pct_path:
            return self.capex_pct
        return self.capex_pct_path[min(i, len(self.capex_pct_path) - 1)]


def _pad(values: list[float], n: int) -> list[float]:
    values = [float(v) for v in values]
    if not values:
        return []
    while len(values) < n:
        values.append(values[-1])
    return values[:n]


def _linspace(a: float, b: float, n: int) -> list[float]:
    if n <= 1:
        return [b]
    return [float(x) for x in np.linspace(a, b, n)]


def _consensus_growth(snap: Snapshot, last_revenue_native: float) -> tuple[list[float], str]:
    """Return consensus revenue growth for the next fiscal years, aligned to history."""
    re = snap.revenue_estimate
    if re is None or re.empty or "growth" not in re.columns:
        return [], ""
    rows = {str(i): r for i, r in re.iterrows()}
    g0, g1 = rows.get("0y"), rows.get("+1y")
    if g0 is None or pd.isna(g0.get("growth")):
        return [], ""
    year_ago = g0.get("yearAgoRevenue")
    aligned = True
    if year_ago is not None and not pd.isna(year_ago) and last_revenue_native:
        aligned = abs(float(year_ago) / float(last_revenue_native) - 1.0) < 0.06
    growth: list[float] = []
    if aligned:
        growth.append(float(g0["growth"]))
        if g1 is not None and not pd.isna(g1.get("growth")):
            growth.append(float(g1["growth"]))
        n = int(g0.get("numberOfAnalysts") or 0)
        return growth, f"consensus ({n} analysts)"
    # consensus already refers to a year beyond our last actual -> use +1y only
    if g1 is not None and not pd.isna(g1.get("growth")):
        return [float(g1["growth"])], "consensus (+1y)"
    return [], ""


def derive_drivers(hist: pd.DataFrame, cfg: CompanyConfig, snap: Snapshot) -> Drivers:
    a = cfg.assumptions
    n = int(a.forecast_years)
    last_year = int(hist.index[-1])
    years = [last_year + i for i in range(1, n + 1)]
    notes: list[str] = []

    # ---- revenue growth ------------------------------------------------------
    if a.revenue_growth:
        growth = _pad(list(a.revenue_growth), n)
        anchor = "config"
    else:
        last_rev_native = float(hist["revenue"].iloc[-1] * cfg.units_divisor)
        cons, anchor = ([], "")
        if a.use_consensus_growth:
            cons, anchor = _consensus_growth(snap, last_rev_native)
        if not cons:
            rev = hist["revenue"].dropna()
            k = min(3, len(rev) - 1)
            if k >= 1:
                cagr = float((rev.iloc[-1] / rev.iloc[-1 - k]) ** (1 / k) - 1)
            else:
                cagr = a.terminal_growth
            cons = [cagr]
            anchor = f"{k}y historical CAGR"
        cons = [min(max(g, a.growth_floor), a.growth_cap) for g in cons]
        remaining = n - len(cons)
        fade = _linspace(cons[-1], a.terminal_growth, remaining + 1)[1:] if remaining > 0 else []
        growth = (cons + fade)[:n]
        notes.append(f"Revenue growth anchored on {anchor}, fading linearly to {a.terminal_growth:.1%} terminal growth.")

    # ---- EBITDA margin -----------------------------------------------------
    last_margin = float(hist["ebitda_margin"].iloc[-1])
    if a.ebitda_margin:
        margins = _pad(list(a.ebitda_margin), n)
    elif a.ebitda_margin_target is not None:
        margins = _linspace(last_margin, float(a.ebitda_margin_target), n + 1)[1:]
        notes.append(f"EBITDA margin moves linearly from {last_margin:.1%} to {a.ebitda_margin_target:.1%}.")
    else:
        recent = hist["ebitda_margin"].dropna().tail(3)
        target = float(recent.mean()) if len(recent) else last_margin
        margins = _linspace(last_margin, target, n + 1)[1:]
        notes.append(f"EBITDA margin held near the 3-year average of {target:.1%}.")

    def _avg(col: str, default: float, lo: float, hi: float) -> float:
        s = hist[col].replace([np.inf, -np.inf], np.nan).dropna().tail(3)
        v = float(s.mean()) if len(s) else default
        return float(min(max(v, lo), hi))

    da_pct = float(a.da_pct_revenue) if a.da_pct_revenue is not None else _avg("da_pct", 0.05, 0.0, 0.4)
    capex_pct = float(a.capex_pct_revenue) if a.capex_pct_revenue is not None else _avg("capex_pct", 0.05, 0.0, 0.4)
    # Net working capital is modelled as a *level* (% of revenue): the cash effect each year is
    # -NWC% x change in revenue. A business that collects cash up front (negative NWC) releases
    # cash as it grows; a receivables-heavy business absorbs it. Never a perpetual inflow.
    if a.nwc_pct_revenue is not None:
        nwc_pct = float(a.nwc_pct_revenue)
    else:
        lvl = hist["nwc_pct_of_revenue"].replace([np.inf, -np.inf], np.nan).dropna().tail(3) if "nwc_pct_of_revenue" in hist else pd.Series(dtype=float)
        if len(lvl):
            nwc_pct = float(min(max(lvl.mean(), -0.6), 0.6))
            notes.append(f"Net working capital held at {nwc_pct:.1%} of revenue (3-year average from the balance sheet).")
        else:
            nwc_pct = 0.0
            notes.append("No balance-sheet working-capital data; change in NWC assumed zero.")
    # ---- capex: a company in an investment phase (capex well above D&A) normalises towards replacement level
    if a.capex_pct_terminal is not None:
        capex_terminal = float(a.capex_pct_terminal)
    elif capex_pct > da_pct * 1.05 and da_pct > 0:
        capex_terminal = da_pct * 1.05
        notes.append(f"Capex normalises from {capex_pct:.1%} to {capex_terminal:.1%} of revenue (D&A x 1.05) by {years[-1]}E.")
    else:
        capex_terminal = capex_pct
    capex_path = _linspace(capex_pct, capex_terminal, n) if n > 1 else [capex_terminal]

    # ---- tax: statutory unless the accounts show a structurally different rate (petroleum tax, tax havens)
    statutory = float(a.statutory_tax_rate)
    if a.tax_rate is not None:
        tax, tax_source = float(a.tax_rate), "config"
    else:
        # profit-weighted effective rate (total tax / total pre-tax profit over the last three profitable years): a plain
        # average is dominated by low-profit years, where a small denominator produces meaningless 60-90% rates
        recent = hist.tail(3)
        profitable = recent[(recent["pretax"] > 0) & recent["tax"].notna()] if {"pretax", "tax"} <= set(recent.columns) else recent.iloc[0:0]
        agg = float(profitable["tax"].sum() / profitable["pretax"].sum()) if len(profitable) and profitable["pretax"].sum() > 0 else statutory
        if abs(agg - statutory) <= 0.05:
            tax, tax_source = statutory, f"statutory rate (effective {agg:.0%})"
        else:
            tax, tax_source = float(min(max(agg, 0.10), 0.85)), "profit-weighted effective rate, last 3 years"
            notes.append(f"Tax rate of {tax:.0%} from the accounts ({tax_source}) instead of the {statutory:.0%} statutory rate.")
    return Drivers(years, growth, margins, da_pct, capex_pct, nwc_pct, tax, float(a.terminal_growth), anchor, notes,
                   capex_pct_path=capex_path, tax_source=tax_source)


def _year(revenue: float, prev_revenue: float, g: float, m: float, d: Drivers, capex_pct: float | None = None) -> dict:
    capex_pct = d.capex_pct if capex_pct is None else capex_pct
    ebitda = revenue * m
    da = revenue * d.da_pct
    ebit = ebitda - da
    tax = max(ebit, 0.0) * d.tax_rate
    nopat = ebit - tax
    capex = -revenue * capex_pct
    nwc = -d.nwc_pct * (revenue - prev_revenue)
    ufcf = nopat + da + capex + nwc
    return dict(revenue=revenue, growth=g, ebitda=ebitda, ebitda_margin=m, da=da, ebit=ebit, ebit_margin=ebit / revenue, tax=tax,
                nopat=nopat, nopat_margin=nopat / revenue, capex=capex, capex_pct=capex_pct, nwc_change=nwc, nwc_pct=d.nwc_pct,
                ufcf=ufcf, ufcf_margin=ufcf / revenue, da_pct=d.da_pct, tax_rate_used=d.tax_rate)


def build_forecast(hist: pd.DataFrame, drivers: Drivers) -> pd.DataFrame:
    """Forecast table with one row per year plus a normalised terminal row (index 'TV')."""
    rows = []
    prev = float(hist["revenue"].iloc[-1])
    for i, (year, g, m) in enumerate(zip(drivers.years, drivers.revenue_growth, drivers.ebitda_margin)):
        revenue = prev * (1 + g)
        rows.append(dict(year=year, **_year(revenue, prev, g, m, drivers, drivers.capex_at(i))))
        prev = revenue
    gt = drivers.terminal_growth
    rows.append(dict(year="TV", **_year(prev * (1 + gt), prev, gt, drivers.ebitda_margin[-1], drivers, drivers.capex_at(len(drivers.years)))))
    return pd.DataFrame(rows).set_index("year")
