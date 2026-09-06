import duckdb
import pandas as pd

# County and statewide rates per release-year; the two CDI releases disagree on 2020-21 and are never summed.
SQL = """
SELECT json_extract_string(props,'$.release') AS release, year(valid_from) AS y,
       CASE WHEN json_extract_string(e.attrs,'$.county') = ? THEN ? ELSE 'California' END AS scope,
       sum(json_extract(props,'$.count')::INT) AS nonrenewed,
       sum(json_extract(props,'$.nonrenewed_insurer')::INT) AS nonrenewed_insurer,
       sum(json_extract(props,'$.policies')::INT) AS policies
FROM edges JOIN entities e ON e.entity_id = dst WHERE rel='NONRENEWED_IN' GROUP BY 1,2,3
"""


FAIR = """
SELECT 'fair-plan-fy' AS release, year(valid_from) AS y,
       CASE WHEN json_extract_string(e.attrs,'$.county') = ? THEN ? ELSE 'California' END AS scope,
       sum(json_extract(props,'$.count')::INT) AS fair
FROM edges JOIN entities e ON e.entity_id = src WHERE rel='HAS_FAIR_PLAN_POLICIES' GROUP BY 1,2,3
"""


def fair_series(con: duckdb.DuckDBPyConnection, county: str) -> pd.DataFrame:
    """FAIR Plan policies in force at 9/30 of the fiscal year, the only series that reaches the 2024-25 events."""
    df = con.execute(FAIR, [county, county]).df()
    ca = df.groupby(["release", "y"]).fair.sum().reset_index().assign(scope="California")
    return pd.concat([df[df.scope == county], ca], ignore_index=True)


def compute(con: duckdb.DuckDBPyConnection, county: str = "Contra Costa") -> pd.DataFrame:
    df = con.execute(SQL, [county, county]).df()
    ca = (
        df.groupby(["release", "y"])[["nonrenewed", "nonrenewed_insurer", "policies"]]
        .sum()
        .reset_index()
        .assign(scope="California")
    )
    df = pd.concat([df[df.scope == county], ca], ignore_index=True)  # "California" rows above exclude the county
    rates = {"rate": df.nonrenewed / df.policies, "rate_insurer": df.nonrenewed_insurer / df.policies}
    return pd.concat([df.assign(**rates), fair_series(con, county)], ignore_index=True).sort_values(["scope", "release", "y"])
