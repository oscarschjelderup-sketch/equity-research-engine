import pytest

from eqr.analyze import build_history, last_fy_metrics
from eqr.config import CompanyConfig


def test_lease_adjustment_operating_basis(snapshot):
    cfg = CompanyConfig(ticker="TEST.OL")
    h = build_history(snapshot, cfg)
    assert list(h.index) == [2023, 2024, 2025]
    last = h.loc[2025]
    # lease principal = financing residual: -( -160 - (-10) - 0 - (-40) - (-20) - 0 ) = 90
    assert last["lease_principal"] == pytest.approx(90.0)
    assert last["lease_interest"] == pytest.approx(500.0 * 0.045)
    assert last["ebitda_reported"] == pytest.approx(1210.0 * 0.30)
    assert last["ebitda"] == pytest.approx(1210.0 * 0.30 - 90.0 - 22.5)
    assert last["da"] == pytest.approx(120.0 - 90.0)
    assert last["ebit"] == pytest.approx(last["ebitda"] - last["da"])
    # net debt excludes leases and matches Yahoo's own "Net Debt" line
    assert last["net_debt"] == pytest.approx(300.0 - 100.0)
    assert last["net_debt_incl_leases"] == pytest.approx(300.0 + 500.0 - 100.0)
    assert last["ufcf"] == pytest.approx(last["nopat"] + last["da"] + last["capex"] + last["nwc_change"])
    assert last["capex"] == pytest.approx(-60.0)
    assert h["growth"].iloc[1] == pytest.approx(0.10)


def test_financial_basis_keeps_reported_figures(snapshot):
    cfg = CompanyConfig(ticker="TEST.OL")
    cfg.assumptions.lease_treatment = "financial"
    h = build_history(snapshot, cfg)
    last = h.loc[2025]
    assert last["ebitda"] == pytest.approx(last["ebitda_reported"])
    assert last["net_debt"] == pytest.approx(700.0)
    assert last["debt_for_wacc"] == pytest.approx(800.0)


def test_last_fy_metrics_for_peers(snapshot):
    m = last_fy_metrics(snapshot, treatment="operating", lease_rate=0.045)
    assert m["fiscal_year"] == 2025
    assert m["revenue"] == pytest.approx(1210e6)
    assert m["rev_growth"] == pytest.approx(0.10)
    assert m["net_debt"] == pytest.approx(200e6)
    assert m["ebitda"] == pytest.approx((1210 * 0.30 - 112.5) * 1e6)
