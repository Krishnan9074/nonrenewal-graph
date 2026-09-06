# Data sources

Every input is declared in `config/sources.yaml`; `make fetch` records the sha256 of each download in
`data/raw/manifest.yaml` (local, with the server's ETag / Last-Modified so a re-run is a conditional GET) and
in `config/source_hashes.yaml` (committed, so a changed upstream file shows as `changed` before it is normalized).

## Structured sources (ingested deterministically, never read by a model)

| source id | what | url | shape observed | normalizer output |
|---|---|---|---|---|
| `cdi_nonrenewal` | CDI residential voluntary-market policy counts by ZIP and year | two xlsx workbooks: 2015–2021 (with insurer-/insured-initiated split), 2020–2023 (total only) | columns `County, ZIP Code, Year, New, Renewed, Insurer-Initiated Nonrenewed, Insured-Initiated Nonrenewed` / `Non-Renewed`; county blank for PO-box ZIPs | `cdi_nonrenewal.parquet`, one row per ZIP-year-release |
| `cdi_fair_plan` | California FAIR Plan residential policies in force by ZIP, 9/30 of FY2021–FY2025 | one AES-encrypted PDF from cfpnet.com | rows of `zip (growth count)×(n−1) oldest_count`; the fiscal years come from the page footer, so a sixth column parses without a code change | `cdi_fair_plan.parquet` |
| `calfire_fhsz` | CAL FIRE Fire Hazard Severity Zones, SRA (effective 2024-04-01) and LRA (2025-03-24) | ArcGIS feature services, paged as GeoJSON in EPSG:3310; the layer's `dataLastEditDate` is the change detector | `FHSZ_Description` ∈ Moderate / High / Very High (+ NonWildland in LRA, dropped) | `hazard_share.parquet`: area share of each class per ZCTA |
| `census_zcta` | ZCTA5 cartographic boundaries (2020, 1:500k) | shapefile zip | national; filtered to 90000–96199 | `zcta.parquet` (EPSG:3310) |
| `acs_zcta` | ACS 2023 5-year: median home value (B25077), median year built (B25035), median household income (B19013) | Census API JSON (needs `CENSUS_API_KEY`) | suppressed cells are `-666666666` → null | `acs.parquet`; attached to ZIP entities as `attrs` |

## Prose sources (read by the extraction service only)

| source id | documents | url pattern | notes |
|---|---|---|---|
| `cdi_bulletins` | SB 824 moratorium bulletins: 2019 (2nd amended, dated 2020-02-03), 2020-11 (amended 2020-11-06), 2020-12, 2025-1 (amended 2025-01-17) | insurance.ca.gov `…/0200-bulletins/…/upload/*.pdf` | The 2019 bulletin's Sky Fire list and 2020-11's SCU Lightning Complex list name Contra Costa ZIPs. Text is pypdf output; the 2019 PDF prints one ZIP as `9 4572`, which the anchor validator cannot see. |
| `cdi_press` | Sustainable Insurance Strategy announcement (2023-09-21), catastrophe-model regulation (2024-12-13), net-cost-of-reinsurance regulation (2024-12-30), State Farm emergency interim rate request and decision (2025-02-14, 2025-05-13), Mercury / CSAA rate approvals (2025-12-20), State Farm settlement (2026-03-06) | insurance.ca.gov `…/0100-press-releases/<year>/release*.cfm`, `…/0102-alerts/…` | HTML; the page carries per-request tokens so `doc_id` hashes the extracted text, not the bytes. Text is the block between the `<H1>` headline and the right sidebar. |

The full CDI bulletin index is <https://www.insurance.ca.gov/01-consumers/140-catastrophes/MandatoryOneYearMoratoriumNonRenewals.cfm>.

## Data facts that bound every finding (not fixable in code)

- **No public per-insurer ZIP data.** CDI's ZIP workbooks carry no company name or NAIC code, so nothing in the graph
  can attribute a ZIP's non-renewals to a named carrier. `NONRENEWED_IN` edges run from `market:ca:voluntary`.
- **The insurer/insured split ends in 2021.** The 2020–2023 release publishes totals only; about 85 % of total
  non-renewals are insured-initiated, so 2022–2023 measure churn, not insurer behaviour.
- **The two CDI releases disagree by 7–8 % on 2020–2021.** Both are loaded, tagged by `release`, and never summed;
  every insight names the release it used. CDI gives no reason for the difference.
- **Three ZIPs in the 2020-12 bulletin have no CDI rows** (and a handful in the other bulletins); they are absent
  from the deferral tables.
- **Rate decisions and regulations post-date the non-renewal series.** The public series ends in 2023; the
  Sustainable Insurance Strategy regulations (Dec 2024) and the State Farm decision (May 2025) can only be aligned
  with FAIR Plan counts (to FY2025), not with non-renewals.
- **Cal-Access contributions are not ingested.** `DONATED_TO` is in the relation vocabulary but the Secretary of
  State's raw export is a multi-GB dump with no per-committee endpoint; it is deterministic tabular work, not
  extraction, and is left for the next iteration.
