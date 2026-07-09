import React, { useMemo, useState } from "react";
import { Archive, Copy, Database, Plus, Trash2 } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const STATUS_LABELS = {
  draft: "草稿",
  collecting: "收集中",
  collection_ready: "集合就绪",
  schema_ready: "字段方案就绪",
  extracting: "抽取中",
  review_required: "待审阅",
  completed: "已完成",
  exported: "已导出",
  failed: "失败",
  archived: "已归档",
};

function fmtDate(value) {
  if (!value) return "暂无";
  return new Date(value * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function ExtractionTaskList() {
  const tasks = useAppStore((s) => s.structuredExtraction.tasks);
  const loading = useAppStore((s) => s.structuredExtraction.loading);
  const creating = useAppStore((s) => s.structuredExtraction.creating);
  const createExtractionTask = useAppStore((s) => s.createExtractionTask);
  const openExtractionTask = useAppStore((s) => s.openExtractionTask);
  const duplicateExtractionTask = useAppStore((s) => s.duplicateExtractionTask);
  const archiveExtractionTask = useAppStore((s) => s.archiveExtractionTask);
  const deleteExtractionTask = useAppStore((s) => s.deleteExtractionTask);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const canCreate = useMemo(() => draft.name.trim().length > 0 && !creating, [draft.name, creating]);

  const submit = async (e) => {
    e.preventDefault();
    if (!canCreate) return;
    await createExtractionTask({ name: draft.name.trim(), description: draft.description.trim() });
    setDraft({ name: "", description: "" });
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div>
            <h1 className="font-serif text-[24px] text-ink-900">数据抽取工作台</h1>
            <p className="text-[13px] text-ink-500 mt-1">按任务管理文献集合、抽取字段、抽取运行和导出产物。</p>
          </div>
        </div>

        <form onSubmit={submit} className="mb-5 rounded-lg border border-line bg-paper-0 p-4">
          <div className="grid grid-cols-[minmax(180px,1fr)_minmax(220px,1.4fr)_auto] gap-3 items-end">
            <label className="block">
              <span className="block text-[12px] text-ink-500 mb-1">任务名称</span>
              <input
                value={draft.name}
                onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber"
                placeholder="例如：膜材料性能数据抽取"
              />
            </label>
            <label className="block">
              <span className="block text-[12px] text-ink-500 mb-1">描述</span>
              <input
                value={draft.description}
                onChange={(e) => setDraft((prev) => ({ ...prev, description: e.target.value }))}
                className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber"
                placeholder="可选"
              />
            </label>
            <button
              type="submit"
              disabled={!canCreate}
              className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-2 text-[13px] text-white disabled:opacity-45"
            >
              <Plus size={15} />
              新建任务
            </button>
          </div>
        </form>

        {loading && <div className="text-[13px] text-ink-500">正在加载任务…</div>}
        {!loading && tasks.length === 0 && (
          <div className="rounded-lg border border-dashed border-line bg-paper-0 p-8 text-center">
            <Database size={28} className="mx-auto text-ink-300 mb-3" />
            <div className="text-[15px] text-ink-800">还没有数据抽取任务</div>
            <div className="text-[12.5px] text-ink-500 mt-1">先创建一个任务，后续再收集文献、定义抽取字段并运行抽取。</div>
          </div>
        )}

        {!loading && tasks.length > 0 && (
          <div className="rounded-lg border border-line bg-paper-0 overflow-hidden">
            <div className="grid grid-cols-[minmax(220px,1.4fr)_80px_80px_110px_120px_120px] gap-3 border-b border-line bg-paper-100 px-4 py-2.5 text-[11px] font-mono uppercase text-ink-500">
              <div>任务</div>
              <div>文献</div>
              <div>字段</div>
              <div>状态</div>
              <div>最近运行</div>
              <div className="text-right">操作</div>
            </div>
            {tasks.map((task) => (
              <button
                key={task.taskId}
                type="button"
                onClick={() => openExtractionTask(task.taskId)}
                className="w-full grid grid-cols-[minmax(220px,1.4fr)_80px_80px_110px_120px_120px] gap-3 px-4 py-3 text-left border-b border-line last:border-b-0 hover:bg-paper-50"
              >
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] text-ink-900">{task.name}</div>
                  <div className="truncate text-[12px] text-ink-500 mt-0.5">{task.description || task.workspaceRelPath}</div>
                </div>
                <div className="text-[13px] text-ink-700 self-center">{task.stats.paperCount}</div>
                <div className="text-[13px] text-ink-700 self-center">{task.stats.fieldCount}</div>
                <div className="text-[12px] text-ink-600 self-center">{STATUS_LABELS[task.status] || task.status}</div>
                <div className="text-[12px] text-ink-500 self-center">{fmtDate(task.lastRunAt)}</div>
                <div className="flex justify-end gap-1 self-center">
                  <IconAction title="复制" icon={Copy} onClick={() => duplicateExtractionTask(task.taskId)} />
                  <IconAction title="归档" icon={Archive} onClick={() => archiveExtractionTask(task.taskId, true)} />
                  <IconAction
                    title="删除"
                    icon={Trash2}
                    danger
                    onClick={() => {
                      if (window.confirm("删除该抽取任务？任务会从列表隐藏，后端保留软删除记录。")) deleteExtractionTask(task.taskId);
                    }}
                  />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function IconAction({ title, icon: Icon, onClick, danger = false }) {
  return (
    <span
      role="button"
      tabIndex={0}
      title={title}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-md ${danger ? "text-red-500 hover:bg-red-50" : "text-ink-500 hover:bg-paper-100"}`}
    >
      <Icon size={14} />
    </span>
  );
}
