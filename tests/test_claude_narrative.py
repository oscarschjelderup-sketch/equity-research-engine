"""The optional Claude narrative, tested offline with a fake client (no API key, no network)."""
import json
from types import SimpleNamespace

import pytest

import eqr.narrative.claude as claude_mod
import eqr.pipeline as pl
from eqr.narrative import generate_narrative
from eqr.retrieve import DiskCache


class _FakeAnthropicModule:
    class BadRequestError(Exception):
        pass


def _fake_client(payload, *, stop_reason="end_turn", record=None):
    def create(**kwargs):
        if record is not None:
            record.update(kwargs)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])

    messages = SimpleNamespace(create=create)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))


@pytest.fixture
def result(config, snapshot, monkeypatch):
    monkeypatch.setattr(pl, "fetch_snapshot", lambda symbol, cache, **kw: snapshot)
    monkeypatch.setattr(pl, "fetch_prices", lambda symbol, cache, **kw: snapshot.prices)
    monkeypatch.setattr(pl, "fetch_fx", lambda a, b, cache=None: 1.0)
    config.peers = []
    return pl.run_analysis(config, DiskCache(enabled=False), progress=lambda m: None)


def test_claude_text_is_merged_but_numbers_stay_locked(result, monkeypatch):
    sent = {}
    reply = {
        "cover_tagline": "Steady compounder",
        "highlights": ["**Moat:** one", "**Growth:** two", "three", "four", "five is dropped"],
        "thesis": ["**Thesis:** rewritten"],
        "valuation_headline": "Claude must not rewrite this",  # locked: pure arithmetic
        "scenario_commentary": ["made up numbers"],  # locked
        "risks": [],  # empty -> keep the rule-based text
        "not_a_key": "ignored",
    }
    monkeypatch.setattr(claude_mod, "_client", lambda: (_FakeAnthropicModule, _fake_client(reply, record=sent)))
    narrative, mode = generate_narrative(result, mode="claude", model="claude-opus-5")
    assert mode.startswith("claude")
    assert narrative["cover_tagline"] == "Steady compounder"
    assert narrative["highlights"] == ["**Moat:** one", "**Growth:** two", "three", "four"]  # capped at 4
    assert narrative["thesis"] == ["**Thesis:** rewritten"]
    base, _ = generate_narrative(result, mode="rules")
    assert narrative["valuation_headline"] == base["valuation_headline"]
    assert narrative["scenario_commentary"] == base["scenario_commentary"]
    assert narrative["risks"] == base["risks"]
    assert "not_a_key" not in narrative
    # the request carries the computed analysis, not raw prices
    assert sent["model"] == "claude-opus-5"
    body = sent["messages"][0]["content"]
    assert "Analysis JSON" in body and '"prices"' not in body


def test_refusal_or_garbage_falls_back_to_rules(result, monkeypatch):
    base, _ = generate_narrative(result, mode="rules")
    monkeypatch.setattr(claude_mod, "_client", lambda: (_FakeAnthropicModule, _fake_client({}, stop_reason="refusal")))
    narrative, mode = generate_narrative(result, mode="claude")
    assert mode == "rules" and narrative == base
    assert any("Claude narrative failed" in w for w in result.warnings)
    monkeypatch.setattr(claude_mod, "_client", lambda: (_FakeAnthropicModule, _fake_client("no json here")))
    narrative, mode = generate_narrative(result, mode="claude")
    assert mode == "rules" and narrative == base


def test_auto_mode_without_credentials_uses_rules(result, monkeypatch):
    monkeypatch.setattr(claude_mod, "credentials_available", lambda: False)
    narrative, mode = generate_narrative(result, mode="auto")
    assert mode == "rules"
