import React from "react";
import clsx from "clsx";
import { CheckCircle2, FileText, Layers3, SearchCheck, ShieldCheck, TriangleAlert } from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import {
  buildAuditItems,
  buildEvidenceSummary,
  buildFilteredEvidenceItems,
  buildPaperItems,
  buildPaperSummary,
  detailValueText,
  evidenceCitationAlias,
  evidenceInternalIds,
} from "./literatureSearchViewModel";
import { citationOrdinalLabel, evidenceIdLabel } from "./citationLabels.js";

const TABS = [
  ["evidence", "证据", Layers3],
  ["papers", "文献", FileText],
  ["audit", "审计", ShieldCheck],
];

const SEVERITY_META = {
  ok: ["通过", CheckCircle2, "text-emerald-700 bg-emerald-50 border-emerald-100"],
  info: ["记录", SearchCheck, "text-ink-600 bg-paper-100 border-line"],
  warning: ["注意", TriangleAlert, "text-amber-700 bg-amber-50 border-amber-200"],
  error: ["失败", TriangleAlert, "text-red-700 bg-red-50 border-red-200"],
};

const STATUS_LABEL = {
  candidate: "候选",
  accepted: "已保留",
  excluded: "已排除",
  needs_review: "待复核",
};

const STATUS_STYLE = {
  candidate: "text-ink-600 bg-paper-100 border-line",
  accepted: "text-emerald-700 bg-emerald-50 border-emerald-200",
  excluded: "text-ink-400 bg-ink-100 border-line line-through",
  needs_review: "text-amber-700 bg-amber-50 border-amber-200",
};

const EVIDENCE_FILTERS = [
  ["current", "本轮"],
  ["pool", "证据池"],
  ["accepted", "已保留"],
  ["needs_review", "待复核"],
  ["excluded", "已排除"],
];

const CURATION_ACTIONS = [
  ["accepted", "保留"],
  ["excluded", "排除"],
  ["needs_review", "待复核"],
];

function evidenceCardLocatorLabel(item) {
  const alias = evidenceCitationAlias(item);
  if (alias) {
    return [citationOrdinalLabel(alias), detailValueText(item.source_path, "")].filter(Boolean).join(" · ");
  }
  return evidenceIdLabel(evidenceInternalIds(item).join(", ") || item.evidenceItemId || detailValueText(item.source_path, ""));
}

export default function ResultsPanel() {
  const rightPanelTab = useAppStore((s) => s.rightPanelTab);
  const setRightPanelTab = useAppStore((s) => s.setRightPanelTab);
  const selectEvidence = useAppStore((s) => s.selectLiteratureEvidence);
  const selectPaper = useAppStore((s) => s.selectLiteraturePaper);
  const selectAudit = useAppStore((s) => s.selectLiteratureAudit);
  const setEvidenceStatus = useAppStore((s) => s.setEvidenceStatus);
  const setPaperStatus = useAppStore((s) => s.setPaperStatus);
  const setEvidenceFilter = useAppStore((s) => s.setLiteratureEvidenceFilter);
  const setChatResearchMode = useAppStore((s) => s.setChatResearchMode);
  const selectAnswer = useAppStore((s) => s.selectLiteratureAnswer);
  const preview = useAppStore((s) => s.literatureSearch.preview);
  const evidenceFilter = useAppStore((s) => s.literatureSearch.evidenceFilter || "current");
  const session = useAppStore((s) => {
    const sid = s.activeSessionByModule[s.activeModuleId];
    return s.sessionsById[sid];
  });

  const evidence = buildFilteredEvidenceItems(session, evidenceFilter);
  const evidenceSummary = buildEvidenceSummary(session);
  const papers = buildPaperItems(session);
  const paperSummary = buildPaperSummary(session);
  const audits = buildAuditItems(session);
  const handleSuggestion = (action) => runSuggestedAction(action, {
    setChatResearchMode,
    selectAnswer,
    setRightPanelTab,
    setEvidenceFilter,
  });

  return (
    <aside className="w-full lg:w-[380px] flex-shrink-0 border-t lg:border-t-0 lg:border-l border-line bg-paper-50 flex flex-col h-[42vh] lg:h-full min-h-[260px] lg:min-h-0">
      <div className="px-4 pt-4">
        <div className="inline-flex w-full rounded-lg border border-line bg-paper-0 p-0.5">
          {TABS.map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setRightPanelTab(key)}
              className={clsx(
                "flex-1 inline-flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors",
                rightPanelTab === key ? "bg-ink-900 text-paper-50" : "text-ink-500 hover:bg-paper-100 hover:text-ink-900"
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {rightPanelTab === "evidence" && (
          <EvidenceTab
            items={evidence}
            filter={evidenceFilter}
            summary={evidenceSummary}
            onFilter={setEvidenceFilter}
            onStatus={setEvidenceStatus}
            selectedId={preview.mode === "evidence" ? preview.selectedEvidenceId : null}
            onSelect={selectEvidence}
          />
        )}
        {rightPanelTab === "papers" && (
          <PapersTab
            items={papers}
            summary={paperSummary}
            onStatus={setPaperStatus}
            selectedId={preview.mode === "paper" ? preview.selectedPaperId : null}
            onSelect={selectPaper}
          />
        )}
        {rightPanelTab === "audit" && (
          <AuditTab
            items={audits}
            selectedId={preview.mode === "audit" ? preview.selectedAuditId : null}
            onSelect={selectAudit}
            onSuggestion={handleSuggestion}
          />
        )}
      </div>
    </aside>
  );
}

function EvidenceTab({ items, filter, summary, selectedId, onSelect, onFilter, onStatus }) {
  if (!items.length) {
    return (
      <div className="space-y-2.5">
        <EvidenceSummary summary={summary} />
        <FilterBar filters={EVIDENCE_FILTERS} active={filter} onChange={onFilter} />
        <EmptyState
          title="暂无正式文献证据"
          text={items.summary?.emptyReason || "完成一次带引用的回答后，本轮回答实际使用的文献证据会显示在这里。"}
        />
      </div>
    );
  }
  return (
    <div className="space-y-2.5">
      <EvidenceSummary summary={summary} />
      <FilterBar filters={EVIDENCE_FILTERS} active={filter} onChange={onFilter} />
      {items.map((item) => (
        <div
          key={item.id}
          onClick={() => onSelect(item.id)}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") onSelect(item.id);
          }}
          className={clsx(
            "w-full cursor-pointer text-left rounded-lg border bg-paper-0 p-3 transition-colors",
            selectedId === item.id ? "border-amber shadow-card" : "border-line hover:border-amber/70"
          )}
        >
          <div className="flex items-start gap-2">
            <span className="mt-0.5 flex-shrink-0 inline-flex min-w-[22px] h-[20px] items-center justify-center rounded-md bg-amber-50 text-amber-700 text-[11px] font-medium">
              {citationOrdinalLabel(item.ordinal)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-serif text-[13.5px] leading-snug text-ink-900 line-clamp-2">
                {item.title || item.doi || "证据片段"}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <StatusBadge status={item.status || "candidate"} />
                {item.isCurrent && <span className="rounded-full border border-amber-100 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">本轮</span>}
                {item.confidence && <span className="text-[10.5px] text-ink-400">{item.confidence}</span>}
              </div>
              {item.section && <div className="mt-1 text-[11px] text-ink-400">{item.section}</div>}
              {(item.snippet || item.text) && (
                <p className="mt-2 text-[12px] leading-relaxed text-ink-600 line-clamp-3">
                  {item.snippet || item.text}
                </p>
              )}
              <div className="mt-2 font-mono text-[10.5px] text-ink-400 truncate">
                {evidenceCardLocatorLabel(item)}
              </div>
              {item.note && <div className="mt-1 text-[11px] text-ink-500 line-clamp-2">备注：{item.note}</div>}
              <CurationButtons
                current={item.status || "candidate"}
                disabled={!item.evidenceItemId && !item.evidence_item_id}
                disabledTitle="这条引用还没有稳定的会话证据 ID，暂不能策展。"
                onSet={(status) => onStatus(item.evidenceItemId || item.evidence_item_id, status)}
                onNote={() => {
                  const note = window.prompt("为这条证据添加备注", item.note || "");
                  if (note != null) onStatus(item.evidenceItemId || item.evidence_item_id, item.status || "candidate", note);
                }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function PapersTab({ items, summary, selectedId, onSelect, onStatus }) {
  if (!items.length) {
    return (
      <EmptyState
        title="暂无检索文献"
        text={items.summary?.emptyReason || "提出问题后，系统检索到的候选文献会显示在这里。"}
      />
    );
  }
  return (
    <div className="space-y-2.5">
      <PaperSummary summary={summary} />
      {items.map((paper) => (
        <PaperCard
          key={paper.id}
          paper={paper}
          selected={selectedId === paper.id}
          onSelect={onSelect}
          onStatus={onStatus}
        />
      ))}
    </div>
  );
}

function AuditTab({ items, selectedId, onSelect, onSuggestion }) {
  if (!items.length) {
    return (
      <EmptyState
        title="暂无审计记录"
        text="回答完成后，引用校验、证据覆盖和检索策略摘要会显示在这里。"
      />
    );
  }
  return (
    <div className="space-y-2.5">
      <PanelSummary title="回答审计" value={`${items.length} 项`} text="用于解释回答如何被检索、引用和校验，并给出安全的下一步动作。" />
      {items.map((item) => {
        const [label, Icon, tone] = SEVERITY_META[item.severity] || SEVERITY_META.info;
        if (item.id === "suggested_actions") {
          return (
            <div key={item.id} className={clsx("w-full rounded-lg border bg-paper-0 p-3", selectedId === item.id ? "border-amber shadow-card" : "border-line")}>
              <button className="w-full text-left" onClick={() => onSelect(item.id)}>
                <div className="font-medium text-[13px] text-ink-900">{item.label}</div>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-600">{item.summary}</p>
              </button>
              <div className="mt-2 space-y-1.5">
                {(item.data?.actions || []).slice(0, 4).map((action) => (
                  <button
                    key={action.id}
                    onClick={() => onSuggestion(action)}
                    className="w-full rounded-md border border-line bg-paper-50 px-2 py-1.5 text-left text-[11.5px] text-ink-700 hover:border-amber hover:text-amber-700"
                  >
                    {action.label}
                    <span className="block text-[10.5px] text-ink-400">{action.description}</span>
                  </button>
                ))}
              </div>
            </div>
          );
        }
        return (
          <button
            key={item.id}
            onClick={() => onSelect(item.id)}
            className={clsx(
              "w-full rounded-lg border bg-paper-0 p-3 text-left transition-colors",
              selectedId === item.id ? "border-amber shadow-card" : "border-line hover:border-amber/70"
            )}
          >
            <div className="flex items-start gap-2.5">
              <span className={clsx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10.5px]", tone)}>
                <Icon size={11} />
                {label}
              </span>
              <div className="min-w-0">
                <div className="font-medium text-[13px] text-ink-900">{item.label}</div>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-600">{item.summary}</p>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function EvidenceSummary({ summary }) {
  return (
    <PanelSummary
      title="正式文献证据"
      value={`本轮 ${summary.current || 0} · 池 ${summary.total || 0}`}
      text={`已保留 ${summary.accepted || 0}，待复核 ${summary.needsReview || 0}，已排除 ${summary.excluded || 0}。上传附件不会进入正式证据池。`}
    />
  );
}

function PaperSummary({ summary }) {
  return (
    <PanelSummary
      title="候选文献"
      value={`本轮 ${summary.current || 0} · 会话 ${summary.total || 0}`}
      text={`已保留 ${summary.accepted || 0}，待复核 ${summary.needsReview || 0}，已排除 ${summary.excluded || 0}。候选文献不等于最终证据。`}
    />
  );
}

function FilterBar({ filters, active, onChange }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {filters.map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={clsx(
            "rounded-md border px-2 py-1 text-[11px] transition-colors",
            active === key ? "border-ink-900 bg-ink-900 text-paper-50" : "border-line bg-paper-0 text-ink-500 hover:border-amber hover:text-amber-700"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function StatusBadge({ status }) {
  return (
    <span className={clsx("inline-flex rounded-full border px-1.5 py-0.5 text-[10px]", STATUS_STYLE[status] || STATUS_STYLE.candidate)}>
      {STATUS_LABEL[status] || status || "候选"}
    </span>
  );
}

function CurationButtons({ current, onSet, onNote, disabled = false, disabledTitle = "" }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {CURATION_ACTIONS.map(([status, label]) => (
        <button
          key={status}
          type="button"
          disabled={disabled}
          title={disabled ? disabledTitle : label}
          onClick={(event) => {
            event.stopPropagation();
            onSet(current === status ? "candidate" : status);
          }}
          className={clsx(
            "rounded border px-1.5 py-0.5 text-[10.5px] transition disabled:cursor-not-allowed disabled:opacity-40",
            current === status ? STATUS_STYLE[status] : "border-line text-ink-400 hover:border-ink-300 hover:text-ink-700"
          )}
        >
          {label}
        </button>
      ))}
      <button
        type="button"
        disabled={disabled}
        title={disabled ? disabledTitle : "备注"}
        onClick={(event) => {
          event.stopPropagation();
          onNote?.();
        }}
        className="rounded border border-line px-1.5 py-0.5 text-[10.5px] text-ink-400 transition hover:border-ink-300 hover:text-ink-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        备注
      </button>
    </div>
  );
}

function PaperCard({ paper, selected, onSelect, onStatus }) {
  const status = paper.status || "candidate";
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(paper.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect(paper.id);
      }}
      className={clsx(
        "w-full cursor-pointer rounded-lg border bg-paper-0 p-3 text-left transition-colors",
        selected ? "border-amber shadow-card" : "border-line hover:border-amber/70"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-serif text-[13.5px] leading-snug text-ink-900 line-clamp-2">{paper.title || paper.doi || "未命名文献"}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <StatusBadge status={status} />
            {paper.isCurrent && <span className="rounded-full border border-amber-100 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">本轮</span>}
            <span className="text-[10.5px] text-ink-400">证据 {paper.evidenceCount || 0}</span>
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[10.5px] text-ink-500">
        {paper.authors?.length > 0 && <span>{paper.authors.slice(0, 3).join(", ")}{paper.authors.length > 3 ? " 等" : ""}</span>}
        {paper.year && <span>· {paper.year}</span>}
        {paper.venue && <span>· {paper.venue}</span>}
      </div>
      {(paper.snippet || paper.abstract) && <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-ink-600">{paper.snippet || paper.abstract}</p>}
      {paper.note && <div className="mt-1 text-[11px] text-ink-500 line-clamp-2">备注：{paper.note}</div>}
      <CurationButtons
        current={status}
        onSet={(nextStatus) => onStatus(paper.id, nextStatus)}
        onNote={() => {
          const note = window.prompt("为这篇候选文献添加备注", paper.note || "");
          if (note != null) onStatus(paper.id, status, note);
        }}
      />
    </div>
  );
}

function runSuggestedAction(action, ctx) {
  const name = action?.action || action?.id;
  if (name === "set_evidence_mode") ctx.setChatResearchMode("evidence");
  if (name === "set_deep_mode") ctx.setChatResearchMode("deep");
  if (name === "review_pending_items") {
    ctx.setRightPanelTab("evidence");
    ctx.setEvidenceFilter("needs_review");
  }
  if (name === "open_attachment_picker") {
    window.dispatchEvent(new CustomEvent("literature:open-attachment-picker"));
  }
  ctx.selectAnswer();
}

function PanelSummary({ title, value, text }) {
  return (
    <div className="rounded-lg border border-line bg-paper-0 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[12px] text-ink-500">{title}</div>
        <div className="font-mono text-[12px] text-ink-900">{value}</div>
      </div>
      <div className="mt-1 text-[11.5px] leading-relaxed text-ink-500">{text}</div>
    </div>
  );
}

function EmptyState({ title, text }) {
  return (
    <div className="mt-10 rounded-lg border border-dashed border-line bg-paper-0 p-4 text-center">
      <div className="font-medium text-[13px] text-ink-800">{title}</div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-ink-500">{text}</p>
    </div>
  );
}
