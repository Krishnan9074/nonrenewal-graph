import duckdb
import numpy as np
import pandas as pd

from policygraph.insights.matching import nearest

# The moratorium year is the calendar year holding most of the 12-month window (its midpoint), so an October
# declaration counts the following year as "during". Each release is analysed alone with the measure it publishes.
FITS = (("2015-2021", "nonrenewed_insurer"), ("2020-2023", "count"))
MATCH_ON = ["very_high", "log_policies"]

PROT = "SELECT DISTINCT src AS zip, dst AS moratorium, valid_from, valid_to FROM edges WHERE rel='PROTECTED_BY'"
NR = """
SELECT dst AS zip, year(valid_from) AS y, json_extract(props, ?)::INT AS n, json_extract(props,'$.policies')::INT AS p
FROM edges WHERE rel='NONRENEWED_IN' AND json_extract_string(props,'$.release')=?
"""
HAZ = """
SELECT src AS zip, json_extract(props,'$.pct')::DOUBLE AS very_high FROM edges WHERE rel='HAZARD_SHARE' AND dst='fhsz:very_high'
"""


def moratorium_year(valid_from: pd.Series, valid_to: pd.Series) -> pd.Series:
    start, end = pd.to_datetime(valid_from), pd.to_datetime(valid_to).fillna(pd.to_datetime(valid_from))
    return (start + (end - start) / 2).dt.year


def windows(nr: pd.DataFrame, y0: int) -> pd.DataFrame:
    w = nr[nr.y.between(y0 - 1, y0 + 1)].pivot_table(index="zip", columns="y", values="n", aggfunc="sum")
    return w.reindex(columns=[y0 - 1, y0, y0 + 1]).set_axis(["before", "during", "after"], axis=1)


def features(nr: pd.DataFrame, haz: pd.DataFrame, y: int) -> pd.DataFrame:
    p = nr[nr.y == y].groupby("zip").p.sum()
    return pd.DataFrame({"log_policies": np.log1p(p)}).join(haz.set_index("zip")).fillna({"very_high": 0})


def summarise(grp: str, label: str, w: pd.DataFrame) -> dict:
    s = w.sum(min_count=1)
    return {"grp": grp, "zip": label, "n_zips": len(w), "before": s.before, "during": s.during, "after": s.after}


def rows(prot: pd.DataFrame, nr: pd.DataFrame, haz: pd.DataFrame) -> list[dict]:
    out, everywhere = [], set(prot.zip)
    for (mor, y0), g in prot.groupby(["moratorium", "y0"]):
        w = windows(nr, y0)
        treated = w.index.intersection(set(g.zip))
        if not len(treated) or w.loc[treated].isna().all().any():
            continue  # the window is outside this release
        pool = w.index.difference(everywhere)
        feats = features(nr, haz, y0 - 1)
        matched = nearest(feats.reindex(treated).fillna(0), feats.reindex(pool).fillna(0), MATCH_ON)
        out += [
            {"grp": "protected", "zip": z[4:], "n_zips": 1, **w.loc[z].to_dict()} | {"moratorium": mor, "y0": y0} for z in treated
        ]
        out += [
            summarise("control_all", "all other CA ZIPs", w.loc[pool]) | {"moratorium": mor, "y0": y0},
            summarise("control_matched", "matched CA ZIPs", w.loc[matched]) | {"moratorium": mor, "y0": y0},
        ]
    return out


def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    prot = con.execute(PROT).df()
    prot["y0"] = moratorium_year(prot.valid_from, prot.valid_to)
    haz = con.execute(HAZ).df()
    frames = []
    for release, measure in FITS:
        nr = con.execute(NR, [f"$.{measure}", release]).df()
        frames.append(pd.DataFrame(rows(prot, nr, haz)).assign(release=release, measure=measure))
    df = pd.concat(frames, ignore_index=True)
    before = df["before"].replace(0, np.nan)
    return df.assign(during_ratio=df["during"] / before, after_ratio=df["after"] / before)
