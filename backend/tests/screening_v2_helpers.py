import json
from typing import Any


def valid_screening_v2_screened_idea(
    *,
    idea_id: str = "idea_gap_comparison_001",
    title: str = "Candidate idea from comparison gap",
    gap_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    paper_id: str = "paper_001",
) -> dict[str, Any]:
    gap_ids = list(gap_ids or ["gap_comparison_001"])
    evidence_ids = list(evidence_ids or ["ecard_001", "ecard_002"])
    return {
        "idea_id": idea_id,
        "source_idea_title": title,
        "gap_ids": gap_ids,
        "evidence_ids": evidence_ids,
        "local_novelty_triage": {
            "judgment": "partial_overlap_with_local_evidence",
            "confidence": "medium",
            "closest_local_prior_evidence": [
                {
                    "evidence_id": evidence_ids[0],
                    "paper_id": paper_id,
                    "overlap": "Local evidence discusses related mechanisms.",
                    "difference": "The candidate remains a preliminary direction requiring external checks.",
                }
            ],
            "rationale": "The candidate has partial overlap with local evidence but is not resolved by it.",
            "limitations": ["Only local evidence artifacts were considered."],
        },
        "external_novelty_search": {
            "status": "not_performed",
            "required": True,
            "rationale": "External prior-work search is required before novelty claims.",
        },
        "feasibility_triage": {
            "judgment": "partially_supported",
            "confidence": "medium",
            "supporting_evidence": evidence_ids,
            "missing_requirements": ["synthesis details", "characterization evidence"],
            "constraints": ["Requires expert feasibility review."],
            "rationale": "Local evidence supports context but not execution feasibility.",
        },
        "risk_triage": {
            "judgment": "evidence_gap_risk",
            "confidence": "medium",
            "risk_factors": ["limited local evidence coverage"],
            "follow_up": ["external novelty search", "expert feasibility review", "risk review"],
            "rationale": "The dominant risk is evidence coverage.",
        },
        "overall_triage": {
            "judgment": "advance_to_external_novelty_search",
            "rationale": "The idea is locally grounded but must not proceed as a final decision.",
            "required_follow_up": ["external novelty search", "expert feasibility review", "risk review"],
        },
        "not_an_experiment_plan": True,
        "not_a_validated_claim": True,
        "warnings": ["screening_sparse_fixture"],
    }


def valid_screening_v2_artifact(
    *,
    task_id: str = "screening_v2_task",
    topic: str = "oxygen vacancy engineering for alkaline HER catalysts",
    screening_id: str = "idea_screening_screening_v2_task",
    idea_set_id: str = "candidate_ideas_screening_v2_task",
    gap_map_id: str = "gap_map_screening_v2_task",
    landscape_id: str = "landscape_screening_v2_task",
    evidence_ids: list[str] | None = None,
    source_paper_ids: list[str] | None = None,
    screened_ideas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence_ids = list(evidence_ids or ["ecard_001", "ecard_002"])
    source_paper_ids = list(source_paper_ids or ["paper_001", "paper_002"])
    return {
        "task_id": task_id,
        "topic": topic,
        "screening_id": screening_id,
        "input_artifacts": [],
        "idea_set_id": idea_set_id,
        "gap_map_id": gap_map_id,
        "landscape_id": landscape_id,
        "evidence_ids": evidence_ids,
        "source_paper_ids": source_paper_ids,
        "screened_ideas": list(screened_ideas or [valid_screening_v2_screened_idea(evidence_ids=evidence_ids)]),
        "analysis_mode": "llm_assisted_local_evidence_triage",
        "llm_provenance": {
            "provider": "scripted",
            "model": "screening-fixture",
            "prompt_version": "p2_m11_llm_screening_v1",
            "external_novelty_search_performed": False,
        },
        "screening_scope": {"source": "candidate_ideas"},
        "screening_policy": {
            "analysis_mode": "llm_assisted_local_evidence_triage",
            "not_an_experiment_plan": True,
            "not_a_validated_claim": True,
            "external_novelty_search_status": "not_performed",
        },
        "limitations": [
            "The analysis is limited to local artifacts.",
            "External novelty search was not performed.",
            "Expert feasibility review was not performed.",
            "Downstream risk review was not performed.",
        ],
        "warnings": ["screening_sparse_fixture"],
        "created_at": 0,
        "schema_version": "idea_screening_v2",
    }


class ScriptedScreeningLLM:
    provider = "scripted"
    model = "screening-fixture"

    async def stream_chat(self, messages, tools=None):
        packet = _packet_from_messages(messages)
        idea = packet["candidate_ideas"][0]
        evidence_ids = list(idea["evidence_basis"]["supporting_evidence_ids"])
        first_evidence = evidence_ids[0]
        paper_id = packet["evidence_reference_map"].get(first_evidence, {}).get("paper_id", "paper_001")
        payload = {
            "screened_ideas": [
                valid_screening_v2_screened_idea(
                    idea_id=idea["idea_id"],
                    title=idea["title"],
                    gap_ids=list(idea["gap_basis"]["gap_ids"]),
                    evidence_ids=evidence_ids,
                    paper_id=paper_id,
                )
            ]
        }
        yield {"type": "content", "text": json.dumps(payload, ensure_ascii=False)}


def _packet_from_messages(messages) -> dict[str, Any]:
    content = "\n".join(str(message.get("content", "")) for message in messages)
    return json.loads(content.split("EVIDENCE_PACKET_JSON:\n", 1)[1])
