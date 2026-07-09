from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperCandidate:
    id: str
    title: str
    source: str
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    abstract: str | None = None
    venue: str | None = None
    citation_count: int | None = None
    verification: str = "verify_pending"
    query: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "year": self.year,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "url": self.url,
            "abstract": self.abstract,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "verification": self.verification,
            "query": self.query,
            "metadata": self.metadata,
        }


@dataclass
class QueryPacket:
    queries_by_idea: dict[str, list[str]]
    dropped_template_terms: list[str]
    year_from: int
    year_to: int

    @property
    def flat_queries(self) -> list[str]:
        out: list[str] = []
        for queries in self.queries_by_idea.values():
            for query in queries:
                if query not in out:
                    out.append(query)
        return out


@dataclass
class VerificationSummary:
    verdict: str
    hallucination_rate: float
    pending_rate: float
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "hallucination_rate": self.hallucination_rate,
            "pending_rate": self.pending_rate,
            "warnings": self.warnings,
        }


@dataclass
class VerificationResult:
    papers: list[PaperCandidate]
    verdict: str
    hallucination_rate: float
    pending_rate: float
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> VerificationSummary:
        return VerificationSummary(self.verdict, self.hallucination_rate, self.pending_rate, list(self.warnings))


@dataclass
class NoveltySearchPacket:
    candidates: list[PaperCandidate]
    source_status: dict[str, Any]
    verification_summary: VerificationSummary
    query_quality: dict[str, Any]

    def as_tuple(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        status = dict(self.source_status)
        status["verification_summary"] = self.verification_summary.as_dict()
        status["query_quality"] = self.query_quality
        return [c.as_dict() for c in self.candidates], status
