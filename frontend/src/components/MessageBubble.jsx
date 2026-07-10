import React, { useState } from "react";
import clsx from "clsx";
import { Copy, Check as CheckIcon, Pencil, FileText, Table, Archive, FlaskConical, Loader2, Wrench, Telescope, RefreshCw } from "lucide-react";
import RetrievalProgress from "./RetrievalProgress";
import RetrievalInspector from "./RetrievalInspector";
import MarkdownMessage, { buildCitationNumbers, buildEvidenceById } from "./MarkdownMessage";
import { citationOrdinalLabel } from "./citationLabels.js";

// Block 6c: specialist-role → badge label for "which subagent answered".
const ROLE_LABEL = {
  retrieval: "检索角色",
  evidence: "证据角色",
  analysis: "分析角色",
  synthesis: "综合角色",
  report: "报告角色",
};

// Block 4b: artifact-type → label + icon for the Chat artifact chips.
const ARTIFACT_META = {
  run: ["报告", FileText],
  report: ["报告", FileText],
  task: ["研究任务", FileText],
  pack: ["证据包", Archive],
  comparison: ["对比表", Table],
  extraction: ["抽取结果", FlaskConical],
};

function JobProgress({ jobs }) {
  const list = Object.values(jobs || {});
  if (!list.length) return null;
  return (
    <div className="space-y-1.5">
      {list.map((job) => {
        const running = job.status !== "completed" && job.status !== "failed";
        const pct = job.total ? Math.min(100, Math.round((job.current / job.total) * 100)) : null;
        return (
          <div
            key={job.job_id}
            className={clsx(
              "rounded-lg border px-3 py-2 text-[12px]",
              job.status === "failed" ? "border-red-200 bg-red-50 text-red-700" : "border-line bg-paper-0 text-ink-600"
            )}
          >
            <div className="flex items-center gap-1.5">
              {running ? <Loader2 size={13} className="animate-spin text-amber" /> : <CheckIcon size={13} className="text-ink-400" />}
              <span className="font-medium text-ink-800">
                {{ run: "深度研究流程", task_run: "研究任务", extract: "指标抽取", compare: "对比分析" }[job.job_type] || job.job_type}
              </span>
              <span className="text-ink-400">
                {job.status === "failed" ? "失败" : job.status === "completed" ? "完成" : job.phase || "进行中…"}
              </span>
              {pct != null && running && <span className="ml-auto font-mono text-ink-400">{pct}%</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ArtifactList({ artifacts }) {
  if (!artifacts?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {artifacts.map((a) => {
        const [label, Icon] = ARTIFACT_META[a.artifact_type] || ["产物", FileText];
        return (
          <span
            key={a.artifact_id}
            title={a.path || a.artifact_id}
            className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper-0 px-2.5 py-1 text-[11.5px] text-ink-600"
          >
            <Icon size={12} className="text-ink-400" />
            {label}
          </span>
        );
      })}
    </div>
  );
}

function DeepResearchSuggestion({ suggestion, streaming, onStartDeep }) {
  // Block 5: advisory only — quick mode never auto-escalates. Hidden while
  // streaming so it appears with the settled answer.
  if (!suggestion || streaming) return null;
  const n = suggestion.candidate_paper_count;
  return (
    <div className="rounded-lg border border-amber/40 bg-amber-50 px-3.5 py-3 text-[12.5px] text-ink-700">
      <div className="flex items-start gap-2">
        <Telescope size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          <div className="font-medium text-ink-900">当前更适合作为代表性概览</div>
          <div className="mt-0.5 text-ink-600">
            {suggestion.reason || "本地库中可能还有更多相关文献。"}
            {n ? `本轮匹配到约 ${n} 篇候选。` : ""}如需更系统的覆盖，可开始深度研究。
          </div>
          <button
            onClick={() => onStartDeep && onStartDeep(suggestion.question)}
            className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-ink-900 text-paper-50 px-3 py-1.5 text-[12px] hover:bg-ink-800 transition-colors"
          >
            <Telescope size={13} /> 开始深度研究
          </button>
        </div>
      </div>
    </div>
  );
}

function ReuseChip({ reused }) {
  if (!reused) return null;
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper-0 px-2.5 py-1 text-[11px] text-ink-500">
      <RefreshCw size={11} className="text-ink-400" /> 基于上一轮证据继续分析
    </div>
  );
}

function ToolTraceFoldout({ trace }) {
  const [open, setOpen] = useState(false);
  if (!trace?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-paper-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11.5px] text-ink-500 hover:text-ink-800 transition-colors"
      >
        <Wrench size={12} /> 执行轨迹（{trace.length}）
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2 space-y-1">
          {trace.map((t, i) => (
            <div key={t.tool_call_id || i} className="flex items-center gap-2 text-[11px] font-mono">
              <span className={clsx("font-medium", t.status === "error" ? "text-red-600" : "text-ink-700")}>{t.tool_name}</span>
              <span className="text-ink-400">{t.permission_level || "?"}</span>
              {t.latency_ms != null && <span className="text-ink-400">{t.latency_ms}ms</span>}
              <span className={clsx("truncate", t.status === "error" ? "text-red-600" : "text-ink-500")}>
                {t.status === "error" ? `${t.error_code}${t.recovery_hint ? " · " + t.recovery_hint : ""}` : t.result_summary}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function fmtTime(at) {
  if (!at) return "";
  try {
    return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function ActionButton({ onClick, title, children }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="inline-flex items-center gap-1 text-ink-400 hover:text-ink-700 transition-colors"
    >
      {children}
    </button>
  );
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard may be unavailable (insecure context); silently ignore
    }
  };
  return (
    <ActionButton onClick={onCopy} title="复制">
      {copied ? <CheckIcon size={12} className="text-teal" /> : <Copy size={12} />}
      {copied ? "已复制" : "复制"}
    </ActionButton>
  );
}

// answer_permission is a COMPLETENESS / evidence-strength axis (how far the local
// evidence lets us go), NOT a "trust the text" axis. After a strict gate the text is
// already safe, so even partial/hypothesis/conflicting are shown as neutral info, not
// alarm. tone: ok=green, info=amber-neutral, muted=gray.
const PERMISSION_META = {
  grounded: { label: "证据充分", tone: "ok" },
  partially_grounded: { label: "部分有支持", tone: "info" },
  hypothesis: { label: "推断为主", tone: "info" },
  conflicting: { label: "证据冲突", tone: "info" },
  not_answerable: { label: "证据不足", tone: "muted" },
};

const PERMISSION_TONE_CLASS = {
  ok: "bg-emerald-50 text-emerald-700",
  info: "bg-amber-50 text-amber-700",
  muted: "bg-paper-100 text-ink-500",
};

const SUPPORT_LABEL = {
  supported: "支持",
  partially_supported: "部分支持",
  unsupported: "无支持",
  conflicting: "冲突",
  inference: "推断",
};

function GroundingSummary({ summary, grounding }) {
  const meta = PERMISSION_META[summary?.answer_permission] || null;
  if (!meta && !(summary?.claims_total)) return null;
  const parts = [];
  if (summary?.claims_total) {
    parts.push(`${summary.claims_total} 项结论`);
    parts.push(`支持 ${summary.supported}`);
    if (summary.limited) parts.push(`受限 ${summary.limited}`);
    if (summary.unsupported) parts.push(`无支持 ${summary.unsupported}`);
    if (summary.conflicting) parts.push(`冲突 ${summary.conflicting}`);
    if (summary.removed) parts.push(`略去 ${summary.removed}`);
  }
  const limited = (grounding?.claims || []).filter((c) => c.support_status !== "supported");
  const removed = grounding?.removed_claims || [];
  return (
    <div className="mt-1.5 leading-snug">
      <div className="flex flex-wrap items-center gap-1.5">
        {meta && (
          <span className={clsx("px-1.5 py-0.5 rounded font-medium", PERMISSION_TONE_CLASS[meta.tone])}>
            Grounding：{meta.label}
          </span>
        )}
        {parts.length > 0 && <span className="text-ink-500">{parts.join(" · ")}</span>}
      </div>
      {/* Transparency notes — these EXPLAIN the answer, they don't contradict it. */}
      {(grounding?.warnings || []).map((w, i) => (
        <div key={i} className="text-ink-500 mt-0.5">· {w}</div>
      ))}
      {limited.length > 0 && (
        <div className="mt-1">
          <div className="text-ink-400">措辞较保守的结论：</div>
          <ul className="mt-0.5 space-y-0.5 border-l-2 border-amber-200 pl-2.5">
            {limited.map((c, i) => (
              <li key={i} className="text-ink-600">
                <span className="text-amber-700">[{SUPPORT_LABEL[c.support_status] || c.support_status}]</span>{" "}
                {c.claim}
                {c.scope_notes && <span className="text-ink-400"> · {c.scope_notes}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {removed.length > 0 && (
        <div className="mt-1">
          <div className="text-ink-400">因本地库无证据支持，未纳入正文：</div>
          <ul className="mt-0.5 space-y-0.5 border-l-2 border-line pl-2.5">
            {removed.map((c, i) => (
              <li key={i} className="text-ink-400 line-through decoration-ink-300">
                {c.claim}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CitationFooter({ citation, numbers }) {
  const [open, setOpen] = useState(false);
  const used = citation.used_evidence || [];
  const numberFor = (e) => (e.evidence_ids || [e.alias, e.citation_alias, e.evidence_id].filter(Boolean)).map((id) => numbers?.get(String(id))).find(Boolean);
  const grounding = citation.grounding;
  const summary = citation.grounding_summary;
  // The red "alarm" tone is reserved for answers that were NOT successfully gated.
  const alarm = citation.audit_status === "unverified" || citation.audit_status === "uncited";
  const permMeta = PERMISSION_META[citation.answer_permission];
  let headline;
  if (alarm) {
    headline = citation.missing_ids?.length
      ? `引用校验警告：${citation.missing_ids.length} 个引用未找到证据 (${citation.missing_ids.join(", ")})`
      : citation.audit_status === "uncited"
        ? "引用校验警告：有证据但未标注引用"
        : "本回答未能完成证据校对，请谨慎参考";
  } else if (permMeta) {
    headline = `${permMeta.label} · 已用证据 ${used.length} 条`;
  } else {
    headline = `已用证据 ${used.length} 条 · 引用校验通过`;
  }
  return (
    <div className="mt-2 text-[12px]">
      <button
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "inline-flex items-center gap-1.5 px-2 py-1 rounded-md border transition-colors",
          alarm
            ? "border-red-200 bg-red-50 text-red-600"
            : "border-line bg-paper-50 text-ink-600 hover:border-amber"
        )}
      >
        {headline}
        <span className="text-ink-400">{open ? "▴" : "▾"}</span>
      </button>
      {open && (grounding || summary) && <GroundingSummary summary={summary} grounding={grounding} />}
      {open && used.length > 0 && (
        <ul className="mt-1.5 space-y-1.5 border-l-2 border-line pl-3">
          {used.map((e, i) => (
            <li key={i} className="leading-snug flex gap-2">
              <span className="flex-shrink-0 inline-flex items-center justify-center min-w-[16px] h-[16px] mt-0.5 px-1 rounded-[7px] bg-amber-50 text-amber-700 text-[10px] font-medium">
                {citationOrdinalLabel(numberFor(e))}
              </span>
              <span className="min-w-0">
                <span className="text-ink-700">{e.title || e.doi || "证据"}</span>
                {e.section && <span className="text-ink-400"> · {e.section}</span>}
                {e.snippet && <div className="text-ink-500 mt-0.5">{e.snippet}</div>}
                {e.source_path && (
                  <div className="text-ink-400 font-mono text-[11px] mt-0.5">
                    {citationOrdinalLabel(numberFor(e))} · {e.source_path}
                  </div>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function MessageBubble({ message, progress, streaming, groundingChecking, isLastUser, onEdit, onStartDeep }) {
  const isUser = message.role === "user";
  const [inspectorOpen, setInspectorOpen] = useState(false);

  if (isUser) {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[72%] rounded-lg rounded-br-sm bg-ink-900 text-paper-50 px-4 py-2.5 text-[14px] leading-relaxed">
          {message.content}
          {message.attachments?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-paper-50/15 pt-2">
              {message.attachments.map((item) => (
                <span
                  key={item.attachmentId || item.filename}
                  className="inline-flex items-center gap-1 rounded-full bg-paper-50/10 px-2 py-0.5 text-[11px] text-paper-50/80"
                >
                  <FileText size={11} />
                  {item.filename}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 pr-1 text-[11px] text-ink-400">
          {message.at && <span>{fmtTime(message.at)}</span>}
          <CopyButton text={message.content} />
          {isLastUser && (
            <ActionButton onClick={onEdit} title="重新编辑这条消息">
              <Pencil size={12} /> 编辑
            </ActionButton>
          )}
        </div>
      </div>
    );
  }

  const inspectorData = progress
    ? {
        query_plan: progress.searchMeta?.query_plan,
        retrieval_used: progress.searchMeta?.retrieval_used,
        vector_unavailable_reason: progress.searchMeta?.vector_unavailable_reason,
        coverage: progress.coverage || {},
        breadth: progress.coverage?.breadth,
        papers: progress.papers || [],
      }
    : null;
  const hasInspect = inspectorData && (inspectorData.query_plan || (inspectorData.papers || []).length);
  // Shared citation numbering: inline badges and the footer list use the same
  // first-appearance numbers; tooltips read from the citation's used_evidence.
  const citationNumbers = buildCitationNumbers(message.content);
  const evidenceById = buildEvidenceById(message.citation);
  const hasResearchProgress = !!progress && (
    (progress.steps || []).length > 0 ||
    !!progress.coverage ||
    (progress.papers || []).length > 0 ||
    !!progress.searchMeta ||
    Object.keys(progress.jobs || {}).length > 0 ||
    (progress.artifacts || []).length > 0 ||
    (progress.trace || []).length > 0 ||
    !!progress.deepSuggestion
  );

  return (
    <div className="flex justify-start">
      <div className="max-w-[78%] w-full space-y-2">
        {hasResearchProgress && (
          <RetrievalProgress
            steps={progress.steps}
            coverage={progress.coverage}
            papers={progress.papers}
            streaming={streaming}
            answered={!!message.content}
            onInspect={hasInspect ? () => setInspectorOpen(true) : null}
          />
        )}
        {hasResearchProgress && <JobProgress jobs={progress.jobs} />}
        {hasResearchProgress && <ArtifactList artifacts={progress.artifacts} />}
        {message.roleUsed && message.roleUsed !== "general" && ROLE_LABEL[message.roleUsed] && (
          <div className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] text-amber-700">
            {ROLE_LABEL[message.roleUsed]}
          </div>
        )}
        {!streaming && !groundingChecking && message.citation?.reused_evidence && (
          <ReuseChip reused />
        )}
        {(message.content || streaming || groundingChecking) && (
          <div
            className={clsx(
              "rounded-lg rounded-bl-sm bg-paper-0 border border-line px-4 py-3 text-[14.5px] leading-[1.7] text-ink-800 font-serif",
              message.error && "border-red-200"
            )}
          >
            {/* Block 3 provisional state: until the grounding gate resolves, the
                streamed text is a DRAFT that may still be rewritten/trimmed. Mark it
                clearly and dim it so the user doesn't take a not-yet-gated draft as
                the final, evidence-bounded answer. */}
            {(streaming || groundingChecking) && (
              <div className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-paper-100 px-2 py-0.5 text-[11px] text-ink-500">
                <span className="h-1.5 w-1.5 rounded-full bg-amber animate-pulse" />
                {groundingChecking ? "正在校对证据…定稿前内容可能调整" : "生成中…"}
              </div>
            )}
            <div className={clsx((streaming || groundingChecking) && "opacity-60")}>
              <MarkdownMessage
                text={message.content}
                missingIds={message.citation?.missing_ids}
                numbers={citationNumbers}
                evidenceById={evidenceById}
              />
              {streaming && <span className="inline-block w-[2px] h-[1em] bg-amber align-middle ml-0.5 animate-pulse" />}
            </div>
            {!streaming && !groundingChecking && message.citation && <CitationFooter citation={message.citation} numbers={citationNumbers} />}
          </div>
        )}
        {!streaming && !groundingChecking && message.content && (
          <div className="flex items-center gap-3 pl-1 text-[11px] text-ink-400">
            {message.at && <span>{fmtTime(message.at)}</span>}
            <CopyButton text={message.content} />
          </div>
        )}
        {hasResearchProgress && (
          <DeepResearchSuggestion
            suggestion={progress.deepSuggestion}
            streaming={streaming || groundingChecking}
            onStartDeep={onStartDeep}
          />
        )}
        {hasResearchProgress && !streaming && <ToolTraceFoldout trace={progress.trace} />}
      </div>
      {inspectorOpen && inspectorData && <RetrievalInspector data={inspectorData} onClose={() => setInspectorOpen(false)} />}
    </div>
  );
}
