import duckdb
import networkx as nx
import pandas as pd

# Betweenness on the county's neighbourhood: every non-ZIP entity plus the county's ZIPs, other ZIPs dropped so the
# statewide market hub is scored by the county paths it sits on, not by 1,600 ZIPs elsewhere.
SQL = """
SELECT DISTINCT e.src, e.dst, e.rel FROM edges e
JOIN entities s ON s.entity_id = e.src JOIN entities t ON t.entity_id = e.dst
WHERE (s.type <> 'zip' OR json_extract_string(s.attrs,'$.county') = ?)
  AND (t.type <> 'zip' OR json_extract_string(t.attrs,'$.county') = ?)
"""
NAMES = "SELECT entity_id, type, canonical_name FROM entities"


def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
    edges, names = con.execute(SQL, [county, county]).df(), con.execute(NAMES).df().set_index("entity_id")
    g = nx.Graph()
    g.add_edges_from(edges[["src", "dst"]].itertuples(index=False))
    zips = {n for n in g if n.startswith("zip:")}
    bc = nx.betweenness_centrality(g, normalized=True)
    rows = [
        {
            "entity_id": n,
            "type": names.type.get(n),
            "name": names.canonical_name.get(n, n),
            "degree": g.degree(n),
            "betweenness": bc[n],
            "cc_zips_within_2": sum(1 for z in zips if z != n and nx.has_path(g, n, z) and nx.shortest_path_length(g, n, z) <= 2),
            "rels": ", ".join(sorted(set(edges[(edges.src == n) | (edges.dst == n)].rel))),
        }
        for n in g
        if n not in zips
    ]
    return pd.DataFrame(rows).sort_values(["betweenness", "degree"], ascending=False).reset_index(drop=True)
