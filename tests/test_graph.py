from policygraph.graph import window


def test_moratorium_window_filled_from_id():
    assert window({"valid_from": None, "valid_to": None}, "moratorium:2020-09-25:slater") == ("2020-09-25", "2021-09-25")


def test_explicit_dates_kept():
    e = {"valid_from": "2025-01-07", "valid_to": "2026-01-07"}
    assert window(e, "moratorium:2025-01-07:eaton") == ("2025-01-07", "2026-01-07")


def test_non_moratorium_left_alone():
    assert window({"valid_from": None, "valid_to": None}, "bill:ca:SB824") == (None, None)


def test_humanize_rule_minted_ids():
    from policygraph.names import humanize

    places = {"94549": "Lafayette"}
    assert humanize("fire:scu-lightning-complex:2020", places) == "SCU Lightning Complex Fire 2020"
    assert humanize("moratorium:2019-10-27:sky", places) == "Sky Fire moratorium 2019-10-27"
    assert humanize("zip:94549", places) == "Lafayette 94549" and humanize("zip:90001", places) == "90001"
    assert (
        humanize("bill:ca:SB824", places) == "SB 824"
        and humanize("pending:insurer:acme-mutual", places) == "acme mutual (unresolved)"
    )
