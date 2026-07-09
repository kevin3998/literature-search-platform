import React, { useState } from "react";
import clsx from "clsx";
import { X } from "lucide-react";

// Block 2 §13: developer-only Retrieval Inspector. Shows the full acquisition
// packet — intent, rewrites, retrieval path, fallback, coverage, breadth, the
// evidence candidate table, and raw JSON. Opened explicitly (never part of the
// default chat flow). Accepts either a full acquire-evidence packet or an object
// assembled from chat events.

function normalizeCandidates(data) {
  if (Array.isArray(data.evidence_candidates) && data.evidence_candidates.length) {
    return data.evidence_candidates;
  }
  // Fall back to flattening paper cards (chat path).
  const out = [];
  for (const paper of data.results || data.papers || []) {
    for (const ev of paper.evidence || []) {
      out.push({
        evidence_id: ev.evidence_id,
        paper_id: paper.paper_id,
        doi: paper.doi,
        title: paper.title,
        year: paper.year,
        journal: paper.journal || paper.venue,
        section: ev.section,
        kind: ev.kind,
        snippet: ev.snippet || ev.text,
        in_llm_context: true,
      });
    }
  }
  return out;
}

// Group flattened candidates by their paper so a multi-evidence paper appears
// once, with its evidence nested underneath (no repeated titles).
function groupByPaper(cands) {
  const groups = [];
  const byKey = new Map();
  for (const c of cands) {
    const key = c.paper_id || c.doi || c.title || c.evidence_id;
    let g = byKey.get(key);
    if (!g) {
      g = { key, title: c.title, year: c.year, journal: c.journal, items: [] };
      byKey.set(key, g);
      groups.push(g);
    }
    g.items.push(c);
  }
  return groups;
}

function clampSnippet(text, n = 200) {
  if (!text) return "";
  const t = String(text).replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

function Badge({ children, tone = "ink" }) {
  return (
    <span
      className={clsx(
        "inline-block rounded px-1.5 py-0.5 text-[10.5px] font-mono",
        tone === "amber" && "bg-amber-50 text-amber-700 border border-amber-200",
        tone === "red" && "bg-red-50 text-red-600 border border-red-200",
        tone === "ink" && "bg-paper-100 text-ink-600 border border-line"
      )}
    >
      {children}
    </span>
  );
}

function Section({ title, children }) {
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-3.5">
      <h3 className="font-serif text-[14px] text-ink-900 mb-2">{title}</h3>
      {children}
    </section>
  );
}

function KV({ k, v }) {
  if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) return null;
  return (
    <div className="flex gap-2 text-[12px] py-0.5">
      <span className="text-ink-500 font-mono min-w-[150px]">{k}</span>
      <span className="text-ink-800 break-words">{Array.isArray(v) ? v.join(" · ") : String(v)}</span>
    </div>
  );
}

export default function RetrievalInspector({ data, onClose }) {
  const [rawOpen, setRawOpen] = useState(false);
  const plan = data.query_plan || {};
  const coverage = data.coverage || {};
  const breadth = data.breadth || coverage.breadth || {};
  const fallback = data.fallback_reason || null;
  const candidates = normalizeCandidates(data);
  const groups = groupByPaper(candidates);
  const warnings = plan.warnings || [];
  const vectorReason = plan.underlying?.vector_unavailable_reason || data.vector_unavailable_reason;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30 p-6" onClick={onClose}>
      <div
        className="bg-paper-50 rounded-xl border border-line w-full max-w-4xl max-h-[88vh] flex flex-col shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div className="font-serif text-[16px] text-ink-900">检索检查器</div>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-900"><X size={18} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge>意图: {data.query_intent?.type || plan.query_intent || "?"}</Badge>
            <Badge>请求方式: {plan.retrieval_requested || "?"}</Badge>
            <Badge>实际使用: {data.retrieval_used || plan.final_retrieval_used || "?"}</Badge>
            {coverage.status && (
              <Badge tone={coverage.status === "none" ? "red" : coverage.status === "sufficient" ? "ink" : "amber"}>
                coverage: {coverage.status}
              </Badge>
            )}
            {breadth.breadth_limited && <Badge tone="amber">广度受限</Badge>}
            {breadth.deep_research_suggested && <Badge tone="amber">建议深度研究</Badge>}
            {warnings.map((w) => <Badge key={w} tone="amber">{w}</Badge>)}
          </div>

          <Section title="覆盖度">
            <KV k="status" v={coverage.status} />
            <KV k="distinct_paper_count" v={coverage.distinct_paper_count} />
            <KV k="evidence_count" v={coverage.evidence_count} />
            <KV k="missing_aspects" v={coverage.missing_aspects} />
            {(coverage.coverage_notes || coverage.notes || []).map((n, i) => (
              <div key={i} className="text-[11.5px] text-ink-500 mt-1">· {n}</div>
            ))}
          </Section>

          {(breadth.candidate_paper_count != null || breadth.estimated_total_matches != null) && (
            <Section title="广度与上下文预算">
              <KV k="candidate_paper_count" v={breadth.candidate_paper_count} />
              <KV k="candidate_evidence_count" v={breadth.candidate_evidence_count} />
              <KV k="selected_evidence_count" v={breadth.selected_evidence_count} />
              <KV k="llm_context_evidence_count" v={breadth.llm_context_evidence_count} />
              <KV
                k="estimated_total_matches"
                v={breadth.estimated_total_matches != null ? `${breadth.estimated_total_matches}${breadth.estimate_is_lower_bound ? "+ (lower bound)" : ""}` : null}
              />
              <KV k="clusters_covered" v={breadth.clusters_covered} />
              <KV k="missing_clusters" v={breadth.missing_clusters} />
              <KV k="cluster_method" v={breadth.cluster_method} />
            </Section>
          )}

          <Section title="查询计划">
            <KV k="original_query" v={plan.original_query} />
            <KV k="rewritten_queries" v={plan.rewritten_queries} />
            <KV k="retrieval_steps" v={plan.retrieval_steps} />
            <KV k="fallback_steps" v={plan.fallback_steps} />
            <KV k="filters_requested" v={plan.filters_requested && JSON.stringify(plan.filters_requested)} />
            <KV k="vector_unavailable" v={vectorReason} />
            {fallback && (
              <div className="mt-1.5 text-[11.5px] text-ink-600">
                fallback: <span className="font-mono text-amber-700">{fallback.code}</span> — {fallback.message}
              </div>
            )}
          </Section>

          <Section title={`证据候选 · ${candidates.length} 条 / ${groups.length} 篇`}>
            {candidates.length === 0 ? (
              <div className="text-[12px] text-ink-400">无候选证据。</div>
            ) : (
              <div className="space-y-3.5">
                {groups.map((g) => (
                  <div key={g.key}>
                    <div className="flex items-baseline flex-wrap gap-x-2 text-[13px]">
                      <span className="font-medium text-ink-900">{g.title || "未命名文献"}</span>
                      {g.year ? <span className="text-ink-400 text-[11.5px]">· {g.year}</span> : null}
                      {g.journal ? <span className="text-ink-400 text-[11.5px]">· {g.journal}</span> : null}
                      <span className="text-ink-400 text-[11.5px]">· {g.items.length} 条证据</span>
                    </div>
                    <ul className="mt-1.5 space-y-2 border-l-2 border-line pl-3">
                      {g.items.map((c, i) => (
                        <li key={c.evidence_id || i} className={clsx(c.in_llm_context === false && "opacity-45")}>
                          <div className="text-[11.5px]">
                            <span className="font-mono text-amber-600">[{c.evidence_id}]</span>
                            {c.section ? <span className="text-ink-500"> · {c.section}</span> : null}
                            {c.kind ? <span className="text-ink-400"> · {c.kind}</span> : null}
                          </div>
                          {c.snippet ? (
                            <div className="text-[12px] text-ink-600 mt-0.5 leading-snug">{clampSnippet(c.snippet)}</div>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Section>

          <div>
            <button onClick={() => setRawOpen((v) => !v)} className="text-[11.5px] text-ink-500 hover:text-amber-600">
              {rawOpen ? "▴ 隐藏" : "▾ 显示"} raw packet JSON
            </button>
            {rawOpen && <pre className="result-pre mt-2 max-h-[40vh] overflow-auto">{JSON.stringify(data, null, 2)}</pre>}
          </div>
        </div>
      </div>
    </div>
  );
}
