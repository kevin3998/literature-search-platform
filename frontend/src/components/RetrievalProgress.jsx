import React from "react";
import clsx from "clsx";
import { Check, Loader2, AlertTriangle, X, Circle } from "lucide-react";

// Block 2 §12: a polished, product-facing progress bar — observable task stages
// only, never the internal query plan / rewrites / scores. Derived from the
// streamed step / coverage / papers signals; the full detail lives behind the
// developer Retrieval Inspector.

const STAGES = [
  ["understand", "理解问题"],
  ["retrieve", "检索文献"],
  ["select", "筛选证据"],
  ["check", "检查证据"],
  ["compose", "组织回答"],
];

function computeStages({ steps = [], coverage, papers = [], streaming, answered }) {
  const cov = coverage || null;
  const hasCoverage = !!cov && (cov.status || cov.evidence_count != null);
  const searchStarted = steps.some((s) => /检索|search/i.test(s.label || "")) || hasCoverage || papers.length > 0;
  const searchDone = hasCoverage || papers.length > 0 || steps.some((s) => /检索|命中/.test(s.label || "") && s.status === "done");
  const covStatus = cov?.status;
  const breadthLimited = cov?.breadth_limited ?? cov?.breadth?.breadth_limited;
  const paperCount = papers.length;

  const status = {};
  const msg = {};

  status.understand = searchStarted || hasCoverage || answered || !streaming ? "done" : streaming ? "running" : "pending";
  msg.understand = status.understand === "done" ? "已识别问题类型" : "";

  if (searchDone) {
    status.retrieve = paperCount === 0 ? "warning" : "done";
    msg.retrieve = paperCount === 0 ? "未找到候选" : `已找到 ${paperCount} 篇候选`;
  } else if (searchStarted) {
    status.retrieve = "running";
    msg.retrieve = "正在查找本地文献库";
  } else {
    status.retrieve = !streaming && answered ? "skipped" : "pending";
    msg.retrieve = status.retrieve === "skipped" ? "复用已有证据" : "";
  }

  if (hasCoverage) {
    status.select = breadthLimited ? "warning" : "done";
    msg.select = breadthLimited ? "代表性样本" : "已筛选证据";
  } else if (searchDone) {
    status.select = "running";
    msg.select = "正在筛选";
  } else {
    status.select = status.retrieve === "skipped" ? "skipped" : "pending";
    msg.select = "";
  }

  if (hasCoverage) {
    status.check = covStatus === "sufficient" ? "done" : covStatus === "none" ? "failed" : "warning";
    msg.check = { sufficient: "证据较充分", partial: "可部分回答", weak: "证据偏少", none: "未找到可用证据" }[covStatus] || "";
  } else {
    status.check = "pending";
    msg.check = "";
  }

  if (!streaming && answered) {
    status.compose = "done";
    msg.compose = "已完成";
  } else if (answered && streaming) {
    status.compose = "running";
    msg.compose = "组织回答中";
  } else if (hasCoverage && covStatus !== "none") {
    status.compose = "running";
    msg.compose = "组织回答中";
  } else {
    status.compose = "pending";
    msg.compose = "";
  }

  return STAGES.map(([id, label]) => ({ id, label, status: status[id], message: msg[id] }));
}

function NodeIcon({ status }) {
  if (status === "running") return <Loader2 size={13} className="animate-spin text-amber" />;
  if (status === "done") return <Check size={13} className="text-teal" />;
  if (status === "warning") return <AlertTriangle size={12} className="text-amber-600" />;
  if (status === "failed") return <X size={12} className="text-red-500" />;
  return <Circle size={9} className={status === "skipped" ? "text-ink-300" : "text-ink-300"} />;
}

export default function RetrievalProgress({ steps, coverage, papers, streaming, answered, onInspect }) {
  const stages = computeStages({ steps, coverage, papers, streaming, answered });
  // Don't render an all-pending bar before anything happens.
  if (stages.every((s) => s.status === "pending")) return null;

  return (
    <div className="rounded-md border border-line bg-paper-0/60 px-3 py-2.5">
      <div className="flex items-start">
        {stages.map((stage, i) => (
          <React.Fragment key={stage.id}>
            <div className="flex flex-col items-center text-center" style={{ flex: "0 0 auto", width: 78 }}>
              <div
                className={clsx(
                  "w-6 h-6 rounded-full flex items-center justify-center border bg-paper-0",
                  stage.status === "done" && "border-teal/40",
                  stage.status === "running" && "border-amber/50",
                  stage.status === "warning" && "border-amber-600/40",
                  stage.status === "failed" && "border-red-300",
                  (stage.status === "pending" || stage.status === "skipped") && "border-line"
                )}
              >
                <NodeIcon status={stage.status} />
              </div>
              <div
                className={clsx(
                  "mt-1 text-[11px] leading-tight",
                  stage.status === "pending" || stage.status === "skipped" ? "text-ink-400" : "text-ink-700"
                )}
              >
                {stage.label}
              </div>
              {stage.message && <div className="text-[10px] text-ink-400 leading-tight mt-0.5">{stage.message}</div>}
            </div>
            {i < stages.length - 1 && (
              <div
                className={clsx(
                  "h-px mt-3 flex-1 min-w-[10px]",
                  stages[i + 1].status !== "pending" && stages[i + 1].status !== "skipped" ? "bg-ink-300" : "bg-line"
                )}
              />
            )}
          </React.Fragment>
        ))}
      </div>
      {onInspect && (
        <div className="mt-1.5 text-right">
          <button onClick={onInspect} className="text-[10.5px] text-ink-400 hover:text-amber-600 transition-colors">
            检索详情 →
          </button>
        </div>
      )}
    </div>
  );
}
