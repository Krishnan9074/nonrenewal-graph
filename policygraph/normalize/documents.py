import re
from datetime import date
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from policygraph import NORMALIZED
from policygraph.normalize.html_text import to_text
from policygraph.util import sha256

DATE_RE = re.compile(r"(?:(?:DATE|For Release):\s*|^)([A-Z][a-z]+ \d{1,2}, \d{4})(?:\s*[-–—]|\s*$)", re.M)


def pdf_text(path: str) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)


def text_of(path: str, kind: str) -> str:
    if kind == "pdf":
        return pdf_text(path)
    if kind == "html":
        return to_text(Path(path).read_text(errors="replace"))
    raise ValueError(f"documents: unsupported source type {kind!r}")


def published_at(text: str) -> date | None:
    m = DATE_RE.search(text)
    return pd.to_datetime(m.group(1)).date() if m else None


def run(spec: dict, files: list[dict]) -> None:
    """doc_id hashes the extracted text: CDI's HTML carries per-request tokens, so raw bytes never repeat."""
    texts = [text_of(f["path"], spec["type"]) for f in files]
    df = pd.DataFrame(
        [
            {
                "doc_id": sha256(t.encode()),
                "source": spec["doc_source"],
                "url": f["url"],
                "published_at": published_at(t),
                "text": t,
            }
            for f, t in zip(files, texts, strict=True)
        ]
    )
    out = NORMALIZED / "documents.parquet"
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df]).drop_duplicates("doc_id")
    df.to_parquet(out, index=False)
