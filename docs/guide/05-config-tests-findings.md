## Part 6. Configuration, tests, findings, and how to work with the project

### 6.1 `config/schema.sql`

```sql
CREATE TABLE IF NOT EXISTS entities (
  entity_id      TEXT PRIMARY KEY,
  type           TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  attrs          JSON
);
CREATE TABLE IF NOT EXISTS documents (
  doc_id       TEXT PRIMARY KEY,
  source       TEXT NOT NULL,
  url          TEXT,
  published_at DATE,
  text         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  edge_id     TEXT PRIMARY KEY,
  src         TEXT NOT NULL,
  rel         TEXT NOT NULL,
  dst         TEXT NOT NULL,
  valid_from  DATE,
  valid_to    DATE,
  props       JSON,
  doc_id      TEXT,
  span        TEXT,
  extractor   TEXT NOT NULL,
  confidence  DOUBLE NOT NULL,
  ingested_at TIMESTAMP DEFAULT current_timestamp
);
```

The three tables from Part 1.4. Note what is `NOT NULL`: every entity has a type and a name; every edge has endpoints, a relation, an extractor and a confidence. `doc_id` and `span` are nullable because deterministic edges have no document; the invariant that model edges always carry both is enforced by the code that builds them, not by the schema.

### 6.2 `config/sources.yaml`

One entry per external input. Each has a `type` (how to download and save it: `xlsx`, `pdf`, `shapefile_zip`, `arcgis_geojson`, `json`, `html`), one `url` or a list of `urls`, and a `normalizer` (which module in `policygraph/normalize/` reads it). Document sources add `doc_source`, the label written into the documents table. The comments record what was observed about each source: the FAIR Plan PDF is fiscal-year policies in force; the ZCTA file is the generalised cartographic version because the full one is 528 MB; the CAL FIRE layers are the state and local responsibility areas with their effective dates; which bulletins cover Contra Costa.

### 6.3 `config/source_hashes.yaml`, `config/extraction_manifest.yaml`

`source_hashes.yaml` is a list of `{url, sha}` pairs written by `make fetch`; it is committed so a change upstream appears as a diff in a pull request. `extraction_manifest.yaml` is the run the graph is pinned to: run id, schema version, status, and the list of artifact ids to load, plus lists of failed and errored jobs (both empty). Changing the model or prompt produces a new manifest, reviewed like any code change; rolling back is pinning the previous one.

### 6.4 `config/entities.yaml`

The registry of entities that can only be resolved by name: insurers (keyed by NAIC code), officials, regulations and rate filings. Each has an `id`, a `type`, a `name`, a `description` (what the embedding and the judge see), and `aliases` (exact matches for resolver step 2). ZIPs, bills, fires and moratoria are not listed because rules mint them. Adding a new insurer is one YAML entry.

### 6.5 `config/resolutions.yaml`

Every answer the service ever gave for a mention that the rules and aliases could not resolve, including "nobody" answers with the nearest candidate and its cosine. Committed, so `make resolve` replays without the service, and so a changed answer shows as a diff. In the current corpus it holds one embedding match, four judge matches and one audit record for a mention the alias table now handles.

### 6.6 `config/places.yaml`

ZIP → place name for Contra Costa, used only for labels on the map, the timeline and the explorer. County membership comes from CDI's data, never from this file.

### 6.7 The tests (`tests/`)

Tests run with `make test` in about two seconds and need no network, no key and no data files beyond the config. What each file proves:

- **`test_fetch.py`** — environment variables are expanded and an unset one fails; conditional headers are built only from validators we have; a 304 leaves the prior record untouched; a source without validators is `cached` unless forced.
- **`test_normalize.py`** — the FAIR Plan parser reads rows and missing values, rejects a malformed row, and follows the footer when a sixth fiscal year appears; the CDI parser handles both releases and fails on a missing column; the ACS sentinel becomes null; the hazard overlay computes shares and ignores non-wildland; the HTML converter and the date finder work on the three date formats.
- **`test_chunk.py`** — a short text is one chunk; long text is covered end to end with overlaps.
- **`test_validators.py`** — a valid edge is kept; a paraphrased span, a ZIP not in the text, a wrong type pair, and reversed dates are each rejected with the right message; a word broken across lines still matches.
- **`test_expand.py`** — ZIP blocks get the right names, dates, ZIPs and verbatim spans from a synthetic bulletin (including the `9 4572` case, which is correctly *not* read as a ZIP); expansion adds the missing fires and ZIPs, keeps the model's own edges, folds yearless mentions, and marks what it added; the prompt view lists blocks without their ZIPs; the mention-folding rules map every known variant.
- **`test_worker.py`** — processing produces an artifact with the expected id; a second call is a cache hit and `force` recomputes; a bad span triggers exactly one retry and then a `failed_validation` status; merge keeps the more confident duplicate.
- **`test_adapters.py`** — the OpenAI-compatible adapter sends the right request and reassembles a streamed response; the embedder returns vectors in input order; transport errors are retried and then succeed.
- **`test_resolve_service.py`** — the decision rule: clear cosine winner accepted; small margin goes to the judge; judge rejection is unresolved but records the nearest; below the band the judge is never called; candidates are restricted to the mention's type and answers are cached.
- **`test_resolve.py`** — canonical rules for ZIPs, bills, fires and moratoria; aliases are case-insensitive and typed; pins are used before the service; offline residuals become pending; the original mention string is preserved.
- **`test_resolution_set.py`** — runs the 53-mention regression set in `tests/resolution_set.yaml` through the offline resolver and fails if any expected id or method differs.
- **`test_graph.py`** — moratorium windows are filled from the id; explicit dates are kept; readable names for rule-minted ids.
- **`test_insights.py`** — on a six-ZIP fixture graph: residuals sum to zero per fit and both specs run; the deferral module finds the protected ZIP, the right year, and both controls with the expected sums; the moratorium year is the window midpoint; the FAIR share is computed; the trend includes the FAIR series and the event study reads the right before/during values.

### 6.8 The extraction quality evaluation (`make eval`)

Four hand-labelled bulletins with 1,232 expected edges. The current numbers: precision 0.992, recall 0.997. The ten false positives are the Lake County Eagle Fire's ZIP list, which the 2019 bulletin prints and then withdraws in a footnote — the parser cannot read footnotes, and the choice was to keep the deterministic rule simple and report the miss. The misses are one ZIP the PDF prints as `9 4572` and the "(Lara, …)" author credit for SB 824 that the model emits in one bulletin of four.

### 6.9 What the findings say (`docs/FINDINGS.md`)

The findings document is regenerated from the insight tables and every number in it names the query that produced it. In brief:

1. **Hazard explains little; price explains less.** Very High hazard share is significant but the fit explains 13 % of the variation between ZIPs. Adding home value and income makes the Lafayette and Orinda residuals *larger*: expensive ZIPs are dropped less, statewide, not more.
2. **The FAIR Plan absorbed the county's hazard ZIPs after the public series ends.** The county's FAIR Plan book grew 11.9× from FY2021 to FY2025 against 2.6× statewide, concentrated in Orinda, Lafayette, Blackhawk and Alamo.
3. **Two moratoria covered Contra Costa, and the first deferred rather than prevented.** The 2019 Sky Fire moratorium covered eleven county ZIPs with data. Their insurer-initiated non-renewals went 1,219 → 910 → 2,253 across 2019–2021 (0.75× then 1.85× the 2019 level); the matched control went 0.83× then 1.09×. Lafayette went 209 → 136 → 613, Orinda 213 → 132 → 578.
4. **Timing.** The county's non-renewal rate moves after the 2020 fire declarations (the Sky moratorium expiring); its FAIR Plan book more than triples in the fiscal year the Sustainable Insurance Strategy regulations were finalised, before the January 2025 fires. Annual data, so alignment, not effect sizes.
5. **Actors.** The Commissioner sits on 90 % of shortest paths in the county neighbourhood; no insurer reaches any ZIP because CDI's data names no carrier.

And the limits: no per-insurer ZIP data exists; the insurer/insured split ends in 2021; the two CDI releases disagree by 7–8 % on their overlap; rate decisions post-date every non-renewal count.

### 6.10 How to run it

```
uv sync --extra dev            # install everything
cp .env.example .env           # fill CENSUS_API_KEY and the model key
make service PORT=8001 &       # extraction API
make worker &                  # extraction worker (the only model caller)
make all                       # fetch → normalize → extract → resolve → graph → insights
make app                       # http://localhost:8501
```

Without any key: `make graph`, `make insights` and `make app` work from the committed artifacts and pins. `make test` and `make lint` should be green before any commit; CI runs both.

### 6.11 How to change it

- **Add a source.** Add an entry to `sources.yaml`; if its shape is new, write a normalizer module with `run(spec, files)` and register it in `normalize/__init__.py`; add a `deterministic_edges` family in `graph.py` if it yields edges; test the parser on a small sample.
- **Add a document.** Add its URL to `cdi_bulletins` or `cdi_press`, run `make fetch normalize extract resolve graph insights`, review the new artifact and any new pins, commit them.
- **Add a relation.** Extend `Rel` and `REL_TYPES` in `models.py`, the enum in `schema/v1.json`, and the prompt; bump the schema version; add a golden example.
- **Add an entity that resolves by name.** One entry in `entities.yaml`.
- **Change the prompt or model.** Edit `prompts/v2.md` or the environment variable, run `make extract` (new prompt hash → new artifact ids), run `make eval`, review the manifest diff.
- **Add a finding.** A module in `insights/` with `compute(con)`, listed in `MODULES`; a tab in `app.py`; numbers into `FINDINGS.md`.

### 6.12 What is deliberately not there

- Cal-Access campaign contributions (`DONATED_TO`) are in the vocabulary but not ingested; the Secretary of State's export is a multi-gigabyte dump with no per-committee endpoint.
- A human review queue for `pending:` entities; today there are none, and the pins file is the review surface.
- Quarterly resolution for the event study; CDI publishes annual counts.
- Bit-exact reproducibility of model output; hosted models are not deterministic even at temperature 0. What is guaranteed is *replayability*: the committed artifacts, pinned by the manifest, rebuild the same graph forever without a key.
