"""Block 3: evidence grounding / claim-level citation / answer permission.

Block 2 decides *did we retrieve enough* (coverage / evidence boundary). Block 3
is the generation-side guardrail: given the final answer plus the evidence that
was actually available for citation, it decides *did the answer answer past the
evidence* and, in strict mode, rewrites the answer back inside the evidence.

The grounding judgement is a SEPARATE post-answer LLM pass (not the main model's
self-report): the generation model already struggles with citation discipline, so
a dedicated pass that only sees (answer + evidence snippets) is both more reliable
and trivially testable with a scripted LLM. The pass emits a structured grounding
record:

    claims[] (claim / support_status / evidence_ids / rewrite_action / scope_notes)
    answer_permission: grounded | partially_grounded | hypothesis | conflicting | not_answerable
    conflicting_claims[] / corpus_boundary_notes[] / warnings[]
    rewritten_answer (strict-mode downgrade that stays inside the evidence)

Any failure (parse error, LLM error, mode=off) degrades to ``None`` so the loop
falls back to the deterministic citation audit it has always done — grounding is
additive and never breaks answering.
"""
from __future__ import annotations

import json
from typing import Any

from core.llm.client import LLMClient
from modules.literature_search.failure_messages import failure_message

PERMISSIONS = {
    "grounded",
    "partially_grounded",
    "hypothesis",
    "conflicting",
    "not_answerable",
}
SUPPORT_STATUSES = {
    "supported",
    "partially_supported",
    "unsupported",
    "conflicting",
    "inference",
}
REWRITE_ACTIONS = {"keep", "downgrade", "remove", "label_inference"}

# rewrite_action values that mean the original answer overstepped the evidence and
# (in strict mode) must be replaced by the downgraded rewrite.
_OVERSTEP_ACTIONS = {"downgrade", "remove", "label_inference"}

# Honest stand-in for a not_answerable answer: in strict mode the final body the
# user sees must BE the non-answer, not a factual answer wearing a "not_answerable"
# label. Used when the grounding pass did not supply its own rewrite.
NOT_ANSWERABLE_MESSAGE = (
    failure_message("no_usable_evidence")
    + "\n\n建议：更换或放宽检索关键词，或切换到深度分析以扩大检索覆盖。"
)

_GROUNDING_SYSTEM = """You are a strict evidence-grounding auditor for a local literature research agent.
You receive (1) the agent's final answer and (2) the ONLY evidence snippets that were available to it.
Your job is NOT to re-answer. It is to check whether the answer stays inside what the evidence supports,
and to produce a corrected answer when it does not.

For each key factual claim in the answer, classify it against the available evidence:
- supported: an available evidence snippet directly supports the claim.
- partially_supported: evidence supports part of it, but the claim extrapolates or has a gap.
- unsupported: no available evidence supports it (a cited [E#] that exists but does NOT actually back the
  claim is also unsupported — citation legality is not support).
- conflicting: different evidence snippets give contradictory information about the claim.
- inference: the claim is the agent's reasoning/synthesis/hypothesis, not a direct evidence statement.

CRITICAL — content support, not id identity:
- Judge whether the CONTENT is supported by ANY available snippet, regardless of which id the answer cited.
- If a specific number, unit, or term in the claim appears VERBATIM in an available snippet (e.g. "13666",
  "19.14 mS", "234 s"), the claim is supported by that snippet — set support_status=supported and set
  evidence_ids to that snippet's [E#]. Do not call it unsupported just because the wording differs.
- RE-ALIGNMENT: if the answer attached a wrong or non-existent id to a claim whose content IS supported by
  some available snippet, keep the claim and re-cite the CORRECT available [E#] (rewrite_action=keep). Only
  mark unsupported (and remove) when NO available snippet supports the content at all.
- METADATA is authoritative: each evidence shows its paper's (year, journal) in parentheses after the title.
  A claim about a paper's publication year or journal that matches that metadata is SUPPORTED — do NOT
  downgrade it for being "absent from the snippet text". The metadata comes from the index, not the prose.

Then assign an overall answer_permission:
- grounded: the main conclusions are each directly supported.
- partially_grounded: answerable in part, with explicit gaps.
- hypothesis: the substance is inference, not direct evidence.
- conflicting: the evidence is contradictory.
- not_answerable: the evidence does not permit a factual conclusion.

Scope discipline you MUST enforce in the rewritten answer:
- A single / local result must NOT be written as a field-wide, universal, or certain conclusion.
- A small experiment must NOT be written as "proven".
- Local-library results must be framed as "within this retrieval / local library", never "all research".
- Conflicting evidence must be presented side by side, never summarised to one side.
- Inferences must be explicitly labelled as inference / hypothesis.
- Always distinguish "the local library returned no supporting evidence" from "this does not exist in reality".

Rewrite rules:
- Remove or downgrade unsupported claims (do not keep them as-is).
- Add limiting language to partially_supported claims.
- Keep every VALID [E#] citation verbatim. NEVER invent, guess, or alter an evidence id; only use ids from
  the provided evidence list. Drop a citation rather than fabricate one.
- Keep the user's language (default 中文). Keep it natural and readable — this is the answer the user sees.
- If nothing needs changing, set rewritten_answer to null.

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "claims": [
    {"claim": "<short paraphrase>", "claim_type": "<fact|metric|comparison|mechanism|inference|...>",
     "support_status": "supported|partially_supported|unsupported|conflicting|inference",
     "evidence_ids": ["E#"...], "confidence": "high|medium|low",
     "scope_notes": "<why / what limitation>", "rewrite_action": "keep|downgrade|remove|label_inference"}
  ],
  "answer_permission": "grounded|partially_grounded|hypothesis|conflicting|not_answerable",
  "conflicting_claims": ["<claim text>"...],
  "corpus_boundary_notes": ["<note about local-library vs reality boundary>"...],
  "warnings": ["<short human-facing warning>"...],
  "rewritten_answer": "<corrected answer, or null if no change needed>"
}"""


async def run_grounding(
    llm: LLMClient,
    answer: str,
    available_evidence: dict[str, dict[str, Any]],
    *,
    coverage_status: str | None = None,
    mode: str = "strict",
) -> dict[str, Any] | None:
    """Audit ``answer`` against ``available_evidence``; return a grounding record or None.

    ``mode`` is ``strict`` | ``warn`` | ``off``. ``off`` skips entirely. The record
    is normalised; ``None`` means "no structured grounding — fall back to the
    deterministic citation audit".
    """
    if mode == "off":
        return None

    # Deterministic floor (applies in audit/strict/warn): with no citable evidence
    # at all there is nothing to ground against — an LLM call cannot manufacture
    # support. The answer is, by definition, not answerable from the local library.
    if not available_evidence:
        return {
            "claims": [],
            "answer_permission": "not_answerable",
            "conflicting_claims": [],
            "corpus_boundary_notes": ["本地库本轮检索未返回可用证据；以下不能作为事实性结论。"],
            "warnings": ["无可用证据，已标记为不可作答（not_answerable）。"],
            "rewritten_answer": None,
        }

    # "audit" = deterministic floor only: stop before the per-claim LLM pass. The
    # answer keeps streaming as-is; the citation audit still flags fabricated ids.
    if mode == "audit":
        return None

    user = _grounding_user_message(answer, available_evidence, coverage_status)
    messages = [
        {"role": "system", "content": _GROUNDING_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        raw = await _collect(llm, messages)
    except Exception:  # noqa: BLE001 - grounding must never break answering
        return None

    data = _extract_json(raw)
    if data is None:
        return None
    return _normalize(data, available_evidence)


def needs_rewrite(grounding: dict[str, Any] | None, mode: str) -> bool:
    """Whether strict mode should replace the answer with the downgraded rewrite."""
    if mode != "strict" or not grounding:
        return False
    rewritten = grounding.get("rewritten_answer")
    if not (isinstance(rewritten, str) and rewritten.strip()):
        return False
    if grounding.get("answer_permission") != "grounded":
        return True
    return any(
        (c.get("rewrite_action") or "keep") in _OVERSTEP_ACTIONS
        for c in grounding.get("claims") or []
    )


def reconcile_final(grounding: dict[str, Any] | None, rewrite_applied: bool) -> dict[str, Any] | None:
    """Project a draft grounding record onto the FINAL (post-gate) answer.

    The grounding pass audits the DRAFT. After a strict rewrite the answer the user
    sees no longer contains the ``remove`` claims, and ``downgrade`` / ``label_inference``
    claims now carry limiting wording. So the record we attach must describe survivors,
    not the discarded draft — otherwise a safe answer wears the draft's scary counts
    (the "正文安全 / 底部说有问题" split). ``removed_claims`` is kept separately for
    transparency ("what we left out, and why"), never as a correction OF the text.
    """
    if not grounding:
        return None
    claims = grounding.get("claims") or []
    out = dict(grounding)
    out.pop("rewritten_answer", None)  # internal draft artifact, never surface it
    if not rewrite_applied:
        # No gate edit: the draft IS the final answer, every claim still stands.
        out["claims"] = claims
        out["removed_claims"] = []
        out["gated"] = False
        return out
    survivors: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for c in claims:
        action = c.get("rewrite_action") or "keep"
        if action == "remove":
            removed.append(c)
            continue
        kept = dict(c)
        # Reflect the limiting wording the rewrite applied to survivors.
        if action == "downgrade" and kept.get("support_status") == "supported":
            kept["support_status"] = "partially_supported"
        elif action == "label_inference":
            kept["support_status"] = "inference"
        survivors.append(kept)
    out["claims"] = survivors
    out["removed_claims"] = removed
    out["gated"] = True
    return out


def summarize(grounding: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact counts for the footer — computed on the FINAL answer's claims.

    Expects the reconciled record (``claims`` = survivors, ``removed_claims`` = what the
    gate dropped). ``removed`` is reported as transparency, not as "unsupported claims
    sitting in the answer".
    """
    if not grounding:
        return None
    claims = grounding.get("claims") or []
    counts = {s: 0 for s in SUPPORT_STATUSES}
    for c in claims:
        status = c.get("support_status")
        if status in counts:
            counts[status] += 1
    return {
        "answer_permission": grounding.get("answer_permission"),
        "gated": bool(grounding.get("gated")),
        "claims_total": len(claims),
        "supported": counts["supported"],
        # "limited" = survivors the user should read with caution (caveated / inferred).
        "limited": counts["partially_supported"] + counts["inference"],
        # post-gate this should be 0 (unsupported claims were removed); kept for warn mode.
        "unsupported": counts["unsupported"],
        "conflicting": counts["conflicting"],
        "removed": len(grounding.get("removed_claims") or []),
        "warnings": grounding.get("warnings") or [],
    }


# --- internals --------------------------------------------------------------


def _grounding_user_message(
    answer: str, available_evidence: dict[str, dict[str, Any]], coverage_status: str | None
) -> str:
    lines = ["AVAILABLE EVIDENCE (the only ids you may cite):"]
    for eid, item in available_evidence.items():
        title = (item.get("title") or "").strip()
        section = (item.get("section") or item.get("kind") or "").strip()
        snippet = " ".join((item.get("snippet") or "").split())[:400]
        # Paper-level metadata is authoritative (it comes from the index), so the
        # publication year / journal are verifiable here even when absent from the
        # chunk snippet — a year/journal claim matching this is supported.
        meta = ", ".join(str(x) for x in (item.get("year"), item.get("journal")) if x)
        head = f"[{eid}]"
        if title:
            head += f" {title}"
        if meta:
            head += f" ({meta})"
        if section:
            head += f" · {section}"
        lines.append(f"{head}\n  {snippet}")
    if coverage_status:
        lines.append("")
        lines.append(f"Retrieval coverage status (from Block 2): {coverage_status}")
    lines.append("")
    lines.append("AGENT ANSWER TO AUDIT:")
    lines.append(answer)
    return "\n".join(lines)


async def _collect(llm: LLMClient, messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    async for delta in llm.stream_chat(messages, None):
        if delta.get("type") == "content":
            text = delta.get("text") or ""
            if text:
                parts.append(text)
    return "".join(parts)


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response (tolerates fences/prose)."""
    if not raw:
        return None
    text = raw.strip()
    # Strip a leading ```json / ``` fence if present.
    if text.startswith("```"):
        text = text.split("```", 2)[-1] if text.count("```") >= 2 else text.lstrip("`")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize(data: dict[str, Any], available_evidence: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    permission = data.get("answer_permission")
    if permission not in PERMISSIONS:
        return None  # an unparseable permission means we don't trust the record
    valid_ids = set(available_evidence)
    claims_out: list[dict[str, Any]] = []
    for raw_claim in data.get("claims") or []:
        if not isinstance(raw_claim, dict):
            continue
        status = raw_claim.get("support_status")
        if status not in SUPPORT_STATUSES:
            status = "unsupported"
        action = raw_claim.get("rewrite_action")
        if action not in REWRITE_ACTIONS:
            action = "keep"
        # Never let the grounding pass smuggle in ids that weren't available.
        eids = [e for e in (raw_claim.get("evidence_ids") or []) if e in valid_ids]
        claims_out.append(
            {
                "claim": str(raw_claim.get("claim") or "").strip(),
                "claim_type": str(raw_claim.get("claim_type") or "").strip() or None,
                "support_status": status,
                "evidence_ids": eids,
                "confidence": raw_claim.get("confidence"),
                "scope_notes": str(raw_claim.get("scope_notes") or "").strip() or None,
                "rewrite_action": action,
            }
        )
    rewritten = data.get("rewritten_answer")
    if not (isinstance(rewritten, str) and rewritten.strip()):
        rewritten = None
    return {
        "claims": claims_out,
        "answer_permission": permission,
        "conflicting_claims": [str(c).strip() for c in (data.get("conflicting_claims") or []) if str(c).strip()],
        "corpus_boundary_notes": [str(c).strip() for c in (data.get("corpus_boundary_notes") or []) if str(c).strip()],
        "warnings": [str(w).strip() for w in (data.get("warnings") or []) if str(w).strip()],
        "rewritten_answer": rewritten,
    }
