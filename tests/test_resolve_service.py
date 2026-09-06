import numpy as np

from extraction_service import resolve as r
from extraction_service.models import Candidate, Mention

MODELS = ("emb", "judge")
LARA = Candidate(entity_id="official:cdi:commissioner", type="Official", name="Ricardo Lara", description="Commissioner")
NEWSOM = Candidate(entity_id="official:ca:governor", type="Official", name="Gavin Newsom", description="Governor")
SFG = Candidate(entity_id="insurer:naic:25143", type="Insurer", name="State Farm General", description="insurer")
VEC = {
    "the Commissioner": [1, 0.1],
    "Ricardo Lara — Commissioner": [1, 0],
    "Gavin Newsom — Governor": [0, 1],
    "State Farm General — insurer": [0.5, 0.5],
}


def judge_yes(prompt: str, schema: dict) -> dict:
    return {"same_entity": True, "confidence": 0.9}


def judge_no(prompt: str, schema: dict) -> dict:
    return {"same_entity": False, "confidence": 0.9}


def test_embedding_accepts_clear_winner():
    out = r.decide(Mention(mention="x", type="Official"), [(LARA, 0.95), (NEWSOM, 0.6)], judge_no, MODELS)
    assert out.method == "embedding" and out.entity_id == LARA.entity_id and out.confidence == 0.95


def test_small_margin_goes_to_judge():
    out = r.decide(Mention(mention="x", type="Official"), [(LARA, 0.95), (NEWSOM, 0.93)], judge_yes, MODELS)
    assert out.method == "llm_judge" and out.entity_id == LARA.entity_id and out.confidence == 0.9


def test_judge_rejection_is_unresolved_with_nearest():
    out = r.decide(Mention(mention="x", type="Official"), [(LARA, 0.85)], judge_no, MODELS)
    assert out.method == "unresolved" and out.entity_id is None and out.nearest == LARA.entity_id and out.score == 0.85


def test_below_band_never_asks_judge():
    calls = []
    out = r.decide(Mention(mention="x", type="Official"), [(LARA, 0.5)], lambda p, s: calls.append(p), MODELS)
    assert out.method == "unresolved" and not calls


def test_resolve_restricts_to_type_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("extraction_service.resolve.STORE", tmp_path)
    embeds = []

    def embed(texts: list[str]) -> list[list[float]]:
        embeds.append(texts)
        return [VEC[t] for t in texts]

    m = [Mention(mention="the Commissioner", type="Official", context="said the Commissioner")]
    first = r.resolve(m, [LARA, NEWSOM, SFG], embed, judge_yes, MODELS)
    assert first[0].method == "embedding" and first[0].entity_id == LARA.entity_id
    assert np.isclose(first[0].score, 1 / np.sqrt(1.01))
    again = r.resolve(m, [LARA, NEWSOM, SFG], embed, judge_yes, MODELS)
    assert again == first and len(embeds) == 1 and len(list(tmp_path.glob("resolutions/*.json"))) == 1
