import json
from pathlib import Path

import duckdb
import pytest

from policygraph.insights import fair_mirror, hazard_residual, moratorium_deferral

SCHEMA = (Path(__file__).parent.parent / "config" / "schema.sql").read_text()


def edge(src: str, rel: str, dst: str, year: int, **props) -> tuple:
    return (f"{src}|{rel}|{dst}|{year}", src, rel, dst, f"{year}-01-01", json.dumps(props), "test", 1.0)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(SCHEMA)
    values = ((1.5e6, 1.6e5), (6e5, 9e4), (5e5, 1.1e5), (8e5, 7e4), (1.4e6, 1.8e5), (1.1e6, 1.5e5))
    attrs = [{"county": "Contra Costa", "median_home_value": h, "median_income": i} for h, i in values]
    c.executemany(
        "INSERT INTO entities VALUES (?,?,?,?)", [(f"zip:{z}", "zip", z, json.dumps(a)) for z, a in zip(ZIPS, attrs, strict=True)]
    )
    c.executemany("INSERT INTO edges (edge_id,src,rel,dst,valid_from,props,extractor,confidence) VALUES (?,?,?,?,?,?,?,?)", EDGES)
    return c


ZIPS = ["94563", "94509", "94565", "94513", "94549", "94526"]
EDGES = [
    *[
        edge("market:ca:voluntary", "NONRENEWED_IN", f"zip:{z}", 2023, count=n, policies=1000, release="2020-2023")
        for z, n in zip(ZIPS, (90, 30, 40, 20, 60, 10), strict=True)
    ],
    *[
        edge(
            "market:ca:voluntary",
            "NONRENEWED_IN",
            f"zip:{z}",
            y,
            count=n,
            nonrenewed_insurer=n // 5 + ZIPS.index(z),
            policies=1000,
            release="2015-2021",
        )
        for z in ZIPS
        for y, n in ((2019, 50), (2020, 25), (2021, 100))
    ],
    edge("zip:94563", "HAZARD_SHARE", "fhsz:very_high", 2020, pct=0.8),
    edge("zip:94565", "HAZARD_SHARE", "fhsz:high", 2020, pct=0.5),
    edge("zip:94563", "PROTECTED_BY", "moratorium:2020-09-25:x", 2020),
    edge("zip:94563", "HAS_FAIR_PLAN_POLICIES", "insurer:fairplan", 2023, count=200),
]


def test_hazard_residual_sums_to_zero_per_fit(con):
    df = hazard_residual.compute(con)
    assert set(df.measure) == {"count", "nonrenewed_insurer"} and set(df.spec) == {"hazard", "hazard+acs"}
    assert df.groupby(["measure", "spec"]).residual.sum().abs().max() == pytest.approx(0)
    assert df.groupby("spec").n.first().to_dict() == {"hazard": 6, "hazard+acs": 6}


def test_moratorium_deferral_protected_vs_controls(con):
    df = moratorium_deferral.compute(con).set_index("grp")
    assert set(df.release) == {"2015-2021"}  # the 2020-2023 fixture has no 2019-2021 window
    assert df.loc["protected"].zip == "94563" and df.loc["protected"].after_ratio == 2.0 and df.loc["protected"].y0 == 2020
    assert df.loc["control_all"].before == 65 and df.loc["control_all"].after == 115 and df.loc["control_all"].n_zips == 5
    assert df.loc["control_matched"].n_zips == 5 and df.loc["control_matched"].after == 115


def test_moratorium_year_is_midpoint():
    import pandas as pd

    y = moratorium_deferral.moratorium_year(pd.Series(["2019-10-27", "2020-09-25"]), pd.Series(["2020-10-27", None]))
    assert y.tolist() == [2020, 2020]


def test_fair_mirror_share(con):
    df = fair_mirror.compute(con)
    assert len(df) == 1 and df.iloc[0].fair_share == pytest.approx(200 / 1200) and df.iloc[0].nonrenewed == 90


def test_trend_and_alignment_include_fair_series(con):
    from policygraph.insights import regulatory_alignment, trend

    tr = trend.compute(con)
    assert set(tr.release) == {"2015-2021", "2020-2023", "fair-plan-fy"} and tr[tr.release == "fair-plan-fy"].fair.sum() == 400
    con.execute("INSERT INTO documents VALUES ('d', 'cdi_press', 'u', '2023-01-01', 'x')")
    con.execute(
        "INSERT INTO edges (edge_id,src,rel,dst,valid_from,props,doc_id,span,extractor,confidence) "
        "VALUES ('e','official:x','ISSUED','regulation:y','2020-06-01','{}','d','span text','llm',0.9)"
    )
    ra = regulatory_alignment.compute(con)
    row = ra[(ra.release == "2015-2021") & (ra.scope == "Contra Costa")].iloc[0]
    assert (
        row.kind == "regulation"
        and row.unit == "pts"
        and row.before == pytest.approx(0.0125)
        and row.during == pytest.approx(0.0075)
    )
    assert set(ra.release) == {"2015-2021"}  # the FAIR fixture has one year, so no window exists there
