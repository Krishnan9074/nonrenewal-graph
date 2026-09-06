import hashlib
import json
from collections.abc import Callable

import numpy as np

from extraction_service import STORE
from extraction_service.models import Candidate, Mention, Resolution

ACCEPT, MARGIN = 0.92, 0.05  # cosine to accept on embeddings alone, and the gap to the runner-up
JUDGE_BAND, JUDGE_ACCEPT = 0.75, 0.85  # below the band nothing is asked; the judge must be this sure
RESOLVE_V = "1"
JUDGE_SCHEMA = {
    "type": "object",
    "required": ["same_entity", "confidence"],
    "additionalProperties": False,
    "properties": {"same_entity": {"type": "boolean"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
}
JUDGE_PROMPT = """Do the mention and the candidate refer to the same real-world {type}?
Mention: {mention}
Mention context: {context}
Candidate: {name} — {description}
Answer with same_entity and your confidence."""

Judge = Callable[[str, dict], dict]


def cosines(q: np.ndarray, m: np.ndarray) -> np.ndarray:
    return (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q))


def ranked(mention_vec: np.ndarray, cands: list[Candidate], cand_vecs: np.ndarray) -> list[tuple[Candidate, float]]:
    return sorted(zip(cands, cosines(mention_vec, cand_vecs).tolist(), strict=True), key=lambda t: -t[1])


def judge_one(m: Mention, c: Candidate, judge: Judge) -> float:
    prompt = JUDGE_PROMPT.format(
        type=m.type, mention=m.mention, context=m.context or "(none)", name=c.name, description=c.description
    )
    out = judge(prompt, JUDGE_SCHEMA)
    return float(out["confidence"]) if out["same_entity"] else 0.0


def decide(m: Mention, order: list[tuple[Candidate, float]], judge: Judge, models: tuple[str, str]) -> Resolution:
    base = {"mention": m.mention, "type": m.type, "embed_model": models[0], "judge_model": models[1]}
    if not order:
        return Resolution(**base, entity_id=None, method="unresolved", confidence=0.0)
    (top, s1), s2 = order[0], order[1][1] if len(order) > 1 else 0.0
    if s1 >= ACCEPT and s1 - s2 >= MARGIN:
        return Resolution(**base, entity_id=top.entity_id, method="embedding", confidence=s1, nearest=top.entity_id, score=s1)
    for c, s in order[:2]:
        if s >= JUDGE_BAND and (p := judge_one(m, c, judge)) >= JUDGE_ACCEPT:
            return Resolution(**base, entity_id=c.entity_id, method="llm_judge", confidence=p, nearest=top.entity_id, score=s1)
    return Resolution(**base, entity_id=None, method="unresolved", confidence=0.0, nearest=top.entity_id, score=s1)


def cache_key(m: Mention, cands: list[Candidate], models: tuple[str, str]) -> str:
    body = [m.model_dump(), sorted((c.model_dump() for c in cands), key=lambda c: c["entity_id"]), *models, RESOLVE_V]
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def resolve(
    mentions: list[Mention], cands: list[Candidate], embed: Callable, judge: Judge, models: tuple[str, str]
) -> list[Resolution]:
    """Embedding kNN within type, then an LLM judge for the ambiguous band; every answer is cached by its inputs."""
    cache = STORE / "resolutions"
    cache.mkdir(parents=True, exist_ok=True)
    keys = [cache_key(m, [c for c in cands if c.type == m.type], models) for m in mentions]
    todo = [m for m, k in zip(mentions, keys, strict=True) if not (cache / f"{k}.json").exists()]
    if todo:
        vecs = np.array(embed([m.mention for m in todo] + [f"{c.name} — {c.description}" for c in cands]))
        mv, cv = vecs[: len(todo)], vecs[len(todo) :]
        for m, v in zip(todo, mv, strict=True):
            same = [i for i, c in enumerate(cands) if c.type == m.type]
            order = ranked(v, [cands[i] for i in same], cv[same]) if same else []
            r = decide(m, order, judge, models)
            (cache / f"{cache_key(m, [cands[i] for i in same], models)}.json").write_text(r.model_dump_json(indent=1))
    return [Resolution.model_validate_json((cache / f"{k}.json").read_text()) for k in keys]
