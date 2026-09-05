import hashlib
import json
import os
import time

from extraction_service import PROMPT_DIR, SCHEMA_DIR, store
from extraction_service.adapters import Adapter, build
from extraction_service.anchors import extract as anchors_for
from extraction_service.chunk import split
from extraction_service.models import Artifact, Edge, Extraction
from extraction_service.validators import validate

MODEL_ID = os.environ.get("EXTRACTION_MODEL", "accounts/fireworks/models/gpt-oss-120b")
SCHEMA_V, PIPELINE_V = "1.0", "0.1.0"
PROMPT = (PROMPT_DIR / "v1.md").read_text()
PROMPT_V = hashlib.sha256(PROMPT.encode()).hexdigest()[:12]
SCHEMA = json.loads((SCHEMA_DIR / "v1.json").read_text())


def extraction_id(doc_id: str, model_id: str) -> str:
    return hashlib.sha256("|".join((doc_id, SCHEMA_V, PROMPT_V, model_id, "adaptive", PIPELINE_V)).encode()).hexdigest()


def merge(parts: list[Extraction]) -> Extraction:
    ents = {(e.mention, e.type): e for p in parts for e in p.entities}
    edges: dict[tuple, Edge] = {}
    for e in (e for p in parts for e in p.edges):
        k = (e.src_mention, e.rel, e.dst_mention, e.valid_from)
        if k not in edges or e.confidence > edges[k].confidence:
            edges[k] = e
    return Extraction(entities=list(ents.values()), edges=list(edges.values()))


def process(doc_id: str, text: str, adapter: Adapter) -> Artifact:
    xid = extraction_id(doc_id, adapter.model_id)
    if store.exists(xid):
        return store.load(xid)
    parts, errors = [], []
    for ch in split(text):
        anc = anchors_for(ch.text)
        prompt = PROMPT.format(anchors=anc.model_dump_json(), chunk=ch.text)
        ok, errs = validate(adapter.extract(prompt, SCHEMA), ch.text, anc)
        parts.append(ok)
        if errs:  # keep the first pass's valid edges; the retry only needs to recover the rejected ones
            retry = prompt + "\n\nThese edges were rejected; re-emit only corrected versions of them:\n" + "\n".join(errs)
            ok, errs = validate(adapter.extract(retry, SCHEMA), ch.text, anc)
            parts.append(ok)
        errors += errs
    merged = merge(parts)
    status = "ok" if merged.edges else "failed_validation" if errors else "no_target_relations"
    return Artifact(
        **merged.model_dump(),
        extraction_id=xid,
        doc_id=doc_id,
        schema_v=SCHEMA_V,
        prompt_v=PROMPT_V,
        model_id=adapter.model_id,
        status=status,
        rejected=errors,
    )


def main() -> None:
    adapter = build(MODEL_ID)
    while True:
        if (job := store.claim()) is None:
            time.sleep(1)
            continue
        run_id, doc_id, _, text = job
        store.complete(run_id, doc_id, process(doc_id, text, adapter))


if __name__ == "__main__":
    main()
