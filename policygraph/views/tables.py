import altair as alt
import pandas as pd
import streamlit as st

from policygraph.views.data import CAT, COUNTY, load


def hazard() -> None:
    res = load("hazard_residual")
    c1, c2 = st.columns(2)
    measure = c1.radio("Measure", sorted(res.measure.unique()), horizontal=True)
    spec = c2.radio("Regressors", sorted(res.spec.unique()), horizontal=True)
    df = res[(res.measure == measure) & (res.spec == spec)]
    head = df.iloc[0]
    coefs = ", ".join(
        f"{c[5:]} {head[c] * 100:+.2f} pts (p={head['p_' + c[5:]]:.3f})" for c in df.columns if c.startswith("coef_")
    )
    fit = f"OLS of ZIP rate on {spec} across {int(head.n)} CA ZIPs, R² {head.r2:.2f}"
    st.caption(f"{int(head.year)}, release {head.release}: {fit}. {coefs}.")
    ranked = df.reset_index(drop=True).assign(rank_ca=lambda d: d.index + 1)
    cc = ranked[ranked.county == COUNTY]
    cols = ["zip", "rate", "very_high", "high", "home_value", "income", "predicted", "residual", "policies", "rank_ca"]
    st.dataframe(cc[cols], width="stretch")
    chart = df.assign(county=df.county.where(df.county == COUNTY, "other CA"), pct=df.rate * 100)
    scale = alt.Scale(domain=[COUNTY, "other CA"], range=[CAT["blue"], "#c3c2b7"])
    dots = (
        alt.Chart(chart)
        .mark_circle(opacity=0.7)
        .encode(
            x=alt.X("very_high:Q", title="Very High FHSZ area share"),
            y=alt.Y("pct:Q", title="non-renewal rate, %"),
            color=alt.Color("county:N", scale=scale, title=None),
            size=alt.Size("policies:Q", legend=None),
            tooltip=["zip", "county", alt.Tooltip("pct:Q", format=".2f"), alt.Tooltip("very_high:Q", format=".2f"), "policies"],
        )
        .properties(height=340)
    )
    st.altair_chart(dots, width="stretch")


def moratorium() -> None:
    df = load("moratorium_deferral")
    st.caption(
        "Non-renewals in protected ZIPs the year before, during and after their moratorium year (the calendar year holding "
        "most of the 12-month window), against every other CA ZIP and against a control matched on Very High hazard share "
        "and policy count. Each release is shown with the measure it publishes."
    )
    release = st.radio("Release", sorted(df.release.unique()), horizontal=True)
    df = df[df.release == release]
    grp = df[df.grp != "protected"].groupby(["moratorium", "y0", "grp"])[["n_zips", "before", "during", "after"]].sum()
    prot = (
        df[df.grp == "protected"]
        .groupby(["moratorium", "y0"])
        .agg(n_zips=("zip", "count"), before=("before", "sum"), during=("during", "sum"), after=("after", "sum"))
    )
    summary = pd.concat([prot.assign(grp="protected").set_index("grp", append=True), grp]).sort_index()
    summary["during_ratio"], summary["after_ratio"] = summary.during / summary.before, summary.after / summary.before
    st.dataframe(summary, width="stretch")
    st.caption("Per-ZIP rows for protected ZIPs.")
    st.dataframe(df[df.grp == "protected"].sort_values(["moratorium", "zip"]), width="stretch", height=300)


def fair() -> None:
    df = load("fair_mirror")
    cc = df[df.county == COUNTY]
    st.caption("FAIR Plan policies in force (9/30 of fiscal year) alongside voluntary-market non-renewals, by ZIP-year.")
    st.line_chart(cc.pivot(index="y", columns="zip", values="fair"))
    st.dataframe(cc.sort_values(["zip", "y"]), width="stretch")


def regulatory() -> None:
    df = load("regulatory_alignment")
    st.caption(
        "Event study at annual resolution: change in the non-renewal rate (percentage points) from the year before each "
        "event to the event year and the year after. Regulatory events versus fire declarations, county and state."
    )
    summary = df.groupby(["release", "measure", "kind", "scope"])[["delta_during", "delta_after"]].agg(["mean", "count"]).round(2)
    st.dataframe(summary, width="stretch")
    st.dataframe(df.sort_values(["release", "date", "scope"]), width="stretch", height=350)


def actors() -> None:
    df = load("actor_centrality")
    st.caption(
        f"Betweenness centrality on the subgraph of every non-ZIP entity plus {COUNTY}'s ZIPs. "
        "`cc_zips_within_2` counts county ZIPs within two hops of the entity."
    )
    st.dataframe(df, width="stretch")


def evidence() -> None:
    st.caption("Every LLM-extracted edge with its verbatim span. Deterministic edges carry their source in props.")
    st.dataframe(load("evidence"), width="stretch")
