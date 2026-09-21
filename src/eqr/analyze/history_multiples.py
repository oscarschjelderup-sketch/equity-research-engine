"""The company's own multiples through time ("valuation bands").

For every weekly close the engine pairs the share price with the latest fiscal year that was
public at the time (fiscal year-end plus a reporting lag), giving a trailing EV/EBITDA and P/E
series on the same lease basis as the rest of the model. The median and the 25th-75th percentile
band answer "is it cheap against its own history?", and the median applied to today's earnings
gives one more bar in the football field.

Approximations, stated rather than hidden: the share count is the fiscal year's diluted average,
net debt steps once a year, and for dual-currency companies today's FX rate is used throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REPORTING_LAG_DAYS = 75
# Tighter than the peer-table limits: a recovery year with near-zero earnings (SATS 2022: 58x) is not a valuation regime,
# and one such year would stretch the interquartile band until it says nothing.
MAX_EV_MULTIPLE, MAX_PE = 30.0, 60.0


@dataclass
class MultipleHistory:
    series: pd.DataFrame  # index: date; columns: ev_ebitda, pe
    stats: dict[str, dict[str, float | None]] = field(default_factory=dict)  # per multiple: current, median, p25, p75, percentile, years
    implied: dict[str, dict[str, float]] = field(default_factory=dict)  # per multiple: per_share, low, high

    def as_dict(self) -> dict:
        s = self.series.replace([np.inf, -np.inf], np.nan)
        return {
            "dates": [pd.Timestamp(i).strftime("%Y-%m-%d") for i in s.index],
            "ev_ebitda": [None if pd.isna(v) else float(v) for v in s["ev_ebitda"]] if "ev_ebitda" in s else [],
            "pe": [None if pd.isna(v) else float(v) for v in s["pe"]] if "pe" in s else [],
            "stats": self.stats, "implied": self.implied,
        }


def _stats(s: pd.Series) -> dict[str, float | None]:
    s = s.dropna()
    if len(s) < 26:  # less than half a year of observations is not a history
        return {}
    cur = float(s.iloc[-1])
    return {"current": cur, "median": float(s.median()), "p25": float(s.quantile(0.25)), "p75": float(s.quantile(0.75)),
            "min": float(s.min()), "max": float(s.max()), "percentile": float((s <= cur).mean()),
            "years": float((s.index[-1] - s.index[0]).days / 365.25)}


def build_multiple_history(hist: pd.DataFrame, prices: pd.DataFrame | None, *, fx: float, shares_now: float, net_debt_now: float,
                           minorities_now: float, fiscal_year_end_month: int = 12, units_divisor: float = 1e6) -> MultipleHistory | None:
    """``hist`` is the canonical history (reporting units); ``prices`` weekly closes in the listing currency.

    ``shares_now`` are effective shares (shares x FX) in reporting units, as used everywhere else in the engine.
    """
    if prices is None or prices.empty or "Close" not in prices:
        return None
    close = prices["Close"].dropna().copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    rows = []
    for year, h in hist.iterrows():
        available = pd.Timestamp(year=int(year), month=fiscal_year_end_month, day=28) + pd.Timedelta(days=REPORTING_LAG_DAYS)
        shares_y = float(h["shares"]) * 1e6 / units_divisor * fx if pd.notna(h.get("shares")) and h["shares"] > 0 else shares_now
        rows.append(dict(available=available, ebitda=h.get("ebitda"), eps=h.get("eps"), net_debt=h.get("net_debt"),
                         minority=h.get("minority") if pd.notna(h.get("minority")) else 0.0, shares=shares_y))
    fund = pd.DataFrame(rows).sort_values("available")
    out = []
    for date, price in close.items():
        known = fund[fund["available"] <= date]
        if known.empty:
            continue
        f = known.iloc[-1]
        ev = price * f["shares"] + (f["net_debt"] if pd.notna(f["net_debt"]) else 0.0) + f["minority"]
        ev_ebitda = ev / f["ebitda"] if pd.notna(f["ebitda"]) and f["ebitda"] > 0 else np.nan
        eps_listing = f["eps"] / fx if pd.notna(f["eps"]) else np.nan
        pe = price / eps_listing if pd.notna(eps_listing) and eps_listing > 0 else np.nan
        out.append(dict(date=date, ev_ebitda=ev_ebitda if 0 < ev_ebitda < MAX_EV_MULTIPLE else np.nan, pe=pe if 0 < pe < MAX_PE else np.nan))
    if not out:
        return None
    series = pd.DataFrame(out).set_index("date")
    stats = {k: st for k in ("ev_ebitda", "pe") if (st := _stats(series[k]))}
    if not stats:
        return None
    last = hist.iloc[-1]
    implied: dict[str, dict[str, float]] = {}
    if "ev_ebitda" in stats and pd.notna(last["ebitda"]) and last["ebitda"] > 0 and shares_now:
        def per_share(m: float) -> float:
            return float((m * float(last["ebitda"]) - net_debt_now - minorities_now) / shares_now)
        st = stats["ev_ebitda"]
        implied["ev_ebitda"] = {"per_share": per_share(st["median"]), "low": per_share(st["p25"]), "high": per_share(st["p75"])}
    if "pe" in stats and pd.notna(last["eps"]) and last["eps"] > 0:
        eps = float(last["eps"]) / fx
        st = stats["pe"]
        implied["pe"] = {"per_share": st["median"] * eps, "low": st["p25"] * eps, "high": st["p75"] * eps}
    return MultipleHistory(series=series, stats=stats, implied=implied)
