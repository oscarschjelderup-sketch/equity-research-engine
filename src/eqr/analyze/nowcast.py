"""Nowcast of the fiscal year in progress from the quarters already reported.

Half-way through a year the first forecast year is half known. A margin path that starts from the
last annual margin ignores that; an analyst does not. The nowcast builds FY0 from what is reported:

    revenue FY0 = year-to-date revenue + remaining quarters of last year x (1 + g)
    EBITDA  FY0 = year-to-date EBITDA  + remaining revenue x (last year's margin in those quarters + the year-to-date margin change)

Using last year's *same quarters* for the rest of the year keeps the seasonality (Kid earns its
year in Q4); ``g`` is the consensus growth for FY0 where it exists, otherwise the year-to-date growth.
The year-to-date margin change is capped (default ±8pp) so a one-off quarter cannot rewrite the
year. Quarterly EBITDA is put on the model's lease basis by scaling the annual lease cost with
revenue, exactly as the LTM figures are.

The nowcast only moves the year-1 revenue growth and EBITDA margin drivers, which stay visible
inputs in the Excel model; it is off with ``assumptions.nowcast: false`` and silently absent when
Yahoo's quarters are missing or do not add up to the annual figures.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .ltm import TOLERANCE_DAYS, _match, _quarterly_lines

MARGIN_SHIFT_CAP = 0.08  # the most of a year-to-date margin change that is carried into the remaining quarters
DISTORTION_LIMIT = 0.20  # a larger year-to-date swing is treated as a one-off or a data error and the nowcast is refused


@dataclass
class Nowcast:
    fy0: int
    quarters_reported: int
    period_end: str
    ytd_revenue: float
    ytd_ebitda: float
    prior_ytd_revenue: float
    prior_ytd_ebitda: float
    remaining_prior_revenue: float
    remaining_prior_ebitda: float
    growth_ytd: float
    margin_ytd: float
    margin_prior_ytd: float
    growth_remaining: float
    growth_source: str
    margin_shift: float
    margin_shift_capped: bool
    revenue_fy0: float
    ebitda_fy0: float
    margin_fy0: float
    growth_fy0: float
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def nowcast_year(fy: dict, fy_end: pd.Timestamp, quarterly: pd.DataFrame | None, *, consensus_growth_fy0: float | None = None,
                 divisor: float = 1.0, treatment: str = "operating", growth_floor: float = -0.5, growth_cap: float = 0.5,
                 margin_cap: float = MARGIN_SHIFT_CAP) -> tuple[Nowcast | None, str]:
    """``fy``: last fiscal year in model units (revenue, ebitda, ebitda_reported, lease_cost). Returns (nowcast, reason when None)."""
    q = _quarterly_lines(quarterly)
    if q is None:
        return None, "no quarterly income statement"
    fy_rev, fy_ebitda, fy_ebitda_rep = fy.get("revenue"), fy.get("ebitda"), fy.get("ebitda_reported")
    if not fy_rev or fy_ebitda is None or fy_ebitda_rep is None:
        return None, "fiscal-year figures incomplete"
    dates = list(q.index)
    new = sorted(d for d in dates if d > fy_end + pd.Timedelta(days=TOLERANCE_DAYS))
    if not new:
        return None, "no quarter reported since the fiscal year-end"
    if len(new) >= 4:
        return None, "the fiscal year in progress is already fully reported: waiting for the annual accounts"
    prior = [_match(dates, d - pd.DateOffset(years=1)) for d in new]
    if any(p is None for p in prior):
        return None, "a comparable quarter from last year is missing"
    cols = ["revenue", "ebitda"]
    ytd, pri = q.loc[new, cols], q.loc[prior, cols]
    if ytd.isna().any().any() or pri.isna().any().any():
        return None, "quarterly EBITDA not reported"
    # Yahoo's quarterly and annual definitions sometimes differ: the last year's quarters must add up to its EBITDA
    fy_quarters = [_match(dates, fy_end - pd.DateOffset(months=3 * k)) for k in range(4)]
    if all(d is not None for d in fy_quarters) and q.loc[fy_quarters, "ebitda"].notna().all() and fy_ebitda_rep:
        if abs(float(q.loc[fy_quarters, "ebitda"].sum()) / divisor / fy_ebitda_rep - 1) > 0.05:
            return None, "quarterly EBITDA does not add up to the annual figure"
    lease_cost = float(fy.get("lease_cost") or 0.0) if treatment == "operating" else 0.0

    def adj(rev: float, ebitda_rep: float) -> float:
        return ebitda_rep - lease_cost * (rev / fy_rev)  # the annual lease cost, scaled with the period's revenue

    ytd_rev, ytd_e_rep = float(ytd["revenue"].sum()) / divisor, float(ytd["ebitda"].sum()) / divisor
    pri_rev, pri_e_rep = float(pri["revenue"].sum()) / divisor, float(pri["ebitda"].sum()) / divisor
    if ytd_rev <= 0 or pri_rev <= 0 or pri_rev >= fy_rev:
        return None, "year-to-date revenue implausible"
    ytd_e, pri_e = adj(ytd_rev, ytd_e_rep), adj(pri_rev, pri_e_rep)
    rem_rev = fy_rev - pri_rev
    rem_e = fy_ebitda - pri_e
    growth_ytd = ytd_rev / pri_rev - 1
    if consensus_growth_fy0 is not None and np.isfinite(consensus_growth_fy0):
        g_rem, g_src = float(consensus_growth_fy0), "consensus growth for the year"
    else:
        g_rem, g_src = growth_ytd, "year-to-date growth"
    g_rem = float(min(max(g_rem, growth_floor), growth_cap))
    m_ytd, m_pri = ytd_e / ytd_rev, pri_e / pri_rev
    shift_raw = m_ytd - m_pri
    if abs(shift_raw) > DISTORTION_LIMIT:
        # a 20pp swing in a half-year margin is an impairment, a disposal gain or a data error, not a run-rate: the reported
        # year-to-date EBITDA would flow straight into the year, so the whole nowcast is refused rather than capped
        return None, (f"year-to-date EBITDA margin of {m_ytd:.1%} against {m_pri:.1%} a year earlier looks distorted by one-offs or data; "
                      "the year is forecast from the annual accounts instead")
    # the cap scales with the margin: +1pp is a quarter of an IT reseller's margin but nothing for a rig owner
    cap = float(min(margin_cap, max(0.02, 0.25 * abs(m_pri))))
    shift = float(min(max(shift_raw, -cap), cap))
    rem_margin = float(min(max(rem_e / rem_rev + shift, -0.5), 0.95))
    rev0 = ytd_rev + rem_rev * (1 + g_rem)
    e0 = ytd_e + rem_rev * (1 + g_rem) * rem_margin
    if not (0.6 < rev0 / fy_rev < 1.8):
        return None, "nowcast revenue implausible against the fiscal year"
    end = max(new)
    n = len(new)
    fy0 = int((fy_end + pd.DateOffset(years=1)).year)
    note = (f"{fy0}E built on {n} reported quarter{'s' if n > 1 else ''} to {end:%b %Y}: year-to-date revenue {growth_ytd:+.1%} at a "
            f"{m_ytd:.1%} EBITDA margin ({m_pri:.1%} a year earlier); the remaining quarters at {g_rem:+.1%} growth ({g_src}) and last year's "
            f"seasonal margins plus the {shift * 100:+.1f}pp year-to-date margin change"
            + (f" (capped at ±{cap * 100:.1f}pp)" if abs(shift_raw) > cap else "") + ".")
    return Nowcast(fy0=fy0, quarters_reported=n, period_end=end.date().isoformat(), ytd_revenue=ytd_rev, ytd_ebitda=ytd_e,
                   prior_ytd_revenue=pri_rev, prior_ytd_ebitda=pri_e, remaining_prior_revenue=rem_rev, remaining_prior_ebitda=rem_e,
                   growth_ytd=float(growth_ytd), margin_ytd=float(m_ytd), margin_prior_ytd=float(m_pri), growth_remaining=g_rem, growth_source=g_src,
                   margin_shift=shift, margin_shift_capped=bool(abs(shift_raw) > cap), revenue_fy0=float(rev0), ebitda_fy0=float(e0),
                   margin_fy0=float(e0 / rev0), growth_fy0=float(rev0 / fy_rev - 1), note=note), ""
