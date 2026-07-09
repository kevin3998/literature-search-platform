"""P2-M11 LLM-assisted evidence-grounded screening skill wrapper.

The wrapper preserves deterministic input guards, builds a bounded evidence
packet, asks an injected LLM client for local triage JSON, and validates all
references before writing artifacts. It does not perform external novelty
search, expert review, risk review, experiment planning, or claim generation.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .screening_contract import (
    EXTERNAL_NOVELTY_SEARCH_STATUS_VALUES,
    FEASIBILITY_TRIAGE_VALUES,
    IDEA_SCREENING_SCHEMA_VERSION,
    LOCAL_NOVELTY_TRIAGE_VALUES,
    OVERALL_TRIAGE_VALUES,
    RISK_TRIAGE_VALUES,
    SCREENING_CONFIDENCE_VALUES,
    SCREENING_FORBIDDEN_MARKDOWN_SECTIONS,
    SCREENING_OUTPUT_ARTIFACTS,
    SCREENING_REQUIRED_INPUT_ARTIFACTS,
    IdeaScreeningArtifact,
    validate_screening_input_artifacts,
)

FORBIDDEN_SCREENING_CLAIMS = [
    "is novel",
    "confirmed novel",
    "definitely novel",
    "is feasible",
    "experimentally feasible",
    "proven feasible",
    "ready to synthesize",
    "ready to test",
    "has been validated",
    "experimentally validated",
    "proves that",
    "confirms that",
    "will improve",
    "will enhance",
    "manuscript draft",
    "final claim",
]

PROMPT_VERSION = "p2_m11_llm_screening_v1"
ANALYSIS_MODE = "llm_assisted_local_evidence_triage"


def screen_novelty_feasibility_risk(
    execution: SkillExecutionInput,
    *,
    llm_client: Any | None = None,
    **_: Any,
) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or SCREENING_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_screening_input_artifacts(input_artifacts)
    forbidden_errors = [error for error in input_errors if "not_allowed_for_screening" in error]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    if not _path(execution, "ideas/candidate_ideas.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_candidate_ideas_artifact"],
        )

    missing = [path for path in SCREENING_REQUIRED_INPUT_ARTIFACTS if not _path(execution, path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{path}" for path in missing],
        )

    payloads: dict[str, Any] = {}
    for artifact_path in SCREENING_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    candidate_ideas = payloads["ideas/candidate_ideas.json"]
    gap_map = payloads["gaps/gap_map.json"]
    landscape = payloads["landscape/literature_landscape.json"]
    schema_errors = _validate_input_schemas(candidate_ideas, gap_map, landscape)
    if schema_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=schema_errors,
        )

    candidate_errors = _validate_candidate_ideas_for_screening(candidate_ideas)
    if candidate_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=candidate_errors,
        )

    if llm_client is None:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=["llm_required_for_screening"],
            metadata={"analysis_mode": ANALYSIS_MODE},
        )

    topic = str(execution.parameters.get("topic") or candidate_ideas.get("topic") or gap_map.get("topic") or "").strip()
    packet = _build_evidence_packet(
        task_id=execution.task_id,
        topic=topic or "unspecified topic",
        candidate_ideas=candidate_ideas,
        idea_diagnostics=payloads["ideas/idea_generation_diagnostics.json"],
        gap_map=gap_map,
        gap_diagnostics=payloads["gaps/gap_coverage_diagnostics.json"],
        landscape=landscape,
        landscape_diagnostics=payloads["landscape/landscape_coverage_diagnostics.json"],
        enriched_cards=payloads["evidence/evidence_cards.enriched.json"],
        selection=payloads["ranked_evidence/evidence_selection.json"],
        ranking_diagnostics=payloads["ranked_evidence/coverage_diagnostics.json"],
    )

    try:
        llm_payload = _call_screening_llm(llm_client, packet)
    except (json.JSONDecodeError, ValueError) as exc:
        _write_safe_diagnostics(
            execution,
            _diagnostics(
                task_id=execution.task_id,
                screening_id=f"idea_screening_{execution.task_id}",
                candidate_ideas=candidate_ideas,
                screened_count=0,
                warnings=packet["warnings"],
                validation_errors=[f"invalid_llm_screening_json:{exc}"],
                llm_called=True,
            ),
        )
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=["invalid_llm_screening_json"],
            warnings=packet["warnings"],
        )

    artifact_payload = _assemble_screening_artifact_payload(
        execution=execution,
        topic=topic or packet["topic"],
        packet=packet,
        llm_payload=llm_payload,
        input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
        llm_client=llm_client,
    )
    markdown = render_screening_summary_markdown(artifact_payload)
    validation_errors = validate_screening_artifact(artifact_payload, markdown, reference_packet=packet)
    if validation_errors:
        _write_safe_diagnostics(
            execution,
            _diagnostics(
                task_id=execution.task_id,
                screening_id=artifact_payload.get("screening_id", f"idea_screening_{execution.task_id}"),
                candidate_ideas=candidate_ideas,
                screened_count=len(artifact_payload.get("screened_ideas") or []),
                warnings=packet["warnings"],
                validation_errors=validation_errors,
                llm_called=True,
            ),
        )
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=packet["warnings"],
        )

    artifact = IdeaScreeningArtifact.from_dict(artifact_payload)
    diagnostics = _diagnostics(
        task_id=execution.task_id,
        screening_id=artifact.screening_id,
        candidate_ideas=candidate_ideas,
        screened_count=len(artifact.screened_ideas),
        warnings=artifact.warnings,
        validation_errors=[],
        llm_called=True,
    )
    _write_json(execution, "screening/idea_screening_results.json", artifact.as_dict())
    _write_text(execution, "screening/idea_screening_results.md", markdown)
    _write_json(execution, "screening/screening_diagnostics.json", diagnostics)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=SCREENING_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=SCREENING_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "screened_idea_count": len(artifact.screened_ideas),
            "analysis_mode": ANALYSIS_MODE,
            "external_novelty_search_performed": False,
            "expert_feasibility_review_performed": False,
            "risk_review_performed": False,
        },
    )


def validate_screening_artifact(
    screening: dict[str, Any],
    markdown: str,
    *,
    reference_packet: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if screening.get("schema_version") != IDEA_SCREENING_SCHEMA_VERSION:
        errors.append("invalid_idea_screening_schema_version")
    if screening.get("analysis_mode") != ANALYSIS_MODE:
        errors.append("invalid_screening_analysis_mode")
    if not screening.get("screening_id"):
        errors.append("missing_screening_id")
    if not screening.get("idea_set_id"):
        errors.append("missing_idea_set_id")
    if not screening.get("gap_map_id"):
        errors.append("missing_gap_map_id")
    if not screening.get("landscape_id"):
        errors.append("missing_landscape_id")
    if not screening.get("evidence_ids"):
        errors.append("screening_requires_evidence_references")
    if not screening.get("screened_ideas"):
        errors.append("screening_requires_screened_ideas")

    refs = _reference_sets(reference_packet) if reference_packet else {}
    for index, idea in enumerate(screening.get("screened_ideas") or []):
        if not isinstance(idea, dict):
            errors.append(f"screened_idea_is_not_object:{index}")
            continue
        idea_id = str(idea.get("idea_id") or "")
        if not idea_id:
            errors.append(f"screened_idea_requires_source_idea_id:{index}")
        elif refs and idea_id not in refs["idea_ids"]:
            errors.append(f"unknown_screening_idea_id:{idea_id}")
        _validate_id_list(errors, refs, "gap_ids", "gap_id", idea, idea_id, index)
        _validate_id_list(errors, refs, "evidence_ids", "evidence_id", idea, idea_id, index)
        _validate_local_novelty(errors, idea, refs, idea_id, index)
        _validate_external_search(errors, idea, index)
        _validate_feasibility(errors, idea, refs, idea_id, index)
        _validate_risk(errors, idea, index)
        _validate_overall(errors, idea, index)
        if idea.get("not_an_experiment_plan") is not True:
            errors.append(f"screening_must_not_be_experiment_plan:{index}")
        if idea.get("not_a_validated_claim") is not True:
            errors.append(f"screening_must_not_be_validated_claim:{index}")

    provenance = screening.get("llm_provenance") if isinstance(screening.get("llm_provenance"), dict) else {}
    if provenance.get("external_novelty_search_performed") is not False:
        errors.append("external_novelty_search_must_not_be_performed")
    if provenance.get("prompt_version") != PROMPT_VERSION:
        errors.append("invalid_screening_prompt_version")

    if "## Evidence References" not in markdown and "## 证据引用" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in SCREENING_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_screening_markdown_section:{section}")
    if _forbidden_claim_matches(screening, markdown):
        errors.append("unsupported_screening_claim")
    return _dedupe(errors)


def render_screening_summary_markdown(screening: dict[str, Any]) -> str:
    screened_ideas = [idea for idea in screening.get("screened_ideas") or [] if isinstance(idea, dict)]
    lines = [
        "# LLM 辅助筛选摘要",
        "",
        "## 范围",
        "",
        f"- 主题：{screening.get('topic') or '未指定主题'}",
        f"- 筛选 ID：{screening.get('screening_id') or ''}",
        f"- 候选想法集 ID：{screening.get('idea_set_id') or ''}",
        f"- 分析模式：{_human(screening.get('analysis_mode') or ANALYSIS_MODE)}",
        "",
        "## 边界",
        "",
        "- 这是基于本地证据的初步筛选，不是最终的新颖性、可行性或风险结论。",
        "- 外部新颖性检索：未执行。",
        "- 专家可行性评审：未执行。",
        "- 下游风险评审：未执行。",
        "- 边界标记已保留：not_an_experiment_plan=true；not_a_validated_claim=true。",
        "",
        "## 候选想法筛选",
        "",
    ]
    for index, idea in enumerate(screened_ideas, start=1):
        title = str(idea.get("source_idea_title") or idea.get("idea_id") or f"候选想法 {index}")
        overall = idea.get("overall_triage") if isinstance(idea.get("overall_triage"), dict) else {}
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"- idea_id: {idea.get('idea_id') or ''}",
                f"- 证据基础：{len(idea.get('evidence_ids') or [])} 张证据卡；{len(idea.get('gap_ids') or [])} 个研究空白引用",
                f"- 总体筛选：{_human(overall.get('judgment'))}",
                f"- 理由：{overall.get('rationale') or '未提供理由。'}",
                "",
            ]
        )

    lines.extend(["## 局部新颖性筛选", ""])
    for idea in screened_ideas:
        novelty = idea.get("local_novelty_triage") if isinstance(idea.get("local_novelty_triage"), dict) else {}
        lines.extend(
            [
                f"### {idea.get('idea_id') or ''}",
                "",
                f"- 局部新颖性筛选：{_human(novelty.get('judgment'))}",
                f"- 置信度：{_human(novelty.get('confidence') or 'unknown')}",
                f"- 理由：{novelty.get('rationale') or '未提供理由。'}",
                f"- 局限：{_compact_list(novelty.get('limitations') or [])}",
                "- 外部新颖性检索：未执行。",
                "",
            ]
        )

    lines.extend(["## 可行性筛选", ""])
    for idea in screened_ideas:
        feasibility = idea.get("feasibility_triage") if isinstance(idea.get("feasibility_triage"), dict) else {}
        lines.extend(
            [
                f"### {idea.get('idea_id') or ''}",
                "",
                f"- 可行性：{_human(feasibility.get('judgment'))}",
                f"- 置信度：{_human(feasibility.get('confidence') or 'unknown')}",
                f"- 缺失要求：{_compact_list(feasibility.get('missing_requirements') or [])}",
                f"- 约束：{_compact_list(feasibility.get('constraints') or [])}",
                f"- 理由：{feasibility.get('rationale') or '未提供理由。'}",
                "",
            ]
        )

    lines.extend(["## 风险筛选", ""])
    for idea in screened_ideas:
        risk = idea.get("risk_triage") if isinstance(idea.get("risk_triage"), dict) else {}
        lines.extend(
            [
                f"### {idea.get('idea_id') or ''}",
                "",
                f"- 风险：{_human(risk.get('judgment'))}",
                f"- 置信度：{_human(risk.get('confidence') or 'unknown')}",
                f"- 风险因素：{_compact_list(risk.get('risk_factors') or [])}",
                f"- 理由：{risk.get('rationale') or '未提供理由。'}",
                "",
            ]
        )

    lines.extend(["## 必要后续检查", ""])
    for idea in screened_ideas:
        overall = idea.get("overall_triage") if isinstance(idea.get("overall_triage"), dict) else {}
        lines.append(f"- {idea.get('idea_id') or ''}: {_compact_list(overall.get('required_follow_up') or [])}")
    lines.extend(["", "## 局限", ""])
    for limitation in screening.get("limitations") or []:
        lines.append(f"- {limitation}")
    warnings = [str(warning) for warning in screening.get("warnings") or [] if str(warning)]
    if warnings:
        lines.append(f"- 警告摘要：{_compact_list(warnings, limit=5)}")
    lines.append("- 完整诊断：screening/screening_diagnostics.json")

    lines.extend(["", "## 证据引用", ""])
    evidence_map = _evidence_reference_map(screening)
    cluster_map = _candidate_reference_map(screening)
    for idea in screened_ideas:
        idea_id = str(idea.get("idea_id") or "")
        for gap_id in [str(value) for value in idea.get("gap_ids") or [] if str(value)]:
            lines.append(f"- idea_id={idea_id}; gap_id={gap_id}")
        for evidence_id in [str(value) for value in idea.get("evidence_ids") or [] if str(value)]:
            ref = evidence_map.get(evidence_id, {})
            lines.append(
                f"- idea_id={idea_id}; evidence_id={evidence_id}; paper_id={ref.get('paper_id', '')}; title={ref.get('title', '')}"
            )
        for cluster_id in cluster_map.get(idea_id, {}).get("landscape_cluster_ids", []):
            lines.append(f"- idea_id={idea_id}; landscape_cluster_id={cluster_id}")
    return "\n".join(lines).strip() + "\n"


def _validate_input_schemas(candidate_ideas: dict[str, Any], gap_map: dict[str, Any], landscape: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate_ideas.get("schema_version") != "candidate_ideas_v1":
        errors.append("invalid_candidate_ideas_schema_version")
    if gap_map.get("schema_version") != "gap_map_v1":
        errors.append("invalid_gap_map_schema_version")
    if landscape.get("schema_version") != "landscape_v1":
        errors.append("invalid_landscape_schema_version")
    return errors


def _validate_candidate_ideas_for_screening(candidate_ideas: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ideas = [idea for idea in candidate_ideas.get("ideas") or [] if isinstance(idea, dict)]
    if not ideas:
        errors.append("screening_requires_gap_and_evidence_basis")
    for idea in ideas:
        gap_basis = idea.get("gap_basis") if isinstance(idea.get("gap_basis"), dict) else {}
        evidence_basis = idea.get("evidence_basis") if isinstance(idea.get("evidence_basis"), dict) else {}
        if not gap_basis.get("gap_ids") or not evidence_basis.get("supporting_evidence_ids"):
            errors.append("screening_requires_gap_and_evidence_basis")
        if idea.get("not_yet_screened") is not True:
            errors.append("screening_requires_unscreened_candidate_ideas")
    return _dedupe(errors)


def _build_evidence_packet(
    *,
    task_id: str,
    topic: str,
    candidate_ideas: dict[str, Any],
    idea_diagnostics: dict[str, Any],
    gap_map: dict[str, Any],
    gap_diagnostics: dict[str, Any],
    landscape: dict[str, Any],
    landscape_diagnostics: dict[str, Any],
    enriched_cards: dict[str, Any],
    selection: dict[str, Any],
    ranking_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    selected_cards = _selected_cards(selection, enriched_cards)
    card_by_id = {str(card.get("evidence_id")): card for card in selected_cards if card.get("evidence_id")}
    ideas = [_packet_idea(idea) for idea in candidate_ideas.get("ideas") or [] if isinstance(idea, dict)]
    wanted_evidence_ids = _dedupe(
        [
            evidence_id
            for idea in ideas
            for evidence_id in idea.get("evidence_basis", {}).get("supporting_evidence_ids", [])
            if evidence_id in card_by_id
        ]
    )
    evidence_cards = [_packet_card(card_by_id[evidence_id]) for evidence_id in wanted_evidence_ids]
    gaps = [_packet_gap(gap) for gap in gap_map.get("gaps") or [] if isinstance(gap, dict)]
    clusters = [_packet_cluster(cluster) for cluster in landscape.get("clusters") or [] if isinstance(cluster, dict)]
    warnings = _collect_warnings(
        candidate_ideas,
        idea_diagnostics,
        gap_map,
        gap_diagnostics,
        landscape,
        landscape_diagnostics,
        enriched_cards,
        selection,
        ranking_diagnostics,
    )
    return {
        "task_id": task_id,
        "topic": topic,
        "idea_set_id": str(candidate_ideas.get("idea_set_id") or ""),
        "gap_map_id": str(candidate_ideas.get("gap_map_id") or gap_map.get("gap_map_id") or ""),
        "landscape_id": str(candidate_ideas.get("landscape_id") or landscape.get("landscape_id") or ""),
        "candidate_ideas": ideas,
        "gaps": gaps,
        "landscape_clusters": clusters,
        "evidence_cards": evidence_cards,
        "diagnostics": {
            "idea_generation": _diagnostic_summary(idea_diagnostics),
            "gap_coverage": _diagnostic_summary(gap_diagnostics),
            "landscape_coverage": _diagnostic_summary(landscape_diagnostics),
            "ranking_coverage": _diagnostic_summary(ranking_diagnostics),
        },
        "warnings": warnings,
        "allowed_reference_ids": {
            "idea_ids": [idea["idea_id"] for idea in ideas],
            "gap_ids": [gap["gap_id"] for gap in gaps],
            "evidence_ids": [card["evidence_id"] for card in evidence_cards],
            "paper_ids": _dedupe([card.get("paper_id") for card in evidence_cards if card.get("paper_id")]),
            "cluster_ids": [cluster["cluster_id"] for cluster in clusters],
        },
        "evidence_reference_map": {
            card["evidence_id"]: {"paper_id": card.get("paper_id", ""), "title": card.get("title", "")}
            for card in evidence_cards
        },
        "candidate_reference_map": {
            idea["idea_id"]: {
                "landscape_cluster_ids": idea.get("gap_basis", {}).get("landscape_cluster_ids", []),
            }
            for idea in ideas
        },
        "external_novelty_search": {"status": "not_performed", "required": True},
    }


def _packet_idea(idea: dict[str, Any]) -> dict[str, Any]:
    gap_basis = idea.get("gap_basis") if isinstance(idea.get("gap_basis"), dict) else {}
    evidence_basis = idea.get("evidence_basis") if isinstance(idea.get("evidence_basis"), dict) else {}
    return {
        "idea_id": str(idea.get("idea_id") or ""),
        "title": str(idea.get("title") or ""),
        "summary": str(idea.get("summary") or ""),
        "rationale": str(idea.get("rationale") or ""),
        "expected_contribution": str(idea.get("expected_contribution") or ""),
        "assumptions": [str(value) for value in idea.get("assumptions") or [] if str(value)],
        "constraints": [str(value) for value in idea.get("constraints") or [] if str(value)],
        "gap_basis": {
            "gap_ids": [str(value) for value in gap_basis.get("gap_ids") or [] if str(value)],
            "gap_types": [str(value) for value in gap_basis.get("gap_types") or [] if str(value)],
            "landscape_cluster_ids": [str(value) for value in gap_basis.get("landscape_cluster_ids") or [] if str(value)],
            "coverage_warnings": [str(value) for value in gap_basis.get("coverage_warnings") or [] if str(value)],
        },
        "evidence_basis": {
            "supporting_evidence_ids": [
                str(value) for value in evidence_basis.get("supporting_evidence_ids") or [] if str(value)
            ],
            "source_paper_ids": [str(value) for value in evidence_basis.get("source_paper_ids") or [] if str(value)],
        },
    }


def _packet_gap(gap: dict[str, Any]) -> dict[str, Any]:
    basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
    return {
        "gap_id": str(gap.get("gap_id") or ""),
        "gap_type": str(gap.get("gap_type") or ""),
        "title": str(gap.get("title") or ""),
        "description": str(gap.get("description") or gap.get("summary") or ""),
        "basis": {
            "landscape_cluster_ids": [str(value) for value in basis.get("landscape_cluster_ids") or [] if str(value)],
            "evidence_ids": [str(value) for value in basis.get("evidence_ids") or [] if str(value)],
            "coverage_warnings": [str(value) for value in basis.get("coverage_warnings") or [] if str(value)],
        },
    }


def _packet_cluster(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": str(cluster.get("cluster_id") or ""),
        "title": str(cluster.get("title") or ""),
        "evidence_ids": [str(value) for value in cluster.get("evidence_ids") or [] if str(value)],
        "representative_claims": [
            {
                "claim": str(claim.get("claim") or claim.get("statement") or ""),
                "evidence_ids": [str(value) for value in claim.get("evidence_ids") or [] if str(value)],
            }
            for claim in cluster.get("representative_claims") or []
            if isinstance(claim, dict)
        ],
    }


def _packet_card(card: dict[str, Any]) -> dict[str, Any]:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    support = card.get("support") if isinstance(card.get("support"), dict) else {}
    return {
        "evidence_id": str(card.get("evidence_id") or ""),
        "paper_id": str(card.get("paper_id") or ""),
        "title": str(card.get("title") or card.get("paper_title") or card.get("seed_id") or ""),
        "primary_role": str(card.get("primary_role") or ""),
        "secondary_roles": [str(value) for value in card.get("secondary_roles") or [] if str(value)],
        "normalized_statement": str(card.get("normalized_statement") or ""),
        "support_strength": str(support.get("support_strength") or ""),
        "source_type": str(source.get("asset_type") or ""),
    }


def _selected_cards(selection: dict[str, Any], enriched_cards: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for item in selection.get("selected_cards") or []:
        if isinstance(item, dict):
            cards.append(item)
    for item in selection.get("ranked_cards") or []:
        if isinstance(item, dict) and item.get("selected") is True and isinstance(item.get("card"), dict):
            cards.append(item["card"])
    if not cards:
        cards = [card for card in enriched_cards.get("cards") or [] if isinstance(card, dict)]
    deduped: dict[str, dict[str, Any]] = {}
    for card in cards:
        evidence_id = str(card.get("evidence_id") or "")
        if evidence_id:
            deduped[evidence_id] = card
    return list(deduped.values())


def _call_screening_llm(llm_client: Any, packet: dict[str, Any]) -> dict[str, Any]:
    text = asyncio.run(_collect_llm_text(llm_client, _screening_messages(packet)))
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("llm_screening_payload_must_be_object")
    return payload


async def _collect_llm_text(llm_client: Any, messages: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    async for event in llm_client.stream_chat(messages, tools=None):
        if isinstance(event, dict):
            text = event.get("text") or event.get("content") or ""
            if isinstance(text, str):
                chunks.append(text)
        elif isinstance(event, str):
            chunks.append(event)
    return "".join(chunks).strip()


def _screening_messages(packet: dict[str, Any]) -> list[dict[str, str]]:
    schema_hint = {
        "screened_ideas": [
            {
                "idea_id": "<allowed idea_id>",
                "source_idea_title": "<candidate title>",
                "gap_ids": ["<allowed gap_id>"],
                "evidence_ids": ["<allowed evidence_id>"],
                "local_novelty_triage": {
                    "judgment": LOCAL_NOVELTY_TRIAGE_VALUES,
                    "confidence": SCREENING_CONFIDENCE_VALUES,
                    "closest_local_prior_evidence": [
                        {
                            "evidence_id": "<allowed evidence_id>",
                            "paper_id": "<allowed paper_id>",
                            "overlap": "<local overlap only>",
                            "difference": "<local difference only>",
                        }
                    ],
                    "rationale": "<uncertainty-aware rationale>",
                    "limitations": ["<limitation>"],
                },
                "external_novelty_search": {
                    "status": "not_performed",
                    "required": True,
                    "rationale": "<why external search is still needed>",
                },
                "feasibility_triage": {
                    "judgment": FEASIBILITY_TRIAGE_VALUES,
                    "confidence": SCREENING_CONFIDENCE_VALUES,
                    "supporting_evidence": ["<allowed evidence_id>"],
                    "missing_requirements": ["<requirement>"],
                    "constraints": ["<constraint>"],
                    "rationale": "<evidence-grounded rationale>",
                },
                "risk_triage": {
                    "judgment": RISK_TRIAGE_VALUES,
                    "confidence": SCREENING_CONFIDENCE_VALUES,
                    "risk_factors": ["<risk factor>"],
                    "follow_up": ["<follow-up>"],
                    "rationale": "<evidence-grounded rationale>",
                },
                "overall_triage": {
                    "judgment": OVERALL_TRIAGE_VALUES,
                    "rationale": "<triage rationale>",
                    "required_follow_up": ["<follow-up>"],
                },
                "not_an_experiment_plan": True,
                "not_a_validated_claim": True,
            }
        ]
    }
    return [
        {
            "role": "system",
            "content": (
                "You are executing P2-M11 local evidence triage. Return JSON only. "
                "Use only IDs present in the evidence packet. Do not invent papers, evidence IDs, gap IDs, "
                "claims, experiments, protocols, or manuscripts. Separate local novelty triage from external novelty search. "
                "External novelty search was not performed. Do not state final novelty, feasibility, risk, or validation conclusions. "
                "用中文撰写所有面向用户阅读的 rationale、limitations、overlap、difference、missing_requirements、"
                "constraints、risk_factors、follow_up 和 required_follow_up；JSON 字段名、枚举值和引用 ID 保持英文原值。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请生成一个不确定性敏感的局部新颖性 / 可行性 / 风险筛选 JSON。"
                "除字段名、枚举值和引用 ID 外，所有解释性文本都必须使用中文。\n"
                f"SCHEMA_HINT_JSON:\n{json.dumps(schema_hint, ensure_ascii=False, indent=2)}\n\n"
                f"EVIDENCE_PACKET_JSON:\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def _assemble_screening_artifact_payload(
    *,
    execution: SkillExecutionInput,
    topic: str,
    packet: dict[str, Any],
    llm_payload: dict[str, Any],
    input_artifacts: list[str],
    llm_client: Any,
) -> dict[str, Any]:
    screened_ideas = [dict(idea) for idea in llm_payload.get("screened_ideas") or [] if isinstance(idea, dict)]
    evidence_ids = _dedupe([evidence_id for idea in screened_ideas for evidence_id in idea.get("evidence_ids", [])])
    source_paper_ids = _dedupe(
        [
            packet["evidence_reference_map"].get(evidence_id, {}).get("paper_id", "")
            for evidence_id in evidence_ids
        ]
    )
    return {
        "task_id": execution.task_id,
        "topic": topic,
        "screening_id": f"idea_screening_{execution.task_id}",
        "input_artifacts": input_artifacts,
        "idea_set_id": packet["idea_set_id"],
        "gap_map_id": packet["gap_map_id"],
        "landscape_id": packet["landscape_id"],
        "evidence_ids": evidence_ids,
        "source_paper_ids": source_paper_ids,
        "screened_ideas": screened_ideas,
        "analysis_mode": ANALYSIS_MODE,
        "llm_provenance": {
            "provider": str(getattr(llm_client, "provider", "unknown")),
            "model": str(getattr(llm_client, "model", "unknown")),
            "prompt_version": PROMPT_VERSION,
            "external_novelty_search_performed": False,
        },
        "screening_scope": {
            "source": "candidate_ideas",
            "external_novelty_search_performed": False,
            "expert_feasibility_review_performed": False,
            "risk_review_performed": False,
            "evidence_reference_map": packet["evidence_reference_map"],
            "candidate_reference_map": packet["candidate_reference_map"],
        },
        "screening_policy": {
            "analysis_mode": ANALYSIS_MODE,
            "not_an_experiment_plan": True,
            "not_a_validated_claim": True,
            "external_novelty_search_status": "not_performed",
        },
        "limitations": [
            "本分析仅限于 evidence packet 中提供的本地 artifact。",
            "未执行外部新颖性检索。",
            "未执行专家可行性评审。",
            "未执行下游风险评审。",
            "该 artifact 不是实验方案，也不是已验证结论。",
        ],
        "warnings": packet["warnings"],
        "created_at": time.time(),
        "schema_version": IDEA_SCREENING_SCHEMA_VERSION,
    }


def _diagnostics(
    *,
    task_id: str,
    screening_id: str,
    candidate_ideas: dict[str, Any],
    screened_count: int,
    warnings: list[str],
    validation_errors: list[str],
    llm_called: bool,
) -> dict[str, Any]:
    forbidden_matches = _forbidden_claim_matches({"validation_errors": validation_errors}, "")
    return {
        "artifact_type": "screening_diagnostics",
        "task_id": task_id,
        "screening_id": screening_id,
        "idea_set_id": str(candidate_ideas.get("idea_set_id") or ""),
        "num_input_ideas": len([idea for idea in candidate_ideas.get("ideas") or [] if isinstance(idea, dict)]),
        "num_screened_ideas": screened_count,
        "analysis_mode": ANALYSIS_MODE,
        "llm_called": llm_called,
        "external_novelty_search_performed": False,
        "expert_feasibility_review_performed": False,
        "risk_review_performed": False,
        "validation_errors": list(validation_errors),
        "forbidden_claim_checks": {"passed": not forbidden_matches, "matches": forbidden_matches},
        "warnings": list(warnings),
        "created_at": time.time(),
        "schema_version": IDEA_SCREENING_SCHEMA_VERSION,
    }


def _write_safe_diagnostics(execution: SkillExecutionInput, diagnostics: dict[str, Any]) -> None:
    _write_json(execution, "screening/screening_diagnostics.json", diagnostics)


def _validate_id_list(
    errors: list[str],
    refs: dict[str, set[str]],
    field: str,
    singular: str,
    idea: dict[str, Any],
    idea_id: str,
    index: int,
) -> None:
    values = [str(value) for value in idea.get(field) or [] if str(value)]
    if not values:
        errors.append(f"screened_idea_requires_{field}:{index}")
    if refs:
        allowed = refs[f"{singular}s"]
        for value in values:
            if value not in allowed:
                errors.append(f"unknown_screening_{singular}:{idea_id}:{value}")


def _validate_local_novelty(errors: list[str], idea: dict[str, Any], refs: dict[str, set[str]], idea_id: str, index: int) -> None:
    novelty = idea.get("local_novelty_triage") if isinstance(idea.get("local_novelty_triage"), dict) else {}
    if novelty.get("judgment") not in LOCAL_NOVELTY_TRIAGE_VALUES:
        errors.append(f"invalid_local_novelty_triage_judgment:{index}")
    if novelty.get("confidence") not in SCREENING_CONFIDENCE_VALUES:
        errors.append(f"invalid_local_novelty_triage_confidence:{index}")
    if not novelty.get("rationale"):
        errors.append(f"local_novelty_triage_requires_rationale:{index}")
    if not novelty.get("limitations"):
        errors.append(f"local_novelty_triage_requires_limitations:{index}")
    if refs:
        for prior in novelty.get("closest_local_prior_evidence") or []:
            if not isinstance(prior, dict):
                continue
            evidence_id = str(prior.get("evidence_id") or "")
            paper_id = str(prior.get("paper_id") or "")
            if evidence_id and evidence_id not in refs["evidence_ids"]:
                errors.append(f"unknown_screening_evidence_id:{idea_id}:{evidence_id}")
            if paper_id and paper_id not in refs["paper_ids"]:
                errors.append(f"unknown_screening_paper_id:{idea_id}:{paper_id}")


def _validate_external_search(errors: list[str], idea: dict[str, Any], index: int) -> None:
    external = idea.get("external_novelty_search") if isinstance(idea.get("external_novelty_search"), dict) else {}
    if external.get("status") not in EXTERNAL_NOVELTY_SEARCH_STATUS_VALUES:
        errors.append(f"external_novelty_search_must_be_not_performed:{index}")
    if external.get("required") is not True:
        errors.append(f"external_novelty_search_required_must_be_true:{index}")
    if not external.get("rationale"):
        errors.append(f"external_novelty_search_requires_rationale:{index}")


def _validate_feasibility(errors: list[str], idea: dict[str, Any], refs: dict[str, set[str]], idea_id: str, index: int) -> None:
    feasibility = idea.get("feasibility_triage") if isinstance(idea.get("feasibility_triage"), dict) else {}
    if feasibility.get("judgment") not in FEASIBILITY_TRIAGE_VALUES:
        errors.append(f"invalid_feasibility_triage_judgment:{index}")
    if feasibility.get("confidence") not in SCREENING_CONFIDENCE_VALUES:
        errors.append(f"invalid_feasibility_triage_confidence:{index}")
    if not feasibility.get("rationale"):
        errors.append(f"feasibility_triage_requires_rationale:{index}")
    if refs:
        for evidence_id in feasibility.get("supporting_evidence") or []:
            evidence_id = str(evidence_id)
            if evidence_id and evidence_id not in refs["evidence_ids"]:
                errors.append(f"unknown_screening_evidence_id:{idea_id}:{evidence_id}")


def _validate_risk(errors: list[str], idea: dict[str, Any], index: int) -> None:
    risk = idea.get("risk_triage") if isinstance(idea.get("risk_triage"), dict) else {}
    if risk.get("judgment") not in RISK_TRIAGE_VALUES:
        errors.append(f"invalid_risk_triage_judgment:{index}")
    if risk.get("confidence") not in SCREENING_CONFIDENCE_VALUES:
        errors.append(f"invalid_risk_triage_confidence:{index}")
    if not risk.get("risk_factors"):
        errors.append(f"risk_triage_requires_risk_factors:{index}")
    if not risk.get("rationale"):
        errors.append(f"risk_triage_requires_rationale:{index}")


def _validate_overall(errors: list[str], idea: dict[str, Any], index: int) -> None:
    overall = idea.get("overall_triage") if isinstance(idea.get("overall_triage"), dict) else {}
    if overall.get("judgment") not in OVERALL_TRIAGE_VALUES:
        errors.append(f"invalid_overall_triage_judgment:{index}")
    if not overall.get("rationale"):
        errors.append(f"overall_triage_requires_rationale:{index}")
    if not overall.get("required_follow_up"):
        errors.append(f"overall_triage_requires_required_follow_up:{index}")


def _reference_sets(packet: dict[str, Any] | None) -> dict[str, set[str]]:
    allowed = (packet or {}).get("allowed_reference_ids") if isinstance((packet or {}).get("allowed_reference_ids"), dict) else {}
    return {
        "idea_ids": set(str(value) for value in allowed.get("idea_ids") or [] if str(value)),
        "gap_ids": set(str(value) for value in allowed.get("gap_ids") or [] if str(value)),
        "evidence_ids": set(str(value) for value in allowed.get("evidence_ids") or [] if str(value)),
        "paper_ids": set(str(value) for value in allowed.get("paper_ids") or [] if str(value)),
        "cluster_ids": set(str(value) for value in allowed.get("cluster_ids") or [] if str(value)),
    }


def _evidence_reference_map(screening: dict[str, Any]) -> dict[str, dict[str, str]]:
    scope = screening.get("screening_scope") if isinstance(screening.get("screening_scope"), dict) else {}
    refs = scope.get("evidence_reference_map") if isinstance(scope.get("evidence_reference_map"), dict) else {}
    return {str(key): dict(value) for key, value in refs.items() if isinstance(value, dict)}


def _candidate_reference_map(screening: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    scope = screening.get("screening_scope") if isinstance(screening.get("screening_scope"), dict) else {}
    refs = scope.get("candidate_reference_map") if isinstance(scope.get("candidate_reference_map"), dict) else {}
    cleaned: dict[str, dict[str, list[str]]] = {}
    for key, value in refs.items():
        if isinstance(value, dict):
            cleaned[str(key)] = {
                "landscape_cluster_ids": [str(item) for item in value.get("landscape_cluster_ids") or [] if str(item)]
            }
    return cleaned


def _diagnostic_summary(payload: dict[str, Any]) -> dict[str, Any]:
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    return {
        "artifact_type": str(payload.get("artifact_type") or ""),
        "warnings": [str(value) for value in payload.get("warnings") or [] if str(value)],
        "coverage_warnings": [str(value) for value in coverage.get("coverage_warnings") or [] if str(value)],
        "missing_required_roles": [str(value) for value in coverage.get("missing_required_roles") or [] if str(value)],
    }


def _human(value: Any) -> str:
    text = str(value or "unknown")
    translations = {
        "llm_assisted_local_evidence_triage": "LLM 辅助的本地证据筛选",
        "likely_distinct_from_local_evidence": "可能区别于本地证据",
        "partial_overlap_with_local_evidence": "与本地证据部分重叠",
        "likely_overlapping_local_prior": "可能与本地既有证据重叠",
        "insufficient_local_evidence": "本地证据不足",
        "locally_supported": "本地证据支持",
        "partially_supported": "部分支持",
        "weakly_supported": "弱支持",
        "under_specified": "表述不足",
        "insufficient_evidence": "证据不足",
        "low_information_risk": "低信息量风险",
        "evidence_gap_risk": "证据缺口风险",
        "mechanism_risk": "机制风险",
        "synthesis_risk": "合成风险",
        "characterization_risk": "表征风险",
        "scope_risk": "范围风险",
        "mixed_risk": "混合风险",
        "advance_to_external_novelty_search": "推进到外部新颖性检索",
        "needs_more_local_evidence": "需要更多本地证据",
        "revise_candidate_scope": "需要修订候选范围",
        "deprioritize_for_now": "暂时降低优先级",
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "未知",
        "not_performed": "未执行",
    }
    return translations.get(text, text.replace("_", " "))


def _compact_list(values: list[Any], *, limit: int = 4) -> str:
    cleaned = [str(value) for value in values if str(value)]
    if not cleaned:
        return "无"
    if len(cleaned) <= limit:
        return ", ".join(cleaned)
    return f"{', '.join(cleaned[:limit])}，另有 {len(cleaned) - limit} 项"


def _forbidden_claim_matches(screening: dict[str, Any], markdown: str) -> list[str]:
    text = f"{json.dumps(screening, ensure_ascii=False)}\n{markdown}".lower()
    return [phrase for phrase in FORBIDDEN_SCREENING_CLAIMS if phrase in text]


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [] if str(warning))
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        warnings.extend(str(warning) for warning in coverage.get("coverage_warnings") or [] if str(warning))
    return _dedupe(warnings)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


def _read_json(execution: SkillExecutionInput, relative_path: str) -> Any:
    return json.loads(_path(execution, relative_path).read_text(encoding="utf-8"))


def _write_json(execution: SkillExecutionInput, relative_path: str, payload: dict[str, Any]) -> None:
    path = _path(execution, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _write_text(execution: SkillExecutionInput, relative_path: str, text: str) -> None:
    path = _path(execution, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _path(execution: SkillExecutionInput, relative_path: str) -> Path:
    return _store(execution).resolve_workspace_path(execution.task_id, relative_path)


def _store(execution: SkillExecutionInput) -> ResearchWorkspaceStore:
    root = Path(execution.workspace_root)
    if root.name != execution.task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2])


def _result(
    execution: SkillExecutionInput,
    status: SkillExecutionStatus | str,
    *,
    input_artifacts: list[str] | None = None,
    output_artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SkillExecutionResult:
    return SkillExecutionResult(
        task_id=execution.task_id,
        skill_name=execution.skill_name,
        status=status,
        input_artifacts=list(input_artifacts or execution.input_artifacts),
        output_artifacts=list(output_artifacts or []),
        warnings=list(warnings or []),
        errors=list(errors or []),
        metadata=dict(metadata or {}),
    )


__all__ = [
    "FORBIDDEN_SCREENING_CLAIMS",
    "render_screening_summary_markdown",
    "screen_novelty_feasibility_risk",
    "validate_screening_artifact",
]
