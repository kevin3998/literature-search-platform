import React, { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  Download,
  FileClock,
  FileText,
  Layers,
  Layers3,
  Loader2,
  Paperclip,
  SearchCheck,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import MessageBubble from "./MessageBubble";
import AuditRecordModal from "./AuditRecordModal";
import ResearchStatePanel from "./ResearchStatePanel";
import { findAudit, findEvidence, findPaper } from "./literatureSearchViewModel";

const SUGGESTIONS = {
  literature_search: ["RAG 在科研场景中的最新进展", "对比检索增强与微调两类方法", "本地文献库里有哪些综述类文章"],
  idea_discovery: ["基于现有文献，哪些方向还存在研究空白？"],
  experiment_bridge: ["把这个假设拆解成可执行的实验步骤"],
};

const RESEARCH_MODES = [
  ["quick", "快速回答", "适合直接问答，系统按需检索并给出简洁回答。"],
  ["evidence", "证据审阅", "优先找材料和核对证据，少做延展分析。"],
  ["deep", "深度分析", "进行更完整的分析，耗时更长。"],
];

const STATUS_LABEL = {
  candidate: "候选",
  accepted: "已保留",
  excluded: "已排除",
  needs_review: "待复核",
};

const STATUS_STYLE = {
  candidate: "bg-paper-100 border-line text-ink-600",
  accepted: "bg-emerald-50 border-emerald-200 text-emerald-700",
  excluded: "bg-ink-100 border-line text-ink-400 line-through",
  needs_review: "bg-amber-50 border-amber-200 text-amber-700",
};

const CURATION_ACTIONS = [
  ["accepted", "保留"],
  ["excluded", "排除"],
  ["needs_review", "待复核"],
];

function currentResearchMode(role, answerMode) {
  if (role === "retrieval") return "evidence";
  if (role === "analysis" && answerMode === "deep") return "deep";
  return "quick";
}

export default function ChatPanel() {
  const activeModuleId = useAppStore((s) => s.activeModuleId);
  const modules = useAppStore((s) => s.modules);
  const session = useAppStore((s) => {
    const sid = s.activeSessionByModule[s.activeModuleId];
    return s.sessionsById[sid];
  });
  const sendMessage = useAppStore((s) => s.sendMessage);
  const editLastMessage = useAppStore((s) => s.editLastMessage);
  const cancelEdit = useAppStore((s) => s.cancelEdit);
  const chatAnswerMode = useAppStore((s) => s.chatAnswerMode);
  const chatRole = useAppStore((s) => s.chatRole);
  const setChatResearchMode = useAppStore((s) => s.setChatResearchMode);
  const setRightPanelTab = useAppStore((s) => s.setRightPanelTab);
  const setEvidenceFilter = useAppStore((s) => s.setLiteratureEvidenceFilter);
  const uploadLiteratureAttachments = useAppStore((s) => s.uploadLiteratureAttachments);
  const deleteLiteratureAttachment = useAppStore((s) => s.deleteLiteratureAttachment);
  const preview = useAppStore((s) => s.literatureSearch.preview);
  const selectLiteratureAnswer = useAppStore((s) => s.selectLiteratureAnswer);
  const startDeepResearch = useAppStore((s) => s.startDeepResearch);

  const exportSession = useAppStore((s) => s.exportActiveSession);
  const [input, setInput] = useState("");
  const [auditOpen, setAuditOpen] = useState(false);
  const [stateOpen, setStateOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);
  const mod = modules.find((m) => m.id === activeModuleId);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [session?.messages, session?.steps]);

  const handleSend = () => {
    if (!input.trim() || session.streaming || session.uploadingAttachments) return;
    sendMessage(input.trim());
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportSession();
    } finally {
      setExporting(false);
    }
  };

  const handleEditLast = () => {
    const text = editLastMessage();
    if (text) {
      setInput(text);
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
        }
      });
    }
  };

  const handleCancelEdit = () => {
    cancelEdit();
    setInput("");
  };

  const handleAttach = () => {
    if (!session || session.streaming || session.uploadingAttachments) return;
    fileInputRef.current?.click();
  };

  useEffect(() => {
    const openPicker = () => handleAttach();
    window.addEventListener("literature:open-attachment-picker", openPicker);
    return () => window.removeEventListener("literature:open-attachment-picker", openPicker);
  });

  const handleSuggestedAction = (action) => {
    const name = action?.action || action?.id;
    if (name === "set_evidence_mode") setChatResearchMode("evidence");
    if (name === "set_deep_mode") setChatResearchMode("deep");
    if (name === "review_pending_items") {
      setRightPanelTab("evidence");
      setEvidenceFilter("needs_review");
    }
    if (name === "open_attachment_picker") handleAttach();
    selectLiteratureAnswer();
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const handleFiles = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    try {
      await uploadLiteratureAttachments(files);
    } catch {
      // The store writes a readable error onto the session.
    }
  };

  if (!session) return null;

  const isEmpty = session.messages.length === 0;
  const lastUserIndex = session.messages.reduce((acc, m, i) => (m.role === "user" ? i : acc), -1);
  const researchMode = currentResearchMode(chatRole, chatAnswerMode);
  const showingDetail = preview.mode && preview.mode !== "answer";

  return (
    <div className="flex-1 flex flex-col h-full min-h-0 min-w-0">
      {!isEmpty && (
        <div className="flex-shrink-0 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-paper-0 px-4 lg:px-6 py-2.5">
          <div className="min-w-0">
            <div className="text-[13px] text-ink-700 truncate">{session.title || mod?.name}</div>
            <ResearchStateStrip state={session.researchState} />
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              className="btn-light inline-flex items-center gap-1.5 text-[12.5px]"
              onClick={() => setStateOpen(true)}
              title="查看本课题的研究状态：候选论文、证据池、覆盖缺口、问题与排除方向"
            >
              <Layers size={14} /> 研究状态
            </button>
            <button
              className="btn-light inline-flex items-center gap-1.5 text-[12.5px]"
              onClick={() => setAuditOpen(true)}
              title="查看本会话的答案—证据—产物审计链"
            >
              <FileClock size={14} /> 研究记录
            </button>
            <button
              className="btn-light inline-flex items-center gap-1.5 text-[12.5px]"
              onClick={handleExport}
              disabled={exporting}
              title="导出可引用的 Markdown 报告"
            >
              <Download size={14} /> {exporting ? "导出中…" : "导出报告"}
            </button>
          </div>
        </div>
      )}
      {auditOpen && <AuditRecordModal onClose={() => setAuditOpen(false)} />}
      {stateOpen && <ResearchStatePanel onClose={() => setStateOpen(false)} />}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-4 lg:px-6 py-6">
        {showingDetail ? (
          <LiteratureDetailOverlay session={session} preview={preview} onBack={selectLiteratureAnswer} onSuggestion={handleSuggestedAction} />
        ) : isEmpty ? (
          <div className="max-w-xl mx-auto mt-10">
            <div className="font-serif text-[22px] text-ink-900">{mod?.name}</div>
            <p className="text-[13.5px] text-ink-500 mt-1.5 leading-relaxed">{mod?.description}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {(SUGGESTIONS[activeModuleId] || []).map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className="text-[12.5px] px-3 py-1.5 rounded-full border border-line bg-paper-0 text-ink-700 hover:border-amber hover:text-amber-600 transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-2xl mx-auto space-y-5 min-w-0">
            {session.messages.map((m, i) => {
              const isLast = i === session.messages.length - 1;
              const isLastAssistant = m.role === "assistant" && isLast;
              return (
                <MessageBubble
                  key={i}
                  message={m}
                  progress={
                    isLastAssistant
                      ? {
                          steps: session.steps,
                          coverage: session.coverage,
                          papers: session.papers,
                          searchMeta: session.searchMeta,
                          jobs: session.liveJobs,
                          artifacts: session.liveArtifacts,
                          trace: session.liveTrace,
                          deepSuggestion: session.deepSuggestion,
                        }
                      : null
                  }
                  streaming={isLastAssistant && session.streaming}
                  groundingChecking={isLastAssistant && session.groundingChecking}
                  isLastUser={m.role === "user" && i === lastUserIndex && !session.streaming}
                  onEdit={handleEditLast}
                  onStartDeep={startDeepResearch}
                />
              );
            })}
          </div>
        )}
      </div>

      <div className="flex-shrink-0 border-t border-line bg-paper-0 px-4 lg:px-6 py-4">
        {session.editing && (
          <div className="max-w-2xl mx-auto mb-2 flex items-center justify-between rounded-md border border-amber/40 bg-amber-50 px-3 py-1.5 text-[12px] text-amber-700">
            <span>编辑模式：发送后将替换上一条问答</span>
            <button onClick={handleCancelEdit} className="text-amber-700/80 hover:text-amber-700 underline">取消</button>
          </div>
        )}
        <AttachmentChips
          attachments={session.attachments || []}
          uploading={!!session.uploadingAttachments}
          error={session.attachmentError}
          onRemove={deleteLiteratureAttachment}
        />
        <div className="max-w-2xl mx-auto mb-2 flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded-lg border border-line bg-paper-0 p-0.5 text-[12px]">
            {RESEARCH_MODES.map(([key, label, title]) => (
              <button
                key={key}
                onClick={() => setChatResearchMode(key)}
                disabled={session.streaming}
                title={title}
                className={
                  "px-2.5 py-1 rounded-md transition-colors disabled:opacity-50 " +
                  (researchMode === key ? "bg-ink-900 text-paper-50" : "text-ink-500 hover:text-ink-900")
                }
              >
                {label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-ink-400">
            {RESEARCH_MODES.find(([key]) => key === researchMode)?.[2]}
          </span>
        </div>
        <div className="max-w-2xl w-full mx-auto flex items-end gap-2.5 rounded-xl border border-line bg-paper-50 px-3.5 py-2.5 focus-within:border-amber transition-colors">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".txt,.pdf,text/plain,application/pdf"
            className="hidden"
            onChange={handleFiles}
          />
          <button
            type="button"
            onClick={handleAttach}
            disabled={session.streaming || session.uploadingAttachments}
            className="flex-shrink-0 w-8 h-8 rounded-lg border border-line bg-paper-0 text-ink-500 flex items-center justify-center hover:border-amber hover:text-amber-700 disabled:opacity-40 transition-colors"
            aria-label="添加附件"
            title="添加当前会话临时附件（txt / pdf）"
          >
            {session.uploadingAttachments ? <Loader2 size={15} className="animate-spin" /> : <Paperclip size={15} />}
          </button>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={`向「${mod?.name || ""}」提问…`}
            className="min-w-0 flex-1 resize-none bg-transparent text-[14px] text-ink-900 placeholder:text-ink-500/60 outline-none max-h-32 py-1"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || session.streaming || session.uploadingAttachments}
            className="flex-shrink-0 w-8 h-8 rounded-lg bg-ink-900 text-paper-50 flex items-center justify-center disabled:opacity-30 transition-opacity"
            aria-label="发送"
          >
            <ArrowUp size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

function ResearchStateStrip({ state }) {
  if (!state) return null;
  const acceptedPapers = state.paper_status_counts?.accepted || state.paperStatusCounts?.accepted || 0;
  const openQuestions = state.open_questions?.length || state.openQuestions?.length || 0;
  const acceptedEvidence = state.evidence_pool?.status_counts?.accepted || state.evidencePool?.statusCounts?.accepted || 0;
  const stage = state.stage || "retrieval";
  const objective = state.objective || state.topic || "尚未设定研究目标";
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-ink-500">
      <span className="max-w-[260px] truncate">{objective}</span>
      <span className="rounded-full border border-line bg-paper-50 px-1.5 py-0.5">阶段：{stage}</span>
      <span className="rounded-full border border-line bg-paper-50 px-1.5 py-0.5">开放问题 {openQuestions}</span>
      <span className="rounded-full border border-line bg-paper-50 px-1.5 py-0.5">保留文献 {acceptedPapers}</span>
      <span className="rounded-full border border-line bg-paper-50 px-1.5 py-0.5">保留证据 {acceptedEvidence}</span>
    </div>
  );
}

function AttachmentChips({ attachments, uploading, error, onRemove }) {
  if (!attachments.length && !uploading && !error) return null;
  return (
    <div className="max-w-2xl mx-auto mb-2 flex flex-wrap items-center gap-2">
      {attachments.map((item) => (
        <span
          key={item.attachmentId}
          className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-paper-50 px-2.5 py-1 text-[11.5px] text-ink-600"
          title={item.textPreview || item.filename}
        >
          <FileText size={12} className="flex-shrink-0 text-ink-400" />
          <span className="truncate max-w-[210px]">{item.filename}</span>
          <span className="text-ink-400">{item.status === "parsed" ? `${item.charCount || 0} 字` : "解析失败"}</span>
          <button
            type="button"
            onClick={() => onRemove(item.attachmentId)}
            className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-ink-400 hover:bg-paper-100 hover:text-ink-800"
            aria-label={`移除附件 ${item.filename}`}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      {uploading && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11.5px] text-amber-700">
          <Loader2 size={12} className="animate-spin" /> 附件解析中
        </span>
      )}
      {error && <span className="text-[11.5px] text-red-600">{error}</span>}
    </div>
  );
}

function LiteratureDetailOverlay({ session, preview, onBack, onSuggestion }) {
  if (preview.mode === "evidence") {
    return (
      <DetailShell title="正式文献证据详情" Icon={Layers3} onBack={onBack}>
        <EvidenceDetail evidence={findEvidence(session, preview.selectedEvidenceId)} />
      </DetailShell>
    );
  }
  if (preview.mode === "paper") {
    return (
      <DetailShell title="文献详情" Icon={FileText} onBack={onBack}>
        <PaperDetail paper={findPaper(session, preview.selectedPaperId)} />
      </DetailShell>
    );
  }
  return (
    <DetailShell title="审计详情" Icon={ShieldCheck} onBack={onBack}>
      <AuditDetail item={findAudit(session, preview.selectedAuditId)} onSuggestion={onSuggestion} />
    </DetailShell>
  );
}

function DetailShell({ title, Icon, onBack, children }) {
  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-paper-0 text-ink-600">
            <Icon size={16} />
          </span>
          <h2 className="font-serif text-[20px] text-ink-900">{title}</h2>
        </div>
        <button onClick={onBack} className="btn-light inline-flex items-center gap-1.5">
          <ArrowLeft size={14} /> 返回回答
        </button>
      </div>
      <section className="rounded-lg border border-line bg-paper-0 p-5 shadow-card">{children}</section>
    </div>
  );
}

function MissingDetail({ text }) {
  return <div className="text-[13px] leading-relaxed text-ink-500">{text}</div>;
}

function citationAlias(evidence) {
  return evidence?.alias || evidence?.citation_alias || evidence?.citationAlias || (/^\d+$/.test(String(evidence?.evidence_id || "")) ? evidence.evidence_id : null);
}

function internalEvidenceIds(evidence, alias) {
  const ids = [
    ...(evidence?.evidence_ids || []),
    evidence?.source_evidence_id,
    evidence?.sourceEvidenceId,
    evidence?.evidence_id,
  ]
    .filter(Boolean)
    .map((id) => String(id))
    .filter((id) => id !== String(alias || ""));
  return [...new Set(ids)];
}

function EvidenceDetail({ evidence }) {
  const setEvidenceStatus = useAppStore((s) => s.setEvidenceStatus);
  if (!evidence) return <MissingDetail text="未找到这条证据。可能是会话已经刷新，或该证据不属于最近一轮回答。" />;
  const alias = citationAlias(evidence);
  const ids = internalEvidenceIds(evidence, alias);
  const evidenceItemId = evidence.evidenceItemId || evidence.evidence_item_id;
  const status = evidence.status || "candidate";
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[12px] text-ink-400">证据来源</div>
        <h3 className="mt-1 font-serif text-[18px] leading-snug text-ink-900">{evidence.title || evidence.doi || "证据片段"}</h3>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <StatusBadge status={status} />
          {evidence.isCurrent && <span className="rounded-full border border-amber-100 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">本轮证据</span>}
        </div>
      </div>
      {(evidence.snippet || evidence.text) && (
        <div className="rounded-lg border border-line bg-paper-50 p-3 text-[13px] leading-relaxed text-ink-700">
          {evidence.snippet || evidence.text}
        </div>
      )}
      <DetailGrid
        rows={[
          ["引用编号", alias ? citationOrdinalLabel(alias) : "未提供"],
          ["内部证据 ID", ids.join(", ") || "未提供"],
          ["章节", evidence.section || "未提供"],
          ["会话证据 ID", evidenceItemId || "未提供"],
          ["来源路径", evidence.source_path || "未提供"],
          ["DOI", evidence.doi || "未提供"],
          ["备注", evidence.note || "无"],
        ]}
      />
      <CurationControls
        current={status}
        disabled={!evidenceItemId}
        disabledText="这条引用还没有稳定的会话证据 ID，暂不能策展。"
        onSet={(nextStatus) => setEvidenceStatus(evidenceItemId, nextStatus)}
        onNote={() => {
          const note = window.prompt("为这条证据添加备注", evidence.note || "");
          if (note != null) setEvidenceStatus(evidenceItemId, status, note);
        }}
      />
      <BoundaryNote text="这是本轮回答引用校验中的正式文献证据，不是上传附件，也不代表整篇论文已经支持所有结论。" />
    </div>
  );
}

function PaperDetail({ paper }) {
  const setPaperStatus = useAppStore((s) => s.setPaperStatus);
  if (!paper) return <MissingDetail text="未找到这篇文献。可能是最近一轮检索结果已经变化。" />;
  const status = paper.status || "candidate";
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[12px] text-ink-400">候选文献</div>
        <h3 className="mt-1 font-serif text-[19px] leading-snug text-ink-900">{paper.title || "未命名文献"}</h3>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <StatusBadge status={status} />
          {paper.isCurrent && <span className="rounded-full border border-amber-100 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">本轮候选</span>}
          <span className="text-[11px] text-ink-400">相关证据 {paper.evidenceCount || paper.evidence_count || paper.evidence?.length || 0}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 font-mono text-[11px] text-ink-500">
          {paper.authors?.length > 0 && <span>{paper.authors.slice(0, 6).join(", ")}{paper.authors.length > 6 ? " 等" : ""}</span>}
          {paper.year && <span>· {paper.year}</span>}
          {paper.venue && <span>· {paper.venue}</span>}
          {paper.citation_count != null && <span>· 被引 {paper.citation_count}</span>}
        </div>
      </div>
      {(paper.abstract || paper.snippet) && (
        <div>
          <div className="mb-1.5 text-[12px] text-ink-400">摘要 / 匹配片段</div>
          <p className="rounded-lg border border-line bg-paper-50 p-3 text-[13px] leading-relaxed text-ink-700">
            {paper.abstract || paper.snippet}
          </p>
        </div>
      )}
      {paper.evidence?.length > 0 && (
        <div>
          <div className="mb-2 text-[12px] text-ink-400">相关证据片段</div>
          <div className="space-y-2">
            {paper.evidence.slice(0, 5).map((ev) => (
              <div key={ev.evidence_id || ev.source_path || ev.text} className="rounded-md border border-line bg-paper-50 px-3 py-2">
                <div className="font-mono text-[10.5px] text-ink-400">{ev.evidence_id || ev.kind || "evidence"}</div>
                <div className="mt-1 text-[12.5px] leading-relaxed text-ink-700">{ev.snippet || ev.text}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      <BoundaryNote text="这是本轮检索返回的候选文献。候选文献用于帮助定位材料，不等于回答最终采用的正式证据。" />
      <CurationControls
        current={status}
        onSet={(nextStatus) => setPaperStatus(paper.id || paper.key || paper.paper_id || paper.doi, nextStatus)}
        onNote={() => {
          const note = window.prompt("为这篇候选文献添加备注", paper.note || "");
          if (note != null) setPaperStatus(paper.id || paper.key || paper.paper_id || paper.doi, status, note);
        }}
      />
      <DetailGrid
        rows={[
          ["文献 ID", paper.id || paper.paper_id || paper.paperId || "未提供"],
          ["DOI", paper.doi || "未提供"],
          ["来源路径", paper.source_path || "未提供"],
          ["当前状态", STATUS_LABEL[status] || status],
          ["备注", paper.note || "无"],
          ["相关度", paper.relevance_score != null ? `${Math.round(paper.relevance_score * 100)}%` : "未提供"],
        ]}
      />
    </div>
  );
}

function AuditDetail({ item, onSuggestion }) {
  if (!item) return <MissingDetail text="未找到这项审计记录。完成一次回答后，审计信息会在这里展示。" />;
  if (item.id === "suggested_actions") return <SuggestedActionsAudit item={item} onSuggestion={onSuggestion} />;
  if (item.id === "route") return <RouteAudit data={item.data} summary={item.summary} />;
  if (item.id === "attachments") return <AttachmentAudit data={item.data} summary={item.summary} />;
  if (item.id === "library_status") return <LibraryStatusAudit data={item.data} summary={item.summary} />;
  if (item.id === "failure") return <FailureAudit data={item.data} summary={item.summary} />;
  if (item.id === "citation") return <CitationAudit data={item.data} summary={item.summary} />;
  if (item.id === "coverage") return <CoverageAudit data={item.data} summary={item.summary} />;
  if (item.id === "retrieval") return <RetrievalAudit data={item.data} summary={item.summary} />;
  if (item.id === "trace") return <TraceAudit data={item.data} summary={item.summary} />;
  return <MissingDetail text={item.summary || "暂无详情。"} />;
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] ${STATUS_STYLE[status] || STATUS_STYLE.candidate}`}>
      {STATUS_LABEL[status] || status || "候选"}
    </span>
  );
}

function CurationControls({ current, onSet, onNote, disabled = false, disabledText = "" }) {
  return (
    <div className="rounded-lg border border-line bg-paper-50 p-3">
      <div className="mb-2 text-[12px] text-ink-500">会话内策展状态</div>
      <div className="flex flex-wrap gap-1.5">
        {CURATION_ACTIONS.map(([status, label]) => (
          <button
            key={status}
            type="button"
            disabled={disabled}
            title={disabled ? disabledText : label}
            onClick={() => onSet(current === status ? "candidate" : status)}
            className={`rounded border px-2 py-1 text-[11.5px] transition disabled:cursor-not-allowed disabled:opacity-40 ${
              current === status ? STATUS_STYLE[status] : "border-line bg-paper-0 text-ink-500 hover:border-ink-300 hover:text-ink-800"
            }`}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          disabled={disabled}
          title={disabled ? disabledText : "备注"}
          onClick={onNote}
          className="rounded border border-line bg-paper-0 px-2 py-1 text-[11.5px] text-ink-500 transition hover:border-ink-300 hover:text-ink-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          备注
        </button>
      </div>
      {disabled && <div className="mt-2 text-[11.5px] text-ink-400">{disabledText}</div>}
    </div>
  );
}

function SuggestedActionsAudit({ item, onSuggestion }) {
  const actions = item?.data?.actions || [];
  return (
    <div className="space-y-4">
      <AuditHeader severity="info" summary={item.summary || "建议下一步"} />
      {actions.length === 0 ? (
        <MissingDetail text="暂无可执行建议。" />
      ) : (
        <div className="space-y-2">
          {actions.map((action) => (
            <button
              key={action.id}
              type="button"
              onClick={() => onSuggestion?.(action)}
              className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-left transition hover:border-amber hover:text-amber-700"
            >
              <div className="text-[13px] font-medium text-ink-800">{action.label}</div>
              <div className="mt-0.5 text-[12px] leading-relaxed text-ink-500">{action.description}</div>
            </button>
          ))}
        </div>
      )}
      <BoundaryNote text="这些建议只会切换界面状态、打开附件选择或帮助你回到输入区，不会自动发送问题，也不会启动研究工作流。" />
    </div>
  );
}

function RouteAudit({ data, summary }) {
  return (
    <div className="space-y-4">
      <AuditHeader severity="info" summary={summary} />
      <DetailGrid
        rows={[
          ["分流结果", data?.label || "未记录"],
          ["路由标识", data?.route || "未记录"],
        ]}
      />
      <BoundaryNote text="意图分流决定本轮是否需要检索文献库、读取上传附件，或只回答普通帮助问题。" />
    </div>
  );
}

function AttachmentAudit({ data, summary }) {
  const filenames = data?.filenames || [];
  return (
    <div className="space-y-4">
      <AuditHeader severity="info" summary={summary} />
      <DetailGrid
        rows={[
          ["附件数量", String(data?.attachmentCount || filenames.length || 0)],
          ["附件名称", filenames.join("、") || "未记录"],
        ]}
      />
      <BoundaryNote text="上传附件只服务当前会话，不写入文献库，不进入全局索引，也不参与 [E#] 文献证据引用校验。" />
    </div>
  );
}

function LibraryStatusAudit({ data, summary }) {
  const years = data?.yearRange || [];
  const journals = data?.topJournals || [];
  return (
    <div className="space-y-4">
      <AuditHeader severity="info" summary={summary} />
      <DetailGrid
        rows={[
          ["文献数", data?.paperCount != null ? String(data.paperCount) : "未提供"],
          ["索引记录", data?.articleIndexCount != null ? String(data.articleIndexCount) : "未提供"],
          ["年份覆盖", years.length >= 2 ? `${years[0]}-${years[1]}` : "未提供"],
          ["向量索引", data?.vectorBuilt === true ? "已构建" : data?.vectorBuilt === false ? "未构建或不可用" : "未提供"],
        ]}
      />
      {journals.length > 0 && (
        <SimpleList title="主要期刊" items={journals.slice(0, 8).map((item) => `${item.journal || "未知期刊"}：${item.count || 0} 篇`)} />
      )}
      <BoundaryNote text="这是当前本地文献库统计，不是外部全网文献统计，也不是主题检索结果。" />
    </div>
  );
}

function FailureAudit({ data, summary }) {
  return (
    <div className="space-y-4">
      <AuditHeader severity={data?.code === "tool_timeout_failed" ? "error" : "warning"} summary={summary} />
      <DetailGrid
        rows={[
          ["原因代码", data?.code || "未提供"],
          ["中文说明", data?.message || summary || "未提供"],
        ]}
      />
      <BoundaryNote text="这项说明用于解释本轮为什么没有形成可复核证据或候选文献，不表示整个文献库一定为空。" />
    </div>
  );
}

function AuditHeader({ severity = "info", summary }) {
  const icon = severity === "warning" || severity === "error" ? <TriangleAlert size={14} /> : severity === "ok" ? <CheckCircle2 size={14} /> : <SearchCheck size={14} />;
  const tone =
    severity === "error"
      ? "border-red-200 bg-red-50 text-red-700"
      : severity === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : severity === "ok"
          ? "border-emerald-100 bg-emerald-50 text-emerald-700"
          : "border-line bg-paper-50 text-ink-600";
  return (
    <div className={`mb-4 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] ${tone}`}>
      {icon}
      {summary}
    </div>
  );
}

function CitationAudit({ data, summary }) {
  const grounding = data?.grounding || {};
  const groundingSummary = data?.grounding_summary || {};
  return (
    <div className="space-y-4">
      <AuditHeader severity={data?.missing_ids?.length ? "warning" : "ok"} summary={summary} />
      <DetailGrid
        rows={[
          ["审计状态", data?.audit_status || "已记录"],
          ["答案权限", data?.answer_permission || groundingSummary.answer_permission || "未提供"],
          ["已用证据", String(data?.used_evidence?.length || 0)],
          ["缺失引用", data?.missing_ids?.length ? data.missing_ids.join(", ") : "无"],
        ]}
      />
      {groundingSummary.claims_total != null && (
        <DetailGrid
          rows={[
            ["结论数量", String(groundingSummary.claims_total)],
            ["支持", String(groundingSummary.supported || 0)],
            ["受限", String(groundingSummary.limited || 0)],
            ["冲突", String(groundingSummary.conflicting || 0)],
            ["已略去", String(groundingSummary.removed || 0)],
          ]}
        />
      )}
      {grounding.warnings?.length > 0 && <SimpleList title="校验说明" items={grounding.warnings} />}
    </div>
  );
}

function CoverageAudit({ data, summary }) {
  return (
    <div className="space-y-4">
      <AuditHeader severity={data?.status === "weak" || data?.status === "none" ? "warning" : "info"} summary={summary} />
      <DetailGrid
        rows={[
          ["覆盖状态", data?.status || "未提供"],
          ["代表文献数", String(data?.source_count || data?.paper_count || data?.breadth?.source_count || "未提供")],
          ["证据数", String(data?.evidence_count || data?.breadth?.evidence_count || "未提供")],
        ]}
      />
      {data?.missing_aspects?.length > 0 && <SimpleList title="缺口提示" items={data.missing_aspects} />}
    </div>
  );
}

function RetrievalAudit({ data, summary }) {
  const plan = data?.query_plan || data?.queryPlan || {};
  return (
    <div className="space-y-4">
      <AuditHeader severity={data?.vector_unavailable_reason ? "warning" : "info"} summary={summary} />
      <DetailGrid
        rows={[
          ["检索方式", data?.retrieval_used || data?.retrievalUsed || plan.retrieval_used || plan.retrievalUsed || "未提供"],
          ["查询扩展", plan.expanded_query || plan.expandedQuery || "未提供"],
          ["向量检索说明", data?.vector_unavailable_reason || data?.query_plan?.vector_unavailable_reason || "无"],
        ]}
      />
    </div>
  );
}

function TraceAudit({ data, summary }) {
  return (
    <div className="space-y-4">
      <AuditHeader severity={data?.some((item) => item.status === "error") ? "warning" : "info"} summary={summary} />
      <div className="space-y-2">
        {(data || []).slice(0, 20).map((item, index) => (
          <div key={item.tool_call_id || index} className="rounded-md border border-line bg-paper-50 px-3 py-2">
            <div className="flex items-center gap-2 text-[12px]">
              <span className="font-medium text-ink-800">{item.tool_name || "工具调用"}</span>
              <span className="text-ink-400">{item.status || "已记录"}</span>
              {item.latency_ms != null && <span className="ml-auto font-mono text-ink-400">{item.latency_ms}ms</span>}
            </div>
            {(item.result_summary || item.error_code || item.recovery_hint) && (
              <div className="mt-1 text-[12px] leading-relaxed text-ink-600">
                {item.status === "error" ? `${item.error_code || "错误"}${item.recovery_hint ? " · " + item.recovery_hint : ""}` : item.result_summary}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailGrid({ rows }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {rows.map(([label, value]) => (
        <div key={label} className="rounded-md border border-line bg-paper-50 px-3 py-2">
          <div className="text-[11px] text-ink-400">{label}</div>
          <div className="mt-0.5 break-words text-[12.5px] leading-relaxed text-ink-700">{value}</div>
        </div>
      ))}
    </div>
  );
}

function BoundaryNote({ text }) {
  return (
    <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-[12.5px] leading-relaxed text-amber-800">
      {text}
    </div>
  );
}

function SimpleList({ title, items }) {
  return (
    <div>
      <div className="mb-1.5 text-[12px] text-ink-400">{title}</div>
      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li key={index} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[12.5px] leading-relaxed text-ink-700">
            {String(item)}
          </li>
        ))}
      </ul>
    </div>
  );
}
