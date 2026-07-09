import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Eye, Loader2, RefreshCcw, Settings, Sparkles, X } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const QUEUES = [
  ["all", "全部材料"],
  ["high_risk", "高风险"],
  ["multimodal_pending", "多模态待确认"],
  ["possibly_missed", "疑似遗漏"],
  ["sample", "抽样队列"],
  ["completed", "已完成"],
];

const SCAN_MODES = [
  ["evidence_only", "仅检查已有证据"],
  ["related_pages_assets", "检查相关页面与图表"],
  ["full_document", "全篇深度扫描"],
];

function statusText(status) {
  return {
    unreviewed: "未审阅",
    accepted: "已接受",
    edited: "已编辑",
    rejected: "已拒绝",
    rerun_required: "需重抽",
    locked: "已锁定",
    multimodal_pending: "多模态待确认",
    partially_reviewed: "部分审阅",
    reviewed: "已审阅",
    completed: "已完成",
  }[status] || status || "-";
}

function runStatusText(status) {
  return {
    completed: "已完成",
    completed_with_errors: "部分完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
  }[status] || status || "-";
}

function riskText(risk) {
  return { low: "低", medium: "中", high: "高", critical: "严重" }[risk] || risk || "-";
}

function riskClass(risk) {
  if (risk === "critical" || risk === "high") return "border-red-200 bg-red-50 text-red-700";
  if (risk === "medium") return "border-amber/30 bg-amber/10 text-amber";
  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

function materialName(row) {
  const identity = row?.recordIdentity || {};
  return identity.materialName || identity.membraneName || identity.sampleName || identity.paperId || row?.recordId || "-";
}

function compactJson(value) {
  if (value === null || value === undefined) return "空";
  if (typeof value !== "object") return String(value);
  const text = JSON.stringify(value, null, 2);
  return text.length > 5000 ? `${text.slice(0, 5000)}\n...` : text;
}

export default function ReviewTable({ task }) {
  const review = useAppStore((s) => s.structuredExtraction.review);
  const loadReview = useAppStore((s) => s.loadExtractionReview);
  const loadQueue = useAppStore((s) => s.loadReviewQueue);
  const loadTable = useAppStore((s) => s.loadReviewTable);
  const openRecord = useAppStore((s) => s.openReviewRecord);
  const startMultimodal = useAppStore((s) => s.startMultimodalReviewJob);
  const refreshJob = useAppStore((s) => s.refreshMultimodalReviewJob);
  const cancelJob = useAppStore((s) => s.cancelMultimodalReviewJob);
  const applySuggestion = useAppStore((s) => s.applyReviewSuggestion);
  const bulkSuggestions = useAppStore((s) => s.bulkReviewSuggestions);
  const openSettings = useAppStore((s) => s.openSettings);
  const [scanMode, setScanMode] = useState("related_pages_assets");

  useEffect(() => {
    if (!task?.taskId) return;
    loadReview(task.taskId).catch(() => {});
  }, [task?.taskId]);

  useEffect(() => {
    const job = review.activeMultimodalJob;
    if (!task?.taskId || !job?.jobId || !["queued", "running", "cancelling"].includes(job.status)) return undefined;
    const timer = window.setInterval(() => {
      refreshJob(task.taskId, job.jobId).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [task?.taskId, review.activeMultimodalJob?.jobId, review.activeMultimodalJob?.status]);

  const activeRow = useMemo(() => {
    const recordId = review.activeRecord?.recordId;
    return (review.queueRows || []).find((row) => row.recordId === recordId) || review.activeRecord;
  }, [review.queueRows, review.activeRecord]);

  const pendingSuggestionIds = useMemo(() => {
    return (review.queueRows || [])
      .flatMap((row) => row.suggestions || [])
      .filter((suggestion) => suggestion.status === "pending")
      .map((suggestion) => suggestion.suggestionId);
  }, [review.queueRows]);

  const activeJob = review.activeMultimodalJob;
  const activeJobRunning = activeJob && ["queued", "running", "cancelling"].includes(activeJob.status);

  const chooseRun = async (runId) => {
    await Promise.all([
      loadTable(task.taskId, { runId }),
      loadQueue(task.taskId, { runId, queue: review.selectedQueue }),
    ]);
  };

  const chooseQueue = async (queue) => {
    await loadQueue(task.taskId, { queue, offset: 0 });
  };

  const launchMultimodal = async () => {
    await startMultimodal(task.taskId, review.activeRunId, { scanMode, reason: "run level multimodal review" });
  };

  const refreshAll = () => loadReview(task.taskId).catch(() => {});

  if (review.runs.length === 0 && !review.loading) {
    return (
      <div className="rounded-lg border border-line bg-paper-0 p-8 text-center">
        <div className="text-[15px] font-medium text-ink-900">暂无可审阅的抽取结果</div>
        <div className="mt-2 text-[13px] text-ink-500">完成一次抽取运行后，审阅工作台会在这里生成。</div>
        <button type="button" onClick={refreshAll} className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100">
          <RefreshCcw size={14} />
          刷新
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {review.error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{review.error}</div>}

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[15px] font-medium text-ink-900">结果审阅控制中心</h2>
            <div className="mt-1 text-[12px] text-ink-500">按风险、覆盖状态和多模态建议组织审阅，不需要逐格扫完整宽表。</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={review.activeRunId || ""} onChange={(event) => chooseRun(event.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber">
              {(review.runs || []).map((run) => (
                <option key={run.runId} value={run.runId}>{run.runId} · {runStatusText(run.status)}</option>
              ))}
            </select>
            <button type="button" onClick={refreshAll} disabled={review.loading} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
              {review.loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
              刷新
            </button>
          </div>
        </div>

        <div className="grid gap-3 border-b border-line p-4 md:grid-cols-5">
          <Metric label="材料记录" value={review.summary?.recordCount ?? review.pagination.total ?? 0} />
          <Metric label="待确认建议" value={review.summary?.pendingSuggestionCount ?? 0} />
          <Metric label="可批量接受" value={review.summary?.bulkAcceptEligibleCount ?? 0} />
          <Metric label="高风险" value={(review.summary?.riskCounts?.high || 0) + (review.summary?.riskCounts?.critical || 0)} tone="danger" />
          <Metric label="普通未报道" value={review.summary?.coverageCounts?.notReported || 0} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <select value={scanMode} onChange={(event) => setScanMode(event.target.value)} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[12.5px] outline-none focus:border-amber">
              {SCAN_MODES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
            <button type="button" onClick={launchMultimodal} disabled={!review.activeRunId || review.multimodalStarting || activeJobRunning} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-2 text-[13px] text-white disabled:opacity-50">
              {review.multimodalStarting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              启动多模态复核
            </button>
            <button type="button" onClick={() => openSettings("models")} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100">
              <Settings size={14} />
              多模态模型设置
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => bulkSuggestions(task.taskId, { suggestionIds: pendingSuggestionIds, action: "accept", reason: "批量接受当前队列多模态建议" })}
              disabled={pendingSuggestionIds.length === 0 || review.saving}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 px-3 py-2 text-[13px] text-emerald-700 disabled:opacity-50"
            >
              <Check size={14} />
              批量接受多模态补充
            </button>
          </div>
        </div>

        {activeJob && (
          <div className="border-b border-line bg-paper-50 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-[13px] font-medium text-ink-900">多模态任务 {activeJob.jobId}</div>
                <div className="mt-1 text-[12px] text-ink-500">
                  {activeJob.status} · {activeJob.processedItemCount || 0}/{activeJob.totalItemCount || 0} · 建议 {activeJob.suggestionCount || 0} · 问题 {activeJob.issueCount || 0}
                </div>
              </div>
              {activeJobRunning && (
                <button type="button" onClick={() => cancelJob(task.taskId, activeJob.jobId)} disabled={review.multimodalCancelling} className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-3 py-2 text-[13px] text-red-600 disabled:opacity-50">
                  <X size={14} />
                  取消
                </button>
              )}
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-100">
              <div className="h-full bg-amber" style={{ width: `${Math.min(100, ((activeJob.processedItemCount || 0) / Math.max(1, activeJob.totalItemCount || 1)) * 100)}%` }} />
            </div>
          </div>
        )}

        <div className="grid min-h-[640px] grid-cols-1 lg:grid-cols-[190px_minmax(260px,360px)_1fr]">
          <aside className="border-b border-line bg-paper-50 p-3 lg:border-b-0 lg:border-r">
            <div className="mb-2 text-[11px] font-medium text-ink-400">审阅队列</div>
            <div className="space-y-1">
              {QUEUES.map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => chooseQueue(key)}
                  className={`flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-[13px] ${review.selectedQueue === key ? "bg-ink-900 text-paper-50" : "text-ink-600 hover:bg-paper-100 hover:text-ink-900"}`}
                >
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </aside>

          <section className="border-b border-line lg:border-b-0 lg:border-r">
            <div className="border-b border-line px-3 py-2 text-[12px] text-ink-500">当前队列 {review.queuePagination.total || 0} 条</div>
            <div className="max-h-[700px] overflow-y-auto">
              {(review.queueRows || []).map((row) => (
                <button
                  key={row.recordId}
                  type="button"
                  onClick={() => openRecord(task.taskId, row.recordId, row.runId)}
                  className={`block w-full border-b border-line px-3 py-3 text-left hover:bg-paper-50 ${review.activeRecord?.recordId === row.recordId ? "bg-amber/10" : ""}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium text-ink-900">{materialName(row)}</div>
                      <div className="mt-1 line-clamp-2 text-[11.5px] text-ink-500">{row.paper?.title || row.paperId}</div>
                    </div>
                    <span className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[11px] ${riskClass(row.riskLevel)}`}>{riskText(row.riskLevel)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {(row.suggestions || []).filter((s) => s.status === "pending").slice(0, 3).map((suggestion) => (
                      <span key={suggestion.suggestionId} className="rounded bg-paper-100 px-1.5 py-0.5 text-[10.5px] text-ink-500">{suggestion.fieldKey}</span>
                    ))}
                  </div>
                  <div className="mt-2 text-[11px] text-ink-400">{statusText(row.reviewStatus)}</div>
                </button>
              ))}
              {(!review.queueRows || review.queueRows.length === 0) && (
                <div className="p-6 text-center text-[13px] text-ink-500">当前队列没有记录</div>
              )}
            </div>
          </section>

          <MaterialDetail
            taskId={task.taskId}
            row={activeRow}
            events={review.events}
            saving={review.saving}
            onAcceptSuggestion={(suggestion) => applySuggestion(task.taskId, suggestion.suggestionId, "accept", { reason: "接受多模态建议" })}
            onRejectSuggestion={(suggestion) => applySuggestion(task.taskId, suggestion.suggestionId, "reject", { reason: "拒绝多模态建议" })}
          />
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, tone = "default" }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 p-3">
      <div className="text-[11px] text-ink-400">{label}</div>
      <div className={`mt-1 text-[20px] ${tone === "danger" ? "text-red-600" : "text-ink-900"}`}>{value}</div>
    </div>
  );
}

function MaterialDetail({ row, events, saving, onAcceptSuggestion, onRejectSuggestion }) {
  const [tab, setTab] = useState("effective");
  if (!row) {
    return (
      <section className="flex min-h-[520px] items-center justify-center p-6 text-[13px] text-ink-500">
        选择一条材料记录查看详情
      </section>
    );
  }
  const pendingSuggestions = (row.suggestions || []).filter((suggestion) => suggestion.status === "pending");
  return (
    <section className="min-w-0 p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-medium text-ink-900">{materialName(row)}</div>
          <div className="mt-1 max-w-2xl truncate text-[12px] text-ink-500">{row.paper?.title || row.paperId}</div>
        </div>
        <span className={`rounded-md border px-2 py-1 text-[12px] ${riskClass(row.riskLevel || row.reviewPriority)}`}>{riskText(row.riskLevel || row.reviewPriority)}</span>
      </div>

      {pendingSuggestions.length > 0 && (
        <div className="mb-4 rounded-md border border-amber/30 bg-amber/10 p-3">
          <div className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-ink-900">
            <Sparkles size={14} />
            多模态待确认
          </div>
          <div className="space-y-2">
            {pendingSuggestions.map((suggestion) => (
              <div key={suggestion.suggestionId} className="rounded-md border border-line bg-paper-0 p-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[12.5px] text-ink-800">{suggestion.fieldKey} · {suggestion.action}</div>
                    <div className="mt-1 text-[11.5px] text-ink-500">{suggestion.issueType || suggestion.coverageStatus || "建议复核"}</div>
                    {suggestion.provenance?.evidenceLocation && <div className="mt-1 text-[11.5px] text-ink-500">证据：{suggestion.provenance.evidenceLocation}</div>}
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button type="button" disabled={saving} onClick={() => onAcceptSuggestion(suggestion)} className="inline-flex items-center gap-1 rounded-md border border-emerald-200 px-2 py-1 text-[12px] text-emerald-700 disabled:opacity-50"><Check size={12} />接受</button>
                    <button type="button" disabled={saving} onClick={() => onRejectSuggestion(suggestion)} className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-[12px] text-red-600 disabled:opacity-50"><X size={12} />拒绝</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-3 flex gap-1 border-b border-line">
        {[
          ["effective", "有效 JSON"],
          ["base", "原始 JSON"],
          ["coverage", "覆盖状态"],
          ["events", "审阅事件"],
        ].map(([key, label]) => (
          <button key={key} type="button" onClick={() => setTab(key)} className={`border-b-2 px-3 py-2 text-[12.5px] ${tab === key ? "border-amber text-ink-900" : "border-transparent text-ink-500 hover:text-ink-900"}`}>{label}</button>
        ))}
      </div>

      {tab === "coverage" ? (
        <div className="grid gap-2">
          {Object.entries(row.coverage || {}).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between rounded-md border border-line bg-paper-50 px-3 py-2 text-[12.5px]">
              <span className="font-mono text-ink-700">{key}</span>
              <span className="text-ink-500">{value}</span>
            </div>
          ))}
          {(!row.coverage || Object.keys(row.coverage).length === 0) && <div className="text-[13px] text-ink-500">暂无覆盖状态</div>}
        </div>
      ) : tab === "events" ? (
        <div className="max-h-[520px] overflow-y-auto rounded-md border border-line">
          {(events || []).map((event) => (
            <div key={event.eventId} className="border-b border-line px-3 py-2 last:border-b-0">
              <div className="flex items-center gap-2 text-[12.5px] text-ink-800">
                {event.eventType?.includes("multimodal") ? <Sparkles size={13} /> : <Eye size={13} />}
                {event.eventType}
              </div>
              <div className="mt-1 text-[11.5px] text-ink-500">{event.reason || event.fieldKey}</div>
            </div>
          ))}
          {(!events || events.length === 0) && <div className="p-4 text-[13px] text-ink-500">暂无事件</div>}
        </div>
      ) : (
        <pre className="max-h-[560px] overflow-auto rounded-md border border-line bg-paper-50 p-3 font-mono text-[11.5px] leading-relaxed text-ink-800">
          {compactJson(tab === "base" ? row.baseData || row.data || {} : row.data || {})}
        </pre>
      )}

      {(row.issues || []).length > 0 && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3">
          <div className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-red-700">
            <AlertTriangle size={14} />
            风险提示
          </div>
          {(row.issues || []).map((issue) => (
            <div key={issue.suggestionId} className="text-[12px] text-red-700">{issue.fieldKey} · {issue.issueType || issue.action}</div>
          ))}
        </div>
      )}
    </section>
  );
}
