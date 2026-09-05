import re
from datetime import date

import pandas as pd
from pypdf import PdfReader

from policygraph import NORMALIZED

DATE_RE = re.compile(r"DATE:\s*([A-Z][a-z]+ \d{1,2}, \d{4})")


def pdf_text(path: str) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)


def published_at(text: str) -> date | None:
    m = DATE_RE.search(text)
    return pd.to_datetime(m.group(1)).date() if m else None


def run(spec: dict, files: list[dict]) -> None:
    texts = {f["sha"]: pdf_text(f["path"]) for f in files}
    df = pd.DataFrame(
        [
            {
                "doc_id": f["sha"],
                "source": spec["doc_source"],
                "url": f["url"],
                "published_at": published_at(texts[f["sha"]]),
                "text": texts[f["sha"]],
            }
            for f in files
        ]
    )
    out = NORMALIZED / "documents.parquet"
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df]).drop_duplicates("doc_id")
    df.to_parquet(out, index=False)
