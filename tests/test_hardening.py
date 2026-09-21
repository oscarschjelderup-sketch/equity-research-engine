"""Guardrails added after running the engine across ~50 listed companies."""
import numpy as np
import pandas as pd
import pytest

import eqr.pipeline as pl
from eqr.analyze import build_comps, build_forecast, build_history, build_multiple_history, cross_check, derive_drivers, recommend, run_dcf
from eqr.config import CompanyConfig
from eqr.errors import UnsupportedCompanyError, check_supported, industry_caution
from eqr.retrieve import DiskCache
from tests.conftest import make_snapshot


# ------------------------------------------------------------------ sectors the FCFF framework does not describe
def test_banks_and_property_are_refused_with_a_reason():
    with pytest.raises(UnsupportedCompanyError, match="valued on equity"):
        check_supported("DNB Bank ASA", "Financial Services")
    with pytest.raises(UnsupportedCompanyError, match="net asset value"):
        check_supported("Entra ASA", "Real Estate")
    check_supported("SATS ASA", "Consumer Cyclical")  # no exception
    check_supported("DNB Bank ASA", "Financial Services", allow=True)  # explicit override


def test_pipeline_refuses_a_bank(config, monkeypatch):
    snap = make_snapshot()
    snap.info["sector"] = "Financial Services"
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snap)
    with pytest.raises(UnsupportedCompanyError):
        pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)


def test_industry_caution_is_a_warning_not_an_error():
    assert "petroleum tax" in industry_caution("Oil & Gas E&P")
    assert "freight-rate" in industry_caution("Marine Shipping")
    assert industry_caution("Leisure") is None and industry_caution(None) is None


# ------------------------------------------------------------------ tax rate from the accounts
def _with_tax(snapshot, rates):
    """Rewrite the tax provision so the effective rate per year (oldest first) is ``rates``."""
    inc = snapshot.income.copy()
    for col, rate in zip(sorted(inc.columns), rates):
        inc.loc["Tax Provision", col] = inc.loc["Pretax Income", col] * rate
    snapshot.income = inc
    return snapshot


def test_statutory_rate_when_the_accounts_are_close_to_it():
    cfg = CompanyConfig(ticker="T")
    snap = _with_tax(make_snapshot(), [0.21, 0.23, 0.24])
    d = derive_drivers(build_history(snap, cfg), cfg, snap)
    assert d.tax_rate == 0.22 and "statutory" in d.tax_source


def test_petroleum_style_tax_rate_is_taken_from_the_accounts():
    cfg = CompanyConfig(ticker="T")
    snap = _with_tax(make_snapshot(), [0.74, 0.78, 0.76])
    d = derive_drivers(build_history(snap, cfg), cfg, snap)
    assert d.tax_rate == pytest.approx(0.76, abs=0.015)
    assert any("Tax rate of" in n for n in d.notes)
    cfg.assumptions.tax_rate = 0.25  # an explicit config value always wins
    assert derive_drivers(build_history(snap, cfg), cfg, snap).tax_rate == 0.25


def test_tax_rate_is_profit_weighted_not_a_plain_average():
    """One low-profit year with a 90% rate must not drag the forecast tax rate up (the Yara case)."""
    cfg = CompanyConfig(ticker="T")
    snap = make_snapshot()
    inc = snap.income.copy()
    cols = sorted(inc.columns)
    inc.loc["Pretax Income", cols[1]] = 10e6  # a collapse in profit in the middle year ...
    inc.loc["Tax Provision", cols[1]] = 9e6  # ... taxed at 90%
    snap.income = inc
    d = derive_drivers(build_history(snap, cfg), cfg, snap)
    assert d.tax_rate == 0.22  # total tax / total profit is still ~23%


# ------------------------------------------------------------------ capex normalisation
def test_capex_normalises_towards_depreciation_in_an_investment_phase():
    cfg = CompanyConfig(ticker="T")
    snap = make_snapshot()
    cf = snap.cashflow.copy()
    cf.loc["Capital Expenditure"] = -300e6  # ~25% of revenue against D&A of ~2.5% (lease-adjusted)
    snap.cashflow = cf
    hist = build_history(snap, cfg)
    d = derive_drivers(hist, cfg, snap)
    assert d.capex_pct_path[0] == pytest.approx(d.capex_pct)
    assert d.capex_pct_path[-1] == pytest.approx(d.da_pct * 1.05)
    assert all(a >= b for a, b in zip(d.capex_pct_path, d.capex_pct_path[1:]))
    f = build_forecast(hist, d)
    assert -f.loc["TV", "capex"] / f.loc["TV", "revenue"] == pytest.approx(d.da_pct * 1.05)
    cfg.assumptions.capex_pct_terminal = 0.10
    assert derive_drivers(hist, cfg, snap).capex_pct_path[-1] == pytest.approx(0.10)


def test_asset_light_capex_is_left_alone(snapshot):
    cfg = CompanyConfig(ticker="T")
    cfg.assumptions.capex_pct_revenue = 0.01
    d = derive_drivers(build_history(snapshot, cfg), cfg, snapshot)
    assert d.capex_pct_path == [0.01] * 6


# ------------------------------------------------------------------ not-meaningful valuations
def test_negative_equity_value_is_not_rated(config):
    snap = make_snapshot()
    hist = build_history(snap, config)
    forecast = build_forecast(hist, derive_drivers(hist, config, snap))
    dcf = run_dcf(forecast, wacc=0.09, terminal_growth=0.02, net_debt=1e6, shares=100.0, price=50.0)  # debt dwarfs the business
    comps = build_comps(config, snap, {}, {"NOK": 1.0}, company_metrics={"revenue": 1.0, "ebitda": 1.0, "ebit": 1.0, "eps": 1.0},
                        net_debt=1e6, minorities=0.0, shares=100.0, price=50.0)
    rec = recommend(config, 50.0, dcf, comps, "NOK", cost_of_equity=0.1, dps=1.0)
    assert rec.rating == "NOT RATED" and rec.target_price == 0.0 and "not meaningful" in rec.method


# ------------------------------------------------------------------ cross-check of the anchors
def test_cross_check_labels():
    high = cross_check(fair_value=100, target_price=108, multiples_value=95, consensus_target=110, n_analysts=6, currency="NOK")
    assert high.agreement == "high" and "anchors agree" in high.message
    low = cross_check(fair_value=160, target_price=170, multiples_value=100, consensus_target=105, n_analysts=3, currency="NOK")
    assert low.agreement == "low" and low.max_gap == pytest.approx(170 / 105 - 1)
    assert "hypothesis" in low.message and "3 analysts" in low.message
    medium = cross_check(fair_value=120, target_price=126, multiples_value=100, consensus_target=None, n_analysts=None, currency="NOK")
    assert medium.agreement == "medium" and medium.target_vs_consensus is None
    none = cross_check(fair_value=120, target_price=126, multiples_value=None, consensus_target=None, n_analysts=None, currency="NOK")
    assert none.agreement == "n/a"


# ------------------------------------------------------------------ own multiples through time
def test_multiple_history_pairs_prices_with_the_fiscal_year_known_at_the_time(config):
    snap = make_snapshot(years=(2021, 2022, 2023, 2024, 2025), revenue=(900.0, 1000.0, 1100.0, 1210.0, 1300.0), eps=(1.5, 2.0, 2.4, 2.9, 3.2))
    hist = build_history(snap, config)
    dates = pd.date_range("2023-01-02", "2026-09-14", freq="W-MON")
    prices = pd.DataFrame({"Close": np.linspace(40.0, 60.0, len(dates))}, index=dates)
    mh = build_multiple_history(hist, prices, fx=1.0, shares_now=100.0, net_debt_now=200.0, minorities_now=0.0)
    assert mh is not None and {"ev_ebitda", "pe"} <= set(mh.stats)
    first = mh.series.dropna().iloc[0]
    # on 2 Jan 2023 the 2022 accounts are not public yet (75-day lag): the multiple uses FY2021 earnings
    ebitda_2021 = float(hist.loc[2021, "ebitda"])
    assert first["ev_ebitda"] == pytest.approx((40.0 * 100.0 + 200.0) / ebitda_2021, rel=1e-6)
    st = mh.stats["ev_ebitda"]
    assert st["p25"] <= st["median"] <= st["p75"] and 0 <= st["percentile"] <= 1 and st["years"] > 3
    iv = mh.implied["ev_ebitda"]
    assert iv["per_share"] == pytest.approx((st["median"] * float(hist["ebitda"].iloc[-1]) - 200.0) / 100.0)
    assert build_multiple_history(hist, None, fx=1.0, shares_now=100.0, net_debt_now=0.0, minorities_now=0.0) is None


def test_recovery_year_multiples_are_dropped_from_the_band(config):
    snap = make_snapshot()
    hist = build_history(snap, config)
    hist.loc[hist.index[0], "ebitda"] = 1.0  # near-zero earnings -> a 4,000x multiple that must not enter the band
    dates = pd.date_range("2024-06-03", "2026-09-14", freq="W-MON")
    prices = pd.DataFrame({"Close": [50.0] * len(dates)}, index=dates)
    mh = build_multiple_history(hist, prices, fx=1.0, shares_now=100.0, net_debt_now=200.0, minorities_now=0.0)
    assert mh.series["ev_ebitda"].max() < 30
