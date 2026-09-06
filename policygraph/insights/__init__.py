import duckdb

from policygraph import GRAPH_DB, INSIGHTS
from policygraph.insights import (
    actor_centrality,
    events,
    evidence,
    explorer,
    fair_mirror,
    geometry,
    hazard_residual,
    moratorium_deferral,
    regulatory_alignment,
    trend,
)

MODULES = (
    hazard_residual,
    moratorium_deferral,
    regulatory_alignment,
    fair_mirror,
    actor_centrality,
    evidence,
    events,
    trend,
    explorer,
)


def run() -> None:
    INSIGHTS.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(GRAPH_DB), read_only=True) as con:
        for m in MODULES:
            m.compute(con).to_parquet(INSIGHTS / f"{m.__name__.rsplit('.', 1)[-1]}.parquet", index=False)
        geometry.write(con, INSIGHTS / "cc_zips.geojson")
