import re

import pandas as pd
from pypdf import PdfReader

from policygraph import NORMALIZED

ROW_RE = re.compile(r"^\d{5}\b")
FY_RE = re.compile(r"9/30/(\d{4})")


def layout(text: str) -> tuple[list[int], int, list[int]]:
    """Fiscal years from the footer; a row is zip, (growth, count) per year except the oldest, then the oldest count."""
    years = list(dict.fromkeys(int(y) for y in FY_RE.findall(text)))
    if not years:
        raise ValueError("cdi_fair_plan: no fiscal-year footer found")
    n = len(years)
    return years, 2 * n, [*range(2, 2 * n, 2), 2 * n - 1]


def parse(text: str) -> pd.DataFrame:
    years, tokens, count_at = layout(text)
    rows = []
    for line in filter(ROW_RE.match, text.splitlines()):
        tok = line.split()
        if len(tok) != tokens:
            raise ValueError(f"cdi_fair_plan: expected {tokens} tokens for {len(years)} fiscal years, got {line!r}")
        counts = [tok[i] for i in count_at]
        rows += [{"zip": tok[0], "year": y, "fair_policies": c} for y, c in zip(years, counts, strict=True) if c != "-"]
    df = pd.DataFrame(rows)
    return df.assign(fair_policies=df.fair_policies.str.replace(",", "").astype(int))


def run(spec: dict, files: list[dict]) -> None:
    text = "\n".join(p.extract_text() for p in PdfReader(files[0]["path"]).pages)
    parse(text).to_parquet(NORMALIZED / "cdi_fair_plan.parquet", index=False)
