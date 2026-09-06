import copy

import pandas as pd
import pydeck as pdk
import streamlit as st

from policygraph.views.data import COUNTY, DIV, SEQ, geojson, load, ramp

# label -> (frame builder, value column, diverging?, format)
CENTER = {"latitude": 37.92, "longitude": -121.95, "zoom": 9.2}


def metrics() -> dict[str, tuple[pd.Series, bool, str]]:
    res = load("hazard_residual")
    res = res[(res.county == COUNTY) & (res.spec == "hazard")]
    ins, tot = res[res.measure == "nonrenewed_insurer"].set_index("zip"), res[res.measure == "count"].set_index("zip")
    fair = load("fair_mirror")
    fair = fair[fair.county == COUNTY].set_index(["zip", "y"]).sort_index()
    prot = load("explorer")
    prot = prot[(prot.rel == "PROTECTED_BY") & (prot.src_county == COUNTY)]
    covered = prot.groupby(prot.src.str[4:]).dst_name.agg(lambda s: "; ".join(sorted(set(s))))
    return {
        "Insurer-initiated non-renewal rate, 2021 (2015–2021 release)": (ins.rate * 100, False, "{:.2f} %"),
        "Hazard residual, 2021 insurer-initiated (pts above the hazard line)": (ins.residual * 100, True, "{:+.2f} pts"),
        "All non-renewals rate, 2023 (2020–2023 release)": (tot.rate * 100, False, "{:.2f} %"),
        "Hazard residual, 2023 all non-renewals (pts)": (tot.residual * 100, True, "{:+.2f} pts"),
        "Very High FHSZ area share": (ins.very_high * 100, False, "{:.0f} %"),
        "FAIR Plan policies in force, FY2025": (fair.xs(2025, level="y").fair, False, "{:,.0f}"),
        "FAIR Plan share of (FAIR + voluntary), 2023": (fair.xs(2023, level="y").fair_share * 100, False, "{:.1f} %"),
        "Median home value (ACS 2023)": (ins.home_value, False, "${:,.0f}"),
        "Median household income (ACS 2023)": (ins.income, False, "${:,.0f}"),
        "Moratorium coverage (SB 824 bulletins)": (covered, False, "{}"),
    }


def colour(values: pd.Series, diverging: bool) -> dict[str, list[int]]:
    if values.dtype == object:
        return {z: [27, 175, 122, 190] for z in values.index}  # categorical: covered or not
    if diverging:
        m = float(values.abs().max()) or 1.0
        return {z: [*ramp(DIV, 0.5 + v / (2 * m)), 200] for z, v in values.items()}
    lo, hi = float(values.min()), float(values.max())
    return {z: [*ramp(SEQ, (v - lo) / ((hi - lo) or 1.0)), 200] for z, v in values.items()}


def render() -> None:
    label = st.selectbox("Colour ZIPs by", list(metrics()))
    values, diverging, fmt = metrics()[label]
    values = values.dropna()
    fills = colour(values, diverging)
    gj = copy.deepcopy(geojson())
    for f in gj["features"]:
        z = f["properties"]["zip"]
        f["properties"]["fill"] = fills.get(z, [240, 239, 236, 120])
        f["properties"]["display"] = fmt.format(values[z]) if z in values.index else "no data"
        f["properties"]["label"] = label
    layer = pdk.Layer(
        "GeoJsonLayer",
        gj,
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color="properties.fill",
        get_line_color=[82, 81, 78],
        line_width_min_pixels=1,
    )
    tooltip = {"html": "<b>{place}</b> · {zip}<br/>{label}<br/><b>{display}</b>"}
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(**CENTER), tooltip=tooltip, map_style="light"))
    if values.dtype != object:
        lo, hi = values.min(), values.max()
        scale = " → ".join(f"<span style='color:{c}'>■</span>" for c in (DIV if diverging else SEQ))
        st.caption(f"{fmt.format(lo)} {scale} {fmt.format(hi)} · grey = no data")
        table = values.rename(label).sort_values(ascending=False).to_frame()
        st.dataframe(table.assign(place=table.index.map(gj_places(gj))), width="stretch", height=240)
    else:
        st.caption("Green = at least one SB 824 moratorium named this ZIP; grey = never covered.")
        st.dataframe(values.rename("moratoria").to_frame(), width="stretch", height=240)


def gj_places(gj: dict) -> dict[str, str]:
    return {f["properties"]["zip"]: f["properties"]["place"] for f in gj["features"]}
