"""Render an auditable, citable Markdown report from a session research record.

Consumes the structure produced by ``SessionStore.build_record`` and emits a
self-contained Markdown document: every turn's question + answer, the retrieval
calls made, and a deduplicated Sources section mapping each evidence id back to
its local file (`source_path`) so the report is traceable end to end.
"""
from __future__ import annotations

import time
from typing import Any


def render_markdown_report(record: dict[str, Any]) -> str:
    session = record.get("session") or {}
    turns = record.get("turns") or []
    title = session.get("title") or "研究记录"
    generated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.get("generated_at") or time.time()))

    lines: list[str] = [f"# {title}", "", f"_导出时间：{generated} · 会话 {session.get('session_id', '')}_", ""]

    sources: dict[str, dict[str, Any]] = {}
    answered = 0
    for index, turn in enumerate(turns, 1):
        query = (turn.get("query") or "").strip()
        answer = (turn.get("answer") or "").strip()
        if not query and not answer:
            continue
        answered += 1
        lines.append(f"## {index}. {query or '（无问题文本）'}")
        lines.append("")

        searches = turn.get("searches") or []
        if searches:
            scopes = ", ".join(
                f"`{s.get('query')}`（{s.get('retrieval_used') or 'n/a'}，命中 {s.get('result_count', 0)}）"
                for s in searches
            )
            lines.append(f"**检索**：{scopes}")
            lines.append("")

        lines.append(answer or "_（本轮无最终回答）_")
        lines.append("")

        citation = turn.get("citation") or {}
        _append_grounding(lines, citation)
        # A genuine warning note is reserved for answers that were NOT successfully
        # gated (fabricated id survived, or grounding unavailable). A safe, gated
        # answer never carries a contradicting "warning" — its grounding line above
        # is a neutral transparency note. Legacy records (pre-audit_status) fall back
        # to the old status==warning behaviour.
        audit = citation.get("audit_status")
        unverified = audit in {"unverified", "uncited"} or (audit is None and citation.get("status") == "warning")
        if unverified:
            missing = citation.get("missing_ids") or []
            note = (
                f"引用校验警告：引用了未检索到的证据 {missing}"
                if missing
                else "本回答未能完成证据校对，请谨慎参考"
            )
            lines.append(f"> ⚠ {note}")
            lines.append("")

        _append_tool_trace(lines, turn.get("tool_trace") or [])

        for item in turn.get("evidence") or []:
            eid = item.get("evidence_id")
            if eid and eid not in sources:
                sources[eid] = item

    if sources:
        lines.append("---")
        lines.append("")
        lines.append("## 来源汇总")
        lines.append("")
        for eid, item in sources.items():
            title_ = item.get("title") or "Untitled"
            paper_id = item.get("paper_id") or ""
            doi = item.get("doi") or ""
            section = item.get("section") or ""
            path = item.get("source_path") or ""
            index_version = item.get("index_version")
            parts = [f"**[{eid}]** {title_}"]
            # paper_id is the canonical research-index identity (Block 0); keep it
            # in the audit trail alongside DOI and the index version it came from.
            if paper_id:
                parts.append(f"paper_id: {paper_id}")
            if doi:
                parts.append(f"DOI: {doi}")
            if section:
                parts.append(f"section: {section}")
            if index_version is not None:
                parts.append(f"index_version: {index_version}")
            if path:
                parts.append(f"source: `{path}`")
            lines.append("- " + " | ".join(parts))
        lines.append("")

    if answered == 0:
        lines.append("_本会话暂无可导出的问答记录。_")

    return "\n".join(lines)


_PERMISSION_LABEL = {
    "grounded": "证据充分（grounded）",
    "partially_grounded": "部分有证据支持（partially grounded）",
    "hypothesis": "主要为推断（hypothesis）",
    "conflicting": "证据存在冲突（conflicting）",
    "not_answerable": "本地库证据不足以作答（not answerable）",
}
_SUPPORT_LABEL = {
    "supported": "支持",
    "partially_supported": "部分支持",
    "unsupported": "无支持",
    "conflicting": "冲突",
    "inference": "推断",
}


def _append_tool_trace(lines: list[str], traces: list[dict[str, Any]]) -> None:
    """Block 4: render the per-turn tool-call trace so a turn can be replayed —
    call order, latency, result/error, and any artifact/job produced."""
    if not traces:
        return
    lines.append("<details><summary>工具执行轨迹</summary>")
    lines.append("")
    for t in traces:
        latency = t.get("latency_ms")
        latency_str = f"{latency}ms" if latency is not None else "n/a"
        if t.get("status") == "error":
            detail = f"失败（{t.get('error_code')}）"
            hint = t.get("recovery_hint")
            if hint:
                detail += f" — {hint}"
        else:
            detail = (t.get("result_summary") or "完成").strip()
            extras = []
            if t.get("artifacts_created"):
                extras.append(f"产物 {len(t['artifacts_created'])}")
            if t.get("jobs_created"):
                extras.append(f"任务 {len(t['jobs_created'])}")
            if extras:
                detail += f"（{', '.join(extras)}）"
        lines.append(f"- `{t.get('tool_name')}` · {t.get('permission_level') or '?'} · {latency_str} — {detail}")
    lines.append("")
    lines.append("</details>")
    lines.append("")


def _append_grounding(lines: list[str], citation: dict[str, Any]) -> None:
    """Block 3: render the FINAL-answer grounding transparency note for a turn.

    This EXPLAINS the answer (how strong the evidence is, why some wording is
    cautious, what was left out for lack of evidence). It is not a correction of the
    body — after a strict gate the body is already inside the evidence boundary.
    """
    grounding = citation.get("grounding")
    if not grounding:
        return
    summary = citation.get("grounding_summary") or {}
    permission = grounding.get("answer_permission")
    label = _PERMISSION_LABEL.get(permission, permission or "未知")
    bits = [f"Grounding：**{label}**"]
    total = summary.get("claims_total")
    if total:
        parts = [f"支持 {summary.get('supported', 0)}"]
        if summary.get("limited"):
            parts.append(f"受限 {summary['limited']}")
        if summary.get("conflicting"):
            parts.append(f"冲突 {summary['conflicting']}")
        if summary.get("unsupported"):  # only in warn mode (gate didn't rewrite)
            parts.append(f"无支持 {summary['unsupported']}")
        if summary.get("removed"):
            parts.append(f"略去 {summary['removed']}")
        bits.append(f"{total} 项结论中 " + " · ".join(parts))
    lines.append("> " + " — ".join(bits))
    for note in grounding.get("warnings") or []:
        lines.append(f"> 校对说明：{note}")
    for note in grounding.get("corpus_boundary_notes") or []:
        lines.append(f"> 边界：{note}")
    limited = [c for c in (grounding.get("claims") or []) if c.get("support_status") != "supported"]
    if limited:
        lines.append(">")
        lines.append("> 措辞较保守的结论：")
        for c in limited:
            tag = _SUPPORT_LABEL.get(c.get("support_status"), c.get("support_status") or "?")
            scope = f"（{c['scope_notes']}）" if c.get("scope_notes") else ""
            lines.append(f"> - [{tag}] {c.get('claim') or ''}{scope}")
    removed = grounding.get("removed_claims") or []
    if removed:
        lines.append(">")
        lines.append("> 因本地库无证据支持，未纳入正文：")
        for c in removed:
            scope = f"（{c['scope_notes']}）" if c.get("scope_notes") else ""
            lines.append(f"> - {c.get('claim') or ''}{scope}")
    lines.append("")


def report_filename(record: dict[str, Any]) -> str:
    session = record.get("session") or {}
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(record.get("generated_at") or time.time()))
    raw = (session.get("title") or "research-record").strip()
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in raw)[:40].strip("-") or "research-record"
    return f"{safe}-{stamp}.md"
