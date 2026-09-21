"""Peer multiples (trading comparables) and multiple-implied valuation.

Multiples are computed consistently from each peer's statements:
EV = market cap + total debt (incl. leases when ``leases_as_debt``) - cash, and
EBITDA / EBIT / revenue from the last reported fiscal year. Currency-neutral
multiples need no FX; market caps are translated to the target's currency for
display only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import CompanyConfig, PeerConfig
from ..retrieve import Snapshot
from .historicals import last_fy_metrics

MULTIPLES = ["ev_sales", "ev_ebitda", "ev_ebit", "pe", "fwd_pe"]
MULTIPLE_LABELS = {"ev_sales": "EV/Sales", "ev_ebitda": "EV/EBITDA", "ev_ebit": "EV/EBIT", "pe": "P/E", "fwd_pe": "P/E (fwd)"}


@dataclass
class ImpliedValue:
    multiple_key: str
    label: str
    multiple: float
    per_share: float
    low_multiple: float
    high_multiple: float
    low: float
    high: float
    basis: str


@dataclass
class CompsResult:
    table: pd.DataFrame
    stats: pd.DataFrame
    company: dict[str, float | None]
    implied: dict[str, ImpliedValue] = field(default_factory=dict)
    company_currency: str = "USD"

    def as_dict(self) -> dict:
        tbl = self.table.replace([np.inf, -np.inf], np.nan)
        return {
            "table": tbl.astype(object).where(tbl.notna(), None).to_dict(orient="records"),
            "stats": {str(k): {str(c): (None if pd.isna(v) else float(v)) for c, v in row.items()} for k, row in self.stats.iterrows()},
            "company": {k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else v) for k, v in self.company.items()},
            "implied": {k: vars(v) for k, v in self.implied.items()},
        }


def _peer_row(peer: PeerConfig, snap: Snapshot, treatment: str, lease_rate: float, fx_to_target: float, divisor: float) -> dict:
    m = last_fy_metrics(snap, treatment=treatment, lease_rate=lease_rate)
    info = snap.info
    mcap = snap.market_cap
    ev = (mcap + (m.get("net_debt") or 0.0) + (m.get("minority") or 0.0)) if (mcap and m) else None
    ev_rep = (mcap + (m.get("net_debt_incl_leases") or 0.0)) if (mcap and m) else None
    row = {
        "ticker": peer.ticker,
        "name": peer.name or str(info.get("shortName") or info.get("longName") or peer.ticker),
        "group": peer.group,
        "currency": snap.currency,
        "fiscal_year": m.get("fiscal_year"),
        "market_cap": (mcap * fx_to_target / divisor) if mcap else None,
        "ev": (ev * fx_to_target / divisor) if ev else None,
        "revenue_growth": m.get("rev_growth"),
        "ebitda_margin": m.get("ebitda_margin"),
        "ebit_margin": m.get("ebit_margin"),
        "ev_sales": _mult(ev, m.get("revenue")),
        "ev_ebitda": _mult(ev, m.get("ebitda")),
        "ev_ebit": _mult(ev, m.get("ebit")),
        "ev_ebitda_reported": _mult(ev_rep, m.get("ebitda_reported")),
        "pe": _pos(info.get("trailingPE"), 80),
        "fwd_pe": _pos(info.get("forwardPE"), 80),
    }
    return row


def _mult(numerator: float | None, denominator: float | None, cap: float = 60.0) -> float | None:
    if not numerator or not denominator or denominator <= 0:
        return None
    v = numerator / denominator
    return float(v) if 0 < v < cap else None  # outside the band = not meaningful


def _pos(v, cap: float = 200.0) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) and 0 < f < cap else None


def build_comps(
    cfg: CompanyConfig,
    company_snap: Snapshot,
    peer_snaps: dict[str, Snapshot],
    fx_rates: dict[str, float],
    *,
    company_metrics: dict[str, float | None],
    net_debt: float,
    minorities: float,
    shares: float,
    price: float | None,
    forward_eps: float | None = None,
) -> CompsResult:
    """``company_metrics`` must contain revenue, ebitda, ebit, eps (reporting units)."""
    rows = []
    for peer in cfg.peers:
        snap = peer_snaps.get(peer.ticker)
        if snap is None:
            continue
        fx = fx_rates.get(snap.currency, 1.0)
        try:
            rows.append(_peer_row(peer, snap, cfg.assumptions.lease_treatment, cfg.assumptions.lease_rate, fx, cfg.units_divisor))
        except Exception:
            continue
    table = pd.DataFrame(rows)
    stats_rows: dict[str, dict] = {}
    if not table.empty:
        for group, sub in [("All", table)] + [(g, table[table["group"] == g]) for g in table["group"].unique()]:
            for stat in ("mean", "median", "p25", "p75"):
                vals = {}
                for m in MULTIPLES + ["revenue_growth", "ebitda_margin", "ebit_margin"]:
                    s = pd.to_numeric(sub[m], errors="coerce").dropna()
                    if s.empty:
                        vals[m] = np.nan
                    elif stat == "mean":
                        vals[m] = float(s.mean())
                    elif stat == "median":
                        vals[m] = float(s.median())
                    elif stat == "p25":
                        vals[m] = float(s.quantile(0.25))
                    else:
                        vals[m] = float(s.quantile(0.75))
                stats_rows[f"{group}|{stat}"] = vals
    stats = pd.DataFrame(stats_rows).T if stats_rows else pd.DataFrame(columns=MULTIPLES)

    # ---- company's own multiples --------------------------------------------
    mcap = (price * shares) if (price and shares) else None
    ev = (mcap + net_debt + minorities) if mcap is not None else None
    cm = company_metrics
    company = {
        "market_cap": mcap,
        "ev": ev,
        "ev_sales": (ev / cm["revenue"]) if (ev and cm.get("revenue")) else None,
        "ev_ebitda": (ev / cm["ebitda"]) if (ev and cm.get("ebitda")) else None,
        "ev_ebit": (ev / cm["ebit"]) if (ev and cm.get("ebit")) else None,
        "pe": (price / cm["eps"]) if (price and cm.get("eps") and cm["eps"] > 0) else None,
        "fwd_pe": (price / forward_eps) if (price and forward_eps and forward_eps > 0) else None,
    }

    # ---- implied values from peer medians ------------------------------------
    implied: dict[str, ImpliedValue] = {}
    if not stats.empty and "All|median" in stats.index:
        med, p25, p75 = stats.loc["All|median"], stats.loc["All|p25"], stats.loc["All|p75"]

        def ev_based(key: str, metric: float | None, basis: str):
            if metric is None or metric <= 0 or pd.isna(med[key]):
                return
            def per_share(mult: float) -> float:
                return (mult * metric - net_debt - minorities) / shares
            implied[key] = ImpliedValue(key, MULTIPLE_LABELS[key], float(med[key]), per_share(float(med[key])),
                                        float(p25[key]), float(p75[key]), per_share(float(p25[key])), per_share(float(p75[key])), basis)

        ev_based("ev_ebitda", cm.get("ebitda"), "LTM EBITDA x peer median")
        ev_based("ev_ebit", cm.get("ebit"), "LTM EBIT x peer median")
        ev_based("ev_sales", cm.get("revenue"), "LTM revenue x peer median")
        eps = cm.get("eps")
        if eps and eps > 0 and not pd.isna(med["pe"]):
            implied["pe"] = ImpliedValue("pe", "P/E", float(med["pe"]), float(med["pe"]) * eps, float(p25["pe"]), float(p75["pe"]),
                                         float(p25["pe"]) * eps, float(p75["pe"]) * eps, "LTM EPS x peer median")
        if forward_eps and forward_eps > 0 and not pd.isna(med["fwd_pe"]):
            implied["fwd_pe"] = ImpliedValue("fwd_pe", "P/E (fwd)", float(med["fwd_pe"]), float(med["fwd_pe"]) * forward_eps,
                                             float(p25["fwd_pe"]), float(p75["fwd_pe"]), float(p25["fwd_pe"]) * forward_eps,
                                             float(p75["fwd_pe"]) * forward_eps, "Forward EPS x peer median")
    return CompsResult(table=table, stats=stats, company=company, implied=implied, company_currency=company_snap.currency)
