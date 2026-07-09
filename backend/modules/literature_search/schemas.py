from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = None
    evidence_per_article_limit: Optional[int] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    site: Optional[str] = None
    journal: Optional[str] = None
    collection: Optional[str] = None
    scope: Optional[str] = None
    profile: Optional[str] = None
    section: Optional[str] = None
    kind: Optional[str] = None
    retrieval: Optional[str] = None
    expand_assets: Optional[bool] = None


class SessionLinkMixin(BaseModel):
    session_id: Optional[str] = None
    turn_id: Optional[str] = None


class PaperLookupRequest(BaseModel):
    doi: Optional[str] = None
    paper_id: Optional[str] = None
    article_id: Optional[int] = None
    section: Optional[str] = None


class EvidenceExpandRequest(BaseModel):
    document_id: Optional[int] = None
    doi: Optional[str] = None
    paper_id: Optional[str] = None
    label: Optional[str] = None
    pack_path: Optional[str] = None
    evidence_id: Optional[str] = None


class PackRequest(SessionLinkMixin):
    query: str
    limit: int = 8
    budget: int = 12000
    collection: Optional[str] = None
    scope: str = "library"
    article_limit: Optional[int] = None
    evidence_limit: Optional[int] = None
    per_article_evidence_limit: Optional[int] = None
    task: Optional[str] = None
    append_to: Optional[str] = None
    expand_assets: bool = False


class TaskRequest(SessionLinkMixin):
    question: str
    budget: int = 20000
    scope: str = "library"


class RunRequest(TaskRequest):
    with_extract: bool = False
    with_compare: bool = False
    sort_by: Optional[str] = None
    verify_answer: Optional[str] = None
    with_notes: bool = False
    with_synthesis: bool = False
    verify_synthesis: bool = False
    with_quality: bool = False
    run_id: Optional[str] = None


class ExtractRequest(SessionLinkMixin):
    query: str
    budget: int = 12000
    pack_path: Optional[str] = None
    task_id: Optional[str] = None


class CompareRequest(SessionLinkMixin):
    query: str
    extract_id: Optional[str] = None
    sort_by: Optional[str] = None
    budget: int = 12000


class AnalysisBundleRequest(SessionLinkMixin):
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    pack_path: Optional[str] = None


class VerifyAnswerRequest(SessionLinkMixin):
    answer_text: Optional[str] = None
    answer_path: Optional[str] = None
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    pack_path: Optional[str] = None


class NotesRequest(SessionLinkMixin):
    run_id: str


class SynthesizeRequest(SessionLinkMixin):
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    verify: bool = False


class QualityRequest(SessionLinkMixin):
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    strict: bool = False


class VectorBuildRequest(SessionLinkMixin):
    provider: str = "local"
    model: Optional[str] = None
    kinds: Optional[list[str]] = None
    include_table_rows: bool = False


class JobCreateResponse(BaseModel):
    job_id: str
    status: str = "queued"
    stream_url: str


class ArtifactSummary(BaseModel):
    artifact_id: str
    artifact_type: str
    title: str
    json_path: Optional[str] = None
    markdown_path: Optional[str] = None
    created_at: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
