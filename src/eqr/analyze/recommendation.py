"""Football field, 12-month target price and rating.

Sell-side target prices are 12-month forward values. The engine therefore rolls today's fair
value forward at the cost of equity and subtracts the dividend expected over the period:

    target price = fair value x (1 + Ke) ^ (months / 12) - DPS

The rating is set on the expected total return, (target price + DPS) / price - 1.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from ..config import CompanyConfig
from .comps import CompsResult
from .dcf import DcfResult

MIN_REGRESSION_R2 = 0.15  # below this the peers' multiples are not set by growth and margin, so the fit is not a valuation anchor


@dataclass
class FootballFieldBar:
    label: str
    low: float
    high: float
    note: str = ""


@dataclass
class Recommendation:
    rating: str
    target_price: float
    upside: float
    price: float
    method: str
    dcf_value: float
    multiples_value: float | None
    currency: str
    fair_value: float = 0.0  # value today, before the roll-forward
    dps: float = 0.0  # expected dividend per share over the horizon
    total_return: float = 0.0
    horizon_months: int = 0
    cost_of_equity: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def football_field(snapshot_info: dict, dcf: DcfResult, comps: CompsResult, price: float | None,
                   scenario_range: tuple[float, float] | None = None) -> list[FootballFieldBar]:
    bars: list[FootballFieldBar] = []
    lo, hi = snapshot_info.get("fiftyTwoWeekLow"), snapshot_info.get("fiftyTwoWeekHigh")
    if lo and hi:
        bars.append(FootballFieldBar("52-week range", float(lo), float(hi)))
    if dcf.sensitivity is not None:
        s = dcf.sensitivity
        k = len(s) // 2
        inner = s.iloc[max(k - 1, 0):k + 2, max(k - 1, 0):k + 2].values
        inner = inner[np.isfinite(inner)]
        if inner.size:
            bars.append(FootballFieldBar("DCF (WACC ±0.5%, g ±0.25%)", float(inner.min()), float(inner.max())))
    if scenario_range is not None and all(np.isfinite(scenario_range)) and scenario_range[1] > 0:
        bars.append(FootballFieldBar("DCF scenarios (bear–bull)", max(float(scenario_range[0]), 0.0), float(scenario_range[1])))
    for key in ("ev_ebitda", "ev_ebit", "pe", "fwd_pe", "ev_sales_ntm"):
        iv = comps.implied.get(key)
        if iv is None:
            continue
        lo_v, hi_v = sorted([iv.low, iv.high])
        if np.isfinite(lo_v) and np.isfinite(hi_v) and hi_v > 0:
            bars.append(FootballFieldBar(f"{iv.label} (peer 25th–75th pct)", max(lo_v, 0.0), hi_v))
    reg = getattr(comps, "regression", None)
    # a regression that explains little of the dispersion is reported on the multiples slide, not used as an anchor
    if reg is not None and reg.r2 >= MIN_REGRESSION_R2 and reg.low is not None and reg.high is not None and reg.high > 0:
        bars.append(FootballFieldBar("EV/EBITDA regression (growth, margin ±1σ)", max(float(reg.low), 0.0), float(reg.high),
                                     note=f"fitted {reg.fitted_target:.1f}x, R² {reg.r2:.2f}"))
    return bars


def _round_to(value: float, step: float) -> float:
    """Round half away from zero to a multiple of ``step`` (same as Excel's MROUND, unlike Python's round)."""
    if step <= 0 or not np.isfinite(value):
        return value
    return float(math.floor(value / step + 0.5) * step)


def recommend(cfg: CompanyConfig, price: float, dcf: DcfResult, comps: CompsResult, currency: str, *,
              cost_of_equity: float | None = None, dps: float = 0.0) -> Recommendation:
    r = cfg.recommendation
    dcf_value = float(dcf.value_per_share)
    mult_values = [iv.per_share for iv in comps.implied.values() if np.isfinite(iv.per_share) and iv.per_share > 0]
    multiples_value = float(np.median(mult_values)) if mult_values else None
    if r.tp_method == "blend" and multiples_value is not None:
        fair = r.blend_dcf_weight * dcf_value + (1 - r.blend_dcf_weight) * multiples_value
        method = f"{r.blend_dcf_weight:.0%} DCF / {1 - r.blend_dcf_weight:.0%} peer multiples"
    else:
        fair = dcf_value
        method = "DCF (base case)"
    dps = float(dps) if (dps and np.isfinite(dps) and dps > 0) else 0.0
    months = int(r.roll_forward_months) if (r.roll_forward and cost_of_equity) else 0
    if months > 0:
        tp = fair * (1 + float(cost_of_equity)) ** (months / 12.0) - dps
        method += f", rolled forward {months} months at the cost of equity"
    else:
        tp = fair
    meaningful = bool(np.isfinite(fair) and fair > 0)
    if not meaningful:  # negative or undefined equity value: the FCFF framework does not describe this company
        tp, fair, method = 0.0, 0.0, method + " (not meaningful: equity value is not positive)"
    tp = _round_to(tp, r.tp_rounding)
    upside = tp / price - 1 if price else float("nan")
    total_return = (tp + (dps if months > 0 else 0.0)) / price - 1 if price else float("nan")
    basis = total_return if r.rating_on_total_return else upside
    if not meaningful:
        rating = "NOT RATED"
    elif basis >= r.buy_threshold:
        rating = "BUY"
    elif basis <= r.sell_threshold:
        rating = "SELL"
    else:
        rating = "HOLD"
    return Recommendation(rating, tp, float(upside), float(price), method, dcf_value, multiples_value, currency,
                          fair_value=float(fair), dps=dps if months > 0 else 0.0, total_return=float(total_return),
                          horizon_months=months, cost_of_equity=cost_of_equity)
