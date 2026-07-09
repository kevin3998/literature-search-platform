from __future__ import annotations

from .collection import StructuredExtractionCollectionService
from .evidence_packets import StructuredExtractionEvidencePacketService
from .exports import StructuredExtractionExportService
from .extraction_runs import StructuredExtractionRunService
from .multimodal_review import StructuredExtractionMultimodalReviewService
from .prompt_contract import StructuredExtractionPromptContractService
from .review import StructuredExtractionReviewService
from .schema_designer import StructuredExtractionSchemaDesigner
from .store import StructuredExtractionStore

structured_extraction_store = StructuredExtractionStore()
structured_extraction_collection_service = StructuredExtractionCollectionService(structured_extraction_store)
structured_extraction_schema_designer = StructuredExtractionSchemaDesigner(structured_extraction_store)
structured_extraction_prompt_contract_service = StructuredExtractionPromptContractService(structured_extraction_store)
structured_extraction_evidence_packet_service = StructuredExtractionEvidencePacketService(
    structured_extraction_store,
    structured_extraction_prompt_contract_service,
)
structured_extraction_evidence_packet_service.reap_orphaned_build_jobs()
structured_extraction_run_service = StructuredExtractionRunService(structured_extraction_store)
structured_extraction_run_service.reap_orphaned_runs()
structured_extraction_review_service = StructuredExtractionReviewService(structured_extraction_store)
structured_extraction_multimodal_review_service = StructuredExtractionMultimodalReviewService(
    structured_extraction_store,
    structured_extraction_review_service,
)
structured_extraction_export_service = StructuredExtractionExportService(
    structured_extraction_store,
    structured_extraction_review_service,
    structured_extraction_multimodal_review_service,
)

__all__ = [
    "structured_extraction_store",
    "structured_extraction_collection_service",
    "structured_extraction_schema_designer",
    "structured_extraction_prompt_contract_service",
    "structured_extraction_evidence_packet_service",
    "structured_extraction_run_service",
    "structured_extraction_review_service",
    "structured_extraction_multimodal_review_service",
    "structured_extraction_export_service",
]
