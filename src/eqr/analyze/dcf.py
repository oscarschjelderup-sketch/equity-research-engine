"""Unlevered DCF (FCFF): terminal value, sensitivity grid and reverse-DCF solvers.

Terminal value methods
----------------------
* ``gordon``        TV = FCF_N x (1 + g) / (WACC - g)
* ``value_driver``  TV = NOPAT_N x (1 + g) x (1 - g / RONIC) / (WACC - g)

The value-driver form makes the reinvestment needed for growth explicit: growing at g while
earning RONIC on new capital requires reinvesting g / RONIC of NOPAT. With RONIC = WACC growth
adds no value; with RONIC -> infinity it collapses to a plain NOPAT perpetuity.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class DcfResult:
    years: list[int]
    fcf: list[float]
    discount_factors: list[float]
    pv_fcf: list[float]
    sum_pv_fcf: float
    terminal_fcf: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    net_debt: float
    minorities: float
    equity_value: float
    shares: float
    value_per_share: float
    price: float | None
    upside: float | None
    tv_share_of_ev: float
    wacc: float
    terminal_growth: float
    mid_year: bool
    implied_exit_ev_ebitda: float | None = None
    terminal_method: str = "gordon"
    ronic: float | None = None
    sensitivity: pd.DataFrame | None = field(default=None, repr=False)
    sensitivity_waccs: list[float] = field(default_factory=list)
    sensitivity_growths: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("sensitivity", None)
        if self.sensitivity is not None:
            d["sensitivity"] = {
                "growths": [float(g) for g in self.sensitivity.index],
                "waccs": [float(w) for w in self.sensitivity.columns],
                "values": [[float(v) for v in row] for row in self.sensitivity.values],
            }
        return d


def terminal_cash_flow(fcf_last: float, g: float, nopat_last: float | None = None, ronic: float | None = None) -> float:
    """Cash flow in year N+1 that the perpetuity capitalises."""
    if ronic is not None and nopat_last is not None and ronic > 0:
        return nopat_last * (1 + g) * (1 - g / ronic)
    return fcf_last * (1 + g)


def value_per_share(fcfs: list[float], wacc: float, g: float, net_debt: float, shares: float, minorities: float = 0.0,
                    mid_year: bool = False, nopat_last: float | None = None, ronic: float | None = None) -> float:
    """Equity value per share for a given WACC / terminal growth pair."""
    if wacc <= g:
        return float("nan")
    n = len(fcfs)
    t = np.arange(1, n + 1, dtype=float) - (0.5 if mid_year else 0.0)
    dfs = (1 + wacc) ** (-t)
    pv = float(np.sum(np.array(fcfs) * dfs))
    tv = terminal_cash_flow(fcfs[-1], g, nopat_last, ronic) / (wacc - g)
    pv_tv = tv * (1 + wacc) ** (-n)
    equity = pv + pv_tv - net_debt - minorities
    return float(equity / shares) if shares else float("nan")


def run_dcf(
    forecast: pd.DataFrame,
    *,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    shares: float,
    minorities: float = 0.0,
    mid_year: bool = False,
    price: float | None = None,
    wacc_step: float = 0.005,
    growth_step: float = 0.0025,
    grid: int = 7,
    terminal_method: str = "gordon",
    ronic: float | None = None,
) -> DcfResult:
    explicit = forecast[forecast.index != "TV"]
    years = [int(y) for y in explicit.index]
    fcfs = [float(v) for v in explicit["ufcf"].values]
    n = len(fcfs)
    if wacc <= terminal_growth:
        raise ValueError(f"WACC ({wacc:.2%}) must exceed terminal growth ({terminal_growth:.2%}).")
    nopat_last = float(explicit["nopat"].iloc[-1]) if (terminal_method == "value_driver" and "nopat" in explicit) else None
    ronic_used = ronic if nopat_last is not None else None
    t = np.arange(1, n + 1, dtype=float) - (0.5 if mid_year else 0.0)
    dfs = (1 + wacc) ** (-t)
    pv = np.array(fcfs) * dfs
    terminal_fcf = terminal_cash_flow(fcfs[-1], terminal_growth, nopat_last, ronic_used)
    tv = terminal_fcf / (wacc - terminal_growth)
    pv_tv = tv * (1 + wacc) ** (-n)
    ev = float(pv.sum() + pv_tv)
    equity = ev - net_debt - minorities
    vps = equity / shares if shares else float("nan")
    upside = (vps / price - 1) if price else None
    ebitda_n = float(explicit["ebitda"].iloc[-1]) if "ebitda" in explicit else None
    exit_mult = tv / ebitda_n if ebitda_n else None

    # sensitivity grid (growth rows x WACC columns)
    k = grid // 2
    waccs = [round(wacc + (i - k) * wacc_step, 6) for i in range(grid)]
    growths = [round(terminal_growth + (i - k) * growth_step, 6) for i in range(grid)]
    values = [[value_per_share(fcfs, w, g, net_debt, shares, minorities, mid_year, nopat_last, ronic_used) for w in waccs] for g in growths]
    sens = pd.DataFrame(values, index=growths, columns=waccs)

    return DcfResult(
        years=years, fcf=fcfs, discount_factors=[float(x) for x in dfs], pv_fcf=[float(x) for x in pv],
        sum_pv_fcf=float(pv.sum()), terminal_fcf=float(terminal_fcf), terminal_value=float(tv), pv_terminal=float(pv_tv),
        enterprise_value=ev, net_debt=float(net_debt), minorities=float(minorities), equity_value=float(equity),
        shares=float(shares), value_per_share=float(vps), price=price, upside=upside,
        tv_share_of_ev=float(pv_tv / ev) if ev else float("nan"), wacc=float(wacc), terminal_growth=float(terminal_growth),
        mid_year=mid_year, implied_exit_ev_ebitda=exit_mult, terminal_method="value_driver" if ronic_used else "gordon",
        ronic=ronic_used, sensitivity=sens, sensitivity_waccs=waccs, sensitivity_growths=growths,
    )


# --------------------------------------------------------------------------- reverse DCF
def solve(fn: Callable[[float], float], target: float, lo: float, hi: float, *, increasing: bool, tol: float = 1e-6,
          max_iter: int = 200) -> float | None:
    """Bisection for fn(x) = target on [lo, hi]; returns None when the target is outside the bracket."""
    f_lo, f_hi = fn(lo), fn(hi)
    if not (np.isfinite(f_lo) and np.isfinite(f_hi)):
        return None
    if increasing and not (f_lo <= target <= f_hi):
        return None
    if not increasing and not (f_hi <= target <= f_lo):
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = fn(mid)
        if not np.isfinite(f_mid):
            return None
        if abs(f_mid - target) < tol * max(1.0, abs(target)):
            return float(mid)
        if (f_mid < target) == increasing:
            lo = mid
        else:
            hi = mid
    return float((lo + hi) / 2)


def implied_wacc(fcfs: list[float], g: float, net_debt: float, shares: float, minorities: float, price: float, mid_year: bool = False,
                 nopat_last: float | None = None, ronic: float | None = None) -> float | None:
    """The discount rate at which the DCF value equals the share price."""
    return solve(lambda w: value_per_share(fcfs, w, g, net_debt, shares, minorities, mid_year, nopat_last, ronic), price,
                 g + 0.0025, 0.40, increasing=False)


def implied_terminal_growth(fcfs: list[float], wacc: float, net_debt: float, shares: float, minorities: float, price: float,
                            mid_year: bool = False, nopat_last: float | None = None, ronic: float | None = None) -> float | None:
    """The perpetual growth rate at which the DCF value equals the share price."""
    return solve(lambda g: value_per_share(fcfs, wacc, g, net_debt, shares, minorities, mid_year, nopat_last, ronic), price,
                 -0.10, wacc - 0.0025, increasing=True)
