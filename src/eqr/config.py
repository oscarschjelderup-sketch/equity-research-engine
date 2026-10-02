"""Configuration models for a research case.

A case is described by a YAML file (see ``configs/``). Everything has a sensible
default so ``eqr run <TICKER>`` works with no config at all; the YAML lets the
analyst take control of peers, forecast drivers, WACC inputs, market slides,
team slide and branding.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class PeerConfig:
    ticker: str
    name: str | None = None
    group: str = "Peers"


@dataclass
class Assumptions:
    """Forecast drivers. ``None`` means "derive from history / consensus"."""

    forecast_years: int = 6
    terminal_growth: float = 0.02
    revenue_growth: list[float] | None = None
    ebitda_margin: list[float] | None = None
    ebitda_margin_target: float | None = None
    da_pct_revenue: float | None = None
    capex_pct_revenue: float | None = None
    capex_pct_terminal: float | None = None  # None -> capex normalises towards D&A x 1.05 when the company is in an investment phase
    nwc_pct_revenue: float | None = None
    tax_rate: float | None = None  # None -> effective rate from the accounts (E&P companies pay far more than the statutory rate)
    statutory_tax_rate: float = 0.22
    lease_treatment: str = "operating"  # operating (pre-IFRS 16, default) | financial (leases as debt)
    lease_rate: float = 0.045  # implicit interest rate on lease liabilities
    mid_year_convention: bool = False
    terminal_method: str = "gordon"  # gordon | value_driver (NOPAT x (1 - g/RONIC) / (WACC - g))
    ronic: float | None = None  # return on new invested capital for value_driver; None -> WACC + 2pp
    valuation_date: str | None = None  # ISO date the DCF is valued at; None -> the run date
    stub_period: bool = True  # discount to the valuation date and count year-1 cash flow from the latest balance sheet
    latest_balance_sheet: bool = True  # net debt from the latest quarterly balance sheet instead of the last annual one
    nowcast: bool = True  # build year-1 revenue growth and margin from the quarters already reported (see analyze/nowcast.py)
    growth_cap: float = 0.20
    growth_floor: float = -0.05
    use_consensus_growth: bool = True


@dataclass
class WaccConfig:
    risk_free: float = 0.038
    equity_risk_premium: float = 0.05
    beta: float | None = None
    beta_method: str = "regression"  # regression | peers (bottom-up: unlevered peer median, relevered) | yahoo | manual
    beta_years: int = 3
    min_r2: float = 0.10  # regression beta is rejected below this R2 (falls back to Yahoo beta)
    blume_adjust: bool = True
    beta_floor: float = 0.6
    beta_cap: float = 1.8
    size_premium: float | str = "auto"  # "auto" = by market cap (0 / 0.75% / 1.5% / 2.5%), or a number
    cost_of_debt_pretax: float | None = None
    debt_weight: float | None = None
    wacc_override: float | None = None


@dataclass
class RecommendationConfig:
    buy_threshold: float = 0.15
    sell_threshold: float = -0.10
    tp_method: str = "dcf"  # dcf | blend
    blend_dcf_weight: float = 0.5
    sensitivity_wacc_step: float = 0.005
    sensitivity_growth_step: float = 0.0025
    tp_rounding: float = 0.5
    roll_forward: bool = True  # 12-month target price: fair value today x (1 + cost of equity) - expected dividend
    roll_forward_months: int = 12
    rating_on_total_return: bool = True  # rate on (target price + dividend) / price - 1
    dividend_source: str = "indicated"  # indicated = Yahoo's indicated annual dividend | last_paid = last fiscal year's cash dividend


@dataclass
class Scenario:
    """Shifts relative to the base case (additive, in decimals: 0.01 = one percentage point)."""

    name: str
    probability: float = 0.0
    growth_shift: float = 0.0
    margin_shift: float = 0.0
    wacc_shift: float = 0.0
    terminal_growth_shift: float = 0.0
    note: str = ""


def default_scenarios() -> list[Scenario]:
    return [
        Scenario("Bear", 0.25, growth_shift=-0.02, margin_shift=-0.015, wacc_shift=0.005, terminal_growth_shift=-0.0025,
                 note="Growth 2pp lower, margin 1.5pp lower, WACC +50bp"),
        Scenario("Base", 0.50, note="Base-case drivers"),
        Scenario("Bull", 0.25, growth_shift=0.02, margin_shift=0.015, wacc_shift=-0.005, terminal_growth_shift=0.0025,
                 note="Growth 2pp higher, margin 1.5pp higher, WACC -50bp"),
    ]


@dataclass
class TeamMember:
    name: str
    school: str = ""
    year: str = ""
    experience: str = ""
    photo: str | None = None


@dataclass
class MarketChart:
    title: str
    type: str = "bar"  # bar | line | pie | stacked
    categories: list[Any] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    value_format: str = ""  # "%", "x", "" (number)
    note: str = ""


@dataclass
class MarketConfig:
    charts: list[MarketChart] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    disruption: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    sources: str = ""


@dataclass
class BrandConfig:
    name: str = "Equity Research Engine"
    analyst: str = ""
    logo: str | None = None
    footer_note: str = "Private and confidential"
    template: str | None = None  # optional .pptx to build on (e.g. a firm template)


@dataclass
class CompanyConfig:
    ticker: str
    name: str | None = None
    short_name: str | None = None
    tagline: str | None = None
    index: str = "^GSPC"
    index_name: str | None = None
    sector_label: str | None = None
    footprint: str | None = None
    business_model: str | None = None
    units_divisor: float = 1e6
    units_label: str | None = None
    peers: list[PeerConfig] = field(default_factory=list)
    assumptions: Assumptions = field(default_factory=Assumptions)
    wacc: WaccConfig = field(default_factory=WaccConfig)
    recommendation: RecommendationConfig = field(default_factory=RecommendationConfig)
    scenarios: list[Scenario] = field(default_factory=default_scenarios)
    appendix: bool = True  # add appendix slides (WACC/DCF build-up, scenarios, peer table)
    allow_unsupported_sector: bool = False  # run banks / insurers / real estate through the FCFF model anyway
    market: MarketConfig = field(default_factory=MarketConfig)
    team: list[TeamMember] = field(default_factory=list)
    brand: BrandConfig = field(default_factory=BrandConfig)
    narrative: dict[str, Any] = field(default_factory=dict)
    history_csv: str | None = None
    oil_sensitivity: str | None = None  # path to an oilbeta.stock/1 factsheet; risk context only, never a driver
    event_title: str | None = None
    date_label: str | None = None
    sources_note: str = "Company reports, Yahoo Finance, Equity Research Engine estimates"

    # ----------------------------------------------------------------- helpers
    @property
    def display_name(self) -> str:
        return self.name or self.ticker

    @property
    def display_short(self) -> str:
        return self.short_name or (self.name or self.ticker).split(" ")[0]


# --------------------------------------------------------------------------- #
# Defaults by exchange
# --------------------------------------------------------------------------- #
INDEX_BY_SUFFIX: dict[str, tuple[str, str]] = {
    ".OL": ("OSEBX.OL", "OSEBX"), ".ST": ("^OMX", "OMX Stockholm 30"), ".CO": ("^OMXC25", "OMX Copenhagen 25"),
    ".HE": ("^OMXH25", "OMX Helsinki 25"), ".L": ("^FTSE", "FTSE 100"), ".DE": ("^GDAXI", "DAX"), ".PA": ("^FCHI", "CAC 40"),
    ".AS": ("^AEX", "AEX"), ".MI": ("FTSEMIB.MI", "FTSE MIB"), ".SW": ("^SSMI", "SMI"), ".TO": ("^GSPTSE", "S&P/TSX"),
    ".AX": ("^AXJO", "ASX 200"), ".HK": ("^HSI", "Hang Seng"), ".T": ("^N225", "Nikkei 225"),
}


def default_index_for(ticker: str) -> tuple[str, str]:
    """Benchmark index by listing suffix (S&P 500 for US tickers and unknown suffixes)."""
    upper = ticker.upper()
    for suffix, pair in INDEX_BY_SUFFIX.items():
        if upper.endswith(suffix):
            return pair
    return "^GSPC", "S&P 500"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _build(cls: type, data: Any) -> Any:
    """Recursively build a dataclass from a plain dict (ignores unknown keys)."""
    if data is None:
        return cls() if _can_default(cls) else None
    if not isinstance(data, dict):
        raise TypeError(f"Expected mapping for {cls.__name__}, got {type(data).__name__}")
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "")
        if f.name == "peers":
            value = [
                _build(PeerConfig, v) if isinstance(v, dict) else PeerConfig(ticker=str(v))
                for v in (value or [])
            ]
        elif f.name == "team":
            value = [_build(TeamMember, v) for v in (value or [])]
        elif f.name == "scenarios":
            value = [_build(Scenario, v) for v in (value or [])] or default_scenarios()
        elif f.name == "charts":
            value = [_build(MarketChart, v) for v in (value or [])]
        elif "Assumptions" in ftype:
            value = _build(Assumptions, value)
        elif "WaccConfig" in ftype:
            value = _build(WaccConfig, value)
        elif "RecommendationConfig" in ftype:
            value = _build(RecommendationConfig, value)
        elif "MarketConfig" in ftype:
            value = _build(MarketConfig, value)
        elif "BrandConfig" in ftype:
            value = _build(BrandConfig, value)
        kwargs[f.name] = value
    return cls(**kwargs)


def _can_default(cls: type) -> bool:
    try:
        cls()
        return True
    except TypeError:
        return False


def load_config(source: str | Path, ticker: str | None = None) -> CompanyConfig:
    """Load a YAML config. ``source`` may be a path or a bare ticker.

    Resolution order for a bare ticker: ``configs/<TICKER>.yaml`` relative to the
    current directory, then the package's bundled ``configs`` folder, then a
    default config.
    """
    path = Path(source)
    if path.suffix.lower() in {".yaml", ".yml"} and path.exists():
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if ticker and "ticker" not in data:
            data["ticker"] = ticker
        return _build(CompanyConfig, data)

    candidate_ticker = ticker or str(source)
    for folder in (Path("configs"), Path(__file__).resolve().parents[2] / "configs"):
        for ext in (".yaml", ".yml"):
            candidate = folder / f"{candidate_ticker}{ext}"
            if candidate.exists():
                return load_config(candidate, ticker=candidate_ticker)
    index, index_name = default_index_for(candidate_ticker)
    return CompanyConfig(ticker=candidate_ticker, index=index, index_name=index_name)


def to_dict(cfg: Any) -> Any:
    """Dataclass -> plain dict (for JSON dumps / dashboards)."""
    if is_dataclass(cfg):
        return {f.name: to_dict(getattr(cfg, f.name)) for f in fields(cfg)}
    if isinstance(cfg, list):
        return [to_dict(v) for v in cfg]
    if isinstance(cfg, dict):
        return {k: to_dict(v) for k, v in cfg.items()}
    return cfg


def default_config_yaml(ticker: str, team: list[dict] | None = None, brand: dict | None = None) -> str:
    """A commented starter config the analyst can edit (``eqr init``)."""
    team_block = (yaml.safe_dump({"team": team}, sort_keys=False, allow_unicode=True) if team
                  else "team:\n  - {name: Analyst Name, school: University, year: 2nd, experience: Experience}\n")
    brand_block = (yaml.safe_dump({"brand": brand}, sort_keys=False, allow_unicode=True) if brand
                   else "brand:\n  name: Equity Research Engine\n  analyst: \"\"\n")
    index, index_name = default_index_for(ticker)
    return f"""# Equity Research Engine case config for {ticker}
ticker: {ticker}
name: null                 # defaults to the Yahoo Finance long name
short_name: null
tagline: null              # cover slide tagline, e.g. "Healthy body, healthy margins"
index: {index}               # benchmark index used for beta and relative performance (chosen from the ticker suffix)
index_name: {index_name}
sector_label: null
footprint: null
business_model: null
units_label: null          # e.g. NOKm / USDm (defaults to <currency>m)

peers:                     # tickers must exist on Yahoo Finance
  # - {{ticker: PEER.OL, name: Peer Name, group: Nordic}}

assumptions:
  forecast_years: 6
  terminal_growth: 0.02
  revenue_growth: null     # explicit list (one per forecast year) or null to derive
  ebitda_margin: null      # explicit list or null
  ebitda_margin_target: null
  da_pct_revenue: null
  capex_pct_revenue: null
  capex_pct_terminal: null # null = capex normalises towards D&A x 1.05 if the company is in an investment phase
  nwc_pct_revenue: null    # net working capital as % of revenue (negative for prepaid models); null = from balance sheet
  tax_rate: null           # null = effective rate from the accounts (22% statutory fallback); set a number to override
  lease_treatment: operating   # operating = pre-IFRS 16 (rent above EBITDA) | financial = leases as debt
  lease_rate: 0.045
  mid_year_convention: false
  terminal_method: gordon  # gordon | value_driver (NOPAT x (1 - g/RONIC) / (WACC - g))
  ronic: null              # return on new capital for value_driver; null -> WACC + 2pp
  valuation_date: null     # null = today; the DCF is discounted to this date (stub period)
  stub_period: true        # count year-1 cash flow only after the latest balance sheet date
  latest_balance_sheet: true   # net debt from the latest quarterly balance sheet
  nowcast: true            # year-1 growth and margin from the reported quarters (year-to-date + last year's remaining quarters)

wacc:
  risk_free: 0.038
  equity_risk_premium: 0.05
  beta: null               # null -> regression vs index (Blume adjusted)
  beta_method: regression  # regression | peers (bottom-up from the peer group) | yahoo | manual
  size_premium: auto       # auto = by market cap (0 / 0.75% / 1.5% / 2.5%), or a number such as 0.01
  cost_of_debt_pretax: null
  debt_weight: null        # null -> market weights

recommendation:
  buy_threshold: 0.15
  sell_threshold: -0.10
  tp_method: dcf           # dcf | blend
  roll_forward: true       # 12-month target price = fair value x (1 + cost of equity) - expected dividend

scenarios:                 # shifts vs the base case, in decimals (0.01 = 1 percentage point)
  - {{name: Bear, probability: 0.25, growth_shift: -0.02, margin_shift: -0.015, wacc_shift: 0.005, terminal_growth_shift: -0.0025}}
  - {{name: Base, probability: 0.50}}
  - {{name: Bull, probability: 0.25, growth_shift: 0.02, margin_shift: 0.015, wacc_shift: -0.005, terminal_growth_shift: 0.0025}}

appendix: true             # add appendix slides (WACC and DCF build-up, scenarios, peer table)

market:                    # analyst-supplied data for the Market overview slide; empty = peer benchmarking
  charts: []
  opportunities: []
  disruption: []
  threats: []
  sources: ""

{team_block}
{brand_block}"""
