# Findings — home-insurance non-renewals, Contra Costa County

Every number below is produced by `make insights` from `data/graph.duckdb` and materialized in `data/insights/*.parquet`.
The query that produced each table is named; the SQL lives in `policygraph/insights/<module>.py`.
"CC" is Contra Costa County (52 ZIPs in CDI's data). Rates are non-renewals divided by policies (new + renewed + non-renewed).

## 1. Fire hazard explains little of the county's non-renewals, and the county sits *below* the statewide hazard line

**Query:** `hazard_residual.fit` — OLS of ZIP non-renewal rate on Very High and High FHSZ area shares across every CA ZIP
with more than 50 policies; residual = actual − predicted.

| fit | year | release | measure | CA ZIPs | R² | CC ZIPs above the line | CC mean residual |
|---|---|---|---|---|---|---|---|
| insurer-initiated | 2021 | 2015–2021 | `nonrenewed_insurer` | 1,647 | 0.13 | 7 of 40 | −0.66 pts |
| all non-renewals | 2023 | 2020–2023 | `count` | 1,628 | 0.13 | 1 of 40 | −1.99 pts |

Hazard share is statistically significant (Very High coefficient +3.1 pts of insurer-initiated rate per 100 % Very High
area, p < 0.001) but explains only 13 % of the variance between ZIPs. Contra Costa as a whole is dropped *less* than its
hazard predicts: 2.09 % insurer-initiated rate in 2021 versus 3.01 % statewide.

**Where the county is above the line** (insurer-initiated, 2021), the two ZIPs the design doc anticipated:

| zip | place | rate | predicted | residual | policies | rank of 1,647 CA ZIPs |
|---|---|---|---|---|---|---|
| 94549 | Lafayette | 5.67 % | 2.64 % | +3.03 pts | 10,812 | 107 |
| 94563 | Orinda | 6.95 % | 4.73 % | +2.21 pts | 8,319 | 164 |
| 94548 | Knightsen | 3.42 % | 2.38 % | +1.05 pts | 146 | 291 |
| 94526 | Danville | 3.32 % | 2.42 % | +0.90 pts | 11,963 | 315 |
| 94507 | Alamo | 3.27 % | 2.64 % | +0.63 pts | 6,333 | 375 |

Lafayette is the clearest case: only 4 % of its area is Very High hazard, yet insurers dropped it at more than twice the
rate hazard predicts. Orinda is 76 % Very High and is still dropped above its prediction.

**What this does not show.** The 2023 fit uses total non-renewals because CDI stopped publishing the insurer/insured
split after 2021. About 85 % of "non-renewals" in that series are insured-initiated (people leaving), so the 2023 fit
measures churn, not insurer behaviour. There is no per-insurer data in any public CDI release, so "portfolio strategy
of a specific carrier" cannot be tested here.

## 2. The FAIR Plan absorbed the county's hazard ZIPs after the public non-renewal data ends

**Query:** `fair_mirror` (ZIP-year join of FAIR Plan policies in force with voluntary-market counts) and
`cdi_fair_plan` directly for FY2024–FY2025, which the voluntary series does not reach.

| fiscal year (9/30) | CC FAIR Plan policies | CA FAIR Plan policies |
|---|---|---|
| 2021 | 1,057 | 236,515 |
| 2022 | 1,223 | 265,909 |
| 2023 | 1,929 | 320,572 |
| 2024 | 6,423 | 449,833 |
| 2025 | 12,609 | 621,234 |

Contra Costa's FAIR Plan book grew 11.9× in four years against 2.6× statewide. Half of the county's FY2025 FAIR policies
sit in four ZIPs:

| zip | place | FAIR FY2021 | FAIR FY2025 | FAIR share of (FAIR + 2023 voluntary) | Very High share |
|---|---|---|---|---|---|
| 94563 | Orinda | 157 | 2,617 | 27.7 % | 0.76 |
| 94549 | Lafayette | 114 | 1,773 | 16.4 % | 0.04 |
| 94506 | Danville / Blackhawk | 40 | 1,087 | 11.8 % | 0.13 |
| 94507 | Alamo | 39 | 827 | 12.9 % | 0.05 |

Across CC ZIPs the FY2025 FAIR count correlates with Very High hazard share at r = 0.49; the ZIP-year change in FAIR
policies does not correlate with same-year voluntary non-renewals (r = −0.10 over 2022–2023). The absorption is
concentrated in the same Lamorinda / Diablo-valley ZIPs that were above the hazard line in finding 1, and most of it
happened in FY2024–FY2025, after the last CDI non-renewal release (2023). The public non-renewal series therefore
cannot show the largest movement in the county's market; the FAIR Plan's own counts can.

## 3. Moratoriums: none has ever applied to Contra Costa; where they did apply, non-renewals were deferred, not prevented

**Query:** `moratorium_deferral` — for every ZIP with a `PROTECTED_BY` edge, insurer-initiated non-renewals in the year
before, during and after the moratorium year (release 2015–2021), against all other CA ZIPs.

No CDI moratorium bulletin has ever named a Contra Costa ZIP (CDI's moratorium list, checked 2026-09-04). The two
bulletins in the graph cover the 2020 Bobcat, Oak and Slater fires (57 ZIPs, LA / Mendocino / Del Norte) and the 2025
Los Angeles fires (106 ZIPs). Only the 2020 moratorium falls inside the non-renewal data window.

| group | ZIPs with data | 2019 (before) | 2020 (during) | 2021 (after) | during / before | after / before |
|---|---|---|---|---|---|---|
| Bobcat Fire moratorium (LA) | 40 | 7,017 | 5,564 | 6,827 | 0.79 | 0.97 |
| Oak Fire moratorium (Mendocino) | 9 | 672 | 456 | 260 | 0.68 | 0.39 |
| Slater Fire moratorium (Del Norte) | 5 | 260 | 182 | 145 | 0.70 | 0.56 |
| all protected ZIPs | 54 | 7,949 | 6,202 | 7,232 | 0.78 | 0.91 |
| control: all other CA ZIPs | 1,600+ | 214,879 | 170,533 | 217,693 | 0.79 | 1.01 |

The moratorium year looks identical to the rest of the state (0.78 versus 0.79 of the prior year: 2020 was a low year
everywhere after the 2019 spike). The year after, protected ZIPs are still 9 % *below* their 2019 level while the
rest of the state is back above it; only 18 of 54 protected ZIPs exceeded their pre-moratorium count in 2021. The data
does not show the "moratorium defers, then non-renewals surge" pattern the design anticipated. Two caveats: the
moratorium ran 2020-09-25 to 2021-09-25 and straddles calendar years, and the three fires' ZIPs are mostly rural
Mendocino / Del Norte plus the LA foothills, so a matched control (same hazard, no moratorium) would be a fairer test
than "all other ZIPs". 3 of the 57 ZIPs named in the bulletin have no CDI rows and are absent from the table.

## 4. Trend for context

**Query:** `select release, year, sum(count), sum(nonrenewed_insurer), sum(policies) from NONRENEWED_IN edges where county = 'Contra Costa'`.

| year | CC insurer-initiated rate | CA insurer-initiated rate | CC all non-renewals | CA all non-renewals |
|---|---|---|---|---|
| 2018 | 1.21 % | 1.75 % | 9.24 % | 9.68 % |
| 2019 | 1.40 % | 2.43 % | 9.39 % | 10.58 % |
| 2020 | 1.45 % | 1.93 % | 9.89 % | 10.25 % |
| 2021 | 2.00 % | 2.45 % | 11.23 % | 11.36 % |
| 2022 (2020–2023 release) | — | — | 9.09 % | 9.56 % |
| 2023 (2020–2023 release) | — | — | 7.39 % | 8.67 % |

Insurer-initiated non-renewals in the county rose 65 % between 2018 and 2021 but stayed below the state rate
throughout. The two CDI releases disagree on their overlapping years (2020, 2021) by 7–8 % statewide; rows above name
the release they come from and the releases are never mixed within a comparison.

## What is and is not supported

- Supported: hazard is a weak predictor county-wide (finding 1); Lafayette and Orinda are dropped above their hazard
  prediction (finding 1); FAIR Plan growth is concentrated in those same ZIPs and post-dates the public non-renewal
  data (finding 2); no moratorium has protected the county (finding 3).
- Not supported by this data: any claim about a named insurer; any claim that 2022–2023 insurer behaviour worsened,
  because the split is not published; causal attribution of Lafayette's excess to anything in particular.

## Extraction quality

`make eval` against the two hand-labeled bulletins (`extraction_service/eval/golden/`), model
`accounts/fireworks/models/gpt-oss-120b` through the `openai_compat` adapter, schema v1, temperature 0:

| precision | recall | true positives | false positives | false negatives |
|---|---|---|---|---|
| 1.000 | 0.973 | 180 | 0 | 5 |

The five misses are the two `AUTHORED` edges for SB 824 (the model did not emit them), one ZIP (93543) whose ZIP
entity the model forgot to declare so the type validator rejected the edge, and two ZIP edges it omitted. Every edge
in the graph from these documents carries a verbatim span and its source URL (see the app's Evidence tab). Graph:
2,706 entities, 37,177 edges, of which 180 are LLM-extracted; 0 entities are `pending:` review.
