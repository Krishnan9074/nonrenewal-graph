import duckdb

from policygraph import GRAPH_DB, INSIGHTS
from policygraph.insights import evidence, fair_mirror, hazard_residual, moratorium_deferral

MODULES = (hazard_residual, moratorium_deferral, fair_mirror, evidence)


def run() -> None:
    INSIGHTS.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(GRAPH_DB), read_only=True) as con:
        for m in MODULES:
            m.compute(con).to_parquet(INSIGHTS / f"{m.__name__.rsplit('.', 1)[-1]}.parquet", index=False)
