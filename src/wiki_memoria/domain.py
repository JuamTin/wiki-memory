from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectContext(BaseModel):
    workspace: Path
    common_dir: Path | None = None
    bank_id: str
    directory: Path
    data_root: Path


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    timestamp: str


class MemoryDoc(BaseModel):
    rel_path: str
    title: str
    kind: str
    status: Literal["active", "superseded", "archived"] = "active"
    verified_commit: str | None = None
    tracks: list[str] = Field(default_factory=list)


class StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Slug = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]


class PageUpdate(StructuredOutput):
    slug: Slug
    title: str = Field(max_length=120)
    mode: Literal["append_section", "update_section", "create_page"]
    section_heading: str = ""
    markdown_delta: str = Field(max_length=4000)
    tracks: list[str]
    citations: list[str] = Field(min_length=1)


class Initiative(StructuredOutput):
    slug: Slug
    title: str
    status: Literal["activa", "pausada", "completada", "archivada"]
    summary: str = Field(max_length=1000)
    next_step: str = Field(max_length=300)


class Correction(StructuredOutput):
    topic: str
    previous_claim: str
    verified_truth: str
    evidence: str
    supersedes_path: str = ""


class ConsolidationPlan(StructuredOutput):
    session_summary: str = Field(max_length=600)
    durable_worth_saving: bool
    page_updates: list[PageUpdate] = Field(max_length=4)
    initiatives: list[Initiative] = Field(max_length=3)
    corrections: list[Correction] = Field(max_length=3)
