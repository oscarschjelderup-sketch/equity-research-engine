# Changelog

## 0.6.0 – 2026-09-23

### Added
- **Nowcast** (`analyze/nowcast.py`, `assumptions.nowcast`): year 1 is built from the reported quarters – year-to-date
  actuals plus last year's remaining quarters at consensus growth and the (capped) year-to-date margin change, on the
  model's lease basis. Only the year-1 drivers move; refused with a warning when the quarters are missing, do not add up
  to the annual figures, or swing more than 20pp (Vend, Scatec, Nel in the sweep). SATS's 2026E now rests on its reported
  first half and lands 17% below consensus EPS.
- A warning when net debt has moved by more than half a year's EBITDA since the year-end (seasonal working capital).

### Fixed
- **Currency of Yahoo's estimates** is detected per company from the year-ago revenue it quotes (`multiples.estimate_currency`):
  Yara and Hafnia come in NOK on USD accounts, Shell in USD on a GBp listing. Forward P/E for Yara went from 0.8x to 9.1x,
  Shell from 918x to 9.2x, Hafnia from 0.8x to 15.0x. Consensus growth alignment and the estimates-vs-consensus view use the
  same detection, so Yara now gets a consensus anchor instead of a historical CAGR.
- `trailingEps`, `forwardEps` and `dividendRate` are used as Yahoo quotes them – in the listing currency, pounds not pence
  for London – instead of being divided by 100.
- The robustness sweep was re-run across 60 companies with the v0.4–v0.6 engine: no crashes beyond the intended refusals.

## 0.5.0 – 2026-09-22

Multiples in depth, and a public coverage site.

### Added
- **Currency-consistent peer EV**: every peer's market cap is converted from its listing currency to its reporting currency
  before it meets the statements (Bakkafrost: NOK price, DKK accounts), with a warning when the rate is missing.
- **Calendarised forward multiples** from consensus (`analyze/multiples.py`): NTM EV/Sales, NTM P/E, P/E on FY0 and FY1,
  consensus EPS growth, PEG, plus a labelled NTM EV/EBITDA proxy, levered FCF yield and dividend yield – for the target and
  every peer, on each company's own fiscal year. NTM EPS and NTM revenue add two implied values and football-field bars.
- **Multiples regression**: EV/EBITDA on expected growth and margin across the peers, splitting the target's gap to the
  median into an explained and an unexplained part; a football-field anchor only above R² 0.15, otherwise reported with a
  warning. Appendix slide 4.6 (scatter with the fit, forward table, reading), a dashboard peers tab with the regression tiles
  and forward table, and a live block on the Excel Peers sheet.
- **Coverage log** (`coverage/history.csv`, one row per ticker and day) written on every `eqr run`.
- **Public site**: `eqr site` builds a static coverage page (cases, deliverables, track record with the return since the
  first call, the full log) and `.github/workflows/pages.yml` publishes it to GitHub Pages.
- 83 tests: calendarisation, currency conversion of peer EV, the regression (coefficients recovered exactly, fallback to one
  regressor, refusal of thin samples, no anchor when weak), the coverage log and the site.

## 0.4.0 – 2026-09-21

A senior-analyst review: the questions a portfolio manager asks in the first meeting.

### Added
- **Valuation date and stub period.** The DCF is discounted to today, year 1 counts only the cash flow after the latest
  balance-sheet date, and net debt comes from the latest quarterly balance sheet – before, a September case was valued at
  the previous December and its "12-month" target was really a three-month target. Python, Excel formulas and the
  dashboard's JavaScript share the arithmetic; the golden test pins that it reduces to the old DCF at the year-end.
- **Last-twelve-month multiples** for the target and every peer (four latest quarters, or fiscal year + year-to-date −
  same period last year), EV on today's market cap and the latest net debt, P/E on trailing EPS for everyone; the basis of
  each figure is reported and falls back to the fiscal year with a reason.
- **Estimates vs consensus**: our revenue and EPS against the Yahoo consensus (mean, range, analysts) for the next two years,
  the 90-day EPS revision trend with an estimate-momentum label, the tension between rating and momentum, and the next
  results and ex-dividend dates as catalysts. New appendix slide 4.5 and dashboard cards.
- **Value drivers (tornado)**: fair value with one driver at a time moved (margin, growth, WACC, terminal growth, capex,
  working capital, tax), on slide 4.5, in the dashboard and in the risk bullets.
- **Bottom-up beta** from the peer group (unlevered median, relevered at the target's D/E) as a cross-check in every case
  and as `beta_method: peers`.
- **One-page research note** (`<TICKER>_note.html`, PDF with `--pdf`): rating box, investment case, consensus table,
  key data, share price chart, catalysts, risks and the key figures table with multiples by year.
- Salmon peers in the Mowi case (SalMar, Lerøy, Bakkafrost, Grieg Seafood).

### Changed
- The expected dividend in the target price is Yahoo's indicated annual dividend (`dividend_source: last_paid` for the old
  behaviour); SATS pays NOK 1.44, not the NOK 0.66 paid in fiscal 2025.
- The golden test is valued at the fiscal year-end so its pinned numbers never drift with the calendar; tests stub the new
  Yahoo call so the suite stays offline. 73 tests.

## 0.3.0 – 2026-09-21

Hardening release, driven by running the engine across 56 listed companies.

### Added
- **Cross-check** of the valuation anchors (DCF vs peer multiples, our target vs consensus) with a high / medium / low
  agreement label on the valuation slide, in the dashboard and in `eqr screen`.
- **Own multiples through time**: trailing EV/EBITDA and P/E bands, a football-field bar, an appendix slide and a dashboard chart.
- **Unsupported sectors** (banks, insurers, real estate) are refused with an explanation; cautions for E&P, shipping,
  airlines, conglomerates and farm products; data sanity warnings; `NOT RATED` when the equity value is not positive.
- `--pdf` exports the deck as PDF. Ruff lint configuration and a lint step in CI. `docs/walkthrough.md`.

### Changed
- Forecast tax rate defaults to the profit-weighted effective rate when it differs materially from the statutory rate
  (Equinor: 73%, DCF from 2.9x the share price to 14% below it).
- Capex normalises towards D&A x 1.05 for companies in an investment phase (`capex_pct_terminal` to override).

## 0.2.0 – 2026-09-20

### Added
- **Scenarios**: bear / base / bull cases (growth, margin, WACC and terminal-growth shifts) with a probability-weighted
  value; configurable per case under `scenarios:`.
- **12-month target price**: fair value rolled forward at the cost of equity less the expected dividend; the rating is
  set on expected total return.
- **Reverse DCF**: the WACC, terminal growth and final-year EBITDA margin implied by the current share price.
- **Value-driver terminal value** (`terminal_method: value_driver`, `ronic`) next to Gordon growth.
- **Appendix slides**: cost of capital and DCF build-up, scenario analysis, peer group detail (`appendix: false` to skip).
- **Excel**: live Scenarios sheet (every case re-runs the forecast), target-price mechanics as formulas, and a Checks
  sheet with eleven integrity tests and an overall status on the cover.
- **Dashboard**: interactive DCF sliders (same arithmetic as the engine), scenario table and reverse-DCF tiles.
- `eqr screen` to run a watch-list and export a comparison table.
- Offline test of the Claude narrative with a fake client; GitHub Actions workflow; `CLAUDE.md`.

### Changed
- Net working capital is modelled as a level (% of revenue) from the balance sheet; the cash effect follows revenue growth.
- Automatic size premium by market cap in the cost of equity.
- Listing currency vs reporting currency handled throughout (per-share values in the listing currency).
- Benchmark index defaults from the ticker suffix (`.OL` -> OSEBX and so on).
- Target price rounding now matches Excel's `MROUND` (half away from zero).

## 0.1.0 – 2026-09-16

- First version: Yahoo Finance retrieval with cache, lease-adjusted (pre-IFRS 16) historicals, driver-based forecast,
  CAPM WACC with regression beta, FCFF DCF with sensitivity grid, peer multiples, football field, six-slide deck,
  Excel model with live formulas, HTML dashboard, optional Claude narrative.
