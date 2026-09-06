from pathlib import Path

import pandas as pd

from policygraph.resolve import resolve_all
from policygraph.util import load_yaml

ROOT = Path(__file__).parent.parent
SET = load_yaml(ROOT / "tests" / "resolution_set.yaml")


def test_resolution_regression_set():
    entities = load_yaml(ROOT / "config" / "entities.yaml")["entities"]
    pinned = ROOT / "config" / "resolutions.yaml"
    pins = {(p["mention"], p["type"]): p for p in (load_yaml(pinned) if pinned.exists() else [])}
    mentions = pd.DataFrame([{"mention": c["mention"], "type": c["type"], "context": ""} for c in SET])
    got = resolve_all(mentions, entities, pins, ask=None).set_index(["mention", "type"])
    wrong = [
        (c["mention"], c["type"], c["entity_id"], r.entity_id, c["method"], r.method)
        for c in SET
        for r in [got.loc[(c["mention"], c["type"])]]
        if (r.entity_id, r.method) != (c["entity_id"], c["method"])
    ]
    assert len(SET) >= 50 and not wrong, wrong
