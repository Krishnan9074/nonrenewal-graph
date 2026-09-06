import pandas as pd

from policygraph.resolve import alias, alias_table, canonical, pending, resolve_all

ENTITIES = [
    {"id": "insurer:naic:25143", "type": "Insurer", "name": "State Farm General", "description": "", "aliases": ["SFG"]},
    {"id": "official:cdi:commissioner", "type": "Official", "name": "Ricardo Lara", "description": "", "aliases": []},
]
ALIASES = alias_table(ENTITIES)


def test_zip_canonical():
    assert canonical("94563", "ZIP").entity_id == "zip:94563"


def test_bill_canonical():
    assert canonical("SB 824", "Regulation").entity_id == "bill:ca:SB824"


def test_fire_and_moratorium_canonical():
    assert canonical("Eaton Fire 2025", "Fire").entity_id == "fire:eaton:2025"
    assert canonical("Eaton Fire moratorium 2025-01-07", "Moratorium").entity_id == "moratorium:2025-01-07:eaton"
    assert canonical("Eaton Fire", "Fire") is None


def test_alias_is_case_insensitive_and_typed():
    assert alias("sfg", "Insurer", ALIASES).method == "alias"
    assert alias("SFG", "Official", ALIASES) is None


def test_unresolved():
    assert canonical("Acme Mutual", "Insurer") is None
    assert pending("Acme Mutual", "Insurer").entity_id == "pending:insurer:acme-mutual"


def mentions(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{"mention": m, "type": t, "context": ""} for m, t in rows])


def test_resolve_all_uses_pins_then_service_then_pending():
    pins = {
        ("the Commissioner", "Official"): {
            "mention": "the Commissioner",
            "type": "Official",
            "entity_id": "official:cdi:commissioner",
            "method": "llm_judge",
            "confidence": 0.9,
        }
    }
    asked = []

    def ask(ms: list[dict], cands: list[dict]) -> list[dict]:
        asked.extend(m["mention"] for m in ms)
        return [{"mention": "Acme", "type": "Insurer", "entity_id": None, "method": "unresolved", "confidence": 0.0}]

    df = resolve_all(
        mentions(("94563", "ZIP"), ("SFG", "Insurer"), ("the Commissioner", "Official"), ("Acme", "Insurer")), ENTITIES, pins, ask
    )
    by = df.set_index("mention")
    assert by.loc["94563"].method == "canonical" and by.loc["SFG"].method == "alias"
    assert by.loc["the Commissioner"].method == "llm_judge" and by.loc["Acme"].entity_id == "pending:insurer:acme"
    assert asked == ["Acme"] and ("Acme", "Insurer") in pins


def test_resolve_all_offline_marks_pending():
    df = resolve_all(mentions(("Acme", "Insurer")), ENTITIES, {}, None)
    assert df.iloc[0].method == "unresolved"


def test_canonical_keeps_original_mention():
    assert canonical(" 94563 ", "ZIP").mention == " 94563 "
