import os
import time

import httpx
import pandas as pd

from policygraph import CONFIG, NORMALIZED
from policygraph.util import dump_yaml

SERVICE = os.environ.get("EXTRACTION_SERVICE_URL", "http://localhost:8000")


def run(schema_v: str = "1.0", force: bool = False) -> None:
    """force re-runs the model even for documents whose extraction id already has an artifact."""
    docs = pd.read_parquet(NORMALIZED / "documents.parquet")
    with httpx.Client(base_url=SERVICE, timeout=60) as c:
        run_id = c.post("/v1/runs", json={"schema_v": schema_v}).json()["run_id"]
        for d in docs.itertuples():
            body = {"run_id": run_id, "doc_id": d.doc_id, "source": d.source, "text": d.text, "force": force}
            c.post("/v1/jobs", json=body).raise_for_status()
        while (m := c.get(f"/v1/manifests/{run_id}").json())["status"] != "complete":
            time.sleep(2)
    dump_yaml(CONFIG / "extraction_manifest.yaml", m)
    if m["failed"] or m["errors"]:
        raise RuntimeError(f"extraction run {run_id}: failed={m['failed']} errors={m['errors']}")
