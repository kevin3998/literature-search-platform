import React, { useEffect, useMemo } from "react";
import { FileCode, Layers, Loader2, PackageCheck, Play, RefreshCcw, RotateCcw, Square, TriangleAlert } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import PromptContractPreview from "./PromptContractPreview";

function versionLabel(value) {
  return value || "尚未创建";
}

function countAssets(item) {
  return (item.tables?.length || 0) + (item.figures?.length || 0);
}

const ACTIVE_RUN_STATUSES = new Set(["queued", "running", "cancelling"]);
const ACTIVE_BUILD_STATUSES = new Set(["queued", "running", "cancelling"]);

function statusLabel(status) {
  const map = {
    queued: "排队中",
    running: "运行中",
    completed: "已完成",
    completed_with_errors: "部分完成",
    failed: "失败",
    interrupted: "已中断",
    cancelling: "取消中",
    cancelled: "已取消",
  };
  return map[status] || status || "-";
}

function buildStatusLabel(status) {
  const map = {
    queued: "排队中",
    running: "构建中",
    completed: "已完成",
    failed: "失败",
    cancelling: "取消中",
    cancelled: "已取消",
    interrupted: "已中断",
  };
  return map[status] || status || "-";
}

function buildPhaseLabel(phase) {
  const map = {
    resolving_inputs: "检查输入",
    loading_collection: "读取集合",
    building_items: "构建证据项",
    finalizing: "写入版本",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
  };
  return map[phase] || phase || "-";
}

function formatError(error) {
  if (!error) return "-";
  if (typeof error === "string") return error;
  const reason = error.reason || "error";
  return error.detail ? `${reason}：${error.detail}` : reason;
}

function formatElapsed(startedAt, fallbackAt) {
  const start = startedAt || fallbackAt;
  if (!start) return "-";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - start));
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export default function ExtractionPreparation({ task }) {
  const preparation = useAppStore((s) => s.structuredExtraction.preparation);
  const runs = useAppStore((s) => s.structuredExtraction.runs);
  const loadPreparation = useAppStore((s) => s.loadExtractionPreparation);
  const compilePromptContract = useAppStore((s) => s.compileExtractionPromptContract);
  const buildEvidencePacket = useAppStore((s) => s.buildExtractionEvidencePacket);
  const loadBuildJob = useAppStore((s) => s.loadExtractionEvidencePacketBuildJob);
  const cancelBuildJob = useAppStore((s) => s.cancelExtractionEvidencePacketBuildJob);
  const loadItems = useAppStore((s) => s.loadExtractionEvidencePacketItems);
  const loadRuns = useAppStore((s) => s.loadExtractionRuns);
  const startRun = useAppStore((s) => s.startExtractionRun);
  const loadRunDetail = useAppStore((s) => s.loadExtractionRunDetail);
  const cancelRun = useAppStore((s) => s.cancelExtractionRun);
  const loadRecovery = useAppStore((s) => s.loadExtractionRunRecovery);
  const resumeRun = useAppStore((s) => s.resumeExtractionRun);

  useEffect(() => {
    if (!task?.taskId) return;
    loadPreparation(task.taskId).catch(() => {});
    loadRuns(task.taskId).catch(() => {});
  }, [task?.taskId]);

  const latestContract = preparation.activePromptContract || preparation.promptContracts[0] || null;
  const latestPacket = preparation.activeEvidencePacket || preparation.evidencePackets[0] || null;
  const activeBuildJob = preparation.activeBuildJob || preparation.buildJobs.find((job) => ACTIVE_BUILD_STATUSES.has(job.status)) || null;
  const activeRun = runs.activeRun || runs.items[0] || null;
  const canPrepare = !!task.currentCollectionVersion && !!task.currentSchemaVersion;
  const canBuild = canPrepare && !!latestContract?.promptContractVersion;
  const canStartRun = canBuild && !!latestPacket?.packetVersion && !runs.starting;
  const packetWarnings = latestPacket?.warnings || [];
  const runStats = activeRun?.stats || {};
  const itemTotal = runStats.packetItemCount || 0;
  const itemDone = (runStats.completedItemCount || 0) + (runStats.failedItemCount || 0);
  const progressValue = itemTotal ? Math.round((itemDone / itemTotal) * 100) : 0;
  const activeRunIsLive = ACTIVE_RUN_STATUSES.has(activeRun?.status);
  const activeBuildIsLive = ACTIVE_BUILD_STATUSES.has(activeBuildJob?.status);
  const buildTotal = activeBuildJob?.totalItemCount || 0;
  const buildDone = activeBuildJob?.processedItemCount || 0;
  const buildProgress = buildTotal ? Math.round((buildDone / buildTotal) * 100) : 0;
  const recovery = runs.recovery?.runId === activeRun?.runId ? runs.recovery : null;
  const itemWarningCount = useMemo(
    () => (preparation.packetItems || []).filter((item) => (item.warnings || []).length > 0).length,
    [preparation.packetItems]
  );

  useEffect(() => {
    if (!task?.taskId || !activeRun?.runId || !activeRunIsLive) return undefined;
    const timer = window.setInterval(() => {
      loadRunDetail(task.taskId, activeRun.runId).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [task?.taskId, activeRun?.runId, activeRun?.status]);

  useEffect(() => {
    if (!task?.taskId || !activeBuildJob?.buildJobId || !activeBuildIsLive) return undefined;
    const timer = window.setInterval(() => {
      loadBuildJob(task.taskId, activeBuildJob.buildJobId).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [task?.taskId, activeBuildJob?.buildJobId, activeBuildJob?.status]);

  const compile = async () => {
    await compilePromptContract(task.taskId, {
      collectionVersion: task.currentCollectionVersion,
      schemaVersion: task.currentSchemaVersion,
    });
  };

  const build = async () => {
    await buildEvidencePacket(task.taskId, {
      collectionVersion: task.currentCollectionVersion,
      schemaVersion: task.currentSchemaVersion,
      promptContractVersion: latestContract?.promptContractVersion,
      maxChunksPerGroup: 6,
      maxCharsPerChunk: 1800,
      includeAssets: true,
    });
  };

  const start = async () => {
    await startRun(task.taskId, {
      collectionVersion: task.currentCollectionVersion,
      schemaVersion: task.currentSchemaVersion,
      promptContractVersion: latestContract?.promptContractVersion,
      packetVersion: latestPacket?.packetVersion,
    });
  };

  if (!canPrepare) {
    return (
      <div className="rounded-lg border border-line bg-paper-0 p-8 text-center">
        <div className="text-[15px] font-medium text-ink-900">需要先冻结文献集合和字段方案</div>
        <div className="mt-2 text-[13px] text-ink-500">
          抽取运行前置准备需要当前任务同时拥有文献集合版本与字段方案版本。
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {preparation.error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {preparation.error}
        </div>
      )}

      {runs.error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
          {runs.error}
        </div>
      )}

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">抽取准备</h2>
            <div className="mt-1 text-[12px] text-ink-500">
              {versionLabel(task.currentCollectionVersion)} + {versionLabel(task.currentSchemaVersion)}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => loadPreparation(task.taskId)}
              disabled={preparation.loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
            >
              {preparation.loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCcw size={15} />}
              刷新
            </button>
            <button
              type="button"
              onClick={compile}
              disabled={preparation.compiling}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
            >
              {preparation.compiling ? <Loader2 size={15} className="animate-spin" /> : <FileCode size={15} />}
              编译提示词契约
            </button>
            <button
              type="button"
              onClick={build}
              disabled={!canBuild || activeBuildIsLive || preparation.building}
              className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-2 text-[13px] text-white disabled:opacity-50"
            >
              {activeBuildIsLive || preparation.building ? <Loader2 size={15} className="animate-spin" /> : <PackageCheck size={15} />}
              {activeBuildJob && !activeBuildIsLive ? "重新构建证据包" : "构建证据包"}
            </button>
            {activeBuildIsLive && (
              <button
                type="button"
                onClick={() => cancelBuildJob(task.taskId, activeBuildJob.buildJobId)}
                disabled={preparation.cancellingBuild}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-3 py-2 text-[13px] text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                {preparation.cancellingBuild ? <Loader2 size={15} className="animate-spin" /> : <Square size={15} />}
                取消构建
              </button>
            )}
          </div>
        </div>
      </section>

      {activeBuildJob && (
        <section className="rounded-lg border border-line bg-paper-0 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[14px] font-medium text-ink-900">证据包构建进度</h2>
              <div className="mt-1 text-[12px] text-ink-500">
                {activeBuildJob.buildJobId} · {buildStatusLabel(activeBuildJob.status)} · {buildPhaseLabel(activeBuildJob.phase)}
              </div>
            </div>
            <div className="text-right text-[12px] text-ink-500">
              <div>目标版本：{activeBuildJob.targetPacketVersion || "-"}</div>
              <div>结果版本：{activeBuildJob.resultPacketVersion || "-"}</div>
            </div>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-paper-100">
            <div className="h-full rounded-full bg-ink-900 transition-all" style={{ width: `${buildProgress}%` }} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-5">
            <Metric label="进度" value={`${buildDone} / ${buildTotal || "-"}`} />
            <Metric label="完成率" value={`${buildProgress}%`} />
            <Metric label="当前文献" value={activeBuildJob.currentPaperId || "-"} />
            <Metric label="当前字段组" value={activeBuildJob.currentFieldGroup || "-"} />
            <Metric label="耗时" value={formatElapsed(activeBuildJob.startedAt, activeBuildJob.createdAt)} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <Metric label="查询模式" value={activeBuildJob.currentQueryMode || "-"} />
            <Metric label="平均文本块" value={activeBuildJob.avgChunksPerItem ?? 0} />
            <Metric label="慢项数量" value={activeBuildJob.slowItemCount ?? 0} />
            <Metric label="上一项耗时" value={activeBuildJob.lastItemSeconds != null ? `${activeBuildJob.lastItemSeconds}s` : "-"} />
          </div>
          <div className="mt-3 rounded-md border border-line bg-paper-50 px-3 py-2 text-[12.5px] text-ink-600">
            警告：{activeBuildJob.warningCount || 0}
            {activeBuildJob.error?.reason ? ` · 错误：${activeBuildJob.error.reason}` : ""}
          </div>
        </section>
      )}

      <div className="grid gap-3 md:grid-cols-5">
        <Metric label="提示词契约" value={latestContract?.promptContractVersion || "-"} />
        <Metric label="证据包" value={latestPacket?.packetVersion || "-"} />
        <Metric label="文献数" value={latestPacket?.paperCount ?? task.stats.paperCount ?? 0} />
        <Metric label="字段组" value={latestPacket?.fieldGroupCount ?? 0} />
        <Metric label="证据项" value={latestPacket?.itemCount ?? 0} />
      </div>

      <PromptContractPreview contract={latestContract} />

      {(packetWarnings.length > 0 || itemWarningCount > 0) && (
        <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[13px] text-ink-700">
          <div className="flex items-center gap-1.5 font-medium">
            <TriangleAlert size={14} />
            构建警告
          </div>
          <div className="mt-1 text-[12.5px] text-ink-600">
            证据包警告：{packetWarnings.length} · 条目警告：{itemWarningCount}
          </div>
        </div>
      )}

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">证据包条目</h2>
            <div className="mt-1 text-[12px] text-ink-500">
              {latestPacket?.packetVersion
                ? `${latestPacket.packetVersion} · ${preparation.packetItems.length} / ${preparation.packetItemsPagination?.total ?? preparation.packetItems.length} 个条目`
                : "尚未构建证据包"}
            </div>
          </div>
          {latestPacket?.packetVersion && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => loadItems(task.taskId, latestPacket.packetVersion, { offset: Math.max(0, (preparation.packetItemsPagination?.offset || 0) - (preparation.packetItemsPagination?.limit || 200)) })}
                disabled={preparation.loading || (preparation.packetItemsPagination?.offset || 0) <= 0}
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={() => loadItems(task.taskId, latestPacket.packetVersion)}
                disabled={preparation.loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
              >
                {preparation.loading ? <Loader2 size={13} className="animate-spin" /> : <Layers size={13} />}
                刷新条目
              </button>
              <button
                type="button"
                onClick={() => loadItems(task.taskId, latestPacket.packetVersion, { offset: (preparation.packetItemsPagination?.offset || 0) + (preparation.packetItemsPagination?.limit || 200) })}
                disabled={
                  preparation.loading ||
                  (preparation.packetItemsPagination?.offset || 0) + (preparation.packetItemsPagination?.limit || 200) >= (preparation.packetItemsPagination?.total || 0)
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-[12.5px]">
            <thead className="bg-paper-50 text-[11px] uppercase text-ink-400">
              <tr>
                <th className="min-w-[150px] px-3 py-2">文献 ID</th>
                <th className="min-w-[140px] px-3 py-2">字段组</th>
                <th className="min-w-[220px] px-3 py-2">字段键</th>
                <th className="px-3 py-2">文本块</th>
                <th className="px-3 py-2">资产</th>
                <th className="min-w-[180px] px-3 py-2">警告</th>
              </tr>
            </thead>
            <tbody>
              {preparation.packetItems.map((item) => (
                <tr key={item.packetItemId} className="border-t border-line align-top">
                  <td className="px-3 py-2 font-mono text-[12px] text-ink-700">{item.paperId}</td>
                  <td className="px-3 py-2 font-mono text-[12px] text-ink-700">{item.fieldGroup}</td>
                  <td className="px-3 py-2 text-ink-700">{(item.fieldKeys || []).join(", ") || "-"}</td>
                  <td className="px-3 py-2 text-ink-700">{item.chunks?.length || 0}</td>
                  <td className="px-3 py-2 text-ink-700">{countAssets(item)}</td>
                  <td className="px-3 py-2 text-ink-600">{(item.warnings || []).join(", ") || "-"}</td>
                </tr>
              ))}
              {preparation.packetItems.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-[13px] text-ink-500">
                    暂无证据包条目
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-paper-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">抽取运行</h2>
            <div className="mt-1 text-[12px] text-ink-500">
              {activeRun?.runId ? `${activeRun.runId} · ${statusLabel(activeRun.status)}` : "尚未启动运行"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => loadRuns(task.taskId)}
              disabled={runs.loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
            >
              {runs.loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
              刷新运行
            </button>
            {activeRunIsLive && (
              <button
                type="button"
                onClick={() => cancelRun(task.taskId, activeRun.runId)}
                disabled={runs.cancelling}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-2.5 py-1.5 text-[12px] text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                {runs.cancelling ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                取消
              </button>
            )}
            {activeRun?.runId && (
              <button
                type="button"
                onClick={() => loadRecovery(task.taskId, activeRun.runId)}
                disabled={runs.loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-50"
              >
                {runs.loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCcw size={13} />}
                检查恢复状态
              </button>
            )}
            {recovery?.resumable && (
              <button
                type="button"
                onClick={() => resumeRun(task.taskId, activeRun.runId, { retryFailedItems: true, reason: "manual_resume" })}
                disabled={runs.resuming}
                className="inline-flex items-center gap-1.5 rounded-md border border-amber/40 bg-amber/10 px-2.5 py-1.5 text-[12px] text-ink-800 hover:bg-amber/20 disabled:opacity-50"
              >
                {runs.resuming ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
                续跑当前运行
              </button>
            )}
            <button
              type="button"
              onClick={start}
              disabled={!canStartRun}
              className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-1.5 text-[12px] text-white disabled:opacity-50"
            >
              {runs.starting ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              启动抽取
            </button>
          </div>
        </div>

        <div className="grid gap-3 border-b border-line p-4 md:grid-cols-5">
          <Metric label="运行状态" value={statusLabel(activeRun?.status)} />
          <Metric label="进度" value={`${progressValue}%`} />
          <Metric label="失败条目" value={runStats.failedItemCount ?? 0} />
          <Metric label="记录数" value={runStats.recordCount ?? 0} />
          <Metric label="模型" value={activeRun?.modelSnapshot?.model || "-"} />
        </div>

        {activeRun?.error && (
          <div className="mx-4 mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">
            {formatError(activeRun.error)}
          </div>
        )}

        {recovery && (
          <div className={`mx-4 mt-3 rounded-md border px-3 py-2 text-[12.5px] ${recovery.resumable ? "border-amber/30 bg-amber/10 text-ink-700" : "border-line bg-paper-50 text-ink-600"}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-medium">{recovery.resumable ? "可续跑" : "不可续跑"}</div>
              <div className="font-mono text-[11.5px] text-ink-500">{recovery.runId}</div>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <span>已完成 {recovery.completedItemCount}</span>
              <span>失败 {recovery.failedItemCount}</span>
              <span>中断 {recovery.interruptedItemCount}</span>
              <span>待处理 {recovery.remainingItemCount}</span>
              <span>记录 {recovery.recordCount}</span>
            </div>
            {recovery.blockers?.length > 0 && (
              <div className="mt-1 text-[12px] text-red-600">阻塞：{recovery.blockers.join(", ")}</div>
            )}
          </div>
        )}

        <div className="grid gap-0 lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="border-b border-line lg:border-b-0 lg:border-r">
            <div className="px-4 py-3 text-[12px] font-medium uppercase text-ink-400">运行历史</div>
            <div className="max-h-[360px] overflow-auto">
              {(runs.items || []).map((run) => (
                <button
                  type="button"
                  key={run.runId}
                  onClick={() => loadRunDetail(task.taskId, run.runId)}
                  className={`block w-full border-t border-line px-4 py-3 text-left hover:bg-paper-50 ${activeRun?.runId === run.runId ? "bg-paper-50" : ""}`}
                >
                  <div className="font-mono text-[12px] text-ink-800">{run.runId}</div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[12px] text-ink-500">
                    <span>{statusLabel(run.status)}</span>
                    <span>{run.stats?.recordCount ?? 0} 条记录</span>
                  </div>
                </button>
              ))}
              {runs.items.length === 0 && <div className="border-t border-line px-4 py-8 text-center text-[13px] text-ink-500">暂无运行</div>}
            </div>
          </div>

          <div className="min-w-0">
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-left text-[12.5px]">
                <thead className="bg-paper-50 text-[11px] uppercase text-ink-400">
                  <tr>
                    <th className="min-w-[150px] px-3 py-2">文献 ID</th>
                    <th className="min-w-[140px] px-3 py-2">字段组</th>
                    <th className="px-3 py-2">状态</th>
                    <th className="min-w-[200px] px-3 py-2">错误</th>
                  </tr>
                </thead>
                <tbody>
                  {(runs.runItems || []).map((item) => (
                    <tr key={item.runItemId} className="border-t border-line align-top">
                      <td className="px-3 py-2 font-mono text-[12px] text-ink-700">{item.paperId}</td>
                      <td className="px-3 py-2 font-mono text-[12px] text-ink-700">{item.fieldGroup}</td>
                      <td className="px-3 py-2 text-ink-700">{statusLabel(item.status)}</td>
                      <td className="px-3 py-2 text-ink-600">{formatError(item.error)}</td>
                    </tr>
                  ))}
                  {runs.runItems.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-10 text-center text-[13px] text-ink-500">
                        暂无运行条目
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="border-t border-line px-4 py-3">
              <div className="mb-3 text-[12px] font-medium uppercase text-ink-400">记录预览</div>
              <div className="grid gap-2">
                {(runs.records || []).slice(0, 20).map((record) => (
                  <div key={record.recordId} className="rounded-md border border-line bg-paper-50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-mono text-[12px] text-ink-800">{record.paperId}</div>
                      <div className="text-[12px] text-ink-500">
                        {Object.keys(record.fields || {}).length} 个字段 · {(record.qualityFlags || []).join(", ") || "正常"}
                      </div>
                    </div>
                    <div className="mt-2 truncate text-[12.5px] text-ink-600">
                      {Object.entries(record.recordIdentity || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || "-"}
                    </div>
                  </div>
                ))}
                {runs.records.length === 0 && <div className="rounded-md border border-dashed border-line px-4 py-8 text-center text-[13px] text-ink-500">暂无记录</div>}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="font-mono text-[11px] uppercase text-ink-400">{label}</div>
      <div className="mt-1 truncate text-[20px] text-ink-900">{value}</div>
    </div>
  );
}
