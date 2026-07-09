import React, { useEffect, useState } from "react";
import { Archive, ArrowLeft, Copy, Save, Trash2 } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import CollectionBuilder from "./CollectionBuilder";
import ExportWorkbench from "./ExportWorkbench";
import ExtractionPreparation from "./ExtractionPreparation";
import ReviewTable from "./ReviewTable";
import SchemaDesigner from "./SchemaDesigner";

const TABS = [
  { key: "overview", label: "概览", enabled: true },
  { key: "collection", label: "文献收集", enabled: true },
  { key: "schema", label: "抽取字段", enabled: true },
  { key: "runs", label: "抽取运行", enabled: true },
  { key: "review", label: "结果审阅", enabled: true },
  { key: "exports", label: "导出", enabled: true },
];

const STATUS_LABELS = {
  draft: "草稿",
  collecting: "收集中",
  collection_ready: "文献集合就绪",
  schema_ready: "字段方案就绪",
  extracting: "抽取中",
  review_required: "待审阅",
  completed: "已完成",
  exported: "已导出",
  failed: "失败",
  archived: "已归档",
  deleted: "已删除",
};

function fmtDate(value) {
  if (!value) return "暂无";
  return new Date(value * 1000).toLocaleString("zh-CN");
}

export default function ExtractionTaskOverview() {
  const task = useAppStore((s) => s.structuredExtraction.activeTask);
  const backToExtractionTasks = useAppStore((s) => s.backToExtractionTasks);
  const updateExtractionTask = useAppStore((s) => s.updateExtractionTask);
  const duplicateExtractionTask = useAppStore((s) => s.duplicateExtractionTask);
  const archiveExtractionTask = useAppStore((s) => s.archiveExtractionTask);
  const deleteExtractionTask = useAppStore((s) => s.deleteExtractionTask);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [activeTab, setActiveTab] = useState("overview");

  useEffect(() => {
    setDraft({ name: task?.name || "", description: task?.description || "" });
  }, [task?.taskId, task?.name, task?.description]);

  useEffect(() => {
    setActiveTab("overview");
  }, [task?.taskId]);

  if (!task) {
    return (
      <div className="flex-1 flex items-center justify-center text-[13px] text-ink-500">
        未选择任务
      </div>
    );
  }

  const save = async () => {
    await updateExtractionTask(task.taskId, { name: draft.name.trim() || task.name, description: draft.description.trim() });
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between gap-4 mb-5">
          <button type="button" onClick={backToExtractionTasks} className="inline-flex items-center gap-1.5 text-[13px] text-ink-600 hover:text-ink-900">
            <ArrowLeft size={15} />
            返回任务列表
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={() => duplicateExtractionTask(task.taskId)} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[12.5px] text-ink-700 hover:bg-paper-100">
              <Copy size={14} />
              复制
            </button>
            <button type="button" onClick={() => archiveExtractionTask(task.taskId, true)} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[12.5px] text-ink-700 hover:bg-paper-100">
              <Archive size={14} />
              归档
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm("删除该抽取任务？任务会从列表隐藏，后端保留软删除记录。")) deleteExtractionTask(task.taskId);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-3 py-1.5 text-[12.5px] text-red-600 hover:bg-red-50"
            >
              <Trash2 size={14} />
              删除
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-line bg-paper-0 p-5 mb-5">
          <div className="grid grid-cols-[1fr_auto] gap-4 items-start">
            <div>
              <input
                value={draft.name}
                onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                className="w-full bg-transparent font-serif text-[24px] text-ink-900 outline-none border-b border-transparent focus:border-amber"
              />
              <textarea
                value={draft.description}
                onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
                rows={2}
                className="mt-2 w-full resize-none rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber"
                placeholder="添加任务描述"
              />
            </div>
            <button type="button" onClick={save} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-2 text-[13px] text-white">
              <Save size={15} />
              保存
            </button>
          </div>
        </div>

        <div className="flex gap-1 border-b border-line mb-5">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              disabled={!tab.enabled}
              onClick={() => tab.enabled && setActiveTab(tab.key)}
              className={`px-3 py-2 text-[13px] border-b-2 ${activeTab === tab.key ? "border-amber text-ink-900" : !tab.enabled ? "border-transparent text-ink-400 opacity-60" : "border-transparent text-ink-600 hover:text-ink-900"}`}
              title={tab.enabled ? tab.label : "后续阶段"}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "collection" ? (
          <CollectionBuilder task={task} />
        ) : activeTab === "schema" ? (
          <SchemaDesigner task={task} />
        ) : activeTab === "runs" ? (
          <ExtractionPreparation task={task} />
        ) : activeTab === "review" ? (
          <ReviewTable task={task} />
        ) : activeTab === "exports" ? (
          <ExportWorkbench task={task} />
        ) : (
          <>
            <div className="grid grid-cols-4 gap-3 mb-5">
              <Metric label="文献数" value={task.stats.paperCount} />
              <Metric label="字段数" value={task.stats.fieldCount} />
              <Metric label="运行次数" value={task.stats.runCount} />
              <Metric label="导出次数" value={task.stats.exportCount} />
            </div>

            <div className="rounded-lg border border-line bg-paper-0 p-5">
              <h2 className="text-[15px] font-medium text-ink-900 mb-3">任务概览</h2>
              <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px]">
                <Info label="任务 ID" value={task.taskId} mono />
                <Info label="状态" value={STATUS_LABELS[task.status] || task.status} />
                <Info label="任务目录" value={task.workspaceRelPath} mono />
                <Info label="文献集合版本" value={task.currentCollectionVersion || "尚未创建"} />
                <Info label="字段方案版本" value={task.currentSchemaVersion || "尚未创建"} />
                <Info label="最近运行" value={fmtDate(task.lastRunAt)} />
                <Info label="创建时间" value={fmtDate(task.createdAt)} />
                <Info label="更新时间" value={fmtDate(task.updatedAt)} />
              </div>
              <div className="mt-5 rounded-md border border-dashed border-line bg-paper-50 p-4 text-[12.5px] text-ink-500">
                文献收集、抽取字段、抽取运行、结果审阅与导出已可用。导出会保存为不可变快照，后续审阅修改不会影响已生成文件。
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="font-mono text-[11px] uppercase text-ink-400">{label}</div>
      <div className="mt-1 text-[22px] text-ink-900">{value}</div>
    </div>
  );
}

function Info({ label, value, mono = false }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-ink-400">{label}</div>
      <div className={`truncate text-ink-800 ${mono ? "font-mono text-[12px]" : ""}`}>{value}</div>
    </div>
  );
}
