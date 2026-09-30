"""Valuation date and the stub period: the DCF is worth what it is worth *today*, not at the last year-end."""
from __future__ import annotations

import pandas as pd
import pytest

import eqr.pipeline as pl
from eqr.analyze.dcf import discount_periods, value_per_share
from eqr.config import CompanyConfig
from eqr.retrieve import DiskCache, Extras
from tests.conftest import make_snapshot


def test_no_offset_is_the_textbook_dcf():
    t, w = discount_periods(4)
    assert list(t) == [1, 2, 3, 4] and list(w) == [1, 1, 1, 1]
    t, w = discount_periods(4, mid_year=True)
    assert list(t) == [0.5, 1.5, 2.5, 3.5]


def test_stub_period_matches_the_closed_form():
    fcfs, wacc, g, v, b = [100.0] * 5, 0.10, 0.02, 0.5, 0.25
    expected = (100 * (1 - b) / 1.1 ** (1 - v)                       # only the part of year 1 not yet in net debt
                + sum(100 / 1.1 ** (i - v) for i in range(2, 6))     # later years discounted from the valuation date
                + 100 * 1.02 / 0.08 / 1.1 ** (5 - v))                # terminal value, N - v years away
    assert value_per_share(fcfs, wacc, g, 0.0, 1.0, valuation_offset=v, balance_offset=b) == pytest.approx(expected)


def test_a_full_elapsed_year_is_the_dcf_of_the_remaining_years():
    fcfs = [80.0, 95.0, 105.0, 110.0, 118.0]
    full = value_per_share(fcfs, 0.09, 0.02, 50.0, 10.0, valuation_offset=1.0, balance_offset=1.0)
    assert full == pytest.approx(value_per_share(fcfs[1:], 0.09, 0.02, 50.0, 10.0))


def test_balance_date_can_not_be_after_the_valuation_date():
    a = value_per_share([100.0] * 3, 0.1, 0.02, 0.0, 1.0, valuation_offset=0.3, balance_offset=0.8)
    b = value_per_share([100.0] * 3, 0.1, 0.02, 0.0, 1.0, valuation_offset=0.3, balance_offset=0.3)
    assert a == pytest.approx(b)


def _quarterly_balance(net_debt_m: float) -> pd.DataFrame:
    m = 1e6
    return pd.DataFrame({pd.Timestamp("2026-06-30"): {"Net Debt": net_debt_m * m, "Long Term Debt": (net_debt_m + 80) * m,
                                                      "Current Debt": 0.0, "Cash And Cash Equivalents": 80 * m,
                                                      "Total Debt": (net_debt_m + 580) * m, "Capital Lease Obligations": 500 * m}})


def test_pipeline_values_at_the_valuation_date_with_the_latest_net_debt(monkeypatch):
    snap = make_snapshot()
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snap)
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snap.prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)
    monkeypatch.setattr(pl, "fetch_extras", lambda symbol, cache, **kw: Extras(ticker=symbol, quarterly_balance=_quarterly_balance(150.0)))
    cfg = CompanyConfig(ticker="TEST.OL", name="Test ASA", index="^TEST", units_label="NOKm")
    cfg.assumptions.valuation_date = "2026-09-30"
    r = pl.run_analysis(cfg, DiskCache(enabled=False), progress=lambda m: None)
    d = r.dcf
    assert r.net_debt == pytest.approx(150.0) and r.latest.net_debt_date == "2026-06-30"
    assert d.valuation_offset == pytest.approx(273 / 365.25) and d.balance_offset == pytest.approx(181 / 365.25)
    assert d.fcf_weights[0] == pytest.approx(1 - 181 / 365.25)
    # everything that quotes a DCF value uses the same valuation date: grid centre, base scenario, reverse DCF
    k = len(d.sensitivity) // 2
    assert d.sensitivity.iloc[k, k] == pytest.approx(d.value_per_share, abs=1e-3)   # the grid rounds WACC to six decimals
    base = next(s for s in r.scenarios if s.name == "Base")
    assert base.value_per_share == pytest.approx(d.value_per_share)
    assert d.enterprise_value == pytest.approx(d.sum_pv_fcf + d.pv_terminal)
    # switching the stub off values the company at the balance-sheet date instead
    cfg.assumptions.stub_period = False
    r2 = pl.run_analysis(cfg, DiskCache(enabled=False), progress=lambda m: None)
    assert r2.dcf.valuation_offset == pytest.approx(r2.dcf.balance_offset)
