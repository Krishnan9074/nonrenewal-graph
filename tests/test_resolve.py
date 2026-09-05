from policygraph.resolve import canonical, pending


def test_zip_canonical():
    assert canonical("94563", "ZIP", {}).entity_id == "zip:94563"


def test_bill_canonical():
    assert canonical("SB 824", "Regulation", {}).entity_id == "bill:ca:SB824"


def test_fire_and_moratorium_canonical():
    assert canonical("Eaton Fire 2025", "Fire", {}).entity_id == "fire:eaton:2025"
    assert canonical("Eaton Fire moratorium 2025-01-07", "Moratorium", {}).entity_id == "moratorium:2025-01-07:eaton"
    assert canonical("Eaton Fire", "Fire", {}) is None


def test_alias():
    assert canonical("State Farm General", "Insurer", {"state farm general": "insurer:naic:25143"}).method == "alias"


def test_unresolved():
    assert canonical("Acme Mutual", "Insurer", {}) is None
    assert pending("Acme Mutual", "Insurer").entity_id == "pending:insurer:acme-mutual"
