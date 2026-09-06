from datetime import date

from extraction_service.anchors import extract as anchors
from extraction_service.anchors import fire_name, zip_blocks
from extraction_service.expand import expand
from extraction_service.models import Edge, Entity, Extraction

DOC = """Therefore, due to the Governor’s October 27, 2019 Declaration, no admitted insurer shall cancel:
Sky Fire
94553, 9 4572, 94525, and
94569.
[Old] Water Fire
92404, 92346, and 92322.
Eagle Fire  (Riverside County)8
92881, 92503.
The fire perimeter shall be determined by the Department of Forestry and Fire Protection.
"""


def test_zip_blocks_headings_dates_and_spans():
    blocks = zip_blocks(DOC)
    assert [b.name for b in blocks] == ["Sky", "Old Water", "Eagle"]
    assert blocks[0].date == date(2019, 10, 27) and blocks[0].zips == ["94553", "94525", "94569"]
    assert blocks[0].span == "Sky Fire\n94553, 9 4572, 94525, and\n94569." and blocks[0].span in DOC
    assert (
        fire_name("SHF Lightning Fires 2020") == "SHF Lightning" and fire_name("Slater Fire (including Devil Fires)") == "Slater"
    )


def test_expand_fills_missing_fires_and_folds_yearless_mentions():
    x = Extraction(
        entities=[
            Entity(mention="Ricardo Lara", type="Official"),
            Entity(mention="Sky Fire 2019", type="Fire"),
            Entity(mention="Sky Fire", type="Fire"),
            Entity(mention="Sky Fire moratorium 2019-10-27", type="Moratorium"),
            Entity(mention="94553", type="ZIP"),
        ],
        edges=[
            Edge(
                src_mention="Sky Fire",
                rel="TRIGGERED",
                dst_mention="Sky Fire moratorium 2019-10-27",
                span="Sky Fire 94553",
                confidence=0.9,
            ),
            Edge(
                src_mention="Ricardo Lara",
                rel="ISSUED",
                dst_mention="Sky Fire moratorium 2019-10-27",
                span="Sky Fire 94553",
                confidence=0.9,
            ),
            Edge(
                src_mention="94553",
                rel="PROTECTED_BY",
                dst_mention="Sky Fire moratorium 2019-10-27",
                span="Sky Fire 94553",
                confidence=0.9,
            ),
        ],
    )
    out = expand(x, zip_blocks(DOC))
    keys = {(e.src_mention, e.rel, e.dst_mention) for e in out.edges}
    assert ("Sky Fire 2019", "TRIGGERED", "Sky Fire moratorium 2019-10-27") in keys and (
        "Sky Fire",
        "TRIGGERED",
        "Sky Fire moratorium 2019-10-27",
    ) not in keys
    assert ("94525", "PROTECTED_BY", "Sky Fire moratorium 2019-10-27") in keys
    assert ("Old Water Fire 2019", "TRIGGERED", "Old Water Fire moratorium 2019-10-27") in keys
    assert ("Ricardo Lara", "ISSUED", "Eagle Fire moratorium 2019-10-27") in keys
    assert ("92881", "PROTECTED_BY", "Eagle Fire moratorium 2019-10-27") in keys
    added = next(e for e in out.edges if e.src_mention == "92404")
    assert added.props == {"expanded_from": "zip_block"} and added.valid_to == date(2020, 10, 27) and added.span in DOC
    assert next(e for e in out.edges if e.src_mention == "94553").props == {}  # the model's own edge is kept
    assert "Sky Fire" not in {e.mention for e in out.entities}


def test_anchor_prompt_view_lists_blocks_without_zips():
    text = anchors(DOC).for_prompt()
    assert '"fire_blocks"' in text and '"heading": "Sky Fire"' in text and "94525" not in text.split('"fire_blocks"')[1]


def test_canonical_mentions_fold_variants():
    from extraction_service.expand import canonical_mentions

    ents = [
        Entity(mention="Bobcat", type="Fire"),
        Entity(mention="Bobcat Fire", type="Fire"),
        Entity(mention="Bobcat Fire 2020", type="Fire"),
        Entity(mention="Eagle Fire (Lake County) 2019", type="Fire"),
        Entity(mention="Water Fire 2019", type="Fire"),
        Entity(mention="Old Water Fire 2019", type="Fire"),
        Entity(mention="lwood Fire moratorium 2019-10-11", type="Moratorium"),
        Entity(mention="Sandalwood Fire moratorium 2019-10-11", type="Moratorium"),
        Entity(mention="Slater Fire (Del Norte County) moratorium 2020-09-25", type="Moratorium"),
        Entity(mention="SHF Lightning Fires 2020 2020", type="Fire"),
        Entity(mention="SHF Lightning Fires 2020 moratorium 2020-08-18", type="Moratorium"),
    ]
    assert canonical_mentions(Extraction(entities=ents, edges=[])) == {
        "Bobcat Fire": "Bobcat Fire 2020",
        "Eagle Fire (Lake County) 2019": "Eagle Fire 2019",
        "Water Fire 2019": "Old Water Fire 2019",
        "lwood Fire moratorium 2019-10-11": "Sandalwood Fire moratorium 2019-10-11",
        "Slater Fire (Del Norte County) moratorium 2020-09-25": "Slater Fire moratorium 2020-09-25",
        "SHF Lightning Fires 2020 2020": "SHF Lightning Fire 2020",
        "SHF Lightning Fires 2020 moratorium 2020-08-18": "SHF Lightning Fire moratorium 2020-08-18",
    }
