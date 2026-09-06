# Findings — home-insurance non-renewals, Contra Costa County

Every number below is produced by `make insights` from `data/graph.duckdb` and materialized in `data/insights/*.parquet`.
The query that produced each table is named; the SQL lives in `policygraph/insights/<module>.py`. "CC" is Contra Costa
County (52 ZIPs in CDI's data, 40 with more than 50 policies). Rates are non-renewals divided by policies
(new + renewed + non-renewed). The two CDI releases (2015–2021 with the insurer/insured split, 2020–2023 totals only)
disagree by 7–8 % on their overlapping years and are never mixed within a comparison.

## 1. Fire hazard explains little of the county's non-renewals, and price explains even less

**Query:** `hazard_residual.fit` — OLS of ZIP non-renewal rate on Very High and High FHSZ area shares across every CA ZIP
with more than 50 policies (`spec = hazard`), then the same with log median home value and log median household income
from ACS 2023 added (`spec = hazard+acs`). Residual = actual − predicted.

| fit | year | release | spec | CA ZIPs | R² | Very High coef | home value coef | CC ZIPs above the line | CC mean residual |
|---|---|---|---|---|---|---|---|---|---|
| insurer-initiated | 2021 | 2015–2021 | hazard | 1,647 | 0.13 | +3.09 pts (p < 0.001) | — | 7 of 40 | −0.66 pts |
| insurer-initiated | 2021 | 2015–2021 | hazard + ACS | 1,531 | 0.20 | +3.06 pts (p < 0.001) | −0.71 pts per log $ (p < 0.001) | 11 of 38 | −0.18 pts |
| all non-renewals | 2023 | 2020–2023 | hazard | 1,628 | 0.13 | +5.11 pts (p < 0.001) | — | 1 of 40 | −1.99 pts |
| all non-renewals | 2023 | 2020–2023 | hazard + ACS | 1,523 | 0.32 | +5.24 pts (p < 0.001) | −2.01 pts per log $ (p < 0.001) | 10 of 38 | −0.64 pts |

Hazard share is significant but explains 13 % of the variance between ZIPs. The obvious rival explanation — that
Lafayette and Orinda are dropped because expensive houses are expensive to insure — runs the wrong way: statewide,
higher home value and income predict *fewer* insurer-initiated non-renewals, so controlling for them makes the
Lamorinda residuals larger, not smaller.

**Where the county is above the line** (insurer-initiated, 2021):

| zip | place | rate | hazard-predicted | residual | rank of 1,647 | with ACS: predicted | residual | rank of 1,531 | median home value |
|---|---|---|---|---|---|---|---|---|---|
| 94549 | Lafayette | 5.67 % | 2.64 % | +3.03 pts | 107 | 1.45 % | +4.21 pts | 56 | $1.97 M |
| 94563 | Orinda | 6.95 % | 4.73 % | +2.21 pts | 164 | 3.52 % | +3.43 pts | 76 | $1.81 M |
| 94548 | Knightsen | 3.42 % | 2.38 % | +1.05 pts | 291 | 1.77 % | +1.65 pts | 173 | $0.92 M |
| 94526 | Danville | 3.32 % | 2.42 % | +0.90 pts | 315 | 1.38 % | +1.94 pts | 148 | $1.59 M |
| 94507 | Alamo | 3.27 % | 2.64 % | +0.63 pts | 375 | 1.41 % | +1.86 pts | 157 | $2.00 M |

Lafayette is 4 % Very High hazard by area and was dropped at more than twice the rate hazard predicts; with price
controlled it ranks 56th of 1,531 California ZIPs. Finding 3 offers a candidate explanation for the timing.

**What this does not show.** The 2023 fit uses total non-renewals because CDI stopped publishing the insurer/insured
split after 2021; about 85 % of that series is insured-initiated. There is no per-insurer data in any public CDI
release, so "portfolio strategy of a specific carrier" cannot be tested on ZIP counts.

## 2. The FAIR Plan absorbed the county's hazard ZIPs after the public non-renewal data ends

**Query:** `fair_mirror` (FAIR Plan policies in force at 9/30 of each fiscal year, joined to voluntary-market counts
where the CDI series reaches) and `trend` for the fiscal-year totals.

| fiscal year (9/30) | CC FAIR Plan policies | CA FAIR Plan policies |
|---|---|---|
| 2021 | 1,057 | 236,515 |
| 2022 | 1,223 | 265,909 |
| 2023 | 1,929 | 320,572 |
| 2024 | 6,423 | 449,833 |
| 2025 | 12,609 | 621,234 |

Contra Costa's FAIR Plan book grew 11.9× in four years against 2.6× statewide. Half of the county's FY2025 FAIR policies
sit in four ZIPs:

| zip | place | FAIR FY2021 | FAIR FY2025 | FAIR share of (FAIR + voluntary), FY2023 | Very High share |
|---|---|---|---|---|---|
| 94563 | Orinda | 157 | 2,617 | 4.7 % | 0.76 |
| 94549 | Lafayette | 114 | 1,773 | 2.7 % | 0.04 |
| 94506 | Danville / Blackhawk | 40 | 1,087 | 1.7 % | 0.13 |
| 94507 | Alamo | 39 | 827 | 1.9 % | 0.05 |
| 94526 | Danville | 15 | 658 | 0.5 % | 0.00 |
| 94556 | Moraga | 21 | 582 | 1.1 % | 0.14 |

Across CC ZIPs the FY2025 FAIR count correlates with Very High hazard share at r = 0.49 (n = 39); the ZIP-year change
in FAIR policies does not correlate with same-year voluntary non-renewals (r = −0.10, 2022–2023, n = 77). The
absorption is concentrated in the same Lamorinda / Diablo-valley ZIPs that were above the hazard line in finding 1,
and most of it happened in FY2024–FY2025, after the last CDI non-renewal release. The public non-renewal series
therefore cannot show the largest movement in the county's market; the FAIR Plan's own counts can (see finding 4 for
how its timing lines up with the regulatory calendar).

## 3. Two moratoria did cover Contra Costa, and the first deferred non-renewals rather than preventing them

**Query:** `moratorium_deferral` — for every ZIP with a `PROTECTED_BY` edge, non-renewals in the year before, during and
after the moratorium year (the calendar year holding the midpoint of the 12-month window, so an October 2019
declaration is a 2020 event), against every other CA ZIP and against a control matched on Very High hazard share and
policy count (`matching.nearest`, five nearest neighbours per protected ZIP, standardized). Each CDI release is
analysed alone with the measure it publishes.

The earlier claim that no bulletin ever named a Contra Costa ZIP was wrong: it rested on two bulletins. The 2019
bulletin (2nd amended, 2020-02-03) lists 13 ZIPs under the **Sky Fire** (Governor's declaration of 2019-10-27; the
fire itself was in Solano and Contra Costa Counties), among them Lafayette, Orinda, Martinez, Concord, Pleasant Hill,
Crockett, Hercules, Pinole, El Cerrito and El Sobrante. Bulletin 2020-11 lists 14 east-county ZIPs under the
**SCU Lightning Complex** (2020-08-18): Brentwood, Antioch, Pittsburg, Oakley, Clayton, Danville, Alamo, Walnut Creek
and the Delta towns.

**Sky Fire moratorium, 2019-10-27 → 2020-10-27** — insurer-initiated non-renewals, release 2015–2021:

| group | ZIPs with data | 2019 (before) | 2020 (during) | 2021 (after) | during / before | after / before |
|---|---|---|---|---|---|---|
| protected, Contra Costa ZIPs | 11 | 1,219 | 910 | 2,253 | 0.75 | **1.85** |
| protected, all listed ZIPs | 12 | 1,309 | 988 | 2,426 | 0.75 | 1.85 |
| matched control (hazard share, policy count) | 34 | 7,259 | 6,046 | 7,935 | 0.83 | 1.09 |
| all other CA ZIPs | 1,542 | 132,892 | 112,257 | 147,713 | 0.84 | 1.11 |

| zip | place | 2019 | 2020 | 2021 |
|---|---|---|---|---|
| 94549 | Lafayette | 209 | 136 | 613 |
| 94563 | Orinda | 213 | 132 | 578 |
| 94553 | Martinez | 192 | 145 | 273 |
| 94530 | El Cerrito | 100 | 91 | 211 |
| 94803 | El Sobrante | 120 | 122 | 166 |
| 94523 | Pleasant Hill | 91 | 92 | 116 |
| 94520 | Concord | 105 | 69 | 98 |
| 94564 | Pinole | 70 | 54 | 88 |
| 94547 | Hercules | 97 | 57 | 87 |
| 94525 | Crockett | 22 | 12 | 22 |
| 94569 | Port Costa | 0 | 0 | 1 |

During the moratorium year the protected ZIPs fell a little more than their matched control (0.75 versus 0.83). The
year it expired they rose to 1.85× their 2019 level while the matched control rose to 1.09× and the rest of the state
to 1.11×. Lafayette and Orinda, the two ZIPs above the hazard line in finding 1, went from 136 and 132 insurer-initiated
non-renewals in 2020 to 613 and 578 in 2021. This is the deferral pattern the design anticipated, and it is the
county's own ZIPs that show it. Across all 16 fires in the 2019 bulletin (184 protected ZIPs with data) the pattern is weaker: 0.61 during and 1.04 after, against matched controls at a median 0.78 and 0.97. Sky's 1.85 is the highest of the 16 (Easy 1.52, Getty 1.45, Maria 1.34 next); eight of the 16 ended the year after their moratorium below their 2019 level. Deferral is visible where insurers had already been leaving, and the Lamorinda ZIPs are the clearest case in the state.

**SCU Lightning Complex moratorium, 2020-08-18 → 2021-08-18** — the window sits in 2021, which only the 2020–2023
release covers, and that release publishes totals only:

| group | ZIPs with data | 2020 | 2021 | 2022 | during / before | after / before |
|---|---|---|---|---|---|---|
| protected, Contra Costa ZIPs | 14 | 14,204 | 15,967 | 13,827 | 1.12 | 0.97 |
| protected, all 66 listed ZIPs | 66 | 48,017 | 54,798 | 47,125 | 1.14 | 0.98 |
| matched control | 259 | 176,886 | 204,117 | 172,653 | 1.15 | 0.98 |
| all other CA ZIPs | 1,460 | 581,907 | 677,865 | 575,009 | 1.16 | 0.99 |

Total non-renewals are about 85 % insured-initiated, so this table measures churn and shows no moratorium effect at
all; the insurer split that would test deferral ends in 2021.

Caveats: the 2019 PDF prints one Sky Fire ZIP as `9 4572` (Rodeo), which the anchor validator cannot see, so it is
absent; 94708 (Berkeley) is in the list but outside the county; the bulletins name ZIPs "within or adjacent to the
fire perimeter", and the Sky Fire perimeter itself was small, so most of the 13 ZIPs were protected for adjacency.

## 4. Timing: the county's non-renewal series moves with the fire calendar, its FAIR Plan book with the regulatory one

**Query:** `regulatory_alignment` — event study at the resolution the data allows (calendar years for CDI counts,
fiscal years for FAIR Plan counts): the change from the year before each dated event to the event year and the year
after, county and state, for fire declarations, regulations and rate decisions extracted from the documents.

Non-renewal rate windows (insurer-initiated, release 2015–2021, percentage points):

| event | scope | year −1 | year 0 | year +1 | Δ during | Δ after |
|---|---|---|---|---|---|---|
| October 2019 fire declarations (Saddleridge, Kincade, Sky, …) | California | 1.77 % | 2.47 % | 1.94 % | +0.68 | +0.18 |
| | Contra Costa | 1.21 % | 1.40 % | 1.45 % | +0.19 | +0.23 |
| August–September 2020 declarations (SCU, LNU, CZU, Bobcat, Glass, …) | California | 2.47 % | 1.94 % | 2.47 % | −0.50 | +0.02 |
| | Contra Costa | 1.40 % | 1.45 % | 2.00 % | +0.05 | +0.59 |
| Sustainable Insurance Strategy announced 2023-09-21 (all non-renewals, release 2020–2023) | California | 9.58 % | 8.72 % | — | −0.88 | — |
| | Contra Costa | 9.09 % | 7.39 % | — | −1.70 | — |

FAIR Plan policies in force (fiscal years ending 9/30; percent change):

| event | scope | FY −1 | FY 0 | FY +1 | Δ during | Δ after |
|---|---|---|---|---|---|---|
| Sustainable Insurance Strategy announced 2023-09-21 | California | 265,909 | 320,572 | 449,833 | +21 % | +69 % |
| | Contra Costa | 1,223 | 1,929 | 6,423 | +58 % | +425 % |
| Catastrophe-model and reinsurance regulations, December 2024 | California | 320,572 | 449,833 | 621,234 | +40 % | +94 % |
| | Contra Costa | 1,929 | 6,423 | 12,609 | +233 % | +554 % |
| LA fire declarations 2025-01-07; State Farm interim decision 2025-05-13; Mercury / CSAA approvals 2025-12-20 | California | 449,833 | 621,234 | — | +38 % | — |
| | Contra Costa | 6,423 | 12,609 | — | +96 % | — |

Statewide, insurer-initiated non-renewals jumped in the year of the 2019 fires and fell back; Contra Costa's rose
after the 2020 declarations instead, which finding 3 attributes to the Sky Fire moratorium expiring. The county's
FAIR Plan book more than tripled in FY2024 — the year that ended before the January 2025 fires and in which the
Sustainable Insurance Strategy regulations were being finalised — and doubled again in FY2025. With annual data and
events that cluster in the same years, this is an alignment, not an effect size; the rate-decision documents in the
graph (State Farm, Mercury, CSAA) post-date every non-renewal count.

## 5. One official sits on nine in ten paths; no insurer sits on any path to a ZIP

**Query:** `actor_centrality` — betweenness on the subgraph of every non-ZIP entity plus the county's ZIPs.

| entity | type | degree | betweenness | CC ZIPs within 2 hops |
|---|---|---|---|---|
| Ricardo Lara | official | 73 | 0.90 | 25 |
| SCU Lightning Complex Fire moratorium 2020-08-18 | moratorium | 16 | 0.24 | 14 |
| Sky Fire moratorium 2019-10-27 | moratorium | 13 | 0.19 | 11 |
| California voluntary market (all admitted insurers) | market | 52 | 0.13 | 52 |
| FHSZ Very High / High / Moderate | hazard class | 42 each | 0.04 | 42 |
| California FAIR Plan Association | insurer | 39 | 0.03 | 39 |
| State Farm General emergency interim rate filing 2025 | rate filing | 3 | 0.02 | 0 |

The Commissioner issued all 65 moratoria in the four bulletins, the three regulations and the three rate decisions,
so every path from a regulatory act to a county ZIP runs through him. State Farm General, Mercury and CSAA appear only
through their rate filings and reach no ZIP, because CDI's ZIP counts carry no carrier identity; the anonymised
voluntary market is the actor that touches every ZIP. This is a statement about the public record, not about
influence.

## 6. Trend for context

**Query:** `trend`.

| year | CC insurer-initiated rate | CA (rest of state) | CC all non-renewals | CA (rest of state) |
|---|---|---|---|---|
| 2018 | 1.21 % | 1.77 % | 9.24 % | 9.70 % |
| 2019 | 1.40 % | 2.47 % | 9.39 % | 10.62 % |
| 2020 | 1.45 % | 1.94 % | 9.89 % | 10.26 % |
| 2021 | 2.00 % | 2.47 % | 11.23 % | 11.36 % |
| 2022 (2020–2023 release) | — | — | 9.09 % | 9.58 % |
| 2023 (2020–2023 release) | — | — | 7.39 % | 8.72 % |

## What is and is not supported

- Supported: hazard is a weak predictor county-wide and price is not the missing variable (finding 1); Lafayette and
  Orinda are dropped above their hazard prediction (1); FAIR Plan growth is concentrated in those ZIPs and post-dates
  the public non-renewal data (2); the Sky Fire moratorium covered them and their insurer-initiated non-renewals
  roughly tripled the year it expired, against a matched control that rose 9 % (3); the county's FAIR Plan growth
  coincides with the Sustainable Insurance Strategy's regulatory calendar rather than with a fire (4).
- Not supported by this data: any claim about a named insurer's ZIP-level behaviour; any claim that 2022–2023
  insurer behaviour worsened, because the split is not published; a causal effect size for the moratorium or the
  regulations (annual data, clustered events, one treated cluster per moratorium).

## Extraction and resolution quality

`make eval` against the four hand-labelled bulletins (`extraction_service/eval/golden/`, 1,232 gold edges), model
`accounts/fireworks/models/gpt-oss-120b` through the `openai_compat` adapter, schema v1, prompt v2, temperature 0.
ZIP lists under fire headings are parsed deterministically inside the service (`anchors.zip_blocks`) and expanded into
`PROTECTED_BY` edges once the model or the bulletin's declaration section has dated the fire; those edges carry
`props.expanded_from = zip_block` and the extractor tag `|zip_block`.

| relation | precision | recall | tp | fp | fn |
|---|---|---|---|---|---|
| PROTECTED_BY | 0.991 | 1.000 | 1,097 | 10 | 0 |
| ISSUED | 1.000 | 1.000 | 65 | 0 | 0 |
| TRIGGERED | 1.000 | 0.985 | 65 | 0 | 1 |
| AUTHORED | 1.000 | 0.250 | 1 | 0 | 3 |
| all | 0.992 | 0.998 | 1,229 | 10 | 3 |

The ten false positives are the Lake County Eagle Fire list, which the 2019 bulletin prints and then withdraws in a
footnote; the misses are the `9 4572` ZIP and the "Senate Bill 824 (Lara, …)" author credit, which the model emits in
one bulletin of four. Two press-release edges were rejected for non-verbatim spans and re-emitted correctly.

Resolution (`config/resolutions.yaml`, `tests/resolution_set.yaml`): 872 mentions across the 11 documents resolved as 857 by canonical key (ZIP, bill, fire, moratorium), 10 by the alias table, 1 by embedding kNN ("State Farm emergency interim rate filing 2025", cosine 0.93) and 4 by the LLM judge at 0.96–0.99 ("Mercury Insurance", "Safer from Wildfire Regulation" and two catastrophe-model regulation variants); 0 entities are `pending:` review. Graph: 2,825 entities and 38,248 edges, of which 1,251 come from documents (607 through ZIP-block expansion), every one with a verbatim span and source URL (see the app's Evidence tab).
