import json
import re

import duckdb
import pandas as pd

from policygraph import CONFIG, EXTRACTIONS, GRAPH_DB, NORMALIZED
from policygraph.util import load_yaml, stable_id

COLS = ["src", "rel", "dst", "valid_from", "valid_to", "props", "doc_id", "span", "extractor", "confidence"]
MARKET = "market:ca:voluntary"  # CDI publishes ZIP totals only; no insurer identity is in the public data
MORATORIUM_RE = re.compile(r"^moratorium:(\d{4}-\d{2}-\d{2}):")


def _year(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str) + "-01-01")


def _props(df: pd.DataFrame) -> list[str]:
    return [json.dumps({k: (None if pd.isna(v) else v) for k, v in r.items()}) for r in df.to_dict("records")]


def deterministic_edges(nr: pd.DataFrame, haz: pd.DataFrame, fair: pd.DataFrame) -> pd.DataFrame:
    haz_long = haz.melt("zip", var_name="haz", value_name="pct")
    nr_props = nr[["nonrenewed", "nonrenewed_insurer", "nonrenewed_insured", "new", "renewed", "policies", "release"]]
    frames = [
        pd.DataFrame(
            {
                "src": MARKET,
                "rel": "NONRENEWED_IN",
                "dst": "zip:" + nr.zip,
                "valid_from": _year(nr.year),
                "props": _props(nr_props.rename(columns={"nonrenewed": "count"})),
                "extractor": "deterministic:cdi_nonrenewal:" + nr.release,  # releases overlap 2020-21 and disagree
            }
        ),
        pd.DataFrame(
            {
                "src": "zip:" + haz_long.zip,
                "rel": "HAZARD_SHARE",
                "dst": "fhsz:" + haz_long.haz,
                "props": _props(haz_long[["pct"]]),
                "extractor": "deterministic:fhsz_v1",
            }
        ),
        pd.DataFrame(
            {
                "src": "zip:" + fair.zip,
                "rel": "HAS_FAIR_PLAN_POLICIES",
                "dst": "insurer:fairplan",
                "valid_from": _year(fair.year),
                "props": _props(fair[["fair_policies"]].rename(columns={"fair_policies": "count"})),
                "extractor": "deterministic:cdi_fair_v1",
            }
        ),
    ]
    return pd.concat(frames, ignore_index=True).assign(confidence=1.0).reindex(columns=COLS)


def window(edge: dict, dst: str) -> tuple[str | None, str | None]:
    """A moratorium runs one year from the declaration date (Ins. Code 675.1(b)(1)); the date is in its canonical id."""
    if edge["valid_from"] or not (m := MORATORIUM_RE.match(dst)):
        return edge["valid_from"], edge["valid_to"]
    start = pd.Timestamp(m.group(1))
    return str(start.date()), str((start + pd.DateOffset(years=1)).date())


def llm_edges(manifest: dict, resolved: dict[str, str]) -> pd.DataFrame:
    rows = []
    for xid in manifest["extractions"]:
        art = json.loads((EXTRACTIONS / f"{xid}.json").read_text())
        rows += [
            {
                "src": resolved[e["src_mention"]],
                "rel": e["rel"],
                "dst": resolved[e["dst_mention"]],
                "valid_from": window(e, resolved[e["dst_mention"]])[0],
                "valid_to": window(e, resolved[e["dst_mention"]])[1],
                "props": json.dumps(e["props"]),
                "doc_id": art["doc_id"],
                "span": e["span"],
                "extractor": f"llm:{art['model_id']}",
                "confidence": e["confidence"],
            }
            for e in art["edges"]
        ]
    return pd.DataFrame(rows, columns=COLS)


def entities_from(edges: pd.DataFrame, county_by_zip: dict[str, str]) -> pd.DataFrame:
    ids = pd.Series(pd.unique(pd.concat([edges.src, edges.dst])))
    attrs = [json.dumps({"county": county_by_zip[i[4:]]}) if i[4:] in county_by_zip else None for i in ids]
    return pd.DataFrame({"entity_id": ids, "type": ids.str.split(":").str[0], "canonical_name": ids, "attrs": attrs})


def run() -> None:
    nr, haz, fair, docs = (
        pd.read_parquet(NORMALIZED / f"{n}.parquet") for n in ("cdi_nonrenewal", "hazard_share", "cdi_fair_plan", "documents")
    )
    resolved = pd.read_parquet(NORMALIZED / "resolved.parquet").set_index("mention").entity_id.to_dict()
    edges = pd.concat([deterministic_edges(nr, haz, fair), llm_edges(load_yaml(CONFIG / "extraction_manifest.yaml"), resolved)])
    key = edges[["src", "rel", "dst", "valid_from", "doc_id", "extractor"]]
    edges["edge_id"] = [stable_id(*r) for r in key.itertuples(index=False)]
    ents = entities_from(edges, nr.dropna(subset=["county"]).drop_duplicates("zip").set_index("zip").county.to_dict())
    with duckdb.connect(str(GRAPH_DB)) as con:
        con.execute((CONFIG / "schema.sql").read_text())
        for table, df in (("documents", docs), ("entities", ents), ("edges", edges)):
            con.register(f"new_{table}", df)  # a bare DataFrame name would resolve to the table itself
            con.execute(f"INSERT OR IGNORE INTO {table} BY NAME SELECT * FROM new_{table}")
