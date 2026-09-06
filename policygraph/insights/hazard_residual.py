import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

# Insurer-initiated non-renewals are the cleaner signal, but CDI stopped publishing the split after 2021.
FITS = (
    (2021, "2015-2021", "nonrenewed_insurer"),
    (2023, "2020-2023", "count"),
)
# The ACS spec tests the obvious rival to hazard: are expensive-to-insure ZIPs dropped regardless of fire risk?
SPECS = {"hazard": ["very_high", "high"], "hazard+acs": ["very_high", "high", "log_home_value", "log_income"]}

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
       coalesce(any_value(haz.very_high),0) AS very_high, coalesce(any_value(haz.high),0) AS high, sum(p) AS policies,
       any_value(json_extract(e.attrs,'$.median_home_value')::DOUBLE) AS home_value,
       any_value(json_extract(e.attrs,'$.median_income')::DOUBLE) AS income
FROM nr LEFT JOIN haz USING (zip) JOIN entities e ON e.entity_id = nr.zip
GROUP BY 1,2 HAVING sum(p) > 50 AND sum(n) IS NOT NULL
"""


def fit(con: duckdb.DuckDBPyConnection, year: int, release: str, measure: str) -> pd.DataFrame:
    base = con.execute(SQL, [f"$.{measure}", year, release]).df()
    base["log_home_value"], base["log_income"] = np.log(base.home_value), np.log(base.income)
    out = []
    for spec, cols in SPECS.items():
        df = base.dropna(subset=cols).copy()
        x = sm.add_constant(df[cols])
        ols = sm.OLS(df.rate, x).fit()
        df["predicted"] = ols.predict(x)
        df["residual"] = df.rate - df.predicted
        coefs = {f"coef_{c}": ols.params[c] for c in cols} | {f"p_{c}": ols.pvalues[c] for c in cols}
        out.append(df.assign(year=year, release=release, measure=measure, spec=spec, r2=ols.rsquared, n=len(df), **coefs))
    return pd.concat(out).sort_values(["spec", "residual"], ascending=[True, False])


def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return pd.concat([fit(con, *f) for f in FITS], ignore_index=True)
