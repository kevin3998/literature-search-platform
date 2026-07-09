"""Block 7/10 P1: corpus-stage workflow engine.

Exercises the real WorkflowStore + WorkflowOrchestrator + CorpusStageRunner over
the test memory DB, with a fake JobRunner/Service standing in for the underlying
ResearchRunManager (so tests never touch the real 87k index). The fakes mirror
the real manifest/checkpoint schema — bare requested_stages vs PREFIXED
completed/failed names — so the stage-mapping logic is genuinely covered.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest

if not os.getenv("TEST_DATABASE_URL"):
    pytest.skip("TEST_DATABASE_URL is not configured; skipping PostgreSQL workflow engine tests", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
os.environ.setdefault("AUTH_MODE", "dev-header")
os.environ.setdefault("APP_ENV", "development")

from modules.literature_search.job_store import JobStore
from modules.evidence_workflow.task_profiles import DEFAULT_TASK_PROFILE_ID
from modules.workflow import templates as templates_mod
from modules.workflow.orchestrator import WorkflowOrchestrator
from modules.workflow.runners.agent_step import AgentStepRunner
from modules.workflow.runners.base import STAGE_PREFIX, RunnerContext, expected_stages
from modules.workflow.runners.corpus_stage import CorpusStageRunner
from modules.workflow.runners.research_controller import ResearchControllerRunner, _acquire_timeout_seconds
from modules.workflow.store import WorkflowStore
from postgres_test_utils import migrated_postgres_schema


class ScriptedLLM:
    """Minimal LLMClient stand-in: streams canned content, captures messages."""

    def __init__(self, chunks=None):
        self.chunks = chunks if chunks is not None else ["# 候选研究 Idea\n", "## Idea 1：测试\n- 摘要：x\n"]
        self.last_messages = None
        self.calls = []

    async def stream_chat(self, messages, tools=None):
        self.last_messages = messages
        self.calls.append(messages)
        for chunk in self.chunks:
            yield {"type": "content", "text": chunk}


class ScriptedScreeningLLM:
    provider = "scripted"
    model = "workflow-screening-fixture"
    supports_screening = True

    async def stream_chat(self, messages, tools=None):
        content = "\n".join(str(message.get("content", "")) for message in messages)
        packet = json.loads(content.split("EVIDENCE_PACKET_JSON:\n", 1)[1])
        idea = packet["candidate_ideas"][0]
        evidence_ids = idea["evidence_basis"]["supporting_evidence_ids"]
        first_evidence = evidence_ids[0]
        evidence_map = packet["evidence_reference_map"]
        payload = {
            "screened_ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "source_idea_title": idea["title"],
                    "gap_ids": idea["gap_basis"]["gap_ids"],
                    "evidence_ids": evidence_ids,
                    "local_novelty_triage": {
                        "judgment": "partial_overlap_with_local_evidence",
                        "confidence": "medium",
                        "closest_local_prior_evidence": [
                            {
                                "evidence_id": first_evidence,
                                "paper_id": evidence_map[first_evidence]["paper_id"],
                                "overlap": "Local evidence covers related defect-engineering mechanisms.",
                                "difference": "The candidate still needs external novelty search and expert review.",
                            }
                        ],
                        "rationale": "The candidate overlaps local evidence but remains a preliminary triage result.",
                        "limitations": ["Only local workflow artifacts were considered."],
                    },
                    "external_novelty_search": {
                        "status": "not_performed",
                        "required": True,
                        "rationale": "External prior-work search is still required.",
                    },
                    "feasibility_triage": {
                        "judgment": "partially_supported",
                        "confidence": "medium",
                        "supporting_evidence": evidence_ids,
                        "missing_requirements": ["synthesis details", "characterization evidence"],
                        "constraints": ["Requires expert feasibility review."],
                        "rationale": "The local evidence supports context but not full feasibility.",
                    },
                    "risk_triage": {
                        "judgment": "evidence_gap_risk",
                        "confidence": "medium",
                        "risk_factors": ["limited local evidence coverage"],
                        "follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                        "rationale": "The key risk is limited evidence coverage.",
                    },
                    "overall_triage": {
                        "judgment": "advance_to_external_novelty_search",
                        "rationale": "Proceed only to external novelty search, not experiment planning.",
                        "required_follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                    },
                    "not_an_experiment_plan": True,
                    "not_a_validated_claim": True,
                }
            ]
        }
        yield {"type": "content", "text": json.dumps(payload, ensure_ascii=False)}

# An all-corpus template (every step runnable) so the fully-completed path is
# covered — production templates are ARIS pipelines that stop at the first
# not-yet-built agent step (partial), by design.
_ALL_CORPUS_TEMPLATE = {
    "id": "__test_all_corpus__",
    "category": "research",
    "name": "测试·全 corpus",
    "est": "test",
    "desc": "test",
    "steps": [
        {"step_key": "research-lit", "label": "文献调研", "runner": "corpus-stage", "available": True, "note": "", "params": {}},
        {"step_key": "research-lit-2", "label": "再次调研", "runner": "corpus-stage", "available": True, "note": "", "params": {"with_synthesis": True}},
    ],
}


@pytest.fixture(autouse=True)
def _register_test_template():
    templates_mod._BY_ID[_ALL_CORPUS_TEMPLATE["id"]] = _ALL_CORPUS_TEMPLATE
    yield
    templates_mod._BY_ID.pop(_ALL_CORPUS_TEMPLATE["id"], None)


class _Paths:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class FakeService:
    """Stands in for LiteratureResearchService.run / run_resume / run_show."""

    def __init__(self, data_dir=None):
        self.runs: dict[str, dict] = {}
        self.fail = False
        # Default: one packed evidence item so corpus retrieval "found" something
        # (the zero-evidence guard is exercised by setting this to []).
        self.pack_evidence = [
            {"evidence_id": "E1", "source_path": "papers/seed.md", "title": "Seed", "section": "Intro", "kind": "text", "text": "seed evidence"}
        ]
        self.evidence_candidates = [
            {
                "evidence_id": "ev_1",
                "paper_id": "paper_1",
                "title": "Oxygen vacancy engineering for alkaline HER catalysts",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
                "source_path": "paper_1/sections/results.md",
                "source_locator": {"section": "Results"},
                "relevance_score": 0.91,
            },
            {
                "evidence_id": "ev_2",
                "paper_id": "paper_2",
                "title": "Defect catalysts for alkaline HER",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": "Defect engineering changes adsorption and activity descriptors.",
                "source_path": "paper_2/sections/results.md",
                "source_locator": {"section": "Results"},
                "relevance_score": 0.88,
            },
        ]
        self.paths = _Paths(Path(data_dir) if data_dir else Path(tempfile.gettempdir()))
        self._scripted = None  # the ScriptedLLM the agent runner uses (test access)
        self.acquire_calls: list[dict] = []

    def _materialize(self, run_id: str, payload: dict) -> None:
        requested = expected_stages(payload)  # bare names
        prefixed = [STAGE_PREFIX[s] for s in requested]
        artifact_paths = {}
        if self.pack_evidence is not None:
            rel = f"research_agent/packs/{run_id}.json"
            (self.paths.data_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.paths.data_dir / rel).write_text(
                json.dumps({"query": payload.get("question"), "evidence": self.pack_evidence}), encoding="utf-8"
            )
            artifact_paths["pack"] = rel
        if self.fail:
            completed = prefixed[:-1]
            manifest = {"run_id": run_id, "status": "failed", "requested_stages": requested, "completed_stages": completed, "artifact_paths": artifact_paths}
            checkpoint = {"completed_stages": completed, "running_stage": None, "failed_stage": prefixed[-1], "error": "boom"}
        else:
            manifest = {"run_id": run_id, "status": "completed", "requested_stages": requested, "completed_stages": prefixed, "artifact_paths": artifact_paths}
            checkpoint = {"completed_stages": prefixed, "running_stage": None, "failed_stage": None}
        self.runs[run_id] = {"manifest": manifest, "checkpoint": checkpoint, "_payload": payload}

    def run_show(self, run_id: str) -> dict:
        if run_id not in self.runs:
            raise KeyError(run_id)
        return self.runs[run_id]

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options) -> dict:
        self.acquire_calls.append({"query": query, "has_history": has_history, "options": dict(options)})
        return {
            "evidence_candidates": list(self.evidence_candidates),
            "expanded_assets": [],
            "query_plan": {"query": query},
            "coverage": {"limit": options.get("limit")},
            "breadth": {"has_history": has_history},
            "warnings": [],
        }


class FakeJobRunner:
    """Synchronous stand-in: materializes the run + emits one artifact event."""

    def __init__(self, job_store: JobStore, service: FakeService):
        self.store = job_store
        self.service = service

    def submit(self, job_type: str, payload: dict) -> dict:
        self.last_job_type = job_type
        self.last_payload = dict(payload)
        job = self.store.create(job_type, payload, user_id=payload.get("user_id"))
        jid = job["job_id"]
        self.store.start(jid)
        run_id = payload["run_id"]
        if job_type == "run_resume":
            payload = self.service.runs[run_id]["_payload"]
        self.service._materialize(run_id, payload)
        self.store.add_event(
            jid,
            {
                "type": "artifact",
                "artifact_type": "run",
                "artifact_id": f"research_agent/runs/{run_id}/summary.md",
                "path": f"research_agent/runs/{run_id}/summary.md",
                "label": "run",
            },
        )
        if self.service.fail:
            self.store.fail(jid, "boom")
        else:
            self.store.complete(jid, {"run_id": run_id})
        return self.store.get(jid)


def _fake_external_search(topic, idea_text):
    return (
        [
            {
                "title": "Diffusion Models for Semantic Communication",
                "source": "arxiv",
                "year": 2025,
                "doi": None,
                "arxiv_id": "2501.00001",
                "url": "https://arxiv.org/abs/2501.00001",
                "abstract": "A close prior work on diffusion models and semantic communication.",
                "verification": "verified",
                "query": topic,
            }
        ],
        {
            "query_plan": ["diffusion semantic communication"],
            "year_from": 2023,
            "year_to": 2026,
            "arxiv": {"status": "ok", "count": 1},
            "semantic_scholar": {"status": "warning", "count": 0},
            "openalex": {"status": "warning", "count": 0},
            "exa": {"status": "skipped_no_api_key", "count": 0},
        },
    )


@pytest.fixture()
def engine():
    with migrated_postgres_schema():
        data_dir = Path(tempfile.gettempdir()) / f"wf_data_{uuid.uuid4().hex}"
        data_dir.mkdir(parents=True, exist_ok=True)
        store = WorkflowStore()
        job_store = JobStore()
        service = FakeService(data_dir=data_dir)
        scripted = ScriptedLLM()
        service._scripted = scripted
        service._screening_llm = ScriptedScreeningLLM()
        agent_runner = AgentStepRunner(llm_factory=lambda: scripted, external_search=_fake_external_search)
        runner = FakeJobRunner(job_store, service)
        orch = WorkflowOrchestrator(
            store, runner, job_store, service,
            runners={
                "corpus-stage": CorpusStageRunner(),
                "agent-step": agent_runner,
                "research-controller": ResearchControllerRunner(),
            },
        )
        store._test_orchestrator = orch
        yield store, orch, service, job_store


def _wait(store, workflow_id, *, timeout=5.0):
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime
    from modules.workflow.worker_handlers import build_workflow_registry

    deadline = time.time() + timeout
    while time.time() < deadline:
        orchestrator = getattr(store, "_test_orchestrator", None)
        if orchestrator is not None:
            runtime = WorkerRuntime(
                JobQueue(store.engine),
                build_workflow_registry(orchestrator=orchestrator),
                worker_id="test-workflow-worker",
                queues=["workflow"],
                max_jobs_per_tick=1,
            )
            runtime.run_once()
        status = store.get(workflow_id)["status"]
        if status in ("completed", "partial", "failed", "paused", "blocked"):
            return status
        time.sleep(0.05)
    raise AssertionError(f"workflow {workflow_id} did not settle (last={store.get(workflow_id)['status']})")


def test_default_templates_are_controlled_controller_templates():
    templates = templates_mod.list_templates()
    template_ids = {tpl["id"] for tpl in templates}

    assert template_ids == {
        "controlled-minimal-evidence",
        "controlled-landscape",
        "controlled-gap-mapping",
        "controlled-idea-generation",
        "controlled-screening",
    }
    assert "idea-discovery" not in template_ids
    assert "controlled-experiment-matrix" not in template_ids
    assert all(step["runner"] == "research-controller" for tpl in templates for step in tpl["steps"])
    assert all(
        stage["stage"] != "create_experiment_matrix"
        for tpl in templates
        for step in tpl["steps"]
        for stage in (step.get("params") or {}).get("stages", [])
    )


def test_controlled_screening_workflow_runs_p2_m11_without_experiment_matrix(engine):
    store, orch, service, job_store = engine
    wf = store.create("controlled-screening", topic="oxygen vacancy engineering for alkaline HER catalysts")
    assert wf["steps"][0]["runner"] == "research-controller"
    assert wf["steps"][0]["params"]["controller_plan_kind"] == "screening"

    orch.start(wf["workflow_id"])
    status = _wait(store, wf["workflow_id"], timeout=10.0)

    assert status == "completed"
    detail = orch.detail(wf["workflow_id"])
    artifacts = {
        artifact_id
        for step in detail["steps"]
        for artifact_id in (step.get("artifact_ids") or [])
    }
    assert any(item.endswith("screening/idea_screening_results.json") for item in artifacts)
    assert any(item.endswith("screening/idea_screening_results.md") for item in artifacts)
    assert any(item.endswith("screening/screening_diagnostics.json") for item in artifacts)
    assert not any("experiments/experiment_matrix" in item for item in artifacts)

    workspace_rel = detail["engine_ref"]["controller_workspace_rel_path"]
    workspace_root = Path(service.paths.data_dir) / workspace_rel
    assert (workspace_root / "screening/idea_screening_results.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    screening = json.loads((workspace_root / "screening/idea_screening_results.json").read_text(encoding="utf-8"))
    assert screening["schema_version"] == "idea_screening_v2"
    assert screening["analysis_mode"] == "llm_assisted_local_evidence_triage"
    assert all(item["local_novelty_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["external_novelty_search"]["status"] == "not_performed" for item in screening["screened_ideas"])
    assert all(item["feasibility_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["risk_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["not_an_experiment_plan"] is True for item in screening["screened_ideas"])
    assert all(item["not_a_validated_claim"] is True for item in screening["screened_ideas"])
    display_output = detail["steps"][0].get("output_text") or ""
    assert "# LLM 辅助筛选摘要" in display_output
    assert "局部新颖性筛选" in display_output
    assert "diagnostic reference=" not in display_output
    assert len(display_output) < 20_000

    orch_job_id = detail["engine_ref"]["orchestrator_job_id"]
    events = job_store.events(orch_job_id)
    executed_stages = [event.get("stage", "") for event in events if event.get("type") == "stage"]
    assert any(stage.endswith("screen_novelty_feasibility_risk") for stage in executed_stages)
    assert not any("create_experiment_matrix" in stage for stage in executed_stages)


def test_controlled_workflow_detail_rehydrates_markdown_output_and_artifact_labels(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-minimal-evidence", topic="large language models materials discovery")

    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"], timeout=10.0) == "completed"

    detail = orch.detail(wf["workflow_id"])
    step = detail["steps"][0]
    assert "# Minimal Topic-to-Evidence Report" in step["output_text"]
    assert "large language models materials discovery" in step["output_text"]

    report_artifact = next(
        item for item in detail["artifacts"]
        if item["artifact_id"].endswith("reports/minimal_topic_to_evidence_report.md")
    )
    assert report_artifact["label"] == "最小证据报告"
    assert report_artifact["artifact_type"] == "build_minimal_topic_to_evidence_report"


def test_workflow_artifact_preview_reads_registered_markdown_artifact(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-minimal-evidence", topic="large language models materials discovery")

    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"], timeout=10.0) == "completed"

    detail = orch.detail(wf["workflow_id"])
    artifact = next(
        item for item in detail["artifacts"]
        if item["artifact_id"].endswith("reports/minimal_topic_to_evidence_report.md")
    )
    preview = orch.artifact_preview(wf["workflow_id"], artifact["artifact_id"])

    assert preview["workflow_id"] == wf["workflow_id"]
    assert preview["artifact_id"] == artifact["artifact_id"]
    assert preview["artifact_type"] == "build_minimal_topic_to_evidence_report"
    assert preview["label"] == "最小证据报告"
    assert preview["content_type"] == "markdown"
    assert "# Minimal Topic-to-Evidence Report" in preview["text"]
    assert preview["json"] is None


def test_workflow_artifact_preview_reads_registered_json_artifact(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-minimal-evidence", topic="large language models materials discovery")

    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"], timeout=10.0) == "completed"

    detail = orch.detail(wf["workflow_id"])
    artifact = next(
        item for item in detail["artifacts"]
        if item["artifact_id"].endswith("reports/minimal_topic_to_evidence_report.json")
    )
    preview = orch.artifact_preview(wf["workflow_id"], artifact["artifact_id"])

    assert preview["content_type"] == "json"
    assert isinstance(preview["json"], dict)
    assert preview["json"]
    assert preview["text"].startswith("{\n")
    assert preview["text"] == json.dumps(preview["json"], ensure_ascii=False, indent=2, sort_keys=True)


def test_workflow_artifact_preview_rejects_unregistered_artifact(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-minimal-evidence", topic="large language models materials discovery")
    outside = service.paths.data_dir / "research_agent" / "outside.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text('{"secret": true}', encoding="utf-8")

    with pytest.raises(KeyError, match="artifact not found"):
        orch.artifact_preview(wf["workflow_id"], "research_agent/outside.json")


def test_workflow_insights_summarizes_registered_evidence_and_diagnostics(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-screening", topic="large language models materials discovery")

    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"], timeout=10.0) == "completed"

    insights = orch.workflow_insights(wf["workflow_id"])

    assert insights["workflow_id"] == wf["workflow_id"]
    evidence = insights["evidence"]
    assert evidence["available"] is True
    assert evidence["card_count"] >= 1
    assert evidence["selected_count"] >= 1
    assert evidence["role_counts"]
    assert evidence["support_counts"]
    first_card = evidence["cards"][0]
    assert set(first_card) >= {
        "evidence_id",
        "paper_id",
        "title",
        "role",
        "normalized_statement",
        "support_strength",
        "selected",
        "artifact_id",
    }
    assert any(card["selected"] is True for card in evidence["cards"])
    assert all(card["artifact_id"].endswith("evidence/evidence_cards.enriched.json") for card in evidence["cards"])

    diagnostics = insights["diagnostics"]
    assert diagnostics["available"] is True
    assert diagnostics["severity_counts"]["info"] + diagnostics["severity_counts"]["warning"] + diagnostics["severity_counts"]["error"] == len(diagnostics["items"])
    diagnostic_ids = {item["diagnostic_id"] for item in diagnostics["items"]}
    assert "screening_diagnostics" in diagnostic_ids
    screening_item = next(item for item in diagnostics["items"] if item["diagnostic_id"] == "screening_diagnostics")
    assert screening_item["stage"] == "screen_novelty_feasibility_risk"
    assert screening_item["label"] == "筛选诊断"
    assert screening_item["severity"] in {"info", "warning", "error"}
    assert screening_item["artifact_id"].endswith("screening/screening_diagnostics.json")


def test_workflow_insights_rejects_unregistered_evidence_file(engine):
    store, orch, service, _ = engine
    wf = store.create("controlled-minimal-evidence", topic="large language models materials discovery")
    outside = service.paths.data_dir / "research_agent" / "outside_evidence.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text('{"cards": [{"evidence_id": "secret"}]}', encoding="utf-8")

    insights = orch.workflow_insights(wf["workflow_id"])

    assert insights["evidence"]["available"] is False
    assert insights["evidence"]["cards"] == []
    assert "secret" not in json.dumps(insights, ensure_ascii=False)


def test_controlled_research_runner_passes_workflow_scope_lock_to_retrieval(engine):
    store, orch, service, _ = engine
    wf = store.create(
        "controlled-minimal-evidence",
        topic="large language models materials discovery",
        scope="library+boost",
        scope_options={"year_from": 2021, "collection": "materials-ai", "limit": 9},
    )

    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"], timeout=10.0) == "completed"

    assert service.acquire_calls
    options = service.acquire_calls[0]["options"]
    assert options["scope"] == "library+boost"
    assert options["year_from"] == 2021
    assert options["collection"] == "materials-ai"
    assert options["limit"] == 9


def test_research_controller_default_acquire_timeout_allows_slow_local_retrieval():
    assert _acquire_timeout_seconds(object()) >= 300


def test_research_controller_acquire_evidence_timeout_returns_safe_empty_packet(tmp_path):
    class SlowService(FakeService):
        workflow_acquire_evidence_timeout_seconds = 0.01

        def acquire_evidence(self, query: str, *, has_history: bool = False, **options) -> dict:
            time.sleep(0.2)
            return super().acquire_evidence(query, has_history=has_history, **options)

    service = SlowService(data_dir=tmp_path)
    acquire = ResearchControllerRunner._acquire_evidence_fn(service)

    packet = acquire("large language models materials discovery", has_history=False, scope="library")

    assert packet["evidence_candidates"] == []
    assert "retrieval_timeout" in packet["warnings"]
    assert packet["coverage"]["status"] == "none"
    assert "timed out" in packet["coverage_notes"][0]


def test_controlled_workflow_blocks_fast_when_retrieval_has_no_evidence(engine):
    store, orch, service, job_store = engine
    service.evidence_candidates = []
    wf = store.create("controlled-screening", topic="some local-index miss")

    orch.start(wf["workflow_id"])
    status = _wait(store, wf["workflow_id"], timeout=10.0)

    assert status == "blocked"
    detail = orch.detail(wf["workflow_id"])
    step = detail["steps"][0]
    assert step["status"] == "blocked"
    assert "未找到可用的本地证据" in (step["error"] or "")
    assert any(item.endswith("retrieval/source_candidate_packet.json") for item in step["artifact_ids"])

    orch_job_id = detail["engine_ref"]["orchestrator_job_id"]
    events = job_store.events(orch_job_id)
    executed_stages = [event.get("stage", "") for event in events if event.get("type") == "stage"]
    assert any(stage.endswith("retrieve_sources") for stage in executed_stages)
    assert not any(stage.endswith("map_gaps") for stage in executed_stages)
    assert not any("screen_novelty_feasibility_risk" in stage for stage in executed_stages)


def test_create_draft_has_planned_stages(engine):
    store, orch, *_ = engine
    wf = store.create("idea-discovery", topic="perovskite stability")
    assert wf["status"] == "draft"
    assert [s["step_key"] for s in wf["steps"]] == ["research-lit", "idea-creator", "novelty-check", "idea-report"]
    assert all(s["status"] == "pending" for s in wf["steps"])
    detail = orch.detail(wf["workflow_id"])
    stages = detail["steps"][0]["stages"]
    assert [s["stage"] for s in stages] == ["selfcheck", "plan", "task", "pack"]
    assert all(s["status"] == "pending" for s in stages)
    novelty_stages = detail["steps"][2]["stages"]
    assert [s["stage"] for s in novelty_stages] == [
        "agent-2-prepare_claims",
        "agent-2-local_overlap",
        "agent-2-external_query_plan",
        "agent-2-external_search",
        "agent-2-paper_verification",
        "agent-2-novelty_synthesis",
        "agent-2-artifact_write",
    ]
    assert all(s["status"] == "pending" for s in novelty_stages)
    report_stages = detail["steps"][3]["stages"]
    assert [s["stage"] for s in report_stages] == [
        "agent-3-collect_inputs",
        "agent-3-structure_report",
        "agent-3-report_synthesis",
        "agent-3-artifact_write",
    ]
    assert all(s["status"] == "pending" for s in report_stages)


def test_create_records_task_profile_and_scope_lock(engine):
    store, orch, *_ = engine
    wf = store.create(
        "idea-discovery",
        topic="solid-state battery interfaces",
        scope="library",
        task_profile_id="topic-to-report",
        scope_options={"year_from": 2020, "limit": 25},
    )

    assert wf["task_profile_id"] == "topic-to-report"
    assert wf["task_profile"]["profile_id"] == "topic-to-report"
    assert wf["task_profile"]["required_evidence_roles"] == [
        "background",
        "material_system",
        "method",
        "property",
        "performance",
        "mechanism",
        "comparison",
        "limitation",
        "condition",
        "figure_evidence",
        "table_evidence",
    ]
    assert "every_report_claim_requires_evidence_cards" in wf["task_profile"]["audit_rules"]
    assert wf["scope_lock"]["topic"] == "solid-state battery interfaces"
    assert wf["scope_lock"]["scope"] == "library"
    assert wf["scope_lock"]["scope_options"] == {"year_from": 2020, "limit": 25}
    assert wf["scope_lock"]["task_profile_id"] == "topic-to-report"
    assert isinstance(wf["scope_lock"]["locked_at"], float)
    assert wf["manifest"]["task_profile_id"] == wf["task_profile_id"]
    assert wf["manifest"]["task_profile"] == wf["task_profile"]
    assert wf["manifest"]["scope_lock"] == wf["scope_lock"]

    detail = orch.detail(wf["workflow_id"])
    assert detail["task_profile_id"] == "topic-to-report"
    assert detail["task_profile"]["profile_id"] == "topic-to-report"
    assert detail["scope_lock"] == wf["scope_lock"]


def test_create_defaults_to_topic_to_report_task_profile(engine):
    store, *_ = engine
    wf = store.create("idea-discovery", topic="default profile")

    assert wf["task_profile_id"] == DEFAULT_TASK_PROFILE_ID
    assert wf["manifest"]["task_profile"]["profile_id"] == DEFAULT_TASK_PROFILE_ID


def test_list_includes_task_profile_summary(engine):
    store, *_ = engine
    wf = store.create("idea-discovery", topic="profile summary")

    listed = next(item for item in store.list() if item["workflow_id"] == wf["workflow_id"])
    assert listed["task_profile_id"] == "topic-to-report"
    assert listed["task_profile_name"] == "Topic-to-Report"


def test_create_rejects_stub_task_profile(engine):
    store, *_ = engine

    with pytest.raises(ValueError, match="not runnable"):
        store.create("idea-discovery", topic="stub profile", task_profile_id="experiment-plan")


def test_idea_discovery_runs_to_idea_report(engine):
    store, orch, service, job_store = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="discrete diffusion LMs")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])
    assert detail["steps"][0]["status"] == "done"   # 文献调研
    assert detail["steps"][1]["status"] == "done"   # Idea 生成
    assert detail["steps"][2]["status"] == "done"   # 新颖性验证
    assert detail["steps"][3]["status"] == "done"   # Idea 报告
    # the agent steps produced idea + novelty artifacts and streamed tokens
    assert any("IDEA_CANDIDATES" in a for a in detail["steps"][1]["artifact_ids"])
    assert any("NOVELTY_CHECK" in a and a.endswith(".md") for a in detail["steps"][2]["artifact_ids"])
    assert any("NOVELTY_CHECK" in a and a.endswith(".json") for a in detail["steps"][2]["artifact_ids"])
    assert any("IDEA_REPORT" in a and a.endswith(".md") for a in detail["steps"][3]["artifact_ids"])
    assert any("IDEA_REPORT" in a and a.endswith(".json") for a in detail["steps"][3]["artifact_ids"])
    orch_job_id = store.get(wf["workflow_id"])["engine_ref"]["orchestrator_job_id"]
    events = job_store.events(orch_job_id)
    assert any(e.get("type") == "token" for e in events)
    assert any(e.get("type") == "stage" and e.get("stage") == "agent-2-external_search" for e in events)
    assert any(e.get("type") == "artifact" and e.get("label") == "新颖性验证报告" for e in events)
    assert any(e.get("type") == "artifact" and e.get("label") == "新颖性验证数据" for e in events)
    assert any(e.get("type") == "artifact" and e.get("label") == "Idea 报告" for e in events)
    assert any(e.get("type") == "artifact" and e.get("label") == "Idea 报告数据" for e in events)
    # the idea-generation system prompt actually reached the LLM
    assert any("Idea 生成" in m["content"] for call in service._scripted.calls for m in call if m["role"] == "system")
    assert any("世界范围" in m["content"] for call in service._scripted.calls for m in call if m["role"] == "system")
    assert any("最终研究 idea 报告" in m["content"] for call in service._scripted.calls for m in call if m["role"] == "system")


def test_detail_rehydrates_history(engine):
    # Re-entering a finished run must NOT be blank: detail() returns the agent
    # step's generated content + a run log rebuilt from persisted job events.
    store, orch, service, _ = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="discrete diffusion LMs")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])  # simulates leaving + re-opening
    step3 = detail["steps"][3]
    assert step3["runner"] == "agent-step"
    assert "候选研究 Idea" in (detail["steps"][1].get("output_text") or "")
    assert step3.get("output_text")
    assert detail["history_log"] and any("步骤" in e["line"] for e in detail["history_log"])


def test_agent_step_injects_local_evidence(engine):
    store, orch, service, _ = engine
    service.fail = False
    service.pack_evidence = [
        {"evidence_id": "E42", "source_path": "papers/x.md", "title": "Cola-DLM", "section": "Method", "kind": "text", "text": "factorized gap analysis"}
    ]
    wf = store.create("idea-discovery", topic="discrete diffusion LMs")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    user_msg = next(m["content"] for m in service._scripted.last_messages if m["role"] == "user")
    assert "E42" in user_msg and "papers/x.md" in user_msg
    assert "IDEA_CANDIDATES" in user_msg
    # corpus step recorded the (passthrough) English search query for audit
    assert "search_query" in store.get(wf["workflow_id"])["engine_ref"]


def test_novelty_check_writes_structured_json_with_external_prior_work(engine):
    store, orch, service, _ = engine
    service.fail = False
    service.pack_evidence = [
        {"evidence_id": "E7", "source_path": "papers/prior.md", "title": "Prior Work", "section": "Abstract", "kind": "text", "text": "semantic communication with diffusion models"}
    ]
    wf = store.create("idea-discovery", topic="semantic communication diffusion")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])
    json_artifact = next(a for a in detail["steps"][2]["artifact_ids"] if a.endswith(".json"))
    data = json.loads((service.paths.data_dir / json_artifact).read_text(encoding="utf-8"))
    assert data["workflow_id"] == wf["workflow_id"]
    assert data["source_status"]["arxiv"]["status"] in {"ok", "warning", "error"}
    assert data["source_status"]["exa"]["status"] == "skipped_no_api_key"
    assert data["verification_summary"]["verdict"] in {"PASS", "WARN", "BLOCKED", "ERROR"}
    assert "query_quality" in data
    assert data["ideas"]
    idea = data["ideas"][0]
    assert idea["local_overlaps"][0]["evidence_id"] == "E7"
    assert idea["external_prior_work"]
    assert idea["external_prior_work"][0]["verification"] in {"verified", "verify_pending", "source_error", "unverified"}


def test_idea_report_writes_structured_json(engine):
    store, orch, service, job_store = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="semantic communication diffusion")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])
    json_artifact = next(a for a in detail["steps"][3]["artifact_ids"] if a.endswith(".json"))
    data = json.loads((service.paths.data_dir / json_artifact).read_text(encoding="utf-8"))
    assert data["workflow_id"] == wf["workflow_id"]
    assert data["topic"] == "semantic communication diffusion"
    assert set(data) >= {"created_at", "inputs", "summary", "ideas", "warnings", "limitations"}
    assert data["summary"]["total_ideas"] >= 1
    assert data["summary"]["overall_readiness"] in {"READY_FOR_EXPERIMENT_BRIDGE", "NEEDS_MORE_SEARCH", "NEEDS_MANUAL_REVIEW"}
    idea = data["ideas"][0]
    assert set(idea) >= {
        "idea_id",
        "title",
        "core_hypothesis",
        "supporting_evidence",
        "local_novelty",
        "world_novelty",
        "closest_prior_work",
        "score",
        "recommendation",
        "risks",
        "positioning",
        "minimal_viable_experiment",
        "next_actions",
    }
    orch_job_id = store.get(wf["workflow_id"])["engine_ref"]["orchestrator_job_id"]
    assert any(e.get("type") == "stage" and e.get("stage") == "agent-3-report_synthesis" for e in job_store.events(orch_job_id))


def test_idea_report_requires_novelty_json(engine):
    store, orch, service, job_store = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="report guard")
    wf_id = wf["workflow_id"]
    run_id = "run-report-guard"
    service._materialize(run_id, {"run_id": run_id, "question": "report guard"})
    store.set_engine_ref(wf_id, run_id_0=run_id)
    ideas_rel = f"research_agent/workflow_ideas/{wf_id}/IDEA_CANDIDATES_fake.md"
    novelty_rel = f"research_agent/workflow_ideas/{wf_id}/NOVELTY_CHECK_fake.md"
    for rel, text in [(ideas_rel, "# 候选研究 Idea\n### Idea 1：x"), (novelty_rel, "# 新颖性验证报告")]:
        path = service.paths.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    store.update_step(wf_id, 0, status="done")
    store.update_step(wf_id, 1, status="done", artifact_ids=[ideas_rel])
    store.update_step(wf_id, 2, status="done", artifact_ids=[novelty_rel])
    orch_job = job_store.create("workflow", {"workflow_id": wf_id})
    job_store.start(orch_job["job_id"])
    report_step = store.get(wf_id)["steps"][3]
    with pytest.raises(Exception) as exc:
        orch.runners["agent-step"].execute(wf_id, report_step, orch_job["job_id"], resume=False, ctx=RunnerContext(store, job_store, orch.job_runner, service))
    assert "缺少新颖性验证数据" in str(exc.value)


def test_no_local_evidence_fails_fast(engine):
    # Zero retrieval hits → the Idea 生成 guard stops instead of producing
    # an ungrounded report (the 2026-06-29 regression).
    store, orch, service, _ = engine
    service.fail = False
    service.pack_evidence = []  # corpus retrieval found nothing
    wf = store.create("idea-discovery", topic="some niche topic")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "failed"
    detail = orch.detail(wf["workflow_id"])
    assert detail["steps"][0]["status"] == "done"        # 文献调研 ran
    assert detail["steps"][1]["status"] == "failed"      # Idea 生成 stopped
    assert "本地检索无果" in (detail["steps"][1]["error"] or "")


def test_to_search_query_translates_non_ascii():
    # A non-ASCII direction is translated to an English search query; ASCII
    # passes through with no LLM call (the corpus is English-only).
    from modules.workflow.query_lang import to_search_query

    scripted = ScriptedLLM(["perovskite solar cell stability"])
    assert to_search_query("钙钛矿太阳能电池稳定性", llm_factory=lambda: scripted) == "perovskite solar cell stability"

    def _boom():
        raise AssertionError("should not call LLM for ASCII input")

    assert to_search_query("battery cycle life", llm_factory=_boom) == "battery cycle life"


def test_gen_run_id_handles_non_ascii():
    from modules.workflow.runners.base import gen_run_id

    rid = gen_run_id("钙钛矿太阳能电池")
    # no longer collapses to the generic "research-run" — a content hash slug
    assert rid.startswith("run-") and not rid.endswith("research-run")
    assert gen_run_id("钙钛矿太阳能电池") != gen_run_id("锂离子电池")


def test_all_corpus_completes_with_stages_and_artifact(engine):
    store, orch, service, _ = engine
    service.fail = False
    wf = store.create("__test_all_corpus__", topic="solar cells")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])
    assert all(s["status"] == "done" for s in detail["steps"])
    step0 = detail["steps"][0]
    assert step0["artifact_ids"] and "summary.md" in step0["artifact_ids"][0]
    assert detail["artifacts"]


def test_partial_when_stops_at_unavailable(engine):
    store, orch, service, _ = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="solar cells")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "completed"
    detail = orch.detail(wf["workflow_id"])
    assert detail["steps"][0]["status"] == "done"          # 文献调研 (corpus)
    assert detail["steps"][1]["status"] == "done"          # Idea 生成 (agent)
    assert detail["steps"][2]["status"] == "done"          # 新颖性验证
    assert detail["steps"][3]["status"] == "done"          # Idea 报告


def test_blocked_when_first_step_unavailable(engine):
    store, orch, service, _ = engine
    wf = store.create("experiment-bridge", topic="anything")  # all agent steps
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "blocked"
    assert all(s["status"] == "unavailable" for s in orch.detail(wf["workflow_id"])["steps"])


def test_start_failure_records_failed_stage(engine):
    store, orch, service, _ = engine
    service.fail = True
    wf = store.create("idea-discovery", topic="batteries")
    orch.start(wf["workflow_id"])
    assert _wait(store, wf["workflow_id"]) == "failed"
    detail = orch.detail(wf["workflow_id"])
    step = detail["steps"][0]
    assert step["status"] == "failed"
    assert step["error"]
    statuses = {s["stage"]: s["status"] for s in step["stages"]}
    assert "failed" in statuses.values()


def test_resume_after_failure_completes(engine):
    store, orch, service, _ = engine
    service.fail = True
    wf = store.create("__test_all_corpus__", topic="catalysis")
    wid = wf["workflow_id"]
    orch.start(wid)
    assert _wait(store, wid) == "failed"
    # fix the underlying condition and resume — reuses the same run_id.
    service.fail = False
    orch.start(wid, resume=True)
    assert _wait(store, wid) == "completed"
    assert orch.detail(wid)["steps"][0]["status"] == "done"


def test_stream_events_carry_step_and_stage(engine):
    store, orch, service, job_store = engine
    service.fail = False
    wf = store.create("idea-discovery", topic="anything")
    orch.start(wf["workflow_id"])
    _wait(store, wf["workflow_id"])
    orch_job_id = store.get(wf["workflow_id"])["engine_ref"]["orchestrator_job_id"]
    types = {e.get("type") for e in job_store.events(orch_job_id)}
    assert {"step", "stage", "artifact", "workflow_status", "done"} <= types
    events = job_store.events(orch_job_id)
    assert events[0]["_event_index"] == 0
    assert job_store.events(orch_job_id, after=1)[0]["_event_index"] == 1
    detail = orch.detail(wf["workflow_id"])
    assert detail["next_event_index"] == events[-1]["_event_index"] + 1


def test_list_and_soft_delete(engine):
    store, orch, *_ = engine
    wf = store.create("idea-discovery", topic="x")
    assert any(w["workflow_id"] == wf["workflow_id"] for w in store.list())
    store.soft_delete(wf["workflow_id"])
    assert all(w["workflow_id"] != wf["workflow_id"] for w in store.list())
