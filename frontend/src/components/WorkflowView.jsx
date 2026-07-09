import React, { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  ArrowLeft,
  Braces,
  Check,
  ChevronDown,
  CircleDashed,
  FileText,
  ListChecks,
  Loader2,
  Pause,
  Play,
  RotateCw,
  ScrollText,
  Trash2,
  X,
} from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import MarkdownMessage from "./MarkdownMessage";

const STATUS_BADGE = {
  draft: ["草稿", "bg-paper-100 text-ink-600 border-line"],
  running: ["执行中", "bg-amber-50 text-amber-700 border-amber-200"],
  paused: ["已暂停", "bg-paper-100 text-ink-600 border-line"],
  failed: ["失败", "bg-red-50 text-red-600 border-red-200"],
  completed: ["已完成", "bg-teal/10 text-teal border-teal/30"],
  partial: ["部分完成 · 后续敬请期待", "bg-amber-50 text-amber-700 border-amber-200"],
  blocked: ["已阻塞", "bg-paper-100 text-ink-500 border-line"],
};

const WORKFLOW_TARGETS = [
  {
    templateId: "controlled-minimal-evidence",
    label: "最小证据报告",
    description: "完成检索、证据卡片、证据排序和最小证据报告。",
    terminalStage: "build_minimal_topic_to_evidence_report",
  },
  {
    templateId: "controlled-landscape",
    label: "文献图景",
    description: "在最小证据报告基础上构建文献图景。",
    terminalStage: "build_landscape",
  },
  {
    templateId: "controlled-gap-mapping",
    label: "研究空白映射",
    description: "基于文献图景映射证据接地的研究空白。",
    terminalStage: "map_gaps",
  },
  {
    templateId: "controlled-idea-generation",
    label: "候选想法生成",
    description: "基于 gap、landscape 和 evidence 生成候选想法。",
    terminalStage: "generate_candidate_ideas",
  },
  {
    templateId: "controlled-screening",
    label: "新颖性 / 可行性 / 风险筛选",
    description: "执行 LLM 辅助的本地证据筛选，不进入后续规划阶段。",
    terminalStage: "screen_novelty_feasibility_risk",
  },
];

const FALLBACK_CONTROLLED_STAGES = [
  { stage: "retrieve_sources", label: "检索来源" },
  { stage: "create_evidence_seeds", label: "创建证据种子" },
  { stage: "extract_evidence_cards", label: "抽取证据卡片" },
  { stage: "enrich_evidence_cards", label: "富集证据卡片" },
  { stage: "rank_evidence", label: "排序代表性证据" },
  { stage: "build_minimal_topic_to_evidence_report", label: "生成最小证据报告" },
  { stage: "build_landscape", label: "构建文献图景" },
  { stage: "map_gaps", label: "映射研究空白" },
  { stage: "generate_candidate_ideas", label: "生成候选想法" },
  { stage: "screen_novelty_feasibility_risk", label: "筛选新颖性 / 可行性 / 风险" },
];

const STAGE_DETAILS = {
  retrieve_sources: {
    purpose: "根据研究主题从当前检索范围中获取候选来源，并记录检索覆盖情况。",
    inputs: ["研究主题", "检索范围", "本地索引状态"],
    outputs: ["检索候选源", "检索警告"],
    boundary: "只收集候选来源，不生成研究结论。",
  },
  create_evidence_seeds: {
    purpose: "把检索命中的来源整理成可审计的证据种子。",
    inputs: ["检索候选源", "来源元数据"],
    outputs: ["证据种子"],
    boundary: "只建立证据入口，不把 raw retrieval 直接当作分析依据。",
  },
  extract_evidence_cards: {
    purpose: "从证据种子中抽取结构化 Evidence Cards。",
    inputs: ["证据种子", "来源片段定位信息"],
    outputs: ["初始证据卡片"],
    boundary: "只抽取可引用证据，不扩写为研究判断。",
  },
  enrich_evidence_cards: {
    purpose: "补充 Evidence Cards 的角色、标准化陈述、支持强度和引用上下文。",
    inputs: ["初始证据卡片", "来源元数据"],
    outputs: ["富集证据卡片"],
    boundary: "保持证据接地，不发明论文、结论或实验结果。",
  },
  rank_evidence: {
    purpose: "选择代表性证据并检查主题覆盖度。",
    inputs: ["富集证据卡片", "研究主题"],
    outputs: ["代表性证据选择", "证据覆盖诊断"],
    boundary: "只排序和诊断证据，不替代人工完整文献综述。",
  },
  build_minimal_topic_to_evidence_report: {
    purpose: "把主题、证据卡片和代表性证据汇总为最小证据报告。",
    inputs: ["富集证据卡片", "代表性证据选择", "覆盖诊断"],
    outputs: ["最小证据报告", "最小证据报告数据"],
    boundary: "报告是证据摘要，不是论文草稿或最终 claim。",
  },
  build_landscape: {
    purpose: "基于证据报告构建文献图景，整理主题簇和代表性主张。",
    inputs: ["最小证据报告", "Evidence Cards", "代表性证据"],
    outputs: ["文献图景", "文献图景数据", "文献图景覆盖诊断"],
    boundary: "只描述本地证据图景，不声称覆盖全部外部文献。",
  },
  map_gaps: {
    purpose: "基于文献图景和证据覆盖情况映射研究空白。",
    inputs: ["文献图景", "证据覆盖诊断", "Evidence Cards"],
    outputs: ["研究空白图", "研究空白图数据", "研究空白覆盖诊断"],
    boundary: "研究空白是候选判断，需要后续证据和专家复核。",
  },
  generate_candidate_ideas: {
    purpose: "基于 gap、landscape 和 evidence 生成候选研究想法。",
    inputs: ["研究空白图", "文献图景", "富集证据卡片", "代表性证据"],
    outputs: ["候选想法", "候选想法数据", "候选想法诊断"],
    boundary: "候选想法尚未筛选，不可直接进入实验或论文 claim。",
  },
  screen_novelty_feasibility_risk: {
    purpose: "基于 candidate ideas、gap map、landscape 和 Evidence Cards 做本地证据筛选。",
    inputs: ["候选想法", "研究空白图", "文献图景", "富集证据卡片", "代表性证据选择"],
    outputs: ["筛选摘要", "筛选结构化数据", "筛选诊断"],
    boundary: "不执行外部新颖性检索，不进入后续规划，不输出定稿结论。",
  },
};

const ARTIFACT_STAGE_FALLBACKS = [
  ["retrieval/source_candidate_packet.json", "retrieve_sources"],
  ["retrieval/retrieval_warnings.json", "retrieve_sources"],
  ["evidence/evidence_card_seeds.json", "create_evidence_seeds"],
  ["evidence/evidence_cards.initial.json", "extract_evidence_cards"],
  ["evidence/evidence_cards.enriched.json", "enrich_evidence_cards"],
  ["ranked_evidence/evidence_selection.json", "rank_evidence"],
  ["ranked_evidence/coverage_diagnostics.json", "rank_evidence"],
  ["reports/minimal_topic_to_evidence_report", "build_minimal_topic_to_evidence_report"],
  ["landscape/literature_landscape", "build_landscape"],
  ["landscape/landscape_coverage_diagnostics.json", "build_landscape"],
  ["gaps/gap_map", "map_gaps"],
  ["gaps/gap_coverage_diagnostics.json", "map_gaps"],
  ["ideas/candidate_ideas", "generate_candidate_ideas"],
  ["ideas/idea_generation_diagnostics.json", "generate_candidate_ideas"],
  ["screening/idea_screening_results", "screen_novelty_feasibility_risk"],
  ["screening/screening_diagnostics.json", "screen_novelty_feasibility_risk"],
];

export default function WorkflowView() {
  const view = useAppStore((s) => s.workflow.view);
  return view === "console" ? <WorkflowConsole /> : <WorkflowGallery />;
}

// ---------------------------------------------------------------- Gallery ----

function templateById(templates) {
  return new Map((templates || []).map((template) => [template.id, template]));
}

function controlledStages(templates) {
  const screening = templateById(templates).get("controlled-screening");
  const stages = screening?.steps?.[0]?.params?.stages;
  return Array.isArray(stages) && stages.length ? stages : FALLBACK_CONTROLLED_STAGES;
}

function workflowErrorText(error) {
  if (!error) return "";
  const text = String(error);
  if (text.includes("llm_required_for_screening")) return "筛选需要可用 LLM，请先在设置中配置模型。";
  if (text.includes("retrieval_timeout")) return "检索超时，请稍后重试或缩小主题范围。";
  if (text.includes("unsupported_screening_claim")) return "筛选输出未通过保守性校验，可重新运行。";
  if (text.includes("missing_candidate_ideas_artifact")) return "缺少候选想法，请先运行到候选想法生成。";
  if (text.includes("screening_requires_gap_and_evidence_basis")) return "缺少研究空白或证据依据，无法筛选。";
  if (text.includes("screening_requires_unscreened_candidate_ideas")) return "候选想法已被标记为筛选过，无法重复作为未筛选输入。";
  if (text.includes("artifact not found")) return "未找到该工作流产物。";
  return text;
}

function formatWorkflowTime(value) {
  if (!value) return "时间未知";
  const numeric = Number(value);
  const ms = numeric > 100000000000 ? numeric : numeric * 1000;
  if (!Number.isFinite(ms)) return "时间未知";
  return new Date(ms).toLocaleString();
}

function StageChainPreview({ stages, selectedTarget }) {
  const foundIndex = stages.findIndex((stage) => stage.stage === selectedTarget.terminalStage);
  const targetIndex = foundIndex >= 0 ? foundIndex : stages.length - 1;
  return (
    <div className="rounded-lg border border-line bg-paper-0 p-3">
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">阶段链预览</div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {stages.map((stage, index) => {
          const willRun = index <= targetIndex;
          const isTarget = index === targetIndex;
          return (
            <div
              key={stage.stage}
              className={clsx(
                "flex items-center gap-2 rounded-md border px-2.5 py-2",
                isTarget
                  ? "border-amber/50 bg-amber/10"
                  : willRun
                    ? "border-teal/25 bg-teal/5"
                    : "border-line bg-paper-50 opacity-60"
              )}
            >
              <span
                className={clsx(
                  "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border text-[10px]",
                  isTarget ? "border-amber text-amber-700" : willRun ? "border-teal text-teal" : "border-ink-200 text-ink-300"
                )}
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <div className={clsx("truncate text-[12.5px]", willRun ? "text-ink-800" : "text-ink-400")}>{stage.label}</div>
                <div className="text-[10.5px] text-ink-400">{isTarget ? "目标阶段" : willRun ? "将执行" : "本次不执行"}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TargetSelector({ templates, selectedTemplateId, onSelect }) {
  const templatesById = templateById(templates);
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase">运行目标</div>
      <div className="grid gap-2">
        {WORKFLOW_TARGETS.map((target) => {
          const available = templatesById.has(target.templateId);
          const selected = selectedTemplateId === target.templateId;
          return (
            <button
              key={target.templateId}
              type="button"
              disabled={!available}
              onClick={() => available && onSelect(target.templateId)}
              className={clsx(
                "text-left rounded-lg border px-3 py-2.5 transition-colors",
                selected ? "border-amber bg-amber/10 ring-1 ring-amber/30" : "border-line bg-paper-0 hover:border-ink-300",
                !available && "opacity-50 cursor-not-allowed"
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={clsx(
                    "h-3.5 w-3.5 rounded-full border flex-shrink-0",
                    selected ? "border-amber bg-amber shadow-[inset_0_0_0_3px_white]" : "border-ink-300 bg-paper-0"
                  )}
                />
                <span className="text-[13.5px] font-medium text-ink-900">{target.label}</span>
                {!available && <span className="ml-auto rounded border border-line bg-paper-100 px-1.5 py-0.5 text-[10.5px] text-ink-400">当前不可用</span>}
              </div>
              <div className="mt-1 pl-5 text-[12px] leading-snug text-ink-500">{target.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function RecentWorkflows({ list, onOpen, onDelete }) {
  return (
    <aside className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="flex items-center gap-2">
        <ScrollText size={14} className="text-ink-400" />
        <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase">最近任务</div>
      </div>
      <div className="mt-3 space-y-2">
        {list.length === 0 && <div className="rounded-md border border-dashed border-line px-3 py-6 text-center text-[12.5px] text-ink-400">还没有工作流运行。</div>}
        {list.map((w) => {
          const [label, tone] = STATUS_BADGE[w.status] || [w.status, "bg-paper-100 text-ink-600 border-line"];
          return (
            <div key={w.workflow_id} className="group rounded-lg border border-line bg-paper-50 px-3 py-2.5">
              <button className="w-full text-left" onClick={() => onOpen(w.workflow_id)}>
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1 truncate text-[13px] text-ink-900">{w.topic || w.title || "未命名研究任务"}</div>
                  <span className={clsx("rounded px-1.5 py-0.5 text-[10.5px] border flex-shrink-0", tone)}>{label}</span>
                </div>
                <div className="mt-1 truncate text-[11.5px] text-ink-500">{w.template_name || w.template_id || "受控研究任务"}</div>
                <div className="mt-0.5 font-mono text-[10px] text-ink-400">{formatWorkflowTime(w.updated_at || w.created_at)}</div>
              </button>
              <button
                className="mt-2 inline-flex items-center gap-1 text-[11px] text-ink-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                title="删除"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(w.workflow_id);
                }}
              >
                <Trash2 size={12} /> 删除
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function WorkflowGallery() {
  const templates = useAppStore((s) => s.workflow.templates);
  const list = useAppStore((s) => s.workflow.list);
  const creating = useAppStore((s) => s.workflow.creating);
  const error = useAppStore((s) => s.workflow.error);
  const createAndStartWorkflow = useAppStore((s) => s.createAndStartWorkflow);
  const openWorkflow = useAppStore((s) => s.openWorkflow);
  const deleteWorkflow = useAppStore((s) => s.deleteWorkflow);

  const [selectedTemplateId, setSelectedTemplateId] = useState("controlled-screening");
  const [topic, setTopic] = useState("");
  const [scope, setScope] = useState("library");
  const topicRef = useRef(null);

  const stages = useMemo(() => controlledStages(templates), [templates]);
  const selectedTarget = useMemo(
    () => WORKFLOW_TARGETS.find((target) => target.templateId === selectedTemplateId) || WORKFLOW_TARGETS[WORKFLOW_TARGETS.length - 1],
    [selectedTemplateId]
  );
  const selectedAvailable = templateById(templates).has(selectedTemplateId);
  const canCreate = selectedAvailable && topic.trim().length > 2 && !creating;

  return (
    <div className="flex-1 overflow-y-auto bg-paper-50">
      <div className="mx-auto grid max-w-6xl gap-5 px-6 py-7 lg:grid-cols-[minmax(0,1fr)_330px]">
        <main className="space-y-5">
          <div>
            <h1 className="font-serif text-[24px] text-ink-900">创建受控研究任务</h1>
            <p className="mt-1 max-w-3xl text-[13px] leading-6 text-ink-500">
              输入研究主题，选择本次要运行到的目标阶段。系统会从检索来源开始按顺序推进，不会跳过前置证据链。
            </p>
          </div>

          <section className="rounded-lg border border-line bg-paper-0 p-4 space-y-4">
            <label className="block">
              <span className="form-label">研究主题</span>
              <textarea
                ref={topicRef}
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                rows={3}
                placeholder="例如：大语言模型在材料发现中的应用"
                className="form-input resize-y"
              />
              <span className="mt-1 block text-[11px] text-ink-400">请尽量具体，系统会围绕该主题构建证据链。</span>
            </label>

            <label className="block max-w-xs">
              <span className="form-label">检索范围</span>
              <select value={scope} onChange={(e) => setScope(e.target.value)} className="form-input">
                <option value="library">library</option>
                <option value="collection">collection</option>
                <option value="library+boost">library+boost</option>
              </select>
            </label>

            <TargetSelector templates={templates} selectedTemplateId={selectedTemplateId} onSelect={setSelectedTemplateId} />
            <StageChainPreview stages={stages} selectedTarget={selectedTarget} />

            <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12.5px] text-ink-700">
              当前目标：{selectedTarget.label}。系统将自动运行到该阶段，目标之后的阶段本次不会执行。
            </div>

            {error && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{workflowErrorText(error)}</div>}
            {!selectedAvailable && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">当前目标阶段不可用，请确认后端工作流模板已加载。</div>}

            <button
              className={clsx("btn-dark inline-flex items-center gap-1.5", !canCreate && "opacity-50 cursor-not-allowed")}
              disabled={!canCreate}
              onClick={() => {
                if (!canCreate) return;
                createAndStartWorkflow({ templateId: selectedTemplateId, topic: topic.trim(), scope });
              }}
            >
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {creating ? "创建中…" : topic.trim().length <= 2 ? "请先填写研究主题" : "开始受控研究"}
            </button>
          </section>
        </main>

        <RecentWorkflows list={list} onOpen={openWorkflow} onDelete={deleteWorkflow} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Console ----

function mergeSteps(detail, live) {
  if (!detail) return [];
  return (detail.steps || []).map((step) => {
    const ls = live.steps[step.step_index];
    const status = ls?.status || step.status;
    const stages = (step.stages || []).map((stage) => ({
      ...stage,
      status: live.stages[stage.stage] || stage.status,
    }));
    return { ...step, status, error: ls?.error || step.error, failed_stage: ls?.failed_stage, stages };
  });
}

function StageIcon({ status }) {
  if (status === "done") return <Check size={14} className="text-teal" />;
  if (status === "running") return <Loader2 size={14} className="text-amber animate-spin" />;
  if (status === "failed") return <X size={14} className="text-red-500" />;
  if (status === "unavailable") return <CircleDashed size={14} className="text-ink-200" />;
  return <CircleDashed size={14} className="text-ink-300" />;
}

function flattenWorkflowStages(steps) {
  return (steps || []).flatMap((step) => {
    if (!Array.isArray(step.stages) || step.stages.length === 0) {
      return [{
        stage: step.step_key || `step-${step.step_index}`,
        label: step.label || "工作流步骤",
        status: step.status,
        stepIndex: step.step_index,
        stepLabel: step.label,
        available: step.available !== false,
        error: step.error,
      }];
    }
    return step.stages.map((stage) => ({
      ...stage,
      stepIndex: step.step_index,
      stepLabel: step.label,
      available: step.available !== false,
      error: stage.status === "failed" ? step.error : null,
    }));
  });
}

function artifactStageId(artifact) {
  if (artifact?.artifact_type && STAGE_DETAILS[artifact.artifact_type]) return artifact.artifact_type;
  const id = artifact?.artifact_id || "";
  const match = ARTIFACT_STAGE_FALLBACKS.find(([suffix]) => id.includes(suffix));
  return match?.[1] || artifact?.artifact_type || "workflow_artifact";
}

function artifactContentType(artifact) {
  const id = artifact?.artifact_id || "";
  if (artifact?.content_type) return artifact.content_type;
  if (id.endsWith(".json")) return "json";
  if (id.endsWith(".md") || id.endsWith(".markdown")) return "markdown";
  return "text";
}

function artifactTypeLabel(contentType) {
  if (contentType === "json") return "结构化数据";
  if (contentType === "markdown") return "可读报告";
  return "文本";
}

function artifactsForStage(artifacts, stageId) {
  return (artifacts || []).filter((artifact) => artifactStageId(artifact) === stageId);
}

function stageById(stages, stageId) {
  return (stages || []).find((stage) => stage.stage === stageId) || null;
}

function stageLabel(stages, stageId) {
  return stageById(stages, stageId)?.label || STAGE_DETAILS[stageId]?.label || stageId || "未归属阶段";
}

function outputFromDetail(detail) {
  const steps = detail?.steps || [];
  const artifactOutput = (pattern) =>
    steps.find((step) => (step.artifact_ids || []).some((id) => pattern.test(id)) && step.output_text)?.output_text || "";
  return (
    artifactOutput(/screening\/idea_screening_results\.md$/) ||
    artifactOutput(/ideas\/candidate_ideas\.md$/) ||
    artifactOutput(/gaps\/gap_map\.md$/) ||
    artifactOutput(/landscape\/literature_landscape\.md$/) ||
    artifactOutput(/reports\/minimal_topic_to_evidence_report\.md$/) ||
    [...steps].reverse().find((step) => step.output_text)?.output_text ||
    ""
  );
}

function stepOutputForStage(detail, stageId) {
  const step = (detail?.steps || []).find((item) => (item.stages || []).some((stage) => stage.stage === stageId));
  return step?.output_text || "";
}

function jsonSummary(value) {
  if (Array.isArray(value)) return `数组，共 ${value.length} 项`;
  if (value && typeof value === "object") {
    const keys = Object.keys(value);
    return `对象，共 ${keys.length} 个顶层字段`;
  }
  return "JSON 值";
}

function severityLabel(severity) {
  if (severity === "error") return ["错误", "bg-red-50 text-red-600 border-red-200"];
  if (severity === "warning") return ["警告", "bg-amber-50 text-amber-700 border-amber-200"];
  return ["信息", "bg-paper-100 text-ink-500 border-line"];
}

function findEvidenceCard(insights, evidenceId) {
  return (insights?.evidence?.cards || []).find((card) => card.evidence_id === evidenceId) || null;
}

function findDiagnosticItem(insights, diagnosticId) {
  return (insights?.diagnostics?.items || []).find((item) => item.diagnostic_id === diagnosticId) || null;
}

function formatPercentish(value) {
  if (value === null || value === undefined || value === "") return "未知";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric <= 1 ? numeric.toFixed(2) : String(numeric);
}

function WorkflowConsole() {
  const detail = useAppStore((s) => s.workflow.detail);
  // Fine-grained selectors keep stage and artifact panes stable while the live
  // text stream updates.
  const liveSteps = useAppStore((s) => s.workflow.live.steps);
  const liveStages = useAppStore((s) => s.workflow.live.stages);
  const liveArtifacts = useAppStore((s) => s.workflow.live.artifacts);
  const liveStatus = useAppStore((s) => s.workflow.live.status);
  const liveStreaming = useAppStore((s) => s.workflow.live.streaming);
  const liveError = useAppStore((s) => s.workflow.live.error);
  const liveLog = useAppStore((s) => s.workflow.live.log);
  const livePauseRequested = useAppStore((s) => s.workflow.live.pauseRequested);
  const insights = useAppStore((s) => s.workflow.insights);
  const sidebarTab = useAppStore((s) => s.workflow.sidebarTab);
  const loading = useAppStore((s) => s.workflow.loading);
  const backToGallery = useAppStore((s) => s.backToGallery);
  const startWorkflow = useAppStore((s) => s.startWorkflow);
  const pauseWorkflow = useAppStore((s) => s.pauseWorkflow);
  const selectWorkflowStage = useAppStore((s) => s.selectWorkflowStage);
  const selectWorkflowArtifact = useAppStore((s) => s.selectWorkflowArtifact);
  const selectWorkflowSidebarTab = useAppStore((s) => s.selectWorkflowSidebarTab);
  const selectWorkflowEvidenceCard = useAppStore((s) => s.selectWorkflowEvidenceCard);
  const selectWorkflowDiagnostic = useAppStore((s) => s.selectWorkflowDiagnostic);

  const steps = useMemo(() => mergeSteps(detail, { steps: liveSteps, stages: liveStages }), [detail, liveSteps, liveStages]);
  const status = liveStatus || detail?.status || "draft";
  const artifacts = useMemo(() => {
    const map = new Map();
    [...(detail?.artifacts || []), ...(liveArtifacts || [])].forEach((a) => map.set(a.artifact_id, a));
    return [...map.values()];
  }, [detail, liveArtifacts]);

  const allStages = useMemo(() => flattenWorkflowStages(steps), [steps]);
  const doneCount = allStages.filter((s) => s.status === "done").length;
  const pct = allStages.length ? Math.round((doneCount / allStages.length) * 100) : 0;
  const [badge, tone] = STATUS_BADGE[status] || [status, "bg-paper-100 text-ink-600 border-line"];

  if (loading && !detail) {
    return <div className="flex-1 flex items-center justify-center text-ink-400 text-[13px]">加载工作流…</div>;
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-paper-50">
      <header className="border-b border-line bg-paper-0 px-6 py-4 flex items-center gap-3">
        <button className="text-ink-400 hover:text-ink-900" onClick={backToGallery} title="返回">
          <ArrowLeft size={18} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="font-serif text-[18px] text-ink-900 truncate">{detail?.topic || detail?.title}</h1>
            <span className={clsx("rounded px-2 py-0.5 text-[11px] border flex-shrink-0", tone)}>{badge}</span>
          </div>
          <div className="font-mono text-[10.5px] text-ink-400 mt-0.5 flex items-center gap-2">
            <span>{detail?.manifest?.template_name} · {doneCount}/{allStages.length} 阶段 · {pct}%</span>
            <RunningClock active={status === "running"} startedAt={detail?.started_at} />
          </div>
        </div>
        <Controls status={status} streaming={liveStreaming} pauseRequested={livePauseRequested} onStart={() => startWorkflow()} onResume={() => startWorkflow(undefined, { resume: true })} onPause={() => pauseWorkflow()} />
      </header>

      {liveError && <div className="mx-6 mt-3 rounded-md bg-red-50 text-red-600 text-[12px] px-3 py-2">{liveError}</div>}

      <div className="flex-1 min-h-0 grid grid-cols-[280px_minmax(0,1fr)_300px]">
        <StageNavigator stages={allStages} onSelect={selectWorkflowStage} />
        <WorkflowMainPane detail={detail} status={status} stages={allStages} artifacts={artifacts} log={liveLog} insights={insights.data} />
        <WorkflowSidePanel
          artifacts={artifacts}
          stages={allStages}
          insights={insights}
          activeTab={sidebarTab}
          onTab={selectWorkflowSidebarTab}
          onArtifact={(artifactId) => selectWorkflowArtifact(artifactId)}
          onEvidence={selectWorkflowEvidenceCard}
          onDiagnostic={selectWorkflowDiagnostic}
        />
      </div>
    </div>
  );
}

function StageNavigator({ stages, onSelect }) {
  const preview = useAppStore((s) => s.workflow.preview);
  return (
    <aside className="border-r border-line bg-paper-0 overflow-y-auto p-3">
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">阶段链</div>
      <div className="space-y-1">
        {stages.map((stage, index) => {
          const selected = preview.mode === "stage" && preview.selectedStage === stage.stage;
          return (
            <button
              key={`${stage.stepIndex}-${stage.stage}`}
              type="button"
              onClick={() => onSelect(stage.stage)}
              className={clsx(
                "w-full rounded-md border px-2.5 py-2 text-left transition-colors",
                selected ? "border-amber bg-amber/10" : "border-transparent hover:border-line hover:bg-paper-50"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-ink-300 w-5">{String(index + 1).padStart(2, "0")}</span>
                <StageIcon status={stage.status} />
                <span className={clsx("min-w-0 flex-1 truncate text-[12.5px]", stage.status === "failed" ? "text-red-600" : "text-ink-700")}>{stage.label}</span>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function WorkflowMainPane({ detail, status, stages, artifacts, log, insights }) {
  const preview = useAppStore((s) => s.workflow.preview);
  return (
    <main className="overflow-y-auto p-4">
      {preview.mode === "artifact" ? (
        <ArtifactPreviewPane stages={stages} />
      ) : preview.mode === "evidence" ? (
        <EvidenceDetailPane card={findEvidenceCard(insights, preview.selectedEvidenceId)} />
      ) : preview.mode === "diagnostic" ? (
        <DiagnosticDetailPane item={findDiagnosticItem(insights, preview.selectedDiagnosticId)} stages={stages} />
      ) : preview.mode === "stage" ? (
        <StageDetailPane detail={detail} stages={stages} artifacts={artifacts} selectedStage={preview.selectedStage} />
      ) : (
        <ResultPane detail={detail} status={status} stages={stages} artifacts={artifacts} />
      )}
      <RunLogPanel log={log} status={status} />
    </main>
  );
}

function PaneTitle({ kicker, title, children }) {
  return (
    <div className="mb-3 flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase">{kicker}</div>
        <h2 className="mt-1 font-serif text-[18px] text-ink-900">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function ResultPane({ detail, status, stages, artifacts }) {
  const liveOutput = useAppStore((s) => s.workflow.live.output);
  const selectWorkflowArtifact = useAppStore((s) => s.selectWorkflowArtifact);
  const output = liveOutput || outputFromDetail(detail);
  const runningStage = stages.find((stage) => stage.status === "running") || [...stages].reverse().find((stage) => stage.status === "done") || stages[0];
  const primaryMarkdown = artifacts.find((artifact) => artifactContentType(artifact) === "markdown");
  const errorText = workflowErrorText(detail?.error || "");

  if (status === "draft") {
    return (
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <PaneTitle kicker="最终结果" title="尚未开始" />
        <p className="text-[13px] leading-6 text-ink-500">点击右上角「开始执行」后，系统会按阶段链推进，并在这里优先显示当前或最终结果。</p>
      </section>
    );
  }

  if (status === "failed" || status === "blocked") {
    return (
      <section className="rounded-lg border border-red-100 bg-red-50 p-4">
        <PaneTitle kicker="执行状态" title={status === "blocked" ? "任务已阻塞" : "任务失败"} />
        <p className="text-[13px] leading-6 text-red-700">{workflowErrorText(errorText || detail?.steps?.find((step) => step.error)?.error || "执行没有完成，请查看阶段详情和运行日志。")}</p>
      </section>
    );
  }

  if (status === "running") {
    return (
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <PaneTitle kicker="当前阶段" title={runningStage?.label || "执行中"} />
        <p className="text-[13px] leading-6 text-ink-500">
          系统正在推进受控阶段链。这里会优先显示已经产生的可读结果，日志已折叠到下方。
        </p>
        {output ? <div className="mt-4"><MarkdownMessage text={output} /></div> : <div className="mt-4 rounded-md border border-dashed border-line px-3 py-8 text-center text-[12.5px] text-ink-400">当前阶段还没有可读产物。</div>}
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <PaneTitle kicker="最终结果" title="工作流输出" />
      {output ? (
        <MarkdownMessage text={output} />
      ) : primaryMarkdown ? (
        <button className="btn-light inline-flex items-center gap-1.5" onClick={() => selectWorkflowArtifact(primaryMarkdown.artifact_id)}>
          <FileText size={14} /> 查看主要报告
        </button>
      ) : (
        <div className="rounded-md border border-dashed border-line px-3 py-8 text-center text-[12.5px] text-ink-400">当前没有可读结果产物。</div>
      )}
    </section>
  );
}

function StageDetailPane({ detail, stages, artifacts, selectedStage }) {
  const stage = stageById(stages, selectedStage);
  const info = STAGE_DETAILS[selectedStage] || {};
  const relatedArtifacts = artifactsForStage(artifacts, selectedStage);
  const markdownPreview = stepOutputForStage(detail, selectedStage);
  const selectWorkflowArtifact = useAppStore((s) => s.selectWorkflowArtifact);

  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <PaneTitle kicker="阶段详情" title={stage?.label || selectedStage || "未选择阶段"} />
      <div className="grid gap-3 md:grid-cols-2">
        <InfoBlock title="作用" items={[info.purpose || "该阶段由后端工作流定义。"]} prose />
        <InfoBlock title="边界" items={[info.boundary || "遵循当前受控工作流边界。"]} prose />
        <InfoBlock title="输入依据" items={info.inputs || ["上游阶段产物"]} />
        <InfoBlock title="输出产物" items={info.outputs || ["阶段产物"]} />
      </div>
      {stage?.error && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{workflowErrorText(stage.error)}</div>}
      <div className="mt-4">
        <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">相关产物</div>
        {relatedArtifacts.length ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {relatedArtifacts.map((artifact) => (
              <button key={artifact.artifact_id} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-left hover:border-amber/50" onClick={() => selectWorkflowArtifact(artifact.artifact_id)}>
                <div className="text-[12.5px] text-ink-800">{artifact.label || "产物"}</div>
                <div className="mt-0.5 text-[11px] text-ink-400">{artifactTypeLabel(artifactContentType(artifact))}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-line px-3 py-5 text-center text-[12px] text-ink-400">该阶段暂未登记产物。</div>
        )}
      </div>
      {markdownPreview && (
        <div className="mt-4 border-t border-line pt-4">
          <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">阶段可读预览</div>
          <MarkdownMessage text={markdownPreview} />
        </div>
      )}
    </section>
  );
}

function InfoBlock({ title, items, prose = false }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 px-3 py-2.5">
      <div className="font-mono text-[10px] tracking-[0.12em] text-ink-400 uppercase mb-1.5">{title}</div>
      {prose ? (
        <p className="text-[12.5px] leading-5 text-ink-600">{items[0]}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item) => <li key={item} className="text-[12.5px] leading-5 text-ink-600">• {item}</li>)}
        </ul>
      )}
    </div>
  );
}

function ArtifactPreviewPane({ stages }) {
  const preview = useAppStore((s) => s.workflow.preview);
  const selectWorkflowResult = useAppStore((s) => s.selectWorkflowResult);
  const artifact = preview.artifact;
  const contentType = artifactContentType(artifact || { artifact_id: preview.selectedArtifactId });

  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <PaneTitle kicker="产物预览" title={artifact?.label || "读取产物"}>
        <button className="btn-light text-[12px]" onClick={selectWorkflowResult}>返回最终结果</button>
      </PaneTitle>
      {preview.loading && <div className="rounded-md border border-dashed border-line px-3 py-8 text-center text-[12.5px] text-ink-400">正在读取产物…</div>}
      {preview.error && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{workflowErrorText(preview.error)}</div>}
      {!preview.loading && !preview.error && artifact && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-[11.5px] text-ink-500">
            <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{artifactTypeLabel(contentType)}</span>
            <span>{stageLabel(stages, artifact.artifact_type)}</span>
            <span className="font-mono truncate text-ink-400">{artifact.artifact_id}</span>
          </div>
          {contentType === "markdown" && <MarkdownMessage text={artifact.text || ""} />}
          {contentType === "json" && <JsonArtifactPreview artifact={artifact} />}
          {contentType === "text" && <pre className="whitespace-pre-wrap break-words rounded-md bg-paper-100 p-3 text-[12px] text-ink-700">{artifact.text || ""}</pre>}
        </>
      )}
    </section>
  );
}

function JsonArtifactPreview({ artifact }) {
  const payload = artifact.json;
  const keys = payload && typeof payload === "object" && !Array.isArray(payload) ? Object.keys(payload) : [];
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-line bg-paper-50 px-3 py-2.5">
        <div className="flex items-center gap-2 text-[13px] text-ink-800">
          <Braces size={14} className="text-ink-400" />
          {jsonSummary(payload)}
        </div>
        {keys.length > 0 && <div className="mt-1 text-[12px] leading-5 text-ink-500">顶层字段：{keys.slice(0, 12).join("、")}{keys.length > 12 ? "…" : ""}</div>}
      </div>
      <details className="rounded-md border border-line bg-paper-50 px-3 py-2">
        <summary className="cursor-pointer text-[12.5px] text-ink-600">查看原始 JSON</summary>
        <pre className="mt-2 max-h-[520px] overflow-auto whitespace-pre-wrap break-words text-[11.5px] text-ink-700">{artifact.text || JSON.stringify(payload, null, 2)}</pre>
      </details>
    </div>
  );
}

function EvidenceDetailPane({ card }) {
  const selectWorkflowArtifact = useAppStore((s) => s.selectWorkflowArtifact);
  if (!card) {
    return (
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <PaneTitle kicker="证据卡片" title="未找到证据" />
        <p className="text-[13px] text-ink-500">该证据卡片可能尚未加载或不属于当前工作流。</p>
      </section>
    );
  }
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <PaneTitle kicker="证据卡片详情" title={card.title || card.evidence_id}>
        {card.artifact_id && (
          <button className="btn-light text-[12px]" onClick={() => selectWorkflowArtifact(card.artifact_id)}>查看原始证据产物</button>
        )}
      </PaneTitle>
      <div className="mb-3 flex flex-wrap gap-2 text-[11.5px] text-ink-500">
        <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{card.evidence_id}</span>
        <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{card.role || "未标注角色"}</span>
        <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{card.support_strength || "支持强度未知"}</span>
        {card.selected && <span className="rounded border border-teal/30 bg-teal/10 px-2 py-0.5 text-teal">代表证据</span>}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <InfoBlock title="论文" items={[card.title || "未知标题", card.paper_id || "未知 paper_id", card.year ? `年份：${card.year}` : "年份未知", card.journal || "期刊未知"]} />
        <InfoBlock title="证据属性" items={[`相关性：${formatPercentish(card.relevance_score)}`, `角色：${card.role || "未知"}`, `支持强度：${card.support_strength || "未知"}`]} />
      </div>
      <div className="mt-4 rounded-md border border-line bg-paper-50 px-3 py-2.5">
        <div className="font-mono text-[10px] tracking-[0.12em] text-ink-400 uppercase mb-1.5">标准化陈述</div>
        <p className="text-[13px] leading-6 text-ink-700">{card.normalized_statement || "该证据卡没有可显示的标准化陈述。"}</p>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <InfoBlock title="来源定位" items={Object.keys(card.source_locator || {}).length ? Object.entries(card.source_locator).map(([key, value]) => `${key}: ${String(value)}`) : ["暂无定位信息"]} />
        <InfoBlock title="警告" items={(card.warnings || []).length ? card.warnings : ["无警告"]} />
      </div>
    </section>
  );
}

function DiagnosticDetailPane({ item, stages }) {
  const selectWorkflowArtifact = useAppStore((s) => s.selectWorkflowArtifact);
  if (!item) {
    return (
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <PaneTitle kicker="诊断详情" title="未找到诊断" />
        <p className="text-[13px] text-ink-500">该诊断可能尚未加载或不属于当前工作流。</p>
      </section>
    );
  }
  const [severityText, severityTone] = severityLabel(item.severity);
  const metricItems = Object.entries(item.metrics || {}).map(([key, value]) => `${key}: ${String(value)}`);
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <PaneTitle kicker="诊断详情" title={item.label || item.diagnostic_id}>
        {item.artifact_id && (
          <button className="btn-light text-[12px]" onClick={() => selectWorkflowArtifact(item.artifact_id)}>查看诊断产物</button>
        )}
      </PaneTitle>
      <div className="mb-3 flex flex-wrap gap-2 text-[11.5px] text-ink-500">
        <span className={clsx("rounded border px-2 py-0.5", severityTone)}>{severityText}</span>
        <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{stageLabel(stages, item.stage)}</span>
        <span className="rounded border border-line bg-paper-50 px-2 py-0.5">{item.diagnostic_id}</span>
      </div>
      <div className="rounded-md border border-line bg-paper-50 px-3 py-2.5">
        <div className="font-mono text-[10px] tracking-[0.12em] text-ink-400 uppercase mb-1.5">摘要</div>
        <p className="text-[13px] leading-6 text-ink-700">{item.summary || "该诊断没有摘要。"}</p>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <InfoBlock title="指标" items={metricItems.length ? metricItems.slice(0, 12) : ["暂无指标"]} />
        <InfoBlock title="警告" items={(item.warnings || []).length ? item.warnings : ["无警告"]} />
        <InfoBlock title="错误" items={(item.errors || []).length ? item.errors : ["无错误"]} />
      </div>
    </section>
  );
}

function RunLogPanel({ log, status }) {
  const [open, setOpen] = useState(false);
  const entries = log || [];
  const visible = open ? entries : entries.slice(-5);
  return (
    <section className="mt-4 rounded-lg border border-line bg-paper-0">
      <button className="flex w-full items-center justify-between px-3 py-2 text-left" onClick={() => setOpen((value) => !value)}>
        <span className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase">运行日志</span>
        <span className="flex items-center gap-2 text-[11.5px] text-ink-400">
          {status === "running" && !open ? "最近 5 条" : `${entries.length} 条事件`}
          <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {(open || status === "running") && (
        <div className="border-t border-line px-3 py-2">
          {visible.length === 0 ? (
            <div className="py-4 text-center text-[12px] text-ink-400">暂无运行事件。</div>
          ) : (
            <div className="space-y-1 font-mono text-[11.5px]">
              {visible.map((entry, i) => (
                <div key={`${entry.at}-${i}`} className="text-ink-600">
                  <span className="text-ink-300">{new Date(entry.at).toLocaleTimeString()}</span> · {entry.line}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function WorkflowSidePanel({ artifacts, stages, insights, activeTab, onTab, onArtifact, onEvidence, onDiagnostic }) {
  const tabs = [
    ["artifacts", "产物"],
    ["evidence", "证据"],
    ["diagnostics", "诊断"],
  ];
  return (
    <aside className="border-l border-line bg-paper-0 overflow-y-auto p-4">
      <div className="mb-3 grid grid-cols-3 rounded-md border border-line bg-paper-50 p-1">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => onTab(id)}
            className={clsx(
              "rounded px-2 py-1.5 text-[12px] transition-colors",
              activeTab === id ? "bg-paper-0 text-ink-900 shadow-sm" : "text-ink-500 hover:text-ink-800"
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === "evidence" ? (
        <EvidenceIndex insights={insights} onSelect={onEvidence} />
      ) : activeTab === "diagnostics" ? (
        <DiagnosticIndex insights={insights} stages={stages} onSelect={onDiagnostic} />
      ) : (
        <ArtifactIndex artifacts={artifacts} stages={stages} onSelect={onArtifact} />
      )}
    </aside>
  );
}

function ArtifactIndex({ artifacts, stages, onSelect }) {
  return (
    <div>
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">产物</div>
      {artifacts.length === 0 ? (
        <div className="text-[12px] text-ink-400 py-4">暂无产物</div>
      ) : (
        <div className="space-y-2">
          {artifacts.map((artifact) => {
            const type = artifactContentType(artifact);
            const Icon = type === "json" ? Braces : FileText;
            const stageId = artifactStageId(artifact);
            return (
              <button
                key={artifact.artifact_id}
                type="button"
                onClick={() => onSelect(artifact.artifact_id)}
                className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-left hover:border-amber/50 hover:bg-amber/5"
              >
                <div className="flex items-center gap-2">
                  <Icon size={14} className="text-ink-400" />
                  <div className="min-w-0 flex-1 truncate text-[12.5px] text-ink-800">{artifact.label || "产物"}</div>
                </div>
                <div className="mt-1 text-[11px] text-ink-500">{stageLabel(stages, stageId)} · {artifactTypeLabel(type)}</div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-ink-400">{artifact.artifact_id}</div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EvidenceIndex({ insights, onSelect }) {
  const [filter, setFilter] = useState("all");
  const evidence = insights.data?.evidence || {};
  const cards = evidence.cards || [];
  const visible = cards.filter((card) => {
    if (filter === "selected") return card.selected;
    if (filter === "warnings") return (card.warnings || []).length > 0;
    return true;
  });
  return (
    <div>
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">证据</div>
      {insights.loading && <div className="text-[12px] text-ink-400 py-4">正在读取证据摘要…</div>}
      {insights.error && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{workflowErrorText(insights.error)}</div>}
      {!insights.loading && !insights.error && !evidence.available && <div className="text-[12px] text-ink-400 py-4">暂无可读证据卡片。</div>}
      {evidence.available && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <MetricCard label="证据卡片" value={evidence.card_count || 0} />
            <MetricCard label="代表证据" value={evidence.selected_count || 0} />
          </div>
          <div className="mt-2 rounded-md border border-line bg-paper-50 px-3 py-2">
            <div className="text-[11px] text-ink-400">角色覆盖</div>
            <div className="mt-1 text-[12px] leading-5 text-ink-600">{Object.entries(evidence.role_counts || {}).slice(0, 5).map(([key, value]) => `${key} ${value}`).join(" · ") || "暂无"}</div>
          </div>
          <div className="mt-3 flex gap-1">
            {[["all", "全部"], ["selected", "代表"], ["warnings", "有警告"]].map(([id, label]) => (
              <button key={id} className={clsx("rounded border px-2 py-1 text-[11.5px]", filter === id ? "border-amber bg-amber/10 text-ink-800" : "border-line bg-paper-50 text-ink-500")} onClick={() => setFilter(id)}>
                {label}
              </button>
            ))}
          </div>
          <div className="mt-3 space-y-2">
            {visible.map((card) => (
              <button key={card.evidence_id} type="button" onClick={() => onSelect(card.evidence_id)} className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-left hover:border-amber/50 hover:bg-amber/5">
                <div className="flex items-center gap-2">
                  <ListChecks size={14} className={card.selected ? "text-teal" : "text-ink-300"} />
                  <div className="min-w-0 flex-1 truncate text-[12.5px] text-ink-800">{card.title || card.evidence_id}</div>
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10.5px] text-ink-500">
                  <span className="rounded border border-line bg-paper-0 px-1.5 py-0.5">{card.role || "role?"}</span>
                  <span className="rounded border border-line bg-paper-0 px-1.5 py-0.5">{card.support_strength || "support?"}</span>
                  {card.selected && <span className="rounded border border-teal/30 bg-teal/10 px-1.5 py-0.5 text-teal">代表</span>}
                </div>
                <div className="mt-1 line-clamp-2 text-[11.5px] leading-4 text-ink-500">{card.normalized_statement || "暂无标准化陈述"}</div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function DiagnosticIndex({ insights, stages, onSelect }) {
  const diagnostics = insights.data?.diagnostics || {};
  const items = diagnostics.items || [];
  return (
    <div>
      <div className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase mb-2">诊断</div>
      {insights.loading && <div className="text-[12px] text-ink-400 py-4">正在读取诊断摘要…</div>}
      {insights.error && <div className="rounded-md bg-red-50 px-3 py-2 text-[12px] text-red-600">{workflowErrorText(insights.error)}</div>}
      {!insights.loading && !insights.error && !diagnostics.available && <div className="text-[12px] text-ink-400 py-4">暂无诊断摘要。</div>}
      {diagnostics.available && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <MetricCard label="信息" value={diagnostics.severity_counts?.info || 0} />
            <MetricCard label="警告" value={diagnostics.severity_counts?.warning || 0} />
            <MetricCard label="错误" value={diagnostics.severity_counts?.error || 0} />
          </div>
          <div className="mt-3 space-y-2">
            {items.map((item) => {
              const [severityText, severityTone] = severityLabel(item.severity);
              return (
                <button key={item.diagnostic_id} type="button" onClick={() => onSelect(item.diagnostic_id)} className="w-full rounded-md border border-line bg-paper-50 px-3 py-2 text-left hover:border-amber/50 hover:bg-amber/5">
                  <div className="flex items-center gap-2">
                    <span className={clsx("rounded border px-1.5 py-0.5 text-[10.5px]", severityTone)}>{severityText}</span>
                    <div className="min-w-0 flex-1 truncate text-[12.5px] text-ink-800">{item.label || item.diagnostic_id}</div>
                  </div>
                  <div className="mt-1 text-[11px] text-ink-500">{stageLabel(stages, item.stage)}</div>
                  <div className="mt-1 line-clamp-2 text-[11.5px] leading-4 text-ink-500">{item.summary}</div>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function MetricCard({ label, value }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 px-2.5 py-2">
      <div className="text-[10.5px] text-ink-400">{label}</div>
      <div className="mt-0.5 font-mono text-[15px] text-ink-800">{value}</div>
    </div>
  );
}

function RunningClock({ active, startedAt }) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const t0 = startedAt ? startedAt * 1000 : Date.now();
    setSec(Math.max(0, Math.floor((Date.now() - t0) / 1000)));
    const id = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [active, startedAt]);
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1 text-amber">
      <Loader2 size={11} className="animate-spin" /> {Math.floor(sec / 60)}:{String(sec % 60).padStart(2, "0")} 执行中
    </span>
  );
}

function Controls({ status, streaming, pauseRequested, onStart, onResume, onPause }) {
  if (status === "draft") {
    return (
      <button className="btn-dark flex items-center gap-1.5" onClick={onStart}>
        <Play size={14} /> 开始执行
      </button>
    );
  }
  if (status === "running") {
    return (
      <div className="flex items-center gap-2">
        {streaming && <Loader2 size={15} className="text-amber animate-spin" />}
        <button className="btn-light flex items-center gap-1.5" onClick={onPause} disabled={pauseRequested} title={pauseRequested ? "将在当前步骤完成后暂停" : undefined}>
          <Pause size={14} /> {pauseRequested ? "暂停中…" : "暂停"}
        </button>
      </div>
    );
  }
  if (status === "failed" || status === "paused") {
    return (
      <button className="btn-dark flex items-center gap-1.5" onClick={onResume}>
        <RotateCw size={14} /> 继续执行
      </button>
    );
  }
  return null;
}
