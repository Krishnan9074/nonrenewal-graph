import uuid

from fastapi import FastAPI

from extraction_service import store
from extraction_service.models import Job

app = FastAPI(title="extraction-service")


@app.post("/v1/runs")
def create_run(body: dict) -> dict:
    run_id = uuid.uuid4().hex[:12]
    store.create_run(run_id, body["schema_v"])
    return {"run_id": run_id}


@app.post("/v1/jobs")
def submit(job: Job) -> dict:
    store.enqueue(job.run_id, job.doc_id, job.source, job.text)
    return {"queued": True}


@app.get("/v1/manifests/{run_id}")
def manifest(run_id: str) -> dict:
    return store.manifest(run_id)


@app.get("/v1/extractions/{extraction_id}")
def extraction(extraction_id: str) -> dict:
    return store.load(extraction_id).model_dump(mode="json")
