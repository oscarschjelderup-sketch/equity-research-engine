"""Last twelve months (LTM) and the latest balance sheet.

Annual accounts can be almost a year old by the time a case is written: in September the
"last fiscal year" is the previous December. Trading multiples and the equity bridge should use
the latest reported figures, so the engine builds last-twelve-months figures from the quarterly
income statement,

    LTM = sum of the four latest quarters                       (when all four are reported)
        = last fiscal year + year-to-date - same period last year (otherwise)

and takes net debt and minorities from the latest quarterly
balance sheet. Lease adjustments are carried over from the fiscal year (lease cost scaled with
LTM revenue), so LTM figures sit on the same basis as the model.

LTM falls back to the fiscal year, with the reason recorded, when a quarter is missing, when
Yahoo's quarterly definitions do not add up to the annual figure, or when the result is implausible.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .historicals import _series

TOLERANCE_DAYS = 20
Q_INCOME = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "ebit": ["EBIT", "Operating Income"],
    "da": ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"],
}


@dataclass
class LatestFigures:
    """LTM income figures (model lease basis) and the latest balance sheet, in model units."""

    basis: str  # "LTM Jun 2026" or "FY2025"
    period_end: str | None
    quarters_added: int
    revenue: float | None
    ebitda: float | None
    ebit: float | None
    net_debt: float | None
    net_debt_date: str | None
    minority: float | None
    fy_revenue: float | None = None
    fy_ebitda: float | None = None
    note: str = ""

    @property
    def is_ltm(self) -> bool:
        return self.quarters_added > 0

    def as_dict(self) -> dict:
        return asdict(self)


def _to_ts(c) -> pd.Timestamp:
    return pd.Timestamp(c).tz_localize(None) if pd.Timestamp(c).tzinfo else pd.Timestamp(c)


def _quarterly_lines(q: pd.DataFrame | None) -> pd.DataFrame | None:
    """Quarterly revenue / EBITDA / EBIT by quarter-end date (native units), newest first."""
    if q is None or q.empty:
        return None
    lines: dict[str, pd.Series] = {}
    for key, names in Q_INCOME.items():
        s = _series(q, names)
        if s is not None:
            s = s.copy()
            s.index = [_to_ts(c) for c in s.index]
            lines[key] = s
    if "revenue" not in lines:
        return None
    df = pd.DataFrame(lines)
    if "ebitda" not in df:
        df["ebitda"] = np.nan
    if "ebit" not in df:
        df["ebit"] = np.nan
    if "da" in df:
        df["ebitda"] = df["ebitda"].fillna(df["ebit"] + df["da"])
    return df.sort_index(ascending=False)


def _match(dates: list[pd.Timestamp], target: pd.Timestamp) -> pd.Timestamp | None:
    for d in dates:
        if abs((d - target).days) <= TOLERANCE_DAYS:
            return d
    return None


def ltm_income(fy: dict, fy_end: pd.Timestamp, quarterly: pd.DataFrame | None, *, divisor: float = 1.0,
               treatment: str = "operating") -> tuple[dict, str, str | None, int, str]:
    """LTM revenue / EBITDA / EBIT on the model basis.

    ``fy`` holds the last fiscal year in model units: revenue, ebitda_reported, ebit_reported, lease_cost, lease_interest.
    Returns (figures, basis label, period end, quarters added, note).
    """
    fy_label = f"FY{fy_end.year}"
    base = {"revenue": fy.get("revenue"), "ebitda": fy.get("ebitda"), "ebit": fy.get("ebit")}
    q = _quarterly_lines(quarterly)
    if q is None:
        return base, fy_label, None, 0, "no quarterly income statement"
    dates = list(q.index)
    new = [d for d in dates if d > fy_end + pd.Timedelta(days=TOLERANCE_DAYS)]
    if not new:
        return base, fy_label, None, 0, "no quarter reported since the fiscal year-end"
    fy_rev, fy_ebitda_rep, fy_ebit_rep = fy.get("revenue"), fy.get("ebitda_reported"), fy.get("ebit_reported")
    if not fy_rev or fy_ebitda_rep is None or fy_ebit_rep is None:
        return base, fy_label, None, 0, "fiscal-year figures incomplete"
    cols = ["revenue", "ebitda", "ebit"]
    end = max(new)

    # Yahoo's quarterly and annual definitions sometimes differ: when the last fiscal year's four
    # quarters are all present, they must add up to the annual EBITDA.
    fy_quarters = [_match(dates, fy_end - pd.DateOffset(months=3 * k)) for k in range(4)]
    if all(d is not None for d in fy_quarters) and fy_ebitda_rep and q.loc[fy_quarters, "ebitda"].notna().all():
        summed = float(q.loc[fy_quarters, "ebitda"].sum()) / divisor
        if abs(summed / fy_ebitda_rep - 1) > 0.05:
            return base, fy_label, None, 0, "quarterly EBITDA does not add up to the annual figure"

    # 1) the four latest quarters, when all are reported
    last4 = [_match(dates, end - pd.DateOffset(months=3 * k)) for k in range(4)]
    if all(d is not None for d in last4) and q.loc[last4, cols].notna().all().all():
        tot = q.loc[last4, cols].sum() / divisor
        rev, ebitda_rep, ebit_rep = float(tot["revenue"]), float(tot["ebitda"]), float(tot["ebit"])
        how = f"sum of the four quarters to {end:%b %Y}"
    else:
        # 2) fiscal year + year-to-date - same quarters last year
        prior = [_match(dates, d - pd.DateOffset(years=1)) for d in new]
        if any(p is None for p in prior):
            return base, fy_label, None, 0, "a comparable quarter from last year is missing"
        ytd, prev = q.loc[new], q.loc[prior]
        if ytd[cols].isna().any().any() or prev[cols].isna().any().any():
            return base, fy_label, None, 0, "quarterly EBITDA or EBIT not reported"
        delta = (ytd[cols].sum() - prev[cols].sum()) / divisor
        rev = fy_rev + float(delta["revenue"])
        ebitda_rep = fy_ebitda_rep + float(delta["ebitda"])
        ebit_rep = fy_ebit_rep + float(delta["ebit"])
        how = f"FY{fy_end.year} + {len(new)} quarter(s) to {end:%b %Y} - same quarter(s) of {end.year - 1}"

    if not (0.6 < rev / fy_rev < 1.8):
        return base, fy_label, None, 0, "LTM revenue implausible against the fiscal year"
    if fy_ebitda_rep > 0 and not (0.5 < ebitda_rep / fy_ebitda_rep < 2.0):
        return base, fy_label, None, 0, "LTM EBITDA implausible against the fiscal year"
    scale = rev / fy_rev
    if treatment == "operating":
        ebitda = ebitda_rep - (fy.get("lease_cost") or 0.0) * scale
        ebit = ebit_rep - (fy.get("lease_interest") or 0.0) * scale
    else:
        ebitda, ebit = ebitda_rep, ebit_rep
    return ({"revenue": rev, "ebitda": ebitda, "ebit": ebit}, f"LTM {end:%b %Y}", end.date().isoformat(), len(new), how)


def latest_balance(fy: dict, fy_end: pd.Timestamp, quarterly_balance: pd.DataFrame | None, *, divisor: float = 1.0,
                   treatment: str = "operating") -> tuple[float | None, float | None, str]:
    """Net debt (model basis) and minorities from the newest balance sheet; falls back to the fiscal year."""
    fy_nd, fy_mi = fy.get("net_debt"), fy.get("minority")
    fallback = (fy_nd, fy_mi, fy_end.date().isoformat())
    qb = quarterly_balance
    if qb is None or qb.empty:
        return fallback
    cols = sorted((_to_ts(c) for c in qb.columns), reverse=True)
    latest = cols[0]
    if latest <= fy_end + pd.Timedelta(days=TOLERANCE_DAYS):
        return fallback
    col = next(c for c in qb.columns if _to_ts(c) == latest)

    def val(names: list[str]) -> float | None:
        for n in names:
            if n in qb.index:
                v = pd.to_numeric(qb.loc[n, col], errors="coerce")
                if isinstance(v, pd.Series):
                    v = v.iloc[0]
                if pd.notna(v):
                    return float(v)
        return None

    cash = val(["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]) or 0.0
    total = val(["Total Debt"])
    leases = val(["Capital Lease Obligations"]) or 0.0
    lt, st = val(["Long Term Debt"]), val(["Current Debt"])
    debt_ex = ((lt or 0.0) + (st or 0.0)) if (lt is not None or st is not None) else (total - leases if total is not None else None)
    if treatment == "operating":
        nd = val(["Net Debt"])
        if nd is None and debt_ex is not None:
            nd = debt_ex - cash
    else:
        nd = (total - cash) if total is not None else ((debt_ex + leases - cash) if debt_ex is not None else None)
    if nd is None:
        return fallback
    mi = val(["Minority Interest"])
    return nd / divisor, (mi / divisor if mi is not None else fy_mi), latest.date().isoformat()


def latest_figures(fy: dict, fy_end: pd.Timestamp, quarterly_income: pd.DataFrame | None, quarterly_balance: pd.DataFrame | None, *,
                   divisor: float = 1.0, treatment: str = "operating", use_balance: bool = True) -> LatestFigures:
    inc, basis, end, n, note = ltm_income(fy, fy_end, quarterly_income, divisor=divisor, treatment=treatment)
    if use_balance:
        nd, mi, nd_date = latest_balance(fy, fy_end, quarterly_balance, divisor=divisor, treatment=treatment)
    else:
        nd, mi, nd_date = fy.get("net_debt"), fy.get("minority"), fy_end.date().isoformat()
    return LatestFigures(basis=basis, period_end=end, quarters_added=n, revenue=inc["revenue"], ebitda=inc["ebitda"], ebit=inc["ebit"],
                         net_debt=nd, net_debt_date=nd_date, minority=mi, fy_revenue=fy.get("revenue"), fy_ebitda=fy.get("ebitda"), note=note)
