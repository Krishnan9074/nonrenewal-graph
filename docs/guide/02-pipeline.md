## Part 3. The pipeline, file by file

### 3.1 `policygraph/fetch.py` — downloading sources

```python
 1  import json
 2  import os
 3  from dataclasses import asdict, dataclass
 4
 5  import httpx
 6
 7  from policygraph import CONFIG, RAW
 8  from policygraph.util import dump_yaml, load_yaml, sha256
 9
10  MANIFEST = RAW / "manifest.yaml"
11  HASHES = CONFIG / "source_hashes.yaml"  # url -> sha256 of the last fetched bytes, committed for review
12  EXT = {"xlsx": "xlsx", "pdf": "pdf", "shapefile_zip": "zip", "json": "json", "arcgis_geojson": "geojson", "html": "html"}
13  PAGE = 2000
14  UA = {"User-Agent": "policygraph/0.1 (+httpx)"}  # insurance.ca.gov rejects the default httpx agent
```

- **1–8** Standard library (`json`, `os`, dataclasses), the HTTP client, and the project's paths and helpers.
- **10** The local manifest: for every URL, where its bytes landed and what validators the server gave. Lives in `data/raw/`, which is not committed.
- **11** The committed list of URL → hash, so a reviewer can see when an upstream file changed.
- **12** Maps a source `type` (from `sources.yaml`) to the file extension to save under.
- **13** ArcGIS feature services return at most a few thousand features per request; this is the page size.
- **14** CDI's web server rejects requests without a browser-like User-Agent header.

```python
17  @dataclass(frozen=True)
18  class Fetched:
19      source: str
20      url: str
21      path: str
22      sha: str
23      etag: str | None = None
24      last_modified: str | None = None  # HTTP Last-Modified, or the ArcGIS layer's dataLastEditDate
```

One record per downloaded file: which source, which URL, where it is, its hash, and the two "validators" the server may have sent. An ETag is an opaque version token; Last-Modified is a date. Either lets us ask "has this changed?" without downloading.

```python
27  def conditional(prior: Fetched | None) -> dict[str, str]:
28      if prior is None:
29          return {}
30      return {k: v for k, v in (("If-None-Match", prior.etag), ("If-Modified-Since", prior.last_modified)) if v}
```

Builds the request headers for a conditional GET from a previous fetch: `If-None-Match` carries the ETag, `If-Modified-Since` the date; only the ones we have are included. With no prior fetch there is nothing to send.

```python
33  def download(url: str, prior: Fetched | None) -> tuple[bytes, str | None, str | None] | None:
34      """None when the server answers 304 to the prior validators, i.e. the bytes on disk are still current."""
35      with httpx.Client(timeout=300, follow_redirects=True, headers=UA | conditional(prior)) as c:
36          r = c.get(url)
37          if r.status_code == 304:
38              return None
39          r.raise_for_status()
40          return r.content, r.headers.get("etag"), r.headers.get("last-modified")
```

- **35** Open an HTTP client with a five-minute timeout, following redirects, sending our User-Agent merged (`|`) with the conditional headers.
- **36–38** Make the request. Status 304 means "not modified": return `None` and keep what is on disk.
- **39** Any other error status (404, 500…) raises. The project's rule is to fail loudly.
- **40** Otherwise return the bytes plus the server's validators for next time.

```python
43  def download_arcgis(layer: str, prior: Fetched | None) -> tuple[bytes, str | None, str | None] | None:
44      feats: list[dict] = []
45      with httpx.Client(timeout=300, headers=UA) as c:
46          edited = str(c.get(layer, params={"f": "json"}).raise_for_status().json()["editingInfo"]["dataLastEditDate"])
47          if prior is not None and prior.last_modified == edited:
48              return None
49          while True:
50              params = {"where": "1=1", "outFields": "*", "outSR": 3310, "resultOffset": len(feats), "resultRecordCount": PAGE}
51              r = c.get(f"{layer}/query", params=params | {"f": "geojson"})
52              r.raise_for_status()
53              page = r.json()["features"]
54              feats += page
55              if len(page) < PAGE:
56                  return json.dumps({"type": "FeatureCollection", "features": feats}).encode(), None, edited
```

CAL FIRE's hazard zones come from an ArcGIS "feature service", which is queried, not downloaded.

- **46** First ask the layer for its metadata; `editingInfo.dataLastEditDate` is when its data last changed. That timestamp plays the role of Last-Modified.
- **47–48** If it matches what we recorded last time, nothing changed.
- **49–56** Otherwise page through every feature: `where=1=1` means all rows, `outSR=3310` asks for California Albers coordinates, `resultOffset` moves through the pages. When a page comes back short, we have everything; wrap the features as one GeoJSON `FeatureCollection` and return the bytes with the edit date as the validator.

```python
59  def expand(url: str) -> str:
60      out = os.path.expandvars(url)
61      if "${" in out:
62          raise ValueError(f"unset env var in {url}")
63      return out
```

The ACS URL contains `${CENSUS_API_KEY}`. `expandvars` substitutes environment variables; if any `${` survives, the variable was unset and we stop with a clear error rather than sending a broken request.

```python
66  def fetch_one(source: str, url: str, kind: str, prior: Fetched | None, force: bool) -> tuple[Fetched, str]:
67      if prior is not None and not os.path.exists(prior.path):
68          prior = None
69      if prior is not None and not force and not (prior.etag or prior.last_modified):
70          return prior, "cached"  # no validator to ask the server about; FORCE=1 re-downloads
71      got = (
72          download_arcgis(url, None if force else prior)
73          if kind == "arcgis_geojson"
74          else download(expand(url), None if force else prior)
75      )
76      if got is None:
77          return prior, "unchanged"
78      body, etag, last_modified = got
79      sha = sha256(body)
80      path = RAW / source / f"{sha}.{EXT[kind]}"
81      if not path.exists():
82          path.parent.mkdir(parents=True, exist_ok=True)
83          path.write_bytes(body)
84      status = "new" if prior is None else "ok" if prior.sha == sha else "changed"
85      return Fetched(source, url, str(path), sha, etag, last_modified), status
```

The decision tree for one URL:

- **67–68** If the manifest mentions a file that no longer exists on disk, forget the prior record.
- **69–70** If we have the file but the server gave no validator last time (the Census API and CDI's HTML pages do not), keep the file and report `cached`. `FORCE=1` overrides this.
- **71–75** Otherwise download conditionally (`None if force else prior` disables the conditional headers under force). ArcGIS layers take the paging path.
- **76–77** A `None` means 304: report `unchanged`.
- **78–83** New bytes: hash them and save them under `data/raw/<source>/<hash>.<ext>`. Because the name is the hash, the same bytes never get written twice and a changed file never overwrites an old one.
- **84–85** Report `new`, `ok` (same hash as before) or `changed`.

```python
88  def run(force: bool = False) -> None:
89      cfg = load_yaml(CONFIG / "sources.yaml")["sources"]
90      prior = {e["url"]: Fetched(**e) for entries in (load_yaml(MANIFEST) if MANIFEST.exists() else {}).values() for e in entries}
91      pinned = {h["url"]: h["sha"] for h in load_yaml(HASHES)} if HASHES.exists() else {}
92      manifest: dict[str, list[dict]] = {}
93      for name, spec in cfg.items():
94          urls = spec.get("urls") or ([spec["url"]] if spec.get("url") else [])
95          if not urls:
96              print(f"skip {name}: url not set")
97              continue
98          manifest[name] = []
99          for u in urls:
100             fetched, status = fetch_one(name, u, spec["type"], prior.get(u), force)
101             manifest[name].append(asdict(fetched))
102             if pinned.get(u, fetched.sha) != fetched.sha:
103                 status = "changed"  # differs from the committed hash: review before the next normalize
104             print(f"{status:9} {name} {fetched.sha[:12]}")
105     RAW.mkdir(parents=True, exist_ok=True)
106     dump_yaml(MANIFEST, manifest)
107     dump_yaml(HASHES, [{"url": e["url"], "sha": e["sha"]} for entries in manifest.values() for e in entries])
```

- **89** Read the source registry.
- **90** Load the previous manifest into a dictionary keyed by URL (empty on first run).
- **91** Load the committed hashes.
- **93–104** For each source and each of its URLs: fetch, record, and print one status line. If the hash differs from the committed one, the line says `changed` even when the local file was already current, so a reviewer notices upstream drift.
- **105–107** Write the local manifest and the committed hash list.

### 3.2 `policygraph/normalize/__init__.py` — running the normalizers

```python
 1  from policygraph import CONFIG, NORMALIZED
 2  from policygraph.fetch import MANIFEST
 3  from policygraph.normalize import acs, cdi_fair_plan, cdi_nonrenewal, documents, fhsz, zcta
 4  from policygraph.util import load_yaml
 5
 6  NORMALIZERS = {m.__name__.rsplit(".", 1)[-1]: m for m in (zcta, fhsz, acs, cdi_nonrenewal, cdi_fair_plan, documents)}
 7
 9  def run() -> None:
10      NORMALIZED.mkdir(parents=True, exist_ok=True)
11      cfg = load_yaml(CONFIG / "sources.yaml")["sources"]
12      manifest = load_yaml(MANIFEST)
13      (NORMALIZED / "documents.parquet").unlink(missing_ok=True)  # document normalizers append, one source at a time
14      for norm in NORMALIZERS.values():  # order matters: zcta before fhsz
15          for name, spec in cfg.items():
16              if spec["normalizer"] == norm.__name__.rsplit(".", 1)[-1] and name in manifest:
17                  norm.run(spec, manifest[name])
```

- **6** A dictionary from normalizer name (the module's last dotted component, e.g. `"zcta"`) to module, in the order they must run. ZCTA geometry must exist before the hazard overlay uses it.
- **13** The documents table is built by appending one source at a time (bulletins, then press releases), so it is deleted first to avoid stale rows from earlier runs.
- **14–17** For each normalizer, find every source whose `normalizer:` field names it and which was actually fetched, and call its `run(spec, files)`. Every normalizer has the same signature: the source's spec from `sources.yaml` and its list of fetched-file records.

### 3.3 `policygraph/normalize/zcta.py` — ZIP boundaries

```python
 5  CA_ZIPS = ("90000", "96200")  # the cartographic file is national
 8  def run(spec: dict, files: list[dict]) -> None:
 9      g = gpd.read_file(f"zip://{files[0]['path']}").rename(columns={"ZCTA5CE20": "zip"})
10      g[g.zip.between(*CA_ZIPS)][["zip", "geometry"]].to_crs(3310).to_parquet(NORMALIZED / "zcta.parquet")
```

- **9** GeoPandas reads a shapefile straight out of the zip archive. The Census column `ZCTA5CE20` is renamed `zip`.
- **10** Keep only California ZIPs (90000–96199), only the two columns needed, reproject to California Albers (metres, area-true), and write parquet.

### 3.4 `policygraph/normalize/fhsz.py` — hazard share per ZIP

```python
 6  HAZ = {"Moderate": "moderate", "High": "high", "Very High": "very_high"}  # LRA also carries NonWildland, dropped
 7  HAZ_COL = "FHSZ_Description"
10  def overlap(zcta: gpd.GeoDataFrame, fhsz: gpd.GeoDataFrame) -> pd.DataFrame:
11      fhsz = fhsz.to_crs(zcta.crs).assign(haz=lambda d: d[HAZ_COL].map(HAZ)).dropna(subset=["haz"])[["haz", "geometry"]]
12      inter = gpd.overlay(zcta, fhsz, how="intersection", keep_geom_type=True)
13      inter["area"] = inter.area
14      share = inter.groupby(["zip", "haz"])["area"].sum().unstack(fill_value=0).reindex(zcta.zip, fill_value=0)
15      return share.div(zcta.set_index("zip").area, axis=0).reindex(columns=HAZ.values(), fill_value=0).reset_index()
```

`overlap` is a pure function (no file I/O), which is why it has a unit test.

- **11** Put the hazard polygons in the same CRS as the ZIPs, map CAL FIRE's labels to short names, drop classes we do not track (`NonWildland`), keep only the class and the shape.
- **12** `overlay(..., "intersection")` cuts every ZIP polygon by every hazard polygon, producing one piece per (ZIP, class) overlap.
- **13** Area of each piece in square metres.
- **14** Sum area by ZIP and class, pivot classes into columns, and make sure every ZIP appears even with zero hazard.
- **15** Divide by each ZIP's total area to get shares in 0–1, make sure all three class columns exist, and turn the index back into a `zip` column.

```python
18  def run(spec: dict, files: list[dict]) -> None:
19      zcta = gpd.read_parquet(NORMALIZED / "zcta.parquet")
20      # ArcGIS GeoJSON omits the crs member; fetch requested outSR=3310
21      fhsz = gpd.GeoDataFrame(pd.concat(gpd.read_file(f["path"]).set_crs(3310, allow_override=True) for f in files))
22      overlap(zcta, fhsz).to_parquet(NORMALIZED / "hazard_share.parquet", index=False)
```

Reads the two fetched layers (state and local responsibility areas), stamps them with the CRS the fetch requested (GeoJSON from ArcGIS does not say), concatenates, overlays, writes.

### 3.5 `policygraph/normalize/acs.py` — Census medians

```python
 5  VARS = {
 6      "B25077_001E": "median_home_value",
 7      "B25035_001E": "median_year_built",
 8      "B19013_001E": "median_income",
 9  }
12  def parse(raw: pd.DataFrame) -> pd.DataFrame:
13      df = pd.DataFrame(raw.iloc[1:].values, columns=raw.iloc[0]).rename(columns=VARS | {"zip code tabulation area": "zip"})
14      vals = df[list(VARS.values())].astype(float)
15      return df[["zip"]].assign(**vals.mask(vals < 0))  # Census encodes suppressed cells as -666666666
18  def run(spec: dict, files: list[dict]) -> None:
19      parse(pd.read_json(files[0]["path"])).to_parquet(NORMALIZED / "acs.parquet", index=False)
```

- **5–9** The three ACS variable codes and their readable names.
- **13** The Census API returns a JSON array whose first row is the header. Rebuild a frame using row 0 as column names and rename.
- **14–15** Convert to numbers; the Census marks suppressed values with a large negative sentinel, which `mask(vals < 0)` turns into null.

### 3.6 `policygraph/normalize/cdi_nonrenewal.py` — the core counts

```python
 7  COMMON = {"County": "county", "ZIP Code": "zip", "Year": "year", "New": "new", "Renewed": "renewed"}
 8  SPLIT = {"Insurer-Initiated Nonrenewed": "nonrenewed_insurer", "Insured-Initiated Nonrenewed": "nonrenewed_insured"}
 9  TOTAL = {"Non-Renewed": "nonrenewed"}  # the 2020-2023 release dropped the insurer/insured split
10  COUNTS = ["new", "renewed", "nonrenewed", "nonrenewed_insurer", "nonrenewed_insured"]
11  RELEASE_RE = re.compile(r"(\d{4}-\d{4})\.xlsx$")
```

CDI published two workbooks with different columns. The 2015–2021 release splits non-renewals by who initiated them (the insurer refusing versus the customer leaving); the 2020–2023 release gives only the total. `RELEASE_RE` pulls `2015-2021` or `2020-2023` from the file name.

```python
14  def parse(df: pd.DataFrame, release: str) -> pd.DataFrame:
15      df = df.rename(columns=COMMON | SPLIT | TOTAL)
16      if missing := set(COMMON.values()) - set(df.columns):
17          raise ValueError(f"cdi_nonrenewal missing columns: {missing}")
18      if "nonrenewed" not in df.columns:
19          df["nonrenewed"] = df.nonrenewed_insurer.astype(int) + df.nonrenewed_insured.astype(int)
20      out = df.reindex(columns=["county", "zip", "year", *COUNTS])
21      out[COUNTS] = out[COUNTS].apply(pd.to_numeric).astype("Int64")
22      county = out.county.str.strip()
23      return out.assign(
24          release=release,
25          county=county.mask(county == ""),
26          zip=out.zip.str.zfill(5),
27          year=out.year.astype(int),
28          policies=out.new + out.renewed + out.nonrenewed,
29      )
```

- **15** Rename whichever columns are present to the short names.
- **16–17** If any required column is absent, stop. This is what "schema drift fails loudly" looks like.
- **18–19** For the split release, total non-renewals is the sum of the two parts.
- **20–21** Select the columns in a fixed order (missing ones become null) and convert counts to nullable integers.
- **22–29** Add the release tag, blank county names become null (PO-box ZIPs have no county in the sheet), ZIPs are padded to five digits (the sheet drops leading zeros in some rows), year becomes int, and `policies` is the denominator used for every rate: new + renewed + non-renewed.

```python
32  def run(spec: dict, files: list[dict]) -> None:
33      frames = [parse(pd.read_excel(f["path"], dtype=str), RELEASE_RE.search(f["url"]).group(1)) for f in files]
34      pd.concat(frames, ignore_index=True).to_parquet(NORMALIZED / "cdi_nonrenewal.parquet", index=False)
```

Read each workbook as text (so ZIPs keep their zeros), parse, stack, write. The two releases stay distinguishable by `release`.

### 3.7 `policygraph/normalize/cdi_fair_plan.py` — the FAIR Plan PDF

```python
 8  ROW_RE = re.compile(r"^\d{5}\b")
 9  FY_RE = re.compile(r"9/30/(\d{4})")
12  def layout(text: str) -> tuple[list[int], int, list[int]]:
13      """Fiscal years from the footer; a row is zip, (growth, count) per year except the oldest, then the oldest count."""
14      years = list(dict.fromkeys(int(y) for y in FY_RE.findall(text)))
15      if not years:
16          raise ValueError("cdi_fair_plan: no fiscal-year footer found")
17      n = len(years)
18      return years, 2 * n, [*range(2, 2 * n, 2), 2 * n - 1]
```

The PDF is a table whose text extraction gives lines like `94549 91% 1,773 265% 927 76% 254 26% 144 114`: the ZIP, then for each fiscal year except the oldest a growth percentage and a count, then the oldest count alone. The years themselves are printed in a footer as `9/30/2025 9/30/2024 …`.

- **14** Collect the fiscal years in order, removing duplicates (the footer repeats on every page).
- **17–18** With `n` years a row has `2n` tokens; the counts sit at token positions 2, 4, …, 2n−2 and the last position. Deriving this from the footer is what lets a future six-column release parse without a code change.

```python
21  def parse(text: str) -> pd.DataFrame:
22      years, tokens, count_at = layout(text)
23      rows = []
24      for line in filter(ROW_RE.match, text.splitlines()):
25          tok = line.split()
26          if len(tok) != tokens:
27              raise ValueError(f"cdi_fair_plan: expected {tokens} tokens for {len(years)} fiscal years, got {line!r}")
28          counts = [tok[i] for i in count_at]
29          rows += [{"zip": tok[0], "year": y, "fair_policies": c} for y, c in zip(years, counts, strict=True) if c != "-"]
30      df = pd.DataFrame(rows)
31      return df.assign(fair_policies=df.fair_policies.str.replace(",", "").astype(int))
```

- **24** Only lines that start with five digits are data rows.
- **26–27** A row with the wrong token count means the layout changed; stop rather than mis-assign numbers.
- **28–29** Pick the counts, pair them with years, skip `-` (no policies that year).
- **31** Strip thousands separators and convert to integers.

```python
34  def run(spec: dict, files: list[dict]) -> None:
35      text = "\n".join(p.extract_text() for p in PdfReader(files[0]["path"]).pages)
36      parse(text).to_parquet(NORMALIZED / "cdi_fair_plan.parquet", index=False)
```

pypdf extracts the text of every page (the `cryptography` dependency lets it open the encrypted file); the result goes through `parse`.

### 3.8 `policygraph/normalize/html_text.py` — press-release HTML to text

```python
 1  from html.parser import HTMLParser
 3  BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "ul", "ol", "tr", "hr"}
 4  SKIP = {"script", "style"}
 7  class _Text(HTMLParser):
 8      def __init__(self) -> None:
 9          super().__init__()
10          self.parts: list[str] = []
11          self.skip = 0
13      def handle_starttag(self, tag: str, attrs: list) -> None:
14          if tag in SKIP:
15              self.skip += 1
16          if tag in BLOCK:
17              self.parts.append("\n")
19      def handle_endtag(self, tag: str) -> None:
20          if tag in SKIP:
21              self.skip -= 1
22          if tag in BLOCK:
23              self.parts.append("\n")
25      def handle_data(self, data: str) -> None:
26          if not self.skip:
27              self.parts.append(data)
```

A tiny HTML-to-text converter built on Python's standard parser, so no new dependency.

- **3–4** Tags that start a new line, and tags whose content (JavaScript, CSS) must be dropped.
- **7–11** The parser keeps a list of text pieces and a counter of how deep we are inside skipped tags.
- **13–23** Entering or leaving a block tag inserts a line break; entering or leaving a skipped tag adjusts the counter.
- **25–27** Text is kept unless we are inside a skipped tag.

```python
30  def to_text(html: str, start: str = "<H1>", end: str = 'class="content_right_column') -> str:
31      """CDI pages wrap the release in a left column between the headline and the sidebar; fail if either marker is missing."""
32      i, j = html.find(start), html.find(end)
33      if i < 0 or j < i:
34          raise ValueError(f"html_text: markers {start!r}..{end!r} not found")
35      p = _Text()
36      p.feed(html[i:j])
37      lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
38      return "\n".join(line for line in lines if line)
```

- **32–34** CDI's page template puts the headline in `<H1>` and the sidebar in a `content_right_column` div. Take the text between them; if the template ever changes, stop loudly.
- **36–38** Feed that slice to the parser, join the pieces, collapse runs of whitespace within each line, and drop empty lines.

### 3.9 `policygraph/normalize/documents.py` — the documents table

```python
12  DATE_RE = re.compile(r"(?:(?:DATE|For Release):\s*|^)([A-Z][a-z]+ \d{1,2}, \d{4})(?:\s*[-–—]|\s*$)", re.M)
15  def pdf_text(path: str) -> str:
16      return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
19  def text_of(path: str, kind: str) -> str:
20      if kind == "pdf":
21          return pdf_text(path)
22      if kind == "html":
23          return to_text(Path(path).read_text(errors="replace"))
24      raise ValueError(f"documents: unsupported source type {kind!r}")
27  def published_at(text: str) -> date | None:
28      m = DATE_RE.search(text)
29      return pd.to_datetime(m.group(1)).date() if m else None
```

- **12** The publication date appears as `DATE: November 6, 2020` in bulletins, `For Release: May 13, 2025` in press releases, or as a line beginning `December 20, 2025 -` in alerts. The pattern captures the `Month day, year` part in any of those positions.
- **15–24** Get the text of a PDF or an HTML file; any other type is an error.
- **27–29** Find the first date match and convert it to a `date`; `None` if there is none.

```python
32  def run(spec: dict, files: list[dict]) -> None:
33      """doc_id hashes the extracted text: CDI's HTML carries per-request tokens, so raw bytes never repeat."""
34      texts = [text_of(f["path"], spec["type"]) for f in files]
35      df = pd.DataFrame(
36          [
37              {
38                  "doc_id": sha256(t.encode()),
39                  "source": spec["doc_source"],
40                  "url": f["url"],
41                  "published_at": published_at(t),
42                  "text": t,
43              }
44              for f, t in zip(files, texts, strict=True)
45          ]
46      )
47      out = NORMALIZED / "documents.parquet"
48      if out.exists():
49          df = pd.concat([pd.read_parquet(out), df]).drop_duplicates("doc_id")
50      df.to_parquet(out, index=False)
```

- **38** The document id is the hash of the *text*, not the downloaded bytes. CDI's HTML embeds a fresh session token on every download, so hashing bytes would give a new id every time; the extracted text is stable.
- **39** `doc_source` (`cdi_bulletin` or `cdi_press`) comes from `sources.yaml`.
- **47–50** Append to the existing table (the bulletins normalizer runs, then the press one), removing duplicate ids.

### 3.10 `policygraph/extract.py` — submitting documents to the service

```python
10  SERVICE = os.environ.get("EXTRACTION_SERVICE_URL", "http://localhost:8000")
13  def run(schema_v: str = "1.0", force: bool = False) -> None:
14      """force re-runs the model even for documents whose extraction id already has an artifact."""
15      docs = pd.read_parquet(NORMALIZED / "documents.parquet")
16      with httpx.Client(base_url=SERVICE, timeout=60) as c:
17          run_id = c.post("/v1/runs", json={"schema_v": schema_v}).json()["run_id"]
18          for d in docs.itertuples():
19              body = {"run_id": run_id, "doc_id": d.doc_id, "source": d.source, "text": d.text, "force": force}
20              c.post("/v1/jobs", json=body).raise_for_status()
21          while (m := c.get(f"/v1/manifests/{run_id}").json())["status"] != "complete":
22              time.sleep(2)
23      dump_yaml(CONFIG / "extraction_manifest.yaml", m)
24      if m["failed"] or m["errors"]:
25          raise RuntimeError(f"extraction run {run_id}: failed={m['failed']} errors={m['errors']}")
```

The pipeline never calls a model. It talks to the service over HTTP.

- **17** Create a run; the service replies with an id.
- **18–20** Submit one job per document, carrying the text and the `force` flag.
- **21–22** Poll the run's manifest every two seconds until every job is done.
- **23** Save the manifest. This file, committed to git, is what pins exactly which extraction artifacts the graph loads.
- **24–25** If any document failed validation or errored, the stage fails.

### 3.11 `policygraph/resolve.py` — mentions to entity ids

The model emits *mentions* ("Eaton Fire 2025", "State Farm", "94563"). Resolution turns each into a canonical entity id, cheapest method first.

```python
13  SERVICE = os.environ.get("EXTRACTION_SERVICE_URL", "http://localhost:8000")
14  PINNED = CONFIG / "resolutions.yaml"  # every answer the service gave, committed so `make resolve` replays offline
15  ZIP_RE = re.compile(r"^\d{5}$")
16  BILL_RE = re.compile(r"^(SB|AB)\s?(\d+)$", re.I)
17  FIRE_RE = re.compile(r"^(.+?) Fire (\d{4})$", re.I)
18  MORATORIUM_RE = re.compile(r"^(.+?) Fire moratorium (\d{4}-\d{2}-\d{2})$", re.I)
19  Ask = Callable[[list[dict], list[dict]], list[dict]]
22  @dataclass(frozen=True)
23  class Resolved:
24      mention: str
25      type: str
26      entity_id: str
27      method: str
28      confidence: float
31  def slug(s: str) -> str:
32      return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
```

- **15–18** The four canonical patterns: five digits; `SB 824` / `AB2996`; `<Name> Fire <year>`; `<Name> Fire moratorium <date>`. The extraction prompt tells the model to write mentions in exactly these shapes.
- **19** The type of "a function that asks the service": takes mentions and candidates, returns answers.
- **22–28** One resolution record.
- **31–32** `slug("SCU Lightning Complex")` → `scu-lightning-complex`: lowercase, non-alphanumerics to hyphens.

```python
35  def canonical(mention: str, etype: str) -> Resolved | None:
36      """The returned mention is the original string: the graph looks edges up by the artifact's exact mention."""
37      m = mention.strip()
38      if etype == "ZIP" and ZIP_RE.match(m):
39          return Resolved(mention, etype, f"zip:{m}", "canonical", 1.0)
40      if etype == "Regulation" and (b := BILL_RE.match(m)):
41          return Resolved(mention, etype, f"bill:ca:{b.group(1).upper()}{b.group(2)}", "canonical", 1.0)
42      if etype == "Fire" and (f := FIRE_RE.match(m)):
43          return Resolved(mention, etype, f"fire:{slug(f.group(1))}:{f.group(2)}", "canonical", 1.0)
44      if etype == "Moratorium" and (mo := MORATORIUM_RE.match(m)):
45          return Resolved(mention, etype, f"moratorium:{mo.group(2)}:{slug(mo.group(1))}", "canonical", 1.0)
46      return None
```

Step 1. Each branch checks the mention's declared type *and* its shape, and mints the id. Type checking prevents the classic failure of an insurer resolving to an official. The confidence is 1.0 because these are rules, not guesses. Note `mention` (original) is returned, not `m` (stripped): the graph stage looks edges up by the exact string the model used.

```python
49  def alias_table(entities: list[dict]) -> dict[tuple[str, str], str]:
50      return {(a.lower(), e["type"]): e["id"] for e in entities for a in (e["name"], *e["aliases"])}
53  def alias(mention: str, etype: str, aliases: dict[tuple[str, str], str]) -> Resolved | None:
54      eid = aliases.get((mention.strip().lower(), etype))
55      return Resolved(mention, etype, eid, "alias", 0.98) if eid else None
58  def pending(mention: str, etype: str) -> Resolved:
59      return Resolved(mention, etype, f"pending:{etype.lower()}:{slug(mention)}", "unresolved", 0.0)
```

Step 2. `alias_table` flattens `config/entities.yaml` into `(lowercase name or alias, type) → id`. `alias` looks a mention up exactly. `pending` mints a placeholder id for anything nobody could resolve, so the graph still loads and the gap is visible.

```python
62  def from_pin(pin: dict) -> Resolved:
63      if pin["entity_id"] is None:
64          return pending(pin["mention"], pin["type"])
65      return Resolved(pin["mention"], pin["type"], pin["entity_id"], pin["method"], pin["confidence"])
68  def ask_service(mentions: list[dict], candidates: list[dict]) -> list[dict]:
69      with httpx.Client(base_url=SERVICE, timeout=600) as c:
70          r = c.post("/v1/resolve", json={"mentions": mentions, "candidates": candidates})
71          r.raise_for_status()
72          return r.json()
```

- **62–65** Turn a pinned service answer (from `config/resolutions.yaml`) into a `Resolved`; an answer of "nobody" becomes pending.
- **68–72** Steps 3–4 live in the service; this posts the residual mentions and the candidate entities and returns its answers.

```python
75  def resolve_all(mentions: pd.DataFrame, entities: list[dict], pins: dict[tuple[str, str], dict], ask: Ask | None) -> pd.DataFrame:
76      """Cheapest first: canonical key, alias table, pinned service answer, then the service (kNN + judge), else pending."""
77      aliases, out, residual = alias_table(entities), {}, []
78      for m in mentions.drop_duplicates(["mention", "type"]).itertuples():
79          key = (m.mention, m.type)
80          if r := canonical(*key) or alias(*key, aliases):
81              out[key] = r
82          elif key in pins:
83              out[key] = from_pin(pins[key])
84          else:
85              residual.append({"mention": m.mention, "type": m.type, "context": m.context})
86      if residual and ask is not None:
87          cands = [{"entity_id": e["id"], "type": e["type"], "name": e["name"], "description": e["description"]} for e in entities]
88          for pin in ask(residual, cands):
89              pins[(pin["mention"], pin["type"])] = pin
90              out[(pin["mention"], pin["type"])] = from_pin(pin)
91      for r in residual:
92          out.setdefault((r["mention"], r["type"]), pending(r["mention"], r["type"]))
93      return pd.DataFrame([asdict(r) for r in out.values()])
```

The whole ladder in one function.

- **78–85** For each distinct (mention, type): try the rules, then the alias table, then a previously pinned answer; anything left is "residual" and carries its context (a quoted span) for the judge.
- **86–90** If there is a residual and we are online, ask the service once for all of them; record every answer in `pins` (so it gets committed) and in the output.
- **91–92** Anything still unanswered (offline, or the service said "nobody") becomes pending.
- **93** Return a table.

```python
96  def mentions_in(artifact: dict) -> pd.DataFrame:
97      ctx = {}
98      for e in artifact["edges"]:
99          ctx.setdefault(e["src_mention"], e["span"])
100         ctx.setdefault(e["dst_mention"], e["span"])
101     return pd.DataFrame(
102         [{"mention": e["mention"], "type": e["type"], "context": ctx.get(e["mention"], "")} for e in artifact["entities"]]
103     )
```

From one extraction artifact, list its entities with, as context, the first quoted span of any edge that touches the mention. The judge reads that context.

```python
106 def run(force: bool = False) -> None:
107     manifest = load_yaml(CONFIG / "extraction_manifest.yaml")
108     entities = load_yaml(CONFIG / "entities.yaml")["entities"]
109     pins = {} if force else {(p["mention"], p["type"]): p for p in (load_yaml(PINNED) if PINNED.exists() else [])}
110     arts = [json.loads((EXTRACTIONS / f"{x}.json").read_text()) for x in manifest["extractions"]]
111     mentions = pd.concat([mentions_in(a) for a in arts], ignore_index=True)
112     ask = ask_service if os.environ.get("EXTRACTION_SERVICE_URL") else None
113     df = resolve_all(mentions, entities, pins, ask)
114     seen = set(zip(mentions.mention, mentions.type, strict=True))
115     dump_yaml(
116         PINNED, sorted((p for p in pins.values() if (p["mention"], p["type"]) in seen), key=lambda p: (p["type"], p["mention"]))
117     )
118     df.to_parquet(EXTRACTIONS.parent / "normalized" / "resolved.parquet", index=False)
119     print(df.method.value_counts().to_dict())
```

- **107–111** Load the pinned manifest, the entity registry, the previous pins (dropped under `--force`), and every mention in every pinned artifact.
- **112** Only ask the service if its URL is configured; otherwise replay offline.
- **114–117** Write the pins back, keeping only mentions that still exist, sorted for a stable diff.
- **118–119** Save the resolution table and print a count per method.

### 3.12 `policygraph/names.py` — readable names for rule-minted ids

```python
 3  FIRE_RE = re.compile(r"^fire:([a-z0-9-]+):(\d{4})$")
 4  MOR_RE = re.compile(r"^moratorium:(\d{4}-\d{2}-\d{2}):([a-z0-9-]+)$")
 5  FIXED = {
 6      "market:ca:voluntary": "California voluntary market (all admitted insurers)",
 7      "fhsz:very_high": "FHSZ Very High",
 8      "fhsz:high": "FHSZ High",
 9      "fhsz:moderate": "FHSZ Moderate",
10  }
13  def title(slug: str) -> str:
14      return " ".join(w.upper() if w in {"scu", "lnu", "czu", "shf", "sqf"} else w.capitalize() for w in slug.split("-"))
17  def humanize(entity_id: str, places: dict[str, str]) -> str:
18      """Readable name for ids that are minted by rule and so have no entry in config/entities.yaml."""
19      if entity_id in FIXED:
20          return FIXED[entity_id]
21      if entity_id.startswith("zip:"):
22          z = entity_id[4:]
23          return f"{places[z]} {z}" if z in places else z
24      if entity_id.startswith("bill:ca:"):
25          return re.sub(r"^([A-Z]+)(\d+)$", r"\1 \2", entity_id[8:])
26      if m := FIRE_RE.match(entity_id):
27          return f"{title(m.group(1))} Fire {m.group(2)}"
28      if m := MOR_RE.match(entity_id):
29          return f"{title(m.group(2))} Fire moratorium {m.group(1)}"
30      if entity_id.startswith("pending:"):
31          return entity_id.split(":", 2)[2].replace("-", " ") + " (unresolved)"
32      return entity_id
```

Entities made by rule (ZIPs, fires, moratoria, bills) have no hand-written name, so this derives one: `zip:94549` → `Lafayette 94549` (from `config/places.yaml`), `fire:scu-lightning-complex:2020` → `SCU Lightning Complex Fire 2020` (fire-complex acronyms stay upper-case), `bill:ca:SB824` → `SB 824`. The app's timeline and explorer show these.

### 3.13 `policygraph/graph.py` — building the DuckDB graph

```python
11  COLS = ["src", "rel", "dst", "valid_from", "valid_to", "props", "doc_id", "span", "extractor", "confidence"]
12  MARKET = "market:ca:voluntary"  # CDI publishes ZIP totals only; no insurer identity is in the public data
13  MORATORIUM_RE = re.compile(r"^moratorium:(\d{4}-\d{2}-\d{2}):")
14  ACS = ["median_home_value", "median_year_built", "median_income"]
17  def _year(s: pd.Series) -> pd.Series:
18      return pd.to_datetime(s.astype(str) + "-01-01")
21  def _props(df: pd.DataFrame) -> list[str]:
22      return [json.dumps({k: (None if pd.isna(v) else v) for k, v in r.items()}) for r in df.to_dict("records")]
```

- **11** The edge columns, in the order the schema expects.
- **12** Because CDI's counts name no insurer, every count edge starts at one anonymous "voluntary market" node.
- **17–18** A year becomes the date January 1 of that year (edges need dates).
- **21–22** Turn each row of a frame into a JSON string, with nulls as JSON `null`.

```python
25  def deterministic_edges(nr: pd.DataFrame, haz: pd.DataFrame, fair: pd.DataFrame) -> pd.DataFrame:
26      haz_long = haz.melt("zip", var_name="haz", value_name="pct")
27      nr_props = nr[["nonrenewed", "nonrenewed_insurer", "nonrenewed_insured", "new", "renewed", "policies", "release"]]
28      frames = [
29          pd.DataFrame(
30              {
31                  "src": MARKET,
32                  "rel": "NONRENEWED_IN",
33                  "dst": "zip:" + nr.zip,
34                  "valid_from": _year(nr.year),
35                  "props": _props(nr_props.rename(columns={"nonrenewed": "count"})),
36                  "extractor": "deterministic:cdi_nonrenewal:" + nr.release,  # releases overlap 2020-21 and disagree
37              }
38          ),
39          pd.DataFrame(
40              {
41                  "src": "zip:" + haz_long.zip,
42                  "rel": "HAZARD_SHARE",
43                  "dst": "fhsz:" + haz_long.haz,
44                  "props": _props(haz_long[["pct"]]),
45                  "extractor": "deterministic:fhsz_v1",
46              }
47          ),
48          pd.DataFrame(
49              {
50                  "src": "zip:" + fair.zip,
51                  "rel": "HAS_FAIR_PLAN_POLICIES",
52                  "dst": "insurer:fairplan",
53                  "valid_from": _year(fair.year),
54                  "props": _props(fair[["fair_policies"]].rename(columns={"fair_policies": "count"})),
55                  "extractor": "deterministic:cdi_fair_v1",
56              }
57          ),
58      ]
59      return pd.concat(frames, ignore_index=True).assign(confidence=1.0).reindex(columns=COLS)
```

Three edge families from the three tabular sources.

- **26** The hazard table has one column per class; `melt` turns it into (zip, class, share) rows.
- **29–38** One `NONRENEWED_IN` edge per ZIP-year-release. The counts travel in `props`; the extractor tag includes the release so the two disagreeing releases are never confused.
- **39–47** One `HAZARD_SHARE` edge per ZIP and class.
- **48–57** One `HAS_FAIR_PLAN_POLICIES` edge per ZIP and fiscal year.
- **59** Stack them, mark confidence 1.0 (deterministic), and align to the edge columns (absent ones become null).

```python
62  def window(edge: dict, dst: str) -> tuple[str | None, str | None]:
63      """A moratorium runs one year from the declaration date (Ins. Code 675.1(b)(1)); the date is in its canonical id."""
64      if edge["valid_from"] or not (m := MORATORIUM_RE.match(dst)):
65          return edge["valid_from"], edge["valid_to"]
66      start = pd.Timestamp(m.group(1))
67      return str(start.date()), str((start + pd.DateOffset(years=1)).date())
```

If the model gave an edge no dates but its target is a moratorium, the id contains the declaration date, and the law says the moratorium lasts one year: fill both dates from that.

```python
70  def llm_edges(manifest: dict, resolved: dict[str, str]) -> pd.DataFrame:
71      rows = []
72      for xid in manifest["extractions"]:
73          art = json.loads((EXTRACTIONS / f"{xid}.json").read_text())
74          rows += [
75              {
76                  "src": resolved[e["src_mention"]],
77                  "rel": e["rel"],
78                  "dst": resolved[e["dst_mention"]],
79                  "valid_from": window(e, resolved[e["dst_mention"]])[0],
80                  "valid_to": window(e, resolved[e["dst_mention"]])[1],
81                  "props": json.dumps(e["props"]),
82                  "doc_id": art["doc_id"],
83                  "span": e["span"],
84                  "extractor": f"llm:{art['model_id']}" + ("|zip_block" if e["props"].get("expanded_from") == "zip_block" else ""),
85                  "confidence": e["confidence"],
86              }
87              for e in art["edges"]
88          ]
89      return pd.DataFrame(rows, columns=COLS)
```

For every pinned artifact, every edge becomes a graph edge: mentions are swapped for resolved ids (`resolved[...]` raises if a mention was never resolved, on purpose), dates are filled by `window`, and provenance is copied through. Edges the service expanded deterministically from ZIP-list blocks get `|zip_block` appended to the extractor tag so they can be told apart from what the model wrote itself.

```python
92  def zip_attrs(nr: pd.DataFrame, acs: pd.DataFrame) -> dict[str, dict]:
93      """County from CDI (blank for PO-box ZIPs) and ACS medians, keyed by ZIP; suppressed ACS cells stay null."""
94      county = nr.dropna(subset=["county"]).drop_duplicates("zip").set_index("zip").county
95      df = acs.set_index("zip")[ACS].join(county, how="outer")
96      return {z: {k: (None if pd.isna(v) else v) for k, v in r.items()} for z, r in df.to_dict("index").items()}
99  def entities_from(edges: pd.DataFrame, attrs: dict[str, dict], names: dict[str, str], places: dict[str, str]) -> pd.DataFrame:
100     ids = pd.Series(pd.unique(pd.concat([edges.src, edges.dst])))
101     return pd.DataFrame(
102         {
103             "entity_id": ids,
104             "type": ids.str.split(":").str[0],
105             "canonical_name": [names.get(i) or humanize(i, places) for i in ids],
106             "attrs": [json.dumps(attrs[i[4:]]) if i.startswith("zip:") and i[4:] in attrs else None for i in ids],
107         }
108     )
```

- **92–96** Per ZIP: its county (from CDI) and its three ACS medians, merged with an outer join so a ZIP present in either source appears.
- **99–108** The entity table is derived from the edges: every id that appears as a source or target. Type is the id's prefix; the name comes from `entities.yaml` if listed, else from `humanize`; ZIPs get their attributes as JSON.

```python
111 def run() -> None:
112     nr, haz, fair, acs, docs = (
113         pd.read_parquet(NORMALIZED / f"{n}.parquet")
114         for n in ("cdi_nonrenewal", "hazard_share", "cdi_fair_plan", "acs", "documents")
115     )
116     resolved = pd.read_parquet(NORMALIZED / "resolved.parquet").set_index("mention").entity_id.to_dict()
117     names = {e["id"]: e["name"] for e in load_yaml(CONFIG / "entities.yaml")["entities"]}
118     edges = pd.concat([deterministic_edges(nr, haz, fair), llm_edges(load_yaml(CONFIG / "extraction_manifest.yaml"), resolved)])
119     key = edges[["src", "rel", "dst", "valid_from", "doc_id", "extractor"]]
120     edges["edge_id"] = [stable_id(*r) for r in key.itertuples(index=False)]
121     ents = entities_from(edges, zip_attrs(nr, acs), names, load_yaml(CONFIG / "places.yaml"))
122     GRAPH_DB.unlink(missing_ok=True)  # the file is derived from the pinned inputs; history lives in those, not here
123     with duckdb.connect(str(GRAPH_DB)) as con:
124         con.execute((CONFIG / "schema.sql").read_text())
125         for table, df in (("documents", docs), ("entities", ents), ("edges", edges)):
126             con.register(f"new_{table}", df)  # a bare DataFrame name would resolve to the table itself
127             con.execute(f"INSERT OR IGNORE INTO {table} BY NAME SELECT * FROM new_{table}")
```

- **112–117** Load the five normalized tables, the resolution map (mention → id), and the hand-written names.
- **118** All edges: deterministic plus model-derived.
- **119–120** Each edge id is a hash of what makes it unique: endpoints, relation, start date, document and extractor. The same fact always gets the same id, so re-running cannot duplicate it.
- **121** Build the entity table.
- **122** Delete the old database file: it is entirely derived from the pinned inputs (the "history" the design promises lives in those inputs, which are append-only), so rebuilding from scratch is the reproducible choice.
- **123–127** Create the tables from `schema.sql`, register each DataFrame under a temporary name (DuckDB can query pandas frames as if they were tables), and insert. `INSERT OR IGNORE` skips any id that already exists.
