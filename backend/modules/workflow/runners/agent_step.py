"""Agent-step runner — runs a ported ARIS step as a platform-native LLM generation.

P2 first runner. It loads a step def (system prompt + user builder), injects the
prior corpus step's local evidence (read from that run's pack artifact), streams
the platform LLM client's generation as ``token`` events onto the workflow's
event stream, and writes the result as an artifact. No tools: generation
consumes already-retrieved evidence and must not re-search.

Uses the LLM client directly (not the chat AgentLoop) because the chat loop
carries citation-enforcement / grounding semantics meant for Q&A answers, which
don't fit free-form idea generation. Same underlying client + provider config.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.memory_db import now
from core.workspace_paths import user_data_rel_prefix, user_workspace_root

from .base import RunnerContext, StepFailed
from ..scholarly_search import render_external_context, search_external_sources

_EVIDENCE_LIMIT = 20
_TEXT_CLIP = 600


class AgentStepRunner:
    name = "agent-step"

    def __init__(self, llm_factory=None, external_search=None) -> None:
        # Injectable for tests (a ScriptedLLM factory); None → real client.
        self._llm_factory = llm_factory
        self._external_search = external_search or search_external_sources

    def _llm(self):
        if self._llm_factory is not None:
            return self._llm_factory()
        from core.settings_store import settings_store
        from core.llm.client import build_llm_client

        return build_llm_client(settings_store)

    def execute(
        self,
        workflow_id: str,
        step: dict[str, Any],
        orch_job_id: str,
        *,
        resume: bool,
        ctx: RunnerContext,
    ) -> list[str]:
        from ..step_defs import StepInputContext, get_step_def

        store, job_store, service = ctx.store, ctx.job_store, ctx.service
        si = step["step_index"]
        store.update_step(workflow_id, si, status="running", started_at=now())
        self._emit_step(job_store, orch_job_id, step, "running")

        sdef = get_step_def(step["step_key"])
        if sdef is None:
            return self._fail(store, job_store, orch_job_id, workflow_id, step, f"未实现的 agent-step：{step['step_key']}")

        wf = store.get(workflow_id)
        topic = wf.get("topic") or ""
        user_id = wf.get("user_id") or (step.get("params") or {}).get("user_id") or "local_user"
        run_id = _latest_corpus_run_id(wf.get("engine_ref") or {})
        evidence_block, evidence_count = _load_evidence(service, run_id)
        # Ported ARIS guard (research-lit: zero verified_local → stop before
        # synthesis). Without it a no-hit retrieval silently yields ungrounded
        # ideas — exactly the misleading report seen on 2026-06-29.
        if evidence_count == 0:
            return self._fail(
                store, job_store, orch_job_id, workflow_id, step,
                "本地检索无果：上一步「文献调研」未找到可用证据（0 条）。已停止 Idea 生成，"
                "以避免产出缺乏本地接地的结果。可能原因：研究方向与英文语料语言不匹配，"
                "或语料未覆盖该主题。建议改用更具体的英文研究方向后重试。",
            )
        prior_artifacts = _load_prior_artifacts(service, wf, step)
        missing = [key for key in sdef.requires_prior_artifacts if not prior_artifacts.get(key)]
        if missing:
            err = _missing_prior_message(sdef.step_key, missing)
            return self._fail(
                store, job_store, orch_job_id, workflow_id, step,
                err,
            )
        external_context: dict[str, Any] = {}
        if sdef.step_key == "novelty-check":
            external_context = self._prepare_novelty_context(job_store, orch_job_id, step, topic, prior_artifacts.get("idea-creator") or "")
        elif sdef.step_key == "idea-report":
            self._emit_stage(job_store, orch_job_id, step, "collect_inputs", "done")
            self._emit_stage(job_store, orch_job_id, step, "structure_report", "done")
            self._emit_stage(job_store, orch_job_id, step, "report_synthesis", "running")
        input_ctx = StepInputContext(
            workflow_id=workflow_id,
            topic=topic,
            evidence_block=evidence_block,
            evidence_count=evidence_count,
            prior_artifacts=prior_artifacts,
            external_context=external_context,
        )
        messages = [
            {"role": "system", "content": sdef.system_prompt},
            {"role": "user", "content": sdef.build_user(input_ctx)},
        ]

        try:
            llm = self._llm()
        except Exception as exc:  # noqa: BLE001 - surface a clean step error
            return self._fail(store, job_store, orch_job_id, workflow_id, step, f"LLM 不可用：{exc}")

        try:
            full = asyncio.run(self._generate(llm, messages, job_store, orch_job_id))
        except Exception as exc:  # noqa: BLE001
            return self._fail(store, job_store, orch_job_id, workflow_id, step, f"生成失败：{exc}")

        if not full.strip():
            return self._fail(store, job_store, orch_job_id, workflow_id, step, "生成结果为空")

        if sdef.step_key == "novelty-check":
            artifact_ids = self._write_novelty_artifacts(
                service, job_store, orch_job_id, workflow_id, user_id, step, sdef, full, input_ctx
            )
        elif sdef.step_key == "idea-report":
            artifact_ids = self._write_idea_report_artifacts(
                service, job_store, orch_job_id, workflow_id, user_id, step, sdef, full, input_ctx
            )
        else:
            artifact_ids = self._write_artifact(service, job_store, orch_job_id, workflow_id, user_id, sdef, full)
        store.update_step(workflow_id, si, status="done", ended_at=now(), artifact_ids=artifact_ids)
        self._mark_all_stages(job_store, orch_job_id, step, "done")
        self._emit_step(job_store, orch_job_id, step, "done")
        return artifact_ids

    def _prepare_novelty_context(self, job_store, orch_job_id, step, topic: str, idea_text: str) -> dict[str, Any]:
        self._emit_stage(job_store, orch_job_id, step, "prepare_claims", "running")
        ideas = _extract_ideas(idea_text)
        self._emit_stage(job_store, orch_job_id, step, "prepare_claims", "done")
        self._emit_stage(job_store, orch_job_id, step, "local_overlap", "done")
        self._emit_stage(job_store, orch_job_id, step, "external_query_plan", "running")
        query_seed = "\n\n".join(ideas[:3]) if ideas else idea_text
        self._emit_stage(job_store, orch_job_id, step, "external_query_plan", "done")
        self._emit_stage(job_store, orch_job_id, step, "external_search", "running")
        try:
            candidates, status = self._external_search(topic, query_seed)
        except Exception as exc:  # noqa: BLE001 - hard guard; helper normally degrades
            candidates = []
            status = {"source_error": {"status": "error", "errors": [str(exc)]}}
        self._emit_stage(job_store, orch_job_id, step, "external_search", "done")
        self._emit_stage(job_store, orch_job_id, step, "paper_verification", "done")
        return {
            "ideas": ideas,
            "external_candidates": candidates,
            "source_status": status,
            "markdown": render_external_context(candidates, status),
        }

    async def _generate(self, llm, messages, job_store, orch_job_id) -> str:
        parts: list[str] = []
        async for delta in llm.stream_chat(messages, None):
            if delta.get("type") == "content":
                text = delta.get("text") or ""
                if text:
                    parts.append(text)
                    job_store.add_event(orch_job_id, {"type": "token", "text": text})
        return "".join(parts)

    def _write_artifact(self, service, job_store, orch_job_id, workflow_id, user_id, sdef, full) -> list[str]:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = f"{sdef.artifact_stem}_{ts}.md"
        user_rel = f"research_agent/workflow_ideas/{workflow_id}/{fname}"
        artifact_id = f"{user_data_rel_prefix(user_id)}/{user_rel}"
        try:
            out = user_workspace_root(user_id) / user_rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(full, encoding="utf-8")
            _mirror_to_service_data_dir(service, artifact_id, full)
        except Exception:  # noqa: BLE001 - degrade to an inline artifact (no file)
            pass
        job_store.add_event(
            orch_job_id,
            {
                "type": "artifact",
                "artifact_type": sdef.artifact_kind,
                "artifact_id": artifact_id,
                "path": artifact_id,
                "label": sdef.artifact_label,
            },
        )
        return [artifact_id]

    def _write_novelty_artifacts(self, service, job_store, orch_job_id, workflow_id, user_id, step, sdef, full, input_ctx) -> list[str]:
        self._emit_stage(job_store, orch_job_id, step, "novelty_synthesis", "done")
        self._emit_stage(job_store, orch_job_id, step, "artifact_write", "running")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"research_agent/workflow_ideas/{workflow_id}/{sdef.artifact_stem}_{ts}"
        md_rel = f"{base}.md"
        json_rel = f"{base}.json"
        md_id = f"{user_data_rel_prefix(user_id)}/{md_rel}"
        json_id = f"{user_data_rel_prefix(user_id)}/{json_rel}"
        data = _novelty_json(workflow_id, input_ctx, full)
        try:
            data_dir = user_workspace_root(user_id)
            (data_dir / md_rel).parent.mkdir(parents=True, exist_ok=True)
            (data_dir / md_rel).write_text(full, encoding="utf-8")
            (data_dir / json_rel).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _mirror_to_service_data_dir(service, md_id, full)
            _mirror_to_service_data_dir(service, json_id, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:  # noqa: BLE001 - still emit ids for inline visibility
            pass
        for rel, label, kind in (
            (md_id, "新颖性验证报告", "novelty_check"),
            (json_id, "新颖性验证数据", "novelty_check_data"),
        ):
            job_store.add_event(
                orch_job_id,
                {"type": "artifact", "artifact_type": kind, "artifact_id": rel, "path": rel, "label": label},
            )
        self._emit_stage(job_store, orch_job_id, step, "artifact_write", "done")
        return [md_id, json_id]

    def _write_idea_report_artifacts(self, service, job_store, orch_job_id, workflow_id, user_id, step, sdef, full, input_ctx) -> list[str]:
        self._emit_stage(job_store, orch_job_id, step, "report_synthesis", "done")
        self._emit_stage(job_store, orch_job_id, step, "artifact_write", "running")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"research_agent/workflow_ideas/{workflow_id}/{sdef.artifact_stem}_{ts}"
        md_rel = f"{base}.md"
        json_rel = f"{base}.json"
        md_id = f"{user_data_rel_prefix(user_id)}/{md_rel}"
        json_id = f"{user_data_rel_prefix(user_id)}/{json_rel}"
        data = _idea_report_json(workflow_id, input_ctx, full)
        try:
            data_dir = user_workspace_root(user_id)
            (data_dir / md_rel).parent.mkdir(parents=True, exist_ok=True)
            (data_dir / md_rel).write_text(full, encoding="utf-8")
            (data_dir / json_rel).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _mirror_to_service_data_dir(service, md_id, full)
            _mirror_to_service_data_dir(service, json_id, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:  # noqa: BLE001 - still emit ids for inline visibility
            pass
        for rel, label, kind in (
            (md_id, "Idea 报告", "idea_report"),
            (json_id, "Idea 报告数据", "idea_report_data"),
        ):
            job_store.add_event(
                orch_job_id,
                {"type": "artifact", "artifact_type": kind, "artifact_id": rel, "path": rel, "label": label},
            )
        self._emit_stage(job_store, orch_job_id, step, "artifact_write", "done")
        return [md_id, json_id]

    def _fail(self, store, job_store, orch_job_id, workflow_id, step, err) -> list[str]:
        store.update_step(workflow_id, step["step_index"], status="failed", ended_at=now(), error=err)
        self._emit_step(job_store, orch_job_id, step, "failed", error=err)
        raise StepFailed(err)

    @staticmethod
    def _emit_step(job_store, orch_job_id, step, status, *, error=None) -> None:
        event = {
            "type": "step",
            "step_index": step["step_index"],
            "step_key": step["step_key"],
            "label": step.get("label"),
            "status": status,
        }
        if error:
            event["error"] = error
        job_store.add_event(orch_job_id, event)

    @staticmethod
    def _emit_stage(job_store, orch_job_id, step, stage, status, label=None) -> None:
        key = f"agent-{step.get('step_index')}-{stage}"
        job_store.add_event(orch_job_id, {"type": "stage", "stage": key, "status": status, "label": label or _AGENT_STAGE_LABELS.get(stage, stage)})

    def _mark_all_stages(self, job_store, orch_job_id, step, status) -> None:
        for item in (step.get("params") or {}).get("stages") or []:
            stage = item.get("stage") if isinstance(item, dict) else item[0]
            if stage:
                self._emit_stage(job_store, orch_job_id, step, stage, status)


def _latest_corpus_run_id(engine_ref: dict[str, Any]) -> str | None:
    """The run_id of the most recent corpus step (highest run_id_<n> key)."""
    best, best_i = None, -1
    for key, value in engine_ref.items():
        if key.startswith("run_id_"):
            try:
                idx = int(key[len("run_id_"):])
            except ValueError:
                continue
            if idx > best_i:
                best_i, best = idx, value
    return best or engine_ref.get("underlying_run_id")


def _load_evidence(service, run_id: str | None) -> tuple[str, int]:
    """Return (grounding_block, evidence_count) from the prior corpus run's pack.

    evidence_count is the REAL number of packed evidence items (not the rendered,
    truncated subset) — the zero-evidence guard keys on it."""
    if not run_id:
        return ("", 0)
    try:
        show = service.run_show(run_id)
    except Exception:  # noqa: BLE001
        return ("", 0)
    manifest = show.get("manifest") or {}
    pack_rel = (manifest.get("artifact_paths") or {}).get("pack")
    items: list[dict[str, Any]] = []
    count = 0
    if pack_rel:
        try:
            data_dir = Path(service.paths.data_dir)
            pack = json.loads((data_dir / pack_rel).read_text(encoding="utf-8"))
            evidence = list(pack.get("evidence") or [])
            count = len(evidence) or int((pack.get("stats") or {}).get("packed_evidence_count") or 0)
            items = evidence[:_EVIDENCE_LIMIT]
        except Exception:  # noqa: BLE001 - fall back to the summary
            items, count = [], 0
    if items:
        return (_render_evidence(items), count)
    return (_summary_block(show), count)


def _render_evidence(items: list[dict[str, Any]]) -> str:
    lines = ["本地语料证据（verified_local，引用时用真实 evidence_id/source_path）："]
    for it in items:
        eid = it.get("evidence_id") or "?"
        title = it.get("title") or it.get("doi") or ""
        section = it.get("section") or it.get("kind") or ""
        src = it.get("source_path") or ""
        text = (it.get("text") or it.get("snippet") or "").strip().replace("\n", " ")
        if len(text) > _TEXT_CLIP:
            text = text[:_TEXT_CLIP] + "…"
        lines.append(f"- [{eid}] {title} · {section} · {src}\n  {text}")
    return "\n".join(lines)


def _summary_block(show: dict[str, Any]) -> str:
    summary = show.get("summary") or {}
    manifest = show.get("manifest") or {}
    assessment = summary.get("evidence_assessment") or {}
    q = manifest.get("question") or summary.get("question") or ""
    status = assessment.get("status") or ""
    if not (q or status):
        return ""
    return (
        "上一步文献调研摘要（本地语料）：\n"
        f"- 检索问题：{q}\n"
        f"- 证据充分性：{status or '未知'}\n"
        "（pack 证据明细不可用，请基于该摘要谨慎生成，并将外部论文标 [UNVERIFIED]。）"
    )


def _load_prior_artifacts(service, wf: dict[str, Any], step: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for prior in wf.get("steps") or []:
        if prior.get("step_index", 9999) >= step.get("step_index", 0):
            continue
        for aid in prior.get("artifact_ids") or []:
            if not isinstance(aid, str) or not (aid.endswith(".md") or aid.endswith(".json")):
                continue
            try:
                text = _artifact_path(service, aid).read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            key = prior.get("step_key") or f"step-{prior.get('step_index')}"
            if aid.endswith(".json"):
                out[f"{key}:json"] = text
                out[f"{key}:json_artifact"] = aid
            else:
                out[key] = f"[artifact:{aid}]\n{text}"
                out[f"{key}:artifact"] = aid
    return out


def _artifact_path(service, artifact_id: str) -> Path:
    if artifact_id.startswith("users/"):
        _prefix, user_id, rel = artifact_id.split("/", 2)
        return user_workspace_root(user_id) / rel
    return Path(service.paths.data_dir) / artifact_id


def _mirror_to_service_data_dir(service, artifact_id: str, content: str) -> None:
    if not artifact_id.startswith("users/"):
        return
    compat_path = Path(service.paths.data_dir) / artifact_id
    compat_path.parent.mkdir(parents=True, exist_ok=True)
    compat_path.write_text(content, encoding="utf-8")


def _missing_prior_message(step_key: str, missing: list[str]) -> str:
    if step_key == "novelty-check" and "idea-creator" in missing:
        return "缺少候选 idea 产物，无法进行新颖性验证"
    if step_key == "idea-report":
        if "idea-creator" in missing:
            return "缺少候选 idea 产物，无法生成 Idea 报告"
        if "novelty-check:json" in missing:
            return "缺少新颖性验证数据，无法生成 Idea 报告"
        if "novelty-check" in missing:
            return "缺少新颖性验证报告，无法生成 Idea 报告"
    return f"缺少前序产物：{', '.join(missing)}"


def _extract_ideas(text: str) -> list[str]:
    chunks = re.split(r"\n(?=###\s+Idea\s+\d+[:：])", text or "")
    ideas = [c.strip() for c in chunks if re.search(r"^###\s+Idea\s+\d+", c.strip(), re.M)]
    if ideas:
        return ideas[:12]
    headings = re.findall(r"(?:^|\n)(?:#{2,4}\s*)?(Idea\s+\d+[:：].{0,160})", text or "")
    return headings[:12] or [(text or "").strip()[:1200]]


def _novelty_json(workflow_id: str, ctx, markdown: str) -> dict[str, Any]:
    ideas = ctx.external_context.get("ideas") or _extract_ideas(ctx.prior_artifacts.get("idea-creator", ""))
    candidates = ctx.external_context.get("external_candidates") or []
    source_status = ctx.external_context.get("source_status") or {}
    verification_summary = source_status.get("verification_summary") or {
        "verdict": "WARN",
        "hallucination_rate": 0.0,
        "pending_rate": 0.0,
        "warnings": ["verification_summary_unavailable"],
    }
    query_quality = source_status.get("query_quality") or {}
    local = _local_overlaps_from_block(ctx.evidence_block)
    out_ideas = []
    for idx, idea in enumerate(ideas[:12], 1):
        title = _idea_title(idea, idx)
        claims = _claims_from_idea(idea)
        world = "SEARCH_INCOMPLETE" if _search_incomplete(source_status) else "UNVERIFIED"
        if any(c.get("verification") == "verified" for c in candidates):
            world = "WORLD_MEDIUM"
        out_ideas.append(
            {
                "idea_id": f"idea_{idx}",
                "title": title,
                "claims": claims,
                "local_novelty": "LOCAL_MEDIUM" if local else "INSUFFICIENT_LOCAL_EVIDENCE",
                "world_novelty": world,
                "score": 5 if world == "SEARCH_INCOMPLETE" else 6,
                "recommendation": "PROCEED_WITH_CAUTION" if world != "WORLD_LOW" else "DEPRIORITIZE",
                "local_overlaps": local,
                "external_prior_work": candidates[:6],
                "risks": ["外部查新不完整，需人工复核"] if world == "SEARCH_INCOMPLETE" else ["closest prior work 可能削弱新颖性"],
                "positioning": "将本地证据作为动机，把世界新颖性结论限制在已验证外部来源范围内。",
            }
        )
    return {
        "workflow_id": workflow_id,
        "topic": ctx.topic,
        "ideas": out_ideas,
        "source_status": source_status,
        "verification_summary": verification_summary,
        "query_quality": query_quality,
        "markdown_preview": markdown[:2000],
    }


def _idea_report_json(workflow_id: str, ctx, markdown: str) -> dict[str, Any]:
    novelty_data = _loads_json(ctx.prior_artifacts.get("novelty-check:json") or "{}")
    novelty_ideas = list(novelty_data.get("ideas") or [])
    ideas = []
    for idx, raw in enumerate(novelty_ideas, 1):
        recommendation = raw.get("recommendation") or "PROCEED_WITH_CAUTION"
        risks = list(raw.get("risks") or [])
        if raw.get("world_novelty") == "SEARCH_INCOMPLETE" and "外部查新不完整，需人工复核" not in risks:
            risks.append("外部查新不完整，需人工复核")
        ideas.append(
            {
                "idea_id": raw.get("idea_id") or f"idea_{idx}",
                "title": raw.get("title") or f"Idea {idx}",
                "core_hypothesis": _first_claim(raw) or raw.get("title") or f"Idea {idx}",
                "supporting_evidence": raw.get("local_overlaps") or [],
                "local_novelty": raw.get("local_novelty") or "UNKNOWN",
                "world_novelty": raw.get("world_novelty") or "UNVERIFIED",
                "closest_prior_work": raw.get("external_prior_work") or [],
                "score": raw.get("score") or 0,
                "recommendation": recommendation,
                "risks": risks,
                "positioning": raw.get("positioning") or "",
                "minimal_viable_experiment": _minimal_experiment_from_candidates(ctx.prior_artifacts.get("idea-creator", ""), idx),
                "next_actions": _next_actions(raw),
            }
        )
    recommendations = [item["recommendation"] for item in ideas]
    world_values = [item["world_novelty"] for item in ideas]
    warnings = []
    limitations = []
    if any(value == "SEARCH_INCOMPLETE" for value in world_values):
        warnings.append("部分 idea 的 world novelty 为 SEARCH_INCOMPLETE。")
        limitations.append("外部学术源检索不完整，报告结论需人工复核。")
    if (novelty_data.get("verification_summary") or {}).get("warnings"):
        warnings.extend(novelty_data["verification_summary"]["warnings"])
    return {
        "workflow_id": workflow_id,
        "topic": ctx.topic,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "idea_candidates_artifact": ctx.prior_artifacts.get("idea-creator:artifact") or "",
            "novelty_check_artifact": ctx.prior_artifacts.get("novelty-check:artifact") or "",
            "novelty_check_data_artifact": ctx.prior_artifacts.get("novelty-check:json_artifact") or "",
        },
        "summary": {
            "total_ideas": len(ideas),
            "recommended_count": sum(1 for rec in recommendations if rec == "PROCEED"),
            "caution_count": sum(1 for rec in recommendations if rec == "PROCEED_WITH_CAUTION"),
            "abandon_count": sum(1 for rec in recommendations if rec in {"ABANDON", "DEPRIORITIZE"}),
            "overall_readiness": _overall_readiness(ideas),
        },
        "ideas": ideas,
        "warnings": _uniq_text(warnings),
        "limitations": _uniq_text(limitations),
        "markdown_preview": markdown[:2000],
    }


def _loads_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _first_claim(raw: dict[str, Any]) -> str:
    claims = raw.get("claims") or []
    return str(claims[0]) if claims else ""


def _minimal_experiment_from_candidates(candidate_md: str, idx: int) -> str:
    ideas = _extract_ideas(candidate_md)
    if 0 <= idx - 1 < len(ideas):
        match = re.search(r"最小可行实验[：:]\s*(.+)", ideas[idx - 1])
        if match:
            return match.group(1).strip()[:500]
    return "基于报告建议设计最小可行实验，并在 experiment-bridge 中细化。"


def _next_actions(raw: dict[str, Any]) -> list[str]:
    actions = ["人工复核 closest prior work", "细化最小可行实验", "进入 experiment-bridge 生成实验计划"]
    if raw.get("world_novelty") == "SEARCH_INCOMPLETE":
        actions.insert(0, "补充外部学术检索以完成 world novelty 验证")
    return actions


def _overall_readiness(ideas: list[dict[str, Any]]) -> str:
    if any(item.get("world_novelty") == "SEARCH_INCOMPLETE" for item in ideas):
        return "NEEDS_MORE_SEARCH"
    if any(item.get("recommendation") == "PROCEED" for item in ideas):
        return "READY_FOR_EXPERIMENT_BRIDGE"
    return "NEEDS_MANUAL_REVIEW"


def _uniq_text(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = str(item)
        if text and text not in out:
            out.append(text)
    return out


def _local_overlaps_from_block(block: str) -> list[dict[str, Any]]:
    overlaps = []
    for line in (block or "").splitlines():
        m = re.match(r"- \[([^\]]+)\] (.*?) · (.*?) · (.*)", line)
        if not m:
            continue
        overlaps.append(
            {
                "evidence_id": m.group(1),
                "paper": m.group(2).strip(),
                "source_path": m.group(4).strip(),
                "overlap": "local evidence is relevant to the idea context",
                "key_difference": "需要通过外部查新和后续评审确认差异。",
            }
        )
    return overlaps[:8]


def _idea_title(text: str, idx: int) -> str:
    m = re.search(r"Idea\s+\d+[:：]\s*(.+)", text or "")
    return (m.group(1).strip() if m else f"Idea {idx}")[:120]


def _claims_from_idea(text: str) -> list[str]:
    lines = [re.sub(r"^[-*]\s*", "", line).strip() for line in (text or "").splitlines()]
    claims = [line for line in lines if any(key in line for key in ("摘要", "核心假设", "最小可行实验", "hypothesis", "experiment"))]
    return claims[:5] or [_idea_title(text, 1)]


def _search_incomplete(status: dict[str, Any]) -> bool:
    return not any(isinstance(v, dict) and v.get("status") == "ok" for k, v in status.items() if k in {"arxiv", "semantic_scholar", "openalex", "exa"})


_AGENT_STAGE_LABELS = {
    "prepare_claims": "抽取核心 claims",
    "local_overlap": "本地语料 overlap",
    "external_query_plan": "规划外部检索",
    "external_search": "外部学术源检索",
    "paper_verification": "候选论文验证",
    "novelty_synthesis": "综合新颖性判断",
    "artifact_write": "写入新颖性产物",
}
