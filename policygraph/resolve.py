import json
import re
from dataclasses import asdict, dataclass

import pandas as pd

from policygraph import CONFIG, EXTRACTIONS, NORMALIZED
from policygraph.util import load_yaml

ZIP_RE = re.compile(r"^\d{5}$")
BILL_RE = re.compile(r"^(SB|AB)\s?(\d+)$", re.I)
FIRE_RE = re.compile(r"^(.+?) Fire (\d{4})$", re.I)
MORATORIUM_RE = re.compile(r"^(.+?) Fire moratorium (\d{4}-\d{2}-\d{2})$", re.I)


@dataclass(frozen=True)
class Resolved:
    mention: str
    entity_id: str
    method: str
    confidence: float


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def canonical(mention: str, etype: str, aliases: dict[str, str]) -> Resolved | None:
    m = mention.strip()
    if etype == "ZIP" and ZIP_RE.match(m):
        return Resolved(m, f"zip:{m}", "canonical", 1.0)
    if etype == "Regulation" and (b := BILL_RE.match(m)):
        return Resolved(m, f"bill:ca:{b.group(1).upper()}{b.group(2)}", "canonical", 1.0)
    if etype == "Fire" and (f := FIRE_RE.match(m)):
        return Resolved(m, f"fire:{slug(f.group(1))}:{f.group(2)}", "canonical", 1.0)
    if etype == "Moratorium" and (mo := MORATORIUM_RE.match(m)):
        return Resolved(m, f"moratorium:{mo.group(2)}:{slug(mo.group(1))}", "canonical", 1.0)
    if (eid := aliases.get(m.lower())) is not None:
        return Resolved(m, eid, "alias", 0.98)
    return None


def pending(mention: str, etype: str) -> Resolved:
    return Resolved(mention, f"pending:{etype.lower()}:{slug(mention)}", "unresolved", 0.0)


def resolve_all(mentions: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rows = [asdict(canonical(m.mention, m.type, aliases) or pending(m.mention, m.type)) for m in mentions.itertuples()]
    return pd.DataFrame(rows).drop_duplicates("mention")


def run() -> None:
    manifest = load_yaml(CONFIG / "extraction_manifest.yaml")
    aliases = {a.lower(): eid for a, eid in load_yaml(CONFIG / "aliases.yaml").items()}
    ents = [e for x in manifest["extractions"] for e in json.loads((EXTRACTIONS / f"{x}.json").read_text())["entities"]]
    resolve_all(pd.DataFrame(ents), aliases).to_parquet(NORMALIZED / "resolved.parquet", index=False)
