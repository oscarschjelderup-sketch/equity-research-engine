"""Optional AI narrative: Claude writes the qualitative text from the engine's numbers.

The model only ever sees the computed metrics (JSON) plus the company
description; it cannot change a number. Its job is the analyst prose: thesis,
highlights, commentary, opportunities/threats and risks. Output is validated
against the rule-based narrative and falls back per key when missing.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .rules import NARRATIVE_KEYS

DEFAULT_MODEL = "claude-opus-5"

LIST_KEYS = {"highlights", "opportunities", "disruption", "threats", "financial_commentary", "thesis", "multiples_commentary", "risks",
             "market_implied", "scenario_commentary", "consensus", "catalysts", "multiples_depth"}
MAX_ITEMS = {"highlights": 4, "opportunities": 3, "disruption": 3, "threats": 3, "financial_commentary": 6, "thesis": 4,
             "multiples_commentary": 4, "risks": 4, "market_implied": 3, "scenario_commentary": 4, "consensus": 4, "catalysts": 3, "multiples_depth": 5}
# Blocks that are pure arithmetic: Claude may not rewrite them (numbers must stay exact).
LOCKED_KEYS = {"market_implied", "scenario_commentary", "valuation_headline", "consensus", "catalysts", "multiples_depth"}

SYSTEM_PROMPT = """You are a sell-side equity research analyst writing the text for a four-slide investment case
(Company overview, Market overview, Financials and estimates, Valuation and recommendation) in the concise, factual
style of a Nordic investment bank. You receive the full quantitative analysis as JSON. Rules:
- Never invent numbers. Every figure you cite must appear in the JSON (round sensibly). Use the units and currency given.
- Do not change the rating or target price; explain them.
- Bullets are short (max ~28 words), start with a bold lead-in written as **lead:** and give one idea each.
- Write in English. No hedging boilerplate, no disclaimers, no emojis.
- Return ONLY a JSON object with exactly these keys:
  cover_tagline (string, max 8 words, a punchy title like "Healthy body, healthy margins"),
  company_subtitle (string, one line), company_headline (string, one bold-style sentence about the business quality),
  highlights (list of 4 bullets on business model, market position, growth, cash generation),
  management_note (string, one sentence about the management team or empty string),
  market_subtitle (string), market_headline (string),
  opportunities (list of 2-3 bullets), disruption (list of 2 bullets), threats (list of 2-3 bullets),
  financials_subtitle (string), financial_commentary (list of 5-6 bullets on history, forecast drivers, margins, FCF, peers),
  valuation_subtitle (string: 'We recommend a <RATING>. ...' with the target price and upside),
  thesis (list of 4 bullets supporting the recommendation), multiples_commentary (list of 3-4 bullets),
  risks (list of 3-4 bullets)."""


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install the 'anthropic' package (pip install equity-research-engine[ai]) to use --narrative claude") from exc
    return anthropic, anthropic.Anthropic()


def credentials_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    cfg_dir = os.path.expanduser("~/.config/anthropic")
    return os.path.isdir(cfg_dir) and any(os.scandir(cfg_dir))


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object in model response")
    return json.loads(m.group(0))


def _analysis_payload(result) -> dict[str, Any]:
    d = result.to_json_dict()
    # keep the payload focused: drop price series and config internals
    for key in ("prices", "relative_performance", "config"):
        d.pop(key, None)
    d["market_inputs"] = {
        "opportunities": result.cfg.market.opportunities, "disruption": result.cfg.market.disruption,
        "threats": result.cfg.market.threats, "charts": [c.title for c in result.cfg.market.charts],
    }
    return d


def generate_claude_narrative(result, base: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    anthropic, client = _client()
    model = model or DEFAULT_MODEL
    payload = json.dumps(_analysis_payload(result), ensure_ascii=False, default=str)
    user = (f"Company: {result.name} ({result.cfg.ticker}). Rating {result.recommendation.rating}, target price "
            f"{result.currency} {result.recommendation.target_price:.2f}, current price {result.price:.2f}.\n"
            f"Rule-based draft you may improve (keep facts): {json.dumps(base, ensure_ascii=False)}\n\n"
            f"Analysis JSON:\n{payload}")
    kwargs = dict(model=model, max_tokens=8000, system=SYSTEM_PROMPT, messages=[{"role": "user", "content": user}])
    try:
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-06-01"], fallbacks=[{"model": "claude-opus-4-8"}], **kwargs
        )
    except TypeError:  # older SDK without server-side fallbacks
        response = client.messages.create(**kwargs)
    except anthropic.BadRequestError:
        response = client.messages.create(**kwargs)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write the narrative; falling back to rules.")
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    data = _extract_json(text)
    out = dict(base)
    for key in NARRATIVE_KEYS:
        value = data.get(key)
        if value in (None, "", []) or key in LOCKED_KEYS:
            continue
        if key in LIST_KEYS:
            if not isinstance(value, list):
                continue
            out[key] = [str(v).strip() for v in value if str(v).strip()][: MAX_ITEMS.get(key, 6)]
        else:
            out[key] = str(value).strip()
    return out
