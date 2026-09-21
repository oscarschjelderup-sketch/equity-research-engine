# Five-minute walkthrough

A guided tour for someone reviewing the project.

## 1. One command

```bash
eqr run SATS.OL --render --pdf
```

This retrieves the data (cached afterwards), builds the model and writes `output/SATS.OL/`: the deck (`.pptx` and
`.pdf`), the Excel model, the dashboard, `analysis.json` and the rendered slides.

## 2. The deck

Slides 3–6 are the four fixed case headings. Look at slide 6: the rating and 12-month target price, the WACC × growth
sensitivity, the football field (52-week range, DCF, scenarios, own history, peers), the scenario bars, and – in the
lower box – what the current share price implies. The appendix shows the WACC and DCF build-up, the scenario table,
the full peer table and the company's own multiples through time with the cross-check of the valuation anchors.

## 3. The Excel model

Open `SATS.OL_model.xlsx` and change *Terminal growth* on the Inputs sheet. The forecast, the DCF, the sensitivity
grid, all three scenario blocks, the target price and the rating update, and the Checks sheet keeps reading `ALL OK`.
Blue cells are inputs, black are formulas, green are links to other sheets.

## 4. The dashboard

Open `SATS.OL_dashboard.html`, tab *Valuation*. The sliders recompute the full operating forecast and the DCF in the
browser with the same arithmetic as the engine. Below: scenarios, the reverse DCF, the heat-mapped sensitivity, the
football field, own multiples through time and the agreement between DCF, peers and consensus.

## 5. A watch-list

```bash
eqr screen SATS.OL KID.OL BOUV.OL MOWI.OL
```

Rating, target price, implied WACC and agreement side by side; the full table goes to `output/screen.csv`.

## 6. Where it refuses, and where it warns

```bash
eqr analyze DNB.OL      # refused: banks are valued on equity, not enterprise free cash flow
eqr analyze AKRBP.OL    # runs, with a warning about petroleum tax and a low-agreement flag
```

The engine was run across 56 listed companies to find where a generic FCFF model breaks. The results shaped four
guardrails: unsupported sectors, a profit-weighted effective tax rate, capex that normalises towards depreciation,
and `NOT RATED` when the equity value is not positive. See [methodology.md](methodology.md) for the detail.

## 7. A new company

```bash
eqr init NHY.OL          # commented starter config; index chosen from the ticker suffix; team and brand copied
# edit configs/NHY.OL.yaml: peers, margin view, scenarios, market slide
eqr run NHY.OL --render
```
