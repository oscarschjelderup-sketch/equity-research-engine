# Methodology

This document explains every number the engine produces, in the order the pipeline computes it.
The guiding principle: **the engine computes, the analyst decides**. Every assumption is an explicit
input in the case YAML, and every output can be traced back to a statement line or a config value.

## 1. Retrieve

| Data | Source | Notes |
|---|---|---|
| Annual income statement, balance sheet, cash flow | Yahoo Finance (`yfinance`) | Typically 4 fiscal years |
| Share price, shares outstanding, 52-week range | Yahoo Finance | Price in the listing currency (GBp converted to GBP) |
| Weekly prices, 5 years, stock and index | Yahoo Finance | Used for beta and relative performance |
| Consensus revenue / EPS estimates, price targets, ratings | Yahoo Finance | Optional; used as growth anchor and for the "street view" |
| Peer statements and market data | Yahoo Finance | Same treatment as the target company |
| FX spot rates | Yahoo Finance (`EURNOK=X` etc.) | Only for displaying peer market caps in the target currency |
| Longer history / restated figures | Analyst CSV or XLSX (`history_csv`) | Overrides or extends the Yahoo history |

Every payload is cached on disk (`.cache/`, 24h by default) so a case can be re-run offline and reproduced.

## 2. Historicals and the lease adjustment

Yahoo lines are mapped to a canonical table: revenue, EBITDA, D&A, EBIT, pre-tax income, tax, net income,
EPS, shares, cash, debt, lease liabilities, equity, invested capital, operating cash flow, capex, change in
working capital, dividends and the financing cash-flow components.

**Why leases matter.** Under IFRS 16 rent is not an operating cost: it is split into right-of-use
depreciation (below EBITDA) and lease interest (below EBIT), and the present value of the lease contracts
sits on the balance sheet as debt. A perpetuity DCF on IFRS 16 cash flows then overstates value, because
the liability only covers *existing* contracts while the cash flows assume the company keeps operating its
clubs or stores forever. For SATS the reported-basis DCF was five times the share price; the adjusted basis
lands within a few percent of the sell-side range.

The engine therefore reconstructs a **pre-IFRS 16 ("operating") basis** from the statements:

* **Lease principal repaid** = the residual of financing cash flow after net debt issuance, net equity
  issuance, dividends, interest paid and other financing items. IFRS filers report the lease principal in
  financing, so the residual is the lease repayment; US GAAP filers keep operating rent in EBITDA, so the
  residual is ≈ 0 and nothing is adjusted. The estimate is clipped to `[0, 60% of lease liabilities]`.
* **Lease interest** = average lease liability × `lease_rate` (default 4.5%), capped at 80% of interest expense.
* **Lease cost** = principal + interest (≈ cash rent).
* `EBITDA_adj = EBITDA − lease cost`, `D&A_adj = D&A − principal` (≈ ROU depreciation), `EBIT_adj = EBIT − lease interest`,
  `net debt_adj = debt excluding leases − cash` (equal to Yahoo's own "Net Debt" line).

`lease_treatment: financial` keeps the reported figures and puts lease liabilities into net debt.

Derived metrics: growth, margins, effective tax rate (clipped 0–35%, falls back to the config rate),
NOPAT = EBIT × (1 − t), unlevered FCF = NOPAT + D&A + capex + ΔNWC, FCF conversion, net debt/EBITDA,
ROE, ROIC (NOPAT / invested capital), payout ratio.

## 3. Forecast drivers

| Driver | Default | Override |
|---|---|---|
| Revenue growth | Consensus growth for the next one or two fiscal years (if ≥ 1 analyst and aligned to the last actual year), else the 3-year CAGR; then a linear fade to terminal growth | `assumptions.revenue_growth` (list) |
| EBITDA margin | Linear path from the last actual margin to the 3-year average | `ebitda_margin` (list) or `ebitda_margin_target` |
| D&A and capex as % of revenue | 3-year averages. When capex runs above D&A × 1.05 the company is in an investment phase and capex normalises linearly to D&A × 1.05 by the final forecast year (otherwise a temporary capex cycle is capitalised for ever) | `da_pct_revenue`, `capex_pct_revenue`, `capex_pct_terminal` |
| Net working capital | Modelled as a *level*: operating NWC (current assets less cash, minus current liabilities less short-term debt and leases) as % of revenue, 3-year average; the cash effect each year is −NWC% × Δrevenue, so prepaid business models release cash as they grow and receivables-heavy ones absorb it — never a perpetual inflow | `nwc_pct_revenue` |
| Tax rate | Statutory 22% unless the accounts say otherwise: total tax / total pre-tax profit over the last three profitable years (profit-weighted, so a low-profit year cannot distort it); used when it differs from the statutory rate by more than 5pp and bounded to 10–85%. Equinor lands at 73%, which moved its DCF from NOK 1,220 (2.9x the share price) to NOK 362 (14% below it) | `tax_rate` |
| Terminal growth | 2% default | `terminal_growth` |

The terminal row normalises the last explicit year by `(1 + g)`.

## 4. Cost of capital

* **Beta**: 3-year weekly OLS regression of log returns against the configured index. If R² is below
  `min_r2` (0.10) the regression is rejected in favour of Yahoo's 5-year monthly beta (SATS vs OSEBX has R² ≈ 0.02:
  an oil-heavy index explains nothing about a gym operator). Betas are Blume-adjusted (0.67β + 0.33) and clipped to
  `[beta_floor, beta_cap]`. A manual beta can be set in YAML.
* **Cost of equity** = risk-free + β × equity risk premium + size premium. The size premium defaults to `auto`:
  0% above USD 10bn market cap, 0.75% for USD 2–10bn, 1.5% for USD 0.5–2bn and 2.5% below USD 0.5bn (in the spirit of the
  Duff & Phelps / Kroll size studies). Small caps are otherwise systematically overvalued by a plain CAPM with a low beta;
  set a number in YAML to override.
* **Cost of debt** = interest expense (excluding estimated lease interest) / average debt, clipped 2–12%, after tax.
* **Weights**: market cap and gross debt on the chosen lease basis (`debt_weight` overrides).

## 5. DCF

Unlevered FCF for each explicit year is discounted at WACC (end-year by default, `mid_year_convention` available).
Terminal value uses Gordon growth on the terminal-year FCF and is discounted from year N. Equity value =
EV − net debt − minorities; value per share uses current shares outstanding. The 7 × 7 sensitivity grid
varies WACC (±0.5% steps) and terminal growth (±0.25% steps); the football-field DCF range is the inner 3 × 3.
The implied exit EV/EBITDA (terminal value / final-year EBITDA) is reported as a sanity check.

### Listing currency vs reporting currency

Some companies report in one currency and trade in another (Mowi: EUR accounts, NOK share price on Oslo Børs).
All money amounts stay in the reporting currency; the share price, target price, EPS-based multiples and every
per-share value are in the listing currency. Technically the engine works with *effective shares* = shares × FX
(reporting units per listing unit), so equity value ÷ effective shares is directly a listing-currency value per share.
The Excel model carries the FX rate as an input cell and divides by it in the same places. `GBp`-quoted London shares
are converted to pounds first.

## 6. Peer multiples

For every peer: EV = market cap + net debt (same lease basis as the target) + minorities; multiples on the
last reported fiscal year (EV/Sales, EV/EBITDA, EV/EBIT) plus Yahoo's trailing and forward P/E. Multiples outside
(0, 60x) — or (0, 80x) for P/E — are treated as not meaningful. Statistics (mean, median, 25th/75th percentile) are
computed per group and for the full set. Implied values apply the pooled median to the target's LTM metric and
bridge to equity value per share; the 25th–75th percentile range feeds the football field.

### Terminal value

`terminal_method: gordon` (default) capitalises the terminal-year FCF: `TV = FCF_N × (1 + g) / (WACC − g)`.
`terminal_method: value_driver` makes the reinvestment behind the growth explicit:
`TV = NOPAT_N × (1 + g) × (1 − g / RONIC) / (WACC − g)`. Growing at g while earning RONIC on new capital requires
reinvesting g / RONIC of NOPAT, so with RONIC = WACC growth adds no value, and a very high RONIC collapses to a NOPAT
perpetuity. `ronic` defaults to WACC + 2pp. The sensitivity grid, the scenarios and the Excel model use the same method.

### Scenarios

`scenarios:` lists the cases (default bear 25% / base 50% / bull 25%). Each case shifts four levers additively relative to
the base case — revenue growth in every forecast year, the whole EBITDA margin path, WACC and terminal growth — and
re-runs the full operating forecast, so capex and working capital follow revenue as in the base case. The
probability-weighted value is the probability-normalised average. The bear–bull range is one bar in the football field.

### Reverse DCF

Three bisection solves answer "what does the share price assume?", each holding everything else at the base case:
the WACC, the terminal growth rate and the uniform EBITDA-margin shift at which the DCF equals today's price. A price
that implies a WACC far above ours (Bouvet: 12.5% vs 8.3%) says the market does not believe the cash flows, not that the
stock is obviously cheap — which is exactly the challenge an analyst should put to their own model.

### Own multiples through time

Each weekly close is paired with the latest fiscal year that was public at the time (fiscal year-end plus a 75-day reporting
lag), giving trailing EV/EBITDA and P/E series on the model's lease basis. Multiples outside 0–30x (EV/EBITDA) or 0–60x (P/E)
are dropped, so a recovery year with near-zero earnings cannot stretch the band. The median and interquartile band give
"cheap or dear against its own history", one more football-field bar and an implied value at the company's own median.

### Cross-check of the anchors

The DCF fair value is compared with the peer-multiple value (both today's values) and our 12-month target with the consensus
target. The largest gap sets the label: **high** agreement below 15%, **medium** below 35%, otherwise **low**. Low agreement is
shown next to the rating, written into the valuation slide and added to the warnings: the target is then a hypothesis about
the DCF assumptions, not a result.

## 7. Recommendation

Fair value today = DCF value per share (`tp_method: dcf`) or a weighted blend of DCF and the median multiple-implied
value (`tp_method: blend`). The **12-month target price** rolls that value forward at the cost of equity and deducts the
dividend expected over the period (last year's cash dividend per share):

`target price = fair value × (1 + Ke)^(months / 12) − DPS`, rounded to `tp_rounding` (half away from zero, like Excel's MROUND).

The rating is set on the expected total return, `(target price + DPS) / price − 1`: BUY at ≥ 15%, SELL at ≤ −10%, else HOLD
(thresholds configurable; `roll_forward: false` sets the target price equal to today's fair value).

## 8. Narrative

Rule-based text is generated from the numbers (every sentence cites a computed figure). With
`--narrative claude` the analysis JSON and the rule-based draft are sent to Claude, which rewrites the qualitative
blocks (thesis, highlights, commentary, opportunities/threats, risks) without changing any number, rating or target;
the output is validated key by key and falls back to the rule-based text where needed.

## 9. Excel model and integrity checks

The workbook mirrors the engine sheet by sheet (Inputs → Historicals → Forecast → WACC → DCF → Scenarios → Peers →
Football field → Checks). Every scenario has its own forecast block driven by the blue shift cells, the target-price
mechanics are formulas on the DCF sheet, and the Checks sheet runs eleven tests (WACC > g, EV bridge, equity bridge,
sensitivity centre = fair value, base scenario = fair value, revenue link, capital-structure weights, probabilities,
market data present, terminal value share, no error cells) with an overall status shown on the cover. After generation the
workbook is recalculated through Excel and the engine compares the Excel values with Python.

## 10. Where the model refuses and where it warns

The engine was run across 56 listed companies (Oslo Børs plus a few international names) to find where a generic FCFF
model breaks. The findings became guardrails:

* **Refused** (`UnsupportedCompanyError`, override with `allow_unsupported_sector: true`): Financial Services (interest is a
  bank's raw material, so enterprise free cash flow is undefined) and Real Estate (valued on NAV and yields).
* **Warned**: oil and gas E&P and integrated (petroleum tax, depletion), shipping and airlines (cyclical margins, leases),
  conglomerates and investment companies (sum-of-the-parts), farm products (biological assets).
* **Data checks**: an EBITDA margin above 80% or below zero, free cash flow negative in most forecast years, terminal
  value above 95% of enterprise value.
* **`NOT RATED`**: when the equity value is not positive no target price is set.

## 11. Known limitations

* Yahoo Finance carries ~4 annual periods and no segment data; longer history or segments come from analyst files.
* Peer multiples are on the last fiscal year, not LTM or forward consensus (Yahoo has no peer-level forward EBITDA).
* Lease interest is an estimate (liability × rate); a company-specific rate can be set per case.
* Net income forecasts (for forward P/E) are approximated as (EBIT − interest) × (1 − t).
* Outputs are for illustration and education, not investment advice.
