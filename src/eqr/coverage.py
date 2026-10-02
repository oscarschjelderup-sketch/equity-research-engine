"""The coverage log: every rating and target the engine has published, by date.

A sell-side desk keeps its recommendation history; so does this engine. ``eqr run`` appends one row
per ticker and day to ``coverage/history.csv`` (the same day is overwritten, so re-runs do not pile
up), and the public site turns the log into a track record: rating and price at initiation, the
latest price, the return since. The log is data the reader can check, not a claim.
"""
from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = ["date", "ticker", "name", "price", "currency", "rating", "target_price", "fair_value", "total_return", "agreement",
           "consensus_target", "engine_version"]


def coverage_row(result) -> dict[str, str]:
    from . import __version__

    rec, cc = result.recommendation, result.crosscheck
    cons = (result.snapshot.price_targets or {}).get("mean")
    return {
        "date": (result.valuation_date or result.as_of).isoformat(),
        "ticker": result.cfg.ticker, "name": result.name,
        "price": f"{result.price:.4f}", "currency": result.price_currency, "rating": rec.rating,
        "target_price": f"{rec.target_price:.2f}", "fair_value": f"{rec.fair_value:.4f}", "total_return": f"{rec.total_return:.6f}",
        "agreement": cc.agreement if cc is not None else "", "consensus_target": f"{float(cons):.2f}" if cons else "",
        "engine_version": __version__,
    }


def read_coverage(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh)]


def log_coverage(result, path: str | Path) -> Path:
    """Append this run to the log; a row for the same ticker and date replaces the earlier one."""
    path = Path(path)
    row = coverage_row(result)
    rows = [x for x in read_coverage(path) if not (x.get("ticker") == row["ticker"] and x.get("date") == row["date"])]
    rows.append(row)
    rows.sort(key=lambda x: (x["date"], x["ticker"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for x in rows:
            w.writerow({k: x.get(k, "") for k in COLUMNS})
    return path
