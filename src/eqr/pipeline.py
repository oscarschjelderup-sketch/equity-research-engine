"""Orchestrates the three phases: retrieve -> analyze -> create."""
from __future__ import annotations

import datetime as dt
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
from .analyze.comps import forward_multiples
from .analyze.consensus import build_consensus_view
from .analyze.forecast import model_eps
from .analyze.historicals import fiscal_year_end
from .analyze.ltm import latest_figures
from .analyze.multiples import consensus_forward, estimate_currency
from .analyze.nowcast import nowcast_year
from .analyze.scenarios import value_drivers
from .config import CompanyConfig, load_config
from .errors import check_supported, industry_caution
from .retrieve import DiskCache, Snapshot, fetch_extras, fetch_fx, fetch_prices, fetch_snapshot, load_history_file

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
    oil = None
    if cfg.oil_sensitivity:
        from .retrieve import OilFactsheetError, load_oil_sensitivity

        try:
            oil = load_oil_sensitivity(cfg.oil_sensitivity)
            progress(f"Oil sensitivity: total beta {oil.beta_total:+.2f} over the {oil.window}")
        except OilFactsheetError as exc:     # context, not a driver: never take the case down with it
            warnings.append(f"Oil sensitivity not loaded: {exc}")

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
    a = cfg.assumptions

    # ------------------------------------------------------------ latest figures and valuation date
    fy_end = fiscal_year_end(snap) or pd.Timestamp(f"{int(hist.index[-1])}-12-31")
    try:
        extras = fetch_extras(cfg.ticker, cache)
    except Exception as exc:  # the case still runs on annual figures
        extras = None
        warnings.append(f"Quarterly balance sheet and calendar unavailable ({exc}); using the last annual balance sheet.")

    def fy_value(key: str) -> float | None:
        v = last.get(key)
        return float(v) if v is not None and pd.notna(v) else None

    fy = {k: fy_value(k) for k in ("revenue", "ebitda", "ebit", "ebitda_reported", "ebit_reported", "lease_cost", "lease_interest", "net_debt", "minority")}
    fy["net_debt"] = fy["net_debt"] or 0.0
    fy["minority"] = fy["minority"] or 0.0
    latest = latest_figures(fy, fy_end, snap.quarterly_income, extras.quarterly_balance if extras is not None else None,
                            divisor=cfg.units_divisor, treatment=a.lease_treatment, use_balance=a.latest_balance_sheet)
    net_debt = float(latest.net_debt if latest.net_debt is not None else fy["net_debt"])
    minorities = float(latest.minority if latest.minority is not None else fy["minority"])
    ev = market_cap + net_debt + minorities
    total_debt = float(last["debt_for_wacc"]) if pd.notna(last["debt_for_wacc"]) else max(net_debt, 0.0)
    valuation_date = dt.date.fromisoformat(a.valuation_date) if a.valuation_date else dt.date.today()
    balance_date = dt.date.fromisoformat(latest.net_debt_date) if latest.net_debt_date else fy_end.date()
    balance_offset = max((balance_date - fy_end.date()).days / 365.25, 0.0)
    elapsed = (valuation_date - fy_end.date()).days / 365.25
    valuation_offset = elapsed if a.stub_period else balance_offset  # no stub: value at the balance-sheet date
    if valuation_offset > 1.0:
        warnings.append(f"The last annual accounts ({fy_end.date():%d.%m.%Y}) are more than a year old: the first forecast year is already "
                        "behind the valuation date. Add the new fiscal year (history_csv) or wait for the annual report.")
    valuation_offset = min(max(valuation_offset, 0.0), 1.0)
    balance_offset = min(balance_offset, valuation_offset)
    timing = {"valuation_offset": valuation_offset, "balance_offset": balance_offset}

    # ------------------------------------------------------------ forecast (year 1 nowcast from the reported quarters)
    progress("Building forecast")
    company_fwd_est = consensus_forward(snap.revenue_estimate, snap.earnings_estimate, fy_end, valuation_date, float(last["revenue"]) * cfg.units_divisor,
                                        fx_listing_to_reporting=fx)
    # Yahoo's estimate table can be in either currency (see multiples.estimate_currency); these factors put it on the model's
    est_ccy, rev_to_reporting = estimate_currency(snap.revenue_estimate, float(last["revenue"]) * cfg.units_divisor, fx)
    eps_to_listing = 1.0 if est_ccy == "listing" else 1.0 / fx
    nowcast = None
    if a.nowcast:
        g_cons = (company_fwd_est.revenue_fy0 / cfg.units_divisor / float(last["revenue"]) - 1) if (company_fwd_est and company_fwd_est.revenue_fy0) else None
        nowcast, why = nowcast_year(fy, fy_end, snap.quarterly_income, consensus_growth_fy0=g_cons, divisor=cfg.units_divisor,
                                    treatment=a.lease_treatment, growth_floor=a.growth_floor, growth_cap=a.growth_cap)
        if nowcast is None and "distorted" in why:
            warnings.append(f"Nowcast refused: {why}.")
        if nowcast is not None and nowcast.margin_shift_capped:
            warnings.append(f"The year-to-date EBITDA margin moved {(nowcast.margin_ytd - nowcast.margin_prior_ytd) * 100:+.1f}pp against a year earlier; "
                            f"the nowcast caps the change at {nowcast.margin_shift * 100:+.1f}pp. Check whether the quarters carry one-offs.")
    drivers = derive_drivers(hist, cfg, snap, nowcast=nowcast, fx_listing_to_reporting=fx)
    forecast = build_forecast(hist, drivers)
    nd_fy = float(fy["net_debt"])
    ebitda_ref = abs(float(last["ebitda"])) if pd.notna(last["ebitda"]) and last["ebitda"] else None
    if a.latest_balance_sheet and latest.net_debt is not None and ebitda_ref and abs(net_debt - nd_fy) > 0.5 * ebitda_ref:
        warnings.append(f"Net debt moved from {nd_fy:,.0f} at the year-end to {net_debt:,.0f} at {latest.net_debt_date} (more than half a year's "
                        "EBITDA): seasonal working capital or a dividend may reverse by the year-end, which the even spread of year-1 cash flow "
                        "does not capture. Set latest_balance_sheet: false to value on the year-end balance sheet.")

    # ------------------------------------------------------------ peers (before WACC: they feed the bottom-up beta)
    peer_snaps: dict[str, Snapshot] = {}
    peer_balances: dict[str, pd.DataFrame | None] = {}
    fx_rates: dict[str, float] = {snap.currency: 1.0}
    if cfg.peers:
        progress(f"Retrieving {len(cfg.peers)} peers")
    peer_fx_listing: dict[str, float] = {}
    for peer in cfg.peers:
        try:
            ps = fetch_snapshot(peer.ticker, cache, with_estimates=True, price_period="1y")
        except Exception as exc:
            warnings.append(f"Peer {peer.ticker} skipped: {exc}")
            continue
        peer_snaps[peer.ticker] = ps
        try:
            peer_balances[peer.ticker] = fetch_extras(peer.ticker, cache, full=False).quarterly_balance
        except Exception:
            peer_balances[peer.ticker] = None
        ccy = ps.currency
        if ccy not in fx_rates:
            fx_rates[ccy] = fetch_fx(ccy, snap.currency, cache)
        # Yahoo's market cap is in the listing currency; the statements are in the reporting currency
        listing = "GBP" if ps.price_currency == "GBp" else ps.price_currency
        peer_fx_listing[peer.ticker] = fetch_fx(listing, ccy, cache) if listing != ccy else 1.0
        if listing != ccy and peer_fx_listing[peer.ticker] == 1.0:
            warnings.append(f"Peer {peer.ticker}: FX {listing}/{ccy} unavailable, its enterprise value mixes currencies.")
    # the target's own forward multiples, calendarised exactly like the peers'
    ltm_margin = (latest.ebitda / latest.revenue) if (latest.ebitda is not None and latest.revenue) else None
    company_forward = forward_multiples(company_fwd_est, price_listing=price, ev=ev, mcap=market_cap, ltm_margin=ltm_margin, divisor=cfg.units_divisor)
    company_forward["revenue_ntm"] = company_fwd_est.revenue_ntm / cfg.units_divisor if (company_fwd_est and company_fwd_est.revenue_ntm) else None
    forward_eps = company_forward.get("eps_ntm") or _forward_eps(snap, forecast, hist, shares, cfg, fx)
    fcf_levered = None
    if pd.notna(last.get("ocf")) and pd.notna(last.get("capex")):
        fcf_levered = float(last["ocf"] + last["capex"] - (last.get("lease_principal") or 0.0 if a.lease_treatment == "operating" else 0.0))
    div_rate = _num(snap.info.get("dividendRate"))  # listing currency (pounds, not pence, for London)
    company_metrics = {"revenue": latest.revenue, "ebitda": latest.ebitda, "ebit": latest.ebit, "eps": _trailing_eps(snap, last, fx),
                       "growth": float(last["growth"]) if pd.notna(last["growth"]) else None, "fcf": fcf_levered,
                       "div_yield": (div_rate / price) if (div_rate is not None and price and 0 < div_rate / price < 0.20) else None}
    comps = build_comps(cfg, snap, peer_snaps, fx_rates, company_metrics=company_metrics, net_debt=net_debt,
                        minorities=minorities, shares=shares, price=price, forward_eps=forward_eps, peer_balances=peer_balances,
                        peer_fx_listing=peer_fx_listing, valuation_date=valuation_date, company_forward=company_forward)
    comps.company["basis"] = latest.basis
    comps.company["forward_basis"] = (f"NTM = {company_fwd_est.weight_fy0:.0%} of FY to {company_fwd_est.fy0_end[:7]} + the rest of the following year"
                                      if company_fwd_est else "no consensus")
    if comps.table.empty and cfg.peers:
        warnings.append("No peer data could be retrieved; multiples valuation omitted.")
    peer_betas = comps.table[["ticker", "beta", "debt_to_equity"]].to_dict(orient="records") if not comps.table.empty else []

    # ------------------------------------------------------------ WACC + DCF
    progress("Building WACC and DCF")
    fx_usd = fetch_fx(snap.currency, "USD", cache)
    wacc = compute_wacc(
        cfg, hist, market_cap=market_cap, total_debt=total_debt, yahoo_beta=snap.info.get("beta"),
        stock_prices=snap.prices["Close"] if snap.prices is not None else None,
        index_prices=index_prices["Close"] if index_prices is not None else None,
        market_cap_usd=market_cap * cfg.units_divisor * fx_usd, peer_betas=peer_betas,
    )
    if cfg.wacc.beta_method == "peers" and wacc.peer_beta is None:
        warnings.append("beta_method is 'peers' but fewer than three peers have a usable beta; the regression / Yahoo beta is used instead.")
    ronic = (float(a.ronic) if a.ronic is not None else wacc.wacc + 0.02) if a.terminal_method == "value_driver" else None
    dcf = run_dcf(
        forecast, wacc=wacc.wacc, terminal_growth=drivers.terminal_growth, net_debt=net_debt, shares=shares,
        minorities=minorities, mid_year=a.mid_year_convention, price=price,
        wacc_step=cfg.recommendation.sensitivity_wacc_step, growth_step=cfg.recommendation.sensitivity_growth_step,
        terminal_method=a.terminal_method, ronic=ronic, **timing,
    )
    scenarios, weighted_value = run_scenarios(hist, drivers, cfg, wacc.wacc, net_debt=net_debt, shares=shares,
                                              minorities=minorities, price=price, ronic=ronic, **timing)
    reverse = reverse_dcf(hist, drivers, cfg, wacc.wacc, net_debt=net_debt, shares=shares, minorities=minorities,
                          price=price, ronic=ronic, **timing)
    tornado = value_drivers(hist, drivers, cfg, wacc.wacc, net_debt=net_debt, shares=shares, minorities=minorities, ronic=ronic, **timing)

    # ------------------------------------------------------------ recommendation
    sc_values = [s.value_per_share for s in scenarios if np.isfinite(s.value_per_share)]
    football = football_field(snap.info, dcf, comps, price, (min(sc_values), max(sc_values)) if len(sc_values) > 1 else None)
    if comps.regression is not None and comps.regression.r2 < 0.15:
        warnings.append(f"The peer multiples regression explains little (R² {comps.regression.r2:.2f} across {comps.regression.n} peers): "
                        "growth and margin do not set EV/EBITDA in this group, so the regression-implied value is weak evidence.")
    dps, dps_source = _expected_dps(snap, hist, shares, price, cfg)
    rec = recommend(cfg, price, dcf, comps, listing_ccy, cost_of_equity=wacc.cost_of_equity, dps=dps)
    fwd = _forward_multiples(forecast, hist, ev, price, shares, cfg, fx)

    # ------------------------------------------------------------ consensus, revisions, catalysts
    explicit = forecast[forecast.index != "TV"]
    consensus = build_consensus_view(
        revenue_estimate=snap.revenue_estimate, earnings_estimate=snap.earnings_estimate,
        eps_trend=extras.eps_trend if extras is not None else None, eps_revisions=extras.eps_revisions if extras is not None else None,
        calendar=extras.calendar if extras is not None else None, last_fy=int(hist.index[-1]), last_fy_revenue=float(last["revenue"]),
        forecast_years=[int(y) for y in explicit.index], our_revenue={int(y): float(v) for y, v in explicit["revenue"].items()},
        our_eps={int(y): _model_eps(forecast, hist, shares, cfg, i) for i, y in enumerate(explicit.index)},
        units_divisor=cfg.units_divisor, eps_to_listing=eps_to_listing, today=valuation_date, revenue_to_reporting=rev_to_reporting,
    )

    # ------------------------------------------------------------ own history and cross-check
    fy_month = int(fy_end.month)
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
        crosscheck=check, multiple_history=mult_hist, oil=oil, latest=latest, consensus=consensus, value_drivers=tornado,
        valuation_date=valuation_date, fiscal_year_end=fy_end.date(), dps_source=dps_source, extras=extras,
    )
    return result


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _trailing_eps(snap: Snapshot, last: pd.Series, fx: float) -> float | None:
    """Trailing twelve-month EPS in the listing currency: Yahoo's (the basis of every peer's P/E), else the last fiscal year.

    Yahoo quotes ``trailingEps`` in the listing currency – pounds, not pence, for London shares – so no conversion is needed.
    """
    teps = _num(snap.info.get("trailingEps"))
    if teps is not None and teps != 0:
        return teps
    return float(last["eps"]) / fx if pd.notna(last["eps"]) else None


def _expected_dps(snap: Snapshot, hist: pd.DataFrame, shares: float, price: float, cfg: CompanyConfig) -> tuple[float, str]:
    """Dividend per share expected over the next twelve months, in the listing currency."""
    div = hist["dividends"].abs().dropna()
    last_paid = float(div.iloc[-1]) / shares if (len(div) and shares) else 0.0
    if cfg.recommendation.dividend_source == "indicated":
        rate = _num(snap.info.get("dividendRate"))  # listing currency (pounds, not pence, for London)
        if rate is not None and price and 0 < rate / price < 0.20:
            return rate, "indicated annual dividend (Yahoo Finance)"
    return last_paid, f"cash dividend paid in FY{int(hist.index[-1])}"


def _forward_eps(snap: Snapshot, forecast: pd.DataFrame, hist: pd.DataFrame, shares: float, cfg: CompanyConfig, fx: float = 1.0) -> float | None:
    """Next-year EPS in the *listing* currency (consensus if available, else the model)."""
    # only reached when the calendarised consensus is unavailable (years not matched): the model's own EPS
    return _model_eps(forecast, hist, shares, cfg, 0)


def _model_eps(forecast: pd.DataFrame, hist: pd.DataFrame, shares: float, cfg: CompanyConfig, i: int) -> float | None:
    return model_eps(forecast, hist, shares, i)


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
    outputs: tuple[str, ...] = ("deck", "excel", "dashboard", "note", "json"),
    cache_ttl_hours: float = 24.0,
    no_cache: bool = False,
    template: str | None = None,
    model: str | None = None,
    progress: Progress = log.info,
    coverage_log: str | Path | None = None,
) -> dict[str, Path]:
    cfg = load_config(source)
    if template:
        cfg.brand.template = template
    cache = DiskCache(ttl_hours=cache_ttl_hours, enabled=not no_cache)
    result = run_analysis(cfg, cache, progress)

    from .narrative import generate_narrative

    progress(f"Writing narrative ({narrative})")
    result.narrative, result.narrative_mode = generate_narrative(result, mode=narrative, model=model)
    if coverage_log:
        from .coverage import log_coverage

        log_coverage(result, coverage_log)

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
    if "note" in outputs:
        from .create.note import build_note

        progress("Writing the research note")
        paths["note"] = build_note(result, out / f"{cfg.ticker}_note.html", charts_dir=out / "charts")
    return paths
