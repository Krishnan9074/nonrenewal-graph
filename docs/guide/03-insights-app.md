## Part 4. Insights and the app

Every insight module has one public function, `compute(con) -> DataFrame`, that takes a read-only DuckDB connection and returns a table. `policygraph/insights/__init__.py` runs them all and writes one parquet file per module into `data/insights/`. The app reads those files and nothing else.

### 4.1 `policygraph/insights/__init__.py`

```python
17  MODULES = (
18      hazard_residual,
19      moratorium_deferral,
20      regulatory_alignment,
21      fair_mirror,
22      actor_centrality,
23      evidence,
24      events,
25      trend,
26      explorer,
27  )
30  def run() -> None:
31      INSIGHTS.mkdir(parents=True, exist_ok=True)
32      with duckdb.connect(str(GRAPH_DB), read_only=True) as con:
33          for m in MODULES:
34              m.compute(con).to_parquet(INSIGHTS / f"{m.__name__.rsplit('.', 1)[-1]}.parquet", index=False)
35          geometry.write(con, INSIGHTS / "cc_zips.geojson")
```

Five findings modules, then four "serving" tables (evidence, events, trend, explorer) and the county geometry file. Each parquet is named after its module.

### 4.2 `hazard_residual.py` — finding 1

```python
 7  FITS = (
 8      (2021, "2015-2021", "nonrenewed_insurer"),
 9      (2023, "2020-2023", "count"),
10  )
12  SPECS = {"hazard": ["very_high", "high"], "hazard+acs": ["very_high", "high", "log_home_value", "log_income"]}
```

Two fits: the last year with the insurer/insured split (2021, insurer-initiated counts) and the last year of data at all (2023, total counts). Two specifications each: hazard alone, and hazard plus log home value and log income (the "is it price, not fire?" test).

```python
14  SQL = """
15  WITH nr AS (
16    SELECT dst AS zip, json_extract(props, ?)::INT AS n, json_extract(props,'$.policies')::INT AS p
17    FROM edges WHERE rel='NONRENEWED_IN' AND year(valid_from)=? AND json_extract_string(props,'$.release')=?),
18  haz AS (
19    SELECT src AS zip,
20           max(CASE WHEN dst='fhsz:very_high' THEN json_extract(props,'$.pct')::DOUBLE END) AS very_high,
21           max(CASE WHEN dst='fhsz:high' THEN json_extract(props,'$.pct')::DOUBLE END) AS high
22    FROM edges WHERE rel='HAZARD_SHARE' GROUP BY 1)
23  SELECT substr(nr.zip, 5) AS zip, json_extract_string(e.attrs,'$.county') AS county, sum(n)::DOUBLE/sum(p) AS rate,
24         coalesce(any_value(haz.very_high),0) AS very_high, coalesce(any_value(haz.high),0) AS high, sum(p) AS policies,
25         any_value(json_extract(e.attrs,'$.median_home_value')::DOUBLE) AS home_value,
26         any_value(json_extract(e.attrs,'$.median_income')::DOUBLE) AS income
27  FROM nr LEFT JOIN haz USING (zip) JOIN entities e ON e.entity_id = nr.zip
28  GROUP BY 1,2 HAVING sum(p) > 50 AND sum(n) IS NOT NULL
29  """
```

SQL with three `?` placeholders (the measure's JSON path, the year, the release).

- **15–17** `nr`: for the chosen year and release, each ZIP's non-renewal count `n` (insurer-initiated or total) and policies `p`, pulled out of the edge's JSON props.
- **18–22** `haz`: pivot each ZIP's Very High and High area shares into columns.
- **23–28** Join, strip the `zip:` prefix, compute the rate, default missing hazard to 0, pull county and ACS medians from the entity attributes, and drop tiny ZIPs (≤ 50 policies) whose rates are noise.

```python
32  def fit(con: duckdb.DuckDBPyConnection, year: int, release: str, measure: str) -> pd.DataFrame:
33      base = con.execute(SQL, [f"$.{measure}", year, release]).df()
34      base["log_home_value"], base["log_income"] = np.log(base.home_value), np.log(base.income)
35      out = []
36      for spec, cols in SPECS.items():
37          df = base.dropna(subset=cols).copy()
38          x = sm.add_constant(df[cols])
39          ols = sm.OLS(df.rate, x).fit()
40          df["predicted"] = ols.predict(x)
41          df["residual"] = df.rate - df.predicted
42          coefs = {f"coef_{c}": ols.params[c] for c in cols} | {f"p_{c}": ols.pvalues[c] for c in cols}
43          out.append(df.assign(year=year, release=release, measure=measure, spec=spec, r2=ols.rsquared, n=len(df), **coefs))
44      return pd.concat(out).sort_values(["spec", "residual"], ascending=[True, False])
47  def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
48      return pd.concat([fit(con, *f) for f in FITS], ignore_index=True)
```

- **33–34** Run the query and add log-transformed price columns (log because a doubling should matter the same at any level).
- **36–43** For each spec: drop ZIPs missing a regressor, add the intercept column, fit ordinary least squares, compute each ZIP's predicted rate and residual, and attach the fit's coefficients, p-values, R² and sample size to every row so the app can show them.
- **44** Sort so the biggest positive residuals (most above the line) come first; the row number becomes the ZIP's statewide rank.

### 4.3 `matching.py` — the matched control

```python
 5  def nearest(treated: pd.DataFrame, pool: pd.DataFrame, cols: list[str], k: int = 5) -> list[str]:
 6      """Union of each treated row's k nearest pool rows in standardized feature space; index values are the ids."""
 7      both = pd.concat([treated[cols], pool[cols]])
 8      mu, sd = both.mean(), both.std().replace(0, 1)
 9      t = ((treated[cols] - mu) / sd).to_numpy(dtype=float)
10      p = ((pool[cols] - mu) / sd).to_numpy(dtype=float)
11      d = np.linalg.norm(t[:, None, :] - p[None, :, :], axis=2)
12      picks = np.argsort(d, axis=1)[:, : min(k, len(pool))]
13      return sorted({pool.index[i] for row in picks for i in row})
```

Given treated rows (protected ZIPs) and a pool (unprotected ZIPs) with the same feature columns:

- **7–10** Standardise each feature (subtract the mean, divide by the standard deviation) so hazard share and log policy count are on the same scale; a zero deviation is replaced by 1 to avoid dividing by zero.
- **11** Euclidean distance from every treated row to every pool row (a treated × pool matrix, via numpy broadcasting).
- **12** For each treated row, the indices of its `k` closest pool rows.
- **13** The union of those, as sorted ids.

### 4.4 `moratorium_deferral.py` — finding 3

```python
 9  FITS = (("2015-2021", "nonrenewed_insurer"), ("2020-2023", "count"))
10  MATCH_ON = ["very_high", "log_policies"]
12  PROT = "SELECT DISTINCT src AS zip, dst AS moratorium, valid_from, valid_to FROM edges WHERE rel='PROTECTED_BY'"
13  NR = """
14  SELECT dst AS zip, year(valid_from) AS y, json_extract(props, ?)::INT AS n, json_extract(props,'$.policies')::INT AS p
15  FROM edges WHERE rel='NONRENEWED_IN' AND json_extract_string(props,'$.release')=?
16  """
17  HAZ = """
18  SELECT src AS zip, json_extract(props,'$.pct')::DOUBLE AS very_high FROM edges WHERE rel='HAZARD_SHARE' AND dst='fhsz:very_high'
19  """
22  def moratorium_year(valid_from: pd.Series, valid_to: pd.Series) -> pd.Series:
23      start, end = pd.to_datetime(valid_from), pd.to_datetime(valid_to).fillna(pd.to_datetime(valid_from))
24      return (start + (end - start) / 2).dt.year
```

- **9** Each release is analysed with the measure it publishes.
- **12–19** Three queries: who was protected by which moratorium and when; the per-ZIP-year counts for a release; each ZIP's Very High share.
- **22–24** A moratorium's "year" is the calendar year containing the midpoint of its 12-month window. A declaration on 27 October 2019 runs to 27 October 2020; its midpoint is April 2020, so 2020 is "during", 2019 "before", 2021 "after".

```python
27  def windows(nr: pd.DataFrame, y0: int) -> pd.DataFrame:
28      w = nr[nr.y.between(y0 - 1, y0 + 1)].pivot_table(index="zip", columns="y", values="n", aggfunc="sum")
29      return w.reindex(columns=[y0 - 1, y0, y0 + 1]).set_axis(["before", "during", "after"], axis=1)
32  def features(nr: pd.DataFrame, haz: pd.DataFrame, y: int) -> pd.DataFrame:
33      p = nr[nr.y == y].groupby("zip").p.sum()
34      return pd.DataFrame({"log_policies": np.log1p(p)}).join(haz.set_index("zip")).fillna({"very_high": 0})
37  def summarise(grp: str, label: str, w: pd.DataFrame) -> dict:
38      s = w.sum(min_count=1)
39      return {"grp": grp, "zip": label, "n_zips": len(w), "before": s.before, "during": s.during, "after": s.after}
```

- **27–29** Pivot the counts of the three years around `y0` into `before / during / after` columns, one row per ZIP (a year absent from the release becomes null).
- **32–34** Matching features as of the year before: log(1 + policies) and Very High share.
- **37–39** Sum a group of ZIPs into one row (`min_count=1` keeps the sum null if every value is null).

```python
42  def rows(prot: pd.DataFrame, nr: pd.DataFrame, haz: pd.DataFrame) -> list[dict]:
43      out, everywhere = [], set(prot.zip)
44      for (mor, y0), g in prot.groupby(["moratorium", "y0"]):
45          w = windows(nr, y0)
46          treated = w.index.intersection(set(g.zip))
47          if not len(treated) or w.loc[treated].isna().all().any():
48              continue  # the window is outside this release
49          pool = w.index.difference(everywhere)
50          feats = features(nr, haz, y0 - 1)
51          matched = nearest(feats.reindex(treated).fillna(0), feats.reindex(pool).fillna(0), MATCH_ON)
52          out += [
53              {"grp": "protected", "zip": z[4:], "n_zips": 1, **w.loc[z].to_dict()} | {"moratorium": mor, "y0": y0} for z in treated
54          ]
55          out += [
56              summarise("control_all", "all other CA ZIPs", w.loc[pool]) | {"moratorium": mor, "y0": y0},
57              summarise("control_matched", "matched CA ZIPs", w.loc[matched]) | {"moratorium": mor, "y0": y0},
58          ]
59      return out
```

- **43** `everywhere` is every ZIP protected by *any* moratorium; none of them may serve as a control.
- **44–48** For each moratorium: build the window, find the protected ZIPs that have data, and skip the moratorium if a whole column is missing (the window falls outside this release).
- **49–51** The control pool is every ZIP never protected; the matched control is the nearest neighbours by hazard share and policy count.
- **52–58** Emit one row per protected ZIP and one summary row for each control group.

```python
62  def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
63      prot = con.execute(PROT).df()
64      prot["y0"] = moratorium_year(prot.valid_from, prot.valid_to)
65      haz = con.execute(HAZ).df()
66      frames = []
67      for release, measure in FITS:
68          nr = con.execute(NR, [f"$.{measure}", release]).df()
69          frames.append(pd.DataFrame(rows(prot, nr, haz)).assign(release=release, measure=measure))
70      df = pd.concat(frames, ignore_index=True)
71      before = df["before"].replace(0, np.nan)
72      return df.assign(during_ratio=df["during"] / before, after_ratio=df["after"] / before)
```

Run `rows` for each release and add the two ratios the write-up quotes (a zero "before" is treated as missing rather than dividing by it).

### 4.5 `events.py`, `trend.py`, `regulatory_alignment.py` — finding 4

`events.py` lists every dated thing the documents contained:

```python
 6  SQL = """
 7  SELECT CASE WHEN rel='TRIGGERED' THEN 'fire' WHEN rel='ISSUED' AND dst LIKE 'moratorium:%' THEN 'moratorium'
 8              WHEN rel IN ('ISSUED','AUTHORED') THEN 'regulation' WHEN rel='FILED' THEN 'rate_filing'
 9              ELSE 'rate_decision' END AS kind,
10         rel, e.src, e.dst, coalesce(s.canonical_name, e.src) AS src_name, coalesce(t.canonical_name, e.dst) AS dst_name,
11         e.valid_from AS date, e.valid_to, e.props, e.span, e.confidence, d.url,
12         (SELECT count(*) FROM edges p JOIN entities z ON z.entity_id = p.src
13          WHERE p.rel='PROTECTED_BY' AND p.dst = e.dst AND json_extract_string(z.attrs,'$.county') = ?) AS cc_zips
14  FROM edges e JOIN documents d USING (doc_id)
15  LEFT JOIN entities s ON s.entity_id = e.src LEFT JOIN entities t ON t.entity_id = e.dst
16  WHERE e.rel IN ('TRIGGERED','ISSUED','FILED','DECIDED','AUTHORED') AND e.valid_from IS NOT NULL
17  ORDER BY e.valid_from, kind, e.dst
18  """
```

Each dated document edge becomes an event with a `kind` (fire, moratorium, regulation, rate filing, rate decision), readable names, its span and URL, and — for moratoria — how many Contra Costa ZIPs it protected (the sub-query on lines 12–13).

`trend.py` computes the county and statewide series:

```python
 5  SQL = """
 6  SELECT json_extract_string(props,'$.release') AS release, year(valid_from) AS y,
 7         CASE WHEN json_extract_string(e.attrs,'$.county') = ? THEN ? ELSE 'California' END AS scope,
 8         sum(json_extract(props,'$.count')::INT) AS nonrenewed,
 9         sum(json_extract(props,'$.nonrenewed_insurer')::INT) AS nonrenewed_insurer,
10         sum(json_extract(props,'$.policies')::INT) AS policies
11  FROM edges JOIN entities e ON e.entity_id = dst WHERE rel='NONRENEWED_IN' GROUP BY 1,2,3
12  """
15  FAIR = """
16  SELECT 'fair-plan-fy' AS release, year(valid_from) AS y,
17         CASE WHEN json_extract_string(e.attrs,'$.county') = ? THEN ? ELSE 'California' END AS scope,
18         sum(json_extract(props,'$.count')::INT) AS fair
19  FROM edges JOIN entities e ON e.entity_id = src WHERE rel='HAS_FAIR_PLAN_POLICIES' GROUP BY 1,2,3
20  """
23  def fair_series(con: duckdb.DuckDBPyConnection, county: str) -> pd.DataFrame:
24      """FAIR Plan policies in force at 9/30 of the fiscal year, the only series that reaches the 2024-25 events."""
25      df = con.execute(FAIR, [county, county]).df()
26      ca = df.groupby(["release", "y"]).fair.sum().reset_index().assign(scope="California")
27      return pd.concat([df[df.scope == county], ca], ignore_index=True)
30  def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
31      df = con.execute(SQL, [county, county]).df()
32      ca = (
33          df.groupby(["release", "y"])[["nonrenewed", "nonrenewed_insurer", "policies"]]
34          .sum()
35          .reset_index()
36          .assign(scope="California")
37      )
38      df = pd.concat([df[df.scope == county], ca], ignore_index=True)  # "California" rows above exclude the county
39      rates = {"rate": df.nonrenewed / df.policies, "rate_insurer": df.nonrenewed_insurer / df.policies}
40      return pd.concat([df.assign(**rates), fair_series(con, county)], ignore_index=True).sort_values(["scope", "release", "y"])
```

- **5–12** Sum counts per release, year and scope (the county versus everyone else).
- **32–38** The SQL's "California" rows exclude the county; summing both groups gives the true statewide total, which replaces them.
- **39–40** Add the two rates and append the FAIR Plan series (tagged as its own release, `fair-plan-fy`).

`regulatory_alignment.py` is the event study:

```python
 9  FITS = (("2015-2021", "rate_insurer", "pts"), ("2020-2023", "rate", "pts"), ("fair-plan-fy", "fair", "%"))
12  def distinct_events(ev: pd.DataFrame) -> pd.DataFrame:
13      ev = ev[ev.kind.isin(["fire", "regulation", "rate_decision"])].copy()
14      ev["date"] = pd.to_datetime(ev.date)
15      g = ev.groupby(["kind", "date"], as_index=False).agg(
16          label=("dst_name", lambda s: ", ".join(sorted(set(s))[:4])), n=("dst", "nunique")
17      )
18      return g.assign(year=g.date.dt.year)
21  def study(ev: pd.DataFrame, tr: pd.DataFrame, release: str, measure: str, unit: str) -> pd.DataFrame:
22      series = tr[tr.release == release].pivot(index="y", columns="scope", values=measure)
23      rows = []
24      for e in ev.itertuples():
25          for scope in series.columns:
26              b, d, a = (series[scope].get(e.year + k) for k in (-1, 0, 1))
27              if pd.isna(b) or pd.isna(d):
28                  continue  # outside this release's window
29              rows.append({**e._asdict(), "scope": scope, "before": b, "during": d, "after": a})
30      out = pd.DataFrame(rows, columns=[*ev.columns, "scope", "before", "during", "after"])
31      if unit == "%":
32          deltas = {"delta_during": (out.during / out.before - 1) * 100, "delta_after": (out.after / out.before - 1) * 100}
33      else:
34          deltas = {"delta_during": (out.during - out.before) * 100, "delta_after": (out.after - out.before) * 100}
35      return out.assign(**deltas, release=release, measure=measure, unit=unit)
38  def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
39      ev, tr = distinct_events(events.compute(con)), trend.compute(con)
40      return pd.concat([study(ev, tr, *f) for f in FITS], ignore_index=True)
```

- **12–18** Collapse events to one per (kind, date): all fires declared the same day are one event, labelled by up to four names.
- **21–35** For each series (insurer-initiated rate, total rate, FAIR count) and each event: read the value in the year before, of, and after the event, for the county and the state; skip if the window is outside the series. Rates are reported as changes in percentage points, counts as percent change.

### 4.6 `fair_mirror.py` — finding 2

```python
 6  SQL = """
 7  WITH nr AS (SELECT dst AS zip, year(valid_from) AS y, json_extract(props,'$.count')::INT AS nonrenewed,
 8                     json_extract(props,'$.policies')::INT AS policies
 9              FROM edges WHERE rel='NONRENEWED_IN' AND json_extract_string(props,'$.release')=?),
10  fair AS (SELECT src AS zip, year(valid_from) AS y, json_extract(props,'$.count')::INT AS fair
11           FROM edges WHERE rel='HAS_FAIR_PLAN_POLICIES')
12  SELECT substr(zip, 5) AS zip, json_extract_string(e.attrs,'$.county') AS county, y, nonrenewed, policies, fair,
13         fair - lag(fair) OVER (PARTITION BY zip ORDER BY y) AS fair_delta,
14         fair::DOUBLE / (fair + policies) AS fair_share
15  FROM fair LEFT JOIN nr USING (zip, y) JOIN entities e ON e.entity_id = zip
16  """
19  def compute(con: duckdb.DuckDBPyConnection, release: str = "2020-2023") -> pd.DataFrame:
20      return con.execute(SQL, [release]).df().assign(release=release)
```

One row per ZIP and year with the FAIR Plan count, its year-over-year change (`lag` is a window function looking at the previous year of the same ZIP), and the FAIR share of all policies where voluntary counts exist. The left join keeps FY2024–2025 rows even though the CDI series has ended.

### 4.7 `actor_centrality.py` — finding 5

```python
 7  SQL = """
 8  SELECT DISTINCT e.src, e.dst, e.rel FROM edges e
 9  JOIN entities s ON s.entity_id = e.src JOIN entities t ON t.entity_id = e.dst
10  WHERE (s.type <> 'zip' OR json_extract_string(s.attrs,'$.county') = ?)
11    AND (t.type <> 'zip' OR json_extract_string(t.attrs,'$.county') = ?)
12  """
16  def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
17      edges, names = con.execute(SQL, [county, county]).df(), con.execute(NAMES).df().set_index("entity_id")
18      g = nx.Graph()
19      g.add_edges_from(edges[["src", "dst"]].itertuples(index=False))
20      zips = {n for n in g if n.startswith("zip:")}
21      bc = nx.betweenness_centrality(g, normalized=True)
22      rows = [
23          {
24              "entity_id": n,
25              "type": names.type.get(n),
26              "name": names.canonical_name.get(n, n),
27              "degree": g.degree(n),
28              "betweenness": bc[n],
29              "cc_zips_within_2": sum(1 for z in zips if z != n and nx.has_path(g, n, z) and nx.shortest_path_length(g, n, z) <= 2),
30              "rels": ", ".join(sorted(set(edges[(edges.src == n) | (edges.dst == n)].rel))),
31          }
32          for n in g
33          if n not in zips
34      ]
35      return pd.DataFrame(rows).sort_values(["betweenness", "degree"], ascending=False).reset_index(drop=True)
```

- **8–12** Take every edge whose endpoints are either non-ZIP entities or Contra Costa ZIPs. Dropping the other 1,600 ZIPs keeps the statewide hub from dominating for reasons that have nothing to do with the county.
- **18–21** Build an undirected NetworkX graph and compute normalised betweenness.
- **22–35** For every non-ZIP node: degree, betweenness, how many county ZIPs are within two hops, and which relations touch it. Sorted by betweenness.

### 4.8 `evidence.py`, `explorer.py`, `geometry.py` — serving tables

`evidence.py` joins every document edge to its document so the app can show the span and URL. `explorer.py` builds the graph explorer's edge list:

```python
 6  SQL = """
 7  WITH cc AS (SELECT entity_id FROM entities WHERE json_extract_string(attrs,'$.county') = ?),
 8  det AS (
 9    SELECT e.*, row_number() OVER (PARTITION BY src, rel, dst, extractor ORDER BY valid_from DESC) AS rn
10    FROM edges e WHERE doc_id IS NULL AND (src IN (SELECT entity_id FROM cc) OR dst IN (SELECT entity_id FROM cc)))
11  SELECT e.src, e.rel, e.dst, e.valid_from, e.valid_to, e.props, e.span, e.extractor, e.confidence, d.url,
12         s.type AS src_type, t.type AS dst_type, s.canonical_name AS src_name, t.canonical_name AS dst_name,
13         json_extract_string(s.attrs,'$.county') AS src_county, json_extract_string(t.attrs,'$.county') AS dst_county
14  FROM (SELECT * FROM edges WHERE doc_id IS NOT NULL UNION ALL SELECT * EXCLUDE (rn) FROM det WHERE rn = 1) e
15  LEFT JOIN documents d USING (doc_id) JOIN entities s ON s.entity_id = e.src JOIN entities t ON t.entity_id = e.dst
16  ORDER BY e.rel, e.src, e.dst
17  """
```

All document edges, plus the county ZIPs' deterministic edges collapsed to their latest year (the `row_number()` window numbers each ZIP's yearly edges from newest to oldest; `rn = 1` keeps the newest), with names, types and counties attached for drawing.

`geometry.py` writes the county's ZIP polygons for the map:

```python
14  def county_geojson(con: duckdb.DuckDBPyConnection, zcta: gpd.GeoDataFrame, places: dict[str, str], county: str) -> dict:
15      zips = set(con.execute(ZIPS, [county]).df().zip)
16      g = zcta[zcta.zip.isin(zips)].copy()
17      g["geometry"] = g.geometry.simplify(TOLERANCE_M)
18      g["place"] = g.zip.map(places).fillna(g.zip)
19      return json.loads(g.to_crs(4326).to_json())
```

Select the county's ZIPs, simplify their outlines by 30 metres (halves the file), attach place names, and reproject to latitude/longitude, which web maps need.

### 4.9 The app: `policygraph/app.py`

```python
 6  ROOT = Path(__file__).resolve().parent.parent
 7  sys.path.insert(0, str(ROOT))  # Streamlit Cloud puts only this file's directory on sys.path
 9  from policygraph.views import explorer, tables, timeline  # noqa: E402
10  from policygraph.views import map as map_view  # noqa: E402
11  from policygraph.views.data import DOCS  # noqa: E402
13  st.set_page_config(page_title="policygraph", layout="wide")
14  st.title("Home-insurance non-renewals · Contra Costa County")
15  st.markdown("This is a knowledge graph built to answer one question: ...")
28  TABS = {
29      "Findings": lambda: st.markdown((DOCS / "FINDINGS.md").read_text()),
30      "Map": map_view.render,
31      "Timeline": timeline.render,
32      "Graph": explorer.render,
33      "Hazard residual": tables.hazard,
34      "Moratorium deferral": tables.moratorium,
35      "FAIR Plan mirror": tables.fair,
36      "Regulatory alignment": tables.regulatory,
37      "Actors": tables.actors,
38      "Evidence": tables.evidence,
39  }
40  for tab, render in zip(st.tabs(list(TABS)), TABS.values(), strict=True):
41      with tab:
42          render()
```

- **6–7** Streamlit Cloud runs the script with only its own folder on Python's import path. Inserting the repository root first makes `import policygraph.views` work everywhere. The `noqa: E402` comments tell the linter the late imports are deliberate.
- **13–15** Page setup, title, and the plain-language summary.
- **28–42** A dictionary from tab name to the function that draws it; `st.tabs` creates the tabs and each function draws inside its tab.

### 4.10 `views/data.py` — shared loading and colours

```python
 7  ROOT = Path(__file__).resolve().parent.parent.parent
 8  INSIGHTS, DOCS = ROOT / "data" / "insights", ROOT / "docs"
 9  COUNTY = "Contra Costa"
12  SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
13  DIV = ["#0d366b", "#3987e5", "#9ec5f4", "#f0efec", "#f3a5a5", "#e34948", "#8f1f1f"]
14  CAT = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "magenta": "#e87ba4", "violet": "#4a3aa7"}
15  KIND_COLOR = {"regulation": CAT["blue"], "fire": CAT["orange"], "moratorium": CAT["aqua"], "rate_decision": CAT["yellow"]}
30  @st.cache_data
31  def load(name: str) -> pd.DataFrame:
32      return pd.read_parquet(INSIGHTS / f"{name}.parquet")
44  def ramp(ramp_hex: list[str], t: float) -> list[int]:
45      """Piecewise-linear interpolation through the ramp at t in [0, 1]."""
46      t = min(max(t, 0.0), 1.0) * (len(ramp_hex) - 1)
47      i = min(int(t), len(ramp_hex) - 2)
48      a, b = hex_rgb(ramp_hex[i]), hex_rgb(ramp_hex[i + 1])
49      return [round(a[k] + (b[k] - a[k]) * (t - i)) for k in range(3)]
```

- **7–9** Paths derived from `__file__` again; the county name.
- **12–15** Colour scales: a single-hue blue ramp for magnitudes, a blue–grey–red ramp for values that can be positive or negative (residuals), and a fixed categorical order for series and event kinds. These come from a validated colour-blind-safe reference palette.
- **30–32** `st.cache_data` keeps each parquet in memory after the first read so tabs render instantly.
- **44–49** Given a ramp and a position 0–1, blend between the two neighbouring colours.

### 4.11 `views/map.py` — the choropleth

```python
13  def metrics() -> dict[str, tuple[pd.Series, bool, str]]:
14      res = load("hazard_residual")
15      res = res[(res.county == COUNTY) & (res.spec == "hazard")]
16      ins, tot = res[res.measure == "nonrenewed_insurer"].set_index("zip"), res[res.measure == "count"].set_index("zip")
17      fair = load("fair_mirror")
18      fair = fair[fair.county == COUNTY].set_index(["zip", "y"]).sort_index()
19      prot = load("explorer")
20      prot = prot[(prot.rel == "PROTECTED_BY") & (prot.src_county == COUNTY)]
21      covered = prot.groupby(prot.src.str[4:]).dst_name.agg(lambda s: "; ".join(sorted(set(s))))
22      return {
23          "Insurer-initiated non-renewal rate, 2021 (2015–2021 release)": (ins.rate * 100, False, "{:.2f} %"),
24          "Hazard residual, 2021 insurer-initiated (pts above the hazard line)": (ins.residual * 100, True, "{:+.2f} pts"),
...
32          "Moratorium coverage (SB 824 bulletins)": (covered, False, "{}"),
33      }
```

Ten selectable metrics, each a Series indexed by ZIP, a flag saying whether it is diverging (needs the two-hue ramp), and a number format.

```python
36  def colour(values: pd.Series, diverging: bool) -> dict[str, list[int]]:
37      if values.dtype == object:
38          return {z: [27, 175, 122, 190] for z in values.index}  # categorical: covered or not
38      if diverging:
40          m = float(values.abs().max()) or 1.0
41          return {z: [*ramp(DIV, 0.5 + v / (2 * m)), 200] for z, v in values.items()}
42      lo, hi = float(values.min()), float(values.max())
43      return {z: [*ramp(SEQ, (v - lo) / ((hi - lo) or 1.0)), 200] for z, v in values.items()}
```

Text metrics (moratorium names) colour every covered ZIP green. Diverging metrics centre zero on the grey midpoint and scale symmetrically. Others map min→lightest, max→darkest. The fourth number is opacity.

```python
46  def render() -> None:
47      label = st.selectbox("Colour ZIPs by", list(metrics()))
48      values, diverging, fmt = metrics()[label]
49      values = values.dropna()
50      fills = colour(values, diverging)
51      gj = copy.deepcopy(geojson())
52      for f in gj["features"]:
53          z = f["properties"]["zip"]
54          f["properties"]["fill"] = fills.get(z, [240, 239, 236, 120])
55          f["properties"]["display"] = fmt.format(values[z]) if z in values.index else "no data"
56          f["properties"]["label"] = label
57      layer = pdk.Layer("GeoJsonLayer", gj, pickable=True, stroked=True, filled=True,
                        get_fill_color="properties.fill", get_line_color=[82, 81, 78], line_width_min_pixels=1)
67      tooltip = {"html": "<b>{place}</b> · {zip}<br/>{label}<br/><b>{display}</b>"}
68      st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(**CENTER), tooltip=tooltip, map_style="light"))
```

Pick a metric, compute fills, copy the cached GeoJSON (never mutate a cached object), stamp each polygon with its colour and formatted value, and draw a pydeck layer with hover tooltips. Below the map a legend line and a sortable table repeat the numbers, so colour never carries meaning alone.

### 4.12 `views/timeline.py`

```python
13  def series_chart(tr: pd.DataFrame, ev: pd.DataFrame, release: str, measure: str, title: str) -> alt.Chart:
14      df = tr[tr.release == release].assign(pct=lambda d: d[measure] * 100, date=lambda d: pd.to_datetime(d.y.astype(str) + "-07-01"))
17      lo, hi = df.date.min() - pd.DateOffset(months=6), df.date.max() + pd.DateOffset(months=6)
18      ev = ev[(ev.date >= lo) & (ev.date <= hi)]
19      scale = alt.Scale(domain=[COUNTY, "California"], range=[CAT["blue"], CAT["orange"]])
20      line = alt.Chart(df).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2).encode(
                x=alt.X("date:T", ...), y=alt.Y("pct:Q", title="% of policies"), color=alt.Color("scope:N", scale=scale, ...), tooltip=[...])
30      rules = alt.Chart(ev).mark_rule(strokeWidth=2, opacity=0.8).encode(x="date:T", color=alt.Color("kind:N", ...), tooltip=[...])
39      return (line + rules).properties(title=title, height=260).resolve_scale(color="independent")
```

Two Altair charts per release: the county and state rates as lines (annual points placed at mid-year), with the document events as vertical rules coloured by kind. `resolve_scale(color="independent")` lets the lines and rules use different colour legends. `render` draws one chart per release and a table of the events.

### 4.13 `views/explorer.py`

```python
24  def neighbourhood(df: pd.DataFrame, start: str, hops: int) -> pd.DataFrame:
25      seen, frontier = {start}, {start}
26      for _ in range(hops):
27          step = df[df.src.isin(frontier) | df.dst.isin(frontier)]
28          frontier = (set(step.src) | set(step.dst)) - seen
29          seen |= frontier
30      return df[df.src.isin(seen) & df.dst.isin(seen)]
```

A breadth-first expansion: starting from one entity, take every edge touching the current frontier, add the new endpoints, repeat `hops` times, and return every edge among the reached nodes.

```python
47  def render() -> None:
48      df = load("explorer")
49      ents = pd.concat([...]).drop_duplicates("id")
55      cc = set(df[df.src_county == COUNTY].src) | set(df[df.dst_county == COUNTY].dst)
56      pick = ents[(ents.type != "zip") | ents.id.isin(cc)].sort_values(["type", "name"])
57      default = int((pick.id == "zip:94549").to_numpy().argmax())
59      start = c1.selectbox("Start entity", pick.id, index=default, format_func=...)
60      hops = c2.slider("Hops", 1, 3, 1)
61      cap = c3.slider("Max edges", 50, 600, 200, step=50)
62      sub = neighbourhood(df, start, hops).head(cap)
65      nodes = [{"id": i, "label": ..., "title": i, "color": TYPE_COLOR.get(names.type[i], "#888"), "borderWidth": 3 if i == start else 1} for i in ids]
75      edges = [{"from": e.src, "to": e.dst, "label": e.rel, "title": title(e)} for e in sub.itertuples()]
80      st.iframe(HTML.format(vis=VIS, nodes=json.dumps(nodes), edges=json.dumps(edges)), height=640)
```

The picker offers every non-ZIP entity plus the county's ZIPs (Lafayette by default). The chosen neighbourhood is turned into node and edge lists for vis-network, a JavaScript graph library loaded from a CDN inside an iframe. `title(e)` builds the hover text: relation, extractor, confidence, dates, props, the quoted span and the source URL — the receipt for every edge.

### 4.14 `views/tables.py`

Five small functions, one per table tab. `hazard` lets you choose the measure and the regressor spec, prints the fit summary (coefficients with p-values, R², sample size), shows the county's ZIPs with their rank among all California ZIPs, and draws a scatter of rate against Very High share with the county highlighted. `moratorium` picks a release and shows protected-versus-control summaries with ratios, then the per-ZIP rows. `fair`, `regulatory`, `actors` and `evidence` show their tables with a caption explaining what they are.
