"""Bear / base / bull scenarios and the market-implied ("reverse DCF") view.

A scenario shifts four levers relative to the base case: revenue growth (every forecast year),
the EBITDA margin path, WACC and terminal growth. Each scenario re-runs the full operating
forecast, so reinvestment (capex, working capital) moves with revenue exactly as in the base case.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from ..config import CompanyConfig
from .dcf import implied_terminal_growth, implied_wacc, solve, value_per_share
from .forecast import Drivers, build_forecast


@dataclass
class ScenarioResult:
    name: str
    probability: float
    growth_shift: float
    margin_shift: float
    wacc: float
    terminal_growth: float
    revenue_cagr: float
    final_margin: float
    final_revenue: float
    value_per_share: float
    upside: float | None
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReverseDcf:
    """What the current share price implies, holding everything else at the base case."""

    implied_wacc: float | None
    implied_terminal_growth: float | None
    implied_margin_shift: float | None
    implied_final_margin: float | None
    base_wacc: float
    base_terminal_growth: float
    base_final_margin: float

    def as_dict(self) -> dict:
        return asdict(self)


def shifted_drivers(drivers: Drivers, growth_shift: float = 0.0, margin_shift: float = 0.0, terminal_growth_shift: float = 0.0) -> Drivers:
    return replace(
        drivers,
        revenue_growth=[g + growth_shift for g in drivers.revenue_growth],
        ebitda_margin=[m + margin_shift for m in drivers.ebitda_margin],
        terminal_growth=drivers.terminal_growth + terminal_growth_shift,
    )


def _value(hist: pd.DataFrame, drivers: Drivers, wacc: float, *, net_debt: float, shares: float, minorities: float, mid_year: bool,
           terminal_method: str, ronic: float | None) -> tuple[float, pd.DataFrame]:
    fc = build_forecast(hist, drivers)
    explicit = fc[fc.index != "TV"]
    fcfs = [float(v) for v in explicit["ufcf"].values]
    nopat_last = float(explicit["nopat"].iloc[-1]) if terminal_method == "value_driver" else None
    v = value_per_share(fcfs, wacc, drivers.terminal_growth, net_debt, shares, minorities, mid_year, nopat_last,
                        ronic if terminal_method == "value_driver" else None)
    return v, explicit


def run_scenarios(hist: pd.DataFrame, drivers: Drivers, cfg: CompanyConfig, base_wacc: float, *, net_debt: float, shares: float,
                  minorities: float, price: float | None, ronic: float | None) -> tuple[list[ScenarioResult], float | None]:
    a = cfg.assumptions
    results: list[ScenarioResult] = []
    last_rev = float(hist["revenue"].iloc[-1])
    for sc in cfg.scenarios:
        d = shifted_drivers(drivers, sc.growth_shift, sc.margin_shift, sc.terminal_growth_shift)
        w = base_wacc + sc.wacc_shift
        if w <= d.terminal_growth + 0.0025:
            continue
        v, explicit = _value(hist, d, w, net_debt=net_debt, shares=shares, minorities=minorities, mid_year=a.mid_year_convention,
                             terminal_method=a.terminal_method, ronic=ronic)
        n = len(explicit)
        final_rev = float(explicit["revenue"].iloc[-1])
        results.append(ScenarioResult(
            name=sc.name, probability=float(sc.probability), growth_shift=sc.growth_shift, margin_shift=sc.margin_shift, wacc=w,
            terminal_growth=d.terminal_growth, revenue_cagr=float((final_rev / last_rev) ** (1 / n) - 1),
            final_margin=float(explicit["ebitda_margin"].iloc[-1]), final_revenue=final_rev, value_per_share=float(v),
            upside=(v / price - 1) if price else None, note=sc.note,
        ))
    total_p = sum(r.probability for r in results)
    weighted = sum(r.probability * r.value_per_share for r in results) / total_p if total_p > 0 else None
    return results, (float(weighted) if weighted is not None and np.isfinite(weighted) else None)


def reverse_dcf(hist: pd.DataFrame, drivers: Drivers, cfg: CompanyConfig, base_wacc: float, *, net_debt: float, shares: float,
                minorities: float, price: float, ronic: float | None) -> ReverseDcf:
    a = cfg.assumptions
    fc = build_forecast(hist, drivers)
    explicit = fc[fc.index != "TV"]
    fcfs = [float(v) for v in explicit["ufcf"].values]
    use_vd = a.terminal_method == "value_driver"
    nopat_last = float(explicit["nopat"].iloc[-1]) if use_vd else None
    r = ronic if use_vd else None
    iw = implied_wacc(fcfs, drivers.terminal_growth, net_debt, shares, minorities, price, a.mid_year_convention, nopat_last, r)
    ig = implied_terminal_growth(fcfs, base_wacc, net_debt, shares, minorities, price, a.mid_year_convention, nopat_last, r)

    def value_at(shift: float) -> float:
        v, _ = _value(hist, shifted_drivers(drivers, margin_shift=shift), base_wacc, net_debt=net_debt, shares=shares,
                      minorities=minorities, mid_year=a.mid_year_convention, terminal_method=a.terminal_method, ronic=ronic)
        return v

    ms = solve(value_at, price, -0.25, 0.25, increasing=True)
    base_margin = float(drivers.ebitda_margin[-1])
    return ReverseDcf(implied_wacc=iw, implied_terminal_growth=ig, implied_margin_shift=ms,
                      implied_final_margin=(base_margin + ms) if ms is not None else None, base_wacc=base_wacc,
                      base_terminal_growth=drivers.terminal_growth, base_final_margin=base_margin)
