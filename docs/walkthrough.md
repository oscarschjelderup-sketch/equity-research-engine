# Five-minute walkthrough

A guided tour for someone reviewing the project.

## 1. One command

```bash
eqr run SATS.OL --render --pdf
```

This retrieves the data (cached afterwards), builds the model and writes `output/SATS.OL/`: the deck (`.pptx` and
`.pdf`), the one-page research note (`.html` and `.pdf`), the Excel model, the dashboard, `analysis.json` and the
rendered slides.

Start with the note: it is what a portfolio manager reads. Rating box, investment case, where we differ from consensus
(SATS: 2026E EPS 17% below the street, because the reported first half is flat), key risks, catalysts, and the key figures table with multiples by year.

## 2. The deck

Slides 3–6 are the four fixed case headings. Look at slide 6: the rating and 12-month target price, the WACC × growth
sensitivity, the football field (52-week range, DCF, scenarios, own history, peers), the scenario bars, and – in the
lower box – what the current share price implies. The appendix shows the WACC and DCF build-up, the scenario table,
the full peer table (last-twelve-month figures, basis in the footer), the company's own multiples through time with the
cross-check of the valuation anchors, and slide 4.5: our estimates against consensus, the revision trend, the next
results date and a tornado of what the value rests on.

The DCF build-up (slide 4.1) shows the valuation date: in September only half of 2026's cash flow is still to come (the
rest is already in the June net debt), and every year is discounted from today, not from last December. Slide 5's
commentary says what 2026E is built on: the two reported quarters, plus the rest of the year at consensus growth on last
year's seasonal margins – so the gap to consensus EPS is a statement about the reported first half, not a round number.

## 3. The Excel model

Open `SATS.OL_model.xlsx` and change *Terminal growth* on the Inputs sheet. The forecast, the DCF, the sensitivity
grid, all three scenario blocks, the target price and the rating update, and the Checks sheet keeps reading `ALL OK`.
Blue cells are inputs, black are formulas, green are links to other sheets.

## 4. The dashboard

Open `SATS.OL_dashboard.html`, tab *Valuation*. The sliders recompute the full operating forecast and the DCF in the
browser with the same arithmetic as the engine. Below: scenarios, the reverse DCF, the heat-mapped sensitivity, the
football field, own multiples through time and the agreement between DCF, peers and consensus.

Then the *Peers* tab: EV/EBITDA against expected growth with the regression line through the target's own margin, the
tiles that split the target's gap to the median into what the fundamentals explain and what they do not, the trailing
table (with each peer's LTM basis) and the forward table – NTM EV/Sales, P/E on FY0, FY1 and NTM, EPS growth, PEG, FCF and
dividend yield – calendarised to every company's own fiscal year. The same material is appendix slide 4.6 in the deck.

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

## 7. The public site

```bash
eqr site                 # builds site/index.html from examples/ and coverage/history.csv
```

The coverage page: every case with rating, target, multiples and agreement of anchors, the deliverables, and the track
record from the coverage log (first call, price then, latest price, return since). The Pages workflow publishes it on push.

## 8. A new company

```bash
eqr init NHY.OL          # commented starter config; index chosen from the ticker suffix; team and brand copied
# edit configs/NHY.OL.yaml: peers, margin view, scenarios, market slide
eqr run NHY.OL --render
```
