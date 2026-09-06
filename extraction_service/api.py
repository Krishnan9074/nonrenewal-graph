import uuid

from fastapi import FastAPI

from extraction_service import resolve as resolver
from extraction_service import store
from extraction_service.adapters import build
from extraction_service.embed import Embedder
from extraction_service.models import Job, ResolveRequest
from extraction_service.worker import MODEL_ID

app = FastAPI(title="extraction-service")


@app.post("/v1/runs")
def create_run(body: dict) -> dict:
    run_id = uuid.uuid4().hex[:12]
    store.create_run(run_id, body["schema_v"])
    return {"run_id": run_id}


@app.post("/v1/jobs")
def submit(job: Job) -> dict:
    store.enqueue(job.run_id, job.doc_id, job.source, job.text, job.force)
    return {"queued": True}


@app.get("/v1/manifests/{run_id}")
def manifest(run_id: str) -> dict:
    return store.manifest(run_id)


@app.get("/v1/extractions/{extraction_id}")
def extraction(extraction_id: str) -> dict:
    return store.load(extraction_id).model_dump(mode="json")


@app.post("/v1/resolve")
def resolve(req: ResolveRequest) -> list[dict]:
    """Synchronous: a resolve request is a few dozen short strings, not a document."""
    embedder, judge = Embedder(), build(MODEL_ID)
    out = resolver.resolve(req.mentions, req.candidates, embedder.embed, judge.structured, (embedder.model_id, judge.model_id))
    return [r.model_dump(mode="json") for r in out]
