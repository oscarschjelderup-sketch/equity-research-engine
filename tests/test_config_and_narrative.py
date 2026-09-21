from pathlib import Path

import yaml

from eqr.config import default_config_yaml, load_config, to_dict
from eqr.narrative import NARRATIVE_KEYS, build_rule_narrative


def test_default_config_yaml_round_trips(tmp_path: Path):
    p = tmp_path / "TEST.OL.yaml"
    p.write_text(default_config_yaml("TEST.OL"), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.ticker == "TEST.OL"
    assert cfg.assumptions.forecast_years == 6
    assert cfg.assumptions.lease_treatment == "operating"
    assert cfg.wacc.risk_free == 0.038
    assert len(cfg.team) == 1


def test_bundled_sats_config_loads():
    cfg = load_config("SATS.OL")
    assert cfg.name == "SATS ASA"
    assert len(cfg.peers) >= 5
    assert cfg.assumptions.ebitda_margin_target == 0.18
    assert cfg.market.charts[0].type == "bar"
    d = to_dict(cfg)
    assert d["peers"][0]["ticker"] == "BFIT.AS"


def test_default_index_follows_listing_suffix():
    from eqr.config import default_index_for

    assert default_index_for("MOWI.OL") == ("OSEBX.OL", "OSEBX")
    assert default_index_for("VOLV-B.ST")[0] == "^OMX"
    assert default_index_for("AAPL") == ("^GSPC", "S&P 500")
    cfg = load_config("NHY.OL")  # no YAML for this ticker -> defaults
    assert cfg.index == "OSEBX.OL"


def test_unknown_keys_are_ignored(tmp_path: Path):
    p = tmp_path / "X.yaml"
    p.write_text(yaml.safe_dump({"ticker": "X", "assumptions": {"tax_rate": 0.25, "not_a_field": 1}, "bogus": True}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.assumptions.tax_rate == 0.25


def test_rule_narrative_has_all_keys(config, snapshot):
    import eqr.pipeline as pl
    from eqr.pipeline import run_analysis
    from eqr.retrieve import DiskCache

    # monkeypatch network calls with the synthetic snapshot
    pl.fetch_snapshot = lambda symbol, cache, **kw: snapshot  # type: ignore[assignment]
    pl.fetch_prices = lambda symbol, cache, **kw: snapshot.prices  # type: ignore[assignment]
    pl.fetch_fx = lambda a, b, cache=None: 1.0  # type: ignore[assignment]
    config.peers = []
    r = run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)
    n = build_rule_narrative(r)
    for key in NARRATIVE_KEYS:
        assert key in n, key
    assert r.recommendation.rating in {"BUY", "HOLD", "SELL"}
    assert "NOK" in n["valuation_subtitle"]
    js = r.to_json_dict()
    assert js["company"]["ticker"] == "TEST.OL"
    assert js["dcf"]["sensitivity"]["values"][3][3] is not None
