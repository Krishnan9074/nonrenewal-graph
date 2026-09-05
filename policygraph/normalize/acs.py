import pandas as pd

from policygraph import NORMALIZED

VARS = {
    "B25077_001E": "median_home_value",
    "B25035_001E": "median_year_built",
    "B19013_001E": "median_income",
}


def parse(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(raw.iloc[1:].values, columns=raw.iloc[0]).rename(columns=VARS | {"zip code tabulation area": "zip"})
    vals = df[list(VARS.values())].astype(float)
    return df[["zip"]].assign(**vals.mask(vals < 0))  # Census encodes suppressed cells as -666666666


def run(spec: dict, files: list[dict]) -> None:
    parse(pd.read_json(files[0]["path"])).to_parquet(NORMALIZED / "acs.parquet", index=False)
