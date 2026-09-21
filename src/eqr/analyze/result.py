"""The single object handed from *analyze* to *create*."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..config import CompanyConfig, to_dict
from ..retrieve import Snapshot
from .comps import CompsResult
from .dcf import DcfResult
from .forecast import Drivers
from .recommendation import FootballFieldBar, Recommendation
from .wacc import WaccResult


@dataclass
class AnalysisResult:
    cfg: CompanyConfig
    snapshot: Snapshot
    hist: pd.DataFrame
    forecast: pd.DataFrame
    drivers: Drivers
    wacc: WaccResult
    dcf: DcfResult
    comps: CompsResult
    football: list[FootballFieldBar]
    recommendation: Recommendation
    price: float
    shares: float
    market_cap: float
    net_debt: float
    minorities: float
    enterprise_value: float
    currency: str
    units_label: str
    prices: pd.DataFrame | None
    index_prices: pd.DataFrame | None
    as_of: date = field(default_factory=date.today)
    narrative: dict[str, Any] = field(default_factory=dict)
    narrative_mode: str = "rules"
    forward_multiples: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)
    price_currency: str = ""  # listing currency for the share price and all per-share values
    fx_reporting_per_listing: float = 1.0  # reporting-currency units per listing-currency unit
    shares_real: float | None = None  # actual shares outstanding (units); ``shares`` is FX-adjusted
    scenarios: list = field(default_factory=list)  # list[ScenarioResult]
    scenario_weighted_value: float | None = None
    reverse_dcf: Any = None  # ReverseDcf
    crosscheck: Any = None  # CrossCheck
    multiple_history: Any = None  # MultipleHistory

    def __post_init__(self):
        if not self.price_currency:
            self.price_currency = self.currency
        if self.shares_real is None:
            self.shares_real = self.shares

    # ------------------------------------------------------------------ views
    @property
    def name(self) -> str:
        return self.cfg.name or self.snapshot.name

    @property
    def dual_currency(self) -> bool:
        return self.price_currency != self.currency

    @property
    def last_actual_year(self) -> int:
        return int(self.hist.index[-1])

    def year_label(self, year: int | str) -> str:
        if year == "TV":
            return "TV"
        y = int(year)
        return f"{y}A" if y <= self.last_actual_year else f"{y}E"

    def combined_table(self) -> pd.DataFrame:
        """Historical + forecast rows for the financials table (index: year label)."""
        cols = ["revenue", "growth", "ebitda", "ebitda_margin", "ebit", "ebit_margin", "nopat", "nopat_margin", "ufcf", "ufcf_margin",
                "da", "capex", "nwc_change", "tax"]
        h = self.hist.reindex(columns=cols)
        f = self.forecast.reindex(columns=cols)
        h.index = [self.year_label(y) for y in h.index]
        f.index = [self.year_label(y) for y in f.index]
        return pd.concat([h, f])

    def relative_performance(self) -> pd.DataFrame | None:
        if self.prices is None or self.index_prices is None:
            return None
        s = self.prices["Close"].dropna().copy()
        i = self.index_prices["Close"].dropna().copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        i.index = pd.to_datetime(i.index).tz_localize(None).normalize()
        df = pd.concat([s.rename("stock"), i.rename("index")], axis=1, join="inner").dropna()
        if df.empty:
            return None
        return df / df.iloc[0] * 100.0

    # ------------------------------------------------------------------ json
    def to_json_dict(self) -> dict[str, Any]:
        def clean(o: Any) -> Any:
            if isinstance(o, dict):
                return {str(k): clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [clean(v) for v in o]
            if isinstance(o, (np.floating, float)):
                return None if (o is None or math.isnan(float(o)) or math.isinf(float(o))) else float(o)
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, pd.Timestamp):
                return o.strftime("%Y-%m-%d")
            if isinstance(o, date):
                return o.isoformat()
            return o

        def frame(df: pd.DataFrame | None) -> dict | None:
            if df is None:
                return None
            d = df.replace([np.inf, -np.inf], np.nan)
            return {"index": [str(i) for i in d.index], "columns": list(map(str, d.columns)),
                    "data": clean(d.astype(object).where(d.notna(), None).values.tolist())}

        rel = self.relative_performance()
        prices = None
        if self.prices is not None:
            p = self.prices["Close"].dropna()
            prices = {"dates": [pd.Timestamp(i).strftime("%Y-%m-%d") for i in p.index], "close": clean(p.values.tolist())}
        return clean({
            "as_of": self.as_of,
            "company": {
                "ticker": self.cfg.ticker, "name": self.name, "short_name": self.cfg.display_short, "currency": self.currency,
                "price_currency": self.price_currency, "fx_reporting_per_listing": self.fx_reporting_per_listing,
                "units": self.units_label, "price": self.price, "shares": self.shares_real, "market_cap": self.market_cap,
                "net_debt": self.net_debt, "minorities": self.minorities, "enterprise_value": self.enterprise_value,
                "sector": self.snapshot.info.get("sector"), "industry": self.snapshot.info.get("industry"),
                "country": self.snapshot.info.get("country"), "employees": self.snapshot.info.get("fullTimeEmployees"),
                "website": self.snapshot.info.get("website"), "summary": self.snapshot.info.get("longBusinessSummary"),
                "officers": self.snapshot.officers[:5],
                "week52_low": self.snapshot.info.get("fiftyTwoWeekLow"), "week52_high": self.snapshot.info.get("fiftyTwoWeekHigh"),
                "consensus_target": self.snapshot.price_targets, "dividend_yield": self.snapshot.info.get("dividendYield"),
            },
            "hist": frame(self.hist), "forecast": frame(self.forecast), "combined": frame(self.combined_table()),
            "drivers": vars(self.drivers), "wacc": self.wacc.as_dict(), "dcf": self.dcf.as_dict(), "comps": self.comps.as_dict(),
            "football": [vars(b) for b in self.football], "recommendation": self.recommendation.as_dict(),
            "scenarios": [s.as_dict() for s in self.scenarios], "scenario_weighted_value": self.scenario_weighted_value,
            "reverse_dcf": self.reverse_dcf.as_dict() if self.reverse_dcf is not None else None,
            "crosscheck": self.crosscheck.as_dict() if self.crosscheck is not None else None,
            "multiple_history": self.multiple_history.as_dict() if self.multiple_history is not None else None,
            "shares_effective": self.shares,
            "forward_multiples": frame(self.forward_multiples), "relative_performance": frame(rel), "prices": prices,
            "narrative": self.narrative, "narrative_mode": self.narrative_mode, "config": to_dict(self.cfg), "warnings": self.warnings,
        })

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_json_dict(), indent=indent, ensure_ascii=False, default=str)
