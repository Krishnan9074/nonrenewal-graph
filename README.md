# policygraph

What is happening with home-insurance non-renewals in Contra Costa County, and what is driving it?

```
uv sync --extra dev
cp .env.example .env          # fill CENSUS_API_KEY and the extraction provider key
make service PORT=8001 &      # extraction API (only needed for `make extract`)
make worker &                 # extraction worker; the only process that talks to a model
make all                      # fetch → normalize → extract → resolve → graph → insights
make app
```

`make graph` and `make app` need no network and no keys: extraction artifacts are committed under
`data/extractions/` and pinned by `config/extraction_manifest.yaml`. Raw and normalized data are rebuilt by
`make fetch` and `make normalize` (about 5 minutes, 330 MB of raw downloads).

Design: `docs/ARCHITECTURE.md`, `docs/EXTRACTION_SERVICE.md`. Findings with their queries: `docs/FINDINGS.md`.

## Sources

| source | what | shape observed |
|---|---|---|
| CDI voluntary-market policy counts by ZIP | 2015–2021 (with insurer/insured split) and 2020–2023 (total only) | two xlsx workbooks; no insurer identity |
| California FAIR Plan | residential policies in force by ZIP, FY2021–FY2025 | one AES-encrypted PDF |
| CAL FIRE FHSZ | SRA (effective 2024-04-01) and LRA (2025-03-24) hazard zones | ArcGIS feature services, paged as GeoJSON |
| Census | ZCTA cartographic boundaries; ACS 5-year home value, year built, income | shapefile zip; JSON (API key) |
| CDI bulletins | moratorium bulletins 2020-12 and 2025-1 | PDF prose, read by the extraction service |
