import duckdb
import pandas as pd

# Insurer-initiated non-renewals (what a moratorium restricts) in protected ZIPs versus every other ZIP in the same
# release, one year before, during, and after the moratorium year.
SQL = """
WITH prot AS (SELECT DISTINCT src AS zip, dst AS moratorium, year(valid_from) AS y0 FROM edges WHERE rel='PROTECTED_BY'),
nr AS (SELECT dst AS zip, year(valid_from) AS y, json_extract(props,'$.nonrenewed_insurer')::INT AS n
       FROM edges WHERE rel='NONRENEWED_IN' AND json_extract_string(props,'$.release')=?),
win AS (SELECT p.zip, p.moratorium, p.y0, nr.y, nr.n FROM prot p JOIN nr USING (zip) WHERE nr.y BETWEEN p.y0-1 AND p.y0+1),
ctrl AS (SELECT m.moratorium, m.y0, nr.y, sum(nr.n) AS n
         FROM (SELECT DISTINCT moratorium, y0 FROM prot) m
         JOIN nr ON nr.y BETWEEN m.y0-1 AND m.y0+1 AND nr.zip NOT IN (SELECT zip FROM prot)
         GROUP BY 1,2,3)
SELECT 'protected' AS grp, substr(zip, 5) AS zip, moratorium, y0,
  max(CASE WHEN y=y0-1 THEN n END) AS before, max(CASE WHEN y=y0 THEN n END) AS during, max(CASE WHEN y=y0+1 THEN n END) AS after
FROM win GROUP BY 1,2,3,4
UNION ALL
SELECT 'control', 'all other CA ZIPs', moratorium, y0,
  max(CASE WHEN y=y0-1 THEN n END), max(CASE WHEN y=y0 THEN n END), max(CASE WHEN y=y0+1 THEN n END)
FROM ctrl GROUP BY 1,2,3,4
"""


def compute(con: duckdb.DuckDBPyConnection, release: str = "2015-2021") -> pd.DataFrame:
    df = con.execute(SQL, [release]).df()
    before = df["before"].replace(0, pd.NA)
    return df.assign(during_ratio=df["during"] / before, after_ratio=df["after"] / before, release=release)
