import re

import pandas as pd
from pypdf import PdfReader

from policygraph import NORMALIZED

ROW_RE = re.compile(r"^\d{5}\b")
FY_RE = re.compile(r"9/30/(\d{4})")
TOKENS = 10
COUNT_AT = (2, 4, 6, 8, 9)  # zip, then (growth, count) x4, then the oldest count without growth


def parse(text: str) -> pd.DataFrame:
    years = [int(y) for y in FY_RE.findall(text)[:5]]
    rows = []
    for line in filter(ROW_RE.match, text.splitlines()):
        tok = line.split()
        if len(tok) != TOKENS:
            raise ValueError(f"cdi_fair_plan unexpected row: {line!r}")
        counts = [tok[i] for i in COUNT_AT]
        rows += [{"zip": tok[0], "year": y, "fair_policies": c} for y, c in zip(years, counts, strict=True) if c != "-"]
    df = pd.DataFrame(rows)
    return df.assign(fair_policies=df.fair_policies.str.replace(",", "").astype(int))


def run(spec: dict, files: list[dict]) -> None:
    text = "\n".join(p.extract_text() for p in PdfReader(files[0]["path"]).pages)
    parse(text).to_parquet(NORMALIZED / "cdi_fair_plan.parquet", index=False)
