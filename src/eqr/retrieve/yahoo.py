"""Yahoo Finance client (via ``yfinance``).

The *retrieve* phase: pull raw statements, prices, estimates and reference data
for the target company and its peers. Nothing here is interpreted; that is the
job of ``eqr.analyze``.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .cache import DiskCache

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class Snapshot:
    """Raw data for one ticker as returned by Yahoo Finance."""

    ticker: str
    info: dict[str, Any] = field(default_factory=dict)
    income: pd.DataFrame | None = None
    balance: pd.DataFrame | None = None
    cashflow: pd.DataFrame | None = None
    quarterly_income: pd.DataFrame | None = None
    prices: pd.DataFrame | None = None
    revenue_estimate: pd.DataFrame | None = None
    earnings_estimate: pd.DataFrame | None = None
    price_targets: dict[str, Any] = field(default_factory=dict)
    recommendations: pd.DataFrame | None = None

    # ------------------------------------------------------------- convenience
    @property
    def currency(self) -> str:
        return str(self.info.get("financialCurrency") or self.info.get("currency") or "USD")

    @property
    def price_currency(self) -> str:
        return str(self.info.get("currency") or self.currency)

    @property
    def name(self) -> str:
        return str(self.info.get("longName") or self.info.get("shortName") or self.ticker)

    @property
    def price(self) -> float | None:
        for key in ("currentPrice", "regularMarketPrice", "previousClose"):
            v = self.info.get(key)
            if v:
                return float(v)
        if self.prices is not None and len(self.prices):
            return float(self.prices["Close"].dropna().iloc[-1])
        return None

    @property
    def shares_outstanding(self) -> float | None:
        v = self.info.get("sharesOutstanding") or self.info.get("impliedSharesOutstanding")
        return float(v) if v else None

    @property
    def market_cap(self) -> float | None:
        v = self.info.get("marketCap")
        if v:
            return float(v)
        if self.price and self.shares_outstanding:
            return self.price * self.shares_outstanding
        return None

    @property
    def officers(self) -> list[dict[str, str]]:
        out = []
        for o in self.info.get("companyOfficers", []) or []:
            name = " ".join(str(o.get("name", "")).split())
            title = str(o.get("title", ""))
            if name:
                out.append({"name": name, "title": title})
        return out


def _safe(fn, default=None):
    try:
        value = fn()
    except Exception as exc:  # network / parsing errors must never kill a run
        log.debug("yfinance call failed: %s", exc)
        return default
    if isinstance(value, pd.DataFrame) and value.empty:
        return default
    return value


def _ticker(symbol: str):
    import yfinance as yf

    return yf.Ticker(symbol)


def fetch_snapshot(
    symbol: str,
    cache: DiskCache | None = None,
    *,
    with_estimates: bool = True,
    price_period: str = "5y",
    price_interval: str = "1wk",
) -> Snapshot:
    """Fetch everything we need for one ticker (cached)."""
    cache = cache or DiskCache(enabled=False)
    key = f"snapshot_{symbol}_{price_period}_{price_interval}_{int(with_estimates)}"

    def produce() -> Snapshot:
        t = _ticker(symbol)
        snap = Snapshot(ticker=symbol)
        snap.info = _safe(lambda: dict(t.info), {}) or {}
        snap.income = _safe(lambda: t.income_stmt)
        snap.balance = _safe(lambda: t.balance_sheet)
        snap.cashflow = _safe(lambda: t.cashflow)
        snap.quarterly_income = _safe(lambda: t.quarterly_income_stmt)
        snap.prices = _safe(lambda: t.history(period=price_period, interval=price_interval, auto_adjust=True))
        if with_estimates:
            snap.revenue_estimate = _safe(lambda: t.revenue_estimate)
            snap.earnings_estimate = _safe(lambda: t.earnings_estimate)
            snap.price_targets = _safe(lambda: dict(t.analyst_price_targets), {}) or {}
            snap.recommendations = _safe(lambda: t.recommendations_summary)
        return snap

    snap = cache.get_or(key, produce)
    if not snap.info and snap.income is None:
        raise RuntimeError(f"No data returned from Yahoo Finance for '{symbol}'. Check the ticker.")
    return snap


@dataclass
class Extras:
    """Data that ages quickly and is fetched separately from the statements snapshot.

    ``quarterly_balance`` gives the latest net debt; ``calendar`` the next results and ex-dividend
    dates; ``eps_trend`` / ``eps_revisions`` how consensus EPS has moved over the last 90 days.
    """

    ticker: str
    quarterly_balance: pd.DataFrame | None = None
    calendar: dict[str, Any] = field(default_factory=dict)
    eps_trend: pd.DataFrame | None = None
    eps_revisions: pd.DataFrame | None = None
    dividends: pd.Series | None = None


def fetch_extras(symbol: str, cache: DiskCache | None = None, *, full: bool = True) -> Extras:
    """Latest quarterly balance sheet, plus (``full``) calendar, estimate revisions and dividends."""
    cache = cache or DiskCache(enabled=False)

    def produce() -> Extras:
        t = _ticker(symbol)
        ex = Extras(ticker=symbol, quarterly_balance=_safe(lambda: t.quarterly_balance_sheet))
        if full:
            ex.calendar = _safe(lambda: dict(t.calendar), {}) or {}
            ex.eps_trend = _safe(lambda: t.eps_trend)
            ex.eps_revisions = _safe(lambda: t.eps_revisions)
            div = _safe(lambda: t.dividends)
            ex.dividends = div if isinstance(div, pd.Series) and len(div) else None
        return ex

    return cache.get_or(f"extras_{symbol}_{int(full)}", produce)


def fetch_prices(symbol: str, cache: DiskCache | None = None, period: str = "5y", interval: str = "1wk") -> pd.DataFrame | None:
    cache = cache or DiskCache(enabled=False)
    key = f"prices_{symbol}_{period}_{interval}"
    return cache.get_or(key, lambda: _safe(lambda: _ticker(symbol).history(period=period, interval=interval, auto_adjust=True)))


def fetch_fx(from_ccy: str, to_ccy: str, cache: DiskCache | None = None) -> float:
    """Spot FX rate ``from_ccy`` -> ``to_ccy`` (1.0 when equal or unavailable)."""
    from_ccy, to_ccy = from_ccy.upper(), to_ccy.upper()
    if from_ccy == "GBP" and to_ccy == "GBP":
        return 1.0
    if from_ccy == to_ccy:
        return 1.0
    cache = cache or DiskCache(enabled=False)
    pair = f"{from_ccy}{to_ccy}=X"

    def produce():
        hist = _safe(lambda: _ticker(pair).history(period="5d"))
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].dropna().iloc[-1])

    rate = cache.get_or(f"fx_{pair}", produce)
    if rate is None:
        # try the inverse pair
        inv = cache.get_or(f"fx_{to_ccy}{from_ccy}=X", lambda: _safe(lambda: _ticker(f"{to_ccy}{from_ccy}=X").history(period="5d")))
        if inv is not None and not getattr(inv, "empty", True):
            return 1.0 / float(inv["Close"].dropna().iloc[-1])
        log.warning("FX rate %s unavailable, using 1.0", pair)
        return 1.0
    return float(rate)
