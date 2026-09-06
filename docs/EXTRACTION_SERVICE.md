# Extraction Service — Design

**A separately deployed system that turns prose documents into versioned, validated, replayable structured extractions.**
The graph pipeline (see `ARCHITECTURE.md`) is a *consumer* of this service. It depends only on the extraction schema contract, never on which model produced the output.

---

## 1. Why a separate system

Calling an LLM inline from the graph pipeline fails on three axes:

| Problem | Inline LLM call | Extraction service |
|---|---|---|
| Reproducibility | Output depends on model version, prompt text, sampling, provider behavior at call time — none of it captured | Every output is an immutable artifact keyed by `(doc_hash, schema_v, prompt_v, model_id, decode_params)`; consumers pin a manifest, like a lockfile |
| Scalability | Pipeline throughput bounded by API rate limits and cost; retries entangled with graph logic | Queue + stateless workers + batch backfill; cost budgets and priority lanes per source |
| Quality control | No way to know if a prompt change made things worse | Golden set, shadow runs, promotion gates; model/prompt changes are releases |

**Honest framing of "reproducible":** hosted frontier models are not bit-deterministic even at temperature 0. The service therefore guarantees *replayability* (stored artifacts are immutable and versioned) and offers a *deterministic tier* (self-hosted open-weight model, pinned weights, greedy decoding) for runs that must reproduce exactly. The graph never re-derives an extraction implicitly; it reads a pinned version.

## 2. Service boundary and contract

```
                        ┌──────────────────────────────────────────────────┐
  graph pipeline ─────► │  POST /v1/runs  {schema_v}                        │
  (producer)            │  POST /v1/jobs  {run_id, doc_id, source, text, force}
                        │  GET  /v1/extractions/{extraction_id}             │
                        │  GET  /v1/manifests/{run_id}                      │
                        │  POST /v1/resolve {mentions, candidates}  (sync)  │
                        └──────────────────────────────────────────────────┘
                                          │
                                          ▼
   documents store ───► queue ───► workers ───► extraction store ───► outbox/topic ───► graph pipeline (consumer)
```

**Contract = the extraction schema, versioned.** `extraction_schema/v1.json` defines entity types, the closed relation vocabulary, and the edge shape (`src_mention, rel, dst_mention, valid_from, valid_to, span, confidence`). Consumers pin `schema_v`. Adding a relation is a minor version; changing an existing field is a major version and a new topic.

**Extraction identity**

```
extraction_id = sha256(doc_hash ‖ schema_v ‖ prompt_v ‖ model_id ‖ decode_params ‖ pipeline_v)
```

Same inputs → same id → cache hit, no compute. Any change to any component → new id, old artifact untouched.

**Run manifest** (what the graph pipeline pins):

```yaml
run_id: 2026-09-04T18:00Z-cdi-backfill
schema_v: 1.2
prompt_v: 7            # sha256 of prompt template + few-shot examples
model_id: <provider snapshot id>   # never an alias
decode: {temperature: 0, max_tokens: 4096, seed: 0}
pipeline_v: 0.4.1
docs: 312
extractions: [<extraction_id>, ...]
eval: {golden_precision: 0.94, golden_recall: 0.89, schema_fail_rate: 0.006}
```

`make graph` reads a manifest and loads exactly those extraction ids. Rebuilding the graph a year from now with the same manifest produces the same graph.

## 3. Worker pipeline (per document)

```
doc ─► 1 dedup ─► 2 classify ─► 3 chunk ─► 4 deterministic pre-extract ─► 5 LLM residual extract
                                                                                   │
        9 write artifact + emit ◄── 8 score ◄── 7 reconcile ◄── 6 validate ◄───────┘
```

1. **Dedup** — `doc_hash` already extracted under this identity → return cached, zero cost.
2. **Classify** (small model or heuristic) — does this doc plausibly contain any target relation? Bulletins: always yes. Press releases: ~40% no. Skipped docs are recorded as `{status: "no_target_relations"}` so the decision is auditable.
3. **Chunk** — token-aware, section-boundary-preferring, 10% overlap. Each chunk carries `(doc_id, chunk_idx, char_start, char_end)` so spans resolve back to the document.
4. **Deterministic pre-extraction** — regex/parsers for everything that doesn't need a model: ZIP codes, dates, NAIC codes, bill numbers (`SB 824`, `AB 2996`), dollar amounts, percentages. These become *anchors* the LLM is told about and validators check against.
5. **LLM residual extraction** — structured output (tool-use / JSON mode) against `schema_v`. The prompt receives the chunk, the anchors, and the closed relation vocabulary. It may only reference mentions and dates that appear in the chunk.
6. **Validate** (deterministic, rejects on failure):
   - JSON schema conformance
   - `span` is a verbatim substring of the chunk (whitespace/case-normalized)
   - `rel` ∈ closed vocabulary; `src.type` / `dst.type` allowed for that `rel`
   - every ZIP / date / bill number in the output ∈ pre-extraction anchors
   - `valid_from ≤ valid_to`; dates within `[doc.published_at − 5y, doc.published_at + 2y]`
   One retry with the validation error appended; second failure → `status: "failed_validation"`, doc to DLQ, never silently dropped.
7. **Reconcile** across chunks — merge duplicate edges from overlapping chunks; keep the highest-confidence span.
8. **Score** — final confidence = model confidence × validator pass ratio × source prior (bulletins 1.0, press 0.85, news 0.6).
9. **Write + emit** — artifact to the extraction store (object storage, path = `extraction_id`), row to the index table, event to the outbox. Consumers read from the outbox; the service never writes to the graph.

Design consequence: the LLM is boxed in on both sides — deterministic anchors going in, deterministic validators coming out. Its job shrinks to "which anchors relate to which, and how." That is the part that scales and the part that is testable.

## 4. Model portability and tiers

| Tier | Model | Use | Reproducibility |
|---|---|---|---|
| Quality | Hosted frontier (pinned snapshot) | Ambiguous docs, low-volume high-value sources, golden-set labeling | Replayable via stored artifacts |
| Throughput | Hosted small model or batch API | Backfills, classification (step 2) | Replayable |
| Deterministic | Self-hosted open-weight, pinned weights, greedy | Regulatory/legal audits; regression baselines | Bit-reproducible on same hardware/software stack |
| Distilled | Fine-tuned small model on accepted extractions | Once ≥ 5k validated extractions exist | Bit-reproducible; owned |

A provider adapter interface (`extract(chunk, schema, anchors) → json`) keeps the pipeline model-agnostic. Routing is by `source` and `classify` output, configured per run, recorded in the manifest.

## 5. Release process for prompts and models

Prompt and model changes are deployments, not edits.

1. Change lands as a new `prompt_v` (content-hashed) or `model_id`.
2. **CI eval**: run on the golden set (≥ 100 hand-labeled docs across sources). Report precision/recall per relation type and schema-failure rate. Block merge below thresholds (p ≥ 0.90, r ≥ 0.85, fail ≤ 1%).
3. **Shadow run**: new version extracts 10% of live traffic alongside current; diff edge sets; surface docs where they disagree for review.
4. **Promote**: new manifest becomes default for new jobs. Old artifacts stay; consumers migrate by pinning the new manifest when they choose.
5. **Rollback** = pin the previous manifest. Nothing to recompute.

## 6. Scaling

| Concern | Mechanism |
|---|---|
| Throughput | Queue (SQS / Redis Streams); stateless workers autoscale on queue depth; batch API for backfills > 1k docs |
| Cost | Per-source token budgets enforced at enqueue; classify step gates the expensive model; cache hit rate tracked (target > 60% on re-runs) |
| Latency | Async by design; priority lanes (`interactive` for user-submitted docs, `bulk` for pollers) |
| Long documents | Chunking with provenance; reconcile step; docs > 200 pages routed to batch tier |
| Provider outages / rate limits | Adapter-level retry with jitter; circuit breaker flips routing to alternate tier; DLQ with replay |
| Storage | Artifacts in object storage keyed by `extraction_id`; index in Postgres; immutable, lifecycle-managed only for superseded shadow runs |
| Multi-tenant / multi-issue | Schema and prompt are per "issue pack"; one service, many packs, isolated budgets |

## 7. Observability

- Per-job trace: doc, chunks, model calls, tokens, latency, validator results, final status.
- Metrics: schema-fail rate, validator-reject rate by rule, confidence histogram, edges-per-doc, cache hit rate, cost per source — all by `prompt_v × model_id`.
- Drift alarms: edges-per-doc or confidence distribution shifting > 2σ from the golden-run baseline for the same source.
- Every graph edge links back to `extraction_id` → full trace.

## 8. Failure modes and how they surface

| Failure | Detected by | Result |
|---|---|---|
| Model hallucinates a ZIP not in the doc | Anchor validator | Edge rejected, logged |
| Span paraphrased instead of quoted | Verbatim check | Confidence zeroed, retry |
| Provider silently updates model behind an alias | Manifest pins snapshot id; drift alarm | New id → new artifacts; old graph unchanged |
| Prompt regression | CI golden eval | Merge blocked |
| Source changes format (PDF → HTML) | Classify + validator reject spike | Alert; parser update; replay from DLQ |

## 8a. Entity resolution endpoint

`POST /v1/resolve` runs steps 3–4 of the resolver (`ARCHITECTURE.md` §7) for mentions the pipeline could not key or
alias: embed mention and `name — description` of every same-type candidate (`EMBED_MODEL`, via the OpenAI-compatible
`/embeddings` route), accept a clear cosine winner (≥ 0.92 with a ≥ 0.05 margin), otherwise ask the extraction model
"same entity?" for candidates in the band (≥ 0.75) and accept ≥ 0.85. Each answer is cached under
`resolutions/<sha256(mention, type, context, candidates, models, version)>.json` and records the nearest candidate and
its cosine even when rejected. The pipeline pins every answer in `config/resolutions.yaml`.

## 9. Prototype implementation (today)

Same architecture, smallest deployable shape:

```
extraction_service/
├── api.py            # FastAPI: POST /jobs, GET /extractions, GET /manifests
├── store.py          # SQLite-backed queue + artifact store (swap: Redis/SQS + S3)
├── resolve.py        # kNN + judge (8a); embed.py wraps the embeddings route
├── worker.py         # steps 1–9; run as `python -m extraction_service.worker`
├── adapters/         # anthropic.py, openai_compat.py (vLLM self-hosted)
├── schema/v1.json
├── prompts/v2.md     # content-hashed at load
├── validators.py
├── eval/golden/      # 4 hand-labelled bulletins today, grows
```

- Deploy: one container on Fly.io / Cloud Run, worker as a sidecar process. The worker requeues jobs left `running`
  by a dead worker at startup and records an unhandled exception as job status `error` (surfaced in the manifest and
  turned into a failing `make extract`) rather than stopping the queue.
- Output budget: `EXTRACTION_MAX_TOKENS` (default 100k); a 700-ZIP moratorium bulletin with verbatim spans is ~80k tokens.
- Graph repo pins `manifests/2026-09-04-cdi.yaml` and commits the referenced artifacts, so `make all` runs with no network and no key.
- `make eval` runs the golden set and prints the precision/recall table that goes in the write-up.

## 10. Next

1. Deterministic tier on vLLM with a pinned open-weight model; report agreement rate vs the quality tier on the golden set.
2. Active-learning loop: validator rejects and low-confidence edges feed the review queue; accepted labels grow the golden set and the distillation corpus.
3. Distill a small extractor once the corpus crosses ~5k accepted extractions; move bulk traffic to it.
4. Contract tests that run the consumer (`make graph`) against every published manifest in CI, so schema evolution can't break replay.
