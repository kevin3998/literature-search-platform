"""Block 2: Retrieval / Evidence Acquisition.

This package turns the underlying ``ResearchSearch.search()`` output into a
first-class, auditable :class:`EvidenceAcquisitionPacket`. It never reimplements
retrieval — it wraps the raw search with:

    intent detection -> deterministic rewrite -> (bounded) recovery
    -> evidence candidate normalization -> deterministic selection
    -> coverage judgment -> packet

See ``docs/capability-blocks/block-02-retrieval-evidence-acquisition.md``.
"""
from __future__ import annotations

from modules.literature_search.retrieval.packet import build_packet
from modules.literature_search.retrieval.schemas import (
    Breadth,
    Coverage,
    EvidenceAcquisitionPacket,
    EvidenceCandidate,
    FallbackReason,
    QueryIntent,
    RewrittenQuery,
)

__all__ = [
    "build_packet",
    "Breadth",
    "Coverage",
    "EvidenceAcquisitionPacket",
    "EvidenceCandidate",
    "FallbackReason",
    "QueryIntent",
    "RewrittenQuery",
]
