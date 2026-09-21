"""Reading an oil-sensitivity factsheet, and what it is allowed to do to a case.

The contract with the companion study is a JSON file, not an import. These tests fix both sides of
it: which documents are accepted, what the risk sentence says about a positive, a negative and an
absent exposure, and — the important one — that none of it moves a single valuation number.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import eqr.pipeline as pl
from eqr.config import CompanyConfig, load_config
from eqr.narrative import generate_narrative
from eqr.retrieve import DiskCache, OilFactsheetError, load_oil_sensitivity
from tests.conftest import make_snapshot

REPO = Path(__file__).resolve().parents[1]


def factsheet(total=0.49, lo=0.40, hi=0.58, partial=0.32, partial_p=0.0, **extra) -> dict:
    doc = {
        "schema": "oilbeta.stock/1",
        "source": {"url": "https://example.invalid/study", "method": "two-factor weekly regression"},
        "ticker": "TEST.OL", "name": "Test ASA", "sector": "Exploration & production",
        "market_index": "Oslo Børs Benchmark Index", "oil_series": "Brent front-month (USD)",
        "sample": {"start": "2021-09-10", "end": "2026-09-11", "frequency": "weekly"},
        "headline_window": "last_5_years",
        "windows": {"last_5_years": {
            "weeks": 260, "beta_market": 1.1,
            "beta_oil_partial": partial, "partial_lo": partial - 0.1, "partial_hi": partial + 0.1, "partial_p": partial_p,
            "beta_oil_total": total, "total_lo": lo, "total_hi": hi, "total_p": 0.0,
            "variance_explained_by_oil": 0.38,
            "scenarios": [
                {"brent": -0.20, "expected": -0.10, "lo": -0.12, "hi": -0.09, "p_same_sign": 0.999},
                {"brent": -0.10, "expected": -0.05, "lo": -0.06, "hi": -0.04, "p_same_sign": 0.94},
                {"brent": 0.10, "expected": 0.05, "lo": 0.04, "hi": 0.06, "p_same_sign": 0.92},
            ],
        }},
        "caveats": ["An oil beta is co-movement with a sign, not causation."],
    }
    doc.update(extra)
    return doc


def write(tmp_path: Path, doc: dict, name="oil.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_factsheet_is_read_into_the_numbers_a_deck_needs(tmp_path):
    oil = load_oil_sensitivity(write(tmp_path, factsheet()))
    assert (oil.ticker, oil.name, oil.weeks) == ("TEST.OL", "Test ASA", 260)
    assert oil.window == "last 5 years" and oil.beta_total == 0.49 and oil.significant
    assert oil.downside.brent == -0.20 and oil.scenario(0.10).expected == 0.05
    assert oil.scenario(0.99) is None
    assert oil.caveats and oil.source_url.startswith("https://")


def test_a_relative_path_resolves_against_the_config(tmp_path):
    (tmp_path / "oil").mkdir()
    write(tmp_path / "oil", factsheet(), "T.json")
    assert load_oil_sensitivity("oil/T.json", base_dir=tmp_path).ticker == "TEST.OL"


@pytest.mark.parametrize("doc, message", [
    ({"schema": "something/else"}, "not an oil factsheet"),
    ({"schema": "oilbeta.stock/2"}, "this version reads"),
    ({"schema": "oilbeta.stock/1", "windows": {}}, "no usable window"),
])
def test_a_document_this_version_cannot_read_is_refused(tmp_path, doc, message):
    with pytest.raises(OilFactsheetError, match=message):
        load_oil_sensitivity(write(tmp_path, doc))


def test_a_missing_or_broken_file_is_refused_by_name(tmp_path):
    with pytest.raises(OilFactsheetError, match="not found"):
        load_oil_sensitivity(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(OilFactsheetError, match="not valid JSON"):
        load_oil_sensitivity(broken)


# --------------------------------------------------------------------------- #
# What it does to a case
# --------------------------------------------------------------------------- #
@pytest.fixture
def case(monkeypatch):
    snapshot = make_snapshot()
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snapshot)
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snapshot.prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)

    def run(oil_path=None):
        cfg = CompanyConfig(ticker="TEST.OL", name="Test ASA", index="^TEST", units_label="NOKm",
                            oil_sensitivity=str(oil_path) if oil_path else None)
        cfg.peers = []
        result = pl.run_analysis(cfg, DiskCache(enabled=False), progress=lambda m: None)
        result.narrative, result.narrative_mode = generate_narrative(result, mode="rules")
        return result
    return run


def test_oil_context_never_moves_a_valuation(case, tmp_path):
    """The whole point: it is context in the risk section, not a driver. Same case, same numbers."""
    plain, withoil = case(), case(write(tmp_path, factsheet()))
    for field in ("value_per_share", "enterprise_value", "equity_value"):
        assert getattr(withoil.dcf, field) == getattr(plain.dcf, field)
    assert withoil.recommendation.target_price == plain.recommendation.target_price
    assert withoil.recommendation.rating == plain.recommendation.rating
    assert withoil.wacc.wacc == plain.wacc.wacc
    assert plain.oil is None and withoil.oil is not None
    assert json.loads(withoil.to_json())["oil_sensitivity"]["beta_total"] == 0.49


@pytest.mark.parametrize("doc, expected, forbidden", [
    (factsheet(), "20% fall in Brent", "no measurable"),                                    # real exposure
    (factsheet(total=0.03, lo=-0.04, hi=0.09, partial=-0.12, partial_p=0.001),               # a cost, not a driver
     "a higher oil price has been a cost", "oil risk beyond"),
    (factsheet(total=0.03, lo=-0.04, hi=0.09, partial=0.01, partial_p=0.8),                  # nothing there
     "the exposure it has is the index's own", "beyond the index's own"),
])
def test_the_risk_sentence_says_what_the_numbers_say(case, tmp_path, doc, expected, forbidden):
    risks = case(write(tmp_path, doc)).narrative["risks"]
    oil_risk = risks[0]
    assert oil_risk.startswith("**Oil price:**")
    assert expected in oil_risk and forbidden not in oil_risk
    assert len(risks) <= 4                                    # it earns its place, it does not add one


def test_a_broken_factsheet_warns_but_still_produces_the_case(case, tmp_path):
    missing = case(tmp_path / "absent.json")
    assert missing.oil is None
    assert any("Oil sensitivity not loaded" in w for w in missing.warnings)
    assert missing.recommendation.target_price > 0
    assert not any("Oil price" in risk for risk in missing.narrative["risks"])


def test_the_shipped_mowi_case_points_at_a_readable_factsheet():
    cfg = load_config(REPO / "configs" / "MOWI.OL.yaml")
    assert cfg.oil_sensitivity
    oil = load_oil_sensitivity(cfg.oil_sensitivity, base_dir=REPO)
    assert oil.ticker == "MOWI.OL" and oil.weeks > 200
    assert oil.total_lo <= 0 <= oil.total_hi        # salmon has no measurable direct oil exposure
    assert oil.beta_partial < 0 and oil.partial_p < 0.05   # but oil is a cost, and that is measurable
