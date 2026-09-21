"""Orchestrates the three phases: retrieve -> analyze -> create."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .analyze import (
    AnalysisResult,
    FootballFieldBar,
    build_comps,
    build_forecast,
    build_history,
    build_multiple_history,
    compute_wacc,
    cross_check,
    derive_drivers,
    football_field,
    recommend,
    reverse_dcf,
    run_dcf,
    run_scenarios,
)
from .config import CompanyConfig, load_config
from .errors import check_supported, industry_caution
from .retrieve import DiskCache, Snapshot, fetch_fx, fetch_prices, fetch_snapshot, load_history_file

log = logging.getLogger(__name__)
Progress = Callable[[str], None]


def _fill_from_info(cfg: CompanyConfig, snap: Snapshot) -> None:
    info = snap.info
    cfg.name = cfg.name or snap.name
    cfg.sector_label = cfg.sector_label or str(info.get("industry") or info.get("sector") or "")
    cfg.footprint = cfg.footprint or str(info.get("country") or "")
    cfg.units_label = cfg.units_label or f"{snap.currency}m"
    cfg.index_name = cfg.index_name or cfg.index


def run_analysis(cfg: CompanyConfig, cache: DiskCache | None = None, progress: Progress = log.info) -> AnalysisResult:
    cache = cache or DiskCache()
    warnings: list[str] = []

    # ------------------------------------------------------------ retrieve
    progress(f"Retrieving {cfg.ticker} from Yahoo Finance")
    snap = fetch_snapshot(cfg.ticker, cache)
    check_supported(snap.name, snap.info.get("sector"), allow=cfg.allow_unsupported_sector)
    caution = industry_caution(snap.info.get("industry"))
    if caution:
        warnings.append(caution)
    _fill_from_info(cfg, snap)
    index_prices = fetch_prices(cfg.index, cache)
    if index_prices is None:
        warnings.append(f"Index {cfg.index} unavailable; beta falls back to Yahoo's beta.")
    extra = load_history_file(cfg.history_csv) if cfg.history_csv else None

    # ------------------------------------------------------------ historicals
    hist = build_history(snap, cfg, extra)
    price = snap.price
    if price is None:
        raise RuntimeError("No share price available.")
    listing_ccy = snap.price_currency
    if listing_ccy == "GBp":
        price, listing_ccy = price / 100.0, "GBP"
    fin_ccy = snap.currency
    # Listing currency vs reporting currency (e.g. Mowi: NOK share price, EUR accounts). All money
    # stays in the reporting currency; per-share values are expressed in the listing currency by
    # working with "effective shares" = shares x FX(reporting per listing unit).
    fx = fetch_fx(listing_ccy, fin_ccy, cache) if listing_ccy != fin_ccy else 1.0
    if fx == 1.0 and listing_ccy != fin_ccy:
        warnings.append(f"FX {listing_ccy}/{fin_ccy} unavailable; per-share values may be in the wrong currency.")
    shares_raw = snap.shares_outstanding
    if not shares_raw:
        shares_raw = float(hist["shares"].dropna().iloc[-1]) * 1e6 if hist["shares"].notna().any() else None
    if not shares_raw:
        raise RuntimeError("Shares outstanding unavailable.")
    shares_real = shares_raw / cfg.units_divisor
    shares = shares_real * fx  # effective shares: reporting-currency equity / shares -> listing-currency value per share
    market_cap = price * shares
    last = hist.iloc[-1]
    net_debt = float(last["net_debt"]) if pd.notna(last["net_debt"]) else 0.0
    minorities = float(last["minority"]) if pd.notna(last.get("minority")) else 0.0
    ev = market_cap + net_debt + minorities
    total_debt = float(last["debt_for_wacc"]) if pd.notna(last["debt_for_wacc"]) else max(net_debt, 0.0)

    # ------------------------------------------------------------ forecast + WACC + DCF
    progress("Building forecast, WACC and DCF")
    drivers = derive_drivers(hist, cfg, snap)
    forecast = build_forecast(hist, drivers)
    fx_usd = fetch_fx(snap.currency, "USD", cache)
    wacc = compute_wacc(
        cfg, hist, market_cap=market_cap, total_debt=total_debt, yahoo_beta=snap.info.get("beta"),
        stock_prices=snap.prices["Close"] if snap.prices is not None else None,
        index_prices=index_prices["Close"] if index_prices is not None else None,
        market_cap_usd=market_cap * cfg.units_divisor * fx_usd,
    )
    a = cfg.assumptions
    ronic = (float(a.ronic) if a.ronic is not None else wacc.wacc + 0.02) if a.terminal_method == "value_driver" else None
    dcf = run_dcf(
        forecast, wacc=wacc.wacc, terminal_growth=drivers.terminal_growth, net_debt=net_debt, shares=shares,
        minorities=minorities, mid_year=a.mid_year_convention, price=price,
        wacc_step=cfg.recommendation.sensitivity_wacc_step, growth_step=cfg.recommendation.sensitivity_growth_step,
        terminal_method=a.terminal_method, ronic=ronic,
    )
    scenarios, weighted_value = run_scenarios(hist, drivers, cfg, wacc.wacc, net_debt=net_debt, shares=shares,
                                              minorities=minorities, price=price, ronic=ronic)
    reverse = reverse_dcf(hist, drivers, cfg, wacc.wacc, net_debt=net_debt, shares=shares, minorities=minorities,
                          price=price, ronic=ronic)

    # ------------------------------------------------------------ peers
    peer_snaps: dict[str, Snapshot] = {}
    fx_rates: dict[str, float] = {snap.currency: 1.0}
    if cfg.peers:
        progress(f"Retrieving {len(cfg.peers)} peers")
    for peer in cfg.peers:
        try:
            ps = fetch_snapshot(peer.ticker, cache, with_estimates=False, price_period="1y")
        except Exception as exc:
            warnings.append(f"Peer {peer.ticker} skipped: {exc}")
            continue
        peer_snaps[peer.ticker] = ps
        ccy = ps.currency
        if ccy not in fx_rates:
            fx_rates[ccy] = fetch_fx(ccy, snap.currency, cache)
    forward_eps = _forward_eps(snap, forecast, hist, shares, cfg, fx)
    company_metrics = {"revenue": float(last["revenue"]), "ebitda": float(last["ebitda"]), "ebit": float(last["ebit"]),
                       "eps": float(last["eps"]) / fx if pd.notna(last["eps"]) else None}  # EPS in listing currency
    comps = build_comps(cfg, snap, peer_snaps, fx_rates, company_metrics=company_metrics, net_debt=net_debt,
                        minorities=minorities, shares=shares, price=price, forward_eps=forward_eps)
    if comps.table.empty and cfg.peers:
        warnings.append("No peer data could be retrieved; multiples valuation omitted.")

    # ------------------------------------------------------------ recommendation
    sc_values = [s.value_per_share for s in scenarios if np.isfinite(s.value_per_share)]
    football = football_field(snap.info, dcf, comps, price, (min(sc_values), max(sc_values)) if len(sc_values) > 1 else None)
    # expected dividend per share over the next 12 months (listing currency): last year's cash dividend
    div = hist["dividends"].abs().dropna()
    dps = float(div.iloc[-1]) / shares if (len(div) and shares) else 0.0
    rec = recommend(cfg, price, dcf, comps, listing_ccy, cost_of_equity=wacc.cost_of_equity, dps=dps)
    fwd = _forward_multiples(forecast, hist, ev, price, shares, cfg, fx)

    # ------------------------------------------------------------ own history and cross-check
    fy_month = int(pd.Timestamp(snap.income.columns[0]).month) if snap.income is not None and len(snap.income.columns) else 12
    mult_hist = build_multiple_history(hist, snap.prices, fx=fx, shares_now=shares, net_debt_now=net_debt, minorities_now=minorities,
                                       fiscal_year_end_month=fy_month, units_divisor=cfg.units_divisor)
    if mult_hist is not None and "ev_ebitda" in mult_hist.implied:
        iv, st = mult_hist.implied["ev_ebitda"], mult_hist.stats["ev_ebitda"]
        lo_v, hi_v = sorted([iv["low"], iv["high"]])
        if np.isfinite(lo_v) and np.isfinite(hi_v) and hi_v > 0:
            bar = FootballFieldBar(f"Own EV/EBITDA band ({st['years']:.1f} years)", max(lo_v, 0.0), hi_v)
            first_peer = next((i for i, b in enumerate(football) if "peer" in b.label), len(football))
            football.insert(first_peer, bar)
    last_margin = float(last["ebitda_margin"]) if pd.notna(last["ebitda_margin"]) else float("nan")
    if np.isfinite(last_margin) and (last_margin > 0.80 or last_margin < 0):
        warnings.append(f"EBITDA margin of {last_margin:.0%} in the last fiscal year: check the data (gains booked in EBITDA, a narrow revenue "
                        "definition, or a loss-making year) before trusting the forecast.")
    explicit_fcf = forecast[forecast.index != "TV"]["ufcf"]
    if (explicit_fcf < 0).sum() > len(explicit_fcf) / 2:
        warnings.append("Free cash flow is negative in most forecast years: the value rests entirely on the terminal year.")
    if rec.rating == "NOT RATED":
        warnings.append("The DCF equity value is not positive, so no target price is set. Typical causes: a holding company that "
                        "consolidates subsidiaries' debt, a loss-making business, or a capex cycle the default drivers extrapolate for ever.")
    elif dcf.tv_share_of_ev > 0.95:
        warnings.append(f"Terminal value is {dcf.tv_share_of_ev:.0%} of enterprise value: the explicit forecast years add almost nothing, "
                        "so the valuation is a bet on the terminal assumptions.")
    n_an = snap.info.get("numberOfAnalystOpinions")
    check = cross_check(fair_value=rec.fair_value, target_price=rec.target_price, multiples_value=rec.multiples_value,
                        consensus_target=(snap.price_targets or {}).get("mean"), n_analysts=int(n_an) if n_an else None, currency=listing_ccy)
    if check.agreement == "low":
        warnings.append(f"Low agreement between valuation anchors: {check.message}.")

    result = AnalysisResult(
        cfg=cfg, snapshot=snap, hist=hist, forecast=forecast, drivers=drivers, wacc=wacc, dcf=dcf, comps=comps,
        football=football, recommendation=rec, price=price, shares=shares, market_cap=market_cap, net_debt=net_debt,
        minorities=minorities, enterprise_value=ev, currency=fin_ccy, units_label=cfg.units_label or f"{fin_ccy}m",
        prices=snap.prices, index_prices=index_prices, forward_multiples=fwd, warnings=warnings,
        price_currency=listing_ccy, fx_reporting_per_listing=fx, shares_real=shares_real,
        scenarios=scenarios, scenario_weighted_value=weighted_value, reverse_dcf=reverse,
        crosscheck=check, multiple_history=mult_hist,
    )
    return result


def _forward_eps(snap: Snapshot, forecast: pd.DataFrame, hist: pd.DataFrame, shares: float, cfg: CompanyConfig, fx: float = 1.0) -> float | None:
    """Next-year EPS in the *listing* currency (consensus if available, else the model)."""
    ee = snap.earnings_estimate
    if ee is not None and not ee.empty and "avg" in ee.columns:
        rows = {str(i): r for i, r in ee.iterrows()}
        for key in ("0y", "+1y"):
            r = rows.get(key)
            if r is not None and pd.notna(r.get("avg")) and float(r["avg"]) > 0:
                v = float(r["avg"])
                if snap.info.get("currency") == "GBp":
                    v = v / 100.0
                return v / fx  # consensus EPS is quoted in the reporting currency
    return _model_eps(forecast, hist, shares, cfg, 0)


def _model_eps(forecast: pd.DataFrame, hist: pd.DataFrame, shares: float, cfg: CompanyConfig, i: int) -> float | None:
    explicit = forecast[forecast.index != "TV"]
    if i >= len(explicit) or not shares:
        return None
    interest = float(hist["interest_ex_leases"].dropna().iloc[-1]) if hist["interest_ex_leases"].notna().any() else 0.0
    ebit = float(explicit["ebit"].iloc[i])
    ni = (ebit - interest) * (1 - float(explicit["tax_rate_used"].iloc[i]))
    return ni / shares


def _forward_multiples(forecast: pd.DataFrame, hist: pd.DataFrame, ev: float, price: float, shares: float, cfg: CompanyConfig,
                       fx: float = 1.0) -> pd.DataFrame:
    rows = {}
    explicit = forecast[forecast.index != "TV"]
    last_year = int(hist.index[-1])
    for label, frame, i in [(f"{last_year}A", hist.iloc[-1], None)] + [(f"{int(y)}E", explicit.loc[y], k) for k, y in enumerate(explicit.index[:3])]:
        eps = (float(hist["eps"].iloc[-1]) / fx if pd.notna(hist["eps"].iloc[-1]) else None) if i is None else _model_eps(forecast, hist, shares, cfg, i)
        rows[label] = {
            "EV/Sales": ev / float(frame["revenue"]) if frame["revenue"] else np.nan,
            "EV/EBITDA": ev / float(frame["ebitda"]) if frame["ebitda"] and frame["ebitda"] > 0 else np.nan,
            "EV/EBIT": ev / float(frame["ebit"]) if frame["ebit"] and frame["ebit"] > 0 else np.nan,
            "P/E": price / eps if eps and eps > 0 else np.nan,
            "FCF yield": float(frame["ufcf"]) / (price * shares) if price and shares else np.nan,
        }
    return pd.DataFrame(rows)


def run_case(
    source: str | Path,
    out_dir: str | Path = "output",
    *,
    narrative: str = "rules",
    outputs: tuple[str, ...] = ("deck", "excel", "dashboard", "json"),
    cache_ttl_hours: float = 24.0,
    no_cache: bool = False,
    template: str | None = None,
    model: str | None = None,
    progress: Progress = log.info,
) -> dict[str, Path]:
    cfg = load_config(source)
    if template:
        cfg.brand.template = template
    cache = DiskCache(ttl_hours=cache_ttl_hours, enabled=not no_cache)
    result = run_analysis(cfg, cache, progress)

    from .narrative import generate_narrative

    progress(f"Writing narrative ({narrative})")
    result.narrative, result.narrative_mode = generate_narrative(result, mode=narrative, model=model)

    out = Path(out_dir) / cfg.ticker
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if "json" in outputs:
        p = out / "analysis.json"
        p.write_text(result.to_json(), encoding="utf-8")
        paths["json"] = p
    if "deck" in outputs:
        from .create.deck import build_deck

        progress("Building PowerPoint deck")
        paths["deck"] = build_deck(result, out / f"{cfg.ticker}_deck.pptx", charts_dir=out / "charts")
    if "excel" in outputs:
        from .create.excel import build_excel

        progress("Building Excel model")
        paths["excel"] = build_excel(result, out / f"{cfg.ticker}_model.xlsx")
    if "dashboard" in outputs:
        from .create.dashboard import build_dashboard

        progress("Building dashboard")
        paths["dashboard"] = build_dashboard(result, out / f"{cfg.ticker}_dashboard.html")
    return paths
