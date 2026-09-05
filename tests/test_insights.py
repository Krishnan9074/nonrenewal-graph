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
    c.executemany(
        "INSERT INTO entities VALUES (?,?,?,?)", [(f"zip:{z}", "zip", z, json.dumps({"county": "Contra Costa"})) for z in ZIPS]
    )
    c.executemany("INSERT INTO edges (edge_id,src,rel,dst,valid_from,props,extractor,confidence) VALUES (?,?,?,?,?,?,?,?)", EDGES)
    return c


ZIPS = ["94563", "94509", "94565", "94513"]
EDGES = [
    *[
        edge("market:ca:voluntary", "NONRENEWED_IN", f"zip:{z}", 2023, count=n, policies=1000, release="2020-2023")
        for z, n in zip(ZIPS, (90, 30, 40, 20), strict=True)
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
    assert set(df.measure) == {"count", "nonrenewed_insurer"} and df.iloc[0].county == "Contra Costa"
    assert df.groupby("measure").residual.sum().abs().max() == pytest.approx(0)


def test_moratorium_deferral_protected_vs_control(con):
    df = moratorium_deferral.compute(con).set_index("grp")
    assert df.loc["protected"].zip == "94563" and df.loc["protected"].after_ratio == 2.0
    assert df.loc["control"].before == 36 and df.loc["control"].after == 66


def test_fair_mirror_share(con):
    df = fair_mirror.compute(con)
    assert len(df) == 1 and df.iloc[0].fair_share == pytest.approx(200 / 1200) and df.iloc[0].nonrenewed == 90
