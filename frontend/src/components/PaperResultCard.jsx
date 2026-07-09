import React from "react";
import clsx from "clsx";
import { FileText, ExternalLink } from "lucide-react";

export default function PaperResultCard({ paper, onClick, selected = false, compact = false }) {
  const pct = paper.relevance_score != null ? Math.round(paper.relevance_score * 100) : null;
  const Wrapper = onClick ? "button" : "div";

  return (
    <Wrapper
      onClick={onClick}
      className={clsx(
        "w-full rounded-lg border bg-paper-0 text-left transition-colors",
        compact ? "p-3" : "p-4 shadow-card",
        selected ? "border-amber shadow-card" : "border-line",
        onClick && "hover:border-amber/70"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className={clsx("font-serif leading-snug text-ink-900", compact ? "text-[13.5px] line-clamp-2" : "text-[14.5px]")}>
          {paper.title}
        </h3>
        {pct != null && (
          <div className="flex-shrink-0 flex items-center gap-1.5 mt-0.5">
            <div className="w-10 h-1.5 rounded-full bg-line overflow-hidden">
              <div className="h-full bg-amber" style={{ width: `${pct}%` }} />
            </div>
            <span className="font-mono text-[10.5px] text-amber-600">{pct}%</span>
          </div>
        )}
      </div>

      <div className="font-mono text-[11px] text-ink-500 mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5">
        {paper.authors?.length > 0 && <span>{paper.authors.slice(0, 3).join(", ")}{paper.authors.length > 3 ? " 等" : ""}</span>}
        {paper.year && <span>· {paper.year}</span>}
        {paper.venue && <span>· {paper.venue}</span>}
        {paper.citation_count != null && <span>· 被引 {paper.citation_count}</span>}
      </div>

      {(paper.snippet || paper.abstract) && (
        <p className={clsx("text-ink-700 leading-relaxed line-clamp-3", compact ? "text-[12px] mt-2" : "text-[12.5px] mt-2.5")}>
          {paper.snippet || paper.abstract}
        </p>
      )}

      {paper.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          {paper.tags.map((t) => (
            <span key={t} className="text-[10.5px] px-2 py-0.5 rounded-full bg-teal-50 text-teal">
              {t}
            </span>
          ))}
        </div>
      )}

      {paper.evidence?.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {paper.evidence.slice(0, 2).map((ev) => (
            <div key={ev.evidence_id || ev.source_path} className="rounded-md bg-paper-50 border border-line px-2.5 py-2">
              <div className="font-mono text-[10px] text-ink-500">
                {ev.evidence_id || "evidence"} · {ev.kind || "source"} · {ev.confidence || "unknown"}
              </div>
              <div className="text-[11.5px] text-ink-700 leading-relaxed mt-1 line-clamp-2">
                {ev.snippet || ev.text}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3 pt-2.5 border-t border-line">
        {paper.source_path && (
          <span className="flex items-center gap-1 text-[11px] text-ink-500 truncate">
            <FileText size={12} className="flex-shrink-0" />
            <span className="truncate">{paper.source_path.split("/").pop()}</span>
          </span>
        )}
        {paper.url && onClick && (
          <span className="flex items-center gap-1 text-[11px] text-amber-600 ml-auto flex-shrink-0">
            查看详情 <ExternalLink size={11} />
          </span>
        )}
        {paper.url && !onClick && (
          <a
            href={paper.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-[11px] text-amber-600 hover:underline ml-auto flex-shrink-0"
          >
            查看原文 <ExternalLink size={11} />
          </a>
        )}
      </div>
    </Wrapper>
  );
}
