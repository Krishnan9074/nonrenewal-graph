import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # Streamlit Cloud puts only this file's directory on sys.path

from policygraph.views import explorer, tables, timeline  # noqa: E402
from policygraph.views import map as map_view  # noqa: E402
from policygraph.views.data import DOCS  # noqa: E402

st.set_page_config(page_title="policygraph", layout="wide")
st.title("Home-insurance non-renewals · Contra Costa County")
st.markdown(
    "This is a knowledge graph built to answer one question: what is actually happening with home-insurance "
    "non-renewals in Contra Costa County, and what appears to be driving it. It joins sources that never meet in one "
    "place: the California Department of Insurance's ZIP-level policy counts (2015–2023), the FAIR Plan's policies in "
    "force by ZIP (FY2021–FY2025), CAL FIRE hazard zones, Census home values and incomes, and the prose of CDI's "
    "moratorium bulletins, regulations and rate decisions, read by a separate extraction service that keeps a verbatim "
    "quote for every claim it makes. Tabular data is loaded deterministically; a model reads only prose; every edge in "
    "the graph carries its source, extractor and confidence. The five findings tabs test the obvious explanations "
    "(fire hazard, house prices, moratoriums, the regulatory calendar) against the data and say what the public record "
    "can and cannot support. Start with **Findings** for the write-up, **Map** to see the county at a glance, and "
    "**Evidence** for the receipts."
)

TABS = {
    "Findings": lambda: st.markdown((DOCS / "FINDINGS.md").read_text()),
    "Map": map_view.render,
    "Timeline": timeline.render,
    "Graph": explorer.render,
    "Hazard residual": tables.hazard,
    "Moratorium deferral": tables.moratorium,
    "FAIR Plan mirror": tables.fair,
    "Regulatory alignment": tables.regulatory,
    "Actors": tables.actors,
    "Evidence": tables.evidence,
}
for tab, render in zip(st.tabs(list(TABS)), TABS.values(), strict=True):
    with tab:
        render()
