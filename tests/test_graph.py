from policygraph.graph import window


def test_moratorium_window_filled_from_id():
    assert window({"valid_from": None, "valid_to": None}, "moratorium:2020-09-25:slater") == ("2020-09-25", "2021-09-25")


def test_explicit_dates_kept():
    e = {"valid_from": "2025-01-07", "valid_to": "2026-01-07"}
    assert window(e, "moratorium:2025-01-07:eaton") == ("2025-01-07", "2026-01-07")


def test_non_moratorium_left_alone():
    assert window({"valid_from": None, "valid_to": None}, "bill:ca:SB824") == (None, None)
