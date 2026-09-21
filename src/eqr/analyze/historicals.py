"""Standardise raw Yahoo statements into one canonical annual history table.

Lease treatment
---------------
IFRS 16 puts rent below EBITDA (as right-of-use depreciation + lease interest)
and books the lease liability as debt. That is fine for reported multiples, but
a perpetuity DCF on IFRS 16 cash flows wildly overstates value: the liability
only covers *existing* contracts while the cash flows assume clubs/stores are
used forever. Sell-side models therefore work on a pre-IFRS 16 ("operating")
basis. The engine reconstructs that basis from the statements:

* lease principal repaid  = the residual of financing cash flow after debt,
  equity, dividends, interest and other financing items (IFRS filers only —
  for US GAAP filers operating rent never left EBITDA, so the residual is ~0),
* lease interest          = average lease liability x ``lease_rate``,
* lease cost              = principal + interest  (≈ cash rent),
* EBITDA_adj = EBITDA - lease cost,  D&A_adj = D&A - principal (≈ ROU depreciation),
  EBIT_adj = EBIT - lease interest,  net debt_adj = net debt excluding leases.

``lease_treatment: financial`` keeps the reported IFRS 16 figures instead.

Output columns (money in ``units_divisor`` units, shares in millions) — the
canonical ``ebitda``/``da``/``ebit``/``net_debt``/``total_debt`` follow the
chosen treatment; ``*_reported`` and ``net_debt_incl_leases`` keep the other view.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import CompanyConfig
from ..retrieve import Snapshot

INCOME_MAP: dict[str, list[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "ebit": ["EBIT", "Operating Income", "Total Operating Income As Reported"],
    "operating_income": ["Operating Income"],
    "da": ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement"],
    "pretax": ["Pretax Income"],
    "tax": ["Tax Provision"],
    "net_income": ["Net Income Common Stockholders", "Net Income"],
    "eps": ["Diluted EPS", "Basic EPS"],
    "shares": ["Diluted Average Shares", "Basic Average Shares"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
}
BALANCE_MAP: dict[str, list[str]] = {
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "total_debt": ["Total Debt"],
    "lt_debt": ["Long Term Debt"],
    "st_debt": ["Current Debt"],
    "leases": ["Capital Lease Obligations"],
    "net_debt_yahoo": ["Net Debt"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "minority": ["Minority Interest"],
    "invested_capital": ["Invested Capital"],
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "current_lease": ["Current Capital Lease Obligation"],
    "cash_and_sti": ["Cash Cash Equivalents And Short Term Investments"],
}
CASHFLOW_MAP: dict[str, list[str]] = {
    "ocf": ["Operating Cash Flow"],
    "capex": ["Capital Expenditure"],
    "fcf_levered": ["Free Cash Flow"],
    "da_cf": ["Depreciation And Amortization"],
    "nwc_change": ["Change In Working Capital"],
    "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "financing_cf": ["Financing Cash Flow"],
    "net_debt_issuance": ["Net Issuance Payments Of Debt"],
    "debt_issuance": ["Issuance Of Debt"],
    "debt_repayment": ["Repayment Of Debt"],
    "net_equity_issuance": ["Net Common Stock Issuance"],
    "equity_issuance": ["Issuance Of Capital Stock"],
    "equity_repurchase": ["Repurchase Of Capital Stock"],
    "interest_paid_cff": ["Interest Paid Cff"],
    "other_financing": ["Net Other Financing Charges"],
}
MONEY_COLUMNS = [c for m in (INCOME_MAP, BALANCE_MAP, CASHFLOW_MAP) for c in m if c not in {"eps", "shares"}]
ALL_COLUMNS = [c for m in (INCOME_MAP, BALANCE_MAP, CASHFLOW_MAP) for c in m]


def _series(df: pd.DataFrame | None, names: list[str]) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            s = df.loc[name]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            s = pd.to_numeric(s, errors="coerce")
            if s.notna().any():
                return s
    return None


def extract_fields(snap: Snapshot) -> pd.DataFrame:
    """Raw statement fields by fiscal year (native currency units)."""
    frames: dict[str, pd.Series] = {}
    for mapping, df in ((INCOME_MAP, snap.income), (BALANCE_MAP, snap.balance), (CASHFLOW_MAP, snap.cashflow)):
        if df is None:
            continue
        for key, names in mapping.items():
            s = _series(df, names)
            if s is None:
                continue
            s = s.copy()
            s.index = [pd.Timestamp(c).year for c in s.index]
            s = s[~s.index.duplicated(keep="first")]
            frames[key] = s
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames).sort_index()
    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df


def add_lease_adjustments(df: pd.DataFrame, lease_rate: float) -> pd.DataFrame:
    """Add lease_principal / lease_interest / lease_cost and *_adj columns (any units)."""
    d = df.copy()
    z = lambda c: d[c].fillna(0.0)  # noqa: E731
    net_debt_iss = d["net_debt_issuance"].fillna(z("debt_issuance") + z("debt_repayment"))
    net_eq_iss = d["net_equity_issuance"].fillna(z("equity_issuance") + z("equity_repurchase"))
    residual = z("financing_cf") - net_debt_iss.fillna(0) - net_eq_iss.fillna(0) - z("dividends") - z("interest_paid_cff") - z("other_financing")
    principal = (-residual).where(d["financing_cf"].notna(), 0.0)
    leases = d["leases"].fillna(0.0)
    avg_leases = leases.rolling(2, min_periods=1).mean()
    principal = principal.clip(lower=0.0, upper=leases * 0.6).where(leases > 0, 0.0)
    interest = (avg_leases * lease_rate).where(leases > 0, 0.0)
    if "interest_expense" in d:
        interest = np.minimum(interest, d["interest_expense"].abs().fillna(np.inf) * 0.8)
    d["lease_principal"] = principal
    d["lease_interest"] = interest
    d["lease_cost"] = principal + interest
    return d


def _fill_basics(d: pd.DataFrame) -> pd.DataFrame:
    d["da"] = d["da"].fillna(d["da_cf"].abs())
    d["ebit"] = d["ebit"].fillna(d["operating_income"])
    d["ebitda"] = d["ebitda"].fillna(d["ebit"] + d["da"])
    d["capex"] = -d["capex"].abs()
    d["nwc_change"] = d["nwc_change"].fillna(0.0)
    d["interest_expense"] = d["interest_expense"].abs()
    d["leases"] = d["leases"].fillna(0.0)
    d["debt_ex_leases"] = (d["lt_debt"].fillna(0) + d["st_debt"].fillna(0)).where(
        d["lt_debt"].notna() | d["st_debt"].notna(), d["total_debt"] - d["leases"]
    )
    d["total_debt"] = d["total_debt"].fillna(d["debt_ex_leases"] + d["leases"])
    d["cash"] = d["cash"].fillna(0.0)
    d["net_debt_incl_leases"] = d["total_debt"] - d["cash"]
    d["net_debt_ex_leases"] = d["net_debt_yahoo"].fillna(d["debt_ex_leases"] - d["cash"])
    # operating net working capital = (current assets - cash & investments) - (current liabilities - short-term debt & leases)
    liquid = d["cash_and_sti"].fillna(d["cash"])
    d["nwc_level"] = (d["current_assets"] - liquid) - (d["current_liabilities"] - d["st_debt"].fillna(0.0) - d["current_lease"].fillna(0.0))
    return d


def apply_treatment(d: pd.DataFrame, treatment: str) -> pd.DataFrame:
    """Set canonical ebitda/da/ebit/net_debt/total_debt according to lease treatment."""
    d["ebitda_reported"] = d["ebitda"]
    d["da_reported"] = d["da"]
    d["ebit_reported"] = d["ebit"]
    if treatment == "operating":
        d["ebitda"] = d["ebitda_reported"] - d["lease_cost"]
        d["da"] = (d["da_reported"] - d["lease_principal"]).clip(lower=0.0)
        d["ebit"] = d["ebitda"] - d["da"]
        d["net_debt"] = d["net_debt_ex_leases"]
        d["debt_for_wacc"] = d["debt_ex_leases"]
        d["interest_ex_leases"] = (d["interest_expense"] - d["lease_interest"]).clip(lower=0.0)
    else:
        d["net_debt"] = d["net_debt_incl_leases"]
        d["debt_for_wacc"] = d["total_debt"]
        d["interest_ex_leases"] = d["interest_expense"]
    return d


def build_history(snap: Snapshot, cfg: CompanyConfig, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """Canonical history table in reporting units (see module docstring)."""
    raw = extract_fields(snap)
    if raw.empty:
        raise ValueError(f"No financial statements for {snap.ticker}")
    div = float(cfg.units_divisor)
    h = raw.copy()
    for col in h.columns:
        if col in MONEY_COLUMNS:
            h[col] = h[col] / div
    h["shares"] = h["shares"] / 1e6

    if extra is not None and not extra.empty:
        for col in extra.columns:
            for year, value in extra[col].items():
                if pd.notna(value):
                    h.loc[int(year), col] = float(value)
        h = h.sort_index()
        for col in ALL_COLUMNS:
            if col not in h.columns:
                h[col] = np.nan

    h = h[h["revenue"].notna() & (h["revenue"] > 0)].copy()
    if h.empty:
        raise ValueError(f"No usable annual revenue history for {snap.ticker}")

    h = _fill_basics(h)
    h = add_lease_adjustments(h, cfg.assumptions.lease_rate)
    h = apply_treatment(h, cfg.assumptions.lease_treatment)

    # --- derived metrics ----------------------------------------------------
    h["growth"] = h["revenue"].pct_change()
    h["ebitda_margin"] = h["ebitda"] / h["revenue"]
    h["ebit_margin"] = h["ebit"] / h["revenue"]
    h["ebitda_margin_reported"] = h["ebitda_reported"] / h["revenue"]
    eff = (h["tax"] / h["pretax"]).where(h["pretax"] > 0)
    h["tax_rate_eff"] = eff.clip(lower=0.0, upper=0.90)  # petroleum tax regimes run at 70-80%
    fallback_tax = cfg.assumptions.tax_rate if cfg.assumptions.tax_rate is not None else cfg.assumptions.statutory_tax_rate
    h["tax_rate_used"] = h["tax_rate_eff"].fillna(fallback_tax)
    h["nopat"] = h["ebit"] * (1 - h["tax_rate_used"])
    h["nopat_margin"] = h["nopat"] / h["revenue"]
    h["net_margin"] = h["net_income"] / h["revenue"]
    h["da_pct"] = h["da"] / h["revenue"]
    h["capex_pct"] = -h["capex"] / h["revenue"]
    h["nwc_pct"] = h["nwc_change"] / h["revenue"]
    h["nwc_pct_of_revenue"] = h["nwc_level"] / h["revenue"]
    h["lease_cost_pct"] = h["lease_cost"] / h["revenue"]
    h["ufcf"] = h["nopat"] + h["da"] + h["capex"] + h["nwc_change"]
    h["ufcf_margin"] = h["ufcf"] / h["revenue"]
    h["fcf_conversion"] = h["ufcf"] / h["ebitda"]
    h["nd_to_ebitda"] = h["net_debt"] / h["ebitda"]
    h["roe"] = h["net_income"] / h["equity"]
    ic = h["invested_capital"].fillna(h["equity"] + h["net_debt"])
    h["roic"] = h["nopat"] / ic
    h["payout"] = (h["dividends"].abs() / h["net_income"]).where(h["net_income"] > 0)

    h.index = h.index.astype(int)
    h.index.name = "year"
    return h


def last_fy_metrics(snap: Snapshot, treatment: str = "operating", lease_rate: float = 0.045) -> dict[str, float | None]:
    """Latest fiscal-year fundamentals for a peer (native units), on the chosen basis."""
    raw = extract_fields(snap)
    if raw.empty:
        return {}
    raw = raw[raw["revenue"].notna() & (raw["revenue"] > 0)].copy()
    if raw.empty:
        return {}
    d = _fill_basics(raw)
    d = add_lease_adjustments(d, lease_rate)
    d = apply_treatment(d, treatment)
    last = d.iloc[-1]
    prev = d.iloc[-2] if len(d) > 1 else None

    def g(key: str):
        v = last.get(key)
        return None if v is None or pd.isna(v) else float(v)

    rev_growth = None
    if prev is not None and pd.notna(prev.get("revenue")) and prev["revenue"] > 0:
        rev_growth = float(last["revenue"] / prev["revenue"] - 1)
    rev = float(last["revenue"])
    return {
        "fiscal_year": int(d.index[-1]),
        "revenue": rev,
        "ebitda": g("ebitda"),
        "ebit": g("ebit"),
        "ebitda_reported": g("ebitda_reported"),
        "ebit_reported": g("ebit_reported"),
        "net_income": g("net_income"),
        "eps": g("eps"),
        "net_debt": g("net_debt"),
        "net_debt_incl_leases": g("net_debt_incl_leases"),
        "lease_cost": g("lease_cost"),
        "minority": g("minority") or 0.0,
        "rev_growth": rev_growth,
        "ebitda_margin": (g("ebitda") / rev) if g("ebitda") is not None else None,
        "ebit_margin": (g("ebit") / rev) if g("ebit") is not None else None,
    }
