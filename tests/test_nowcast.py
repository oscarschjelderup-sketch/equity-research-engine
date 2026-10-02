"""Nowcast of the fiscal year in progress from the reported quarters."""
from __future__ import annotations

import pandas as pd
import pytest

import eqr.pipeline as pl
from eqr.analyze import build_history, derive_drivers
from eqr.analyze.nowcast import nowcast_year
from eqr.retrieve import DiskCache
from tests.conftest import make_snapshot

FY_END = pd.Timestamp("2025-12-31")
M = 1e6


def _quarters(values: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """{quarter-end: (revenue, EBITDA)} in millions -> a Yahoo-like quarterly income statement (newest first)."""
    cols = sorted((pd.Timestamp(d) for d in values), reverse=True)
    return pd.DataFrame({c: {"Total Revenue": values[c.date().isoformat()][0] * M, "EBITDA": values[c.date().isoformat()][1] * M} for c in cols})


# The synthetic company (conftest): FY2025 revenue 1,210, reported EBITDA 363, lease cost 112.5 -> adjusted EBITDA 250.5.
FY = {"revenue": 1210.0, "ebitda": 250.5, "ebitda_reported": 363.0, "lease_cost": 112.5}
# Four flat quarters in 2025 (302.5 / 90.75 each), two stronger quarters in 2026 (330 / 105 each).
Q = {"2026-06-30": (330.0, 105.0), "2026-03-31": (330.0, 105.0), "2025-12-31": (302.5, 90.75), "2025-09-30": (302.5, 90.75),
     "2025-06-30": (302.5, 90.75), "2025-03-31": (302.5, 90.75)}


def test_nowcast_arithmetic_on_the_synthetic_quarters():
    nc, why = nowcast_year(FY, FY_END, _quarters(Q), divisor=M)
    assert nc is not None, why
    assert nc.quarters_reported == 2 and nc.fy0 == 2026 and nc.period_end == "2026-06-30"
    assert nc.growth_ytd == pytest.approx(660 / 605 - 1)
    ytd_adj = 210 - 112.5 * 660 / 1210                        # the annual lease cost, scaled with the period's revenue
    pri_adj = 181.5 - 112.5 * 605 / 1210
    assert nc.ytd_ebitda == pytest.approx(ytd_adj) and nc.prior_ytd_ebitda == pytest.approx(pri_adj)
    assert nc.margin_ytd == pytest.approx(ytd_adj / 660) and nc.margin_prior_ytd == pytest.approx(pri_adj / 605)
    assert nc.growth_source == "year-to-date growth"          # no consensus given
    rem_rev = 605 * (1 + nc.growth_ytd)
    rem_margin = (250.5 - pri_adj) / 605 + nc.margin_shift
    assert nc.revenue_fy0 == pytest.approx(660 + rem_rev)
    assert nc.ebitda_fy0 == pytest.approx(ytd_adj + rem_rev * rem_margin)
    assert nc.margin_fy0 == pytest.approx(nc.ebitda_fy0 / nc.revenue_fy0)
    assert not nc.margin_shift_capped


def test_consensus_growth_drives_the_remaining_quarters_and_the_margin_shift_is_capped():
    nc, _ = nowcast_year(FY, FY_END, _quarters(Q), consensus_growth_fy0=0.04, divisor=M)
    assert nc.growth_source == "consensus growth for the year" and nc.growth_remaining == pytest.approx(0.04)
    assert nc.revenue_fy0 == pytest.approx(660 + 605 * 1.04)
    hot = dict(Q, **{"2026-06-30": (330.0, 140.0), "2026-03-31": (330.0, 140.0)})   # +12pp: real, but no one extrapolates all of it
    nc, why = nowcast_year(FY, FY_END, _quarters(hot), divisor=M)
    assert nc is not None, why
    assert nc.margin_shift_capped
    assert nc.margin_shift == pytest.approx(min(0.08, max(0.02, 0.25 * nc.margin_prior_ytd)))
    assert nc.ytd_ebitda == pytest.approx(280 - 112.5 * 660 / 1210)                   # the reported half-year itself is taken as it is


def test_nowcast_refuses_bad_or_missing_quarters():
    assert nowcast_year(FY, FY_END, None, divisor=M)[0] is None
    only_old = {k: v for k, v in Q.items() if k < "2026"}
    assert "no quarter reported" in nowcast_year(FY, FY_END, _quarters(only_old), divisor=M)[1]
    no_prior = {k: v for k, v in Q.items() if k != "2025-06-30"}
    assert "comparable quarter" in nowcast_year(FY, FY_END, _quarters(no_prior), divisor=M)[1]
    off = dict(Q, **{"2025-12-31": (302.5, 200.0)})                                # the year's quarters no longer add up to the annual EBITDA
    assert "does not add up" in nowcast_year(FY, FY_END, _quarters(off), divisor=M)[1]
    full = dict(Q, **{"2026-09-30": (330.0, 105.0), "2026-12-31": (330.0, 105.0)})  # FY2026 fully reported: wait for the accounts
    assert "already fully reported" in nowcast_year(FY, FY_END, _quarters(full), divisor=M)[1]
    wrecked = dict(Q, **{"2026-06-30": (330.0, -400.0), "2026-03-31": (330.0, -400.0)})  # an impairment or a data error, not a run-rate
    assert "distorted" in nowcast_year(FY, FY_END, _quarters(wrecked), divisor=M)[1]


def test_nowcast_moves_only_year_one_of_the_drivers(config):
    snap = make_snapshot()
    hist = build_history(snap, config)
    base = derive_drivers(hist, config, snap)
    nc, _ = nowcast_year(FY, FY_END, _quarters(Q), divisor=M)
    d = derive_drivers(hist, config, snap, nowcast=nc)
    assert d.revenue_growth[0] == pytest.approx(nc.growth_fy0)
    assert d.revenue_growth[1:] == base.revenue_growth[1:]          # the path from year 2 keeps its anchor
    assert d.ebitda_margin[0] == pytest.approx(nc.margin_fy0)
    assert d.ebitda_margin[-1] == pytest.approx(base.ebitda_margin[-1])   # and lands on the same terminal margin
    assert d.nowcast["quarters_reported"] == 2 and any("built on 2 reported quarters" in n for n in d.notes)


def test_pipeline_uses_the_nowcast_and_can_switch_it_off(monkeypatch, config):
    snap = make_snapshot()
    snap.quarterly_income = _quarters(Q)
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snap)
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snap.prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)
    config.peers = []
    config.assumptions.valuation_date = "2026-09-30"
    on = pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)
    config.assumptions.nowcast = False
    off = pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)
    assert on.drivers.nowcast is not None and off.drivers.nowcast is None
    assert on.forecast["revenue"].iloc[0] == pytest.approx(on.drivers.nowcast["revenue_fy0"])
    assert on.dcf.value_per_share != pytest.approx(off.dcf.value_per_share)
