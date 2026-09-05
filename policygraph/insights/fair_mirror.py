import duckdb
import pandas as pd

# FAIR Plan counts are policies in force at 9/30 of the fiscal year; non-renewals are calendar-year counts.
SQL = """
WITH nr AS (SELECT dst AS zip, year(valid_from) AS y, json_extract(props,'$.count')::INT AS nonrenewed,
                   json_extract(props,'$.policies')::INT AS policies
            FROM edges WHERE rel='NONRENEWED_IN' AND json_extract_string(props,'$.release')=?),
fair AS (SELECT src AS zip, year(valid_from) AS y, json_extract(props,'$.count')::INT AS fair
         FROM edges WHERE rel='HAS_FAIR_PLAN_POLICIES')
SELECT substr(zip, 5) AS zip, json_extract_string(e.attrs,'$.county') AS county, y, nonrenewed, policies, fair,
       fair - lag(fair) OVER (PARTITION BY zip ORDER BY y) AS fair_delta,
       fair::DOUBLE / (fair + policies) AS fair_share
FROM nr JOIN fair USING (zip, y) JOIN entities e ON e.entity_id = zip
"""


def compute(con: duckdb.DuckDBPyConnection, release: str = "2020-2023") -> pd.DataFrame:
    return con.execute(SQL, [release]).df().assign(release=release)
