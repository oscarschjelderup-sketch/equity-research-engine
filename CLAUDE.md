# Equity Research Engine – working notes for Claude

Python package `eqr` (src layout). Pipeline: `retrieve/` (yfinance + disk cache) -> `analyze/` (lease-adjusted
historicals, LTM and latest balance sheet, forecast, WACC incl. bottom-up beta, DCF at the valuation date, scenarios,
reverse DCF, value drivers, comps, consensus, recommendation) -> `create/` (python-pptx deck, openpyxl model, Chart.js
dashboard, one-page HTML/PDF note). Case assumptions live in `configs/<TICKER>.yaml`.

## Commands

```bash
python -m pytest -q && python -m ruff check .   # offline tests (synthetic snapshot, mocked Claude client) + lint
eqr analyze SATS.OL                      # valuation summary, no files
eqr run SATS.OL --render --pdf --cache-ttl 720 # full outputs, slide PNGs (PowerPoint COM), deck + note PDFs (Edge)
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
- `oil/*.json` are factsheets from the companion oslo-oil-sensitivity study (schema `oilbeta.stock/1`), refreshed with
  `oilbeta stock <TICKER> --json oil/<TICKER>.json`. They feed the risk section only: never let one touch the forecast,
  the WACC or the DCF — `test_oil_context_never_moves_a_valuation` enforces it.
- `notes/` is private (git-ignored): the owner's Norwegian interview guide lives there.
- Before trusting a modelling change, re-run the sweep idea: many tickers with default configs, look for crashes, negative
  values and extreme upsides. Sector refusals and cautions live in `src/eqr/errors.py`.
- Do not commit or push unless asked.
- Valuation date: the DCF is discounted to the run date (stub period). Anything that pins numbers must set
  `assumptions.valuation_date` (the golden test uses the fiscal year-end); otherwise values drift by the day.
- The stub arithmetic lives in three places that must agree: `dcf.discount_periods` / `value_per_share`, the Excel `ev_expr`
  helper (DCF rows 6-8, sensitivity grid, scenario blocks) and `dcfValue` in the dashboard JavaScript.
- Tests must stay offline: `tests/conftest.py` stubs `pipeline.fetch_extras` (quarterly balance, calendar, revisions)
  for every test; stub any new Yahoo call the same way.
- Peers: EV is market cap x FX(listing -> reporting) + latest net debt; forward multiples are calendarised to NTM per fiscal
  year (`analyze/multiples.py`). The regression is an anchor only with R² >= `recommendation.MIN_REGRESSION_R2`.
- `coverage/history.csv` is the coverage log (committed); `eqr site` builds `site/` (git-ignored) from `examples/` + the log,
  and the Pages workflow publishes it. Refresh `examples/` and the log together.
- Yahoo's estimate table can be in the listing or the reporting currency per company: `multiples.estimate_currency` decides
  from the year-ago revenue; `trailingEps`/`forwardEps`/`dividendRate` are in the listing currency (pounds, not pence).
- The nowcast (`analyze/nowcast.py`) only moves year-1 growth and margin; sweep scripts live in the session scratchpad,
  not the repo – re-create `sweep_v05.py` from CLAUDE.md's sweep rule when needed (60 tickers, cached snapshots, ~3 min).
