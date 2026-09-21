import pytest

from eqr.analyze import build_forecast, build_history, derive_drivers
from eqr.config import CompanyConfig


def test_explicit_growth_and_margin_target(snapshot):
    cfg = CompanyConfig(ticker="TEST.OL")
    cfg.assumptions.forecast_years = 4
    cfg.assumptions.revenue_growth = [0.10, 0.05]  # padded with the last value
    cfg.assumptions.ebitda_margin_target = 0.25
    cfg.assumptions.terminal_growth = 0.02
    h = build_history(snapshot, cfg)
    d = derive_drivers(h, cfg, snapshot)
    assert d.years == [2026, 2027, 2028, 2029]
    assert d.revenue_growth == [0.10, 0.05, 0.05, 0.05]
    assert d.ebitda_margin[-1] == pytest.approx(0.25)
    f = build_forecast(h, d)
    assert list(f.index) == [2026, 2027, 2028, 2029, "TV"]
    assert f.loc[2026, "revenue"] == pytest.approx(1210.0 * 1.10)
    assert f.loc[2027, "revenue"] == pytest.approx(1210.0 * 1.10 * 1.05)
    assert f.loc["TV", "ufcf"] == pytest.approx(f.loc[2029, "ufcf"] * 1.02)
    assert f.loc[2029, "ebitda"] == pytest.approx(f.loc[2029, "revenue"] * 0.25)
    assert (f["ufcf"] == f["nopat"] + f["da"] + f["capex"] + f["nwc_change"]).all()


def test_derived_growth_fades_to_terminal(snapshot):
    cfg = CompanyConfig(ticker="TEST.OL")
    cfg.assumptions.forecast_years = 5
    cfg.assumptions.terminal_growth = 0.02
    cfg.assumptions.use_consensus_growth = False
    h = build_history(snapshot, cfg)
    d = derive_drivers(h, cfg, snapshot)
    assert d.revenue_growth[0] == pytest.approx(0.10, abs=1e-6)  # 2-year CAGR of 10%
    assert d.revenue_growth[-1] == pytest.approx(0.02)
    assert all(a >= b for a, b in zip(d.revenue_growth, d.revenue_growth[1:]))
    assert "CAGR" in d.growth_anchor
