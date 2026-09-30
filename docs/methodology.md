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
| Consensus revenue / EPS estimates, price targets, ratings | Yahoo Finance | Optional; growth anchor, the "street view" and the estimates-vs-consensus table |
| Quarterly income statement and balance sheet | Yahoo Finance | Last-twelve-month figures and the latest net debt (section 5 and 6) |
| EPS revision trend, results and ex-dividend calendar, indicated dividend | Yahoo Finance | Estimate momentum, catalysts, the dividend in the target price |
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

### Year 1 from the reported quarters (nowcast)

Half-way through a year the first forecast year is half known, and a margin path that starts from the last annual margin
ignores it. With `nowcast: true` (default) year 1 is built from what is reported:

* revenue FY0 = year-to-date revenue + last year's remaining quarters × (1 + g), with `g` the consensus growth for the
  year where it exists, otherwise the year-to-date growth – using last year's *same quarters* keeps the seasonality
  (Kid earns its year in Q4);
* EBITDA FY0 = year-to-date EBITDA + remaining revenue × (last year's margin in those quarters + the year-to-date margin
  change), the change capped at the smaller of 8pp and a quarter of last year's margin (+1pp is a quarter of an IT
  reseller's margin, nothing for a rig owner); quarterly EBITDA is put on the model's lease basis by scaling the annual
  lease cost with revenue, as the LTM figures are.

Only the year-1 growth and margin drivers move; the growth path from year 2 keeps its anchor (this year's momentum is a
level effect, not a new long-run rate) and the margin path runs from the nowcast level to the same target. Both stay
visible inputs in the Excel model, with the arithmetic in the notes. The nowcast is refused, with the reason in the
warnings, when quarters are missing or do not add up to the annual figures, and when the year-to-date margin swings more
than 20pp against a year earlier – an impairment, a disposal gain or a data error, not a run-rate. SATS: two reported
quarters at +4.9% revenue and a 16.7% margin (17.0% a year earlier) put 2026E EPS 17% below consensus – the flat first
half is the reason, and the slide says so.

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
* **Bottom-up beta (cross-check, or `beta_method: peers`)**: a single stock's regression beta is noisy, so every peer's Yahoo
  beta is unlevered with its own debt/equity (Hamada, `βu = βL / (1 + (1 − t) × D/E)`, tax at the corporate rate), the median
  is taken (betas outside 0.1–3 and D/E above 5 are ignored, at least three peers are required) and relevered at the target's
  D/E, then Blume-adjusted and clipped like the regression beta. It is always shown next to the beta used (SATS: 0.83 bottom-up
  vs 0.89 used; Bouvet 0.78 against the 0.60 floor it sits on), and `beta_method: peers` makes it the beta in the WACC.

## 5. DCF

Unlevered FCF for each explicit year is discounted at WACC (end-year by default, `mid_year_convention` available).
Terminal value uses Gordon growth on the terminal-year FCF. Equity value = EV − net debt − minorities; value per share
uses current shares outstanding. The 7 × 7 sensitivity grid
varies WACC (±0.5% steps) and terminal growth (±0.25% steps); the football-field DCF range is the inner 3 × 3.
The implied exit EV/EBITDA (terminal value / final-year EBITDA) is reported as a sanity check.

### Valuation date and the stub period

The forecast years are fiscal years, but the share price is today's. A DCF discounted to the last fiscal year-end is a
value as at that date: in September it is nine months old, and a 12-month target built on it is really a three-month
target. The engine therefore values the company **at the valuation date** (the run date, or `valuation_date`) and takes
net debt from the **latest quarterly balance sheet**. With `v` = years from the fiscal year-end to the valuation date
and `b` = years to the balance-sheet date:

* year 1 counts only the share `1 − b` of its cash flow – the part before the balance-sheet date is already in net debt –
  discounted over `1 − v` years (`(1 + b)/2 − v` with the mid-year convention);
* year `i ≥ 2` is discounted over `i − v` years (less 0.5 mid-year), the terminal value over `N − v` years.

SATS on 21 September 2026: `v` = 0.72, `b` = 0.50 (June balance sheet), fair value NOK 44.66 against NOK 43.50 on the
year-end basis with the same data. With `v = b = 0` this is exactly the textbook DCF (the golden test pins that), and with `v = b = 1` it equals a
DCF of the remaining years. The sensitivity grid, the scenarios, the reverse DCF, the value drivers, the Excel formulas and the
dashboard's JavaScript all use the same two offsets. `stub_period: false` values the company at the balance-sheet date.

### Listing currency vs reporting currency

Some companies report in one currency and trade in another (Mowi: EUR accounts, NOK share price on Oslo Børs).
All money amounts stay in the reporting currency; the share price, target price, EPS-based multiples and every
per-share value are in the listing currency. Technically the engine works with *effective shares* = shares × FX
(reporting units per listing unit), so equity value ÷ effective shares is directly a listing-currency value per share.
The Excel model carries the FX rate as an input cell and divides by it in the same places. `GBp`-quoted London shares
are converted to pounds first.

## 6. Peer multiples

For the target and every peer: EV = market cap today + net debt from the latest balance sheet (same lease basis as the
target) + minorities, over **last-twelve-month** revenue, EBITDA and EBIT, plus trailing (TTM) P/E and the forward multiples
of section 6b. The market cap is converted from the **listing currency to the reporting currency** before it meets the
statements: Bakkafrost trades in NOK and reports in DKK, and a NOK market cap over DKK EBITDA overstates the multiple by a
third (the pipeline warns when the FX rate is missing). The target's own P/E uses the same trailing EPS. LTM is the sum of the four latest quarters when all are reported, otherwise the
last fiscal year + year-to-date − the same quarters a year earlier. Lease cost and lease interest are carried over from the
fiscal year, scaled with LTM revenue. LTM falls back to the fiscal year, and says why, when a quarter is missing, when
Yahoo's quarterly EBITDA does not add up to the annual figure (definitions differ), or when the result is implausible; the
basis of each peer is in the peer table. Multiples outside
(0, 60x) — or (0, 80x) for P/E — are treated as not meaningful. Statistics (mean, median, 25th/75th percentile) are
computed per group and for the full set. Implied values apply the pooled median to the target's own metric (LTM EBITDA,
EBIT and revenue, trailing EPS, NTM EPS and NTM revenue) and bridge to equity value per share; the 25th–75th percentile
range feeds the football field.

### 6b. Forward multiples, calendarised

Consensus comes by fiscal year, and fiscal years differ (Clas Ohlson and Rusta end in April, most others in December).
Comparing "FY1 P/E" across them compares different periods. Every company is therefore put on the same clock: with `w` =
the share of the fiscal year in progress (FY0) still ahead at the valuation date,

`NTM = w × FY0 + (1 − w) × FY1`

for consensus revenue and EPS. Yahoo's "0y" is taken as FY0 only when the year-ago revenue it quotes matches the last
reported fiscal year within 3%, so the years are known to line up. The same check settles **which currency the table is
in**, because Yahoo is inconsistent: Equinor, Mowi, Bakkafrost and Shell come in the reporting currency, Yara and Hafnia in
the listing currency (NOK on USD accounts). A year-ago revenue that matches the accounts once converted at the listing
rate marks a listing-currency table, and revenue and EPS are converted accordingly – before this Yara showed a 0.8x forward
P/E and Shell 918x. Yahoo's own `trailingEps`, `forwardEps` and `dividendRate` are in the listing currency (pounds, not
pence, for London), and are used as they are. From this: **EV/Sales (NTM)**, **P/E (NTM)**, **P/E on FY0
and FY1**, **consensus EPS growth** FY1/FY0 and **PEG** = NTM P/E / EPS growth (only above 2% growth). **EV/EBITDA (NTM)** is
a proxy – NTM revenue at the LTM EBITDA margin – because Yahoo carries no EBITDA consensus; it is labelled as such
everywhere. Two quality measures sit beside them: **levered FCF yield** (operating cash flow + capex − lease principal, over
the market cap) and the **dividend yield** on the indicated dividend; yields outside ±25% (±20% for dividends) are treated as
data errors (Yahoo shows a 145% dividend yield for Grieg Seafood).

### 6c. What sets the multiples – the regression

A peer median assumes every peer deserves the same multiple. A regression of the peers' EV/EBITDA on the two drivers that
should set it – expected revenue growth (consensus FY1, last fiscal year where there is no consensus) and EBITDA margin –
gives a *fundamentals-justified* multiple for the target and splits its gap to the median in two:

* **explained** = fitted / median − 1: the premium or discount the fundamentals justify;
* **unexplained** = actual / fitted − 1: what the fundamentals do not explain – mispricing, or something the model does not
  see (leverage, geography, liquidity, the cycle).

Ordinary least squares with an intercept; two regressors need six peers, one needs four; a regressor with no variation
across the peers is dropped. The fit is drawn on the multiples slide as a line through the target's own margin. Its
strength decides how it is used: with **R² ≥ 0.15** the regression-implied value (± one residual standard deviation) is a
football-field bar; below that it is reported with a warning and not used as an anchor. Across SATS's eleven fitness and
Nordic consumer peers growth and margin explain 6% of the dispersion in EV/EBITDA: the honest reading is that this group is
priced on something else, and the slide says so. The Excel model carries the coefficients as inputs and the fitted
multiple and implied value as live formulas.

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

### Value drivers (tornado)

One input at a time is moved by the step a portfolio manager asks about first – EBITDA margin ±1pp and revenue growth ±1pp
in every forecast year, WACC ±0.5pp, terminal growth ±0.5pp, capex ±0.5pp of revenue, working capital ±2pp of revenue,
tax ±2pp – with everything else at the base case, and the full forecast and DCF re-run. Sorted by swing, the chart shows
which assumption the value actually rests on (SATS: margin ±1pp moves fair value NOK 40.9–48.4; WACC ±0.5pp NOK 41.3–48.5).

### Estimates vs consensus, estimate momentum and catalysts

Our revenue and EPS for the current and next fiscal year are lined up with the Yahoo consensus (mean, low, high, number of
analysts) after checking that Yahoo's "current year" is our first forecast year (its year-ago revenue must match our last
actual year). Revenue growth is anchored on consensus by default, so the revenue gap is small by construction; the
differentiated view sits in EPS (margins, tax, financing). A figure outside the analysts' range is flagged. The 90-day
change in consensus EPS and the number of upward and downward revisions over 30 days give the estimate momentum
(positive / negative / mixed / flat); a BUY against falling estimates, or a SELL against rising ones, is called out as a
tension. The next results date (with the quarter's consensus) and a coming ex-dividend date are listed as catalysts.

### Cross-check of the anchors

The DCF fair value is compared with the peer-multiple value (both today's values) and our 12-month target with the consensus
target. The largest gap sets the label: **high** agreement below 15%, **medium** below 35%, otherwise **low**. Low agreement is
shown next to the rating, written into the valuation slide and added to the warnings: the target is then a hypothesis about
the DCF assumptions, not a result.

## 7. Recommendation

Fair value today = DCF value per share (`tp_method: dcf`) or a weighted blend of DCF and the median multiple-implied
value (`tp_method: blend`), both at the valuation date. The **12-month target price** rolls that value forward at the cost
of equity and deducts the dividend expected over the period – Yahoo's indicated annual dividend when it gives a yield
between 0% and 20%, otherwise the cash dividend paid in the last fiscal year (`dividend_source`):

`target price = fair value × (1 + Ke)^(months / 12) − DPS`, rounded to `tp_rounding` (half away from zero, like Excel's MROUND).

The rating is set on the expected total return, `(target price + DPS) / price − 1`: BUY at ≥ 15%, SELL at ≤ −10%, else HOLD
(thresholds configurable; `roll_forward: false` sets the target price equal to today's fair value).

### Research note

`<TICKER>_note.html` (and `.pdf` with `--pdf`, printed by headless Edge or Chrome) is the front page of a sell-side report:
rating, 12-month target, total return and the agreement of the anchors; the investment case, where we differ from consensus
and the key risks; key data (market cap, EV, net debt, free float, average daily turnover, 52-week range, dividend yield,
next results); a two-year share price chart; and the key figures table – revenue, growth, EBITDA, margin, EBIT, EPS, and
EV/EBITDA, P/E and FCF yield at today's price, for the last two actual and next three forecast years.

### Coverage log and the public site

Every `eqr run` appends the date, price, rating, target, fair value, expected total return and the agreement of the anchors
to `coverage/history.csv` (a re-run the same day replaces its row). `eqr site` builds a static page from the generated cases
and the log – rating, target and multiples per company, links to the note, dashboard, deck and model, and a track record:
first call, price then, latest price and the return since, plus the full log – and a GitHub Actions workflow publishes it
to GitHub Pages on every push. The return is the share price change from the log, so a reader can check the calls, including
the wrong ones.

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

## 10b. Oil sensitivity (optional risk context)

A case config may point at a factsheet from the companion study
[oslo-oil-sensitivity](https://github.com/oscarschjelderup-sketch/oslo-oil-sensitivity):

```yaml
oil_sensitivity: oil/MOWI.OL.json     # written by: oilbeta stock MOWI.OL --json oil/MOWI.OL.json
```

The file is a versioned JSON document (`oilbeta.stock/1`); the two projects share the schema, not an
import, so either can be rewritten as long as the contract holds. It carries two betas from a weekly
two-factor regression with Newey-West intervals — the *total* oil beta (the move per 1% move in Brent
through every channel) and the *partial* one (what is left once the index is held fixed) — plus
scenarios, the share of weekly variance oil explains, and the study's own caveats.

The engine uses it in exactly one place: the first bullet of the risk section, which then states a
measured exposure with its interval instead of a generic sentence about commodity prices. The
sentence follows the numbers, including when they say there is nothing there:

| What the numbers say | What the deck says |
|---|---|
| Total beta interval excludes zero | "a 20% fall in Brent has come with an 8.4% fall in the share (5.2% to 11.5% interval)" |
| Total interval spans zero | "no measurable direct exposure — an interval of −0.04 to +0.09 that spans zero" |
| Partial beta significantly negative | "a higher oil price has been a cost" |
| Partial beta not significant | "the exposure it has is the index's own, not the company's" |

**It is not a driver.** It never enters the forecast, the WACC or the DCF, and a test asserts that a
case runs to identical numbers with and without the file. An oil beta measures co-movement on past
returns; turning it into a discount-rate adjustment would claim far more than the study supports. A
missing or unreadable file produces a warning, not a failure.

## 11. Known limitations

* **Seasonal balance sheets.** The stub period spreads year-1 cash flow evenly over the year and takes net debt as reported
  at the last quarter. For seasonal businesses that quarter carries seasonal working capital and the dividend: Kid's net debt
  is NOK 1,081m in June against NOK 722m at the year-end, which lowers the value by about NOK 2.4 per share against the
  year-end basis. Set `latest_balance_sheet: false` (and a year-end `valuation_date`) where that distorts the case.
* Yahoo Finance carries ~4 annual periods and no segment data; longer history or segments come from analyst files.
* Forward EV/EBITDA is a proxy (NTM consensus revenue at the LTM margin): Yahoo has forward EPS and revenue but no
  forward EBITDA, so a margin change the street expects is not in it.
* The multiples regression uses two regressors on small peer groups; it is a decomposition of the gap to the median, not a
  pricing model, and it is only an anchor when it explains a reasonable share of the dispersion.
* The nowcast takes the reported half-year as it is: a one-off inside a quarter that stays below the 20pp refusal limit
  flows into the year. Yahoo's quarterly statements are patchier than its annual ones (Mowi's quarterly EBITDA is missing
  for some quarters), in which case the year is forecast from the annual accounts and says so.
* Lease interest is an estimate (liability × rate); a company-specific rate can be set per case.
* Net income forecasts (for forward P/E) are approximated as (EBIT − interest) × (1 − t).
* Outputs are for illustration and education, not investment advice.
