import React, { useEffect, useState } from "react";
import { Layers, X, RefreshCw, Plus, Pencil, Check } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

// Block 6a/6b: Shared Research State drawer for a 课题. Derived projections
// (evidence pool / coverage gaps) are read-only; candidate-paper status and the
// authored facts (objective / stage / open questions / excluded directions) are
// editable — every edit is persisted with provenance via the curation endpoints.

const STATUS_LABEL = {
  candidate: "候选",
  accepted: "保留",
  excluded: "排除",
  needs_review: "待复核",
};
const STATUS_STYLE = {
  candidate: "bg-paper-100 border-line text-ink-600",
  accepted: "bg-emerald-50 border-emerald-200 text-emerald-700",
  excluded: "bg-ink-100 border-line text-ink-400 line-through",
  needs_review: "bg-amber-50 border-amber-200 text-amber-700",
};
const CURATE_ACTIONS = [
  ["accepted", "保留"],
  ["excluded", "排除"],
  ["needs_review", "待复核"],
];
const STAGES = ["retrieval", "evidence curation", "analysis", "synthesis", "report"];
const STAGE_LABEL = {
  retrieval: "检索",
  "evidence curation": "证据整理",
  analysis: "分析",
  synthesis: "综合",
  report: "报告",
};

function Section({ title, count, children }) {
  return (
    <div className="rounded-lg border border-line bg-paper-50 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[12px] font-medium text-ink-700">{title}</div>
        {count != null && <div className="text-[11px] text-ink-400">{count}</div>}
      </div>
      {children}
    </div>
  );
}

// An editable string list: each item removable, with an inline add box.
function EditableList({ items, empty, placeholder, onChange }) {
  const [draft, setDraft] = useState("");
  const list = items || [];
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    onChange([...list, v]);
    setDraft("");
  };
  return (
    <div>
      {list.length === 0 ? (
        <div className="text-[12px] text-ink-400 mb-1.5">{empty}</div>
      ) : (
        <ul className="space-y-1 mb-1.5">
          {list.map((it, i) => (
            <li key={i} className="group flex items-start gap-1.5 text-[12px] leading-snug text-ink-700 border-l-2 border-line pl-2">
              <span className="flex-1">{it}</span>
              <button
                className="text-ink-300 hover:text-red-500 opacity-0 group-hover:opacity-100"
                onClick={() => onChange(list.filter((_, k) => k !== i))}
                aria-label="移除"
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-1">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder={placeholder}
          className="flex-1 rounded border border-line bg-paper-0 px-2 py-1 text-[12px] outline-none focus:border-ink-400"
        />
        <button className="btn-light p-1" onClick={add} aria-label="添加"><Plus size={13} /></button>
      </div>
    </div>
  );
}

export default function ResearchStatePanel({ onClose }) {
  const state = useAppStore((s) => {
    const sid = s.activeSessionByModule[s.activeModuleId];
    return s.sessionsById[sid]?.researchState;
  });
  const loadResearchState = useAppStore((s) => s.loadResearchState);
  const setPaperStatus = useAppStore((s) => s.setPaperStatus);
  const setEvidenceStatus = useAppStore((s) => s.setEvidenceStatus);
  const updateResearchState = useAppStore((s) => s.updateResearchState);
  const [refreshing, setRefreshing] = useState(false);
  const [editingObjective, setEditingObjective] = useState(false);
  const [objectiveDraft, setObjectiveDraft] = useState("");

  useEffect(() => {
    loadResearchState();
  }, [loadResearchState]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadResearchState();
    } finally {
      setRefreshing(false);
    }
  };

  const saveObjective = async () => {
    // send "" (not null) so an emptied field actually clears — exclude_none on
    // the backend would otherwise drop a null and leave the old objective.
    await updateResearchState({ objective: objectiveDraft.trim() });
    setEditingObjective(false);
  };

  const papers = state?.candidate_papers || [];
  const counts = state?.paper_status_counts || {};
  const pool = state?.evidence_pool || { total: 0, by_confidence: {}, status_counts: {}, recent: [] };
  const gaps = state?.coverage_gaps || {};
  const stage = state?.stage || "retrieval";

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink-900/30" onClick={onClose}>
      <div
        className="w-[440px] max-w-[92vw] h-full bg-paper-0 border-l border-line flex flex-col shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2 font-serif text-[16px] text-ink-900">
            <Layers size={16} /> 研究状态
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn-light inline-flex items-center gap-1.5 text-[12.5px]"
              onClick={handleRefresh}
              disabled={refreshing}
              title="刷新研究状态"
            >
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} /> 刷新
            </button>
            <button className="text-ink-400 hover:text-ink-900 p-1" onClick={onClose} aria-label="关闭">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {!state && <div className="text-[13px] text-ink-500">正在加载…</div>}

          {state && (
            <>
              {/* 课题主题 / 目标 / 阶段 */}
              <div className="rounded-lg border border-line bg-paper-50 p-3">
                <div className="text-[14px] text-ink-900 font-medium">{state.topic || "未命名课题"}</div>

                {editingObjective ? (
                  <div className="mt-1.5">
                    <textarea
                      value={objectiveDraft}
                      onChange={(e) => setObjectiveDraft(e.target.value)}
                      rows={2}
                      placeholder="本课题的研究目标…"
                      className="w-full rounded border border-line bg-paper-0 px-2 py-1 text-[12.5px] outline-none focus:border-ink-400"
                    />
                    <div className="mt-1 flex gap-1.5">
                      <button className="btn-light inline-flex items-center gap-1 text-[11.5px]" onClick={saveObjective}>
                        <Check size={12} /> 保存
                      </button>
                      <button className="text-[11.5px] text-ink-400 px-2" onClick={() => setEditingObjective(false)}>取消</button>
                    </div>
                  </div>
                ) : (
                  <button
                    className="group mt-1 flex items-start gap-1 text-left"
                    onClick={() => {
                      setObjectiveDraft(state.objective || "");
                      setEditingObjective(true);
                    }}
                  >
                    <span className={`text-[12.5px] leading-snug ${state.objective ? "text-ink-600" : "text-ink-400"}`}>
                      {state.objective || "设定研究目标…"}
                    </span>
                    <Pencil size={11} className="mt-0.5 text-ink-300 opacity-0 group-hover:opacity-100" />
                  </button>
                )}

                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-600">
                  <span>当前阶段</span>
                  <select
                    value={stage}
                    onChange={(e) => updateResearchState({ stage: e.target.value })}
                    className="rounded border border-line bg-paper-0 px-1.5 py-0.5 text-[11px] outline-none focus:border-ink-400"
                  >
                    {STAGES.map((st) => (
                      <option key={st} value={st}>{STAGE_LABEL[st] || st}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* 候选论文（派生 + 可策展状态） */}
              <Section title="候选论文" count={papers.length}>
                {papers.length === 0 ? (
                  <div className="text-[12px] text-ink-400">尚未检索到论文。</div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {Object.entries(counts).map(([st, n]) => (
                        <span key={st} className={`rounded-full border px-2 py-0.5 text-[10.5px] ${STATUS_STYLE[st] || STATUS_STYLE.candidate}`}>
                          {STATUS_LABEL[st] || st} {n}
                        </span>
                      ))}
                    </div>
                    <ul className="space-y-2">
                      {papers.slice(0, 30).map((p, i) => (
                        <li key={p.key || i} className="text-[12px] leading-snug">
                          <div className="flex items-start gap-2">
                            <span className={`mt-0.5 shrink-0 rounded-full border px-1.5 py-0 text-[10px] ${STATUS_STYLE[p.status] || STATUS_STYLE.candidate}`}>
                              {STATUS_LABEL[p.status] || p.status}
                            </span>
                            <span className="text-ink-700">
                              {p.title || p.doi || p.paper_id || "（无标题）"}
                              <span className="text-ink-400"> · 证据 {p.evidence_count}</span>
                            </span>
                          </div>
                          <div className="mt-1 flex gap-1 pl-7">
                            {CURATE_ACTIONS.map(([st, label]) => (
                              <button
                                key={st}
                                onClick={() => setPaperStatus(p.key || p.paper_id || p.doi, p.status === st ? "candidate" : st)}
                                className={`rounded border px-1.5 py-0.5 text-[10px] transition ${
                                  p.status === st ? STATUS_STYLE[st] : "border-line text-ink-400 hover:text-ink-700 hover:border-ink-300"
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </Section>

              {/* 证据池（派生 + 会话内策展状态） */}
              <Section title="证据池" count={pool.total}>
                {pool.total === 0 ? (
                  <div className="text-[12px] text-ink-400">暂无证据。</div>
                ) : (
                  <>
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {Object.entries(pool.status_counts || {}).map(([st, n]) => (
                        <span key={st} className={`rounded-full border px-2 py-0.5 text-[10.5px] ${STATUS_STYLE[st] || STATUS_STYLE.candidate}`}>
                          {STATUS_LABEL[st] || st} {n}
                        </span>
                      ))}
                      {Object.entries(pool.by_confidence || {}).map(([c, n]) => (
                        <span key={c} className="rounded-full bg-paper-100 border border-line px-2 py-0.5 text-[10.5px] text-ink-600">
                          {c} {n}
                        </span>
                      ))}
                    </div>
                    <ul className="space-y-2">
                      {(pool.recent || []).slice(0, 30).map((ev, i) => (
                        <li key={ev.evidence_item_id || i} className="text-[12px] leading-snug">
                          <div className="flex items-start gap-2">
                            <span className={`mt-0.5 shrink-0 rounded-full border px-1.5 py-0 text-[10px] ${STATUS_STYLE[ev.status] || STATUS_STYLE.candidate}`}>
                              {STATUS_LABEL[ev.status] || ev.status || "候选"}
                            </span>
                            <span className="min-w-0 flex-1 text-ink-700">
                              <span className="line-clamp-2">{ev.title || ev.evidence_id || "证据片段"}</span>
                              {(ev.snippet || ev.text) && <span className="mt-0.5 block line-clamp-2 text-ink-500">{ev.snippet || ev.text}</span>}
                              {ev.note && <span className="mt-0.5 block text-ink-500">备注：{ev.note}</span>}
                            </span>
                          </div>
                          <div className="mt-1 flex gap-1 pl-7">
                            {CURATE_ACTIONS.map(([st, label]) => (
                              <button
                                key={st}
                                onClick={() => setEvidenceStatus(ev.evidence_item_id, ev.status === st ? "candidate" : st)}
                                className={`rounded border px-1.5 py-0.5 text-[10px] transition ${
                                  ev.status === st ? STATUS_STYLE[st] : "border-line text-ink-400 hover:text-ink-700 hover:border-ink-300"
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                            <button
                              onClick={() => {
                                const note = window.prompt("为这条证据添加备注", ev.note || "");
                                if (note != null) setEvidenceStatus(ev.evidence_item_id, ev.status || "candidate", note);
                              }}
                              className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-400 transition hover:border-ink-300 hover:text-ink-700"
                            >
                              备注
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </Section>

              {/* 覆盖缺口（派生，只读） */}
              {gaps.coverage && (
                <Section title="覆盖缺口">
                  <div className="text-[12px] text-ink-700 leading-snug">
                    {gaps.coverage.sufficient === false ? (
                      <span className="text-amber-700">证据可能不足{gaps.coverage.missing?.length ? `：${gaps.coverage.missing.join("、")}` : ""}</span>
                    ) : (
                      <span className="text-emerald-700">最近一轮覆盖判断为充分</span>
                    )}
                    {gaps.from_query && <div className="text-[10.5px] text-ink-400 mt-1 font-mono">来自：{gaps.from_query}</div>}
                  </div>
                </Section>
              )}

              {/* 被授权的事实（可编辑） */}
              <Section title="待解决问题">
                <EditableList
                  items={state.open_questions}
                  empty="暂无。添加后，“继续”时会优先处理。"
                  placeholder="新增待解决问题…"
                  onChange={(open_questions) => updateResearchState({ open_questions })}
                />
              </Section>

              <Section title="已排除方向">
                <EditableList
                  items={state.excluded_directions}
                  empty="暂无。排除后，后续检索会避开。"
                  placeholder="新增排除方向…"
                  onChange={(excluded_directions) => updateResearchState({ excluded_directions })}
                />
              </Section>

              <Section title="下一步行动">
                <EditableList
                  items={state.next_actions}
                  empty="暂无。添加后会作为后续研究提醒。"
                  placeholder="新增下一步行动…"
                  onChange={(next_actions) => updateResearchState({ next_actions })}
                />
              </Section>

              {/* 当前产物（只读） */}
              {state.active_artifact && (
                <Section title="当前产物">
                  <div className="text-[12px] text-ink-700">
                    <span className="font-mono text-ink-500">{state.active_artifact.artifact_type}</span> ·{" "}
                    {state.active_artifact.title || state.active_artifact.artifact_id}
                  </div>
                </Section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
