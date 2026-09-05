import re
from datetime import date

import pandas as pd

from extraction_service.models import Anchors

ZIP_RE = re.compile(r"\b9[0-6]\d{3}\b")
BILL_RE = re.compile(r"\b(SB|AB|Senate Bill|Assembly Bill)\s?(\d{1,4})\b", re.I)
HOUSE = {"senate bill": "SB", "assembly bill": "AB"}
DATE_RE = re.compile(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def _dates(text: str) -> set[date]:
    out: set[date] = set()
    for m in DATE_RE.findall(text):
        try:
            out.add(pd.to_datetime(m).date())
        except ValueError:
            continue
    return out


def extract(text: str) -> Anchors:
    return Anchors(
        zips=set(ZIP_RE.findall(text)),
        dates=_dates(text),
        bills={HOUSE.get(h.lower(), h.upper()) + n for h, n in BILL_RE.findall(text)},
    )
