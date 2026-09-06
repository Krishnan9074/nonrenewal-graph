import duckdb
import pandas as pd

# The graph explorer's edge list: every LLM edge, plus the county ZIPs' deterministic edges collapsed to their
# latest year per release so a ZIP node shows one number, not one edge per year.
SQL = """
WITH cc AS (SELECT entity_id FROM entities WHERE json_extract_string(attrs,'$.county') = ?),
det AS (
  SELECT e.*, row_number() OVER (PARTITION BY src, rel, dst, extractor ORDER BY valid_from DESC) AS rn
  FROM edges e WHERE doc_id IS NULL AND (src IN (SELECT entity_id FROM cc) OR dst IN (SELECT entity_id FROM cc)))
SELECT e.src, e.rel, e.dst, e.valid_from, e.valid_to, e.props, e.span, e.extractor, e.confidence, d.url,
       s.type AS src_type, t.type AS dst_type, s.canonical_name AS src_name, t.canonical_name AS dst_name,
       json_extract_string(s.attrs,'$.county') AS src_county, json_extract_string(t.attrs,'$.county') AS dst_county
FROM (SELECT * FROM edges WHERE doc_id IS NOT NULL UNION ALL SELECT * EXCLUDE (rn) FROM det WHERE rn = 1) e
LEFT JOIN documents d USING (doc_id) JOIN entities s ON s.entity_id = e.src JOIN entities t ON t.entity_id = e.dst
ORDER BY e.rel, e.src, e.dst
"""


def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
    return con.execute(SQL, [county]).df()
