import React, { useEffect, useState } from "react";
import { Download, FileClock, X } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

const ROLE_LABEL = { retrieval: "检索", evidence: "证据", analysis: "分析", synthesis: "综合", report: "报告" };

// Read-only audit drawer: shows the per-turn chain question → retrieval → evidence → artifacts,
// assembled by GET /api/sessions/{id}/record.
export default function AuditRecordModal({ onClose }) {
  const loadRecord = useAppStore((s) => s.loadActiveRecord);
  const exportSession = useAppStore((s) => s.exportActiveSession);
  const [record, setRecord] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    loadRecord()
      .then((r) => alive && setRecord(r))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [loadRecord]);

  const turns = (record?.turns || []).filter((t) => t.query || t.answer);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink-900/30" onClick={onClose}>
      <div className="w-[460px] max-w-[92vw] h-full bg-paper-0 border-l border-line flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2 font-serif text-[16px] text-ink-900">
            <FileClock size={16} /> 研究记录
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-light inline-flex items-center gap-1.5 text-[12.5px]" onClick={exportSession}>
              <Download size={13} /> 导出
            </button>
            <button className="text-ink-400 hover:text-ink-900 p-1" onClick={onClose} aria-label="关闭"><X size={16} /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{error}</div>}
          {!record && !error && <div className="text-[13px] text-ink-500">正在加载…</div>}
          {record && turns.length === 0 && <div className="text-[13px] text-ink-500">本会话暂无可审计的问答记录。</div>}

          {turns.map((turn, i) => (
            <div key={turn.turn_id || i} className="rounded-lg border border-line bg-paper-50 p-3">
              <div className="text-[13.5px] text-ink-900 font-medium">
                {i + 1}. {turn.query || "（无问题）"}
                {turn.role && turn.role !== "general" && (
                  <span className="ml-2 rounded-full bg-amber-50 border border-amber-200 px-1.5 py-0 text-[10px] text-amber-700 font-normal">
                    {ROLE_LABEL[turn.role] || turn.role}
                  </span>
                )}
              </div>

              {turn.searches?.length > 0 && (
                <div className="mt-2 text-[11.5px] text-ink-500">
                  检索：{turn.searches.map((s, k) => (
                    <span key={k} className="font-mono">{s.query}（{s.retrieval_used || "n/a"}·{s.result_count}）{k < turn.searches.length - 1 ? "，" : ""}</span>
                  ))}
                </div>
              )}

              {turn.citation?.status === "warning" && (
                <div className="mt-2 text-[11.5px] text-red-600">
                  ⚠ 引用校验：{turn.citation.missing_ids?.length ? `未找到证据 ${turn.citation.missing_ids.join(", ")}` : "有证据未标注引用"}
                </div>
              )}

              {turn.evidence?.length > 0 && (
                <div className="mt-2">
                  <div className="text-[11px] text-ink-400 mb-1">证据 {turn.evidence.length} 条</div>
                  <ul className="space-y-1">
                    {turn.evidence.slice(0, 8).map((e, k) => (
                      <li key={k} className="text-[11.5px] leading-snug border-l-2 border-line pl-2">
                        <span className="text-amber-600 font-medium">[{e.evidence_id}]</span>{" "}
                        <span className="text-ink-700">{e.title || e.doi || "证据"}</span>
                        {e.source_path && <div className="font-mono text-[10.5px] text-ink-400">{e.source_path}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {turn.artifacts?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {turn.artifacts.map((a, k) => (
                    <span key={k} className="rounded-full bg-paper-100 border border-line px-2 py-0.5 text-[10.5px] font-mono text-ink-600">
                      {a.artifact_type}: {a.title || a.artifact_id}
                    </span>
                  ))}
                </div>
              )}

              {turn.tool_trace?.length > 0 && (
                <div className="mt-2">
                  <div className="text-[11px] text-ink-400 mb-1">执行轨迹 {turn.tool_trace.length} 步</div>
                  <ul className="space-y-0.5">
                    {turn.tool_trace.map((t, k) => (
                      <li key={t.tool_call_id || k} className="text-[10.5px] font-mono flex items-center gap-2">
                        <span className={t.status === "error" ? "text-red-600 font-medium" : "text-ink-700 font-medium"}>{t.tool_name}</span>
                        <span className="text-ink-400">{t.permission_level || "?"}</span>
                        {t.latency_ms != null && <span className="text-ink-400">{t.latency_ms}ms</span>}
                        <span className={t.status === "error" ? "text-red-600 truncate" : "text-ink-500 truncate"}>
                          {t.status === "error" ? t.error_code : t.result_summary}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
