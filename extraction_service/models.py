from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["ZIP", "Insurer", "Fire", "Moratorium", "Regulation", "Official", "RateFiling", "County"]
Rel = Literal["PROTECTED_BY", "TRIGGERED", "ISSUED", "FILED", "DECIDED", "AUTHORED", "DONATED_TO"]

REL_TYPES: dict[str, tuple[set[str], set[str]]] = {
    "PROTECTED_BY": ({"ZIP"}, {"Moratorium"}),
    "TRIGGERED": ({"Fire"}, {"Moratorium"}),
    "ISSUED": ({"Official"}, {"Moratorium", "Regulation"}),
    "FILED": ({"Insurer"}, {"RateFiling"}),
    "DECIDED": ({"Official"}, {"RateFiling"}),
    "AUTHORED": ({"Official"}, {"Regulation"}),
    "DONATED_TO": ({"Insurer"}, {"Official"}),
}


class Entity(BaseModel):
    mention: str
    type: EntityType


class Edge(BaseModel):
    src_mention: str
    rel: Rel
    dst_mention: str
    valid_from: date | None = None
    valid_to: date | None = None
    props: dict = Field(default_factory=dict)
    span: str = Field(min_length=8)
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    entities: list[Entity]
    edges: list[Edge]


class Artifact(Extraction):
    extraction_id: str
    doc_id: str
    schema_v: str
    prompt_v: str
    model_id: str
    status: Literal["ok", "no_target_relations", "failed_validation", "error"]
    rejected: list[str] = Field(default_factory=list)


class Job(BaseModel):
    run_id: str
    doc_id: str
    source: str
    text: str
    force: bool = False  # bypass the extraction cache and overwrite the artifact


class ZipBlock(BaseModel):
    heading: str
    name: str
    date: date | None  # the declaration this block sits under; None outside a dated section
    zips: list[str]
    span: str


class Anchors(BaseModel):
    zips: set[str]
    dates: set[date]
    bills: set[str]
    zip_blocks: list[ZipBlock] = Field(default_factory=list)

    def for_prompt(self) -> str:
        """Headings and dates only: the model relates fires to declarations, it does not enumerate ZIPs."""
        blocks = [{"heading": b.heading, "declaration": str(b.date), "zips": len(b.zips)} for b in self.zip_blocks]
        return self.model_dump_json(exclude={"zip_blocks"})[:-1] + f', "fire_blocks": {blocks}}}'.replace("'", '"')


class Candidate(BaseModel):
    entity_id: str
    type: EntityType
    name: str
    description: str = ""


class Mention(BaseModel):
    mention: str
    type: EntityType
    context: str = ""  # a span from the document that contains the mention


class Resolution(BaseModel):
    mention: str
    type: EntityType
    entity_id: str | None
    method: Literal["embedding", "llm_judge", "unresolved"]
    confidence: float
    nearest: str | None = None  # best candidate and its cosine, kept even when rejected, for review
    score: float = 0.0
    embed_model: str
    judge_model: str


class ResolveRequest(BaseModel):
    mentions: list[Mention]
    candidates: list[Candidate]
