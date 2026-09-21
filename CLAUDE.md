# Equity Research Engine – working notes for Claude

Python package `eqr` (src layout). Pipeline: `retrieve/` (yfinance + disk cache) -> `analyze/` (lease-adjusted
historicals, forecast, WACC, DCF, scenarios, reverse DCF, comps, recommendation) -> `create/` (python-pptx deck,
openpyxl model, Chart.js dashboard). Case assumptions live in `configs/<TICKER>.yaml`.

## Commands

```bash
python -m pytest -q && python -m ruff check .   # offline tests (synthetic snapshot, mocked Claude client) + lint
eqr analyze SATS.OL                      # valuation summary, no files
eqr run SATS.OL --render --cache-ttl 720 # full outputs + slide PNGs (PowerPoint COM on Windows)
eqr screen SATS.OL KID.OL BOUV.OL MOWI.OL
```

## Rules of the road

- The owner writes in Norwegian; code, README and deck text are English.
- Explainability beats features: every number must trace to a statement line or a YAML key. New drivers need a
  config key, an Inputs cell in Excel and a line in `docs/methodology.md`.
- The Excel model must reproduce Python. After touching `analyze/` or `create/excel.py`, build a case and compare
  `DCF!B21` (fair value), `DCF!B30` (target price), the Scenarios sheet and `Checks` (must read ALL OK) with
  `analysis.json`. `recalc_with_excel()` recalculates through Excel COM.
- Per-share values are in the listing currency, money in the reporting currency (Mowi: NOK vs EUR). `result.shares`
  is FX-adjusted ("effective shares"); use `result.shares_real` for display.
- Deck layout follows the Pareto case template: the four headings (Company overview, Market overview, Financials and
  estimates, Valuation and recommendation) are fixed. Always render and look at the slides after layout changes.
- Edit `.py` files with the Edit/Write tools, not bash heredocs (heredocs have mangled `\n` escapes before).
- The owner's Excel is Norwegian-locale: avoid `TEXT()` with format codes in formulas.
- `output/` and `.cache/` are git-ignored; `examples/` and `docs/img/` hold the committed showcase outputs — refresh
  them when outputs change.
- `notes/` is private (git-ignored): the owner's Norwegian interview guide lives there.
- Before trusting a modelling change, re-run the sweep idea: many tickers with default configs, look for crashes, negative
  values and extreme upsides. Sector refusals and cautions live in `src/eqr/errors.py`.
- Do not commit or push unless asked.
