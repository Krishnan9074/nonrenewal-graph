import pytest

from policygraph.fetch import expand


def test_expand_env(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "k1")
    assert expand("https://x/?key=${CENSUS_API_KEY}") == "https://x/?key=k1"


def test_expand_unset_fails(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(ValueError):
        expand("https://x/?key=${CENSUS_API_KEY}")
