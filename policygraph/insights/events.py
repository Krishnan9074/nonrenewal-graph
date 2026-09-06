import duckdb
import pandas as pd

# One row per dated thing that happened: a fire's emergency declaration, a moratorium issued, a regulation issued,
# a rate filing made or decided. Fires share their moratorium's declaration date (Ins. Code 675.1).
SQL = """
SELECT CASE WHEN rel='TRIGGERED' THEN 'fire' WHEN rel='ISSUED' AND dst LIKE 'moratorium:%' THEN 'moratorium'
            WHEN rel IN ('ISSUED','AUTHORED') THEN 'regulation' WHEN rel='FILED' THEN 'rate_filing'
            ELSE 'rate_decision' END AS kind,
       rel, e.src, e.dst, coalesce(s.canonical_name, e.src) AS src_name, coalesce(t.canonical_name, e.dst) AS dst_name,
       e.valid_from AS date, e.valid_to, e.props, e.span, e.confidence, d.url,
       (SELECT count(*) FROM edges p JOIN entities z ON z.entity_id = p.src
        WHERE p.rel='PROTECTED_BY' AND p.dst = e.dst AND json_extract_string(z.attrs,'$.county') = ?) AS cc_zips
FROM edges e JOIN documents d USING (doc_id)
LEFT JOIN entities s ON s.entity_id = e.src LEFT JOIN entities t ON t.entity_id = e.dst
WHERE e.rel IN ('TRIGGERED','ISSUED','FILED','DECIDED','AUTHORED') AND e.valid_from IS NOT NULL
ORDER BY e.valid_from, kind, e.dst
"""


def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
    return con.execute(SQL, [county]).df()
