# policygraph — the complete guide

*A line-by-line teaching walk-through of the whole project, written for someone who has never seen the code.*

---

## Part 0. How to read this guide

This document explains everything in the repository: what the project is for, how the data flows, what every file does, and what every line of code in it means. It is long because the request was "every single thing". It is organised so that you can also dip in:

- **Part 1** explains the problem and the design in plain language, and defines every technical term used later.
- **Part 2** explains the tooling: how the project is built, run, tested and deployed.
- **Part 3** walks through the data pipeline (`policygraph/`) file by file, line by line.
- **Part 4** walks through the analysis modules (`policygraph/insights/`) and the web app (`policygraph/app.py`, `policygraph/views/`).
- **Part 5** walks through the extraction service (`extraction_service/`), the part that talks to a language model.
- **Part 6** explains the configuration files, the tests, the findings, and how to run, change and extend the project.

Code is shown in boxes with line numbers. Each box is followed by an explanation keyed to those line numbers. Where several lines do the same kind of thing (for example five `import` lines) they are explained together.

Conventions in the explanations:

- "The pipeline" means the Python package `policygraph/`, run stage by stage from the command line.
- "The service" means `extraction_service/`, a separate program with its own web API and a background worker.
- "The app" means the Streamlit web page in `policygraph/app.py` and `policygraph/views/`.
- "CDI" is the California Department of Insurance. "FAIR Plan" is California's state-mandated insurer of last resort. "SB 824" is the 2018 state law that creates one-year moratoriums on non-renewals after a wildfire emergency. "FHSZ" is CAL FIRE's Fire Hazard Severity Zone map. "ACS" is the Census Bureau's American Community Survey. "ZCTA" is the Census version of a ZIP code area.

---

## Part 1. What the project is and how it thinks

### 1.1 The question

Home insurers in California have been refusing to renew policies ("non-renewals") at rising rates. The project asks one narrow question about one county: **what is actually happening with home-insurance non-renewals in Contra Costa County, and what appears to be driving it?**

The candidate explanations are the ones anyone would list:

1. **Fire hazard.** Insurers drop houses that are likely to burn.
2. **Price.** Expensive houses are expensive to rebuild, so insurers drop them regardless of fire risk.
3. **Moratoriums.** After a declared wildfire emergency, SB 824 forbids non-renewals in ZIP codes near the fire for one year. Do those moratoriums prevent non-renewals or only delay them?
4. **Regulation.** The Insurance Commissioner's rules and rate decisions change insurers' incentives. Does the timing of non-renewals follow the regulatory calendar more than the fire calendar?
5. **Actors.** Which people and organisations sit on the most paths between a decision and an outcome in the county?

None of these can be answered from any single data set. The answer lives in the *joins*: CDI's ZIP-level counts joined to CAL FIRE's hazard map; the text of CDI's moratorium bulletins joined to the count time series; FAIR Plan counts joined to both. The project is a machine for making those joins reliably, with a receipt for every fact.

### 1.2 The design principles

The whole codebase follows six rules, and understanding them makes every file predictable.

1. **Structured data never touches a language model.** Spreadsheets, PDF tables, map files and Census JSON are read by ordinary deterministic code. A model reads prose only (bulletins, regulations, press releases) and emits typed JSON.
2. **Canonical identifiers before fuzzy matching.** A ZIP code is `zip:94563`. An insurer is its NAIC company code, `insurer:naic:25143`. A bill is `bill:ca:SB824`. A fire is `fire:eaton:2025`. A moratorium is `moratorium:2025-01-07:eaton`. Only when a mention cannot be keyed like this does the project fall back to an alias table, then to embeddings, then to a model acting as a judge.
3. **Every edge carries provenance.** Each fact in the graph records where it came from (document, URL), the exact quoted text that supports it (the "span"), what produced it (deterministic code or a named model), and a confidence.
4. **The graph is temporal.** Facts have `valid_from` and `valid_to` dates. Nothing is overwritten; new facts are appended.
5. **The pipeline is idempotent and content-addressed.** Every stage is keyed by a hash of its inputs. Running a stage twice on the same inputs does nothing new. A changed input reprocesses only what depends on it.
6. **Insights are precomputed; serving is read-only.** The web app never calls a model or runs a heavy query. It reads small files that the pipeline wrote.

### 1.3 The data flow in one picture

```
sources.yaml ──► fetch ──► data/raw/            (bytes, named by their hash)
                    │
                    ▼
               normalize ──► data/normalized/   (typed tables; documents table for prose)
                    │
                    ▼
                extract ──► extraction service ──► data/extractions/*.json  (model output, validated)
                    │                               config/extraction_manifest.yaml (which artifacts are pinned)
                    ▼
                resolve ──► data/normalized/resolved.parquet   (mention → canonical entity id)
                    │       config/resolutions.yaml            (every answer the service gave)
                    ▼
                 graph  ──► data/graph.duckdb   (entities, edges, documents)
                    │
                    ▼
               insights ──► data/insights/*.parquet + cc_zips.geojson   (one table per finding + app tables)
                    │
                    ▼
                  app   ──► Streamlit web page reading only data/insights/ and docs/FINDINGS.md
```

Each arrow is one command (`make fetch`, `make normalize`, and so on). `make all` runs them in order.

### 1.4 The graph model

The graph has three tables (defined in `config/schema.sql`, explained in Part 6):

- **entities** — one row per thing: a ZIP, an insurer, a fire, a moratorium, a regulation, an official, a rate filing, a hazard class, the anonymous "voluntary market". Each has an id, a type, a readable name, and optional attributes (for ZIPs: county, median home value, median income).
- **edges** — one row per fact: `src --rel--> dst`, with dates, a JSON bag of properties, the document and span it came from, the extractor, and a confidence. The relation vocabulary is closed:

| relation | from → to | produced by |
|---|---|---|
| `NONRENEWED_IN` | voluntary market → ZIP | CDI spreadsheets (deterministic), one edge per ZIP-year-release with counts in `props` |
| `HAZARD_SHARE` | ZIP → FHSZ class | geometry overlay (deterministic), `props.pct` is the area share |
| `HAS_FAIR_PLAN_POLICIES` | ZIP → FAIR Plan | FAIR Plan PDF (deterministic), `props.count` per fiscal year |
| `PROTECTED_BY` | ZIP → moratorium | bulletins (model + deterministic ZIP-block expansion) |
| `TRIGGERED` | fire → moratorium | bulletins |
| `ISSUED` | official → moratorium or regulation | bulletins and press releases |
| `FILED` | insurer → rate filing | press releases |
| `DECIDED` | official → rate filing | press releases |
| `AUTHORED` | official → regulation | bulletins ("Senate Bill 824 (Lara, …)") |
| `DONATED_TO` | insurer → official | in the vocabulary; no source ingested yet |

- **documents** — one row per prose document: id (hash of its text), source, URL, publication date, full text.

### 1.5 Glossary of technical terms

These terms recur throughout the code. Skim now, refer back later.

- **Python package / module.** A module is one `.py` file. A package is a folder of modules with an `__init__.py` file. `policygraph/insights/trend.py` is the module `policygraph.insights.trend`.
- **`import x` / `from x import y`.** Loads another module so its functions and constants can be used.
- **Type hints** such as `def f(x: int) -> str`. Annotations saying what a function takes and returns. Python does not enforce them; they document intent and let tools check it.
- **`dataclass`.** A decorator that turns a class into a simple record with named fields. `frozen=True` makes instances immutable.
- **Pydantic `BaseModel`.** Like a dataclass but *validating*: constructing one from a dictionary checks every field's type and constraints and raises if anything is off. Used at every boundary where data comes from outside (the model's JSON, HTTP requests).
- **pandas `DataFrame` / `Series`.** A table and a column, respectively. Most transformations here are one-line pandas expressions.
- **Parquet.** A compressed columnar file format for tables; fast to read, keeps column types.
- **DuckDB.** An embedded SQL database that lives in one file (`data/graph.duckdb`) and queries pandas frames and parquet directly.
- **GeoPandas / shapely / CRS.** GeoPandas is pandas with a geometry column. A CRS (coordinate reference system) says what the numbers mean; EPSG:3310 is "California Albers", a metre-based projection in which areas are correct; EPSG:4326 is plain latitude/longitude for web maps.
- **Regular expression (regex).** A pattern for matching text, compiled with `re.compile`. `\d{5}` means five digits; `^` and `$` anchor to line start and end; `(...)` captures a group; `(?:...)` groups without capturing; `?` makes the preceding thing optional; `re.I` ignores case; `re.M` makes `^`/`$` match at every line.
- **SHA-256.** A hash function: any bytes in, a fixed 64-character hex string out, and any change to the input changes the output. Used to name files by content and to build stable ids.
- **HTTP conditional GET.** Asking a web server "send me this file unless it is unchanged since this ETag / date". If unchanged the server answers `304 Not Modified` with no body.
- **LLM (large language model).** The model that reads prose. The project uses an open-weight model (`gpt-oss-120b`) through Fireworks' OpenAI-compatible API, at temperature 0 (least random).
- **JSON schema / structured output.** A description of the exact JSON shape the model must produce; the API refuses anything else.
- **Embedding.** A vector of numbers representing a piece of text so that similar texts have similar vectors. Cosine similarity between two vectors is 1.0 for identical direction, 0 for unrelated.
- **OLS regression.** Ordinary least squares: fit a line (or hyperplane) through points; the residual is how far each point sits above or below the fitted line. R² is the share of variance the fit explains.
- **Betweenness centrality.** For a node in a network, the share of shortest paths between all other node pairs that pass through it.
- **Streamlit.** A Python library that turns a script into a web page; `st.dataframe`, `st.selectbox` and so on draw widgets.
- **uv.** The Python package manager used here; `uv run` runs a command inside the project's virtual environment.
- **Make.** A tool that runs named recipes from a `Makefile`; `make fetch` runs the `fetch` recipe.

---

## Part 2. Tooling: how the project is built and run

### 2.1 `Makefile`

```make
 1  .PHONY: all fetch normalize extract resolve graph insights app test eval lint service worker docker
 2
 3  PY := uv run --env-file .env python
 4  PORT ?= 8000
 5
 6  all: fetch normalize extract resolve graph insights
 7
 8  fetch:      ; $(PY) -m policygraph fetch $(if $(FORCE),--force)
 9  normalize:  ; $(PY) -m policygraph normalize
10  extract:    ; $(PY) -m policygraph extract $(if $(FORCE),--force)
11  resolve:    ; $(PY) -m policygraph resolve $(if $(FORCE),--force)
12  graph:      ; $(PY) -m policygraph graph
13  insights:   ; $(PY) -m policygraph insights
14  app:        ; uv run streamlit run policygraph/app.py
15  test:       ; uv run pytest -q
16  eval:       ; $(PY) -m extraction_service.eval
17  lint:       ; uv run ruff check . && uv run ruff format --check .
18  docker:     ; docker build -t policygraph .
19  service:    ; uv run --env-file .env uvicorn extraction_service.api:app --port $(PORT)
20  worker:     ; $(PY) -m extraction_service.worker
```

- **1** `.PHONY` tells Make these names are commands, not files to build, so `make test` always runs even if a file called `test` exists.
- **3** `PY` is a variable: "run Python inside the project environment, first loading variables from `.env`". `.env` holds secrets (API keys); it is never committed.
- **4** `PORT ?= 8000` sets a default port for the service; `make service PORT=8001` overrides it.
- **6** `make all` runs the six pipeline stages in order.
- **8–13** Each stage runs `python -m policygraph <stage>`, which goes through `policygraph/__main__.py` (Part 3). `$(if $(FORCE),--force)` appends `--force` only when you type `make fetch FORCE=1`.
- **14** `make app` starts the web page locally.
- **15–17** Tests, the extraction quality evaluation, and the linter/formatter check.
- **18** Builds the Docker image.
- **19** Starts the extraction service's HTTP API with uvicorn (a web server for Python). The `--env-file .env` matters: the API's resolve endpoint needs the model keys.
- **20** Starts the extraction worker, the only process that ever talks to a model.

### 2.2 `pyproject.toml`

```toml
 1  [project]
 2  name = "policygraph"
 3  version = "0.1.0"
 4  requires-python = ">=3.12"
 5  dependencies = [
 6    "duckdb>=1.1", "pandas>=2.2", "pyarrow>=17", "geopandas>=1.0", "openpyxl>=3.1",
 7    "httpx>=0.27", "pydantic>=2.8", "pyyaml>=6", "typer>=0.12", "pypdf>=5",
 8    "networkx>=3.3", "statsmodels>=0.14", "streamlit>=1.38", "pydeck>=0.9",
 9    "fastapi>=0.115", "uvicorn>=0.30", "anthropic>=0.40",
10    "cryptography>=43",  # FAIR Plan PDFs are AES-encrypted; pypdf needs it to decrypt
11  ]
12
13  [project.optional-dependencies]
14  dev = ["pytest>=8", "ruff>=0.6"]
15
16  [tool.ruff]
17  line-length = 130
18  target-version = "py312"
19
20  [tool.ruff.lint]
21  select = ["E", "F", "I", "B", "UP", "SIM"]
22
23  [tool.pytest.ini_options]
24  testpaths = ["tests"]
25  pythonpath = ["."]
```

- **1–4** Project name, version, and the Python version it needs.
- **5–11** Runtime dependencies. Each earns its place: `duckdb` (graph store), `pandas`/`pyarrow` (tables, parquet), `geopandas` (map overlay), `openpyxl` (reading `.xlsx`), `httpx` (HTTP client), `pydantic` (validation), `pyyaml` (config files), `typer` (command-line interface), `pypdf` (PDF text), `networkx` (graph algorithms), `statsmodels` (regression), `streamlit`/`pydeck` (app and map), `fastapi`/`uvicorn` (service API), `anthropic` (one of two model adapters), `cryptography` (the FAIR Plan PDF is encrypted).
- **13–14** Extra tools only developers need: `pytest` runs tests, `ruff` lints and formats.
- **16–21** Ruff settings: lines may be up to 130 characters; the selected rule families are errors (`E`), pyflakes (`F`), import ordering (`I`), bugbear (`B`), modern syntax (`UP`) and simplifications (`SIM`).
- **23–25** Pytest looks in `tests/` and puts the repo root on the import path so tests can `import policygraph`.

`uv.lock` (not shown) pins the exact version of every dependency so every machine installs the same thing.

### 2.3 `requirements.txt` (for Streamlit Cloud only)

```
streamlit>=1.48
pandas>=2.2
pyarrow>=17
pydeck>=0.9
altair>=5
numpy>=2
```

Streamlit Community Cloud installs only this file. The app imports nothing from the pipeline beyond path constants, so it needs none of the heavy dependencies (no DuckDB, no GeoPandas, no model client).

### 2.4 `Dockerfile` and `.dockerignore`

```docker
 1  FROM python:3.12-slim
 2  COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
 3  WORKDIR /app
 4  ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
 5  COPY pyproject.toml uv.lock ./
 6  RUN uv sync --frozen --no-dev --no-install-project
 7  COPY . .
 8  RUN uv sync --frozen --no-dev
 9  CMD ["uv", "run", "streamlit", "run", "policygraph/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

- **1** Start from a small official Python 3.12 image.
- **2** Copy the `uv` binary in from its own image.
- **5–6** Copy only the dependency files first and install dependencies. Docker caches this layer, so editing code does not reinstall everything.
- **7–8** Copy the rest of the project and finish the install.
- **9** The container's default command runs the app on port 8501, listening on all interfaces.

`.dockerignore` keeps `.git`, the virtual environment, raw and normalized data, `.env` and caches out of the image.

### 2.5 `.github/workflows/ci.yml`

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev
      - run: make lint
      - run: make test
```

On every push and pull request GitHub checks out the code, installs uv and the dependencies (including dev tools), then runs the linter and the tests. A red mark on a commit means one of those failed.

### 2.6 `.env.example` and `.gitignore`

`.env.example` documents every environment variable. Copy it to `.env` and fill in the keys:

- `CENSUS_API_KEY` — needed once, by `make fetch`, for the ACS download.
- `EXTRACTION_SERVICE_URL` — where the pipeline finds the service (`http://localhost:8001` on this machine).
- `EXTRACTION_STORE` — where the service writes artifacts (`data/extractions`).
- `EXTRACTION_PROVIDER` — `openai_compat` or `anthropic`; which model adapter the worker uses.
- `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY`, `EXTRACTION_MODEL` — the OpenAI-compatible endpoint (Fireworks), its key, and the model id.
- `ANTHROPIC_API_KEY` — only if the provider is `anthropic`.
- `EMBED_MODEL` — the embedding model for the resolver's kNN step.
- `EXTRACTION_MAX_TOKENS` — output cap per model call (100,000; a 700-ZIP bulletin with quoted spans is about 80,000 tokens).

`.gitignore` keeps out of git: `.env`, the virtual environment, compiled Python, the raw downloads (330 MB), the normalized tables, the DuckDB file, the service's SQLite queue index, and macOS `.DS_Store` files. Everything else — including the extraction artifacts and the insight tables — is committed, which is what lets the graph and the app rebuild without any network or key.

### 2.7 The command-line entry point: `policygraph/__main__.py`

```python
 1  import typer
 2
 3  from policygraph import extract, fetch, graph, insights, normalize, resolve
 4
 5  app = typer.Typer(no_args_is_help=True)
 6  for name, mod in (
 7      ("fetch", fetch),
 8      ("normalize", normalize),
 9      ("extract", extract),
10      ("resolve", resolve),
11      ("graph", graph),
12      ("insights", insights),
13  ):
14      app.command(name)(mod.run)
15
16  if __name__ == "__main__":
17      app()
```

- **1** Typer builds command-line interfaces from Python functions.
- **3** Import the six stage modules.
- **5** Create the CLI; with no arguments it prints help.
- **6–14** For each (name, module) pair, register the module's `run` function as a sub-command with that name. Typer reads the function's parameters, so `run(force: bool = False)` automatically becomes a `--force` flag.
- **16–17** When the file is executed as a script (`python -m policygraph`), start the CLI.

### 2.8 Shared constants: `policygraph/__init__.py`

```python
 1  from pathlib import Path
 2
 3  ROOT = Path(__file__).resolve().parent.parent
 4  CONFIG, DATA, DOCS = ROOT / "config", ROOT / "data", ROOT / "docs"
 5  RAW, NORMALIZED, EXTRACTIONS, INSIGHTS = (DATA / d for d in ("raw", "normalized", "extractions", "insights"))
 6  GRAPH_DB = DATA / "graph.duckdb"
 7  COUNTY_FIPS = "06013"
```

- **3** `__file__` is this file's path; two `.parent`s up is the repository root. Every path in the project derives from this, so the code works from any working directory.
- **4–6** Named folders and the graph file.
- **7** Contra Costa's FIPS county code, kept for reference.

### 2.9 Small helpers: `policygraph/util.py`

```python
 9  def sha256(data: bytes) -> str:
10      return hashlib.sha256(data).hexdigest()
11
13  def stable_id(*parts: Any) -> str:
14      return sha256(json.dumps(parts, sort_keys=True, default=str).encode())
15
17  def load_yaml(path: Path) -> dict:
18      return yaml.safe_load(path.read_text())
19
21  def dump_yaml(path: Path, obj: object) -> None:
22      path.write_text(yaml.safe_dump(obj, sort_keys=False))
```

- **9–10** Hash bytes to a hex string.
- **13–14** Hash any list of values: serialise them to JSON with sorted keys (so the same content always gives the same string; `default=str` turns dates and other non-JSON values into strings), then hash. Used for edge ids.
- **17–22** Read and write YAML files. `safe_load` refuses to execute anything; `sort_keys=False` preserves the order the code wrote.
