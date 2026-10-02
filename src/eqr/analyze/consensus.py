"""Where our estimates differ from consensus, where consensus is moving, and what is coming up.

A sell-side case is judged on its *variant perception*: where the analyst's numbers differ from
the street and why. The engine lines up its own revenue and EPS forecasts with the Yahoo Finance
consensus for the current and next fiscal year, reads the 90-day EPS revision trend (estimate
momentum moves share prices), and lists the next dated events (results, ex-dividend).

Our revenue growth is anchored on consensus by default, so the revenue gap is small by
construction; the informative gap is EPS, which carries our margin, tax and financing view.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

YEAR_KEYS = ("0y", "+1y")


@dataclass
class EstimateComparison:
    year: int
    metric: str  # "Revenue" (model units) or "EPS" (listing currency)
    ours: float | None
    consensus: float | None
    low: float | None
    high: float | None
    n_analysts: int | None

    @property
    def diff(self) -> float | None:
        if self.ours is None or not self.consensus:
            return None
        return float(self.ours / self.consensus - 1)

    @property
    def outside_range(self) -> bool:
        return bool(self.ours is not None and self.low is not None and self.high is not None and not self.low <= self.ours <= self.high)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["diff"] = self.diff
        d["outside_range"] = self.outside_range
        return d


@dataclass
class Revision:
    year: int
    eps_now: float | None
    eps_90d_ago: float | None
    up_30d: int | None
    down_30d: int | None

    @property
    def change_90d(self) -> float | None:
        if self.eps_now is None or not self.eps_90d_ago or self.eps_90d_ago <= 0:
            return None
        return float(self.eps_now / self.eps_90d_ago - 1)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["change_90d"] = self.change_90d
        return d


@dataclass
class Catalyst:
    date: str
    event: str
    detail: str = ""


@dataclass
class ConsensusView:
    estimates: list[EstimateComparison] = field(default_factory=list)
    revisions: list[Revision] = field(default_factory=list)
    catalysts: list[Catalyst] = field(default_factory=list)
    momentum: str = "n.a."  # positive | negative | mixed | flat | n.a.
    aligned: bool = False  # Yahoo's "current year" matches our first forecast year
    note: str = ""

    def as_dict(self) -> dict:
        return {"estimates": [e.as_dict() for e in self.estimates], "revisions": [r.as_dict() for r in self.revisions],
                "catalysts": [asdict(c) for c in self.catalysts], "momentum": self.momentum, "aligned": self.aligned, "note": self.note}

    def get(self, metric: str, year: int) -> EstimateComparison | None:
        return next((e for e in self.estimates if e.metric == metric and e.year == year), None)


def _rows(df: pd.DataFrame | None) -> dict[str, pd.Series]:
    if df is None or df.empty:
        return {}
    return {str(i): r for i, r in df.iterrows()}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def momentum_label(revisions: list[Revision]) -> str:
    """Positive / negative when the 90-day change and the 30-day up/down count point the same way."""
    changes = [r.change_90d for r in revisions if r.change_90d is not None]
    ups = sum(r.up_30d or 0 for r in revisions)
    downs = sum(r.down_30d or 0 for r in revisions)
    if not changes and not (ups or downs):
        return "n.a."
    avg = float(np.mean(changes)) if changes else 0.0
    if avg > 0.02 and ups >= downs:
        return "positive"
    if avg < -0.02 and downs >= ups:
        return "negative"
    if abs(avg) <= 0.02 and ups == downs:
        return "flat"
    return "mixed"


def build_consensus_view(*, revenue_estimate: pd.DataFrame | None, earnings_estimate: pd.DataFrame | None,
                         eps_trend: pd.DataFrame | None, eps_revisions: pd.DataFrame | None, calendar: dict | None,
                         last_fy: int, last_fy_revenue: float, forecast_years: list[int], our_revenue: dict[int, float],
                         our_eps: dict[int, float | None], units_divisor: float, eps_to_listing: float, today: dt.date,
                         revenue_to_reporting: float = 1.0) -> ConsensusView:
    """``eps_to_listing`` converts a consensus EPS into the listing currency and ``revenue_to_reporting`` a consensus revenue into
    the reporting currency – both from ``multiples.estimate_currency``, because Yahoo's table can be in either currency."""
    view = ConsensusView()
    rev_rows, eps_rows = _rows(revenue_estimate), _rows(earnings_estimate)
    # Yahoo's "0y" is the fiscal year in progress; confirm with the year-ago revenue it quotes.
    r0 = rev_rows.get("0y")
    year_ago = _num(r0.get("yearAgoRevenue")) if r0 is not None else None
    units_divisor = units_divisor / revenue_to_reporting  # native table units -> model units in the reporting currency
    view.aligned = bool(year_ago and last_fy_revenue and abs(year_ago / units_divisor / last_fy_revenue - 1) < 0.03)
    if not view.aligned:
        view.note = "Consensus years could not be matched to our fiscal years; comparison omitted."
    else:
        for k, key in enumerate(YEAR_KEYS):
            year = last_fy + 1 + k
            if year not in forecast_years:
                continue
            rr = rev_rows.get(key)
            if rr is not None and _num(rr.get("avg")):
                view.estimates.append(EstimateComparison(
                    year, "Revenue", our_revenue.get(year), _num(rr.get("avg")) / units_divisor,
                    (_num(rr.get("low")) or 0) / units_divisor or None, (_num(rr.get("high")) or 0) / units_divisor or None,
                    int(_num(rr.get("numberOfAnalysts")) or 0) or None))
            er = eps_rows.get(key)
            if er is not None and _num(er.get("avg")) is not None:
                conv = lambda v: (v * eps_to_listing) if v is not None else None  # noqa: E731
                view.estimates.append(EstimateComparison(
                    year, "EPS", our_eps.get(year), conv(_num(er.get("avg"))), conv(_num(er.get("low"))), conv(_num(er.get("high"))),
                    int(_num(er.get("numberOfAnalysts")) or 0) or None))
        trend, revs = _rows(eps_trend), _rows(eps_revisions)
        for k, key in enumerate(YEAR_KEYS):
            t = trend.get(key)
            if t is None:
                continue
            rv = revs.get(key)
            conv = lambda v: (v * eps_to_listing) if v is not None else None  # noqa: E731
            view.revisions.append(Revision(
                last_fy + 1 + k, conv(_num(t.get("current"))), conv(_num(t.get("90daysAgo"))),
                int(_num(rv.get("upLast30days")) or 0) if rv is not None else None,
                int(_num(rv.get("downLast30days")) or 0) if rv is not None else None))
        view.momentum = momentum_label(view.revisions)

    cal = calendar or {}
    earnings = cal.get("Earnings Date")
    earnings = earnings if isinstance(earnings, list) else ([earnings] if earnings else [])
    for d in earnings[:1]:
        d = pd.Timestamp(d).date()
        if d >= today:
            rev_avg, eps_avg = _num(cal.get("Revenue Average")), _num(cal.get("Earnings Average"))
            parts = []
            if rev_avg:
                parts.append(f"consensus revenue {rev_avg / units_divisor:,.0f}")
            if eps_avg is not None:
                parts.append(f"EPS {eps_avg * eps_to_listing:,.2f}")
            view.catalysts.append(Catalyst(d.isoformat(), "Quarterly results", ", ".join(parts)))
    exd = cal.get("Ex-Dividend Date")
    if exd:
        d = pd.Timestamp(exd).date()
        if d >= today:
            view.catalysts.append(Catalyst(d.isoformat(), "Ex-dividend date"))
    view.catalysts.sort(key=lambda c: c.date)
    return view
