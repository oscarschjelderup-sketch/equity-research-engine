"""Cross-check: do the independent valuation anchors agree?

A DCF is one opinion. The engine compares it with two others that do not share its assumptions:
the peer-multiple value (today's values, like for like) and the sell-side consensus target (12-month
targets, compared with our own 12-month target). The largest gap sets the agreement label, so a
"+60% upside" that neither peers nor the street support is flagged instead of presented as a fact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

HIGH, MEDIUM = 0.15, 0.35  # maximum gap for "high" and "medium" agreement


@dataclass
class CrossCheck:
    dcf_vs_multiples: float | None  # DCF fair value / peer-multiple value - 1
    target_vs_consensus: float | None  # our 12-month target / consensus mean target - 1
    consensus_target: float | None
    n_analysts: int | None
    max_gap: float | None
    agreement: str  # high | medium | low | n/a
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _gap(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or b <= 0:
        return None
    return float(a / b - 1)


def cross_check(*, fair_value: float, target_price: float, multiples_value: float | None, consensus_target: float | None,
                n_analysts: int | None, currency: str) -> CrossCheck:
    g_mult = _gap(fair_value, multiples_value)
    g_cons = _gap(target_price, consensus_target)
    gaps = [abs(g) for g in (g_mult, g_cons) if g is not None]
    if not gaps:
        return CrossCheck(None, None, consensus_target, n_analysts, None, "n/a",
                          "No peer group or consensus target available to cross-check the DCF")
    worst = max(gaps)
    label = "high" if worst < HIGH else ("medium" if worst < MEDIUM else "low")
    parts = []
    if g_mult is not None:
        parts.append(f"the DCF is {abs(g_mult):.0%} {'above' if g_mult >= 0 else 'below'} the peer-multiple value ({currency} {multiples_value:,.2f})")
    if g_cons is not None:
        who = f"{n_analysts} analysts" if n_analysts else "consensus"
        parts.append(f"our target is {abs(g_cons):.0%} {'above' if g_cons >= 0 else 'below'} the consensus of {who} ({currency} {consensus_target:,.2f})")
    tail = {"high": "the anchors agree", "medium": "review the growth, margin and WACC assumptions before relying on the target",
            "low": "the recommendation rests on the DCF assumptions alone — treat the target as a hypothesis, not a result"}[label]
    return CrossCheck(g_mult, g_cons, consensus_target, n_analysts, float(worst), label, f"{' and '.join(parts)}; {tail}")
