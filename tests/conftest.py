"""Shared fixtures: a synthetic Yahoo-like snapshot so tests run offline."""
from __future__ import annotations

import pandas as pd
import pytest

from eqr.config import CompanyConfig, PeerConfig
from eqr.retrieve import Snapshot


def make_snapshot(ticker="TEST.OL", *, years=(2023, 2024, 2025), revenue=(1000.0, 1100.0, 1210.0), ebitda_margin=0.30,
                  da=120.0, leases=500.0, lease_principal=90.0, debt=300.0, cash=100.0, price=50.0, shares=100e6,
                  currency="NOK", eps=(2.0, 2.4, 2.9), trailing_pe=17.0, forward_pe=14.0) -> Snapshot:
    """Statements in native units (millions -> we scale to full currency units like Yahoo)."""
    cols = [pd.Timestamp(f"{y}-12-31") for y in reversed(years)]  # Yahoo orders newest first
    m = 1e6
    revs = list(reversed(revenue))
    epss = list(reversed(eps))
    income = pd.DataFrame({
        c: {
            "Total Revenue": r * m, "EBITDA": r * ebitda_margin * m, "EBIT": (r * ebitda_margin - da) * m,
            "Reconciled Depreciation": da * m, "Pretax Income": (r * ebitda_margin - da - 30) * m,
            "Tax Provision": (r * ebitda_margin - da - 30) * 0.22 * m, "Net Income": (r * ebitda_margin - da - 30) * 0.78 * m,
            "Diluted EPS": e, "Diluted Average Shares": shares, "Interest Expense": 30 * m,
        } for c, r, e in zip(cols, revs, epss)
    })
    balance = pd.DataFrame({
        c: {
            "Cash And Cash Equivalents": cash * m, "Total Debt": (debt + leases) * m, "Long Term Debt": debt * m, "Current Debt": 0.0,
            "Capital Lease Obligations": leases * m, "Net Debt": (debt - cash) * m, "Stockholders Equity": 800 * m,
            "Invested Capital": 1000 * m,
        } for c in cols
    })
    cashflow = pd.DataFrame({
        c: {
            "Operating Cash Flow": 300 * m, "Capital Expenditure": -60 * m, "Free Cash Flow": 240 * m,
            "Depreciation And Amortization": da * m, "Change In Working Capital": 5 * m, "Cash Dividends Paid": -40 * m,
            "Financing Cash Flow": -(lease_principal + 40 + 20 + 10) * m, "Net Issuance Payments Of Debt": -10 * m,
            "Net Common Stock Issuance": 0.0, "Interest Paid Cff": -20 * m, "Net Other Financing Charges": 0.0,
        } for c in cols
    })
    dates = pd.date_range("2021-01-04", periods=260, freq="W-MON")
    prices = pd.DataFrame({"Close": [price * (1 + 0.001 * i) for i in range(len(dates))]}, index=dates)
    info = {"longName": f"{ticker} ASA", "currency": currency, "financialCurrency": currency, "marketCap": price * shares,
            "sharesOutstanding": shares, "currentPrice": price, "beta": 0.9, "trailingPE": trailing_pe, "forwardPE": forward_pe,
            "fiftyTwoWeekLow": price * 0.8, "fiftyTwoWeekHigh": price * 1.1, "sector": "Consumer", "industry": "Leisure",
            "country": "Norway", "companyOfficers": [{"name": "Test  Person", "title": "Chief Executive Officer"}]}
    return Snapshot(ticker=ticker, info=info, income=income, balance=balance, cashflow=cashflow, prices=prices)


@pytest.fixture(autouse=True)
def _offline_extras(monkeypatch):
    """The quarterly balance sheet, calendar and estimate revisions come from a second Yahoo call: keep every test offline."""
    import eqr.pipeline as pl
    from eqr.retrieve import Extras

    monkeypatch.setattr(pl, "fetch_extras", lambda symbol, cache=None, **kw: Extras(ticker=symbol))


@pytest.fixture
def snapshot() -> Snapshot:
    return make_snapshot()


@pytest.fixture
def config() -> CompanyConfig:
    cfg = CompanyConfig(ticker="TEST.OL", name="Test ASA", index="^TEST", units_label="NOKm")
    cfg.peers = [PeerConfig("P1.OL", "Peer One", "Nordic"), PeerConfig("P2.OL", "Peer Two", "Nordic")]
    return cfg
