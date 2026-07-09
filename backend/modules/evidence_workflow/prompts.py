"""Prompt helpers for evidence workflow extraction and enrichment."""
from __future__ import annotations

from typing import Any

from .schemas import EvidenceCard, EvidenceCardSeed

INITIAL_EXTRACTION_SYSTEM_PROMPT = """You extract initial Evidence Card draft fields.

Return JSON only.
Do not add external knowledge.
Do not perform final role classification.
Do not extract entities or relations.
Use only the provided seed text or caption.
If any part is an assumption, put it in unsupported_parts.
Use support_strength only as one of: direct, indirect, weak.
Use extraction_confidence only as a number from 0 to 1.
Use unsupported_parts and warnings as arrays of strings.
"""

ROLE_ENTITY_RELATION_SYSTEM_PROMPT = """You perform Evidence Card role/entity/relation enrichment.

Return JSON only.
Do not add external knowledge.
This is not a Claim Ledger.
Use only the provided Evidence Card snippet and normalized statement.
Do not generate ideas, novelty claims, reports, or experiment plans.
Do not use a material-domain profile schema.
If anything is uncertain, put it in uncertainty or unsupported_parts.
Use primary_role and secondary_roles only from the provided Evidence Card role vocabulary.
Use support_strength only as one of: direct, indirect, weak.
Use extraction_confidence only as a number from 0 to 1.
Use unsupported_parts and warnings as arrays of strings.
Use entities as an object with only these array fields:
materials, methods, properties, metrics, values, units, conditions,
characterization_tools, mechanisms, applications.
Do not output entities as typed objects with name/type fields.
Use relations as an array of objects with subject, predicate, object,
optional qualifiers object, optional condition string, and optional confidence number.
"""


def build_initial_extraction_messages(
    seed: EvidenceCardSeed,
    *,
    topic: str,
    task_profile: Any | None = None,
) -> list[dict[str, str]]:
    task_profile_id = _profile_id(task_profile)
    source_text = seed.raw_text or seed.raw_caption or ""
    user = (
        f"Topic: {topic}\n"
        f"Task profile: {task_profile_id or 'unspecified'}\n"
        f"Seed ID: {seed.seed_id}\n"
        f"Paper ID: {seed.paper_id}\n"
        f"Source type: {seed.asset_type}\n"
        f"Source path: {seed.source_path}\n"
        f"Locator: {seed.locator}\n\n"
        "Do not add external knowledge.\n"
        "Do not perform final role classification.\n"
        "Do not extract entities or relations.\n"
        "Return JSON only with these optional fields: normalized_statement, "
        "relevance_reason, support_strength, extraction_confidence, unsupported_parts, warnings.\n\n"
        "Allowed support_strength values: direct, indirect, weak.\n"
        "extraction_confidence must be a number from 0 to 1.\n"
        "unsupported_parts and warnings must be arrays of strings.\n\n"
        f"Seed text or caption:\n{source_text}"
    )
    return [
        {"role": "system", "content": INITIAL_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_role_entity_relation_messages(
    card: EvidenceCard,
    *,
    topic: str,
    task_profile: Any | None = None,
) -> list[dict[str, str]]:
    task_profile_id = _profile_id(task_profile)
    user = (
        f"Topic: {topic}\n"
        f"Task profile: {task_profile_id or 'unspecified'}\n"
        f"Evidence ID: {card.evidence_id}\n"
        f"Seed ID: {card.seed_id}\n"
        f"Paper ID: {card.paper_id}\n"
        f"Source type: {card.source.asset_type}\n"
        f"Source path: {card.source.source_path}\n"
        f"Locator: {card.source.locator}\n"
        f"Current primary role: {card.primary_role}\n"
        f"Current secondary roles: {card.secondary_roles}\n\n"
        "Do not add external knowledge.\n"
        "This is not a Claim Ledger.\n"
        "Do not generate ideas, novelty claims, reports, or experiment plans.\n"
        "Only perform role/entity/relation enrichment for this Evidence Card.\n"
        "Do not use a domain profile schema; use only the open EvidenceEntities fields.\n"
        "Return JSON only with these optional fields: primary_role, secondary_roles, entities, "
        "relations, support_strength, extraction_confidence, uncertainty, unsupported_parts, warnings.\n\n"
        "Allowed primary_role/secondary_roles values: background, material_system, method, structure, "
        "property, performance, mechanism, characterization, comparison, limitation, condition, "
        "calculation, hypothesis, figure_evidence, table_evidence.\n"
        "Allowed support_strength values: direct, indirect, weak.\n"
        "extraction_confidence must be a number from 0 to 1.\n"
        "unsupported_parts and warnings must be arrays of strings.\n"
        "entities must be an object with only these array fields: materials, methods, properties, "
        "metrics, values, units, conditions, characterization_tools, mechanisms, applications.\n"
        "relations must be an array of objects with subject, predicate, object, optional qualifiers, "
        "optional condition, and optional confidence.\n\n"
        f"Verbatim snippet:\n{card.verbatim_snippet or ''}\n\n"
        f"Normalized statement:\n{card.normalized_statement or ''}"
    )
    return [
        {"role": "system", "content": ROLE_ENTITY_RELATION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _profile_id(task_profile: Any | None) -> str | None:
    if task_profile is None:
        return None
    if hasattr(task_profile, "profile_id"):
        return str(task_profile.profile_id)
    if isinstance(task_profile, dict):
        value = task_profile.get("profile_id")
        return str(value) if value else None
    return None


__all__ = [
    "INITIAL_EXTRACTION_SYSTEM_PROMPT",
    "ROLE_ENTITY_RELATION_SYSTEM_PROMPT",
    "build_initial_extraction_messages",
    "build_role_entity_relation_messages",
]
