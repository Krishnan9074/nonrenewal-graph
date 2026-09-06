import re

FIRE_RE = re.compile(r"^fire:([a-z0-9-]+):(\d{4})$")
MOR_RE = re.compile(r"^moratorium:(\d{4}-\d{2}-\d{2}):([a-z0-9-]+)$")
FIXED = {
    "market:ca:voluntary": "California voluntary market (all admitted insurers)",
    "fhsz:very_high": "FHSZ Very High",
    "fhsz:high": "FHSZ High",
    "fhsz:moderate": "FHSZ Moderate",
}


def title(slug: str) -> str:
    return " ".join(w.upper() if w in {"scu", "lnu", "czu", "shf", "sqf"} else w.capitalize() for w in slug.split("-"))


def humanize(entity_id: str, places: dict[str, str]) -> str:
    """Readable name for ids that are minted by rule and so have no entry in config/entities.yaml."""
    if entity_id in FIXED:
        return FIXED[entity_id]
    if entity_id.startswith("zip:"):
        z = entity_id[4:]
        return f"{places[z]} {z}" if z in places else z
    if entity_id.startswith("bill:ca:"):
        return re.sub(r"^([A-Z]+)(\d+)$", r"\1 \2", entity_id[8:])
    if m := FIRE_RE.match(entity_id):
        return f"{title(m.group(1))} Fire {m.group(2)}"
    if m := MOR_RE.match(entity_id):
        return f"{title(m.group(2))} Fire moratorium {m.group(1)}"
    if entity_id.startswith("pending:"):
        return entity_id.split(":", 2)[2].replace("-", " ") + " (unresolved)"
    return entity_id
