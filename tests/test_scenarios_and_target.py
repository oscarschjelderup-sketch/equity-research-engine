import math

import pytest

from eqr.analyze import (
    build_comps,
    build_forecast,
    build_history,
    derive_drivers,
    implied_terminal_growth,
    implied_wacc,
    recommend,
    reverse_dcf,
    run_dcf,
    run_scenarios,
    terminal_cash_flow,
    value_per_share,
)
from eqr.analyze.recommendation import _round_to
from eqr.config import CompanyConfig, Scenario
from tests.conftest import make_snapshot


def _case(cfg: CompanyConfig):
    snap = make_snapshot()
    hist = build_history(snap, cfg)
    drivers = derive_drivers(hist, cfg, snap)
    return snap, hist, drivers, build_forecast(hist, drivers)


def test_scenarios_are_ordered_and_base_matches_dcf():
    cfg = CompanyConfig(ticker="TEST.OL")
    snap, hist, drivers, forecast = _case(cfg)
    dcf = run_dcf(forecast, wacc=0.09, terminal_growth=drivers.terminal_growth, net_debt=200.0, shares=100.0, price=50.0)
    results, weighted = run_scenarios(hist, drivers, cfg, 0.09, net_debt=200.0, shares=100.0, minorities=0.0, price=50.0, ronic=None)
    by = {r.name: r for r in results}
    assert by["Bear"].value_per_share < by["Base"].value_per_share < by["Bull"].value_per_share
    assert by["Base"].value_per_share == pytest.approx(dcf.value_per_share, rel=1e-12)
    assert by["Bear"].wacc == pytest.approx(0.095) and by["Bull"].wacc == pytest.approx(0.085)
    expected = sum(r.probability * r.value_per_share for r in results)
    assert weighted == pytest.approx(expected)
    assert by["Bull"].revenue_cagr - by["Base"].revenue_cagr == pytest.approx(0.02, abs=1e-3)


def test_custom_scenarios_and_probability_normalisation():
    cfg = CompanyConfig(ticker="TEST.OL")
    cfg.scenarios = [Scenario("Down", 1.0, margin_shift=-0.03), Scenario("Up", 3.0, margin_shift=0.03)]
    _, hist, drivers, _ = _case(cfg)
    results, weighted = run_scenarios(hist, drivers, cfg, 0.09, net_debt=0.0, shares=100.0, minorities=0.0, price=50.0, ronic=None)
    down, up = results
    assert weighted == pytest.approx(0.25 * down.value_per_share + 0.75 * up.value_per_share)


def test_reverse_dcf_recovers_the_price():
    cfg = CompanyConfig(ticker="TEST.OL")
    _, hist, drivers, forecast = _case(cfg)
    explicit = forecast[forecast.index != "TV"]
    fcfs = [float(v) for v in explicit["ufcf"]]
    price = value_per_share(fcfs, 0.10, drivers.terminal_growth, 200.0, 100.0)  # the "market" discounts at 10%
    assert implied_wacc(fcfs, drivers.terminal_growth, 200.0, 100.0, 0.0, price) == pytest.approx(0.10, abs=1e-5)
    g = implied_terminal_growth(fcfs, 0.10, 200.0, 100.0, 0.0, price)
    assert g == pytest.approx(drivers.terminal_growth, abs=1e-5)
    rv = reverse_dcf(hist, drivers, cfg, 0.08, net_debt=200.0, shares=100.0, minorities=0.0, price=price, ronic=None)
    assert rv.implied_wacc == pytest.approx(0.10, abs=1e-5)
    assert rv.implied_margin_shift < 0  # at an 8% WACC the lower price must come from lower margins
    assert implied_wacc(fcfs, 0.02, 200.0, 100.0, 0.0, price=1e9) is None  # unreachable price -> no solution


def test_value_driver_terminal_value():
    # RONIC = WACC: new investment earns exactly its cost, so the terminal value is just next year's NOPAT capitalised
    # at WACC -- the (WACC - g) growth premium cancels out
    for g in (0.01, 0.03):
        tv = terminal_cash_flow(110.0, g, nopat_last=120.0, ronic=0.09) / (0.09 - g)
        assert tv == pytest.approx(120.0 * (1 + g) / 0.09, rel=1e-12)
    # a higher RONIC makes growth more valuable
    low = value_per_share([100.0, 105.0, 110.0], 0.09, 0.03, 0.0, 1.0, nopat_last=120.0, ronic=0.09)
    high = value_per_share([100.0, 105.0, 110.0], 0.09, 0.03, 0.0, 1.0, nopat_last=120.0, ronic=0.15)
    assert high > low
    # very high RONIC -> reinvestment need vanishes -> NOPAT perpetuity
    assert terminal_cash_flow(110.0, 0.02, nopat_last=120.0, ronic=1e9) == pytest.approx(120.0 * 1.02)
    # no RONIC -> Gordon growth on FCF
    assert terminal_cash_flow(110.0, 0.02) == pytest.approx(110.0 * 1.02)


def test_run_dcf_value_driver_flag(config):
    _, hist, drivers, forecast = _case(config)
    gordon = run_dcf(forecast, wacc=0.09, terminal_growth=0.02, net_debt=0.0, shares=100.0)
    vd = run_dcf(forecast, wacc=0.09, terminal_growth=0.02, net_debt=0.0, shares=100.0, terminal_method="value_driver", ronic=0.11)
    assert gordon.terminal_method == "gordon" and gordon.ronic is None
    assert vd.terminal_method == "value_driver" and vd.ronic == 0.11
    nopat_n = float(forecast[forecast.index != "TV"]["nopat"].iloc[-1])
    assert vd.terminal_fcf == pytest.approx(nopat_n * 1.02 * (1 - 0.02 / 0.11))
    assert vd.sensitivity.iloc[3, 3] == pytest.approx(vd.value_per_share, rel=1e-6)


def test_target_price_roll_forward_and_rating(config):
    snap, hist, drivers, forecast = _case(config)
    dcf = run_dcf(forecast, wacc=0.09, terminal_growth=0.02, net_debt=200.0, shares=100.0, price=50.0)
    comps = build_comps(config, snap, {}, {"NOK": 1.0}, company_metrics={"revenue": 1.0, "ebitda": 1.0, "ebit": 1.0, "eps": 1.0},
                        net_debt=200.0, minorities=0.0, shares=100.0, price=50.0)
    rec = recommend(config, 50.0, dcf, comps, "NOK", cost_of_equity=0.10, dps=2.0)
    assert rec.horizon_months == 12 and rec.fair_value == pytest.approx(dcf.value_per_share)
    unrounded = dcf.value_per_share * 1.10 - 2.0
    assert rec.target_price == pytest.approx(math.floor(unrounded / 0.5 + 0.5) * 0.5)
    assert rec.total_return == pytest.approx((rec.target_price + 2.0) / 50.0 - 1)
    assert rec.upside == pytest.approx(rec.target_price / 50.0 - 1)
    # rolling forward can be switched off
    config.recommendation.roll_forward = False
    flat = recommend(config, 50.0, dcf, comps, "NOK", cost_of_equity=0.10, dps=2.0)
    assert flat.horizon_months == 0 and flat.dps == 0.0
    assert flat.target_price == pytest.approx(math.floor(dcf.value_per_share / 0.5 + 0.5) * 0.5)


def test_rounding_matches_excel_mround():
    assert _round_to(2.25, 0.5) == 2.5  # Python's round() would give 2.0 (banker's rounding)
    assert _round_to(46.31, 0.5) == 46.5
    assert _round_to(46.2, 0.5) == 46.0
    assert _round_to(12.34, 0.0) == 12.34
