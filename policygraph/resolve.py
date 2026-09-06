import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

import httpx
import pandas as pd

from policygraph import CONFIG, EXTRACTIONS
from policygraph.util import dump_yaml, load_yaml

SERVICE = os.environ.get("EXTRACTION_SERVICE_URL", "http://localhost:8000")
PINNED = CONFIG / "resolutions.yaml"  # every answer the service gave, committed so `make resolve` replays offline
ZIP_RE = re.compile(r"^\d{5}$")
BILL_RE = re.compile(r"^(SB|AB)\s?(\d+)$", re.I)
FIRE_RE = re.compile(r"^(.+?) Fire (\d{4})$", re.I)
MORATORIUM_RE = re.compile(r"^(.+?) Fire moratorium (\d{4}-\d{2}-\d{2})$", re.I)
Ask = Callable[[list[dict], list[dict]], list[dict]]


@dataclass(frozen=True)
class Resolved:
    mention: str
    type: str
    entity_id: str
    method: str
    confidence: float


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def canonical(mention: str, etype: str) -> Resolved | None:
    """The returned mention is the original string: the graph looks edges up by the artifact's exact mention."""
    m = mention.strip()
    if etype == "ZIP" and ZIP_RE.match(m):
        return Resolved(mention, etype, f"zip:{m}", "canonical", 1.0)
    if etype == "Regulation" and (b := BILL_RE.match(m)):
        return Resolved(mention, etype, f"bill:ca:{b.group(1).upper()}{b.group(2)}", "canonical", 1.0)
    if etype == "Fire" and (f := FIRE_RE.match(m)):
        return Resolved(mention, etype, f"fire:{slug(f.group(1))}:{f.group(2)}", "canonical", 1.0)
    if etype == "Moratorium" and (mo := MORATORIUM_RE.match(m)):
        return Resolved(mention, etype, f"moratorium:{mo.group(2)}:{slug(mo.group(1))}", "canonical", 1.0)
    return None


def alias_table(entities: list[dict]) -> dict[tuple[str, str], str]:
    return {(a.lower(), e["type"]): e["id"] for e in entities for a in (e["name"], *e["aliases"])}


def alias(mention: str, etype: str, aliases: dict[tuple[str, str], str]) -> Resolved | None:
    eid = aliases.get((mention.strip().lower(), etype))
    return Resolved(mention, etype, eid, "alias", 0.98) if eid else None


def pending(mention: str, etype: str) -> Resolved:
    return Resolved(mention, etype, f"pending:{etype.lower()}:{slug(mention)}", "unresolved", 0.0)


def from_pin(pin: dict) -> Resolved:
    if pin["entity_id"] is None:
        return pending(pin["mention"], pin["type"])
    return Resolved(pin["mention"], pin["type"], pin["entity_id"], pin["method"], pin["confidence"])


def ask_service(mentions: list[dict], candidates: list[dict]) -> list[dict]:
    with httpx.Client(base_url=SERVICE, timeout=600) as c:
        r = c.post("/v1/resolve", json={"mentions": mentions, "candidates": candidates})
        r.raise_for_status()
        return r.json()


def resolve_all(mentions: pd.DataFrame, entities: list[dict], pins: dict[tuple[str, str], dict], ask: Ask | None) -> pd.DataFrame:
    """Cheapest first: canonical key, alias table, pinned service answer, then the service (kNN + judge), else pending."""
    aliases, out, residual = alias_table(entities), {}, []
    for m in mentions.drop_duplicates(["mention", "type"]).itertuples():
        key = (m.mention, m.type)
        if r := canonical(*key) or alias(*key, aliases):
            out[key] = r
        elif key in pins:
            out[key] = from_pin(pins[key])
        else:
            residual.append({"mention": m.mention, "type": m.type, "context": m.context})
    if residual and ask is not None:
        cands = [{"entity_id": e["id"], "type": e["type"], "name": e["name"], "description": e["description"]} for e in entities]
        for pin in ask(residual, cands):
            pins[(pin["mention"], pin["type"])] = pin
            out[(pin["mention"], pin["type"])] = from_pin(pin)
    for r in residual:
        out.setdefault((r["mention"], r["type"]), pending(r["mention"], r["type"]))
    return pd.DataFrame([asdict(r) for r in out.values()])


def mentions_in(artifact: dict) -> pd.DataFrame:
    ctx = {}
    for e in artifact["edges"]:
        ctx.setdefault(e["src_mention"], e["span"])
        ctx.setdefault(e["dst_mention"], e["span"])
    return pd.DataFrame(
        [{"mention": e["mention"], "type": e["type"], "context": ctx.get(e["mention"], "")} for e in artifact["entities"]]
    )


def run(force: bool = False) -> None:
    manifest = load_yaml(CONFIG / "extraction_manifest.yaml")
    entities = load_yaml(CONFIG / "entities.yaml")["entities"]
    pins = {} if force else {(p["mention"], p["type"]): p for p in (load_yaml(PINNED) if PINNED.exists() else [])}
    arts = [json.loads((EXTRACTIONS / f"{x}.json").read_text()) for x in manifest["extractions"]]
    mentions = pd.concat([mentions_in(a) for a in arts], ignore_index=True)
    ask = ask_service if os.environ.get("EXTRACTION_SERVICE_URL") else None
    df = resolve_all(mentions, entities, pins, ask)
    seen = set(zip(mentions.mention, mentions.type, strict=True))
    dump_yaml(
        PINNED, sorted((p for p in pins.values() if (p["mention"], p["type"]) in seen), key=lambda p: (p["type"], p["mention"]))
    )
    df.to_parquet(EXTRACTIONS.parent / "normalized" / "resolved.parquet", index=False)
    print(df.method.value_counts().to_dict())
