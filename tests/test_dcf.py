import numpy as np
import pandas as pd
import pytest

from eqr.analyze.dcf import run_dcf, value_per_share


def test_value_per_share_one_period():
    # PV(FCF) = 100/1.1 = 90.91 ; TV = 100/(0.10-0) = 1000, PV = 909.09 ; EV = 1000 ; equity = 800 ; 10 shares -> 80
    v = value_per_share([100.0], 0.10, 0.0, net_debt=200.0, shares=10.0)
    assert v == pytest.approx(80.0, abs=1e-9)


def test_run_dcf_matches_manual_and_grid_center():
    forecast = pd.DataFrame({"ufcf": [100.0, 110.0, 121.0], "ebitda": [200.0, 220.0, 242.0]}, index=[2026, 2027, 2028])
    forecast.loc["TV"] = [121.0 * 1.02, 242.0 * 1.02]
    res = run_dcf(forecast, wacc=0.08, terminal_growth=0.02, net_debt=100.0, shares=50.0, price=10.0)
    manual = value_per_share([100.0, 110.0, 121.0], 0.08, 0.02, 100.0, 50.0)
    assert res.value_per_share == pytest.approx(manual, rel=1e-9)
    assert res.sensitivity.shape == (7, 7)
    assert res.sensitivity.iloc[3, 3] == pytest.approx(res.value_per_share, rel=1e-6)
    assert res.upside == pytest.approx(res.value_per_share / 10.0 - 1)
    assert 0 < res.tv_share_of_ev < 1
    assert res.implied_exit_ev_ebitda == pytest.approx(res.terminal_value / 242.0)
    # more growth / lower WACC -> higher value (monotone grid)
    assert (np.diff(res.sensitivity.values, axis=0) > 0).all()
    assert (np.diff(res.sensitivity.values, axis=1) < 0).all()


def test_mid_year_convention_raises_value():
    a = value_per_share([100.0] * 5, 0.09, 0.02, 0.0, 1.0, mid_year=False)
    b = value_per_share([100.0] * 5, 0.09, 0.02, 0.0, 1.0, mid_year=True)
    assert b > a


def test_wacc_must_exceed_growth():
    forecast = pd.DataFrame({"ufcf": [100.0], "ebitda": [200.0]}, index=[2026])
    with pytest.raises(ValueError):
        run_dcf(forecast, wacc=0.02, terminal_growth=0.03, net_debt=0.0, shares=1.0)
    assert np.isnan(value_per_share([100.0], 0.02, 0.03, 0.0, 1.0))
