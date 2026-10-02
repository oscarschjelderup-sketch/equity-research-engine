"""LTM figures, consensus comparison, bottom-up beta, value drivers, dividend and the research note."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

import eqr.pipeline as pl
from eqr.analyze.consensus import Revision, build_consensus_view, momentum_label
from eqr.analyze.ltm import latest_balance, ltm_income
from eqr.analyze.scenarios import value_drivers
from eqr.analyze.wacc import bottom_up_beta, relever, unlever
from eqr.retrieve import DiskCache
from tests.conftest import make_snapshot

FY_END = pd.Timestamp("2025-12-31")
FY = {"revenue": 1000.0, "ebitda": 250.0, "ebit": 150.0, "ebitda_reported": 300.0, "ebit_reported": 160.0,
      "lease_cost": 50.0, "lease_interest": 10.0, "net_debt": 200.0, "minority": 5.0}


def _quarters(values: dict[str, tuple[float, float, float]]) -> pd.DataFrame:
    """{date: (revenue, ebitda, ebit)} -> a Yahoo-like quarterly income statement (newest first)."""
    cols = sorted((pd.Timestamp(d) for d in values), reverse=True)
    return pd.DataFrame({c: {"Total Revenue": values[c.date().isoformat()][0], "EBITDA": values[c.date().isoformat()][1],
                             "EBIT": values[c.date().isoformat()][2]} for c in cols})


# ------------------------------------------------------------------ LTM
def test_ltm_is_the_sum_of_the_four_latest_quarters():
    q = _quarters({"2026-06-30": (270, 80, 42), "2026-03-31": (260, 75, 40), "2025-12-31": (255, 76, 41), "2025-09-30": (250, 74, 40)})
    inc, basis, end, n, how = ltm_income(FY, FY_END, q)
    assert basis == "LTM Jun 2026" and end == "2026-06-30" and n == 2 and "four quarters" in how
    scale = 1035 / 1000
    assert inc["revenue"] == pytest.approx(1035)
    assert inc["ebitda"] == pytest.approx(305 - 50 * scale)   # reported EBITDA less the lease cost, scaled with revenue
    assert inc["ebit"] == pytest.approx(163 - 10 * scale)     # reported EBIT less the lease interest


def test_ltm_falls_back_to_year_to_date_arithmetic_when_a_quarter_is_missing():
    # the September quarter is missing, so: FY + H1 2026 - H1 2025
    q = _quarters({"2026-06-30": (270, 80, 42), "2026-03-31": (260, 75, 40), "2025-12-31": (255, 76, 41),
                   "2025-06-30": (245, 73, 39), "2025-03-31": (240, 72, 38)})
    inc, basis, _, _, how = ltm_income(FY, FY_END, q)
    assert basis == "LTM Jun 2026" and how.startswith("FY2025 + 2 quarter(s)")
    assert inc["revenue"] == pytest.approx(1000 + 530 - 485)


def test_ltm_refuses_quarters_that_do_not_add_up_to_the_year():
    q = _quarters({"2026-06-30": (270, 80, 42), "2026-03-31": (260, 75, 40), "2025-12-31": (255, 100, 41), "2025-09-30": (250, 100, 40),
                   "2025-06-30": (245, 100, 39), "2025-03-31": (240, 100, 38)})   # 400 of quarterly EBITDA vs 300 annual
    inc, basis, _, n, how = ltm_income(FY, FY_END, q)
    assert basis == "FY2025" and n == 0 and "does not add up" in how and inc["revenue"] == 1000


def test_no_new_quarter_means_the_fiscal_year():
    q = _quarters({"2025-12-31": (255, 76, 41), "2025-09-30": (250, 74, 40)})
    _, basis, _, n, _ = ltm_income(FY, FY_END, q)
    assert basis == "FY2025" and n == 0


def test_latest_balance_sheet_net_debt():
    qb = pd.DataFrame({pd.Timestamp("2026-06-30"): {"Net Debt": 260.0, "Minority Interest": 7.0, "Cash And Cash Equivalents": 40.0,
                                                    "Long Term Debt": 300.0, "Current Debt": 0.0},
                       pd.Timestamp("2025-12-31"): {"Net Debt": 200.0, "Minority Interest": 5.0, "Cash And Cash Equivalents": 50.0,
                                                    "Long Term Debt": 250.0, "Current Debt": 0.0}})
    assert latest_balance(FY, FY_END, qb) == (260.0, 7.0, "2026-06-30")
    assert latest_balance(FY, FY_END, qb.drop(columns=[pd.Timestamp("2026-06-30")])) == (200.0, 5.0, "2025-12-31")


# ------------------------------------------------------------------ consensus
def _estimates():
    rev = pd.DataFrame({"avg": [1100e6, 1200e6], "low": [1080e6, 1150e6], "high": [1120e6, 1260e6], "numberOfAnalysts": [5, 5],
                        "yearAgoRevenue": [1000e6, 1100e6]}, index=["0y", "+1y"])
    eps = pd.DataFrame({"avg": [3.0, 3.5], "low": [2.8, 3.2], "high": [3.2, 3.9], "numberOfAnalysts": [5, 4]}, index=["0y", "+1y"])
    trend = pd.DataFrame({"current": [3.0, 3.5], "90daysAgo": [3.2, 3.9]}, index=["0y", "+1y"])
    revs = pd.DataFrame({"upLast30days": [0, 0], "downLast30days": [2, 3]}, index=["0y", "+1y"])
    return rev, eps, trend, revs


def test_consensus_comparison_and_momentum():
    rev, eps, trend, revs = _estimates()
    cal = {"Earnings Date": [dt.date(2026, 10, 27)], "Revenue Average": 280e6, "Earnings Average": 0.8, "Ex-Dividend Date": dt.date(2026, 5, 1)}
    v = build_consensus_view(revenue_estimate=rev, earnings_estimate=eps, eps_trend=trend, eps_revisions=revs, calendar=cal, last_fy=2025,
                             last_fy_revenue=1000.0, forecast_years=[2026, 2027, 2028], our_revenue={2026: 1100.0, 2027: 1190.0},
                             our_eps={2026: 2.7, 2027: 3.6}, units_divisor=1e6, eps_to_listing=1.0, today=dt.date(2026, 9, 21))
    assert v.aligned
    e26 = v.get("EPS", 2026)
    assert e26.diff == pytest.approx(2.7 / 3.0 - 1) and e26.outside_range          # below the lowest estimate
    assert v.get("Revenue", 2027).diff == pytest.approx(1190 / 1200 - 1)
    assert v.momentum == "negative"
    assert [c.event for c in v.catalysts] == ["Quarterly results"]                   # the ex-dividend date has passed


def test_consensus_is_not_compared_when_the_years_do_not_line_up():
    rev, eps, trend, revs = _estimates()
    v = build_consensus_view(revenue_estimate=rev, earnings_estimate=eps, eps_trend=trend, eps_revisions=revs, calendar={}, last_fy=2025,
                             last_fy_revenue=800.0, forecast_years=[2026], our_revenue={}, our_eps={}, units_divisor=1e6,
                             eps_to_listing=1.0, today=dt.date(2026, 9, 21))
    assert not v.aligned and not v.estimates and v.note


def test_momentum_labels():
    assert momentum_label([Revision(2026, 3.3, 3.0, 4, 0)]) == "positive"
    assert momentum_label([Revision(2026, 3.0, 3.01, 1, 1)]) == "flat"
    assert momentum_label([Revision(2026, 3.3, 3.0, 0, 3)]) == "mixed"
    assert momentum_label([]) == "n.a."


# ------------------------------------------------------------------ bottom-up beta
def test_unlever_and_relever_are_inverse():
    assert relever(unlever(1.2, 0.5, 0.22), 0.5, 0.22) == pytest.approx(1.2)


def test_bottom_up_beta_takes_the_median_unlevered_beta():
    peers = [{"ticker": "A", "beta": 1.0, "debt_to_equity": 0.0}, {"ticker": "B", "beta": 1.39, "debt_to_equity": 0.5},
             {"ticker": "C", "beta": 0.9, "debt_to_equity": 0.2}, {"ticker": "D", "beta": 7.0, "debt_to_equity": 0.1}]  # D is ignored
    pb = bottom_up_beta(peers, target_debt_to_equity=0.3, tax=0.22)
    assert pb.n == 3
    assert pb.unlevered_median == pytest.approx(1.0)                                   # 1.0, 1.39/1.39 = 1.0, 0.9/1.156
    assert pb.relevered_raw == pytest.approx(1.0 * (1 + 0.78 * 0.3))
    assert pb.relevered_adjusted == pytest.approx(0.67 * pb.relevered_raw + 0.33)
    assert bottom_up_beta(peers[:2], 0.3, 0.22) is None                                # fewer than three peers


# ------------------------------------------------------------------ pipeline: value drivers, dividend, note
@pytest.fixture
def case(monkeypatch, config):
    snaps = {"TEST.OL": make_snapshot(), "P1.OL": make_snapshot("P1.OL", price=40.0), "P2.OL": make_snapshot("P2.OL", price=60.0)}
    snaps["TEST.OL"].info.update({"dividendRate": 1.5})
    for s in snaps.values():
        s.info["beta"] = 1.1
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snaps[symbol])
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snaps["TEST.OL"].prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)
    config.assumptions.valuation_date = "2026-03-31"
    return pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)


def test_value_drivers_move_the_value_the_right_way(case):
    by = {v.driver: v for v in case.value_drivers}
    assert by["EBITDA margin (all years)"].value_up > by["EBITDA margin (all years)"].base > by["EBITDA margin (all years)"].value_down
    assert by["WACC"].value_up < by["WACC"].base < by["WACC"].value_down
    assert by["Capex, % of revenue"].value_up < by["Capex, % of revenue"].value_down
    swings = [v.swing for v in case.value_drivers]
    assert swings == sorted(swings, reverse=True)
    assert case.value_drivers[0].base == pytest.approx(case.dcf.value_per_share)
    again = value_drivers(case.hist, case.drivers, case.cfg, case.wacc.wacc, net_debt=case.net_debt, shares=case.shares,
                          minorities=case.minorities, ronic=None, valuation_offset=case.dcf.valuation_offset,
                          balance_offset=case.dcf.balance_offset)
    assert again[0].value_down == pytest.approx(case.value_drivers[0].value_down)


def test_indicated_dividend_and_peer_beta_cross_check(case):
    assert case.recommendation.dps == pytest.approx(1.5) and "indicated" in case.dps_source
    assert case.wacc.peer_beta is None                       # two peers is below the three needed for a bottom-up beta
    assert list(case.comps.table["beta"]) == [1.1, 1.1]      # but the peer betas are collected for it


def test_research_note_carries_the_numbers(case, tmp_path):
    from eqr.create.note import build_note
    from eqr.narrative import generate_narrative

    case.narrative, case.narrative_mode = generate_narrative(case, mode="rules")
    kf = case.key_figures()
    assert list(kf.columns) == ["2024A", "2025A", "2026E", "2027E", "2028E"]
    assert kf.loc["EV/EBITDA", "2025A"] == pytest.approx(case.enterprise_value / case.hist.loc[2025, "ebitda"])
    html = build_note(case, tmp_path / "note.html", charts_dir=tmp_path / "charts").read_text(encoding="utf-8")
    assert case.recommendation.rating in html and f"{case.recommendation.target_price:,.2f}" in html
    assert "Key figures" in html and "31.03.2026" in html
