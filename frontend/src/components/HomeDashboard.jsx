import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  Image,
  Layers,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Table2,
  Boxes,
  XCircle,
} from "lucide-react";
import clsx from "clsx";
import { useAppStore } from "../store/useAppStore";

const STATUS_META = {
  healthy: { label: "健康", cls: "text-teal bg-teal/10 border-teal/30", Icon: CheckCircle2 },
  updating: { label: "更新中", cls: "text-amber bg-amber/10 border-amber/30", Icon: RefreshCw },
  warning: { label: "需关注", cls: "text-amber bg-amber/10 border-amber/30", Icon: AlertTriangle },
  failed: { label: "不可用", cls: "text-red-600 bg-red-50 border-red-200", Icon: XCircle },
};

const WARNING_LABELS = {
  vector_not_built: "向量索引尚未构建，语义检索将降级为全文检索（FTS）",
  vector_incomplete: "向量索引存在缺失或过期记录",
  broken_source_paths: "抽样检测到本地文献文件缺失",
  index_warnings_present: "索引存在告警记录",
  indexed_papers_empty: "索引中没有任何文献",
  index_errors_present: "索引存在错误记录",
  index_db_missing: "未找到 research_index.sqlite，索引尚未建立",
  index_refresh_running: "索引刷新任务正在运行，健康统计会在任务完成后恢复",
  health_check_running: "健康检查任务正在运行",
  vector_build_running: "向量索引构建任务正在运行",
};

const ACTION_LABELS = {
  health_check: "运行健康检查",
  index_refresh: "刷新变更文献索引",
  vector_build: "构建向量索引",
};

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("en-US");
}

function CoverageCard({ Icon, label, value, sub, accent = "text-ink-500" }) {
  return (
    <div className="rounded-lg border border-line bg-paper-0 px-4 py-3.5">
      <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-wide text-ink-400">
        <Icon size={13} className={accent} />
        {label}
      </div>
      <div className="mt-1.5 font-serif text-[22px] text-ink-900 leading-none">{value}</div>
      {sub && <div className="mt-1 text-[11px] text-ink-400">{sub}</div>}
    </div>
  );
}

export default function HomeDashboard() {
  const home = useAppStore((s) => s.home);
  const currentUser = useAppStore((s) => s.currentUser);
  const loadHomeDashboard = useAppStore((s) => s.loadHomeDashboard);
  const runMaintenance = useAppStore((s) => s.runMaintenance);

  const { dashboard, loading, error, maintenance } = home;

  useEffect(() => {
    if (!dashboard) loadHomeDashboard().catch(() => {});
  }, [dashboard, loadHomeDashboard]);

  // While a maintenance job runs the dashboard reports overall_status "updating".
  // Poll so the page (and progress bar) stays live even after a reload or when
  // another tab triggered the job, and flips back to real stats on completion.
  const isUpdating = dashboard?.overall_status === "updating";
  useEffect(() => {
    if (!isUpdating) return;
    const id = setInterval(() => loadHomeDashboard().catch(() => {}), 3000);
    return () => clearInterval(id);
  }, [isUpdating, loadHomeDashboard]);

  if (loading && !dashboard) {
    return <div className="flex-1 flex items-center justify-center text-ink-400 text-[13px] font-mono">正在读取 Research Index 健康状态…</div>;
  }
  if (error && !dashboard) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-ink-500 text-[13px]">
        <XCircle className="text-red-500" />
        <div>无法加载索引健康状态：{error}</div>
        <button onClick={() => loadHomeDashboard()} className="rounded-md border border-line px-3 py-1.5 text-[12px] hover:bg-paper-100">
          重试
        </button>
      </div>
    );
  }
  if (!dashboard) return null;

  const status = STATUS_META[dashboard.overall_status] || STATUS_META.warning;
  const cov = dashboard.coverage || {};
  const assets = cov.assets || {};
  const vector = dashboard.vector || {};
  const integrity = dashboard.integrity || {};
  const caps = dashboard.capabilities || {};
  const warnings = dashboard.warnings || [];
  const recentJobs = dashboard.recent_jobs || [];
  const runningMaintenance = dashboard.running_maintenance;
  const isAdmin = currentUser?.role === "admin";

  if (!isAdmin) {
    return <UserCorpusSummary dashboard={dashboard} status={status} loading={loading} onRefresh={loadHomeDashboard} />;
  }

  return (
    <div className="flex-1 overflow-y-auto bg-paper-50">
      <div className="max-w-[1080px] mx-auto px-8 py-7">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-ink-400 font-mono text-[11px] uppercase tracking-[0.16em]">
              <Database size={13} /> Research Index Health
            </div>
            <h1 className="font-serif text-[26px] text-ink-900 mt-1.5">本地文献库健康总览</h1>
            <div className="text-[12px] text-ink-400 mt-1 font-mono truncate">{dashboard.index_db_path}</div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium", status.cls)}>
              <status.Icon size={14} /> {status.label}
            </span>
            <button
              onClick={() => loadHomeDashboard()}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line text-ink-500 hover:text-ink-900 hover:bg-paper-100"
              title="刷新"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Coverage grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6">
          <CoverageCard Icon={FileText} label="文献 Papers" value={fmt(cov.papers)} accent="text-teal"
            sub={cov.index_versions ? `index_version ${Object.keys(cov.index_versions).join("/")}` : null} />
          <CoverageCard Icon={Layers} label="章节 Sections" value={fmt(cov.sections)} />
          <CoverageCard Icon={Boxes} label="文本块 Chunks" value={fmt(cov.chunks)} />
          <CoverageCard Icon={Activity} label="文档 Documents" value={fmt(dashboard.summary?.documents)} />
          <CoverageCard Icon={Image} label="图片 Figures" value={fmt(assets.figure)} accent="text-violet" />
          <CoverageCard Icon={Table2} label="表格 Tables" value={fmt(assets.table)} accent="text-violet" />
          <CoverageCard
            Icon={ShieldCheck}
            label="向量记录 Vectors"
            value={fmt(cov.vector_records)}
            accent={vector.built ? "text-teal" : "text-amber"}
            sub={vector.built ? vector.embedding_model || "已构建" : "未构建"}
          />
          <CoverageCard
            Icon={CheckCircle2}
            label="抽样完整性"
            value={integrity.broken_count ? `${integrity.broken_count} 缺失` : "OK"}
            accent={integrity.broken_count ? "text-amber" : "text-teal"}
            sub={integrity.sampled != null ? `抽样 ${integrity.sampled} 篇` : null}
          />
        </div>

        {/* Vector + warnings */}
        <div className="grid md:grid-cols-2 gap-4 mt-5">
          <div className="rounded-lg border border-line bg-paper-0 p-4">
            <div className="text-[12px] font-medium text-ink-700 mb-2 flex items-center gap-1.5">
              <ShieldCheck size={14} className="text-ink-400" /> 向量检索状态
            </div>
            {vector.built ? (
              <div className="text-[12.5px] text-ink-600">
                已构建 · 模型 <span className="font-mono">{vector.embedding_model || "—"}</span> · 已索引 {fmt(vector.indexed_vectors)} / 目标 {fmt(vector.target_documents)}
                {(vector.missing_vectors || vector.stale_vectors) ? (
                  <span className="text-amber"> · 缺失 {fmt(vector.missing_vectors)} / 过期 {fmt(vector.stale_vectors)}</span>
                ) : null}
              </div>
            ) : (
              <div className="flex items-start gap-2 text-[12.5px] text-amber">
                <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
                <span>向量索引未构建（vector_index_not_built）。语义检索当前不可用，混合检索会降级为 FTS。</span>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-line bg-paper-0 p-4">
            <div className="text-[12px] font-medium text-ink-700 mb-2 flex items-center gap-1.5">
              <AlertTriangle size={14} className="text-ink-400" /> 风险与告警
            </div>
            {warnings.length === 0 ? (
              <div className="text-[12.5px] text-teal flex items-center gap-1.5"><CheckCircle2 size={14} /> 未检测到告警</div>
            ) : (
              <ul className="space-y-1.5">
                {warnings.map((w) => (
                  <li key={w} className="text-[12.5px] text-ink-600 flex items-start gap-1.5">
                    <span className="mt-1.5 w-1 h-1 rounded-full bg-amber flex-shrink-0" />
                    {WARNING_LABELS[w] || w}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <AdminCorpusOperations
          caps={caps}
          maintenance={maintenance}
          recentJobs={recentJobs}
          runningMaintenance={runningMaintenance}
          onRunMaintenance={runMaintenance}
        />
      </div>
    </div>
  );
}

function UserCorpusSummary({ dashboard, status, loading, onRefresh }) {
  const cov = dashboard.coverage || {};
  const summary = dashboard.summary || {};
  const vector = dashboard.vector || {};
  const failures = dashboard.failures || [];
  const StatusIcon = status.Icon;
  const unavailable = dashboard.overall_status === "failed" || failures.length > 0;
  return (
    <div className="flex-1 overflow-y-auto bg-paper-50">
      <div className="mx-auto max-w-[920px] px-8 py-7">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-400">
              <Database size={13} /> Corpus
            </div>
            <h1 className="mt-1.5 font-serif text-[24px] text-ink-900">正式文献库</h1>
            <div className="mt-1 text-[12.5px] text-ink-500">
              {unavailable ? "文献库暂不可用，请联系管理员处理。" : "文献库已连接，可以开始检索和研究任务。"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium", status.cls)}>
              <StatusIcon size={14} /> {unavailable ? "不可用" : "可检索"}
            </span>
            <button
              onClick={() => onRefresh()}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line text-ink-500 hover:bg-paper-100 hover:text-ink-900"
              title="刷新"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <CoverageCard Icon={FileText} label="文献 Papers" value={fmt(summary.papers || cov.papers)} accent="text-teal" />
          <CoverageCard Icon={Activity} label="文档 Documents" value={fmt(summary.documents)} />
          <CoverageCard Icon={Layers} label="章节 Sections" value={fmt(summary.sections || cov.sections)} />
          <CoverageCard Icon={Boxes} label="文本块 Chunks" value={fmt(summary.chunks || cov.chunks)} />
        </div>

        <div className="mt-5 rounded-lg border border-line bg-paper-0 p-4">
          <div className="flex items-center gap-2 text-[12px] font-medium text-ink-700">
            <ShieldCheck size={14} className={vector.built ? "text-teal" : "text-amber"} />
            检索能力
          </div>
          <div className="mt-2 text-[12.5px] text-ink-600">
            {vector.built ? "关键词检索与向量检索均可用。" : "当前使用关键词与结构化检索；向量检索暂未启用。"}
          </div>
        </div>
      </div>
    </div>
  );
}

function AdminCorpusOperations({ caps, maintenance, recentJobs, runningMaintenance, onRunMaintenance }) {
  return (
    <div className="mt-5 rounded-lg border border-line bg-paper-0 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink-700">
          <RefreshCw size={14} className="text-ink-400" /> 索引维护
          <span className="ml-1 rounded bg-paper-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
            {caps.can_maintain ? "admin" : "read-only"}
          </span>
        </div>
      </div>

      {caps.can_maintain && (
        <div className="mt-3 flex flex-wrap gap-2">
          {["health_check", "index_refresh", "vector_build"].map((action) => {
            const running = maintenance.runningAction === action || runningMaintenance?.job_type === action;
            const busy = !!maintenance.runningAction || !!runningMaintenance;
            return (
              <button
                key={action}
                disabled={busy}
                onClick={() => onRunMaintenance(action)}
                className={clsx(
                  "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] transition-colors",
                  running ? "border-amber text-amber" : "border-line text-ink-700 hover:bg-paper-100",
                  busy && !running && "cursor-not-allowed opacity-40"
                )}
              >
                {running && <RefreshCw size={12} className="animate-spin" />}
                {ACTION_LABELS[action]}
              </button>
            );
          })}
        </div>
      )}

      <MaintenanceProgress maintenance={maintenance} runningMaintenance={runningMaintenance} />

      {maintenance.error && <div className="mt-2 text-[12px] text-red-500">{maintenance.error}</div>}
      {maintenance.events.length > 0 && (
        <div className="mt-3 max-h-32 overflow-y-auto rounded-md bg-ink-900 p-2.5 font-mono text-[11px] text-paper-50/90">
          {maintenance.events.map((e, i) => (
            <div key={i} className="truncate">
              · {e.type === "stage" ? `${e.label || e.stage} [${e.status}]` : e.type === "error" ? `错误: ${e.message}` : e.type}
            </div>
          ))}
        </div>
      )}

      {recentJobs.length > 0 && (
        <div className="mt-4">
          <div className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-400">最近维护任务</div>
          <div className="space-y-1">
            {recentJobs.slice(0, 6).map((job) => {
              const dur = jobDurationSeconds(job);
              return (
                <div key={job.job_id} className="flex items-center gap-2 text-[12px] text-ink-600">
                  <JobStatusDot status={job.status} />
                  <span className="font-mono text-ink-400">{ACTION_LABELS[job.job_type] || job.job_type}</span>
                  <span className="text-ink-300">·</span>
                  <span>{job.status}</span>
                  {dur != null && <span className="text-ink-400">· 用时 {fmtDuration(dur)}</span>}
                  {job.error && <span className="truncate text-red-500">· {job.error}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function JobStatusDot({ status }) {
  const cls =
    status === "completed" ? "bg-teal" : status === "failed" ? "bg-red-500" : status === "running" ? "bg-amber animate-pulse" : "bg-ink-300";
  return <span className={clsx("w-1.5 h-1.5 rounded-full flex-shrink-0", cls)} />;
}

/**
 * Live progress for the active/last maintenance job.
 *
 * The underlying `index build` runs as one SQLite transaction with no per-item
 * commit and no progress callback (and we don't modify the underlying agent), so
 * an exact percentage is not observable. We therefore show an honest animated
 * (indeterminate) bar driven by elapsed time + the latest stage label, and we
 * automatically switch to a determinate bar if the job stream ever emits a
 * `progress` event carrying `current`/`total` (e.g. a future vector build).
 */
function MaintenanceProgress({ maintenance, runningMaintenance }) {
  const localRunning = !!maintenance.runningAction;
  const dashRunning = !!runningMaintenance;
  const running = localRunning || dashRunning;
  const action = maintenance.runningAction || runningMaintenance?.job_type || maintenance.lastAction;

  // Prefer the locally-tracked start time; fall back to the job row's timestamp
  // (epoch seconds) so a bar still ticks after a page reload / other tab.
  const startMs = localRunning && maintenance.startedAt
    ? maintenance.startedAt
    : dashRunning
      ? (runningMaintenance.started_at || runningMaintenance.created_at || 0) * 1000
      : maintenance.startedAt;

  // Hooks must run unconditionally — keep useElapsed above any early return.
  const elapsed = useElapsed(startMs, running);
  if (!action) return null;

  // Prefer the live local stream; fall back to the last progress the dashboard
  // carries (survives a page reload / cross-tab) so the bar stays determinate.
  const determinate = progressFromEvents(maintenance.events) || progressFromEvent(runningMaintenance?.progress);
  const streamPhase = latestPhase(maintenance.events);
  const phase = running
    ? (maintenance.events.length ? streamPhase : runningMaintenance?.progress?.phase || "处理中")
    : maintenance.lastStatus === "failed" ? "失败" : "已完成";
  const failed = !running && maintenance.lastStatus === "failed";
  const finalDuration = !running && maintenance.startedAt && maintenance.completedAt
    ? Math.round((maintenance.completedAt - maintenance.startedAt) / 1000)
    : null;

  let fillCls = "bg-amber";
  let pct = null;
  if (!running) {
    pct = 100;
    fillCls = failed ? "bg-red-500" : "bg-teal";
  } else if (determinate) {
    pct = Math.min(99, Math.round((determinate.current / determinate.total) * 100));
  }

  return (
    <div className="mt-3 rounded-md border border-line bg-paper-50 px-3 py-2.5">
      <div className="flex items-center justify-between text-[12px]">
        <div className="flex items-center gap-1.5 text-ink-700">
          {running ? <Loader2 size={13} className="animate-spin text-amber" /> : failed ? <XCircle size={13} className="text-red-500" /> : <CheckCircle2 size={13} className="text-teal" />}
          <span className="font-medium">{ACTION_LABELS[action] || action}</span>
          <span className="text-ink-400">· {phase}</span>
        </div>
        <div className="font-mono text-[11px] text-ink-400">
          {running ? `已运行 ${fmtDuration(elapsed)}` : finalDuration != null ? `用时 ${fmtDuration(finalDuration)}` : ""}
        </div>
      </div>

      <div className="relative mt-2 h-2 rounded-full bg-paper-100 overflow-hidden">
        {pct != null ? (
          <div className={clsx("h-full rounded-full transition-all duration-500", fillCls)} style={{ width: `${pct}%` }} />
        ) : (
          <div className={clsx("progress-indeterminate", fillCls, "opacity-80")} />
        )}
      </div>

      {running && !determinate && (
        <div className="mt-1.5 text-[11px] text-ink-400">
          该任务的精确百分比无法从底层单事务构建中获取，进度按已运行时间与阶段实时显示。
        </div>
      )}
      {running && determinate && (
        <div className="mt-1.5 text-[11px] text-ink-400 font-mono">
          {fmt(determinate.current)} / {fmt(determinate.total)}
        </div>
      )}
    </div>
  );
}

function useElapsed(startMs, active) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!active || !startMs) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [active, startMs]);
  if (!startMs) return 0;
  return Math.max(0, Math.floor((Date.now() - startMs) / 1000));
}

function latestPhase(events) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i];
    if (e.type === "progress") return e.phase || e.label || "处理中";
    if (e.type === "stage") return e.label || e.stage || "处理中";
    if (e.type === "result") return "即将完成";
    if (e.type === "queued") return "已排队";
  }
  return "已排队";
}

function progressFromEvents(events) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const found = progressFromEvent(events[i]);
    if (found) return found;
  }
  return null;
}

function progressFromEvent(e) {
  if (e && e.type === "progress" && Number(e.total) > 0 && e.current != null) {
    return { current: Number(e.current), total: Number(e.total) };
  }
  return null;
}

function fmtDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m${rem.toString().padStart(2, "0")}s`;
}

function jobDurationSeconds(job) {
  const start = job.started_at || job.created_at;
  const end = job.completed_at;
  if (!start || !end) return null;
  return Math.max(0, Math.round(end - start));
}
