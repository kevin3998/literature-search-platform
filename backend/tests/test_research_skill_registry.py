from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ArtifactRequirement,
    SkillContract,
    SkillDatabaseAccess,
    SkillExecutionMode,
    SkillRegistry,
    SkillStatus,
    build_default_skill_registry,
)


AVAILABLE_SKILLS = {
    "retrieve_sources",
    "create_evidence_seeds",
    "extract_evidence_cards",
    "enrich_evidence_cards",
    "rank_evidence",
    "build_landscape",
    "map_gaps",
    "generate_candidate_ideas",
    "screen_novelty_feasibility_risk",
    "create_experiment_matrix",
    "build_claim_ledger",
    "draft_manuscript_section",
    "build_minimal_topic_to_evidence_report",
    "validate_evidence_cards",
    "validate_artifact_manifest",
}

STUB_SKILLS = {
    "draft_evidence_grounded_report",
}


def _sample_contract(name: str = "sample_skill") -> SkillContract:
    return SkillContract(
        name=name,
        purpose="Declare a test skill contract.",
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="task",
                path_hint="task.md",
                required=True,
                description="Task definition.",
            )
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="evidence_cards",
                path_hint="evidence/evidence_cards.json",
                required=True,
                description="Evidence card artifact.",
            )
        ],
        required_artifacts=["task.md"],
        produced_artifacts=["evidence/evidence_cards.json"],
        validation_rules=["schema_valid"],
        failure_modes=["missing_required_artifact"],
        based_on_modules=["A3"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=["metadata only"],
    )


def test_artifact_requirement_and_skill_contract_round_trip() -> None:
    contract = _sample_contract()
    data = contract.as_dict()

    assert data["status"] == "available"
    assert data["execution_mode"] == "deterministic"
    assert data["database_access"] == "none"
    assert data["input_artifacts"][0]["artifact_type"] == "task"
    assert data["output_artifacts"][0]["artifact_type"] == "evidence_cards"
    assert SkillContract.from_dict(data).as_dict() == data


def test_invalid_skill_contract_enum_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        SkillContract(name="bad", purpose="bad", execution_mode="magic")

    with pytest.raises(ValueError):
        SkillContract(name="bad", purpose="bad", database_access="read_write")

    with pytest.raises(ValueError):
        SkillContract(name="bad", purpose="bad", status="running")

    assert "read_write" not in {item.value for item in SkillDatabaseAccess}


def test_skill_registry_registers_lists_and_rejects_duplicates() -> None:
    registry = SkillRegistry()
    contract = _sample_contract("sample_skill")

    registered = registry.register_skill(contract)

    assert registered is contract
    assert registry.is_registered("sample_skill") is True
    assert registry.is_registered("missing") is False
    assert registry.get_skill("sample_skill") is contract
    assert registry.list_skills() == [contract]
    assert registry.list_available_skills() == [contract]
    assert registry.list_stub_skills() == []

    with pytest.raises(ValueError):
        registry.register_skill(_sample_contract("sample_skill"))


def test_skill_registry_rejects_unknown_skill_requests_deterministically() -> None:
    registry = SkillRegistry()

    with pytest.raises(KeyError):
        registry.get_skill("missing")

    with pytest.raises(KeyError):
        registry.validate_skill_request_name("missing")

    registry.register_skill(_sample_contract("known"))
    assert registry.validate_skill_request_name("known") == "known"


def test_default_registry_contains_expected_available_and_stub_skills() -> None:
    registry = build_default_skill_registry()

    assert {skill.name for skill in registry.list_available_skills()} == AVAILABLE_SKILLS
    assert {skill.name for skill in registry.list_stub_skills()} == STUB_SKILLS
    assert {skill.name for skill in registry.list_skills()} == AVAILABLE_SKILLS | STUB_SKILLS


def test_default_registry_declares_artifacts_validation_rules_and_failure_modes() -> None:
    registry = build_default_skill_registry()

    for skill in registry.list_skills():
        assert skill.produced_artifacts, skill.name
        assert skill.validation_rules, skill.name
        assert skill.failure_modes, skill.name
        assert skill.output_artifacts, skill.name


def test_raw_chunks_are_only_allowed_for_retrieval_and_seed_skills() -> None:
    registry = build_default_skill_registry()
    raw_chunk_skills = {skill.name for skill in registry.list_skills() if skill.allows_raw_chunks}

    assert raw_chunk_skills == {"retrieve_sources", "create_evidence_seeds"}

    for name in {
        "build_landscape",
        "map_gaps",
        "generate_candidate_ideas",
        "draft_evidence_grounded_report",
        "draft_manuscript_section",
    }:
        assert registry.get_skill(name).allows_raw_chunks is False


def test_evidence_dependent_skills_require_evidence_cards() -> None:
    registry = build_default_skill_registry()

    evidence_dependent = {
        "enrich_evidence_cards",
        "rank_evidence",
        "build_minimal_topic_to_evidence_report",
        "validate_evidence_cards",
        "build_landscape",
        "map_gaps",
        "generate_candidate_ideas",
        "screen_novelty_feasibility_risk",
        "draft_evidence_grounded_report",
        "create_experiment_matrix",
        "build_claim_ledger",
        "draft_manuscript_section",
    }
    for name in evidence_dependent:
        assert registry.get_skill(name).requires_evidence_cards is True


def test_default_registry_database_access_is_read_only_or_less() -> None:
    registry = build_default_skill_registry()

    assert registry.get_skill("retrieve_sources").database_access == SkillDatabaseAccess.READ_ONLY
    for skill in registry.list_skills():
        assert skill.database_access in {
            SkillDatabaseAccess.NONE,
            SkillDatabaseAccess.READ_ONLY,
            SkillDatabaseAccess.FORBIDDEN,
        }


def test_skill_registry_has_no_runtime_database_cli_or_llm_dependencies() -> None:
    source = Path("backend/modules/research_agent_controller/skill_registry.py").read_text(encoding="utf-8")

    forbidden = [
        "modules.evidence_workflow",
        "LiteratureResearchService",
        "core.memory_db",
        "sqlite",
        "workflow runner",
        "cli_backed_controller",
        "native_fallback_controller",
        "OpenAI",
        "DeepSeek",
        "llm_client",
    ]
    for token in forbidden:
        assert token not in source
