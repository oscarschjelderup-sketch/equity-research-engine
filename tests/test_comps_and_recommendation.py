import pytest

from eqr.analyze import build_comps, build_forecast, build_history, compute_wacc, derive_drivers, football_field, recommend, run_dcf
from tests.conftest import make_snapshot


def _setup(config):
    snap = make_snapshot()
    peers = {"P1.OL": make_snapshot("P1.OL", price=40.0, trailing_pe=15.0, forward_pe=12.0),
             "P2.OL": make_snapshot("P2.OL", price=60.0, ebitda_margin=0.35, trailing_pe=21.0, forward_pe=16.0)}
    hist = build_history(snap, config)
    last = hist.iloc[-1]
    metrics = {"revenue": float(last["revenue"]), "ebitda": float(last["ebitda"]), "ebit": float(last["ebit"]), "eps": float(last["eps"])}
    comps = build_comps(config, snap, peers, {"NOK": 1.0}, company_metrics=metrics, net_debt=float(last["net_debt"]), minorities=0.0,
                        shares=100.0, price=50.0, forward_eps=3.2)
    return snap, hist, comps


def test_comps_table_and_implied_values(config):
    snap, hist, comps = _setup(config)
    assert len(comps.table) == 2
    assert set(comps.table["group"]) == {"Nordic"}
    assert "All|median" in comps.stats.index
    row = comps.table.set_index("ticker").loc["P1.OL"]
    # EV = 40 * 100m + net debt 200m = 4,200m ; adjusted EBITDA = 363 - 112.5 = 250.5
    assert row["ev"] == pytest.approx(4200.0)
    assert row["ev_ebitda"] == pytest.approx(4200.0 / 250.5)
    assert comps.company["ev_ebitda"] == pytest.approx((50 * 100 + 200) / 250.5)
    iv = comps.implied["ev_ebitda"]
    assert iv.per_share == pytest.approx((iv.multiple * 250.5 - 200) / 100)
    assert comps.implied["pe"].per_share == pytest.approx(comps.stats.loc["All|median", "pe"] * 2.9)
    assert comps.implied["fwd_pe"].per_share == pytest.approx(comps.stats.loc["All|median", "fwd_pe"] * 3.2)


def test_recommendation_thresholds_and_football_field(config):
    snap, hist, comps = _setup(config)
    drivers = derive_drivers(hist, config, snap)
    forecast = build_forecast(hist, drivers)
    wacc = compute_wacc(config, hist, market_cap=5000.0, total_debt=300.0, yahoo_beta=0.9, stock_prices=None, index_prices=None)
    assert 0.05 < wacc.wacc < 0.12
    dcf = run_dcf(forecast, wacc=wacc.wacc, terminal_growth=drivers.terminal_growth, net_debt=200.0, shares=100.0, price=50.0)
    rec = recommend(config, 50.0, dcf, comps, "NOK")
    assert rec.rating in {"BUY", "HOLD", "SELL"}
    expected = "BUY" if rec.upside >= 0.15 else ("SELL" if rec.upside <= -0.10 else "HOLD")
    assert rec.rating == expected
    assert rec.target_price == pytest.approx(round(dcf.value_per_share / 0.5) * 0.5)
    bars = football_field(snap.info, dcf, comps, 50.0)
    labels = [b.label for b in bars]
    assert labels[0] == "52-week range"
    assert any(b.label.startswith("DCF") for b in bars)
    assert all(b.high >= b.low for b in bars)


def test_blend_method(config):
    config.recommendation.tp_method = "blend"
    snap, hist, comps = _setup(config)
    drivers = derive_drivers(hist, config, snap)
    forecast = build_forecast(hist, drivers)
    dcf = run_dcf(forecast, wacc=0.09, terminal_growth=0.02, net_debt=200.0, shares=100.0, price=50.0)
    rec = recommend(config, 50.0, dcf, comps, "NOK")
    assert "DCF" in rec.method and "multiples" in rec.method
    assert rec.multiples_value is not None
