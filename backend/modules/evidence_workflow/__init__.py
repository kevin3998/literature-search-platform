"""Evidence-grounded workflow core contracts, profiles, retrieval, extraction, enrichment, reports, ranking, and storage.

M1 exposes data contracts and pure adapters. M2 adds artifact-first card
storage. M3/M4 add task profiles and retrieval seed adapters. M5 adds initial
card extraction. M6 adds role/entity/relation enrichment. M6.5 adds a minimal
topic-to-evidence report slice. M7 adds deterministic evidence ranking and
selection. This package does not register a platform
module or touch workflow execution.
"""
from .schemas import (
    EVIDENCE_ROLES,
    SOURCE_ASSET_TYPES,
    EvidenceCard,
    EvidenceCardSeed,
    EvidenceEntities,
    EvidenceRelation,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
    deterministic_card_id,
    deterministic_seed_id,
    evidence_card_seed_from_candidate,
    validate_evidence_card,
    validate_evidence_card_seed,
)
from .store import EvidenceCardStore
from .task_profiles import (
    DEFAULT_TASK_PROFILE_ID,
    TaskProfile,
    build_scope_lock,
    get_task_profile,
    list_task_profiles,
    resolve_task_profile,
)
from .retrieval import (
    EvidenceSourceCandidatePacket,
    retrieve_source_candidates,
    source_candidate_packet_from_acquisition,
)
from .extraction import (
    INITIAL_EXTRACTION_VERSION,
    EvidenceExtractionResult,
    extract_initial_card,
    extract_initial_cards,
    save_initial_extraction_result,
)
from .prompts import INITIAL_EXTRACTION_SYSTEM_PROMPT, build_initial_extraction_messages
from .prompts import ROLE_ENTITY_RELATION_SYSTEM_PROMPT, build_role_entity_relation_messages
from .classification import (
    ROLE_ENRICHMENT_VERSION,
    EvidenceEnrichmentResult,
    compute_role_coverage,
    enrich_evidence_card,
    enrich_evidence_cards,
    save_enrichment_result,
)
from .minimal_report import (
    MINIMAL_REPORT_VERSION,
    MinimalTopicEvidenceReport,
    build_minimal_topic_to_evidence_report,
    render_minimal_topic_to_evidence_markdown,
    run_minimal_topic_to_evidence_slice,
    save_minimal_topic_to_evidence_report,
)
from .ranking import (
    EVIDENCE_SELECTION_VERSION,
    EvidenceRankingConfig,
    EvidenceSelectionResult,
    RankedEvidenceCard,
    compute_selection_coverage,
    rank_evidence_cards,
    save_selection_result,
    select_representative_evidence,
)

__all__ = [
    "EVIDENCE_ROLES",
    "SOURCE_ASSET_TYPES",
    "EvidenceCard",
    "EvidenceCardSeed",
    "EvidenceEntities",
    "EvidenceRelation",
    "EvidenceRelevance",
    "EvidenceSource",
    "EvidenceSupport",
    "deterministic_card_id",
    "deterministic_seed_id",
    "evidence_card_seed_from_candidate",
    "validate_evidence_card",
    "validate_evidence_card_seed",
    "EvidenceCardStore",
    "DEFAULT_TASK_PROFILE_ID",
    "TaskProfile",
    "build_scope_lock",
    "get_task_profile",
    "list_task_profiles",
    "resolve_task_profile",
    "EvidenceSourceCandidatePacket",
    "retrieve_source_candidates",
    "source_candidate_packet_from_acquisition",
    "INITIAL_EXTRACTION_VERSION",
    "EvidenceExtractionResult",
    "extract_initial_card",
    "extract_initial_cards",
    "save_initial_extraction_result",
    "INITIAL_EXTRACTION_SYSTEM_PROMPT",
    "build_initial_extraction_messages",
    "ROLE_ENTITY_RELATION_SYSTEM_PROMPT",
    "build_role_entity_relation_messages",
    "ROLE_ENRICHMENT_VERSION",
    "EvidenceEnrichmentResult",
    "compute_role_coverage",
    "enrich_evidence_card",
    "enrich_evidence_cards",
    "save_enrichment_result",
    "MINIMAL_REPORT_VERSION",
    "MinimalTopicEvidenceReport",
    "build_minimal_topic_to_evidence_report",
    "render_minimal_topic_to_evidence_markdown",
    "run_minimal_topic_to_evidence_slice",
    "save_minimal_topic_to_evidence_report",
    "EVIDENCE_SELECTION_VERSION",
    "EvidenceRankingConfig",
    "EvidenceSelectionResult",
    "RankedEvidenceCard",
    "compute_selection_coverage",
    "rank_evidence_cards",
    "save_selection_result",
    "select_representative_evidence",
]
