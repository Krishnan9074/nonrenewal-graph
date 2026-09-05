import pandas as pd
import streamlit as st

from policygraph import DOCS, INSIGHTS

COUNTY = "Contra Costa"

st.set_page_config(page_title="policygraph", layout="wide")
st.title("Home-insurance non-renewals · Contra Costa County")

residual, deferral, fair, evidence = (
    pd.read_parquet(INSIGHTS / f"{n}.parquet") for n in ("hazard_residual", "moratorium_deferral", "fair_mirror", "evidence")
)
tabs = st.tabs(["Findings", "Hazard residual", "Moratorium deferral", "FAIR Plan mirror", "Evidence"])

with tabs[0]:
    st.markdown((DOCS / "FINDINGS.md").read_text())

with tabs[1]:
    measure = st.radio("Measure", sorted(residual.measure.unique()), horizontal=True)
    residual = residual[residual.measure == measure]
    year, r2 = int(residual.year.iloc[0]), float(residual.r2.iloc[0])
    st.caption(f"{year} non-renewal rate above what Very High + High hazard share predicts (OLS across CA ZIPs, R² {r2:.2f}).")
    ranked = residual.reset_index(drop=True).assign(rank_ca=lambda d: d.index + 1)
    cc = ranked[ranked.county == COUNTY]
    st.dataframe(cc[["zip", "rate", "very_high", "high", "predicted", "residual", "policies", "rank_ca"]], width="stretch")
    chart = residual.assign(county=residual.county.where(residual.county == COUNTY, "other CA"))
    st.scatter_chart(chart, x="very_high", y="rate", color="county", size="policies")

with tabs[2]:
    st.caption("Insurer non-renewals one year before, during, and after a ZIP's moratorium year versus all other CA ZIPs.")
    st.info(f"No CDI moratorium bulletin has ever covered a {COUNTY} ZIP. Protected ZIPs are in LA, Mendocino and Del Norte.")
    st.dataframe(deferral.sort_values(["moratorium", "grp"]), width="stretch")

with tabs[3]:
    st.caption("FAIR Plan policies in force (9/30 of fiscal year) alongside voluntary-market non-renewals, by ZIP-year.")
    st.dataframe(fair[fair.county == COUNTY].sort_values(["zip", "y"]), width="stretch")
    st.line_chart(fair[fair.county == COUNTY].pivot(index="y", columns="zip", values="fair"))

with tabs[4]:
    st.caption("Every LLM-extracted edge with its verbatim span. Deterministic edges carry their source in props.")
    st.dataframe(evidence, width="stretch")
