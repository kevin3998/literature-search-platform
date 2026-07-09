"""Dataclass contracts for the evidence acquisition packet (Block 2).

The platform returns plain dicts everywhere (see ``service.py``); these
dataclasses exist only to keep the packet shape explicit and self-documenting.
``as_dict`` recursively converts to the wire form via :func:`dataclasses.asdict`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class QueryIntent:
    """What kind of retrieval task the user's question is."""

    type: str = "unknown"
    confidence: float = 0.0
    detected_entities: dict[str, Any] = field(default_factory=dict)
    suggested_filters: dict[str, Any] = field(default_factory=dict)
    suggested_retrieval: str = "hybrid"


@dataclass
class RewrittenQuery:
    """One concrete retrieval expression derived from the original query."""

    query: str
    reason: str = ""
    retrieval_hint: str | None = None
    filters_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceCandidate:
    """A flattened, citable piece of evidence.

    ``evidence_id`` is the underlying ``E{document_id}`` verbatim — it is the id
    the citation audit, session memory, and agent loop already depend on. Block 2
    normalizes the surrounding metadata; it never re-mints this id.
    """

    evidence_id: str
    paper_id: str | None = None
    article_id: int | None = None
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    journal: str | None = None
    kind: str | None = None
    section: str | None = None
    section_id: str | None = None
    chunk_index: int | None = None
    snippet: str | None = None
    expanded_context: str | None = None
    confidence: float | None = None
    relevance_score: float | None = None
    source_path: str | None = None
    source_locator: dict[str, Any] | None = None
    asset_path: str | None = None
    asset_label: str | None = None
    retrieval_source: str | None = None
    query_match_reason: str | None = None
    selection_score: float | None = None
    cluster: str | None = None
    # True when this candidate is inlined into the LLM prompt — the citation
    # boundary. False candidates stay in the packet/record/browsing pool only.
    in_llm_context: bool = False


@dataclass
class FallbackReason:
    """Why a degradation or recovery happened. Always explicit and auditable."""

    code: str
    message: str = ""
    triggered_by: str = ""
    attempted_recoveries: list[str] = field(default_factory=list)
    final_status: str = ""


@dataclass
class Coverage:
    """Whether the acquired evidence is enough to answer."""

    status: str = "none"  # sufficient | partial | weak | none
    distinct_paper_count: int = 0
    evidence_count: int = 0
    year_range: list[int | None] = field(default_factory=lambda: [None, None])
    sections_covered: list[str] = field(default_factory=list)
    evidence_kinds: list[str] = field(default_factory=list)
    dominant_paper_ratio: float = 0.0
    candidate_paper_count: int = 0
    selected_evidence_count: int = 0
    breadth_limited: bool = False
    deep_research_suggested: bool = False
    missing_aspects: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)


@dataclass
class Breadth:
    """Retrieval breadth vs LLM context budget (Block 2 §8)."""

    candidate_paper_count: int = 0
    candidate_evidence_count: int = 0
    selected_evidence_count: int = 0
    llm_context_evidence_count: int = 0
    estimated_total_matches: int = 0
    estimate_is_lower_bound: bool = False
    cluster_count: int = 0
    clusters_covered: list[str] = field(default_factory=list)
    missing_clusters: list[str] = field(default_factory=list)
    cluster_method: str = "lexical_approx"
    breadth_limited: bool = False
    deep_research_suggested: bool = False
    breadth_notes: list[str] = field(default_factory=list)


@dataclass
class EvidenceAcquisitionPacket:
    """Block 2's unified, auditable output shared across consumers."""

    query: str
    query_intent: dict[str, Any]
    query_plan: dict[str, Any]
    rewritten_queries: list[dict[str, Any]]
    retrieval_requested: str | None
    retrieval_used: str | None
    filters: dict[str, Any]
    fallback_reason: dict[str, Any] | None
    results: list[dict[str, Any]]
    evidence_candidates: list[dict[str, Any]]
    expanded_assets: list[dict[str, Any]]
    coverage: dict[str, Any]
    breadth: dict[str, Any]
    coverage_notes: list[str]
    warnings: list[str]
    debug: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
