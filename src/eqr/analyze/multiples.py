"""Multiples in depth: calendarised forward estimates and the multiples regression.

Calendarisation
---------------
Consensus comes by fiscal year, and fiscal years differ (Clas Ohlson ends in April, most others in
December). "Next twelve months" (NTM) lines every company up on the same clock: with ``w`` = the share
of the fiscal year in progress that is still ahead at the valuation date,

    NTM = w x FY0 + (1 - w) x FY1

where FY0 is the fiscal year in progress and FY1 the one after. Yahoo's "0y" is FY0; it is used only
when the year-ago revenue it quotes matches the last reported fiscal year, so the years are known to line up.

Multiples regression
--------------------
A peer median assumes every peer deserves the same multiple. A regression of EV/EBITDA on the drivers
that should set it – expected revenue growth and EBITDA margin – gives a *fundamentals-justified*
multiple for the target, and splits its premium or discount to the median into the part the
fundamentals explain and the part they do not (the mispricing, or what the model is missing).
Ordinary least squares with an intercept; two regressors need at least six peers, one needs four.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ForwardEstimates:
    """Consensus for the fiscal year in progress (FY0) and the next (FY1), and the NTM blend.

    Revenue in native units of the **reporting** currency; EPS in the **listing** currency (what the share
    price is in), whatever currency Yahoo quoted the table in (``estimates_currency``).
    """

    fy0_end: str
    weight_fy0: float
    revenue_fy0: float | None
    revenue_fy1: float | None
    eps_fy0: float | None
    eps_fy1: float | None
    n_revenue: int | None
    n_eps: int | None
    estimates_currency: str = "reporting"  # the currency Yahoo's table turned out to be in: reporting | listing

    @property
    def revenue_ntm(self) -> float | None:
        return _blend(self.revenue_fy0, self.revenue_fy1, self.weight_fy0)

    @property
    def eps_ntm(self) -> float | None:
        return _blend(self.eps_fy0, self.eps_fy1, self.weight_fy0)

    @property
    def revenue_growth_fy1(self) -> float | None:
        if self.revenue_fy0 and self.revenue_fy1 and self.revenue_fy0 > 0:
            return float(self.revenue_fy1 / self.revenue_fy0 - 1)
        return None

    @property
    def eps_growth_fy1(self) -> float | None:
        if self.eps_fy0 and self.eps_fy1 and self.eps_fy0 > 0:
            return float(self.eps_fy1 / self.eps_fy0 - 1)
        return None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(revenue_ntm=self.revenue_ntm, eps_ntm=self.eps_ntm, revenue_growth_fy1=self.revenue_growth_fy1, eps_growth_fy1=self.eps_growth_fy1)
        return d


def _blend(a: float | None, b: float | None, w: float) -> float | None:
    if a is None or b is None:
        return None
    return float(w * a + (1 - w) * b)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def ntm_weight(fy_end: pd.Timestamp, valuation_date: dt.date) -> tuple[float, pd.Timestamp]:
    """Share of the fiscal year in progress still ahead at the valuation date, and that year's end."""
    fy0_end = pd.Timestamp(fy_end) + pd.DateOffset(years=1)
    remaining = (fy0_end.date() - valuation_date).days / 365.25
    return float(min(max(remaining, 0.0), 1.0)), fy0_end


def estimate_currency(revenue_estimate: pd.DataFrame | None, last_fy_revenue: float | None, fx_listing_to_reporting: float = 1.0,
                      tolerance: float = 0.03) -> tuple[str | None, float]:
    """Which currency Yahoo's estimate table is in, from the year-ago revenue it quotes against the reported fiscal year.

    Yahoo is inconsistent: Equinor, Mowi and Shell come in the reporting currency, Yara and Hafnia in the listing currency
    (NOK for USD reporters). Returns (``"reporting"`` | ``"listing"`` | None when the years do not line up, factor that turns
    the table's revenue into reporting-currency units); ``last_fy_revenue`` is in native reporting units.
    """
    if revenue_estimate is None or revenue_estimate.empty or not last_fy_revenue:
        return None, 1.0
    rows = {str(i): r for i, r in revenue_estimate.iterrows()}
    r0 = rows.get("0y")
    year_ago = _num(r0.get("yearAgoRevenue")) if r0 is not None else None
    if not year_ago:
        return None, 1.0
    if abs(year_ago / last_fy_revenue - 1) <= tolerance:
        return "reporting", 1.0
    fx = float(fx_listing_to_reporting or 1.0)
    if fx != 1.0 and abs(year_ago * fx / last_fy_revenue - 1) <= tolerance:
        return "listing", fx
    return None, 1.0


def consensus_forward(revenue_estimate: pd.DataFrame | None, earnings_estimate: pd.DataFrame | None, fy_end: pd.Timestamp | None,
                      valuation_date: dt.date, last_fy_revenue: float | None, tolerance: float = 0.03,
                      fx_listing_to_reporting: float = 1.0) -> ForwardEstimates | None:
    """Calendarised consensus in the model's currencies, or None when Yahoo's years cannot be matched to the reported fiscal year."""
    if fy_end is None or revenue_estimate is None or revenue_estimate.empty or "avg" not in revenue_estimate.columns:
        return None
    ccy, to_reporting = estimate_currency(revenue_estimate, last_fy_revenue, fx_listing_to_reporting, tolerance)
    if ccy is None:
        return None
    eps_to_listing = 1.0 if ccy == "listing" else 1.0 / float(fx_listing_to_reporting or 1.0)
    rows = {str(i): r for i, r in revenue_estimate.iterrows()}
    r0, r1 = rows.get("0y"), rows.get("+1y")
    w, fy0_end = ntm_weight(fy_end, valuation_date)
    erows = {str(i): r for i, r in earnings_estimate.iterrows()} if (earnings_estimate is not None and not earnings_estimate.empty) else {}
    e0, e1 = erows.get("0y"), erows.get("+1y")

    def avg(r, factor: float):
        v = _num(r.get("avg")) if r is not None else None
        return v * factor if (v is not None and v != 0) else None

    def n(r):
        v = _num(r.get("numberOfAnalysts")) if r is not None else None
        return int(v) if v else None

    return ForwardEstimates(fy0_end=fy0_end.date().isoformat(), weight_fy0=w, revenue_fy0=avg(r0, to_reporting), revenue_fy1=avg(r1, to_reporting),
                            eps_fy0=avg(e0, eps_to_listing), eps_fy1=avg(e1, eps_to_listing), n_revenue=n(r0), n_eps=n(e0), estimates_currency=ccy)


# --------------------------------------------------------------------------- regression
REGRESSORS = {"growth_reg": "expected revenue growth", "ebitda_margin": "EBITDA margin"}


@dataclass
class RegressionResult:
    multiple: str  # "ev_ebitda"
    n: int
    regressors: list[str]
    intercept: float
    coefficients: dict[str, float]
    r2: float
    resid_std: float
    target_inputs: dict[str, float]
    fitted_target: float
    actual_target: float | None
    peer_median: float | None
    implied_value_per_share: float | None
    low: float | None
    high: float | None
    fitted_peers: list[dict] = field(default_factory=list)
    note: str = ""

    @property
    def explained(self) -> float | None:
        """Premium (+) or discount (-) to the median that the fundamentals justify, as a share of the median."""
        return float(self.fitted_target / self.peer_median - 1) if self.peer_median else None

    @property
    def unexplained(self) -> float | None:
        """The part of the actual multiple the fundamentals do not explain, as a share of the fitted multiple."""
        return float(self.actual_target / self.fitted_target - 1) if (self.actual_target and self.fitted_target) else None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(explained=self.explained, unexplained=self.unexplained)
        return d


def multiples_regression(table: pd.DataFrame, target: dict, *, multiple: str = "ev_ebitda", ebitda: float | None = None,
                         net_debt: float = 0.0, minorities: float = 0.0, shares: float | None = None) -> RegressionResult | None:
    """OLS of the peers' ``multiple`` on growth and margin; ``target`` holds the target's growth_reg, ebitda_margin and the multiple."""
    if table is None or table.empty or multiple not in table:
        return None
    cols = [c for c in REGRESSORS if c in table]
    df = table[["ticker", "name", multiple, *cols]].copy()
    for c in [multiple, *cols]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[multiple])
    # a regressor that does not vary across the peers (or is missing for the target) cannot explain anything
    cols = [c for c in cols if df[c].notna().sum() >= 2 and df[c].dropna().std() > 1e-9 and target.get(c) is not None]
    for x_cols in ([c for c in cols if df[c].notna().sum() >= 6], [c for c in cols if df[c].notna().sum() >= 4][:1]):
        need = 6 if len(x_cols) == 2 else 4
        sub = df.dropna(subset=x_cols) if x_cols else df.iloc[0:0]
        if x_cols and len(sub) >= need and all(target.get(c) is not None for c in x_cols):
            break
    else:
        return None
    y = sub[multiple].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(sub))] + [sub[c].to_numpy(dtype=float) for c in x_cols])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    fitted = X @ beta
    resid = y - fitted
    ss_res, ss_tot = float(resid @ resid), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = max(len(sub) - len(x_cols) - 1, 1)
    resid_std = float(np.sqrt(ss_res / dof))
    t_in = {c: float(target[c]) for c in x_cols}
    fitted_t = float(beta[0] + sum(beta[i + 1] * t_in[c] for i, c in enumerate(x_cols)))
    actual = _num(target.get(multiple))
    med = float(sub[multiple].median())
    implied = low = high = None
    if ebitda and ebitda > 0 and shares:
        implied = (fitted_t * ebitda - net_debt - minorities) / shares
        low = ((fitted_t - resid_std) * ebitda - net_debt - minorities) / shares
        high = ((fitted_t + resid_std) * ebitda - net_debt - minorities) / shares
    peers = [{"ticker": t, "name": nm, "actual": float(a), "fitted": float(f), **{c: float(v) for c, v in zip(x_cols, xs)}}
             for t, nm, a, f, xs in zip(sub["ticker"], sub["name"], y, fitted, sub[x_cols].to_numpy(dtype=float))]
    note = (f"OLS of {multiple.replace('_', '/').upper()} on {' and '.join(REGRESSORS[c] for c in x_cols)} across {len(sub)} peers "
            f"(R² {r2:.2f}); the band is ± one residual standard deviation ({resid_std:.1f}x)")
    return RegressionResult(multiple=multiple, n=len(sub), regressors=x_cols, intercept=float(beta[0]),
                            coefficients={c: float(b) for c, b in zip(x_cols, beta[1:])}, r2=float(r2), resid_std=resid_std,
                            target_inputs=t_in, fitted_target=fitted_t, actual_target=actual, peer_median=med,
                            implied_value_per_share=implied, low=low, high=high, fitted_peers=peers, note=note)
