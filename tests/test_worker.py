from extraction_service.models import Extraction
from extraction_service.worker import extraction_id, merge, process


class Fake:
    model_id = "fake"

    def __init__(self, out: dict):
        self.out, self.calls = out, 0

    def structured(self, prompt: str, schema: dict) -> dict:
        self.calls += 1
        return self.out


DOC = "DATE: January 9, 2025. No insurer shall issue a notice of non-renewal in ZIP Codes 91001, 91006."
GOOD = {
    "entities": [{"mention": "91001", "type": "ZIP"}, {"mention": "Eaton moratorium", "type": "Moratorium"}],
    "edges": [
        {
            "src_mention": "91001",
            "rel": "PROTECTED_BY",
            "dst_mention": "Eaton moratorium",
            "valid_from": "2025-01-07",
            "valid_to": "2026-01-07",
            "span": "notice of non-renewal in ZIP Codes 91001",
            "confidence": 0.9,
        }
    ],
}


def test_process_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("extraction_service.store.STORE", tmp_path)
    art = process("doc1", DOC, Fake(GOOD))
    assert art.status == "ok" and art.extraction_id == extraction_id("doc1", "fake")


def test_process_cache_hit_and_force(tmp_path, monkeypatch):
    monkeypatch.setattr("extraction_service.store.STORE", tmp_path)
    adapter = Fake(GOOD)
    art = process("doc1", DOC, adapter)
    (tmp_path / f"{art.extraction_id}.json").write_text(art.model_dump_json())
    process("doc1", DOC, adapter)
    assert adapter.calls == 1
    process("doc1", DOC, adapter, force=True)
    assert adapter.calls == 2


def test_bad_span_retries_then_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("extraction_service.store.STORE", tmp_path)
    bad = {**GOOD, "edges": [{**GOOD["edges"][0], "span": "paraphrased text here"}]}
    adapter = Fake(bad)
    art = process("doc2", DOC, adapter)
    assert art.status == "failed_validation" and adapter.calls == 2 and "span" in art.rejected[0]


def test_merge_keeps_highest_confidence():
    a = Extraction.model_validate(GOOD)
    b = Extraction.model_validate({**GOOD, "edges": [{**GOOD["edges"][0], "confidence": 0.5}]})
    assert merge([b, a]).edges[0].confidence == 0.9
