import pytest

from policygraph import fetch
from policygraph.fetch import Fetched, conditional, expand, fetch_one


def test_expand_env(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "k1")
    assert expand("https://x/?key=${CENSUS_API_KEY}") == "https://x/?key=k1"


def test_expand_unset_fails(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(ValueError):
        expand("https://x/?key=${CENSUS_API_KEY}")


def test_conditional_headers():
    assert conditional(None) == {}
    assert conditional(Fetched("s", "u", "p", "h", etag='"e"')) == {"If-None-Match": '"e"'}
    assert conditional(Fetched("s", "u", "p", "h", last_modified="Mon")) == {"If-Modified-Since": "Mon"}


def test_fetch_one_skips_on_304(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    f = tmp_path / "s" / "abc.pdf"
    f.parent.mkdir()
    f.write_bytes(b"x")
    prior = Fetched("s", "https://x/a.pdf", str(f), "abc", etag='"e"')
    monkeypatch.setattr(fetch, "download", lambda url, p: None)
    assert fetch_one("s", "https://x/a.pdf", "pdf", prior, force=False) == (prior, "unchanged")


def test_fetch_one_without_validator_is_cached_unless_forced(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    f = tmp_path / "s" / "abc.json"
    f.parent.mkdir()
    f.write_bytes(b"x")
    prior = Fetched("s", "https://x/a.json", str(f), "abc")
    calls = []
    monkeypatch.setattr(fetch, "download", lambda url, p: calls.append(p) or (b"y", None, None))
    assert fetch_one("s", "https://x/a.json", "json", prior, force=False) == (prior, "cached")
    got, status = fetch_one("s", "https://x/a.json", "json", prior, force=True)
    assert status == "changed" and calls == [None] and got.path.endswith(".json")
