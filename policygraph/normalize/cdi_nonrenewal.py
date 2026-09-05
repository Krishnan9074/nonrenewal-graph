import re

import pandas as pd

from policygraph import NORMALIZED

COMMON = {"County": "county", "ZIP Code": "zip", "Year": "year", "New": "new", "Renewed": "renewed"}
SPLIT = {"Insurer-Initiated Nonrenewed": "nonrenewed_insurer", "Insured-Initiated Nonrenewed": "nonrenewed_insured"}
TOTAL = {"Non-Renewed": "nonrenewed"}  # the 2020-2023 release dropped the insurer/insured split
COUNTS = ["new", "renewed", "nonrenewed", "nonrenewed_insurer", "nonrenewed_insured"]
RELEASE_RE = re.compile(r"(\d{4}-\d{4})\.xlsx$")


def parse(df: pd.DataFrame, release: str) -> pd.DataFrame:
    df = df.rename(columns=COMMON | SPLIT | TOTAL)
    if missing := set(COMMON.values()) - set(df.columns):
        raise ValueError(f"cdi_nonrenewal missing columns: {missing}")
    if "nonrenewed" not in df.columns:
        df["nonrenewed"] = df.nonrenewed_insurer.astype(int) + df.nonrenewed_insured.astype(int)
    out = df.reindex(columns=["county", "zip", "year", *COUNTS])
    out[COUNTS] = out[COUNTS].apply(pd.to_numeric).astype("Int64")
    county = out.county.str.strip()
    return out.assign(
        release=release,
        county=county.mask(county == ""),
        zip=out.zip.str.zfill(5),
        year=out.year.astype(int),
        policies=out.new + out.renewed + out.nonrenewed,
    )


def run(spec: dict, files: list[dict]) -> None:
    frames = [parse(pd.read_excel(f["path"], dtype=str), RELEASE_RE.search(f["url"]).group(1)) for f in files]
    pd.concat(frames, ignore_index=True).to_parquet(NORMALIZED / "cdi_nonrenewal.parquet", index=False)
