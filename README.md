# policygraph

What is happening with home-insurance non-renewals in Contra Costa County, and what is driving it?

```
uv sync --extra dev
cp .env.example .env          # fill CENSUS_API_KEY and the extraction provider key
make service PORT=8001 &      # extraction API (only needed for `make extract` and new mentions in `make resolve`)
make worker &                 # extraction worker; the only process that talks to a model
make all                      # fetch → normalize → extract → resolve → graph → insights
make app
```

`make graph`, `make insights` and `make app` need no network and no keys: extraction artifacts are committed under
`data/extractions/`, pinned by `config/extraction_manifest.yaml`, and every resolver answer is pinned in
`config/resolutions.yaml`. `make fetch` is a conditional GET per source (a no-op when nothing changed; `FORCE=1`
re-downloads); `make normalize` takes about five minutes for the hazard overlay. `make extract FORCE=1` re-runs the model.

`make test` runs the unit tests and the 50-mention resolution regression set; `make eval` scores extraction against the
four hand-labelled bulletins; `make lint` runs ruff; `make docker` builds the app image. CI runs lint and test on push.

Design: `docs/ARCHITECTURE.md`, `docs/EXTRACTION_SERVICE.md`. Sources and their limits: `docs/DATA_SOURCES.md`.
Findings with their queries: `docs/FINDINGS.md`.

## App

`policygraph/app.py` reads only `data/insights/`: Findings · Map (pydeck choropleth of the county's ZIPs by rate,
hazard residual, FAIR Plan share, home value, moratorium coverage) · Timeline (rates against dated events) ·
Graph (neighbourhood explorer with span-on-hover) · the five insight tables · Evidence. Deployed on Streamlit
Community Cloud from `main`; `requirements.txt` lists only what the app imports.

## Sources

| source | what | shape observed |
|---|---|---|
| CDI voluntary-market policy counts by ZIP | 2015–2021 (with insurer/insured split) and 2020–2023 (total only) | two xlsx workbooks; no insurer identity |
| California FAIR Plan | residential policies in force by ZIP, FY2021–FY2025 | one AES-encrypted PDF; column layout read from the footer |
| CAL FIRE FHSZ | SRA (effective 2024-04-01) and LRA (2025-03-24) hazard zones | ArcGIS feature services, paged as GeoJSON |
| Census | ZCTA cartographic boundaries; ACS 5-year home value, year built, income | shapefile zip; JSON (API key) |
| CDI bulletins | SB 824 moratorium bulletins 2019, 2020-11, 2020-12, 2025-1 | PDF prose, read by the extraction service |
| CDI press releases | Sustainable Insurance Strategy regulations; State Farm, Mercury and CSAA rate decisions | HTML prose, read by the extraction service |
