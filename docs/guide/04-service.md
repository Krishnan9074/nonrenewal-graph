## Part 5. The extraction service

The service is the only code that talks to a language model. It is a separate program with two processes:

- **the API** (`api.py`, run by uvicorn): accepts jobs, reports run manifests, serves artifacts, and answers resolution requests;
- **the worker** (`worker.py`): takes queued jobs one at a time and produces a validated artifact per document.

They share a SQLite queue and a folder of JSON artifacts (`store.py`). The design idea is that the model is boxed in on both sides: deterministic *anchors* go in (every ZIP, date and bill number the text contains, plus every fire heading with a ZIP list under it), and deterministic *validators* check what comes out (spans must be verbatim, types must fit the relation, ZIPs and dates must be anchored). What survives is written as an immutable artifact whose id is a hash of everything that produced it.

### 5.1 `extraction_service/__init__.py` and `models.py`

```python
 4  STORE = Path(os.environ.get("EXTRACTION_STORE", "data/extractions"))
 5  SCHEMA_DIR = Path(__file__).parent / "schema"
 6  PROMPT_DIR = Path(__file__).parent / "prompts"
```

Where artifacts go, and where the JSON schema and the prompt live.

```python
 6  EntityType = Literal["ZIP", "Insurer", "Fire", "Moratorium", "Regulation", "Official", "RateFiling", "County"]
 7  Rel = Literal["PROTECTED_BY", "TRIGGERED", "ISSUED", "FILED", "DECIDED", "AUTHORED", "DONATED_TO"]
 9  REL_TYPES: dict[str, tuple[set[str], set[str]]] = {
10      "PROTECTED_BY": ({"ZIP"}, {"Moratorium"}),
11      "TRIGGERED": ({"Fire"}, {"Moratorium"}),
12      "ISSUED": ({"Official"}, {"Moratorium", "Regulation"}),
13      "FILED": ({"Insurer"}, {"RateFiling"}),
14      "DECIDED": ({"Official"}, {"RateFiling"}),
15      "AUTHORED": ({"Official"}, {"Regulation"}),
16      "DONATED_TO": ({"Insurer"}, {"Official"}),
17  }
```

The closed vocabularies: eight entity types, seven relations, and for each relation which source and target types are allowed. `Literal[...]` makes Pydantic reject any other value.

```python
20  class Entity(BaseModel):
21      mention: str
22      type: EntityType
25  class Edge(BaseModel):
26      src_mention: str
27      rel: Rel
28      dst_mention: str
29      valid_from: date | None = None
30      valid_to: date | None = None
31      props: dict = Field(default_factory=dict)
32      span: str = Field(min_length=8)
33      confidence: float = Field(ge=0, le=1)
36  class Extraction(BaseModel):
37      entities: list[Entity]
38      edges: list[Edge]
41  class Artifact(Extraction):
42      extraction_id: str
43      doc_id: str
44      schema_v: str
45      prompt_v: str
46      model_id: str
47      status: Literal["ok", "no_target_relations", "failed_validation", "error"]
48      rejected: list[str] = Field(default_factory=list)
51  class Job(BaseModel):
52      run_id: str
53      doc_id: str
54      source: str
55      text: str
56      force: bool = False  # bypass the extraction cache and overwrite the artifact
```

- **20–38** What the model returns: entities (a mention and its type) and edges (two mentions, a relation, optional dates, a property bag, a span of at least eight characters, and a confidence in 0–1).
- **41–48** An artifact is an extraction plus its identity (which document, schema version, prompt version, model), a status, and the list of edges the validators rejected (kept for audit).
- **51–56** A job as the API receives it.

```python
59  class ZipBlock(BaseModel):
60      heading: str
61      name: str
62      date: date | None  # the declaration this block sits under; None outside a dated section
63      zips: list[str]
64      span: str
67  class Anchors(BaseModel):
68      zips: set[str]
69      dates: set[date]
70      bills: set[str]
71      zip_blocks: list[ZipBlock] = Field(default_factory=list)
73      def for_prompt(self) -> str:
74          """Headings and dates only: the model relates fires to declarations, it does not enumerate ZIPs."""
75          blocks = [{"heading": b.heading, "declaration": str(b.date), "zips": len(b.zips)} for b in self.zip_blocks]
76          return self.model_dump_json(exclude={"zip_blocks"})[:-1] + f', "fire_blocks": {blocks}}}'.replace("'", '"')
```

- **59–64** A ZIP block: a fire heading in a bulletin, the fire's cleaned name, the declaration date the section falls under, the ZIPs listed under it, and the verbatim text of heading plus list.
- **67–76** The anchors handed to the model. `for_prompt` serialises them as JSON but replaces each block's ZIP list with a count: the model is told which fires exist and which declaration they belong to, not asked to copy hundreds of ZIPs.

```python
79  class Candidate(BaseModel):    # an entity the resolver may map a mention to
86  class Mention(BaseModel):      # a mention plus a context span
92  class Resolution(BaseModel):   # the service's answer: entity id or None, method, confidence, nearest candidate and its cosine, models used
104 class ResolveRequest(BaseModel): mentions + candidates
```

The request and response shapes of the resolve endpoint.

### 5.2 `chunk.py`

```python
 3  TARGET, OVERLAP = 5000, 1500  # ~10 fires per chunk: the model drops ZIPs past ~200 per call; overlap covers a whole ZIP list
 4  HEAD = 3500  # the document head travels with every chunk as context: bulletins date their declarations on page 2-3
14  def split(text: str, target: int = TARGET, overlap: int = OVERLAP) -> list[Chunk]:
15      if len(text) <= target:
16          return [Chunk(0, 0, text)]
17      chunks: list[Chunk] = []
18      start = 0
19      while start < len(text):
20          end = min(len(text), start + target)
21          if end < len(text) and (cut := text.rfind("\n", start + target // 2, end)) > 0:
22              end = cut
23          chunks.append(Chunk(len(chunks), start, text[start:end]))
24          if end == len(text):
25              break
26          start = end - overlap
27      return chunks
```

Long documents are cut into overlapping pieces. Each piece is at most 5,000 characters, preferably ending at a line break in its second half, and the next piece starts 1,500 characters back so that any ZIP list cut in two appears whole in one of them. Each chunk remembers its starting offset so spans can be located in the document. Separately, the first 3,500 characters of the document ride along with every chunk as read-only context, because bulletins state their declaration dates near the top and list ZIPs pages later.

### 5.3 `anchors.py`

```python
 8  ZIP_RE = re.compile(r"\b9[0-6]\d{3}\b")
 9  BILL_RE = re.compile(r"\b(SB|AB|Senate Bill|Assembly Bill)\s?(\d{1,4})\b", re.I)
10  HOUSE = {"senate bill": "SB", "assembly bill": "AB"}
11  DATE_RE = re.compile(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
13  DECL_RE = re.compile(r"Governor[’']s\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s+(?:emergency\s+)?[Dd]\s?eclarations?")
14  HEADING_RE = re.compile(r"^[^\n]{1,90}\bFires?\b[^\n]{0,60}$")
15  NOT_HEADING = re.compile(r"perimeter|Protection|Department|insurer|ZIP|Governor|declar|Bulletin|Moratorium|Page|due to|•", re.I)
16  NAME_STRIP = (re.compile(r"\(.*?\)"), re.compile(r"[\[\]]"), re.compile(r"\d+$"), re.compile(r"\bFires?\b(\s+\d{4})?\s*$"))
```

- **8** A California ZIP: five digits starting 90–96, as a whole word.
- **9–10** Bill numbers in short or long form, normalised to `SB824`.
- **11** Dates written as `January 7, 2025` or `2025-01-07`.
- **13** The sentence that dates a bulletin section: "due to the Governor's October 27, 2019 Declaration" or "as a result of the Governor's September 6, 2020 emergency declaration" (pypdf sometimes inserts a space inside "declaration", hence `[Dd]\s?eclaration`).
- **14–15** A fire heading is a short line containing "Fire" or "Fires" that is not one of the sentences that merely mention fires.
- **16** Patterns stripped from a heading to get the fire's name: parentheticals, square brackets, trailing footnote digits, and the word "Fire(s)" with an optional year.

```python
29  def fire_name(heading: str) -> str:
30      """'[Old] Water Fire' -> 'Old Water'; 'SHF Lightning Fires 2020' -> 'SHF Lightning'."""
31      name = heading.strip()
32      for rx in NAME_STRIP:
33          name = rx.sub("", name).strip()
34      return " ".join(name.split())
37  def zip_blocks(text: str) -> list[ZipBlock]:
38      """Fire headings followed by ZIP lines, dated by the nearest preceding declaration sentence. Bulletins only."""
39      decls = [(m.start(), pd.to_datetime(m.group(1)).date()) for m in DECL_RE.finditer(text)]
40      lines, pos, out = text.split("\n"), 0, []
41      starts = []
42      for line in lines:
43          starts.append(pos)
44          pos += len(line) + 1
45      i = 0
46      while i < len(lines):
47          line = lines[i].strip()
48          is_heading = HEADING_RE.match(line) and not NOT_HEADING.search(line) and not ZIP_RE.search(line)
49          if is_heading and i + 1 < len(lines) and ZIP_RE.search(lines[i + 1]):
50              j = i + 1
51              while j < len(lines) and ZIP_RE.search(lines[j]):
52                  j += 1
53              zips = [z for k in range(i + 1, j) for z in ZIP_RE.findall(lines[k])]
54              before = [d for p, d in decls if p < starts[i]]
55              span = text[starts[i] : starts[j - 1] + len(lines[j - 1])].strip()
56              out.append(ZipBlock(heading=line, name=fire_name(line), date=before[-1] if before else None, zips=zips, span=span))
57              i = j
58          else:
59              i += 1
60      return out
```

- **39** Every declaration sentence with its character position and date.
- **40–44** Split into lines and record where each line starts in the full text.
- **46–60** Scan the lines. A heading immediately followed by a line containing a ZIP starts a block; the block continues while lines contain ZIPs. Collect the ZIPs, find the last declaration sentence before the heading (that is the section's date), cut the exact text from heading to last ZIP line as the span, and jump past the block.

On the four bulletins this parser recovers every ZIP list: 231 ZIPs in the 2019 bulletin and 713 in the 2020-11 bulletin, matching the hand-made golden set exactly. The 2025-1 bulletin lists ZIPs on the same line as the fire name, so it yields no blocks and is handled entirely by the model.

```python
63  def extract(text: str) -> Anchors:
64      return Anchors(zips=set(ZIP_RE.findall(text)), dates=_dates(text),
                     bills={HOUSE.get(h.lower(), h.upper()) + n for h, n in BILL_RE.findall(text)}, zip_blocks=zip_blocks(text))
```

All anchors for a piece of text.

### 5.4 `validators.py`

```python
11  def _norm(s: str) -> str:
12      """pypdf breaks words across lines ("Sanda\nlwood"), so whitespace is ignored entirely; characters are not."""
13      return _WS.sub("", s).lower()
17  def span_verbatim(edge: Edge, chunk: str) -> str | None:
18      return None if _norm(edge.span) in _norm(chunk) else "span is not a verbatim substring of the chunk"
21  def types_allowed(edge: Edge, types: dict[str, str]) -> str | None:
22      src_ok, dst_ok = REL_TYPES[edge.rel]
23      got = (types.get(edge.src_mention), types.get(edge.dst_mention))
24      if got[0] in src_ok and got[1] in dst_ok:
25          return None
26      return f"types {got[0]}->{got[1]} not allowed for {edge.rel}; need {'/'.join(src_ok)}->{'/'.join(dst_ok)}"
```

Each check returns `None` on success or a message on failure; the message is fed back to the model on retry.

- **11–18** The span must be a verbatim substring of the chunk, comparing with all whitespace removed and case ignored (PDF text extraction breaks words across lines; nothing else is forgiven).
- **21–26** The source and target mention types must be allowed for the relation.

```python
29  def _near(d: date, anchors: Anchors) -> bool:
30      return d in anchors.dates or any(abs(d - a) <= timedelta(days=366) for a in anchors.dates)
33  def anchored(edge: Edge, anchors: Anchors) -> str | None:
34      for m in (edge.src_mention, edge.dst_mention):
35          if _ZIP.fullmatch(m) and m not in anchors.zips:
36              return f"anchors: ZIP {m} is not in the chunk"
37          if _BILL.fullmatch(m) and m.upper().replace(" ", "") not in anchors.bills:
38              return f"anchors: bill {m} is not in the chunk"
39      if all(d is None or _near(d, anchors) for d in (edge.valid_from, edge.valid_to)):
40          return None
41      return "anchors: dates are not within a year of any date in the chunk"
44  def dates_sane(edge: Edge) -> str | None:
45      if edge.valid_from is None or edge.valid_to is None or edge.valid_from <= edge.valid_to:
46          return None
47      return "dates: valid_from > valid_to"
```

- **33–41** A ZIP or bill mention must appear in the chunk (this is what stops a hallucinated ZIP), and any edge date must be within a year of some date the chunk (or document head) contains.
- **44–47** Start must not be after end.

```python
50  def validate(x: Extraction, chunk: str, anchors: Anchors) -> tuple[Extraction, list[str]]:
51      types = {e.mention: e.type for e in x.entities}
52      kept, errors = [], []
53      for e in x.edges:
54          failed = [m for m in (span_verbatim(e, chunk), types_allowed(e, types), anchored(e, anchors), dates_sane(e)) if m]
55          if failed:
56              errors.append(f"{e.src_mention} -{e.rel}-> {e.dst_mention}: {'; '.join(failed)}")
57          else:
58              kept.append(e)
59      return Extraction(entities=x.entities, edges=kept), errors
```

Run all four checks on every edge; keep the clean ones, collect a readable error for each rejected one.

### 5.5 `expand.py` — deterministic expansion of ZIP blocks

```python
 8  FIRE_RE = re.compile(r"^(.+?) Fires?(?: \(.*?\))?(?: (\d{4}))?(?: \d{4})?$", re.I)
 9  MOR_RE = re.compile(r"^(.+?) Fires?(?: \(.*?\))?(?: \d{4})? moratorium (\d{4}-\d{2}-\d{2})$", re.I)
10  CONFIDENCE = 0.97  # the ZIP list is read by regex; the fire-to-declaration link is the model's or the section's
13  def same(a: str, b: str) -> bool:
14      a, b = a.lower(), b.lower()
15      return a == b or a.endswith(b) or b.endswith(a)
```

- **8–9** Tolerant versions of the mention conventions: they accept parentheticals, "Fires", and a doubled year, so that variants the model copies from headings can be recognised.
- **13–15** Two names are "the same" if equal or one is a suffix of the other. This absorbs PDF artefacts such as "lwood" for "Sandalwood" and "Water" for "Old Water".

```python
18  def canonical_mentions(x: Extraction) -> dict[str, str]:
22      parsed: dict[str, tuple[str, str, str | None]] = {}
23      for e in x.entities:
24          if e.type == "Fire" and (m := FIRE_RE.match(e.mention)):
25              parsed[e.mention] = ("Fire", fire_name(m.group(1) + " Fire"), m.group(2))
26          elif e.type == "Moratorium" and (m := MOR_RE.match(e.mention)):
27              parsed[e.mention] = ("Moratorium", fire_name(m.group(1) + " Fire"), m.group(2))
28      out = {}
29      for mention, (kind, name, when) in parsed.items():
30          peers = [(n, w) for k, n, w in parsed.values() if k == kind and same(n, name) and (w == when or when is None or w is None)]
33          name = max((n for n, _ in peers), key=len)
34          when = when or next((w for _, w in peers if w), None)
35          if kind == "Fire":
36              out[mention] = f"{name} Fire {when}" if when else f"{name} Fire"
37          else:
38              out[mention] = f"{name} Fire moratorium {when}"
39      return {k: v for k, v in out.items() if v != k}
```

Builds a rename map from every fire or moratorium mention the model produced to its canonical form: parse each into (kind, clean name, year or date); group with its peers (same kind, same-ish name, compatible date); take the longest name in the group and any date the group knows; rebuild the mention in the prompt's convention. Only mentions that actually change are returned. Examples: "Eagle Fire (Lake County) 2019" → "Eagle Fire 2019"; "Bobcat Fire" → "Bobcat Fire 2020"; "lwood Fire moratorium 2019-10-11" → "Sandalwood Fire moratorium 2019-10-11".

```python
42  def expand(x: Extraction, blocks: list[ZipBlock]) -> Extraction:
45      fold = canonical_mentions(x)
46      ents = {(fold.get(e.mention, e.mention), e.type): Entity(mention=fold.get(e.mention, e.mention), type=e.type) for e in x.entities}
49      edges: dict[tuple, Edge] = {}
50      for e in x.edges:
51          e = e.model_copy(update={"src_mention": fold.get(e.src_mention, e.src_mention), "dst_mention": fold.get(e.dst_mention, e.dst_mention)})
54          edges.setdefault((e.src_mention, e.rel, e.dst_mention), e)
55      mors = {m: MOR_RE.match(m) for (m, t) in ents if t == "Moratorium" and MOR_RE.match(m)}
56      official = next((e.src_mention for e in edges.values() if e.rel == "ISSUED" and e.dst_mention in mors), None)
57      for b in blocks:
58          if b.date is None:
59              continue
60          hit = [m for m, r in mors.items() if same(r.group(1), b.name) and r.group(2) == b.date.isoformat()]
61          name = mors[hit[0]].group(1) if hit else b.name
62          mor, fire = hit[0] if hit else f"{name} Fire moratorium {b.date.isoformat()}", f"{name} Fire {b.date.year}"
63          base = {"valid_from": b.date, "valid_to": _plus_year(b.date), "props": {"expanded_from": "zip_block"}, "span": b.span, "confidence": CONFIDENCE}
70          ents.setdefault((fire, "Fire"), Entity(mention=fire, type="Fire"))
71          ents.setdefault((mor, "Moratorium"), Entity(mention=mor, type="Moratorium"))
72          edges.setdefault((fire, "TRIGGERED", mor), Edge(src_mention=fire, rel="TRIGGERED", dst_mention=mor, **base))
73          if official:
74              edges.setdefault((official, "ISSUED", mor), Edge(src_mention=official, rel="ISSUED", dst_mention=mor, **base))
75          for z in b.zips:
76              ents.setdefault((z, "ZIP"), Entity(mention=z, type="ZIP"))
77              edges.setdefault((z, "PROTECTED_BY", mor), Edge(src_mention=z, rel="PROTECTED_BY", dst_mention=mor, **base))
78      return Extraction(entities=list(ents.values()), edges=list(edges.values()))
```

- **45–54** Apply the rename map to entities and edges, and de-duplicate edges by (source, relation, target) — the model's own edge wins because it is inserted first (`setdefault` keeps the first value).
- **55–56** Index the moratorium mentions, and find the official who issued them (the Commissioner).
- **57–77** For every dated block: find the model's moratorium mention for this fire (same name, same declaration date) or synthesise one from the heading; then add, only where missing, the TRIGGERED edge, the ISSUED edge and one PROTECTED_BY edge per ZIP. Expanded edges carry the block's verbatim span, a confidence of 0.97, the moratorium's one-year window, and `props.expanded_from = "zip_block"` so downstream code can tell them apart.

This step is why recall on bulletins is 0.997: the model reliably names the fires and dates; the regex reliably reads the lists; neither is asked to do the other's job.

### 5.6 The adapters: `adapters/__init__.py`, `openai_compat.py`, `anthropic.py`

```python
 7  class Adapter(Protocol):
 8      model_id: str
10      def structured(self, prompt: str, schema: dict) -> dict:
11          """One model call constrained to a JSON schema; the caller validates the result."""
15  def build(model_id: str) -> Adapter:
16      if PROVIDER == "anthropic": ... return AnthropicAdapter(model_id)
20      if PROVIDER == "openai_compat": ... return OpenAICompatAdapter(model_id)
24      raise ValueError(f"unknown EXTRACTION_PROVIDER {PROVIDER!r}")
```

An adapter is anything with a `model_id` and a `structured(prompt, schema)` method returning a dictionary. `build` picks the implementation from the `EXTRACTION_PROVIDER` variable. Everything above this line is provider-agnostic.

```python
10  def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
11      return httpx.Client(base_url=os.environ["OPENAI_COMPAT_BASE_URL"],
                           headers={"Authorization": f"Bearer {os.environ['OPENAI_COMPAT_API_KEY']}"},
                           timeout=httpx.Timeout(600, read=120), transport=transport)
27      def structured(self, prompt: str, schema: dict) -> dict:
28          for attempt in range(RETRIES):
29              try:
30                  return self._once(prompt, schema)
31              except httpx.TransportError as e:
32                  if attempt == RETRIES - 1:
33                      raise
34                  print(f"retry {attempt + 1}/{RETRIES} after {type(e).__name__}", flush=True)
35                  time.sleep(BACKOFF_S * (attempt + 1))
38      def _once(self, prompt: str, schema: dict) -> dict:
39          body = {"model": self.model_id, "max_tokens": self.max_tokens, "temperature": 0, "stream": True,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}}}
47          parts: list[str] = []
48          with self.client.stream("POST", "/chat/completions", json=body) as r:
49              r.raise_for_status()
50              for line in r.iter_lines():
51                  if line.startswith("data: ") and line != "data: [DONE]":
52                      choices = json.loads(line[6:])["choices"]  # the final usage event carries no choices
53                      parts += [c["delta"].get("content") or "" for c in choices]
54          return json.loads("".join(parts))
```

- **10–16** An HTTP client for any OpenAI-compatible endpoint (Fireworks here); the `transport` parameter lets tests substitute a fake server. The read timeout is the maximum silence between streamed tokens.
- **27–36** Up to three attempts; a network stall waits 15, then 30 seconds before retrying.
- **38–54** One call: temperature 0, streaming on, output constrained to the JSON schema. The stream arrives as `data: {...}` lines; the text deltas are concatenated and parsed as JSON.

The Anthropic adapter does the same through Anthropic's SDK, using a forced tool call whose input schema is the JSON schema.

### 5.7 `embed.py` and `resolve.py` — the resolver's model steps

```python
15      def embed(self, texts: list[str]) -> list[list[float]]:
16          r = self.client.post("/embeddings", json={"model": self.model_id, "input": texts})
17          r.raise_for_status()
18          return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
```

Embeds a list of strings in one request and returns the vectors in input order.

```python
10  ACCEPT, MARGIN = 0.92, 0.05  # cosine to accept on embeddings alone, and the gap to the runner-up
11  JUDGE_BAND, JUDGE_ACCEPT = 0.75, 0.85  # below the band nothing is asked; the judge must be this sure
19  JUDGE_PROMPT = """Do the mention and the candidate refer to the same real-world {type}?
20  Mention: {mention}
21  Mention context: {context}
22  Candidate: {name} — {description}
23  Answer with same_entity and your confidence."""
28  def cosines(q: np.ndarray, m: np.ndarray) -> np.ndarray:
29      return (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q))
44  def decide(m: Mention, order: list[tuple[Candidate, float]], judge: Judge, models: tuple[str, str]) -> Resolution:
46      if not order:
47          return Resolution(**base, entity_id=None, method="unresolved", confidence=0.0)
48      (top, s1), s2 = order[0], order[1][1] if len(order) > 1 else 0.0
49      if s1 >= ACCEPT and s1 - s2 >= MARGIN:
50          return Resolution(**base, entity_id=top.entity_id, method="embedding", confidence=s1, nearest=top.entity_id, score=s1)
51      for c, s in order[:2]:
52          if s >= JUDGE_BAND and (p := judge_one(m, c, judge)) >= JUDGE_ACCEPT:
53              return Resolution(**base, entity_id=c.entity_id, method="llm_judge", confidence=p, nearest=top.entity_id, score=s1)
54      return Resolution(**base, entity_id=None, method="unresolved", confidence=0.0, nearest=top.entity_id, score=s1)
```

The decision rule for one mention, given candidates ranked by cosine similarity:

- Accept on embeddings alone if the best cosine is at least 0.92 *and* beats the runner-up by 0.05.
- Otherwise, for the top two candidates with cosine at least 0.75, ask the model "same entity?" with the mention's context; accept if it says yes with confidence at least 0.85.
- Otherwise unresolved, recording the nearest candidate and its score so a reviewer can see what was close.

```python
62  def resolve(mentions, cands, embed, judge, models) -> list[Resolution]:
66      cache = STORE / "resolutions"
68      keys = [cache_key(m, [c for c in cands if c.type == m.type], models) for m in mentions]
69      todo = [m for m, k in zip(mentions, keys, strict=True) if not (cache / f"{k}.json").exists()]
70      if todo:
71          vecs = np.array(embed([m.mention for m in todo] + [f"{c.name} — {c.description}" for c in cands]))
72          mv, cv = vecs[: len(todo)], vecs[len(todo) :]
73          for m, v in zip(todo, mv, strict=True):
74              same = [i for i, c in enumerate(cands) if c.type == m.type]
75              order = ranked(v, [cands[i] for i in same], cv[same]) if same else []
76              r = decide(m, order, judge, models)
77              (cache / f"{cache_key(m, [cands[i] for i in same], models)}.json").write_text(r.model_dump_json(indent=1))
78      return [Resolution.model_validate_json((cache / f"{k}.json").read_text()) for k in keys]
```

Every answer is cached by a hash of the mention, its context, the same-type candidates, the two model ids and a resolver version, so identical questions never cost a second call. Mentions and candidates are embedded in one batch; each mention is compared only with candidates of its own type (an insurer can never resolve to an official).

### 5.8 `store.py` — queue and artifact store

```python
 6  DDL = """
 7  CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, schema_v TEXT, created_at TEXT DEFAULT current_timestamp);
 8  CREATE TABLE IF NOT EXISTS jobs (run_id TEXT, doc_id TEXT, source TEXT, text TEXT, status TEXT,
 9    extraction_id TEXT, force INTEGER DEFAULT 0, PRIMARY KEY (run_id, doc_id));
10  """
39  def claim() -> tuple[str, str, str, str, bool] | None:
40      con = _con()
41      con.execute("BEGIN IMMEDIATE")
42      row = con.execute("SELECT run_id, doc_id, source, text, force FROM jobs WHERE status='queued' LIMIT 1").fetchone()
43      if row:
44          con.execute("UPDATE jobs SET status='running' WHERE run_id=? AND doc_id=?", row[:2])
45      con.execute("COMMIT")
46      return (*row[:4], bool(row[4])) if row else None
49  def complete(run_id: str, doc_id: str, art: Artifact, overwrite: bool = False) -> None:
50      path = STORE / f"{art.extraction_id}.json"
51      if overwrite or not path.exists():
52          path.write_text(art.model_dump_json(indent=1))
53      _con().execute("UPDATE jobs SET status=?, extraction_id=? WHERE run_id=? AND doc_id=?", (art.status, art.extraction_id, run_id, doc_id))
59  def manifest(run_id: str) -> dict:
        ... returns run_id, schema_v, status ("running" while any job is queued or running, else "complete"),
            and the extraction ids grouped as extractions / failed / errors
```

A SQLite file holds runs and jobs. `claim` takes one queued job inside an immediate transaction so two workers could not grab the same one. `complete` writes the artifact (never overwriting unless forced) and records its id on the job. `requeue_running` (called at worker start) returns jobs a crashed worker left behind to the queue; `fail` marks a job `error` with the message.

### 5.9 `worker.py`

```python
14  MODEL_ID = os.environ.get("EXTRACTION_MODEL", "accounts/fireworks/models/gpt-oss-120b")
15  SCHEMA_V, PIPELINE_V = "1.0", "0.3.2"
16  PROMPT = (PROMPT_DIR / "v2.md").read_text()
17  PROMPT_V = hashlib.sha256(PROMPT.encode()).hexdigest()[:12]
18  SCHEMA = json.loads((SCHEMA_DIR / "v1.json").read_text())
21  def extraction_id(doc_id: str, model_id: str) -> str:
22      return hashlib.sha256("|".join((doc_id, SCHEMA_V, PROMPT_V, model_id, "adaptive", PIPELINE_V)).encode()).hexdigest()
```

- **15–17** The schema version, the pipeline version (bumped whenever the worker's logic changes), and the prompt version, which is a hash of the prompt text so any edit changes it.
- **21–22** An artifact's id is a hash of everything that determines its content: document, schema, prompt, model, decoding mode and pipeline version. Same inputs → same id → cache hit; any change → a new id, and the old artifact is never touched.

```python
25  def merge(parts: list[Extraction]) -> Extraction:
26      ents = {(e.mention, e.type): e for p in parts for e in p.entities}
27      edges: dict[tuple, Edge] = {}
28      for e in (e for p in parts for e in p.edges):
29          k = (e.src_mention, e.rel, e.dst_mention)  # one edge per triple within a document
30          if k not in edges or e.confidence > edges[k].confidence:
31              edges[k] = e
32      return Extraction(entities=list(ents.values()), edges=list(edges.values()))
```

Combine the chunks' results: unique entities; for edges that overlapping chunks both produced, keep the more confident one.

```python
35  def process(doc_id: str, text: str, adapter: Adapter, force: bool = False) -> Artifact:
36      xid = extraction_id(doc_id, adapter.model_id)
37      if store.exists(xid) and not force:
38          return store.load(xid)
39      parts, errors = [], []
40      head = text[:HEAD]
41      for ch in split(text):
42          anc = anchors_for(ch.text)
43          anc.dates |= anchors_for(head).dates  # declaration dates live in the head; ZIPs and bills must be in the chunk
44          prompt = PROMPT.format(anchors=anc.for_prompt(), head=head, chunk=ch.text)
45          ok, errs = validate(Extraction.model_validate(adapter.structured(prompt, SCHEMA)), ch.text, anc)
46          parts.append(ok)
47          if errs:  # keep the first pass's valid edges; the retry only needs to recover the rejected ones
48              retry = prompt + "\n\nThese edges were rejected; re-emit only corrected versions of them:\n" + "\n".join(errs)
49              ok, errs = validate(Extraction.model_validate(adapter.structured(retry, SCHEMA)), ch.text, anc)
50              parts.append(ok)
51          errors += errs
52      merged = expand(merge(parts), anchors_for(text).zip_blocks)
53      status = "ok" if merged.edges else "failed_validation" if errors else "no_target_relations"
54      return Artifact(**merged.model_dump(), extraction_id=xid, doc_id=doc_id, schema_v=SCHEMA_V, prompt_v=PROMPT_V,
                      model_id=adapter.model_id, status=status, rejected=errors)
```

The per-document pipeline:

- **36–38** Cache check by extraction id.
- **40–44** For each chunk: compute anchors (ZIPs and bills from the chunk, dates also from the document head), fill the prompt template.
- **45–51** Call the model, validate; if anything was rejected, call once more with the rejection reasons appended, asking only for corrected versions; keep everything valid from both passes; remember the final rejections.
- **52** Merge the chunks and run the ZIP-block expansion over the whole document.
- **53–54** Status and artifact.

```python
66  def main() -> None:
67      adapter = build(MODEL_ID)
68      store.requeue_running()
69      while True:
70          if (job := store.claim()) is None:
71              time.sleep(1)
72              continue
73          run_id, doc_id, _, text, force = job
74          try:
75              store.complete(run_id, doc_id, process(doc_id, text, adapter, force), overwrite=force)
76          except Exception as e:  # a bad document must not stop the queue; the manifest reports it
77              store.fail(run_id, doc_id, f"{type(e).__name__}: {e}")
78              print(f"error {doc_id[:12]}: {type(e).__name__}: {e}", flush=True)
```

The worker loop: requeue anything a previous worker abandoned, then forever claim a job, process it, store the result; any exception marks that job as an error and the loop continues.

### 5.10 `api.py`

Five endpoints on a FastAPI app: `POST /v1/runs` creates a run id; `POST /v1/jobs` enqueues a job; `GET /v1/manifests/{run_id}` reports progress and the artifact ids; `GET /v1/extractions/{id}` returns an artifact; `POST /v1/resolve` runs the embedding and judge steps synchronously for a batch of mentions and returns the resolutions. FastAPI validates every request body against the Pydantic models.

### 5.11 The prompt (`prompts/v2.md`) and schema (`schema/v1.json`)

The prompt states the rules the validators enforce (verbatim spans, anchored ZIPs and dates, closed relation set, one edge per triple), the special rules for bulletins (one TRIGGERED, one ISSUED and one PROTECTED_BY per ZIP for each fire; PROTECTED_BY points at the moratorium, never the fire), for press releases (the Commissioner ISSUED what the release announces; a request is FILED; a ruling or settlement is DECIDED with an outcome) and the mention conventions the resolver keys on. Then it includes the document head, the anchors and the chunk. Everything in braces is filled by `PROMPT.format(...)`; literal braces in the examples are doubled (`{{ }}`) so `format` leaves them alone.

The schema is the JSON shape the API forces the model to produce: an `entities` array and an `edges` array with exactly the fields the Pydantic models expect, enumerated types and relations, and `additionalProperties: false` so nothing extra sneaks in.

### 5.12 `eval/__init__.py` — scoring against the golden set

```python
12  def keys(x: Extraction) -> set[tuple]:
13      return {(e.src_mention.strip().lower(), e.rel, e.dst_mention.strip().lower()) for e in x.edges}
20  def main() -> None:
21      adapter = build(MODEL_ID)
22      total, by_rel = Counter(), {}
23      for case in sorted(GOLDEN.glob("*.json")):
24          g = json.loads(case.read_text())
25          art = process(g["doc_id"], g["text"], adapter)
26          pred, gold = keys(art), keys(Extraction.model_validate(g["expected"]))
27          c = Counter(tp=len(pred & gold), fp=len(pred - gold), fn=len(gold - pred))
```

Each golden file holds a document's text and the hand-labelled expected edges. The eval runs the worker's `process` (cache hits are free), reduces both sides to sets of (source, relation, target) triples, and counts true positives (in both), false positives (predicted only) and false negatives (expected only). It prints precision and recall per document, per relation, and overall, plus the first few misses so a reviewer can see what kind they are.
