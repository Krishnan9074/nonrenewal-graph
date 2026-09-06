import sqlite3

from extraction_service import STORE
from extraction_service.models import Artifact

DDL = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, schema_v TEXT, created_at TEXT DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS jobs (run_id TEXT, doc_id TEXT, source TEXT, text TEXT, status TEXT,
  extraction_id TEXT, force INTEGER DEFAULT 0, PRIMARY KEY (run_id, doc_id));
"""


def _con() -> sqlite3.Connection:
    STORE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(STORE / "index.sqlite", isolation_level=None)
    con.executescript(DDL)
    if "force" not in {r[1] for r in con.execute("PRAGMA table_info(jobs)")}:  # index created before jobs carried force
        con.execute("ALTER TABLE jobs ADD COLUMN force INTEGER DEFAULT 0")
    return con


def create_run(run_id: str, schema_v: str) -> None:
    _con().execute("INSERT INTO runs (run_id, schema_v) VALUES (?,?)", (run_id, schema_v))


def enqueue(run_id: str, doc_id: str, source: str, text: str, force: bool = False) -> None:
    _con().execute("INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,'queued',NULL,?)", (run_id, doc_id, source, text, int(force)))


def requeue_running() -> int:
    """Jobs left 'running' by a worker that died; the single-worker prototype has no lease to check."""
    return _con().execute("UPDATE jobs SET status='queued' WHERE status='running'").rowcount


def fail(run_id: str, doc_id: str, error: str) -> None:
    _con().execute("UPDATE jobs SET status='error', extraction_id=? WHERE run_id=? AND doc_id=?", (error[:500], run_id, doc_id))


def claim() -> tuple[str, str, str, str, bool] | None:
    con = _con()
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT run_id, doc_id, source, text, force FROM jobs WHERE status='queued' LIMIT 1").fetchone()
    if row:
        con.execute("UPDATE jobs SET status='running' WHERE run_id=? AND doc_id=?", row[:2])
    con.execute("COMMIT")
    return (*row[:4], bool(row[4])) if row else None


def complete(run_id: str, doc_id: str, art: Artifact, overwrite: bool = False) -> None:
    path = STORE / f"{art.extraction_id}.json"
    if overwrite or not path.exists():
        path.write_text(art.model_dump_json(indent=1))
    _con().execute(
        "UPDATE jobs SET status=?, extraction_id=? WHERE run_id=? AND doc_id=?",
        (art.status, art.extraction_id, run_id, doc_id),
    )


def manifest(run_id: str) -> dict:
    con = _con()
    schema_v = con.execute("SELECT schema_v FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
    rows = con.execute("SELECT status, extraction_id FROM jobs WHERE run_id=?", (run_id,)).fetchall()
    pending = any(s in ("queued", "running") for s, _ in rows)
    return {
        "run_id": run_id,
        "schema_v": schema_v,
        "status": "running" if pending else "complete",
        "extractions": [x for s, x in rows if s == "ok"],
        "failed": [x for s, x in rows if s == "failed_validation"],
        "errors": [x for s, x in rows if s == "error"],
    }


def exists(extraction_id: str) -> bool:
    return (STORE / f"{extraction_id}.json").exists()


def load(extraction_id: str) -> Artifact:
    return Artifact.model_validate_json((STORE / f"{extraction_id}.json").read_text())
