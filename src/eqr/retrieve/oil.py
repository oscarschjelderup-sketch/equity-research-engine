"""Read an oil-sensitivity factsheet produced by the oslo-oil-sensitivity study.

The file is a small JSON document with schema ``oilbeta.stock/1``, written by::

    oilbeta stock EQNR.OL --json oil/EQNR.OL.json

Point a case config at it with ``oil_sensitivity:`` and the risk section gains a measured
statement — "a 10% fall in Brent has come with a 4.8% fall in the share, interval 4.0% to 5.8%" —
instead of the usual hand-wave about commodity exposure.

Nothing here touches the valuation. The beta is co-movement with a sign, measured on past returns;
turning it into a WACC adjustment would claim far more than the study supports. It is context for
the risk section, and the caveats that come with the file are carried into the deck with it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_PREFIX = "oilbeta.stock/"
SUPPORTED_MAJOR = "1"


class OilFactsheetError(ValueError):
    """The file is missing, unreadable, or not a factsheet this version understands."""


@dataclass
class OilScenario:
    brent: float           # e.g. -0.10 for a 10% fall in Brent
    expected: float        # expected move in the share, same convention
    lo: float
    hi: float
    p_same_sign: float     # how often the share actually moves that way in such a week


@dataclass
class OilSensitivity:
    """One stock's oil sensitivity, as measured by the companion study."""

    ticker: str
    name: str
    window: str                    # which window the headline numbers come from
    weeks: int
    beta_total: float              # move per 1% move in Brent, through every channel
    total_lo: float
    total_hi: float
    beta_partial: float            # oil risk beyond what the index already carries
    partial_p: float
    variance_explained: float
    scenarios: list[OilScenario]
    caveats: list[str]
    source_url: str = ""
    method: str = ""
    sample: dict[str, Any] = field(default_factory=dict)
    sector: str | None = None
    sector_context: dict[str, Any] | None = None
    market_index: str = ""
    oil_series: str = ""

    @property
    def significant(self) -> bool:
        """Does the stock carry oil risk beyond the index's own?"""
        return self.partial_p < 0.05

    def scenario(self, brent: float) -> OilScenario | None:
        for s in self.scenarios:
            if abs(s.brent - brent) < 1e-9:
                return s
        return None

    @property
    def downside(self) -> OilScenario | None:
        """The most negative Brent scenario on file, which is the one a risk section needs."""
        down = [s for s in self.scenarios if s.brent < 0]
        return min(down, key=lambda s: s.brent) if down else None


def load_oil_sensitivity(source: str | Path, base_dir: str | Path | None = None) -> OilSensitivity:
    path = Path(source)
    if base_dir and not path.is_absolute():
        path = Path(base_dir) / path
    if not path.exists():
        raise OilFactsheetError(f"oil_sensitivity file not found: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OilFactsheetError(f"{path.name} is not valid JSON: {exc}") from exc

    schema = str(doc.get("schema", ""))
    if not schema.startswith(SCHEMA_PREFIX):
        raise OilFactsheetError(f"{path.name} is not an oil factsheet (schema {schema!r})")
    major = schema[len(SCHEMA_PREFIX):].split(".")[0]
    if major != SUPPORTED_MAJOR:
        raise OilFactsheetError(f"{path.name} uses schema {schema}; this version reads {SCHEMA_PREFIX}{SUPPORTED_MAJOR}.x")

    key = doc.get("headline_window") or next(iter(doc.get("windows", {})), None)
    window = (doc.get("windows") or {}).get(key)
    if not window:
        raise OilFactsheetError(f"{path.name} has no usable window (headline_window={key!r})")

    return OilSensitivity(
        ticker=doc.get("ticker", ""),
        name=doc.get("name") or doc.get("ticker", ""),
        window=str(key).replace("_", " "),
        weeks=int(window.get("weeks", 0)),
        beta_total=float(window["beta_oil_total"]),
        total_lo=float(window["total_lo"]),
        total_hi=float(window["total_hi"]),
        beta_partial=float(window.get("beta_oil_partial", float("nan"))),
        partial_p=float(window.get("partial_p", 1.0)),
        variance_explained=float(window.get("variance_explained_by_oil", 0.0)),
        scenarios=[OilScenario(**{k: float(v) for k, v in s.items()}) for s in window.get("scenarios", [])],
        caveats=list(doc.get("caveats", [])),
        source_url=(doc.get("source") or {}).get("url", ""),
        method=(doc.get("source") or {}).get("method", ""),
        sample=doc.get("sample", {}),
        sector=doc.get("sector"),
        sector_context=doc.get("sector_context"),
        market_index=doc.get("market_index", ""),
        oil_series=doc.get("oil_series", ""),
    )
