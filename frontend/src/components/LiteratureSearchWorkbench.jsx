import React, { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  Activity,
  Archive,
  Boxes,
  FileSearch,
  FlaskConical,
  Layers3,
  ListChecks,
  Play,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useAppStore } from "../store/useAppStore";
import ChatPanel from "./ChatPanel";
import ResultsPanel from "./ResultsPanel";
import RetrievalInspector from "./RetrievalInspector";

// Block 4b:普通研究路径只从 Chat 进入。手动工具控制台是早期调试形态,降级到
// 开发者模式后才出现(developerMode),普通用户不可见。
const PRODUCT_TABS = [["chat", "对话", Activity]];
const DEV_TABS = [
  ["overview", "概览", ListChecks],
  ["search", "检索", Search],
  ["paper", "文献", FileSearch],
  ["evidence", "证据", Layers3],
  ["pack", "证据包", Archive],
  ["task", "任务", Boxes],
  ["run", "运行", Play],
  ["extract", "抽取 / 对比", FlaskConical],
  ["analysis", "分析", ShieldCheck],
  ["artifacts", "产物", Archive],
];
const TABS = [...PRODUCT_TABS, ...DEV_TABS];

const OPTION_LABELS = {
  "": "使用默认",
  library: "文献库",
  collection: "集合",
  "library+boost": "文献库 + 增强",
  default: "默认",
  review: "综述",
  idea: "想法",
  data: "数据",
  hybrid: "混合检索",
  fts: "全文检索",
  vector: "向量检索",
};

const CHECKBOX_LABELS = {
  with_extract: "包含抽取",
  with_compare: "包含对比",
  with_notes: "包含笔记",
  with_synthesis: "包含综合",
  with_quality: "包含质量检查",
};

const JOB_STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  completed_with_errors: "部分完成",
  failed: "失败",
  cancelling: "取消中",
  cancelled: "已取消",
};

const FIELD_LABELS = {
  document_id: "文档 ID",
  doi: "DOI",
  paper_id: "文献 ID",
  label: "标签",
  pack_path: "证据包路径",
  evidence_id: "证据 ID",
  run_id: "运行 ID",
  task_id: "任务 ID",
  bundle_id: "分析包 ID",
  answer_text: "答案文本",
};

export default function LiteratureSearchWorkbench() {
  const rawToolTab = useAppStore((s) => s.literatureSearch.activeToolTab);
  const setTab = useAppStore((s) => s.setLiteratureToolTab);
  const developerMode = useAppStore((s) => s.developerMode);
  const loadStatus = useAppStore((s) => s.loadLiteratureStatus);
  const loadArtifacts = useAppStore((s) => s.loadLiteratureArtifacts);

  // Outside developer mode only Chat exists; never land on a dev console.
  const tabs = developerMode ? TABS : PRODUCT_TABS;
  const activeToolTab = developerMode ? rawToolTab : "chat";

  useEffect(() => {
    if (!developerMode) return;
    loadStatus();
    loadArtifacts();
  }, [developerMode, loadStatus, loadArtifacts]);

  if (activeToolTab === "chat") {
    return (
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {developerMode && <WorkbenchTabs active={activeToolTab} onChange={setTab} tabs={tabs} compact />}
        <ChatPanel />
        <ResultsPanel />
      </div>
    );
  }

  return (
    <div className="flex-1 flex min-h-0 bg-paper-50">
      <WorkbenchTabs active={activeToolTab} onChange={setTab} tabs={tabs} />
      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-6 py-5">
          <ToolHeader />
          {activeToolTab === "overview" && <OverviewTab />}
          {activeToolTab === "search" && <SearchTab />}
          {activeToolTab === "paper" && <PaperTab />}
          {activeToolTab === "evidence" && <EvidenceTab />}
          {activeToolTab === "pack" && <PackTab />}
          {activeToolTab === "task" && <TaskTab />}
          {activeToolTab === "run" && <RunTab />}
          {activeToolTab === "extract" && <ExtractCompareTab />}
          {activeToolTab === "analysis" && <AnalysisTab />}
          {activeToolTab === "artifacts" && <ArtifactsTab />}
        </div>
      </main>
      <RightInspector />
    </div>
  );
}

function WorkbenchTabs({ active, onChange, tabs = TABS, compact = false }) {
  return (
    <aside className={clsx("border-r border-line bg-paper-0 flex-shrink-0", compact ? "w-14" : "w-[176px]")}>
      <div className="p-2 space-y-1">
        {tabs.map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            title={label}
            className={clsx(
              "w-full flex items-center gap-2 rounded-md px-2.5 py-2 text-[12.5px] transition-colors",
              active === key ? "bg-ink-900 text-paper-50" : "text-ink-500 hover:bg-paper-100 hover:text-ink-900",
              compact && "justify-center px-0"
            )}
          >
            <Icon size={15} />
            {!compact && <span className="truncate">{label}</span>}
          </button>
        ))}
      </div>
    </aside>
  );
}

function ToolHeader() {
  const active = useAppStore((s) => s.literatureSearch.activeToolTab);
  const [, label] = TABS.find(([key]) => key === active) || [];
  return (
    <div className="mb-4">
      <h1 className="font-serif text-[22px] text-ink-900">{label}</h1>
      <p className="text-[13px] text-ink-500 mt-1">
        完整研究智能体能力已归入文献检索分析模块，产物保存在本地 research_agent 目录。
      </p>
    </div>
  );
}

function OverviewTab() {
  const status = useAppStore((s) => s.literatureSearch.status);
  const loadStatus = useAppStore((s) => s.loadLiteratureStatus);
  return (
    <div className="space-y-3">
      <button className="btn-dark" onClick={loadStatus}>刷新状态</button>
      <div className="grid grid-cols-3 gap-3">
        <StatusCard title="自检" data={status.selfcheck} />
        <StatusCard title="索引" data={status.indexStatus} />
        <StatusCard title="向量" data={status.vectorStatus} />
      </div>
    </div>
  );
}

function StatusCard({ title, data }) {
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <h2 className="font-serif text-[15px] text-ink-900">{title}</h2>
      <JsonBlock data={data || { status: "loading" }} compact />
    </section>
  );
}

function SearchTab() {
  const runSearch = useAppStore((s) => s.runLiteratureSearch);
  const result = useAppStore((s) => s.literatureSearch.searchResults);
  const effective = useAppStore((s) => s.settings.effective);
  const defaults = {
    limit: effective?.["retrieval.default_limit"]?.value ?? 10,
    scope: effective?.["retrieval.default_scope"]?.value ?? "library",
    profile: effective?.["retrieval.default_profile"]?.value ?? "default",
    retrieval: effective?.["retrieval.default_retrieval"]?.value ?? "hybrid",
  };
  const [form, setForm] = useState({
    query: "perovskite solar cell stability",
    limit: "",
    scope: "",
    profile: "",
    retrieval: "",
    expand_assets: false,
  });
  const payload = cleanPayload({
    query: form.query,
    limit: form.limit === "" ? undefined : Number(form.limit),
    scope: form.scope,
    profile: form.profile,
    retrieval: form.retrieval,
    expand_assets: form.expand_assets,
  });
  return (
    <ToolLayout
      form={
        <>
          <TextArea label="查询" value={form.query} onChange={(query) => setForm({ ...form, query })} />
          <FormGrid>
            <Input label={`数量上限 · 默认 ${defaults.limit}`} type="number" value={form.limit} onChange={(limit) => setForm({ ...form, limit })} />
            <Select label={`范围 · 默认 ${defaults.scope}`} value={form.scope} options={["", "library", "collection", "library+boost"]} onChange={(scope) => setForm({ ...form, scope })} />
            <Select label={`配置档 · 默认 ${defaults.profile}`} value={form.profile} options={["", "default", "review", "idea", "data"]} onChange={(profile) => setForm({ ...form, profile })} />
            <Select label={`检索方式 · 默认 ${defaults.retrieval}`} value={form.retrieval} options={["", "hybrid", "fts", "vector"]} onChange={(retrieval) => setForm({ ...form, retrieval })} />
          </FormGrid>
          <button className="btn-dark" onClick={() => runSearch(payload)}>运行检索</button>
        </>
      }
      result={<SearchResults result={result} />}
    />
  );
}

const COVERAGE_LABEL = { sufficient: "证据较充分", partial: "可部分回答", weak: "证据偏少", none: "未找到可用证据" };
const COVERAGE_TONE = {
  sufficient: "bg-teal/10 text-teal border-teal/30",
  partial: "bg-amber-50 text-amber-700 border-amber-200",
  weak: "bg-amber-50 text-amber-700 border-amber-200",
  none: "bg-red-50 text-red-600 border-red-200",
};

function SearchResults({ result }) {
  const [inspectorOpen, setInspectorOpen] = useState(false);
  if (!result) return <Empty text="检索结果会显示在这里。" />;
  // Block 2: result is now an EvidenceAcquisitionPacket.
  const coverage = result.coverage || {};
  const breadth = result.breadth || {};
  const plan = result.query_plan || {};
  const vectorReason = plan.underlying?.vector_unavailable_reason || plan.vector_unavailable_reason;
  const status = coverage.status;
  return (
    <div className="space-y-3">
      <section className="rounded-lg border border-line bg-paper-0 p-4 space-y-2.5">
        <div className="flex items-center flex-wrap gap-2">
          {status && (
            <span className={clsx("rounded px-2 py-0.5 text-[11.5px] border", COVERAGE_TONE[status] || "bg-paper-100 text-ink-600 border-line")}>
              证据覆盖：{COVERAGE_LABEL[status] || status}
            </span>
          )}
          {breadth.breadth_limited && (
            <span className="rounded px-2 py-0.5 text-[11.5px] border bg-amber-50 text-amber-700 border-amber-200">代表性概览</span>
          )}
          {breadth.deep_research_suggested && (
            <span className="rounded px-2 py-0.5 text-[11.5px] border bg-amber-50 text-amber-700 border-amber-200">建议深度研究</span>
          )}
          <button className="ml-auto text-[11.5px] text-ink-500 hover:text-amber-600" onClick={() => setInspectorOpen(true)}>
            检索详情 →
          </button>
        </div>
        <div className="font-mono text-[11px] text-ink-500">
          意图：{result.query_intent?.type || "?"} · 检索方式：{result.retrieval_used || plan.final_retrieval_used || "?"}
          {breadth.candidate_paper_count != null
            ? ` · 候选 ${breadth.candidate_paper_count} 篇 / 作答 ${breadth.llm_context_evidence_count || 0} 条`
            : ` · 返回 ${result.results?.length || 0} 条`}
          {vectorReason ? ` · ${vectorReason}` : ""}
        </div>
        {(coverage.coverage_notes || []).map((n, i) => (
          <div key={i} className="text-[11.5px] text-ink-500">· {n}</div>
        ))}
      </section>
      {(result.results || []).map((paper) => (
        <section key={`${paper.article_id}-${paper.doi}`} className="rounded-lg border border-line bg-paper-0 p-4">
          <h3 className="font-serif text-[16px] text-ink-900">{paper.title}</h3>
          <div className="font-mono text-[11px] text-ink-500 mt-1">
            {paper.year} · {paper.journal} · {paper.doi || paper.article_id}
          </div>
          <div className="mt-3 space-y-2">
            {(paper.evidence || []).slice(0, 3).map((ev) => (
              <EvidenceSnippet key={ev.evidence_id || ev.source_path} evidence={ev} />
            ))}
          </div>
        </section>
      ))}
      {inspectorOpen && <RetrievalInspector data={result} onClose={() => setInspectorOpen(false)} />}
    </div>
  );
}

function PaperTab() {
  const callTool = useAppStore((s) => s.callLiteratureTool);
  const result = useAppStore((s) => s.literatureSearch.toolResult);
  const [lookup, setLookup] = useState({ article_id: "", doi: "", paper_id: "", section: "" });
  const payload = cleanPayload({
    article_id: lookup.article_id ? Number(lookup.article_id) : undefined,
    doi: lookup.doi,
    paper_id: lookup.paper_id,
    section: lookup.section,
  });
  return (
    <ToolLayout
      form={
        <>
          <FormGrid>
            <Input label="文章 ID" value={lookup.article_id} onChange={(article_id) => setLookup({ ...lookup, article_id })} />
            <Input label="DOI" value={lookup.doi} onChange={(doi) => setLookup({ ...lookup, doi })} />
            <Input label="文献 ID" value={lookup.paper_id} onChange={(paper_id) => setLookup({ ...lookup, paper_id })} />
            <Input label="章节" value={lookup.section} onChange={(section) => setLookup({ ...lookup, section })} />
          </FormGrid>
          <div className="flex gap-2">
            <button className="btn-dark" onClick={() => callTool("paperShow", payload)}>查看</button>
            <button className="btn-light" onClick={() => callTool("paperSections", payload)}>章节</button>
            <button className="btn-light" onClick={() => callTool("paperChunks", payload)}>切片</button>
          </div>
        </>
      }
      result={<JsonBlock data={result} />}
    />
  );
}

function EvidenceTab() {
  const callTool = useAppStore((s) => s.callLiteratureTool);
  const result = useAppStore((s) => s.literatureSearch.toolResult);
  const [form, setForm] = useState({ document_id: "", doi: "", paper_id: "", label: "", pack_path: "", evidence_id: "" });
  return (
    <ToolLayout
      form={
        <>
          <FormGrid>
            {Object.keys(form).map((key) => (
              <Input key={key} label={FIELD_LABELS[key] || key} value={form[key]} onChange={(value) => setForm({ ...form, [key]: value })} />
            ))}
          </FormGrid>
          <button className="btn-dark" onClick={() => callTool("evidenceExpand", cleanPayload({ ...form, document_id: form.document_id ? Number(form.document_id) : undefined }))}>
            展开证据
          </button>
        </>
      }
      result={<JsonBlock data={result} />}
    />
  );
}

function PackTab() {
  const startJob = useAppStore((s) => s.startLiteratureJob);
  const [form, setForm] = useState({ query: "perovskite solar cell stability", budget: 12000, limit: 8, scope: "library" });
  return <SimpleJobForm title="创建证据包" form={form} setForm={setForm} onSubmit={() => startJob("pack", form)} />;
}

function TaskTab() {
  const callTool = useAppStore((s) => s.callLiteratureTool);
  const startJob = useAppStore((s) => s.startLiteratureJob);
  const result = useAppStore((s) => s.literatureSearch.toolResult);
  const [form, setForm] = useState({ question: "compare perovskite solar cell stability strategies", budget: 20000, scope: "library" });
  return (
    <ToolLayout
      form={
        <>
          <TextArea label="问题" value={form.question} onChange={(question) => setForm({ ...form, question })} />
          <FormGrid>
            <Input label="预算" type="number" value={form.budget} onChange={(budget) => setForm({ ...form, budget: Number(budget) })} />
            <Select label="范围" value={form.scope} options={["library", "collection", "library+boost"]} onChange={(scope) => setForm({ ...form, scope })} />
          </FormGrid>
          <div className="flex gap-2">
            <button className="btn-light" onClick={() => callTool("taskPlan", form)}>规划</button>
            <button className="btn-dark" onClick={() => startJob("taskRun", form)}>运行任务</button>
          </div>
        </>
      }
      result={<JsonBlock data={result} />}
    />
  );
}

function RunTab() {
  const startJob = useAppStore((s) => s.startLiteratureJob);
  const callTool = useAppStore((s) => s.callLiteratureTool);
  const result = useAppStore((s) => s.literatureSearch.toolResult);
  const [form, setForm] = useState({
    question: "compare perovskite solar cell stability strategies",
    budget: 20000,
    scope: "library",
    with_extract: false,
    with_compare: false,
    with_notes: false,
    with_synthesis: false,
    with_quality: false,
  });
  const [runId, setRunId] = useState("");
  return (
    <ToolLayout
      form={
        <>
          <TextArea label="问题" value={form.question} onChange={(question) => setForm({ ...form, question })} />
          <FormGrid>
            <Input label="预算" type="number" value={form.budget} onChange={(budget) => setForm({ ...form, budget: Number(budget) })} />
            <Select label="范围" value={form.scope} options={["library", "collection", "library+boost"]} onChange={(scope) => setForm({ ...form, scope })} />
          </FormGrid>
          <Checkboxes form={form} setForm={setForm} keys={["with_extract", "with_compare", "with_notes", "with_synthesis", "with_quality"]} />
          <button className="btn-dark" onClick={() => startJob("run", form)}>开始运行</button>
          <div className="border-t border-line pt-3 mt-3">
            <Input label="运行 ID" value={runId} onChange={setRunId} />
            <div className="flex gap-2 mt-2">
              <button className="btn-light" onClick={() => callTool("runShow", runId)}>查看</button>
              <button className="btn-light" onClick={() => callTool("runResume", runId)}>继续</button>
              <button className="btn-light" onClick={() => callTool("runs")}>列表</button>
            </div>
          </div>
        </>
      }
      result={<JsonBlock data={result} />}
    />
  );
}

function ExtractCompareTab() {
  const startJob = useAppStore((s) => s.startLiteratureJob);
  const [form, setForm] = useState({ query: "perovskite solar cell stability", budget: 12000, pack_path: "", task_id: "", extract_id: "", sort_by: "" });
  return (
    <ToolLayout
      form={
        <>
          <TextArea label="查询" value={form.query} onChange={(query) => setForm({ ...form, query })} />
          <FormGrid>
            <Input label="预算" type="number" value={form.budget} onChange={(budget) => setForm({ ...form, budget: Number(budget) })} />
            <Input label="证据包路径" value={form.pack_path} onChange={(pack_path) => setForm({ ...form, pack_path })} />
            <Input label="任务 ID" value={form.task_id} onChange={(task_id) => setForm({ ...form, task_id })} />
            <Input label="抽取 ID" value={form.extract_id} onChange={(extract_id) => setForm({ ...form, extract_id })} />
            <Input label="排序字段" value={form.sort_by} onChange={(sort_by) => setForm({ ...form, sort_by })} />
          </FormGrid>
          <div className="flex gap-2">
            <button className="btn-dark" onClick={() => startJob("extract", cleanPayload(form))}>抽取</button>
            <button className="btn-light" onClick={() => startJob("compare", cleanPayload(form))}>对比</button>
          </div>
        </>
      }
      result={<ActiveJob />}
    />
  );
}

function AnalysisTab() {
  const startJob = useAppStore((s) => s.startLiteratureJob);
  const callTool = useAppStore((s) => s.callLiteratureTool);
  const result = useAppStore((s) => s.literatureSearch.toolResult);
  const [form, setForm] = useState({ run_id: "", task_id: "", pack_path: "", bundle_id: "", answer_text: "" });
  return (
    <ToolLayout
      form={
        <>
          <FormGrid>
            {Object.keys(form).map((key) => (
              <Input key={key} label={FIELD_LABELS[key] || key} value={form[key]} onChange={(value) => setForm({ ...form, [key]: value })} />
            ))}
          </FormGrid>
          <div className="flex flex-wrap gap-2">
            <button className="btn-dark" onClick={() => startJob("analysisBundle", cleanPayload(form))}>打包分析</button>
            <button className="btn-light" onClick={() => callTool("analysisShow", form.bundle_id)}>查看分析包</button>
            <button className="btn-light" onClick={() => startJob("verifyAnswer", cleanPayload(form))}>核查</button>
            <button className="btn-light" onClick={() => startJob("synthesize", cleanPayload(form))}>综合</button>
            <button className="btn-light" onClick={() => startJob("quality", cleanPayload(form))}>质量检查</button>
          </div>
        </>
      }
      result={<JsonBlock data={result} />}
    />
  );
}

function ArtifactsTab() {
  const artifacts = useAppStore((s) => s.literatureSearch.artifacts);
  const selected = useAppStore((s) => s.literatureSearch.selectedArtifact);
  const loadArtifacts = useAppStore((s) => s.loadLiteratureArtifacts);
  const selectArtifact = useAppStore((s) => s.selectLiteratureArtifact);
  return (
    <div className="grid grid-cols-[320px_1fr] gap-4">
      <section className="rounded-lg border border-line bg-paper-0 p-3">
        <button className="btn-dark mb-3" onClick={loadArtifacts}>刷新产物</button>
        <div className="space-y-1 max-h-[70vh] overflow-y-auto">
          {artifacts.map((item) => (
            <button key={item.artifact_id} onClick={() => selectArtifact(item.artifact_id)} className="w-full text-left rounded-md px-2.5 py-2 hover:bg-paper-100">
              <div className="text-[12.5px] text-ink-900 truncate">{item.title}</div>
              <div className="font-mono text-[10.5px] text-ink-500">{item.artifact_type}</div>
            </button>
          ))}
        </div>
      </section>
      <section className="rounded-lg border border-line bg-paper-0 p-4 min-w-0">
        {selected ? (
          <div className="space-y-4">
            <div>
              <h2 className="font-serif text-[17px] text-ink-900">{selected.title}</h2>
              <div className="font-mono text-[11px] text-ink-500 mt-1">{selected.json_path}</div>
            </div>
            {selected.markdown && <pre className="result-pre whitespace-pre-wrap">{selected.markdown}</pre>}
            <JsonBlock data={selected.content} />
          </div>
        ) : (
          <Empty text="选择一个产物查看内容。" />
        )}
      </section>
    </div>
  );
}

function SimpleJobForm({ title, form, setForm, onSubmit }) {
  return (
    <ToolLayout
      form={
        <>
          <h2 className="font-serif text-[16px] text-ink-900">{title}</h2>
          <TextArea label="查询" value={form.query} onChange={(query) => setForm({ ...form, query })} />
          <FormGrid>
            <Input label="预算" type="number" value={form.budget} onChange={(budget) => setForm({ ...form, budget: Number(budget) })} />
            <Input label="数量上限" type="number" value={form.limit} onChange={(limit) => setForm({ ...form, limit: Number(limit) })} />
            <Select label="范围" value={form.scope} options={["library", "collection", "library+boost"]} onChange={(scope) => setForm({ ...form, scope })} />
          </FormGrid>
          <button className="btn-dark" onClick={onSubmit}>启动任务</button>
        </>
      }
      result={<ActiveJob />}
    />
  );
}

function RightInspector() {
  const session = useAppStore((s) => {
    const sid = s.activeSessionByModule[s.activeModuleId];
    return s.sessionsById[sid];
  });
  return (
    <aside className="w-[360px] flex-shrink-0 border-l border-line bg-paper-0 p-4 overflow-y-auto">
      <h2 className="font-serif text-[16px] text-ink-900 mb-3">任务时间线</h2>
      <ActiveJob />
      <h2 className="font-serif text-[16px] text-ink-900 mt-6 mb-3">会话记忆</h2>
      <div className="space-y-2">
        <div className="font-mono text-[11px] text-ink-500">
          证据：{session?.context?.recent_evidence?.length || 0} · 产物：{session?.linkedArtifacts?.length || 0} · 任务：{session?.jobs?.length || 0}
        </div>
        {(session?.linkedArtifacts || []).slice(0, 6).map((artifact) => (
          <div key={`${artifact.artifact_id}-${artifact.linked_at}`} className="rounded-md border border-line bg-paper-50 px-3 py-2">
            <div className="text-[12px] text-ink-800 truncate">{artifact.title}</div>
            <div className="font-mono text-[10.5px] text-ink-500">{artifact.artifact_type} · {artifact.link_type}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function ActiveJob() {
  const { jobsById, activeJobId } = useAppStore((s) => s.literatureSearch);
  const job = activeJobId ? jobsById[activeJobId] : null;
  if (!job) return <Empty text="长任务事件会显示在这里。" />;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[11px] text-ink-500">{job.job_id} · {JOB_STATUS_LABELS[job.status] || job.status}</div>
      {(job.events || []).map((event, idx) => (
        <div key={idx} className="rounded-md border border-line bg-paper-50 px-3 py-2 text-[12px]">
          <span className="font-mono text-amber-600">{event.type}</span>
          {event.label ? <span className="text-ink-700"> · {event.label}</span> : null}
          {event.message ? <div className="text-red-500 mt-1">{event.message}</div> : null}
        </div>
      ))}
    </div>
  );
}

function ToolLayout({ form, result }) {
  const error = useAppStore((s) => s.literatureSearch.error);
  const loading = useAppStore((s) => s.literatureSearch.loading);
  return (
    <div className="grid grid-cols-[360px_1fr] gap-4">
      <section className="rounded-lg border border-line bg-paper-0 p-4 space-y-3 h-fit">
        {form}
        {loading && <div className="font-mono text-[11px] text-ink-500">运行中...</div>}
        {error && <div className="rounded-md bg-red-50 text-red-600 text-[12px] px-3 py-2">{error}</div>}
      </section>
      <section className="rounded-lg border border-line bg-paper-0 p-4 min-w-0">{result}</section>
    </div>
  );
}

function EvidenceSnippet({ evidence }) {
  return (
    <div className="rounded-md bg-paper-50 border border-line px-3 py-2">
      <div className="font-mono text-[10.5px] text-ink-500">
        {evidence.evidence_id} · {evidence.kind} · {evidence.confidence} · {evidence.source_path}
      </div>
      <div className="text-[12.5px] text-ink-700 mt-1 leading-relaxed">{evidence.snippet || evidence.text}</div>
    </div>
  );
}

function FormGrid({ children }) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>;
}

function Input({ label, value, onChange, type = "text" }) {
  return (
    <label className="block">
      <span className="form-label">{label}</span>
      <input type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)} className="form-input" />
    </label>
  );
}

function Select({ label, value, options, onChange }) {
  return (
    <label className="block">
      <span className="form-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="form-input">
        {options.map((option) => <option key={option} value={option}>{OPTION_LABELS[option] || option}</option>)}
      </select>
    </label>
  );
}

function TextArea({ label, value, onChange }) {
  return (
    <label className="block">
      <span className="form-label">{label}</span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={4} className="form-input resize-y" />
    </label>
  );
}

function Checkboxes({ form, setForm, keys }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {keys.map((key) => (
        <label key={key} className="flex items-center gap-2 text-[12px] text-ink-600">
          <input type="checkbox" checked={!!form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} />
          {CHECKBOX_LABELS[key] || key}
        </label>
      ))}
    </div>
  );
}

function JsonBlock({ data, compact = false }) {
  const text = useMemo(() => JSON.stringify(data || {}, null, compact ? 1 : 2), [data, compact]);
  return <pre className="result-pre">{text}</pre>;
}

function Empty({ text }) {
  return <div className="text-[12.5px] text-ink-500 text-center py-10">{text}</div>;
}

function cleanPayload(payload) {
  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== "" && value !== undefined && value !== null)
  );
}
