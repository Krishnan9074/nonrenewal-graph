import duckdb
import pandas as pd

from policygraph.insights import events, trend

# Event study at the resolution CDI publishes (calendar years): the change in non-renewal rate (points) or FAIR Plan
# policies in force (percent) from the year before an event to the event year and the year after, for regulatory
# events versus fire declarations, county and state. Only the FAIR series reaches the 2024-25 regulatory events.
FITS = (("2015-2021", "rate_insurer", "pts"), ("2020-2023", "rate", "pts"), ("fair-plan-fy", "fair", "%"))


def distinct_events(ev: pd.DataFrame) -> pd.DataFrame:
    ev = ev[ev.kind.isin(["fire", "regulation", "rate_decision"])].copy()
    ev["date"] = pd.to_datetime(ev.date)
    g = ev.groupby(["kind", "date"], as_index=False).agg(
        label=("dst_name", lambda s: ", ".join(sorted(set(s))[:4])), n=("dst", "nunique")
    )
    return g.assign(year=g.date.dt.year)


def study(ev: pd.DataFrame, tr: pd.DataFrame, release: str, measure: str, unit: str) -> pd.DataFrame:
    series = tr[tr.release == release].pivot(index="y", columns="scope", values=measure)
    rows = []
    for e in ev.itertuples():
        for scope in series.columns:
            b, d, a = (series[scope].get(e.year + k) for k in (-1, 0, 1))
            if pd.isna(b) or pd.isna(d):
                continue  # outside this release's window
            rows.append({**e._asdict(), "scope": scope, "before": b, "during": d, "after": a})
    out = pd.DataFrame(rows, columns=[*ev.columns, "scope", "before", "during", "after"])
    if unit == "%":
        deltas = {"delta_during": (out.during / out.before - 1) * 100, "delta_after": (out.after / out.before - 1) * 100}
    else:
        deltas = {"delta_during": (out.during - out.before) * 100, "delta_after": (out.after - out.before) * 100}
    return out.assign(**deltas, release=release, measure=measure, unit=unit)


def compute(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    ev, tr = distinct_events(events.compute(con)), trend.compute(con)
    return pd.concat([study(ev, tr, *f) for f in FITS], ignore_index=True)
