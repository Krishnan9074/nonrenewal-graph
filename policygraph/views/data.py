import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
INSIGHTS, DOCS = ROOT / "data" / "insights", ROOT / "docs"
COUNTY = "Contra Costa"

# Reference data-viz palette: sequential blue for magnitude, blue<->red around gray for polarity, fixed categorical order.
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIV = ["#0d366b", "#3987e5", "#9ec5f4", "#f0efec", "#f3a5a5", "#e34948", "#8f1f1f"]
CAT = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "magenta": "#e87ba4", "violet": "#4a3aa7"}
KIND_COLOR = {"regulation": CAT["blue"], "fire": CAT["orange"], "moratorium": CAT["aqua"], "rate_decision": CAT["yellow"]}
TYPE_COLOR = {
    "zip": CAT["blue"],
    "moratorium": CAT["aqua"],
    "fire": CAT["orange"],
    "official": CAT["violet"],
    "insurer": CAT["magenta"],
    "regulation": CAT["yellow"],
    "ratefiling": "#e34948",
    "bill": CAT["yellow"],
    "market": "#52514e",
    "fhsz": "#8a8985",
}


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(INSIGHTS / f"{name}.parquet")


@st.cache_data
def geojson() -> dict:
    return json.loads((INSIGHTS / "cc_zips.geojson").read_text())


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def ramp(ramp_hex: list[str], t: float) -> list[int]:
    """Piecewise-linear interpolation through the ramp at t in [0, 1]."""
    t = min(max(t, 0.0), 1.0) * (len(ramp_hex) - 1)
    i = min(int(t), len(ramp_hex) - 2)
    a, b = hex_rgb(ramp_hex[i]), hex_rgb(ramp_hex[i + 1])
    return [round(a[k] + (b[k] - a[k]) * (t - i)) for k in range(3)]


def places() -> dict[str, str]:
    return {f["properties"]["zip"]: f["properties"]["place"] for f in geojson()["features"]}
