"""Tool registry exposing the existing research service to the LLM agent.

Each tool wraps an already-implemented :class:`LiteratureResearchService` method
(see ``service.py``). Tools never reimplement retrieval logic — they call the
service, persist results into ``session_store`` (so every tool call enters the
audit trail and conversation memory), and return a compact, citation-friendly
payload back to the model.

``answer_mode`` gates which tools are exposed:
    quick → search / paper inspection / evidence expand / pack
    deep  → quick + task_run / run / extract / compare / verify_answer / quality
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from modules.literature_search.agent import tool_errors as te
from modules.literature_search.agent.citations import CitationRegistry, item_to_available_evidence
from modules.literature_search.agent.tool_specs import (
    JOB_REQUIRED,
    ToolSpec,
    get_spec,
    specs_for_mode,
    validate_arguments,
)
from modules.literature_search.job_runner import _artifact_events
from modules.literature_search.service import LiteratureResearchService


# Tool JSON schemas + governance metadata now live in `tool_specs.ToolSpec`
# (the single source of truth). This module is the execution layer over them.

_JOB_POLL_INTERVAL = 0.1  # seconds between job-status polls while block-streaming
_JOB_SUMMARY = {
    "task_run": "运行研究任务",
    "run": "运行可审计研究流程",
    "extract": "抽取指标",
    "compare": "生成对比表",
    "pack": "构建证据包",
}
# Subset of the trace surfaced as a forwardable `tool_trace` event (no raw args).
_TRACE_EVENT_FIELDS = (
    "tool_call_id",
    "tool_name",
    "permission_level",
    "agent_mode",
    "status",
    "error_code",
    "error_message",
    "recovery_hint",
    "result_summary",
    "latency_ms",
    "artifacts_created",
    "jobs_created",
    "state_changed",
)


def now() -> float:
    return time.time()


@dataclass
class ToolResult:
    """Outcome of one tool call."""

    summary: str  # short human label for the step event
    content: Any  # compact payload returned to the LLM
    events: list[dict[str, Any]] = field(default_factory=list)  # platform events to forward
    evidence: list[dict[str, Any]] = field(default_factory=list)  # evidence available for citation


class ToolRegistry:
    def __init__(
        self,
        service: LiteratureResearchService,
        session_store,
        *,
        session_id: str,
        turn_id: str | None,
        answer_mode: str = "quick",
        has_history: bool = False,
        job_runner=None,
        role_tools: frozenset[str] | None = None,
        original_question: str | None = None,
        user_id: str | None = None,
        citation_registry: CitationRegistry | None = None,
    ) -> None:
        self.service = service
        self.session_store = session_store
        self.session_id = session_id
        self.turn_id = turn_id
        self.has_history = has_history
        self.answer_mode = "deep" if answer_mode == "deep" else "quick"
        # Spec-driven gating: expose exactly the tools whose agent_modes include
        # the active mode (admin/destructive tools are in no mode → never auto).
        self.specs = {spec.name: spec for spec in specs_for_mode(self.answer_mode)}
        # Block 6c: a specialist role narrows the mode's tools to its own subset.
        # This is what structurally stops e.g. the retrieval role from doing
        # analysis — the compare/extract/run tools are absent, not just discouraged.
        if role_tools is not None:
            self.specs = {n: s for n, s in self.specs.items() if n in role_tools}
        self.enabled = list(self.specs)
        self._job_runner = job_runner
        self.original_question = original_question or ""
        self.user_id = user_id
        self.citation_registry = citation_registry

    @property
    def job_runner(self):
        # Lazily bind the shared in-process runner (same one the API uses), so
        # long tools run through ONE job path. Tests inject a fake.
        if self._job_runner is None:
            from modules.literature_search.literature_search_shared import job_runner

            self._job_runner = job_runner
        return self._job_runner

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in self.specs.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any], *, tool_call_id: str | None = None) -> ToolResult:
        """The Block 4 execution layer: permission gate → input validation →
        execution (direct w/ timeout+retry, or job runner) → result normalize →
        structured error → tool trace.

        A tool failure NEVER raises into the agent loop; it returns a ToolResult
        whose ``content`` is the structured error (``{"ok": false, "error": …}``)
        so the model can read ``recovery_hint`` and continue.
        """
        arguments = arguments or {}
        started = now()
        t0 = time.monotonic()
        spec = self.specs.get(name)

        # --- permission / mode gate ---
        if spec is None:
            disabled = get_spec(name)
            msg = (
                f"tool '{name}' is not available in {self.answer_mode} mode"
                if disabled is not None
                else f"unknown tool: {name}"
            )
            err = te.make_error(te.PERMISSION_DENIED, msg)
            result = ToolResult(summary=f"工具 {name} 不可用", content=err.as_dict())
            self._record_trace(name, None, arguments, result, started, t0, tool_call_id, error=err)
            return result

        # --- input validation ---
        invalid = validate_arguments(spec.input_schema, arguments)
        if invalid:
            err = te.make_error(te.VALIDATION_ERROR, invalid)
            result = ToolResult(summary=f"{spec.name} 参数不合法", content=err.as_dict())
            self._record_trace(spec.name, spec, arguments, result, started, t0, tool_call_id, error=err)
            return result

        # --- execution (direct w/ timeout+retry, or job) ---
        try:
            if spec.execution_mode == JOB_REQUIRED:
                result = await self._execute_job(spec, arguments)
            else:
                result = await self._execute_direct(spec, arguments)
            self._bind_citation_aliases(result)
            self._record_trace(spec.name, spec, arguments, result, started, t0, tool_call_id)
            return result
        except te.ToolError as err:  # raised by job/timeout paths
            result = ToolResult(summary=f"{spec.name} 执行失败", content=err.as_dict())
            self._record_trace(spec.name, spec, arguments, result, started, t0, tool_call_id, error=err)
            return result
        except Exception as exc:  # noqa: BLE001 - normalize, never crash the loop
            err = te.classify_exception(exc)
            result = ToolResult(summary=f"{spec.name} 执行失败", content=err.as_dict())
            self._record_trace(spec.name, spec, arguments, result, started, t0, tool_call_id, error=err)
            return result

    async def _execute_direct(self, spec: ToolSpec, arguments: dict[str, Any]) -> ToolResult:
        handler = getattr(self, f"_tool_{spec.name}")
        attempts = max(0, spec.max_retries) + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(handler(arguments), timeout=spec.timeout_seconds)
            except asyncio.TimeoutError:
                last_exc = te.make_error(te.TIMEOUT, f"{spec.name} timed out after {spec.timeout_seconds:.0f}s")
            except Exception as exc:  # noqa: BLE001
                err = te.classify_exception(exc)
                if not err.retryable or attempt == attempts - 1:
                    raise
                last_exc = err
        # Only retryable errors fall through here.
        raise last_exc  # type: ignore[misc]

    async def _execute_job(self, spec: ToolSpec, arguments: dict[str, Any]) -> ToolResult:
        """Submit to the shared job runner and block-stream until terminal.

        The ReAct loop semantics are unchanged (the tool still returns a result
        the model reasons over); the job just runs through the SAME runner the
        API uses, emitting stage/artifact/progress events the UI can follow, and
        is governed by the spec timeout.
        """
        runner = self.job_runner
        payload = {**arguments, "session_id": self.session_id, "turn_id": self.turn_id, "user_id": self.user_id}
        job = await _thread(runner.submit, spec.name, payload)
        job_id = job["job_id"]
        events: list[dict[str, Any]] = [
            {"type": "job", "job_id": job_id, "job_type": spec.name, "status": "running", "label": spec.description}
        ]
        artifacts: list[dict[str, Any]] = []
        cursor = 0
        deadline = time.monotonic() + spec.timeout_seconds
        terminal = {"completed", "failed", "interrupted"}
        status = "running"
        while True:
            new_events = await _thread(runner.store.events, job_id, after=cursor)
            cursor += len(new_events)
            for ev in new_events:
                etype = ev.get("type")
                if etype in {"stage", "progress"}:
                    events.append({**ev, "job_id": job_id})
                elif etype == "artifact":
                    artifacts.append(ev)
                    events.append(ev)
            status = (await _thread(runner.store.get, job_id)).get("status") or "running"
            if status in terminal:
                break
            if time.monotonic() > deadline:
                raise te.make_error(
                    te.TIMEOUT,
                    f"{spec.name} job {job_id} exceeded {spec.timeout_seconds:.0f}s (still running in background)",
                )
            await asyncio.sleep(_JOB_POLL_INTERVAL)

        job = await _thread(runner.store.get, job_id)
        if status != "completed":
            raise te.make_error(
                te.JOB_FAILED,
                te.redact(job.get("error") or f"job {job_id} {status}"),
            )
        data = job.get("result") or {}
        # Artifacts are recorded ONCE, by the JobRunner (against the session) —
        # the tool only forwards the events, it does not re-record them.
        result = ToolResult(summary=f"{_JOB_SUMMARY.get(spec.name, spec.name)}", content=data, events=events)
        if spec.name == "pack":
            result.evidence = _pack_evidence(data)
        result._artifact_ids = [a.get("artifact_id") for a in artifacts if a.get("artifact_id")]  # type: ignore[attr-defined]
        result._job_ids = [job_id]  # type: ignore[attr-defined]
        return result

    def _bind_citation_aliases(self, result: ToolResult) -> None:
        if not self.citation_registry or not result.evidence:
            return
        old_to_alias: dict[str, str] = {}
        registered_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for evidence in result.evidence:
            manifest_item = self.citation_registry.register_evidence(evidence)
            if manifest_item is None:
                continue
            alias = str(manifest_item["alias"])
            source_id = evidence.get("evidence_id")
            if source_id:
                old_to_alias[str(source_id)] = alias
            if alias not in seen_aliases:
                seen_aliases.add(alias)
                registered_aliases.append(alias)
        result.evidence = [
            item_to_available_evidence(self.citation_registry.current_manifest[alias])
            for alias in registered_aliases
        ]
        result.content = _alias_evidence_ids(result.content, old_to_alias)

    def _record_trace(
        self,
        name: str,
        spec: ToolSpec | None,
        arguments: dict[str, Any],
        result: ToolResult,
        started: float,
        t0: float,
        tool_call_id: str | None,
        *,
        error: te.ToolError | None = None,
    ) -> None:
        """Persist a tool-call trace and attach a forwardable `tool_trace` event.

        References (not copies) the artifacts/jobs the tool already recorded.
        Arguments are redacted before storage.
        """
        artifacts = getattr(result, "_artifact_ids", None) or [
            ev.get("artifact_id") for ev in result.events if ev.get("type") == "artifact" and ev.get("artifact_id")
        ]
        jobs = getattr(result, "_job_ids", None) or [
            ev.get("job_id") for ev in result.events if ev.get("type") == "job" and ev.get("job_id")
        ]
        trace = {
            "tool_call_id": tool_call_id or f"tc_{int(t0 * 1000)}",
            "tool_name": name,
            "schema_version": spec.schema_version if spec else None,
            "permission_level": spec.permission_level if spec else None,
            "agent_mode": self.answer_mode,
            "arguments": te.redact(arguments),
            "status": "error" if error else "ok",
            "error_code": error.code if error else None,
            "error_message": error.message if error else None,
            "recovery_hint": (error.recovery_hint or "") if error else None,
            "result_summary": result.summary,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "artifacts_created": [a for a in artifacts if a],
            "jobs_created": [j for j in jobs if j],
            "state_changed": bool(spec and spec.permission_level != "read_only" and not error),
            "started_at": started,
            "completed_at": now(),
        }
        try:
            self.session_store.record_tool_trace(trace, session_id=self.session_id, turn_id=self.turn_id, user_id=self.user_id)
        except Exception:  # noqa: BLE001 - tracing must never break a tool call
            pass
        result.events.append({"type": "tool_trace", **{k: trace[k] for k in _TRACE_EVENT_FIELDS}})

    # --- individual tools -------------------------------------------------------

    async def _tool_search(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query") or ""
        options = {k: v for k, v in args.items() if k != "query" and v is not None}
        options.setdefault("limit", 8)
        if self.original_question:
            options["_original_user_query"] = self.original_question
        # Block 2: acquire an auditable evidence packet (intent -> rewrite ->
        # search + recovery -> normalized candidates -> coverage) instead of a
        # bare result list. The raw `results` shape is preserved inside the packet.
        packet = await _thread(
            self.service.acquire_evidence, query, has_history=self.has_history, **options
        )
        plan = packet.get("query_plan") or {}
        coverage = packet.get("coverage") or {}
        breadth = packet.get("breadth") or {}
        candidates = packet.get("evidence_candidates") or []
        # Block 2 §8 three tiers:
        #  - selection pool (all candidates) → displayed cards + persisted record
        #    + follow-up reuse (broad, for browsing/breadth).
        #  - llm-context subset (in_llm_context) → compact payload + citation
        #    boundary (bounded, so context never balloons with the pool).
        selection_ids = {c.get("evidence_id") for c in candidates if c.get("evidence_id")}
        context_ids = {c.get("evidence_id") for c in candidates if c.get("in_llm_context") and c.get("evidence_id")}
        papers_all = self.service.to_chat_papers({"results": packet.get("results") or []})
        cards = _restrict_to_selected(papers_all, selection_ids)
        context_papers = _restrict_to_selected(papers_all, context_ids)
        search_payload = {
            "query": query,
            "query_plan": plan,
            "filters": packet.get("filters") or {},
            "coverage": coverage,
            "breadth": breadth,
            "fallback_reason": packet.get("fallback_reason"),
            "results": cards,
        }
        self.session_store.record_search_result(self.session_id, self.turn_id, search_payload, user_id=self.user_id)
        evidence = _collect_evidence(context_papers)
        events = [
            {
                "type": "search_meta",
                "query_plan": plan,
                "retrieval_used": packet.get("retrieval_used"),
                "vector_unavailable_reason": (plan.get("underlying") or {}).get("vector_unavailable_reason") or "",
            },
            {"type": "papers", "papers": cards},
            {
                "type": "coverage",
                "status": coverage.get("status"),
                "distinct_paper_count": coverage.get("distinct_paper_count"),
                "evidence_count": coverage.get("evidence_count"),
                "breadth_limited": breadth.get("breadth_limited"),
                "deep_research_suggested": breadth.get("deep_research_suggested"),
                "breadth": breadth,
                "notes": coverage.get("coverage_notes") or [],
                "short_message": _coverage_short_message(coverage, breadth),
            },
        ]
        status = coverage.get("status") or "?"
        ctx_n = breadth.get("llm_context_evidence_count") or len(context_ids)
        summary = (
            f"检索本地文献库「{query}」，候选 {len(cards)} 篇，"
            f"用于作答 {ctx_n} 条证据，覆盖 {status}"
        )
        return ToolResult(
            summary=summary,
            content=_compact_search(query, context_papers, packet, answer_mode=self.answer_mode),
            events=events,
            evidence=evidence,
        )

    async def _tool_paper_sections(self, args: dict[str, Any]) -> ToolResult:
        data = await _thread(self.service.paper_sections, **args)
        return ToolResult(summary="读取论文章节结构", content=data)

    async def _tool_paper_chunks(self, args: dict[str, Any]) -> ToolResult:
        # L1 (index-native grounding): serve full-text chunks straight from the
        # `documents` table so each carries its REAL citable evidence_id
        # (E{document_id}). Registering them means the model can cite a specific
        # full-text detail it read instead of fabricating an id for it.
        lookup = {k: args.get(k) for k in ("doi", "paper_id", "article_id", "section") if args.get(k) is not None}
        docs = await _thread(self.service.paper_text_documents, limit=30, **lookup)
        evidence = [
            {
                "source_namespace": "research_index",
                "evidence_id": d.get("evidence_id"),
                "paper_id": d.get("paper_id"),
                "doi": d.get("doi"),
                "title": d.get("title"),
                "year": d.get("year"),
                "journal": d.get("journal"),
                "section": d.get("section"),
                "section_id": d.get("section_id"),
                "chunk_index": d.get("chunk_index"),
                "kind": d.get("kind"),
                "snippet": d.get("snippet"),
                "canonical_text": d.get("text"),
                "source_path": d.get("source_path"),
                "confidence": d.get("confidence"),
            }
            for d in docs
            if d.get("evidence_id")
        ]
        content = {
            "chunks": [
                {"evidence_id": d.get("evidence_id"), "section": d.get("section"), "snippet": _truncate(d.get("snippet"), 400)}
                for d in docs
            ],
            "note": "These are full-text chunks with numeric citation aliases — cite specific full-text details (numbers, methods) with these aliases, e.g. [1]; never invent an alias.",
        }
        return ToolResult(summary=f"读取论文全文块（{len(docs)} 块，可引用）", content=content, evidence=evidence)

    async def _tool_evidence_expand(self, args: dict[str, Any]) -> ToolResult:
        data = await _thread(self.service.evidence_expand, **args)
        return ToolResult(summary="展开表格/图片证据", content=data)

    async def _tool_pack(self, args: dict[str, Any]) -> ToolResult:
        query = args.pop("query", "")
        data = await _thread(self.service.pack, query, **args)
        result = self._artifact_result("构建证据包", data, link_type="pack")
        # `pack` re-numbers its evidence locally (E1..En) — a DIFFERENT scheme from
        # search's E{document_id}. The model is shown these ids and will cite them,
        # so they must enter the citation-audit available set just like search does,
        # otherwise every pack-based citation is flagged "未找到证据".
        result.evidence = _pack_evidence(data)
        return result

    # task_run / run / extract / compare are JOB_REQUIRED — they run through
    # `_execute_job` (the shared job runner), so they have no direct `_tool_*`
    # handler here. The JobRunner records their artifacts against the session.

    async def _tool_verify_answer(self, args: dict[str, Any]) -> ToolResult:
        data = await _thread(self.service.verify_answer, **args)
        return ToolResult(summary="验证答案证据支持", content=data)

    async def _tool_quality(self, args: dict[str, Any]) -> ToolResult:
        data = await _thread(self.service.quality, **args)
        return ToolResult(summary="质量审计", content=data)

    # --- helpers ----------------------------------------------------------------

    def _artifact_result(self, summary: str, data: dict, *, link_type: str) -> ToolResult:
        events: list[dict[str, Any]] = []
        for artifact in _artifact_events(data):
            self.session_store.record_artifact(
                artifact,
                session_id=self.session_id,
                turn_id=self.turn_id,
                link_type=artifact.get("artifact_type") or link_type,
                user_id=self.user_id,
            )
            events.append(artifact)
        return ToolResult(summary=summary, content=data, events=events)


async def _thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def _restrict_to_selected(papers: list[dict], selected_ids: set) -> list[dict[str, Any]]:
    """Keep only selector-approved evidence; drop papers left with none.

    This makes the selector's `evidence_candidates` the single evidence boundary
    across the LLM context, citation audit, UI cards, and persisted record.
    """
    if not selected_ids:
        return []
    restricted: list[dict[str, Any]] = []
    for paper in papers:
        kept = [e for e in (paper.get("evidence") or []) if e.get("evidence_id") in selected_ids]
        if kept:
            restricted.append({**paper, "evidence": kept})
    return restricted


def _pack_evidence(data: dict) -> list[dict[str, Any]]:
    """Normalize a pack's evidence rows into citable evidence for the audit set.

    Pack ids are local (E1..En) and may coincide numerically with search's
    E{document_id}. Their explicit namespace keeps those physical ids distinct.
    """
    evidence: list[dict[str, Any]] = []
    for item in data.get("evidence") or []:
        if not item.get("evidence_id"):
            continue
        evidence.append(
            {
                "source_namespace": "evidence_pack",
                "source_type": "evidence_pack",
                "evidence_id": item.get("evidence_id"),
                "paper_id": item.get("paper_id"),
                "doi": item.get("doi"),
                "title": item.get("title"),
                "year": item.get("year"),
                "journal": item.get("journal"),
                "section": item.get("section"),
                "section_id": item.get("section_id"),
                "chunk_index": item.get("chunk_index"),
                "source_path": item.get("source_path"),
                "snippet": item.get("snippet") or item.get("text"),
                "canonical_text": item.get("text"),
                "confidence": item.get("confidence"),
            }
        )
    return evidence


def _collect_evidence(papers: list[dict]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for paper in papers:
        for item in paper.get("evidence") or []:
            evidence.append(
                {
                    "source_namespace": "research_index",
                    "evidence_id": item.get("evidence_id"),
                    "paper_id": item.get("paper_id") or paper.get("paper_id"),
                    "doi": item.get("doi") or paper.get("doi"),
                    "title": item.get("title") or paper.get("title"),
                    # Paper-level metadata so grounding can verify year/journal
                    # claims (they live in the index, not in the chunk snippet).
                    "year": paper.get("year"),
                    "journal": paper.get("venue") or paper.get("journal"),
                    "section": item.get("section"),
                    "section_id": item.get("section_id"),
                    "chunk_index": item.get("chunk_index"),
                    "source_path": item.get("source_path"),
                    "snippet": item.get("snippet") or item.get("text"),
                    "canonical_text": item.get("text"),
                    "confidence": item.get("confidence"),
                }
            )
    return [e for e in evidence if e.get("evidence_id")]


def _compact_search(query: str, papers: list[dict], packet: dict, *, max_evidence: int = 4, answer_mode: str = "quick") -> dict[str, Any]:
    """Trim packet output to a citation-friendly, token-bounded shape for the LLM."""
    plan = packet.get("query_plan") or {}
    coverage = packet.get("coverage") or {}
    breadth = packet.get("breadth") or {}
    underlying = plan.get("underlying") or {}
    compact_papers = []
    for paper in papers:
        evidence = []
        for item in (paper.get("evidence") or [])[:max_evidence]:
            evidence.append(
                {
                    "evidence_id": item.get("evidence_id"),
                    "snippet": _truncate(item.get("snippet") or item.get("text"), 400),
                    "section": item.get("section"),
                    "source_path": item.get("source_path"),
                    "confidence": item.get("confidence"),
                }
            )
        compact_papers.append(
            {
                "title": paper.get("title"),
                "paper_id": paper.get("paper_id"),
                "doi": paper.get("doi"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "evidence": evidence,
            }
        )
    return {
        "query": query,
        "query_intent": (packet.get("query_intent") or {}).get("type"),
        "retrieval_used": packet.get("retrieval_used") or underlying.get("retrieval_used"),
        "vector_unavailable_reason": underlying.get("vector_unavailable_reason") or "",
        "coverage": {
            "status": coverage.get("status"),
            "distinct_paper_count": coverage.get("distinct_paper_count"),
            "evidence_count": coverage.get("evidence_count"),
            "missing_aspects": coverage.get("missing_aspects") or [],
            "notes": coverage.get("coverage_notes") or [],
        },
        "breadth": {
            "candidate_paper_count": breadth.get("candidate_paper_count"),
            "estimated_total_matches": breadth.get("estimated_total_matches"),
            "estimate_is_lower_bound": breadth.get("estimate_is_lower_bound"),
            "llm_context_evidence_count": breadth.get("llm_context_evidence_count"),
            "clusters_covered": breadth.get("clusters_covered") or [],
            "missing_clusters": breadth.get("missing_clusters") or [],
            "breadth_limited": breadth.get("breadth_limited"),
            "deep_research_suggested": breadth.get("deep_research_suggested"),
        },
        "papers": compact_papers,
        "note": (
            "Cite claims with the numeric evidence_id aliases above, e.g. [1]. "
            "Use `coverage.status` to decide: sufficient -> answer; partial -> "
            "answer supported parts and list gaps; weak -> retrieve more or state "
            "insufficiency; none -> do NOT assert factual conclusions. "
            "The evidence above is a bounded context subset; `breadth` describes how "
            "many candidates exist beyond it. If breadth.breadth_limited is true, "
            "present the answer as a representative overview, not exhaustive. "
            + _breadth_action_note(answer_mode)
        ),
    }


def _alias_evidence_ids(value: Any, old_to_alias: dict[str, str]) -> Any:
    if not old_to_alias:
        return value
    if isinstance(value, list):
        return [_alias_evidence_ids(item, old_to_alias) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _alias_evidence_ids(item, old_to_alias) for key, item in value.items()}
    evidence_id = out.get("evidence_id")
    if evidence_id is not None and str(evidence_id) in old_to_alias:
        out["original_evidence_id"] = evidence_id
        out["evidence_id"] = old_to_alias[str(evidence_id)]
    return out


def _breadth_action_note(answer_mode: str) -> str:
    """What to do when breadth.deep_research_suggested is true — mode-aware.

    In deep mode the user is ALREADY running deep research, so telling them to
    "start a deep research / report flow" is contradictory (the reported bug).
    Instead, instruct the model to broaden in-place or label the overview.
    """
    if answer_mode == "deep":
        return (
            "If breadth.deep_research_suggested is true, you are ALREADY in deep "
            "research mode: broaden coverage yourself with more search calls or the "
            "pack/extract/compare tools, or clearly label the result a representative "
            "overview. Do NOT tell the user to start a deep research / report flow."
        )
    return (
        "If breadth.deep_research_suggested is true, recommend switching to deep "
        "research for comprehensive coverage."
    )


def _coverage_short_message(coverage: dict[str, Any], breadth: dict[str, Any] | None = None) -> str:
    """Product-facing one-liner (no internal plan/score detail)."""
    status = coverage.get("status")
    base = {
        "sufficient": "证据较充分",
        "partial": "证据可部分支持",
        "weak": "证据偏少",
        "none": "未找到可用证据",
    }.get(status, "")
    if breadth and breadth.get("breadth_limited"):
        base = (base + "（代表性概览）") if base else "代表性概览"
    return base


def _truncate(text: str | None, limit: int) -> str | None:
    if not text:
        return text
    return text if len(text) <= limit else text[:limit] + "…"
