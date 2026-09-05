from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG, DATA, DOCS = ROOT / "config", ROOT / "data", ROOT / "docs"
RAW, NORMALIZED, EXTRACTIONS, INSIGHTS = (DATA / d for d in ("raw", "normalized", "extractions", "insights"))
GRAPH_DB = DATA / "graph.duckdb"
COUNTY_FIPS = "06013"
