"""Multiples in depth (currency-consistent EV, calendarised consensus, the regression) and the public site."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

import eqr.pipeline as pl
from eqr.analyze import build_comps, build_history, football_field, run_dcf
from eqr.analyze.comps import CompsResult, forward_multiples
from eqr.analyze.multiples import consensus_forward, multiples_regression, ntm_weight
from eqr.coverage import log_coverage, read_coverage
from eqr.create.site import build_site
from eqr.retrieve import DiskCache
from tests.conftest import make_snapshot


# ------------------------------------------------------------------ calendarisation
def test_ntm_weight_follows_each_companys_fiscal_year():
    w, end = ntm_weight(pd.Timestamp("2025-12-31"), dt.date(2026, 9, 30))   # December year-end: 3 months of FY0 left
    assert end == pd.Timestamp("2026-12-31") and w == pytest.approx(92 / 365.25, abs=1e-6)
    w, end = ntm_weight(pd.Timestamp("2026-04-30"), dt.date(2026, 9, 30))   # April year-end (Clas Ohlson): 7 months left
    assert end == pd.Timestamp("2027-04-30") and w == pytest.approx(212 / 365.25, abs=1e-6)
    assert ntm_weight(pd.Timestamp("2025-12-31"), dt.date(2027, 3, 1))[0] == 0.0   # FY0 already over


def _estimates(year_ago=1000e6):
    scale = year_ago / 1000e6                                      # the whole table is quoted in the same currency as the year-ago figure
    rev = pd.DataFrame({"avg": [1100e6 * scale, 1210e6 * scale], "numberOfAnalysts": [5, 5], "yearAgoRevenue": [year_ago, 1100e6 * scale]},
                       index=["0y", "+1y"])
    eps = pd.DataFrame({"avg": [3.0, 3.6], "numberOfAnalysts": [5, 4]}, index=["0y", "+1y"])
    return rev, eps


def test_consensus_forward_blends_the_two_fiscal_years():
    rev, eps = _estimates()
    f = consensus_forward(rev, eps, pd.Timestamp("2025-12-31"), dt.date(2026, 9, 30), 1000e6)
    w = 92 / 365.25
    assert f.revenue_ntm == pytest.approx(w * 1100e6 + (1 - w) * 1210e6)
    assert f.eps_ntm == pytest.approx(w * 3.0 + (1 - w) * 3.6)
    assert f.revenue_growth_fy1 == pytest.approx(0.10) and f.eps_growth_fy1 == pytest.approx(0.2)
    assert consensus_forward(*_estimates(year_ago=800e6), pd.Timestamp("2025-12-31"), dt.date(2026, 9, 30), 1000e6) is None  # years do not line up


def test_forward_multiples_convert_eps_to_the_listing_currency():
    rev, eps = _estimates()
    # accounts in EUR, share in NOK: 0.085 EUR per NOK, so a EUR EPS is worth 1/0.085 NOK
    f = consensus_forward(rev, eps, pd.Timestamp("2025-12-31"), dt.date(2026, 9, 30), 1000e6, fx_listing_to_reporting=0.085)
    assert f.estimates_currency == "reporting"
    w = 92 / 365.25
    assert f.eps_ntm == pytest.approx((w * 3.0 + (1 - w) * 3.6) / 0.085)
    assert f.revenue_ntm == pytest.approx(w * 1100e6 + (1 - w) * 1210e6)   # revenue stays in the reporting currency
    m = forward_multiples(f, price_listing=60.0, ev=2000.0, mcap=1500.0, ltm_margin=0.25, divisor=1e6)
    assert m["ev_sales_ntm"] == pytest.approx(2000.0 / (f.revenue_ntm / 1e6))
    assert m["ev_ebitda_ntm"] == pytest.approx(2000.0 / (f.revenue_ntm / 1e6 * 0.25))
    assert m["fwd_pe"] == pytest.approx(60.0 / f.eps_ntm)
    assert m["pe_fy1"] == pytest.approx(60.0 / (3.6 / 0.085))
    assert m["peg"] == pytest.approx(m["fwd_pe"] / 20.0)
    assert forward_multiples(None, price_listing=60.0, ev=1.0, mcap=1.0, ltm_margin=0.2)["fwd_pe"] is None


def test_yahoo_estimates_quoted_in_the_listing_currency_are_detected():
    """Yara: USD accounts, but Yahoo's estimate table is in NOK – the year-ago revenue gives it away."""
    from eqr.analyze.multiples import estimate_currency

    fx = 0.10                                                      # USD per NOK
    rev, eps = _estimates(year_ago=1000e6 / fx)                    # the table quotes last year's USD 1,000m as NOK 10,000m
    assert estimate_currency(rev, 1000e6, fx) == ("listing", fx)
    assert estimate_currency(_estimates()[0], 1000e6, fx) == ("reporting", 1.0)
    assert estimate_currency(_estimates(year_ago=1234e6)[0], 1000e6, fx) == (None, 1.0)
    f = consensus_forward(rev, eps, pd.Timestamp("2025-12-31"), dt.date(2026, 9, 30), 1000e6, fx_listing_to_reporting=fx)
    assert f.estimates_currency == "listing"
    assert f.revenue_fy0 == pytest.approx(1100e6)                  # the NOK 11,000m of the table back into USD 1,100m
    assert f.eps_fy0 == pytest.approx(3.0)                         # already NOK: the share price's currency


# ------------------------------------------------------------------ currency-consistent EV
def test_a_peer_listed_in_another_currency_gets_its_market_cap_converted(config):
    snap = make_snapshot()
    hist = build_history(snap, config)
    last = hist.iloc[-1]
    metrics = {"revenue": float(last["revenue"]), "ebitda": float(last["ebitda"]), "ebit": float(last["ebit"]), "eps": float(last["eps"])}
    foreign = make_snapshot("P1.OL", price=40.0)            # reports in NOK ...
    foreign.info["currency"] = "DKK"                        # ... but the share trades in DKK: Yahoo's market cap is in DKK
    peers = {"P1.OL": foreign, "P2.OL": make_snapshot("P2.OL", price=60.0)}
    kw = dict(company_metrics=metrics, net_debt=float(last["net_debt"]), minorities=0.0, shares=100.0, price=50.0, forward_eps=3.2)
    naive = build_comps(config, snap, peers, {"NOK": 1.0}, **kw).table.set_index("ticker").loc["P1.OL"]
    fixed = build_comps(config, snap, peers, {"NOK": 1.0}, peer_fx_listing={"P1.OL": 0.65}, **kw).table.set_index("ticker").loc["P1.OL"]
    assert naive["ev"] == pytest.approx(40 * 100 + 200)                     # DKK market cap plus NOK net debt: mixed currencies
    assert fixed["ev"] == pytest.approx(40 * 100 * 0.65 + 200)             # market cap in NOK first
    assert fixed["ev_ebitda"] == pytest.approx(fixed["ev"] / 250.5)
    assert fixed["debt_to_equity"] == pytest.approx(300 / (40 * 100 * 0.65))


# ------------------------------------------------------------------ regression
def _peer_table(n=8):
    rows = []
    for i in range(n):
        g, m = 0.02 + 0.02 * i, 0.10 + 0.03 * (i % 4)
        rows.append({"ticker": f"P{i}", "name": f"Peer {i}", "ev_ebitda": 4.0 + 60 * g + 20 * m, "growth_reg": g, "ebitda_margin": m})
    return pd.DataFrame(rows)


def test_regression_recovers_the_coefficients_and_decomposes_the_gap():
    tbl = _peer_table()
    target = {"ev_ebitda": 9.0, "growth_reg": 0.05, "ebitda_margin": 0.20}
    reg = multiples_regression(tbl, target, ebitda=100.0, net_debt=150.0, minorities=0.0, shares=10.0)
    assert reg.n == 8 and reg.regressors == ["growth_reg", "ebitda_margin"]
    assert reg.intercept == pytest.approx(4.0, abs=1e-6)
    assert reg.coefficients["growth_reg"] == pytest.approx(60.0, abs=1e-6) and reg.coefficients["ebitda_margin"] == pytest.approx(20.0, abs=1e-6)
    assert reg.r2 == pytest.approx(1.0, abs=1e-9)
    fitted = 4.0 + 60 * 0.05 + 20 * 0.20
    assert reg.fitted_target == pytest.approx(fitted)
    assert reg.implied_value_per_share == pytest.approx((fitted * 100 - 150) / 10)
    assert reg.unexplained == pytest.approx(9.0 / fitted - 1)
    assert reg.explained == pytest.approx(fitted / reg.peer_median - 1)


def test_regression_falls_back_to_growth_only_and_refuses_thin_samples():
    tbl = _peer_table(5)                                    # five peers: too few for two regressors, enough for one
    reg = multiples_regression(tbl, {"ev_ebitda": 8.0, "growth_reg": 0.05, "ebitda_margin": 0.2})
    assert reg is not None and reg.regressors == ["growth_reg"]
    assert multiples_regression(_peer_table(3), {"ev_ebitda": 8.0, "growth_reg": 0.05, "ebitda_margin": 0.2}) is None


def test_a_weak_regression_is_reported_but_not_a_football_field_anchor(config):
    snap = make_snapshot()
    hist = build_history(snap, config)
    last = hist.iloc[-1]
    metrics = {"revenue": float(last["revenue"]), "ebitda": float(last["ebitda"]), "ebit": float(last["ebit"]), "eps": float(last["eps"]),
               "growth": float(last["growth"])}
    peers = {f"P{i}.OL": make_snapshot(f"P{i}.OL", price=30.0 + 5 * i, ebitda_margin=0.2 + 0.03 * i) for i in range(7)}
    config.peers = [type(config.peers[0])(t, t, "Nordic") for t in peers]
    comps = build_comps(config, snap, peers, {"NOK": 1.0}, company_metrics=metrics, net_debt=200.0, minorities=0.0, shares=100.0, price=50.0)
    assert comps.regression is not None
    assert comps.regression.regressors == ["ebitda_margin"]   # every synthetic peer grows 10%: growth cannot explain anything and is dropped
    from eqr.analyze import build_forecast, derive_drivers
    dcf = run_dcf(build_forecast(hist, derive_drivers(hist, config, snap)), wacc=0.09, terminal_growth=0.02, net_debt=200.0, shares=100.0, price=50.0)
    strong = CompsResult(comps.table, comps.stats, comps.company, comps.implied, "NOK", comps.regression)
    strong.regression.r2 = 0.6
    assert any(b.label.startswith("EV/EBITDA regression") for b in football_field(snap.info, dcf, strong, 50.0))
    strong.regression.r2 = 0.05
    assert not any(b.label.startswith("EV/EBITDA regression") for b in football_field(snap.info, dcf, strong, 50.0))


# ------------------------------------------------------------------ coverage log and site
@pytest.fixture
def case(monkeypatch, config):
    snaps = {"TEST.OL": make_snapshot(), "P1.OL": make_snapshot("P1.OL", price=40.0), "P2.OL": make_snapshot("P2.OL", price=60.0)}
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snaps[symbol])
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snaps["TEST.OL"].prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)
    config.assumptions.valuation_date = "2026-03-31"
    return pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)


def test_coverage_log_keeps_one_row_per_ticker_and_day(case, tmp_path):
    path = tmp_path / "history.csv"
    log_coverage(case, path)
    log_coverage(case, path)                                 # a re-run the same day replaces, it does not pile up
    rows = read_coverage(path)
    assert len(rows) == 1 and rows[0]["ticker"] == "TEST.OL" and rows[0]["rating"] == case.recommendation.rating
    case.valuation_date = dt.date(2026, 6, 30)
    log_coverage(case, path)
    assert [r["date"] for r in read_coverage(path)] == ["2026-03-31", "2026-06-30"]


def test_site_lists_the_cases_and_the_track_record(case, tmp_path):
    from eqr.narrative import generate_narrative

    case.narrative, case.narrative_mode = generate_narrative(case, mode="rules")
    cases = tmp_path / "examples" / "TEST.OL"
    cases.mkdir(parents=True)
    (cases / "analysis.json").write_text(case.to_json(), encoding="utf-8")
    (cases / "TEST.OL_note.html").write_text("<html>note</html>", encoding="utf-8")
    log = tmp_path / "history.csv"
    case.valuation_date = dt.date(2026, 1, 15)
    case.price = 40.0
    log_coverage(case, log)                                  # an earlier call at NOK 40 ...
    case.valuation_date = dt.date(2026, 3, 31)
    case.price = 50.0
    log_coverage(case, log)                                  # ... and today's at NOK 50
    out = build_site(tmp_path / "examples", tmp_path / "site", log)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "TEST.OL" in html and case.recommendation.rating in html
    assert (out / "cases" / "TEST.OL" / "TEST.OL_note.html").exists() and (out / ".nojekyll").exists()
    assert "+25.0%" in html                                  # return since the first rating: 50 / 40 - 1
    assert "Full log (2 entries)" in html
    assert "not investment advice" in html


def test_analysis_json_carries_the_new_multiples(case):
    d = json.loads(case.to_json())
    comp = d["comps"]["company"]
    assert "fwd_pe" in comp and "ev_sales_ntm" in comp and "fcf_yield" in comp
    assert d["comps"]["regression"] is None or "fitted_target" in d["comps"]["regression"]
