"""Command line interface: ``eqr run SATS.OL``."""
from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import default_config_yaml, load_config

app = typer.Typer(add_completion=False, help="Equity Research Engine — retrieve, analyze, create.", no_args_is_help=True)
console = Console()


def _version(value: bool):
    if value:
        console.print(f"eqr {__version__}")
        raise typer.Exit()


@app.callback()
def main(version: bool = typer.Option(False, "--version", callback=_version, is_eager=True)):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def run(
    source: str = typer.Argument(..., help="Ticker (uses configs/<TICKER>.yaml if present) or a path to a YAML config."),
    out: Path = typer.Option(Path("output"), "--out", "-o", help="Output folder (a sub-folder per ticker is created)."),
    narrative: str = typer.Option("rules", "--narrative", "-n", help="rules | claude | auto (claude when credentials exist)."),
    model: str | None = typer.Option(None, "--model", help="Claude model id for --narrative claude (default claude-opus-5)."),
    deck: bool = typer.Option(True, help="Build the PowerPoint deck."),
    excel: bool = typer.Option(True, help="Build the Excel model."),
    dashboard: bool = typer.Option(True, help="Build the HTML dashboard."),
    render: bool = typer.Option(False, "--render", help="Also export deck slides to PNG (needs PowerPoint or LibreOffice)."),
    pdf: bool = typer.Option(False, "--pdf", help="Also save the deck as PDF (needs PowerPoint or LibreOffice)."),
    template: str | None = typer.Option(None, "--template", help="Optional .pptx template to build the deck on (e.g. a firm template)."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the on-disk data cache."),
    cache_ttl: float = typer.Option(24.0, "--cache-ttl", help="Cache lifetime in hours."),
):
    """Run the full pipeline for one company."""
    from .pipeline import run_case

    outputs = ["json"] + [n for n, flag in (("deck", deck), ("excel", excel), ("dashboard", dashboard)) if flag]
    from .errors import UnsupportedCompanyError

    try:
        with console.status("[bold]Working...") as status:
            paths = run_case(source, out, narrative=narrative, outputs=tuple(outputs), cache_ttl_hours=cache_ttl,
                             no_cache=no_cache, template=template, model=model,
                             progress=lambda m: status.update(f"[bold]{m}"))
    except UnsupportedCompanyError as exc:
        console.print(f"[yellow]Not supported:[/yellow] {exc}")
        raise typer.Exit(2) from None
    _print_summary(paths)
    if render and "deck" in paths:
        from .create.render import export_slides

        imgs = export_slides(paths["deck"], paths["deck"].parent / "slides")
        console.print(f"Rendered {len(imgs)} slides to {imgs[0].parent}")
    if pdf and "deck" in paths:
        from .create.render import export_pdf

        console.print(f"Saved {export_pdf(paths['deck'])}")


@app.command()
def analyze(
    source: str = typer.Argument(..., help="Ticker or YAML config."),
    no_cache: bool = typer.Option(False, "--no-cache"),
):
    """Print the valuation summary without creating any files."""
    from .create.style import fmt_mult, fmt_num, fmt_pct
    from .errors import UnsupportedCompanyError
    from .pipeline import run_analysis
    from .retrieve import DiskCache

    cfg = load_config(source)
    try:
        with console.status("[bold]Analyzing..."):
            r = run_analysis(cfg, DiskCache(enabled=not no_cache), progress=lambda m: None)
    except UnsupportedCompanyError as exc:
        console.print(f"[yellow]Not supported:[/yellow] {exc}")
        raise typer.Exit(2) from None
    rec = r.recommendation
    console.rule(f"[bold]{r.name} ({cfg.ticker})")
    t = Table(show_header=False, box=None)
    t.add_row("Price", f"{r.price_currency} {fmt_num(r.price, 2)}", "Market cap", f"{r.currency} {fmt_num(r.market_cap)}m")
    t.add_row("Rating", f"[bold]{rec.rating}[/bold]", "Target price", f"{r.price_currency} {fmt_num(rec.target_price, 2)} ({fmt_pct(rec.upside, 0, sign=True)})")
    t.add_row("DCF value", f"{r.price_currency} {fmt_num(rec.dcf_value, 2)}", "Multiples value", f"{r.price_currency} {fmt_num(rec.multiples_value, 2)}")
    t.add_row("WACC", fmt_pct(r.wacc.wacc), "Terminal growth", fmt_pct(r.drivers.terminal_growth))
    t.add_row("EV/EBITDA (LTM)", fmt_mult(r.comps.company.get("ev_ebitda")), "Peer median", fmt_mult(r.comps.stats.loc["All|median", "ev_ebitda"]) if not r.comps.stats.empty else "–")
    console.print(t)
    ct = r.combined_table()
    ft = Table(title="Financials", header_style="bold")
    ft.add_column(r.units_label)
    for y in ct.index:
        ft.add_column(str(y), justify="right")
    for label, key, f in (("Revenue", "revenue", fmt_num), ("Growth", "growth", fmt_pct), ("EBITDA", "ebitda", fmt_num),
                          ("Margin", "ebitda_margin", fmt_pct), ("EBIT", "ebit", fmt_num), ("Unlevered FCF", "ufcf", fmt_num)):
        ft.add_row(label, *[f(v) for v in ct[key]])
    console.print(ft)
    for w in r.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")


@app.command()
def screen(
    tickers: list[str] = typer.Argument(..., help="Tickers or YAML configs, e.g. SATS.OL KID.OL BOUV.OL"),
    out: Path = typer.Option(Path("output/screen.csv"), "--out", "-o", help="CSV file with the comparison table."),
    no_cache: bool = typer.Option(False, "--no-cache"),
    cache_ttl: float = typer.Option(24.0, "--cache-ttl", help="Cache lifetime in hours."),
):
    """Run the analysis for a watch-list and compare rating, target price, implied WACC and multiples."""
    import pandas as pd

    from .create.style import fmt_mult, fmt_num, fmt_pct
    from .errors import UnsupportedCompanyError
    from .pipeline import run_analysis
    from .retrieve import DiskCache

    rows = []
    with console.status("[bold]Screening...") as status:
        for t in tickers:
            status.update(f"[bold]Analyzing {t}")
            try:
                r = run_analysis(load_config(t), DiskCache(ttl_hours=cache_ttl, enabled=not no_cache), progress=lambda m: None)
            except UnsupportedCompanyError as exc:
                console.print(f"[yellow]skipped[/yellow] {exc}")
                continue
            except Exception as exc:
                console.print(f"[red]{t}: {exc}[/red]")
                continue
            rec, rv = r.recommendation, r.reverse_dcf
            stats = r.comps.stats
            rows.append({
                "ticker": r.cfg.ticker, "name": r.name, "currency": r.price_currency, "price": r.price, "rating": rec.rating,
                "target_price": rec.target_price, "upside": rec.upside, "total_return": rec.total_return, "fair_value": rec.fair_value,
                "scenario_weighted": r.scenario_weighted_value, "wacc": r.wacc.wacc, "implied_wacc": rv.implied_wacc if rv else None,
                "ev_ebitda": r.comps.company.get("ev_ebitda"),
                "peer_median_ev_ebitda": float(stats.loc["All|median", "ev_ebitda"]) if (not stats.empty and "All|median" in stats.index) else None,
                "net_debt_to_ebitda": float(r.hist["nd_to_ebitda"].iloc[-1]),
                "agreement": r.crosscheck.agreement if r.crosscheck is not None else "n/a", "warnings": len(r.warnings),
            })
    if not rows:
        raise typer.Exit(1)
    df = pd.DataFrame(rows).sort_values("total_return", ascending=False)
    t = Table(title="Watch-list (full table in the CSV)", header_style="bold")
    for name in ("Ticker", "Rating", "Agree", "Price", "12m TP", "Return", "Fair", "WACC", "Impl.", "EV/EBITDA"):
        t.add_column(name, justify="left" if name in {"Ticker", "Rating", "Agree"} else "right", no_wrap=True)
    colour = {"BUY": "green", "SELL": "red", "HOLD": "yellow", "NOT RATED": "magenta"}
    for _, x in df.iterrows():
        t.add_row(x["ticker"], f"[{colour[x['rating']]}]{x['rating']}[/]", x["agreement"], fmt_num(x["price"], 2), fmt_num(x["target_price"], 2),
                  fmt_pct(x["total_return"], 0, sign=True), fmt_num(x["fair_value"], 2), fmt_pct(x["wacc"]), fmt_pct(x["implied_wacc"]),
                  fmt_mult(x["ev_ebitda"]))
    console.print(t)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    console.print(f"Wrote {out}")


@app.command()
def init(ticker: str = typer.Argument(..., help="Ticker, e.g. SATS.OL"), folder: Path = typer.Option(Path("configs"), "--folder")):
    """Write a commented starter config for a new case."""
    import yaml

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ticker}.yaml"
    if path.exists():
        console.print(f"[red]{path} already exists[/red]")
        raise typer.Exit(1)
    team = brand = None
    note = ""
    for other in sorted(folder.glob("*.yaml")):
        try:
            data = yaml.safe_load(other.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if data.get("team") or data.get("brand"):
            team, brand = data.get("team"), data.get("brand")
            note = f" (team and brand copied from {other.name})"
            break
    path.write_text(default_config_yaml(ticker, team=team, brand=brand), encoding="utf-8")
    console.print(f"Wrote {path}{note}. Edit peers and assumptions, then run: eqr run {ticker} --render")


@app.command()
def render(deck: Path = typer.Argument(..., help="Path to a .pptx"), out: Path | None = typer.Option(None, "--out")):
    """Export a deck's slides to PNG files."""
    from .create.render import export_slides

    imgs = export_slides(deck, out or deck.parent / "slides")
    console.print(f"Rendered {len(imgs)} slides to {imgs[0].parent}")


def _print_summary(paths: dict[str, Path]):
    t = Table(title="Outputs", header_style="bold")
    t.add_column("Artifact")
    t.add_column("Path")
    for k, p in paths.items():
        t.add_row(k, str(p))
    console.print(t)


if __name__ == "__main__":  # pragma: no cover
    app()
