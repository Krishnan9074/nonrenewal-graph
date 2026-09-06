import json

import pandas as pd
import streamlit as st

from policygraph.views.data import COUNTY, TYPE_COLOR, load

VIS = "https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js"
HTML = """
<script src="{vis}"></script>
<div id="g" style="height:620px;border:1px solid #ddd;border-radius:6px;background:#fcfcfb"></div>
<script>
const nodes = new vis.DataSet({nodes}); const edges = new vis.DataSet({edges});
new vis.Network(document.getElementById('g'), {{nodes, edges}}, {{
  nodes: {{shape: 'dot', size: 12, font: {{size: 12}}}},
  edges: {{arrows: 'to', font: {{size: 10, align: 'middle'}}, color: {{color: '#9a9994'}}, smooth: false}},
  physics: {{solver: 'forceAtlas2Based', stabilization: {{iterations: 200}}}},
  interaction: {{hover: true, tooltipDelay: 80}}
}});
</script>
"""


def neighbourhood(df: pd.DataFrame, start: str, hops: int) -> pd.DataFrame:
    seen, frontier = {start}, {start}
    for _ in range(hops):
        step = df[df.src.isin(frontier) | df.dst.isin(frontier)]
        frontier = (set(step.src) | set(step.dst)) - seen
        seen |= frontier
    return df[df.src.isin(seen) & df.dst.isin(seen)]


def title(e: pd.Series) -> str:
    props = json.loads(e.props) if e.props else {}
    bits = [f"{e.rel} · {e.extractor} · confidence {e.confidence:.2f}"]
    if e.valid_from is not None and not pd.isna(e.valid_from):
        bits.append(f"valid {e.valid_from} → {e.valid_to if not pd.isna(e.valid_to) else 'open'}")
    if props:
        bits.append(", ".join(f"{k}={v}" for k, v in props.items() if v is not None))
    if isinstance(e.span, str):
        bits.append(f"“{e.span[:300]}”")
    if isinstance(e.url, str):
        bits.append(e.url)
    return "\n".join(bits)


def render() -> None:
    df = load("explorer")
    ents = pd.concat(
        [
            df[["src", "src_name", "src_type"]].set_axis(["id", "name", "type"], axis=1),
            df[["dst", "dst_name", "dst_type"]].set_axis(["id", "name", "type"], axis=1),
        ]
    ).drop_duplicates("id")
    cc = set(df[df.src_county == COUNTY].src) | set(df[df.dst_county == COUNTY].dst)
    pick = ents[(ents.type != "zip") | ents.id.isin(cc)].sort_values(["type", "name"])
    default = int((pick.id == "zip:94549").to_numpy().argmax())
    c1, c2, c3 = st.columns([3, 1, 1])
    start = c1.selectbox("Start entity", pick.id, index=default, format_func=lambda i: f"{pick.set_index('id').name[i]}  ({i})")
    hops = c2.slider("Hops", 1, 3, 1)
    cap = c3.slider("Max edges", 50, 600, 200, step=50)
    sub = neighbourhood(df, start, hops).head(cap)
    ids = set(sub.src) | set(sub.dst)
    names = ents.set_index("id")
    nodes = [
        {
            "id": i,
            "label": names.name[i] if len(names.name[i]) < 40 else names.name[i][:38] + "…",
            "title": i,
            "color": TYPE_COLOR.get(names.type[i], "#888"),
            "borderWidth": 3 if i == start else 1,
        }
        for i in ids
    ]
    edges = [{"from": e.src, "to": e.dst, "label": e.rel, "title": title(e)} for e in sub.itertuples()]
    st.caption(
        f"{len(nodes)} entities, {len(edges)} edges. Hover an edge for its span, provenance and source URL; "
        "nodes are coloured by type."
    )
    st.iframe(HTML.format(vis=VIS, nodes=json.dumps(nodes), edges=json.dumps(edges)), height=640)
    legend = " ".join(f"<span style='color:{c}'>●</span> {t}" for t, c in TYPE_COLOR.items())
    st.markdown(legend, unsafe_allow_html=True)
