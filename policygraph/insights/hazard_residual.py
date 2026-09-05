import duckdb
import pandas as pd
import statsmodels.api as sm

# Insurer-initiated non-renewals are the cleaner signal, but CDI stopped publishing the split after 2021.
FITS = (
    (2021, "2015-2021", "nonrenewed_insurer"),
    (2023, "2020-2023", "count"),
)

SQL = """
WITH nr AS (
  SELECT dst AS zip, json_extract(props, ?)::INT AS n, json_extract(props,'$.policies')::INT AS p
  FROM edges WHERE rel='NONRENEWED_IN' AND year(valid_from)=? AND json_extract_string(props,'$.release')=?),
haz AS (
  SELECT src AS zip,
         max(CASE WHEN dst='fhsz:very_high' THEN json_extract(props,'$.pct')::DOUBLE END) AS very_high,
         max(CASE WHEN dst='fhsz:high' THEN json_extract(props,'$.pct')::DOUBLE END) AS high
  FROM edges WHERE rel='HAZARD_SHARE' GROUP BY 1)
SELECT substr(nr.zip, 5) AS zip, json_extract_string(e.attrs,'$.county') AS county, sum(n)::DOUBLE/sum(p) AS rate,
       coalesce(any_value(haz.very_high),0) AS very_high, coalesce(any_value(haz.high),0) AS high, sum(p) AS policies
FROM nr LEFT JOIN haz USING (zip) JOIN entities e ON e.entity_id = nr.zip
GROUP BY 1,2 HAVING sum(p) > 50 AND sum(n) IS NOT NULL
"""


def fit(con: duckdb.DuckDBPyConnection, year: int, release: str, measure: str) -> pd.DataFrame:
    df = con.execute(SQL, [f"$.{measure}", year, release]).df()
    x = sm.add_constant(df[["very_high", "high"]])
    ols = sm.OLS(df.rate, x).fit()
    df["predicted"] = ols.predict(x)
    df["residual"] = df.rate - df.predicted
    return df.assign(year=year, release=release, measure=measure, r2=ols.rsquared).sort_values("residual", ascending=False)


def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return pd.concat([fit(con, *f) for f in FITS], ignore_index=True)
