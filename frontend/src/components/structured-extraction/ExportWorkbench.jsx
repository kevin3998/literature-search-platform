import React, { useEffect, useMemo } from "react";
import { Download, FileJson, FileSpreadsheet, FileText, Loader2, RefreshCcw, Send } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

const FORMAT_LABELS = {
  csv: "CSV",
  json: "JSON",
  xlsx: "XLSX",
  markdown: "Markdown",
};

const FORMAT_ICONS = {
  csv: FileSpreadsheet,
  json: FileJson,
  xlsx: FileSpreadsheet,
  markdown: FileText,
};

function fmtDate(value) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString("zh-CN");
}

function runStatusText(status) {
  return {
    completed: "已完成",
    completed_with_errors: "部分完成",
    queued: "排队中",
    running: "运行中",
    failed: "失败",
    cancelled: "已取消",
  }[status] || status || "-";
}

function reviewStatusText(status) {
  return {
    unreviewed: "未审阅",
    partially_reviewed: "部分审阅",
    fully_reviewed: "已全部审阅",
    accepted: "已接受",
    edited: "已编辑",
    rejected: "已拒绝",
    locked: "已锁定",
  }[status] || status;
}

function warningText(warning) {
  if (!warning) return "";
  if (typeof warning === "string") return warning;
  return warning.message || warning.warning || warning.reason || JSON.stringify(warning);
}

export default function ExportWorkbench({ task }) {
  const exportsState = useAppStore((s) => s.structuredExtraction.exports);
  const loadExports = useAppStore((s) => s.loadExtractionExports);
  const previewExport = useAppStore((s) => s.previewExtractionExport);
  const createExport = useAppStore((s) => s.createExtractionExport);
  const downloadExport = useAppStore((s) => s.downloadExtractionExport);
  const setFormats = useAppStore((s) => s.setExtractionExportFormats);
  const setRun = useAppStore((s) => s.setExtractionExportRun);

  useEffect(() => {
    if (!task?.taskId) return;
    loadExports(task.taskId).catch(() => {});
  }, [task?.taskId]);

  const selectedFormats = useMemo(
    () => Object.entries(exportsState.selectedFormats || {}).filter(([, enabled]) => enabled).map(([format]) => format),
    [exportsState.selectedFormats]
  );

  const selectedRun = (exportsState.runs || []).find((run) => run.runId === exportsState.selectedRunId) || null;
  const preview = exportsState.preview;
  const warnings = preview?.warnings || [];
  const canCreate = !!exportsState.selectedRunId && selectedFormats.length > 0 && !exportsState.creating;

  const changeRun = async (runId) => {
    setRun(runId);
    if (runId) await previewExport(task.taskId, runId);
  };

  const generate = async () => {
    await createExport(task.taskId, { runId: exportsState.selectedRunId, formats: selectedFormats });
  };

  if (!exportsState.loading && (exportsState.runs || []).length === 0) {
    return (
      <div className="rounded-lg border border-line bg-paper-0 p-8 text-center">
        <div className="text-[15px] font-medium text-ink-900">暂无可导出的抽取结果</div>
        <div className="mt-2 text-[13px] text-ink-500">完成一次抽取运行后，可以在这里生成导出快照。</div>
        <button type="button" onClick={() => loadExports(task.taskId)} className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100">
          <RefreshCcw size={14} />
          刷新
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {exportsState.error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{exportsState.error}</div>}

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">生成导出</h2>
            <div className="mt-1 text-[12px] text-ink-500">
              {selectedRun ? `${selectedRun.runId} · ${runStatusText(selectedRun.status)}` : "请选择抽取运行"}
            </div>
          </div>
          <button type="button" onClick={() => loadExports(task.taskId)} disabled={exportsState.loading} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
            {exportsState.loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
            刷新
          </button>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(280px,1.4fr)_auto]">
          <select
            value={exportsState.selectedRunId || ""}
            onChange={(event) => changeRun(event.target.value)}
            className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700 outline-none focus:border-amber"
          >
            {(exportsState.runs || []).map((run) => (
              <option key={run.runId} value={run.runId}>
                {run.runId} · {runStatusText(run.status)} · {run.stats?.recordCount || 0} 条记录
              </option>
            ))}
          </select>

          <div className="flex flex-wrap gap-2">
            {Object.entries(FORMAT_LABELS).map(([format, label]) => {
              const Icon = FORMAT_ICONS[format];
              return (
                <label key={format} className="inline-flex items-center gap-2 rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] text-ink-700">
                  <input
                    type="checkbox"
                    checked={!!exportsState.selectedFormats?.[format]}
                    onChange={(event) => setFormats({ [format]: event.target.checked })}
                  />
                  <Icon size={14} className="text-ink-500" />
                  {label}
                </label>
              );
            })}
          </div>

          <button type="button" onClick={generate} disabled={!canCreate} className="inline-flex items-center justify-center gap-1.5 rounded-md bg-ink-900 px-4 py-2 text-[13px] text-white disabled:opacity-50">
            {exportsState.creating ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            生成导出
          </button>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="记录数" value={preview?.recordCount ?? 0} />
        <Metric label="字段数" value={preview?.fieldCount ?? 0} />
        <Metric label="审阅状态" value={Object.keys(preview?.reviewStatusCounts || {}).length} />
        <Metric label="警告" value={warnings.length} />
      </div>

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-[14px] font-medium text-ink-900">导出预览</h2>
        </div>
        <div className="grid gap-4 p-4 md:grid-cols-2">
          <div className="rounded-md border border-line bg-paper-50 p-3">
            <div className="text-[11px] uppercase text-ink-400">审阅状态统计</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(preview?.reviewStatusCounts || {}).map(([status, count]) => (
                <span key={status} className="rounded bg-paper-100 px-2 py-1 text-[12px] text-ink-700">
                  {reviewStatusText(status)}：{count}
                </span>
              ))}
              {Object.keys(preview?.reviewStatusCounts || {}).length === 0 && <span className="text-[12px] text-ink-500">暂无统计</span>}
            </div>
          </div>
          <div className="rounded-md border border-line bg-paper-50 p-3">
            <div className="text-[11px] uppercase text-ink-400">导出警告</div>
            <div className="mt-2 space-y-1 text-[12px] text-ink-600">
              {warnings.map((warning, index) => <div key={`${warningText(warning)}-${index}`}>{warningText(warning)}</div>)}
              {warnings.length === 0 && <span className="text-ink-500">无</span>}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">导出历史</h2>
            <div className="mt-1 text-[12px] text-ink-500">{exportsState.items.length} 个快照</div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-[12.5px]">
            <thead className="bg-paper-50 text-[11px] uppercase text-ink-400">
              <tr>
                <th className="min-w-[110px] px-3 py-2">导出 ID</th>
                <th className="min-w-[130px] px-3 py-2">运行</th>
                <th className="px-3 py-2">记录</th>
                <th className="px-3 py-2">字段</th>
                <th className="min-w-[180px] px-3 py-2">格式</th>
                <th className="min-w-[160px] px-3 py-2">创建时间</th>
                <th className="min-w-[260px] px-3 py-2">下载</th>
              </tr>
            </thead>
            <tbody>
              {exportsState.items.map((item) => (
                <tr key={item.exportId} className="border-t border-line align-top hover:bg-paper-50">
                  <td className="px-3 py-3 font-mono text-[12px] text-ink-800">{item.exportId}</td>
                  <td className="px-3 py-3 font-mono text-[12px] text-ink-700">{item.runId}</td>
                  <td className="px-3 py-3 text-ink-700">{item.recordCount}</td>
                  <td className="px-3 py-3 text-ink-700">{item.fieldCount}</td>
                  <td className="px-3 py-3 text-ink-700">{(item.formats || []).map((format) => FORMAT_LABELS[format] || format).join(", ")}</td>
                  <td className="px-3 py-3 text-ink-600">{fmtDate(item.createdAt)}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {(item.formats || []).map((format) => (
                        <button
                          key={format}
                          type="button"
                          onClick={() => downloadExport(task.taskId, item.exportId, format)}
                          disabled={exportsState.downloading}
                          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11.5px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
                        >
                          <Download size={12} />
                          {FORMAT_LABELS[format] || format}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {exportsState.items.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-[13px] text-ink-500">
                    暂无导出快照
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
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
