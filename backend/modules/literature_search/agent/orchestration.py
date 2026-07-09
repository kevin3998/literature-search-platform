"""Deterministic orchestration shell for the Chat agent loop (Block 5).

This module is the *deterministic* part of orchestration — small, testable rules
that bound the ReAct loop. It deliberately does NOT decide which tool to use or
whether a question is a follow-up; those remain the LLM's judgment, guided by the
system prompt and the injected recent-evidence context. What lives here:

- a per-turn guard that stops the loop from re-calling an identical tool call that
  keeps failing, and caps supplemental searches so the agent can't spin;
- a deterministic derivation of the "start deep research?" suggestion from a
  coverage event (quick mode only — deep mode broadens in place, never suggests).

No LLM calls. No extra planner pass.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

# A normal quick turn rarely needs more than a couple of searches; the cap stops
# runaway re-searching. Coordinated with the lower retry layers (Block 2
# MAX_RECOVERY, Block 4 search retry=1) — this is the OUTER per-turn ceiling.
MAX_SEARCH_CALLS_PER_TURN = 3
# Re-issuing the exact same call after it failed twice is a loop, not recovery.
MAX_IDENTICAL_FAILURES = 2


@dataclass(frozen=True)
class ChatRoute:
    """Deterministic entry route for a user chat turn.

    Non-research turns are answered before the evidence-grounded AgentLoop so
    normal conversational affordances are not rewritten as "no local evidence".
    """

    kind: str

    @property
    def should_enter_research(self) -> bool:
        return self.kind in {"research", "followup_research"}


_CASUAL_EXACT = {
    "你好", "您好", "hello", "hi", "嗨", "哈喽",
    "谢谢", "感谢", "多谢", "thanks", "thank you",
    "好的", "好", "ok", "okay", "明白了", "了解", "收到",
    "再见", "拜拜",
}
_HELP_PATTERNS = (
    "你能做什么", "你可以做什么", "你会做什么", "能做什么",
    "怎么用", "如何使用", "怎样使用", "使用方法", "如何开始",
    "怎么开始", "你是谁", "你是什么", "帮助", "help",
)
_FOLLOWUP_TERMS = (
    "这些", "上述", "上面", "前面", "刚才", "它们", "他们", "这些论文",
    "第二篇", "第一篇", "继续", "还有", "分别",
)
_RESEARCH_TERMS = (
    "文献", "论文", "研究", "综述", "检索", "证据", "引用", "doi",
    "对比", "比较", "指标", "数据", "机制", "作用", "影响", "实验",
    "测试", "方法", "结果", "结论", "材料", "性能", "进展", "最新",
    "分析", "总结", "梳理", "tumor", "immune", "treg", "review",
    "paper", "papers", "literature", "compare", "mechanism",
)
_VAGUE_ANALYSIS = {
    "帮我分析一下", "分析一下", "帮我看看", "帮我总结一下", "总结一下",
    "帮我研究一下", "研究一下", "查一下", "检索一下",
}
_PUNCT_RE = re.compile(r"[\s。！？!?.,，；;：:、~～]+")


def _compact_text(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").strip().lower())


_CASUAL_COMPACT = {_compact_text(x) for x in _CASUAL_EXACT}
_VAGUE_ANALYSIS_COMPACT = {_compact_text(x) for x in _VAGUE_ANALYSIS}


def route_chat_intent(
    message: str,
    *,
    has_history: bool = False,
    has_recent_evidence: bool = False,
) -> ChatRoute:
    """Classify whether a turn should enter the evidence-grounded research loop.

    This is deliberately conservative and deterministic: short product/chit-chat
    turns are handled locally, while anything that looks like a literature task
    continues into the existing AgentLoop.
    """
    raw = (message or "").strip()
    compact = _compact_text(raw)
    lowered = raw.lower()
    if not compact:
        return ChatRoute("clarification")

    if compact in _CASUAL_COMPACT:
        return ChatRoute("casual")
    if compact in {"你好啊", "您好啊", "hello there"}:
        return ChatRoute("casual")

    if any(term in lowered or _compact_text(term) in compact for term in _HELP_PATTERNS):
        return ChatRoute("help")

    if has_recent_evidence and has_history and any(term in lowered for term in _FOLLOWUP_TERMS):
        if any(term in lowered for term in _RESEARCH_TERMS) or len(compact) >= 8:
            return ChatRoute("followup_research")

    if compact in _VAGUE_ANALYSIS_COMPACT:
        return ChatRoute("clarification")

    if len(compact) <= 3 and not any(term in lowered for term in _RESEARCH_TERMS):
        return ChatRoute("clarification")

    if any(term in lowered for term in _RESEARCH_TERMS):
        return ChatRoute("research")

    # Preserve the literature module's prior behavior for substantive free-form
    # queries that do not happen to contain one of our keyword hints.
    return ChatRoute("research")

def call_signature(name: str, arguments: dict[str, Any] | None) -> str:
    """Stable id for a (tool, arguments) pair, for failure de-duplication."""
    try:
        payload = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        payload = str(arguments)
    return f"{name}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def blocked_payload(reason: str) -> dict[str, Any]:
    """Structured tool result for a call the guard refused to execute, mirroring
    the Block 4 error shape so the model reads it the same way."""
    return {
        "ok": False,
        "error": {
            "code": "blocked_by_policy",
            "message": reason,
            "retryable": False,
            "recovery_hint": reason,
        },
    }


class TurnGuard:
    """Per-turn deterministic guard. Construct one per ``AgentLoop.run`` turn."""

    def __init__(
        self,
        *,
        max_searches: int = MAX_SEARCH_CALLS_PER_TURN,
        max_identical_failures: int = MAX_IDENTICAL_FAILURES,
    ) -> None:
        self.max_searches = max_searches
        self.max_identical_failures = max_identical_failures
        self._failures: dict[str, int] = {}
        self.search_calls = 0
        self.search_timeout_seen = False

    def block_reason(self, name: str, arguments: dict[str, Any] | None) -> str | None:
        """Return a short instruction if this call should NOT be executed, else None.

        Checked BEFORE execution so a known-bad or over-budget call never runs.
        """
        if name == "search" and self.search_calls >= self.max_searches:
            return (
                f"已达到本轮检索次数上限（{self.max_searches} 次）。不要再检索，"
                "请基于已获得的证据作答，并说明覆盖度限制。"
            )
        if name == "search" and self.search_timeout_seen:
            return (
                "本轮检索工具已经超时。不要继续发起新的检索；"
                "请说明检索超时，当前无法给出可靠的本地文献证据回答。"
            )
        sig = call_signature(name, arguments)
        if self._failures.get(sig, 0) >= self.max_identical_failures:
            return (
                "该操作以完全相同的参数已多次失败，不要重复调用。"
                "请改用不同参数或其他工具，或根据现有信息说明无法继续。"
            )
        return None

    def record(self, name: str, arguments: dict[str, Any] | None, *, is_error: bool) -> None:
        """Record the outcome of an executed call (errors feed the loop-guard)."""
        if name == "search":
            self.search_calls += 1
        if is_error:
            sig = call_signature(name, arguments)
            self._failures[sig] = self._failures.get(sig, 0) + 1

    def record_error_code(self, name: str, code: str | None) -> None:
        if name == "search" and code == "timeout":
            self.search_timeout_seen = True


def should_suggest_deep(coverage_event: dict[str, Any], answer_mode: str) -> dict[str, Any] | None:
    """Deterministically derive a deep-research suggestion from a coverage event.

    Quick mode only — deep mode is already broadening, so it must never tell the
    user to "start deep research" (consistent with the breadth note fix). Returns
    a small payload for the ``deep_research_suggestion`` event, or None.
    """
    if answer_mode == "deep":
        return None
    breadth = coverage_event.get("breadth") or {}
    suggested = coverage_event.get("deep_research_suggested") or breadth.get("deep_research_suggested")
    if not suggested:
        return None
    return {
        "reason": coverage_event.get("short_message") or "当前结果更适合作为代表性概览。",
        "candidate_paper_count": breadth.get("candidate_paper_count"),
        "estimated_total_matches": breadth.get("estimated_total_matches"),
    }
