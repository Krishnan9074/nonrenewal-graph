import re
from datetime import date

from extraction_service.anchors import fire_name
from extraction_service.models import Edge, Entity, Extraction, ZipBlock

# "Fires 2020 2020" and "Fires 2020 moratorium": headings like "SHF Lightning Fires 2020" get the year appended twice
FIRE_RE = re.compile(r"^(.+?) Fires?(?: \(.*?\))?(?: (\d{4}))?(?: \d{4})?$", re.I)
MOR_RE = re.compile(r"^(.+?) Fires?(?: \(.*?\))?(?: \d{4})? moratorium (\d{4}-\d{2}-\d{2})$", re.I)
CONFIDENCE = 0.97  # the ZIP list is read by regex; the fire-to-declaration link is the model's or the section's


def same(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a.endswith(b) or b.endswith(a)


def canonical_mentions(x: Extraction) -> dict[str, str]:
    """Fire and Moratorium mentions rewritten to the prompt's convention with variants folded together: parentheticals
    dropped, a yearless fire takes the year of its dated twin, and a name that is a suffix of another with the same
    date ('Water' / 'Old Water', 'lwood' / 'Sandalwood', both pypdf artefacts) takes the longer name."""
    parsed: dict[str, tuple[str, str, str | None]] = {}
    for e in x.entities:
        if e.type == "Fire" and (m := FIRE_RE.match(e.mention)):
            parsed[e.mention] = ("Fire", fire_name(m.group(1) + " Fire"), m.group(2))
        elif e.type == "Moratorium" and (m := MOR_RE.match(e.mention)):
            parsed[e.mention] = ("Moratorium", fire_name(m.group(1) + " Fire"), m.group(2))
    out = {}
    for mention, (kind, name, when) in parsed.items():
        peers = [
            (n, w) for k, n, w in parsed.values() if k == kind and same(n, name) and (w == when or when is None or w is None)
        ]
        name = max((n for n, _ in peers), key=len)
        when = when or next((w for _, w in peers if w), None)
        if kind == "Fire":
            out[mention] = f"{name} Fire {when}" if when else f"{name} Fire"
        else:
            out[mention] = f"{name} Fire moratorium {when}"
    return {k: v for k, v in out.items() if v != k}


def expand(x: Extraction, blocks: list[ZipBlock]) -> Extraction:
    """Fold mention variants, then add TRIGGERED, ISSUED and PROTECTED_BY edges for every dated ZIP block the model's
    output does not already cover."""
    fold = canonical_mentions(x)
    ents = {
        (fold.get(e.mention, e.mention), e.type): Entity(mention=fold.get(e.mention, e.mention), type=e.type) for e in x.entities
    }
    edges: dict[tuple, Edge] = {}
    for e in x.edges:
        e = e.model_copy(
            update={"src_mention": fold.get(e.src_mention, e.src_mention), "dst_mention": fold.get(e.dst_mention, e.dst_mention)}
        )
        edges.setdefault((e.src_mention, e.rel, e.dst_mention), e)
    mors = {m: MOR_RE.match(m) for (m, t) in ents if t == "Moratorium" and MOR_RE.match(m)}
    official = next((e.src_mention for e in edges.values() if e.rel == "ISSUED" and e.dst_mention in mors), None)
    for b in blocks:
        if b.date is None:
            continue
        hit = [m for m, r in mors.items() if same(r.group(1), b.name) and r.group(2) == b.date.isoformat()]
        name = mors[hit[0]].group(1) if hit else b.name
        mor, fire = hit[0] if hit else f"{name} Fire moratorium {b.date.isoformat()}", f"{name} Fire {b.date.year}"
        base = {
            "valid_from": b.date,
            "valid_to": _plus_year(b.date),
            "props": {"expanded_from": "zip_block"},
            "span": b.span,
            "confidence": CONFIDENCE,
        }
        ents.setdefault((fire, "Fire"), Entity(mention=fire, type="Fire"))
        ents.setdefault((mor, "Moratorium"), Entity(mention=mor, type="Moratorium"))
        edges.setdefault((fire, "TRIGGERED", mor), Edge(src_mention=fire, rel="TRIGGERED", dst_mention=mor, **base))
        if official:
            edges.setdefault((official, "ISSUED", mor), Edge(src_mention=official, rel="ISSUED", dst_mention=mor, **base))
        for z in b.zips:
            ents.setdefault((z, "ZIP"), Entity(mention=z, type="ZIP"))
            edges.setdefault((z, "PROTECTED_BY", mor), Edge(src_mention=z, rel="PROTECTED_BY", dst_mention=mor, **base))
    return Extraction(entities=list(ents.values()), edges=list(edges.values()))


def _plus_year(d: date) -> date:
    return d.replace(year=d.year + 1) if not (d.month == 2 and d.day == 29) else d.replace(year=d.year + 1, day=28)
