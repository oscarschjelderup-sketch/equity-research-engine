"""Import historical financials from the analyst's own files.

Yahoo Finance only carries ~4 annual periods. A CSV/XLSX with one row per fiscal
year (columns are matched case-insensitively against the canonical names below)
extends or overrides the history used in the model.

Canonical columns (all optional except ``year``): revenue, ebitda, da, ebit,
net_income, eps, capex, nwc_change, cash, total_debt, shares. Values are in the
same units as the config's ``units_divisor`` (millions by default) — set
``scale`` if the file uses another unit.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CANONICAL = ["revenue", "ebitda", "da", "ebit", "net_income", "eps", "capex", "nwc_change", "cash", "total_debt", "shares"]
ALIASES = {
    "total revenue": "revenue",
    "revenues": "revenue",
    "sales": "revenue",
    "d&a": "da",
    "depreciation": "da",
    "operating income": "ebit",
    "net profit": "net_income",
    "capital expenditure": "capex",
    "change in nwc": "nwc_change",
    "chg in nwc": "nwc_change",
    "net debt": "net_debt",
    "shares outstanding": "shares",
}


def load_history_file(path: str | Path, scale: float = 1.0, sheet: str | int | None = 0) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        raw = pd.read_excel(path, sheet_name=sheet)
    else:
        raw = pd.read_csv(path, sep=None, engine="python")
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    raw = raw.rename(columns=ALIASES)
    if "year" not in raw.columns:
        # allow a "wide" layout: first column is the line item, other columns are years
        first = raw.columns[0]
        wide = raw.set_index(first).T
        wide.index.name = "year"
        raw = wide.reset_index()
        raw.columns = [str(c).strip().lower() for c in raw.columns]
        raw = raw.rename(columns=ALIASES)
    raw["year"] = pd.to_numeric(raw["year"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce")
    raw = raw.dropna(subset=["year"])
    raw["year"] = raw["year"].astype(int)
    keep = ["year"] + [c for c in raw.columns if c in CANONICAL or c == "net_debt"]
    out = raw[keep].set_index("year").sort_index()
    for col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if col != "eps":
            out[col] = out[col] * scale
    return out
