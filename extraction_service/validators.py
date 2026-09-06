import re
from datetime import date, timedelta

from extraction_service.models import REL_TYPES, Anchors, Edge, Extraction

_WS = re.compile(r"\s+")
_ZIP = re.compile(r"\d{5}")
_BILL = re.compile(r"(SB|AB)\s?\d+", re.I)


def _norm(s: str) -> str:
    """pypdf breaks words across lines ("Sanda\nlwood"), so whitespace is ignored entirely; characters are not."""
    return _WS.sub("", s).lower()


# Each check returns None when it passes, else a message the model can act on when retrying.
def span_verbatim(edge: Edge, chunk: str) -> str | None:
    return None if _norm(edge.span) in _norm(chunk) else "span is not a verbatim substring of the chunk"


def types_allowed(edge: Edge, types: dict[str, str]) -> str | None:
    src_ok, dst_ok = REL_TYPES[edge.rel]
    got = (types.get(edge.src_mention), types.get(edge.dst_mention))
    if got[0] in src_ok and got[1] in dst_ok:
        return None
    return f"types {got[0]}->{got[1]} not allowed for {edge.rel}; need {'/'.join(src_ok)}->{'/'.join(dst_ok)}"


def _near(d: date, anchors: Anchors) -> bool:
    return d in anchors.dates or any(abs(d - a) <= timedelta(days=366) for a in anchors.dates)


def anchored(edge: Edge, anchors: Anchors) -> str | None:
    for m in (edge.src_mention, edge.dst_mention):
        if _ZIP.fullmatch(m) and m not in anchors.zips:
            return f"anchors: ZIP {m} is not in the chunk"
        if _BILL.fullmatch(m) and m.upper().replace(" ", "") not in anchors.bills:
            return f"anchors: bill {m} is not in the chunk"
    if all(d is None or _near(d, anchors) for d in (edge.valid_from, edge.valid_to)):
        return None
    return "anchors: dates are not within a year of any date in the chunk"


def dates_sane(edge: Edge) -> str | None:
    if edge.valid_from is None or edge.valid_to is None or edge.valid_from <= edge.valid_to:
        return None
    return "dates: valid_from > valid_to"


def validate(x: Extraction, chunk: str, anchors: Anchors) -> tuple[Extraction, list[str]]:
    types = {e.mention: e.type for e in x.entities}
    kept, errors = [], []
    for e in x.edges:
        failed = [m for m in (span_verbatim(e, chunk), types_allowed(e, types), anchored(e, anchors), dates_sane(e)) if m]
        if failed:
            errors.append(f"{e.src_mention} -{e.rel}-> {e.dst_mention}: {'; '.join(failed)}")
        else:
            kept.append(e)
    return Extraction(entities=x.entities, edges=kept), errors
