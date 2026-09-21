"""Cost of capital: CAPM cost of equity, market-implied cost of debt, WACC."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from ..config import CompanyConfig

SIZE_PREMIUM_TIERS = [(10e9, 0.0), (2e9, 0.0075), (0.5e9, 0.015), (0.0, 0.025)]  # market cap in USD -> premium


def auto_size_premium(market_cap_usd: float | None) -> tuple[float, str]:
    if market_cap_usd is None or not np.isfinite(market_cap_usd) or market_cap_usd <= 0:
        return 0.0, "size premium n.a. (market cap unknown)"
    for floor, premium in SIZE_PREMIUM_TIERS:
        if market_cap_usd >= floor:
            return premium, f"size premium {premium:.2%} (market cap USD {market_cap_usd / 1e9:.1f}bn)"
    return 0.0, ""


@dataclass
class WaccResult:
    risk_free: float
    equity_risk_premium: float
    beta_raw: float | None
    beta_used: float
    beta_source: str
    beta_r2: float | None
    size_premium: float
    cost_of_equity: float
    cost_of_debt_pretax: float
    cost_of_debt_source: str
    tax_rate: float
    cost_of_debt_after_tax: float
    equity_value: float
    debt_value: float
    weight_equity: float
    weight_debt: float
    wacc: float
    overridden: bool = False
    size_premium_source: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def regression_beta(stock: pd.Series, index: pd.Series, years: int = 3) -> tuple[float, float, int] | None:
    """OLS beta of stock returns on index returns (weekly, last ``years`` years)."""
    if stock is None or index is None or len(stock) < 30 or len(index) < 30:
        return None
    s = stock.dropna().copy()
    i = index.dropna().copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    i.index = pd.to_datetime(i.index).tz_localize(None).normalize()
    df = pd.concat([s.rename("s"), i.rename("i")], axis=1, join="inner").dropna()
    if len(df) < 30:
        return None
    cutoff = df.index.max() - pd.DateOffset(years=years)
    df = df[df.index >= cutoff]
    rets = np.log(df).diff().dropna()
    if len(rets) < 30 or rets["i"].var() == 0:
        return None
    cov = np.cov(rets["s"], rets["i"])
    beta = float(cov[0, 1] / cov[1, 1])
    corr = float(np.corrcoef(rets["s"], rets["i"])[0, 1])
    return beta, corr ** 2, int(len(rets))


def compute_wacc(
    cfg: CompanyConfig,
    hist: pd.DataFrame,
    *,
    market_cap: float,
    total_debt: float,
    yahoo_beta: float | None,
    stock_prices: pd.Series | None,
    index_prices: pd.Series | None,
    market_cap_usd: float | None = None,
) -> WaccResult:
    w = cfg.wacc
    a = cfg.assumptions
    # the interest tax shield is earned at the corporate rate, even when the operating tax rate is higher (petroleum tax)
    tax = float(a.tax_rate) if a.tax_rate is not None else float(a.statutory_tax_rate)
    if isinstance(w.size_premium, str):
        size_premium, size_src = auto_size_premium(market_cap_usd)
    else:
        size_premium, size_src = float(w.size_premium or 0.0), "size premium from config"

    # ---- beta ---------------------------------------------------------------
    beta_raw: float | None = None
    r2: float | None = None
    source = ""
    if w.beta_method == "manual" and w.beta is not None:
        beta_raw, source = float(w.beta), "manual"
    elif w.beta_method == "yahoo" and yahoo_beta:
        beta_raw, source = float(yahoo_beta), "Yahoo Finance"
    else:
        reg = regression_beta(stock_prices, index_prices, years=w.beta_years) if stock_prices is not None else None
        if reg is not None and reg[1] >= w.min_r2:
            beta_raw, r2, n = reg
            source = f"{w.beta_years}y weekly regression vs {cfg.index_name or cfg.index} (n={n}, R2={r2:.2f})"
        elif w.beta is not None:
            beta_raw, source = float(w.beta), "manual"
        elif yahoo_beta:
            beta_raw, source = float(yahoo_beta), "Yahoo Finance (5y monthly)"
            if reg is not None:
                r2 = reg[1]
                source += f"; regression vs {cfg.index_name or cfg.index} rejected (R2={reg[1]:.2f} < {w.min_r2:.2f})"
        else:
            beta_raw, source = 1.0, "default (1.0)"
    beta_used = beta_raw
    if w.blume_adjust and source not in {"manual"}:
        beta_used = 0.67 * beta_raw + 0.33
        source += ", Blume-adjusted"
    beta_used = float(min(max(beta_used, w.beta_floor), w.beta_cap))

    cost_of_equity = w.risk_free + beta_used * w.equity_risk_premium + size_premium

    # ---- cost of debt ---------------------------------------------------------
    if w.cost_of_debt_pretax is not None:
        kd, kd_src = float(w.cost_of_debt_pretax), "config"
    else:
        ie = hist["interest_ex_leases"].dropna()
        debt = hist["debt_for_wacc"].dropna()
        if len(ie) and len(debt) and float(debt.tail(2).mean()) > 0:
            kd = float(ie.iloc[-1] / debt.tail(2).mean())
            kd = float(min(max(kd, 0.02), 0.12))
            kd_src = "interest expense / average debt"
        else:
            kd, kd_src = w.risk_free + 0.02, "risk-free + 200bp"
    kd_after = kd * (1 - tax)

    # ---- weights ----------------------------------------------------------------
    e = max(float(market_cap), 0.0)
    d = max(float(total_debt), 0.0)
    if w.debt_weight is not None:
        wd = float(min(max(w.debt_weight, 0.0), 0.95))
    else:
        wd = d / (d + e) if (d + e) > 0 else 0.0
    we = 1 - wd
    wacc = we * cost_of_equity + wd * kd_after
    overridden = False
    if w.wacc_override is not None:
        wacc, overridden = float(w.wacc_override), True

    return WaccResult(
        risk_free=w.risk_free, equity_risk_premium=w.equity_risk_premium, beta_raw=beta_raw, beta_used=beta_used,
        beta_source=source, beta_r2=r2, size_premium=size_premium, cost_of_equity=cost_of_equity,
        cost_of_debt_pretax=kd, cost_of_debt_source=kd_src, tax_rate=tax, cost_of_debt_after_tax=kd_after,
        equity_value=e, debt_value=d, weight_equity=we, weight_debt=wd, wacc=float(wacc), overridden=overridden,
        size_premium_source=size_src,
    )
