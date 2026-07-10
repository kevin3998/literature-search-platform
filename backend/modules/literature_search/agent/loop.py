"""ReAct-style agent loop driving the research tools with an LLM.

The loop turns a chat message into an evidence-grounded answer:

    LLM → tool_calls → execute tools → feed results back → repeat → final answer

It yields platform events compatible with the existing chat protocol
(``step`` / ``search_meta`` / ``papers`` / ``token``) so the frontend needs no
new rendering for the agent's process, plus one new ``citation`` event carrying
the per-turn evidence-to-claim audit.

The system prompt is derived from the research agent's own ``agent.md`` (its
"Answer contract" and "Citation format" were written for exactly this kind of
tool-using agent); a compact form of the session memory context is injected so
follow-up questions can reuse prior evidence instead of blindly re-searching.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncIterator

from core.llm.client import LLMClient
from modules.literature_search.failure_messages import failure_message
from modules.literature_search.agent import grounding as grounding_mod
from modules.literature_search.agent.citations import CitationRegistry
from modules.literature_search.agent import orchestration as orch
from modules.literature_search.agent import tool_errors as te
from modules.literature_search.agent.tools import ToolRegistry

# Accept BOTH half-width [1] and full-width 【1】 brackets: Chinese-output models
# routinely emit 【1】, which would otherwise read as "no citation at all"
# and trip a false "had evidence but cited nothing" warning.
_CITATION_RE = re.compile(r"[\[【]([0-9]+)[\]】]")

_FORCE_ANSWER = (
    "现在不要再调用任何工具。基于以上对话中工具已经返回的证据，直接写出最终中文回答："
    "用 [1] 这种数字引用标注每一处来自证据的结论（只能使用前面工具真实返回过的数字 evidence_id alias），"
    "并在证据不足时明确说明缺口。不要复述你的搜索过程、尝试过程、工具调用计划、工具预算、"
    "pack/paper_chunks 是否成功或失败。"
)

_PROCESS_NARRATION_SENTENCE_RE = re.compile(
    r"^\s*(?:"
    r"(?:I(?:'ll| will| am going to)\s+(?:search|look|check|try|query|retrieve)[^.?!。！？]*(?:[.?!。！？]\s*)+)"
    r"|(?:I\s+already\s+have\s+sufficient\s+evidence[^.?!。！？]*(?:[.?!。！？]\s*)+)"
    r"|(?:Let me\s+(?:try|search|look|check|query|retrieve)[^.?!。！？]*(?:[.?!。！？]\s*)+)"
    r"|(?:Let me\s+(?:compile|summarize|synthesi[sz]e)[^.?!。！？]*(?:[.?!。！？]\s*)+)"
    r"|(?:非常好[,，]?\s*)?(?:现在)?我(?:已经)?(?:获得|收集|拿到)了[^。！？.!?]*(?:充分|足够|丰富)?[^。！？.!?]*证据[^。！？.!?]*(?:[。！？.!?]\s*)+"
    r"|(?:(?:好的|好)[,，]?\s*)?(?:现在)?我(?:已经)?有(?:了)?[^。！？.!?]*(?:充分|足够|丰富)[^。！？.!?]*证据[^。！？.!?]*(?:整合|组织|整理|撰写|生成|给出)[^。！？.!?]*回答[^。！？.!?]*(?:[。！？.!?]\s*)+"
    r"|(?:现在(?:来|开始)?(?:组织|整理|撰写|生成)[^。！？.!?]*回答[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r"|(?:我(?:来|将|会)?(?:先)?(?:搜索|检索|查找|查询|尝试)[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r"|(?:让我(?:先)?(?:搜索|检索|查找|查询|尝试)[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r"|(?:让我(?:先)?(?:整合|组织|整理|撰写|生成|给出|总结)[^。！？.!?]*回答[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r"|(?:pack\s*没有返回额外内容[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r"|(?:(?:好的|好)[,，]?\s*)?检索次数已达上限[^。！？.!?]*(?:[。！？.!?]\s*)+"
    r"|(?:下面我基于[^。！？.!?]*(?:新检索|检索到|已有|本次)[^。！？.!?]*(?:给出|整理|概览|回答)[^。！？.!?]*(?:[。！？.!?]\s*)+)"
    r")",
    re.IGNORECASE,
)


def _thought_label(text: str) -> str:
    """Condense a model's tool-turn narration into a short process step label."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= 40 else flat[:40] + "…"


_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
_ACRONYM_RE = re.compile(r"\b[A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b|\b[A-Z]{2,}\b")


def _distinctive_terms(answer: str, *, limit: int = 24) -> list[str]:
    """Pull the high-signal tokens from an answer for index re-alignment: numeric
    values (commas stripped: 13,666 -> 13666) and acronym-ish terms (RMSE, mS).
    Numbers survive paraphrase, so they reliably locate the supporting chunk."""
    terms: list[str] = []
    seen: set[str] = set()
    for raw in _NUM_RE.findall(answer or ""):
        tok = raw.replace(",", "").strip(".")
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            terms.append(tok)
    for tok in _ACRONYM_RE.findall(answer or ""):
        if len(tok) >= 2 and tok.lower() not in seen:
            seen.add(tok.lower())
            terms.append(tok)
    return terms[:limit]

SYSTEM_PROMPT = """You are the Literature Research Agent for a single local literature library.
You answer ONLY from evidence retrieved via your tools; never invent papers, numbers, or citations.

Workflow:
- Use `search` first to find candidate papers and evidence snippets. Each evidence item has an
  numeric citation alias in `evidence_id` (e.g. 1). Cite it as [1].
- For follow-up questions, reuse evidence already present in the conversation context before searching again.
- Inspect paper structure (`paper_sections` / `paper_chunks`) or expand assets (`evidence_expand`) when needed.
- For multi-paper, comparison, or statistics answers, build a `pack` (and in deep mode use task_run/run/extract/compare) before composing.
- When you have enough evidence, stop calling tools and write the final answer.

Orchestration policy (how to organize the turn):
- Evidence reuse: if the question is a FOLLOW-UP on the current topic (e.g. "它们的测试条件是什么？",
  "上面第二篇用了什么材料？"), reuse the evidence already in the conversation context and read the
  relevant paper chunks instead of searching again. If the user clearly SWITCHES topic/material/field
  or asks for a new time range, do a fresh search — do NOT reuse the previous topic's evidence.
- Tool failure recovery (each failed tool returns a structured error with a `recovery_hint`):
  read the hint and act on it; do NOT re-issue the SAME call with the same arguments after it failed —
  change the arguments, use a different tool, or, if you cannot proceed, state plainly what is missing.
  `paper_not_found` → search first or ask for a DOI/paper_id; `timeout` → narrow the scope;
  `permission_denied` → the action isn't available in this mode (don't retry); `index_unavailable` →
  say the local index is unavailable, never fabricate.
- Do not loop: a few supplemental searches at most per turn; if coverage is still not improving, answer
  with what you have and state the limitation.

Evidence coverage (decide BEFORE answering — every `search` result includes a `coverage` field):
- coverage.status = sufficient → proceed to a grounded answer.
- coverage.status = partial → answer only the supported parts and explicitly list the gaps;
  optionally do one more targeted search to close a gap.
- coverage.status = weak → prefer a supplemental search (rewrite the query, relax filters,
  drop the year/section restriction) before answering; if still weak, state the insufficiency.
- coverage.status = none → do NOT assert factual conclusions; say the local library has no usable
  evidence and suggest how to broaden the search.
- Do not over-search: when coverage is already sufficient, stop and answer.

Breadth vs coverage (the `breadth` field on each search result):
- The cited evidence is a bounded representative subset; many more candidates may exist beyond it.
- breadth.breadth_limited = true → explicitly frame the answer as a representative overview, not an
  exhaustive/complete review; mention roughly how many papers matched vs how many you grounded on.
- breadth.deep_research_suggested = true → a comprehensive systematic review needs broader coverage; do
  NOT claim full coverage. Follow the per-search-result `note` for the mode-appropriate action: in deep
  mode broaden it yourself (more searches / pack / extract / compare) and label it a representative
  overview; only when you are NOT already in deep research may you suggest switching to deep research.
- Never imply you read the whole field when you only used a representative sample.

Answer contract:
1. State the local search scope / retrieval path you used.
2. Draw conclusions ONLY from returned evidence.
3. Cite every non-obvious claim with its numeric evidence alias in square brackets, e.g. [1].
4. List unresolved gaps when evidence is weak or absent.
5. If the local database returned no usable evidence, say so plainly instead of guessing.

Citation format in prose: put [1] right after the supported sentence. ALWAYS use half-width
square brackets [1] — never full-width 【1】 — so the citation can be parsed.
CRITICAL — every citation you write MUST be copied from a numeric evidence_id alias that a tool returned in
THIS conversation or from a historical citation explicitly listed in the conversation context. Never invent,
guess, increment, or pattern-match a new alias. If you have no real alias for a claim, omit the citation and
state the evidence is limited.
Answer in the user's language (default 中文)."""


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        max_iterations: int = 6,
        tool_budget: int = 12,
        max_searches: int = orch.MAX_SEARCH_CALLS_PER_TURN,
        enforce_citations: bool = True,
        grounding_mode: str = "off",
        role_prompt: str = "",
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_iterations = max_iterations
        self.tool_budget = tool_budget
        self.max_searches = max_searches
        self.enforce_citations = enforce_citations
        # Block 6c: specialist-role system-prompt fragment (empty for the general
        # role). Stated up front so the model honours the role's boundary.
        self.role_prompt = role_prompt
        # Block 3 grounding gate: strict | warn | off. Defaults off here so unit
        # tests of the bare loop don't incur a grounding LLM call; production wires
        # the configured mode (default strict) via settings.
        self.grounding_mode = grounding_mode
        self._available_evidence: dict[str, dict[str, Any]] = {}
        self._coverage_status: str | None = None
        self.citation_registry = CitationRegistry()
        setattr(self.registry, "citation_registry", self.citation_registry)

    async def run(
        self,
        message: str,
        history: list[dict[str, Any]],
        memory_context: dict[str, Any] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.citation_registry = CitationRegistry((memory_context or {}).get("recent_citations") or [])
        setattr(self.registry, "citation_registry", self.citation_registry)
        messages = self._build_messages(message, history, memory_context)
        tools = self.registry.definitions()
        tool_calls_used = 0
        answer = ""
        final_reached = False
        # Block 5 deterministic orchestration shell (no LLM, no planner pass):
        # bound retries/searches and derive the deep-research suggestion.
        mode = getattr(self.registry, "answer_mode", "quick")
        guard = orch.TurnGuard(max_searches=self.max_searches)
        deep_suggested = False
        timeout_failure_emitted = False
        coverage_failure_emitted = False

        for i in range(self.max_iterations):
            # Some models narrate ("我来搜索…") on a tool turn. That narration is
            # process, NOT the answer — only the LAST turn (one with no tool calls)
            # is the answer. We stream every turn live for the typewriter effect,
            # but reset the answer bubble at the start of each new turn so prior
            # narration is discarded and replaced by the eventual final answer.
            if i > 0:
                yield {"type": "answer_reset"}
            turn_content: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            async for delta in self.llm.stream_chat(messages, tools):
                if delta["type"] == "content":
                    text = delta.get("text") or ""
                    if text:
                        turn_content.append(text)
                        yield {"type": "token", "text": text}
                elif delta["type"] == "tool_call":
                    tool_calls.append(delta)

            content = "".join(turn_content)
            if not tool_calls:
                answer = content
                final_reached = True
                break

            # Tool turn: surface any narration as a process step (it was already
            # streamed and will be reset by the next iteration), then run tools.
            if content.strip():
                yield {"type": "step", "status": "info", "label": _thought_label(content)}
            messages.append(_assistant_tool_message(content, tool_calls))
            for call in tool_calls:
                if tool_calls_used >= self.tool_budget:
                    messages.append(_tool_message(call["id"], {"error": "tool budget exhausted"}))
                    continue
                name = call["name"]
                args = call.get("arguments") or {}
                # Guard BEFORE executing: refuse an over-budget search or an
                # identical call that already failed repeatedly, so the loop can't
                # spin. The model gets a structured instruction and moves on.
                block = guard.block_reason(name, args)
                if block:
                    yield {"type": "step", "status": "info", "label": "跳过重复或超额的操作"}
                    messages.append(_tool_message(call["id"], orch.blocked_payload(block)))
                    continue
                tool_calls_used += 1
                yield {"type": "step", "status": "running", "label": _step_label(call)}
                result = await self.registry.execute(name, args, tool_call_id=call.get("id"))
                error_code = _tool_error_code(result.content)
                guard.record(name, args, is_error=te.is_tool_error(result.content))
                guard.record_error_code(name, error_code)
                if name == "search" and error_code == te.TIMEOUT and not timeout_failure_emitted:
                    timeout_failure_emitted = True
                    yield {
                        "type": "failure_explanation",
                        "code": "tool_timeout_failed",
                        "message": failure_message("tool_timeout_failed"),
                    }
                self._available_evidence = self.citation_registry.available_evidence()
                for event in result.events:
                    if event.get("type") == "coverage" and event.get("status"):
                        self._coverage_status = event["status"]  # Block 3 input signal
                    yield event
                    if event.get("type") == "coverage" and not coverage_failure_emitted:
                        failure = _coverage_failure_event(event, message)
                        if failure:
                            coverage_failure_emitted = True
                            yield failure
                    # Deterministically derive the deep-research suggestion from
                    # coverage/breadth (quick mode only); emit at most once a turn.
                    if event.get("type") == "coverage" and not deep_suggested:
                        sug = orch.should_suggest_deep(event, mode)
                        if sug:
                            deep_suggested = True
                            yield {"type": "deep_research_suggestion", "question": message, **sug}
                yield {"type": "step", "status": "done", "label": result.summary}
                messages.append(_tool_message(call["id"], result.content))

        # Exhausted the tool/iteration budget (or the model stopped without an
        # answer) → force ONE final synthesis with tools disabled so we always
        # return a grounded, cited answer instead of leftover narration.
        if not final_reached or not answer.strip():
            yield {"type": "answer_reset"}
            messages.append({"role": "user", "content": _FORCE_ANSWER})
            parts: list[str] = []
            async for delta in self.llm.stream_chat(messages, None):
                if delta["type"] == "content":
                    text = delta.get("text") or ""
                    if text:
                        parts.append(text)
                        yield {"type": "token", "text": text}
            answer = "".join(parts)

        cleaned_answer = _strip_process_narration(answer)
        cleaned_answer = _ensure_attachment_source_marker(cleaned_answer, memory_context)
        if cleaned_answer != answer:
            answer = cleaned_answer
            yield {"type": "answer_reset"}
            if answer:
                yield {"type": "token", "text": answer}

        # Block 3 grounding. The DEFAULT is the deterministic floor ("audit"): no
        # per-claim LLM pass — the answer is never silently rewritten by an LLM
        # judge. The cheap, reliable guardrails still apply: fabricated-citation
        # flagging (below, in the citation audit) and the no-evidence hard-stop.
        # Only strict/warn run the (opt-in) LLM grounding pass; only it shows the
        # "校对中" state and the index re-alignment enrichment that feeds it.
        llm_pass = self.grounding_mode in {"strict", "warn"}
        self._available_evidence = {
            **self.citation_registry.historical_available_evidence(),
            **self.citation_registry.available_evidence(),
        }
        if llm_pass:
            yield {"type": "grounding_status", "state": "checking"}
            # L2 (index-native re-alignment): pull the REAL index chunks containing
            # the answer's distinctive terms into the citable set so the grounding
            # pass verifies "true content with a wrong id" instead of deleting it.
            await self._enrich_available_evidence(answer)
        grounding = await grounding_mod.run_grounding(
            self.llm,
            answer,
            self._available_evidence,
            coverage_status=self._coverage_status,
            mode=self.grounding_mode,
        )
        rewrite_applied = False
        if grounding:
            permission = grounding.get("answer_permission")
            if permission == "not_answerable":
                # Deterministic hard-stop (applies in audit too): answering with
                # zero evidence is the one case we always replace with the honest
                # non-answer — no LLM judgment, no false-positive risk.
                answer = grounding.get("rewritten_answer") or grounding_mod.NOT_ANSWERABLE_MESSAGE
                rewrite_applied = True
            elif self.grounding_mode == "strict" and grounding_mod.needs_rewrite(grounding, self.grounding_mode):
                answer = grounding["rewritten_answer"]
                rewrite_applied = True
            if rewrite_applied:
                yield {"type": "answer_reset"}
                yield {"type": "token", "text": answer}

        # Project the draft audit onto the FINAL answer so the footer describes what
        # the user actually sees (survivors), not the discarded draft. The
        # deterministic citation audit always runs on the final answer below.
        final_grounding = grounding_mod.reconcile_final(grounding, rewrite_applied)
        finalized = self.citation_registry.finalize_answer(answer)
        if finalized["answer"] != answer:
            answer = finalized["answer"]
            yield {"type": "answer_reset"}
            if answer:
                yield {"type": "token", "text": answer}
        # Block 5: deterministic "reused prior evidence" signal — this turn made no
        # search call yet answered from the injected recent evidence (a follow-up).
        reused_evidence = guard.search_calls == 0 and bool((memory_context or {}).get("recent_citations")) and bool(_CITATION_RE.search(answer or ""))
        yield self._citation_event(answer, final_grounding, reused_evidence=reused_evidence, resolved=finalized)

    # --- internals --------------------------------------------------------------

    def _build_messages(
        self,
        message: str,
        history: list[dict[str, Any]],
        memory_context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.role_prompt:
            messages.append({"role": "system", "content": self.role_prompt})
        # Tell the model which research intent it is serving, so breadth guidance is
        # consistent (in deep mode it must NOT suggest "start deep research").
        mode = getattr(self.registry, "answer_mode", "quick")
        mode_line = (
            "Current research intent: DEEP RESEARCH. You are already in deep mode — broaden "
            "coverage yourself and never tell the user to start deep research."
            if mode == "deep"
            else "Current research intent: QUICK ANSWER. Keep it focused; you may suggest deep "
            "research for comprehensive coverage."
        )
        messages.append({"role": "system", "content": mode_line})
        context_block = _memory_block(memory_context)
        if context_block:
            messages.append({"role": "system", "content": context_block})
        for turn in history[-8:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        return messages

    async def _enrich_available_evidence(self, answer: str) -> None:
        """L2: add real index chunks that support the answer's distinctive terms to
        the citable set, scoped to the papers already in play. Defensive — any
        failure (no index, fake service in tests) silently no-ops."""
        service = getattr(self.registry, "service", None)
        finder = getattr(service, "find_supporting_evidence", None)
        if not callable(finder):
            return
        paper_ids = {e.get("paper_id") for e in self._available_evidence.values() if e.get("paper_id")}
        terms = _distinctive_terms(answer)
        if not paper_ids or not terms:
            return
        try:
            supporting = await asyncio.to_thread(finder, list(paper_ids), terms, limit=12)
        except Exception:  # noqa: BLE001 - re-alignment must never break answering
            return
        for ev in supporting or []:
            eid = ev.get("evidence_id")
            if eid and eid not in self._available_evidence:
                self._available_evidence[eid] = ev

    def _register_recent_evidence(self, memory_context: dict[str, Any] | None) -> None:
        for item in (memory_context or {}).get("recent_evidence") or []:
            eid = item.get("evidence_id") if isinstance(item, dict) else None
            if eid and eid not in self._available_evidence:
                self._available_evidence[eid] = dict(item)

    def _citation_event(
        self,
        answer: str,
        grounding: dict[str, Any] | None = None,
        *,
        reused_evidence: bool = False,
        resolved: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = resolved or self.citation_registry.resolve_answer(answer)
        cited_ids = resolved["cited_ids"]
        missing = resolved["missing_ids"]
        available = set(self.citation_registry.available_evidence()) | {
            str(item.get("alias")) for item in self.citation_registry.historical_manifest.values() if item.get("alias")
        }
        used = resolved["used_evidence"]
        audit_status, status = self._resolve_audit_status(grounding, cited_ids, missing, available)
        event = {
            "type": "citation",
            "status": status,  # legacy ok/warning axis (report.py / older consumers)
            "audit_status": audit_status,  # verified | advisory | unverified | uncited | off
            "cited_ids": cited_ids,
            "missing_ids": missing,
            "used_evidence": used,
            "resolved_citations": resolved["resolved_citations"],
            "available_count": resolved["available_count"],
            "reused_evidence": reused_evidence,
        }
        # Block 3 superset: nest the FINAL-answer grounding record + answer_permission
        # + a compact summary. `answer_permission` here is a COMPLETENESS/strength axis
        # ("how far the local evidence lets us go"), NOT a "should you trust the text"
        # axis — after a strict gate the text is already safe; the summary only explains
        # why it is phrased the way it is, it does not contradict the body.
        if grounding is not None:
            event["grounding"] = grounding
            event["answer_permission"] = grounding.get("answer_permission")
            event["grounding_summary"] = grounding_mod.summarize(grounding)
        return event

    def _resolve_audit_status(
        self,
        grounding: dict[str, Any] | None,
        cited_ids: list[str],
        missing: list[str],
        available: set[str],
    ) -> tuple[str, str]:
        """Decide the audit state + legacy ok/warning flag.

        Key reframing (Block 3): a successfully gated answer is NEVER a warning, even
        when it is partial/hypothesis/conflicting — the body is safe and the footer is
        a neutral transparency note. The red "warning" is reserved for answers that were
        NOT successfully gated: a fabricated id survived into the text, or the grounding
        pass was unavailable (so we fell back to the raw model answer).
        """
        if grounding is None:
            # "audit" (default) and "off" intentionally produce NO LLM grounding
            # record — fall back to the deterministic citation audit (the reliable
            # floor): flag a fabricated/unknown id, else neutral.
            if self.grounding_mode in {"off", "audit"}:
                if missing:
                    return "unverified", "warning"  # cited an id we never retrieved
                if self.enforce_citations and self._available_evidence and not cited_ids:
                    return "uncited", "warning"  # had evidence but cited nothing
                return ("verified" if self.grounding_mode == "audit" else "off", "ok")
            # strict/warn requested but grounding could not be produced (LLM/parse
            # failure) → the answer is genuinely un-vetted: caution is warranted.
            return "unverified", "warning"
        if missing:
            return "unverified", "warning"  # a hallucinated id survived the gate
        if self.grounding_mode == "strict":
            return "verified", "ok"  # gated to safety → neutral regardless of permission
        # warn mode: grounding explains but did NOT rewrite the answer, so unsupported
        # claims may still be present → flag them as genuine caution.
        has_unsupported = any(
            (c.get("support_status") == "unsupported") for c in grounding.get("claims") or []
        )
        return ("advisory", "warning" if has_unsupported else "ok")


def _dedupe_used_evidence(cited_ids: list[str], available: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse cited evidence that points at the same physical locus.

    Keyed by (paper_id, source_path, section_id, chunk_index). Entries whose
    locus is entirely empty are NOT merged (keyed by their id) to avoid folding
    together unrelated evidence. Each kept entry gains an `evidence_ids` list of
    every cited id that resolved to it; `evidence_id` stays as the first one.
    """
    groups: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for cid in cited_ids:
        item = available.get(cid)
        if not item:
            continue
        locus = (item.get("paper_id"), item.get("source_path"), item.get("section_id"), item.get("chunk_index"))
        key = locus if any(locus) else ("__id__", cid)
        existing = groups.get(key)
        if existing is None:
            entry = dict(item)
            entry["evidence_id"] = cid
            entry["evidence_ids"] = [cid]
            groups[key] = entry
            order.append(key)
        elif cid not in existing["evidence_ids"]:
            existing["evidence_ids"].append(cid)
    return [groups[key] for key in order]


def _assistant_tool_message(content: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }


def _tool_message(tool_call_id: str, content: Any) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return {"role": "tool", "tool_call_id": tool_call_id, "content": text}


def _tool_error_code(content: Any) -> str | None:
    if not te.is_tool_error(content):
        return None
    error = content.get("error") or {}
    code = error.get("code")
    return str(code) if code else None


def _coverage_failure_event(event: dict[str, Any], message: str) -> dict[str, Any] | None:
    status = event.get("status")
    if status == "none":
        breadth = event.get("breadth") or {}
        candidate_count = int(breadth.get("candidate_paper_count") or event.get("candidate_paper_count") or 0)
        code = "no_candidate_papers" if candidate_count == 0 else "no_usable_evidence"
        return {"type": "failure_explanation", "code": code, "message": failure_message(code, query=message)}
    if status == "weak":
        code = "no_usable_evidence"
        return {"type": "failure_explanation", "code": code, "message": failure_message(code, query=message)}
    return None


def _strip_process_narration(answer: str) -> str:
    text = answer or ""
    previous = None
    while text and text != previous:
        previous = text
        text = _PROCESS_NARRATION_SENTENCE_RE.sub("", text).lstrip()
    return text or (answer or "")


def _ensure_attachment_source_marker(answer: str, memory_context: dict[str, Any] | None) -> str:
    attachments = (memory_context or {}).get("session_attachments") or []
    if not answer or not attachments:
        return answer
    filenames = [item.get("filename") or "附件" for item in attachments[:5]]
    if any(f"来自上传附件《{filename}》" in answer for filename in filenames):
        return answer
    source = "、".join(f"《{filename}》" for filename in filenames)
    marker = f"来自上传附件{source}：本轮回答已加载这些会话临时附件；附件内容不属于正式文献证据。"
    return f"{marker}\n\n{answer}"


def _step_label(call: dict[str, Any]) -> str:
    name = call.get("name", "tool")
    args = call.get("arguments") or {}
    target = args.get("query") or args.get("question") or args.get("doi") or ""
    labels = {
        "search": "检索本地文献库",
        "pack": "整理证据包",
        "task_run": "进行深度研究",
        "run": "进行深度研究",
        "extract": "抽取指标数据",
        "compare": "生成对比分析",
        "paper_sections": "读取关键论文",
        "paper_chunks": "读取论文文本",
        "evidence_expand": "展开表格/图片证据",
        "verify_answer": "检查引用",
        "quality": "检查研究质量",
    }
    # Never leak a raw tool name to the user (Block 5 process-language rule).
    base = labels.get(name, "执行研究操作")
    return f"{base}：{target}" if target else base


def _research_state_lines(state: dict[str, Any] | None) -> list[str]:
    """Block 6b: render the authored research state so the agent honours the
    user's curation — keep retained papers, avoid excluded ones/directions,
    and treat open questions as the standing agenda when asked to "继续"."""
    if not state:
        return []
    lines: list[str] = ["当前课题研究状态（用户已确认，须遵守）："]
    if state.get("objective"):
        lines.append(f"- 研究目标：{state['objective']}")
    if state.get("stage"):
        lines.append(f"- 当前阶段：{state['stage']}")

    def _titles(papers: list[dict], limit: int = 8) -> str:
        names = [p.get("title") or p.get("doi") or p.get("paper_id") or "?" for p in papers[:limit]]
        return "；".join(names)

    if state.get("accepted_papers"):
        lines.append(f"- 已保留论文（优先复用其证据）：{_titles(state['accepted_papers'])}")
    if state.get("excluded_papers"):
        lines.append(f"- 已排除论文（不要再引用）：{_titles(state['excluded_papers'])}")

    def _evidence_refs(items: list[dict], limit: int = 8) -> str:
        refs = []
        for item in items[:limit]:
            eid = item.get("evidence_id") or "?"
            title = item.get("title") or item.get("doi") or ""
            refs.append(f"证据 {eid} {title}".strip())
        return "；".join(refs)

    if state.get("accepted_evidence"):
        lines.append(f"- 已保留证据（优先复用）：{_evidence_refs(state['accepted_evidence'])}")
    if state.get("excluded_evidence"):
        lines.append(f"- 已排除证据（不要再引用）：{_evidence_refs(state['excluded_evidence'])}")
    if state.get("needs_review_evidence"):
        lines.append(f"- 待复核证据（引用前先核对）：{_evidence_refs(state['needs_review_evidence'])}")
    if state.get("excluded_directions"):
        lines.append(f"- 已排除方向（不要再检索）：{'；'.join(state['excluded_directions'][:8])}")
    if state.get("open_questions"):
        lines.append(f"- 待解决问题（继续推进时优先处理）：{'；'.join(state['open_questions'][:8])}")
    return lines


def _memory_block(memory_context: dict[str, Any] | None) -> str:
    if not memory_context:
        return ""
    lines: list[str] = []
    state_lines = _research_state_lines(memory_context.get("research_state"))
    if state_lines:
        lines.extend(state_lines)
        lines.append("")
    citation_groups = memory_context.get("recent_citations") or []
    if citation_groups:
        lines.append("本会话此前回答中已经持久化的历史引用（仅在追问前文时复用这些编号）：")
        for group in citation_groups[:6]:
            msg = group.get("message_id") or "previous"
            lines.append(f"Message {msg}:")
            for item in (group.get("citations") or [])[:8]:
                alias = item.get("alias") or "?"
                paper = item.get("paper_snapshot") or {}
                title = paper.get("title") or paper.get("doi") or ""
                snippet = (item.get("display_snippet") or item.get("snippet") or "")[:200]
                lines.append(f"[{alias}] {title}: {snippet}")
    artifacts = memory_context.get("linked_artifacts") or []
    if artifacts:
        lines.append("")
        lines.append("已生成的研究产物（可作为 verify/quality 的引用对象）：")
        for art in artifacts[:8]:
            lines.append(f"- {art.get('artifact_type')}: {art.get('title') or art.get('artifact_id')}")
    attachments = memory_context.get("session_attachments") or []
    if attachments:
        lines.append("")
        lines.append(
            "用户上传的会话临时附件（只能作为上传材料引用，不属于本地文献库证据；"
            "不要把它们写成数字文献证据引用）："
        )
        for item in attachments[:5]:
            filename = item.get("filename") or "附件"
            text = (item.get("text") or item.get("text_preview") or "")[:2400]
            lines.append(f"来自上传附件《{filename}》:\n{text}")
    return "\n".join(lines)
