# Changelog

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
