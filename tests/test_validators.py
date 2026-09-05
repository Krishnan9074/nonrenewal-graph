from datetime import date

from extraction_service.anchors import extract as anchors
from extraction_service.models import Edge, Entity, Extraction
from extraction_service.validators import validate

CHUNK = "DATE: January 9, 2025. No insurer shall issue a notice of non-renewal in ZIP Codes 91001, 91006."
ANCHORS = anchors(CHUNK)


def edge(**kw) -> Edge:
    base = dict(
        src_mention="91001",
        rel="PROTECTED_BY",
        dst_mention="Eaton Fire moratorium",
        valid_from=date(2025, 1, 7),
        valid_to=date(2026, 1, 7),
        span="notice of non-renewal in ZIP Codes 91001",
        confidence=0.9,
    )
    return Edge(**(base | kw))


def extraction(*edges: Edge, extra: list[Entity] = ()) -> Extraction:
    ents = [
        Entity(mention="91001", type="ZIP"),
        Entity(mention="Eaton Fire moratorium", type="Moratorium"),
        *extra,
    ]
    return Extraction(entities=ents, edges=list(edges))


def test_bill_anchor_long_form():
    assert anchors("As enacted by Senate Bill 824 (Lara) and AB 2996.").bills == {"SB824", "AB2996"}


def test_valid_edge_kept():
    kept, errs = validate(extraction(edge()), CHUNK, ANCHORS)
    assert len(kept.edges) == 1 and not errs


def test_paraphrased_span_rejected():
    _, errs = validate(extraction(edge(span="insurers cannot drop 91001")), CHUNK, ANCHORS)
    assert "span" in errs[0]


def test_hallucinated_zip_rejected():
    x = extraction(edge(src_mention="94563", span="ZIP Codes 91001, 91006"), extra=[Entity(mention="94563", type="ZIP")])
    _, errs = validate(x, CHUNK, ANCHORS)
    assert "anchors" in errs[0]


def test_type_constraint_rejected():
    _, errs = validate(extraction(edge(rel="TRIGGERED")), CHUNK, ANCHORS)
    assert "types" in errs[0]


def test_reversed_dates_rejected():
    _, errs = validate(extraction(edge(valid_to=date(2024, 1, 1))), CHUNK, ANCHORS)
    assert "dates" in errs[0]
