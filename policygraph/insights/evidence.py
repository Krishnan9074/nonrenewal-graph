import duckdb
import pandas as pd

# Every LLM edge with its verbatim span and source document, so the app can show receipts without the graph file.
SQL = """
SELECT e.src, e.rel, e.dst, e.valid_from, e.valid_to, e.confidence, e.extractor, e.span, d.url, d.published_at
FROM edges e JOIN documents d USING (doc_id)
ORDER BY d.published_at, e.rel, e.src
"""


def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(SQL).df()
