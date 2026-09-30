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
           terminal_method: str, ronic: float | None, valuation_offset: float = 0.0, balance_offset: float = 0.0) -> tuple[float, pd.DataFrame]:
    fc = build_forecast(hist, drivers)
    explicit = fc[fc.index != "TV"]
    fcfs = [float(v) for v in explicit["ufcf"].values]
    nopat_last = float(explicit["nopat"].iloc[-1]) if terminal_method == "value_driver" else None
    v = value_per_share(fcfs, wacc, drivers.terminal_growth, net_debt, shares, minorities, mid_year, nopat_last,
                        ronic if terminal_method == "value_driver" else None, valuation_offset, balance_offset)
    return v, explicit


def run_scenarios(hist: pd.DataFrame, drivers: Drivers, cfg: CompanyConfig, base_wacc: float, *, net_debt: float, shares: float,
                  minorities: float, price: float | None, ronic: float | None, valuation_offset: float = 0.0,
                  balance_offset: float = 0.0) -> tuple[list[ScenarioResult], float | None]:
    a = cfg.assumptions
    results: list[ScenarioResult] = []
    last_rev = float(hist["revenue"].iloc[-1])
    for sc in cfg.scenarios:
        d = shifted_drivers(drivers, sc.growth_shift, sc.margin_shift, sc.terminal_growth_shift)
        w = base_wacc + sc.wacc_shift
        if w <= d.terminal_growth + 0.0025:
            continue
        v, explicit = _value(hist, d, w, net_debt=net_debt, shares=shares, minorities=minorities, mid_year=a.mid_year_convention,
                             terminal_method=a.terminal_method, ronic=ronic, valuation_offset=valuation_offset, balance_offset=balance_offset)
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
                minorities: float, price: float, ronic: float | None, valuation_offset: float = 0.0, balance_offset: float = 0.0) -> ReverseDcf:
    a = cfg.assumptions
    fc = build_forecast(hist, drivers)
    explicit = fc[fc.index != "TV"]
    fcfs = [float(v) for v in explicit["ufcf"].values]
    use_vd = a.terminal_method == "value_driver"
    nopat_last = float(explicit["nopat"].iloc[-1]) if use_vd else None
    r = ronic if use_vd else None
    timing = {"valuation_offset": valuation_offset, "balance_offset": balance_offset}
    iw = implied_wacc(fcfs, drivers.terminal_growth, net_debt, shares, minorities, price, a.mid_year_convention, nopat_last, r, **timing)
    ig = implied_terminal_growth(fcfs, base_wacc, net_debt, shares, minorities, price, a.mid_year_convention, nopat_last, r, **timing)

    def value_at(shift: float) -> float:
        v, _ = _value(hist, shifted_drivers(drivers, margin_shift=shift), base_wacc, net_debt=net_debt, shares=shares,
                      minorities=minorities, mid_year=a.mid_year_convention, terminal_method=a.terminal_method, ronic=ronic, **timing)
        return v

    ms = solve(value_at, price, -0.25, 0.25, increasing=True)
    base_margin = float(drivers.ebitda_margin[-1])
    return ReverseDcf(implied_wacc=iw, implied_terminal_growth=ig, implied_margin_shift=ms,
                      implied_final_margin=(base_margin + ms) if ms is not None else None, base_wacc=base_wacc,
                      base_terminal_growth=drivers.terminal_growth, base_final_margin=base_margin)


# --------------------------------------------------------------------------- value drivers (tornado)
@dataclass
class DriverSensitivity:
    """Value per share with one driver shocked down and up, everything else at the base case."""

    driver: str
    shock: str
    value_down: float  # driver lowered by the shock
    value_up: float  # driver raised by the shock
    base: float

    @property
    def swing(self) -> float:
        vals = [v for v in (self.value_down, self.value_up) if np.isfinite(v)]
        return float(max(vals) - min(vals)) if len(vals) == 2 else 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["swing"] = self.swing
        return d


# (label, lever, step, shock text). Steps are the moves a portfolio manager asks about first.
TORNADO_SHOCKS = [
    ("EBITDA margin (all years)", "margin", 0.01, "±1pp"),
    ("Revenue growth (all years)", "growth", 0.01, "±1pp"),
    ("WACC", "wacc", 0.005, "±0.5pp"),
    ("Terminal growth", "tg", 0.005, "±0.5pp"),
    ("Capex, % of revenue", "capex", 0.005, "±0.5pp"),
    ("Working capital, % of revenue", "nwc", 0.02, "±2pp"),
    ("Tax rate", "tax", 0.02, "±2pp"),
]


def value_drivers(hist: pd.DataFrame, drivers: Drivers, cfg: CompanyConfig, base_wacc: float, *, net_debt: float, shares: float,
                  minorities: float, ronic: float | None, valuation_offset: float = 0.0, balance_offset: float = 0.0) -> list[DriverSensitivity]:
    """One-at-a-time sensitivities of the DCF value, sorted by swing (largest first)."""
    a = cfg.assumptions
    common = dict(net_debt=net_debt, shares=shares, minorities=minorities, mid_year=a.mid_year_convention,
                  terminal_method=a.terminal_method, ronic=ronic, valuation_offset=valuation_offset, balance_offset=balance_offset)
    base, _ = _value(hist, drivers, base_wacc, **common)
    out: list[DriverSensitivity] = []
    for label, lever, step, shock in TORNADO_SHOCKS:
        vals = []
        for sign in (-1.0, 1.0):
            s, d, w = sign * step, drivers, base_wacc
            if lever == "growth":
                d = shifted_drivers(drivers, growth_shift=s)
            elif lever == "margin":
                d = shifted_drivers(drivers, margin_shift=s)
            elif lever == "tg":
                d = shifted_drivers(drivers, terminal_growth_shift=s)
            elif lever == "wacc":
                w = base_wacc + s
            elif lever == "capex":
                d = replace(drivers, capex_pct=drivers.capex_pct + s, capex_pct_path=[c + s for c in drivers.capex_pct_path])
            elif lever == "nwc":
                d = replace(drivers, nwc_pct=drivers.nwc_pct + s)
            elif lever == "tax":
                d = replace(drivers, tax_rate=min(max(drivers.tax_rate + s, 0.0), 0.95))
            if w <= d.terminal_growth + 0.0025:
                vals.append(float("nan"))
                continue
            vals.append(float(_value(hist, d, w, **common)[0]))
        out.append(DriverSensitivity(label, shock, vals[0], vals[1], float(base)))
    return sorted(out, key=lambda x: -x.swing)
