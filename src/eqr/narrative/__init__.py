"""Narrative layer: rule-based by default, Claude-written on request."""
from __future__ import annotations

import logging
from typing import Any

from .rules import NARRATIVE_KEYS, build_rule_narrative

log = logging.getLogger(__name__)


def generate_narrative(result, mode: str = "rules", model: str | None = None) -> tuple[dict[str, Any], str]:
    """Return (narrative, mode_used). ``mode``: rules | claude | auto."""
    base = build_rule_narrative(result)
    if mode == "rules":
        return base, "rules"
    from .claude import credentials_available, generate_claude_narrative

    if mode == "auto" and not credentials_available():
        return base, "rules"
    try:
        return generate_claude_narrative(result, base, model=model), f"claude ({model or 'claude-opus-5'})"
    except Exception as exc:
        if mode == "claude":
            result.warnings.append(f"Claude narrative failed ({exc}); used rule-based text instead.")
        log.warning("Claude narrative failed: %s", exc)
        return base, "rules"


__all__ = ["generate_narrative", "build_rule_narrative", "NARRATIVE_KEYS"]
