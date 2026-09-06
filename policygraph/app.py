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
