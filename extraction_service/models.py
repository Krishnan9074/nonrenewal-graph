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
    status: Literal["ok", "no_target_relations", "failed_validation"]
    rejected: list[str] = Field(default_factory=list)


class Job(BaseModel):
    run_id: str
    doc_id: str
    source: str
    text: str


class Anchors(BaseModel):
    zips: set[str]
    dates: set[date]
    bills: set[str]
