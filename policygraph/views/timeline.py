import altair as alt
import pandas as pd
import streamlit as st

from policygraph.views.data import CAT, COUNTY, KIND_COLOR, load

SERIES = (
    ("2015-2021", "rate_insurer", "Insurer-initiated non-renewal rate (2015–2021 release)"),
    ("2020-2023", "rate", "All non-renewals rate (2020–2023 release)"),
)


def series_chart(tr: pd.DataFrame, ev: pd.DataFrame, release: str, measure: str, title: str) -> alt.Chart:
    df = tr[tr.release == release].assign(
        pct=lambda d: d[measure] * 100, date=lambda d: pd.to_datetime(d.y.astype(str) + "-07-01")
    )
    lo, hi = df.date.min() - pd.DateOffset(months=6), df.date.max() + pd.DateOffset(months=6)
    ev = ev[(ev.date >= lo) & (ev.date <= hi)]
    scale = alt.Scale(domain=[COUNTY, "California"], range=[CAT["blue"], CAT["orange"]])
    line = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2)
        .encode(
            x=alt.X("date:T", title=None, scale=alt.Scale(domain=[lo, hi])),
            y=alt.Y("pct:Q", title="% of policies"),
            color=alt.Color("scope:N", scale=scale, title=None),
            tooltip=["scope", "y", alt.Tooltip("pct:Q", format=".2f", title="%")],
        )
    )
    rules = (
        alt.Chart(ev)
        .mark_rule(strokeWidth=2, opacity=0.8)
        .encode(
            x="date:T",
            color=alt.Color("kind:N", scale=alt.Scale(domain=list(KIND_COLOR), range=list(KIND_COLOR.values())), title="event"),
            tooltip=["kind", alt.Tooltip("date:T"), "label", "cc_zips"],
        )
    )
    return (line + rules).properties(title=title, height=260).resolve_scale(color="independent")


def render() -> None:
    tr, ev = load("trend"), load("events")
    ev = ev.assign(date=pd.to_datetime(ev.date))
    ev = ev.groupby(["kind", "date"], as_index=False).agg(
        label=("dst_name", lambda s: "; ".join(sorted(set(s))[:5])), cc_zips=("cc_zips", "max")
    )
    st.caption(
        "County and statewide non-renewal rates by CDI release, with dated events from the extracted documents "
        "as vertical rules. Hover for detail."
    )
    for release, measure, title in SERIES:
        st.altair_chart(series_chart(tr, ev, release, measure, title), width="stretch")
    st.caption("Events by date. `cc_zips` is how many Contra Costa ZIPs the moratorium named.")
    st.dataframe(ev.sort_values("date"), width="stretch", height=300)
