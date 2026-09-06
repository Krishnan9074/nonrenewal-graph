import re
from datetime import date

import pandas as pd

from extraction_service.models import Anchors, ZipBlock

ZIP_RE = re.compile(r"\b9[0-6]\d{3}\b")
BILL_RE = re.compile(r"\b(SB|AB|Senate Bill|Assembly Bill)\s?(\d{1,4})\b", re.I)
HOUSE = {"senate bill": "SB", "assembly bill": "AB"}
DATE_RE = re.compile(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
# "due to the Governor's October 27, 2019 Declaration" / "As a result of the Governor's September 6, 2020 emergency declaration"
DECL_RE = re.compile(r"Governor[’']s\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s+(?:emergency\s+)?[Dd]\s?eclarations?")
HEADING_RE = re.compile(r"^[^\n]{1,90}\bFires?\b[^\n]{0,60}$")
NOT_HEADING = re.compile(r"perimeter|Protection|Department|insurer|ZIP|Governor|declar|Bulletin|Moratorium|Page|due to|•", re.I)
NAME_STRIP = (re.compile(r"\(.*?\)"), re.compile(r"[\[\]]"), re.compile(r"\d+$"), re.compile(r"\bFires?\b(\s+\d{4})?\s*$"))


def _dates(text: str) -> set[date]:
    out: set[date] = set()
    for m in DATE_RE.findall(text):
        try:
            out.add(pd.to_datetime(m).date())
        except ValueError:
            continue
    return out


def fire_name(heading: str) -> str:
    """'[Old] Water Fire' -> 'Old Water'; 'SHF Lightning Fires 2020' -> 'SHF Lightning'."""
    name = heading.strip()
    for rx in NAME_STRIP:
        name = rx.sub("", name).strip()
    return " ".join(name.split())


def zip_blocks(text: str) -> list[ZipBlock]:
    """Fire headings followed by ZIP lines, dated by the nearest preceding declaration sentence. Bulletins only."""
    decls = [(m.start(), pd.to_datetime(m.group(1)).date()) for m in DECL_RE.finditer(text)]
    lines, pos, out = text.split("\n"), 0, []
    starts = []
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        is_heading = HEADING_RE.match(line) and not NOT_HEADING.search(line) and not ZIP_RE.search(line)
        if is_heading and i + 1 < len(lines) and ZIP_RE.search(lines[i + 1]):
            j = i + 1
            while j < len(lines) and ZIP_RE.search(lines[j]):
                j += 1
            zips = [z for k in range(i + 1, j) for z in ZIP_RE.findall(lines[k])]
            before = [d for p, d in decls if p < starts[i]]
            span = text[starts[i] : starts[j - 1] + len(lines[j - 1])].strip()
            out.append(ZipBlock(heading=line, name=fire_name(line), date=before[-1] if before else None, zips=zips, span=span))
            i = j
        else:
            i += 1
    return out


def extract(text: str) -> Anchors:
    return Anchors(
        zips=set(ZIP_RE.findall(text)),
        dates=_dates(text),
        bills={HOUSE.get(h.lower(), h.upper()) + n for h, n in BILL_RE.findall(text)},
        zip_blocks=zip_blocks(text),
    )
