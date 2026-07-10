import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Copy, Loader2, Lock, Plus, Save, Sparkles, Trash2 } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import { emptySchemaWorkbench } from "./schemaWorkbenchState";
import {
  MATERIAL_RECORD_SCHEMA,
  TREE_TYPES,
  cloneNode,
  deleteAtPath,
  fieldsFromTree,
  getAtPath,
  groupsFromTree,
  insertChild,
  insertSibling,
  makeTreeKeysUnique,
  mergeTree,
  moveNode,
  newSchemaNode,
  normalizeTree,
  parentSupportsChildren,
  sampleNode,
  sampleRecord,
  schemaResolutionDefaults,
  treeFromFlatFields,
  treeStats,
  toSchemaKey,
  uniqueNodeKey,
  updateAtPath,
} from "./schemaTreeUtils";

const INPUT_CLASS = "min-h-[34px] min-w-0 rounded-md border border-line bg-paper-0 px-2 py-1.5 text-[12.5px] outline-none focus:border-amber";
const EMPTY_SCHEMA_WORKBENCH = emptySchemaWorkbench();
const SCHEMA_PHASE_LABELS = {
  submitting: "正在提交字段定义",
  queued: "等待解析任务开始",
  source_parsing: "正在解析输入格式",
  requirement_graph: "正在构建要求关系",
  semantic_compile: "正在调用模型进行语义编译",
  normalization: "正在规范化字段结构",
  validation: "正在验证字段和覆盖率",
  targeted_repair: "正在定向修复编译结果",
  final_validation: "正在复核修复结果",
  completed: "字段结构解析完成",
  submission_failed: "字段解析任务提交失败",
};

function defaultDraft(task) {
  return {
    schemaMode: "nested_material",
    recordSchema: MATERIAL_RECORD_SCHEMA,
    fieldTree: [],
    fieldGroups: [],
    fields: [],
    baseCollectionVersion: task?.currentCollectionVersion || null,
  };
}

export default function SchemaDesigner({ task }) {
  const schema = useAppStore((s) => s.structuredExtraction.schema);
  const workbench = useAppStore((s) => s.structuredExtraction.schemaWorkbenchByTask?.[task?.taskId] || EMPTY_SCHEMA_WORKBENCH);
  const loadDraft = useAppStore((s) => s.loadExtractionSchemaDraft);
  const saveDraft = useAppStore((s) => s.saveExtractionSchemaDraft);
  const assistSchema = useAppStore((s) => s.assistExtractionSchema);
  const updateWorkbench = useAppStore((s) => s.updateExtractionSchemaWorkbench);
  const resumeCompilation = useAppStore((s) => s.resumeExtractionSchemaCompilation);
  const resolveCompilation = useAppStore((s) => s.resolveExtractionSchemaCompilation);
  const applyCompilation = useAppStore((s) => s.applyExtractionSchemaCompilation);
  const freezeSchema = useAppStore((s) => s.freezeExtractionSchema);
  const loadVersions = useAppStore((s) => s.loadExtractionSchemaVersions);
  const duplicateToDraft = useAppStore((s) => s.duplicateExtractionSchemaToDraft);
  const [draft, setDraft] = useState(defaultDraft(task));
  const [expanded, setExpanded] = useState({});
  const [selectedPath, setSelectedPath] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewMode, setPreviewMode] = useState("summary");
  const treeWorkbenchRef = useRef(null);
  const definitionText = workbench.definitionText;
  const applyMode = workbench.applyMode;
  const previewTree = workbench.previewTree;
  const syncMessage = workbench.syncMessage;
  const compilationActive = ["queued", "running"].includes(workbench.executionStatus) || workbench.phase === "submitting";
  const setDefinitionText = (value) => updateWorkbench(task.taskId, { definitionText: value });
  const setApplyMode = (value) => updateWorkbench(task.taskId, { applyMode: value });

  useEffect(() => {
    if (!task?.taskId || !task.currentCollectionVersion) return;
    loadDraft(task.taskId).catch(() => {});
    loadVersions(task.taskId).catch(() => {});
    resumeCompilation(task.taskId).catch(() => {});
  }, [task?.taskId, task?.currentCollectionVersion]);

  useEffect(() => {
    if (schema.draft) setDraft(normalizeDraft(schema.draft, task));
    else setDraft(defaultDraft(task));
  }, [schema.draft?.updatedAt, task?.taskId]);

  useEffect(() => {
    const tree = draft.fieldTree || [];
    if (!tree.length) {
      setSelectedPath(null);
      return;
    }
    if (!selectedPath || !getAtPath(tree, selectedPath)) setSelectedPath([0]);
  }, [draft.fieldTree]);

  const validation = useMemo(() => validateDraft(draft), [draft]);
  const stats = useMemo(() => treeStats(draft.fieldTree || []), [draft.fieldTree]);
  const canFreeze = task.currentCollectionVersion && (draft.fieldTree || []).length > 0 && validation.length === 0;
  const selectedNode = selectedPath ? getAtPath(draft.fieldTree || [], selectedPath) : null;
  const compilation = schema.assistResult?.result || null;

  if (!task.currentCollectionVersion) {
    return (
      <div className="rounded-lg border border-line bg-paper-0 p-8 text-center">
        <div className="text-[15px] font-medium text-ink-900">需要先冻结文献集合</div>
        <div className="mt-2 text-[13px] text-ink-500">材料级 JSON 字段方案必须绑定一个文献集合版本。</div>
      </div>
    );
  }

  const setTree = (tree, nextSelectedPath = selectedPath) => {
    setDraft((prev) => withTree(prev, tree));
    setSelectedPath(nextSelectedPath);
  };

  const save = async () => {
    const fieldTree = normalizeTree(draft.fieldTree || []);
    await saveDraft(task.taskId, {
      schemaMode: draft.schemaMode || "nested_material",
      recordSchema: draft.recordSchema || MATERIAL_RECORD_SCHEMA,
      fieldTree,
      fieldGroups: groupsFromTree(fieldTree),
      fields: fieldsFromTree(fieldTree),
      globalInstructions: draft.globalInstructions || [],
      sourceCompilationId: draft.sourceCompilationId || null,
    });
  };

  const parseDefinition = async () => {
    updateWorkbench(task.taskId, { syncMessage: "", previewTree: null, startedAt: Date.now() / 1000 });
    await assistSchema(task.taskId, {
      action: "parse_field_definition",
      instruction: definitionText,
      draft,
    }).catch(() => {});
  };

  const syncPreviewToTree = async () => {
    if (!previewTree) return;
    const confirmations = [];
    if (compilation?.status === "valid_with_warnings") confirmations.push("编译结果包含警告，请确认报告中的自动修正和模型提示。");
    if ((draft.fieldTree || []).length > 0) confirmations.push("当前字段树已有内容，应用会替换或合并当前结构。");
    if (confirmations.length) {
      const confirmed = typeof window === "undefined" ? true : window.confirm(`${confirmations.join("\n\n")}\n\n是否继续？`);
      if (!confirmed) return;
    }
    if (compilation?.compilationId) {
      const applied = await applyCompilation(task.taskId, compilation.compilationId, applyMode);
      setDraft(normalizeDraft(applied, task));
      setSelectedPath(applied?.fieldTree?.length ? [0] : null);
    } else {
      const next = makeTreeKeysUnique(applyMode === "merge" ? mergeTree(draft.fieldTree || [], previewTree) : previewTree);
      setTree(next, next.length ? [0] : null);
    }
    updateWorkbench(task.taskId, { previewTree: null, syncMessage: "已同步，下面可以继续手动调整。" });
    const scroll = () => treeWorkbenchRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(scroll);
    else setTimeout(scroll, 0);
  };

  const addTopLevel = () => {
    const key = uniqueNodeKey(draft.fieldTree || [], "new_section");
    const nextNode = newSchemaNode(key, labelForGeneratedKey("新分组", key), "object");
    const next = [...(draft.fieldTree || []), nextNode];
    setTree(next, [next.length - 1]);
  };

  const addChild = (path) => {
    const parent = getAtPath(draft.fieldTree || [], path);
    const key = uniqueNodeKey(parent?.children || [], "child_field");
    const nextNode = newSchemaNode(key, labelForGeneratedKey("子字段", key), "string");
    const childIndex = parent?.children?.length || 0;
    setTree(insertChild(draft.fieldTree || [], path, nextNode), [...path, childIndex]);
    setExpanded((prev) => ({ ...prev, [path.join(".")]: true }));
  };

  const addSibling = (path) => {
    const siblings = siblingNodesAtPath(draft.fieldTree || [], path);
    const key = uniqueNodeKey(siblings, "new_field");
    const nextNode = newSchemaNode(key, labelForGeneratedKey("新字段", key), "string");
    setTree(insertSibling(draft.fieldTree || [], path, nextNode), [...path.slice(0, -1), path[path.length - 1] + 1]);
  };

  const duplicate = (path) => {
    setTree(insertSibling(draft.fieldTree || [], path, cloneNode(getAtPath(draft.fieldTree || [], path))), [...path.slice(0, -1), path[path.length - 1] + 1]);
  };

  const remove = (path) => {
    const next = deleteAtPath(draft.fieldTree || [], path);
    setTree(next, nextSelectionAfterDelete(next, path));
  };

  const move = (path, direction) => {
    setTree(moveNode(draft.fieldTree || [], path, direction), [...path.slice(0, -1), path[path.length - 1] + direction]);
  };

  const updateSelected = (patch) => {
    if (!selectedPath) return;
    setTree(updateAtPath(draft.fieldTree || [], selectedPath, (node) => ({ ...node, ...patch })), selectedPath);
  };

  return (
    <div className="space-y-4">
      {schema.error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{schema.error}</div>}
      {validation.length > 0 && <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[13px] text-ink-700">{validation.join(" · ")}</div>}

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-medium text-ink-900">记录结构</h2>
            <div className="mt-1 text-[12.5px] leading-5 text-ink-500">
              记录粒度、身份字段和 data 结构由编译结果或手工草稿共同定义。
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-[12px] text-ink-500">当前工作草稿{schema.draft?.updatedAt ? ` · 最近保存 ${formatTime(schema.draft.updatedAt)}` : ""}</div>
            <button type="button" onClick={save} disabled={schema.saving || validation.length > 0} className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-[13px] text-ink-700 hover:bg-paper-100 disabled:opacity-50">
              {schema.saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              保存草稿
            </button>
            <button type="button" onClick={() => freezeSchema(task.taskId)} disabled={!canFreeze || schema.freezing} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-3 py-2 text-[13px] text-white disabled:opacity-50">
              {schema.freezing ? <Loader2 size={15} className="animate-spin" /> : <Lock size={15} />}
              冻结为 schema_vN
            </button>
          </div>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Metric label="记录粒度" value={draft.recordSchema?.recordUnit || "material_level"} />
          <Metric label="记录身份" value={(draft.recordSchema?.recordIdentityFields || ["paper_id", "material_name"]).join(" + ")} />
          <Metric label="输出格式" value="嵌套 JSON" />
        </div>
      </section>

      <SchemaSourcePanel
        definitionText={definitionText}
        setDefinitionText={setDefinitionText}
        applyMode={applyMode}
        setApplyMode={setApplyMode}
        previewTree={previewTree}
        assisting={compilationActive}
        assistUnavailable={(compilation?.warnings || []).some((warning) => warning.code === "llm_unavailable")}
        canSync={compilation?.status === "valid" || compilation?.status === "valid_with_warnings"}
        syncMessage={syncMessage}
        progressState={workbench}
        onParse={parseDefinition}
        onSync={syncPreviewToTree}
        onDiscardPreview={() => {
          updateWorkbench(task.taskId, { previewTree: null, syncMessage: "", dismissedCompilationId: compilation?.compilationId || null });
        }}
        onResetTree={() => {
          setTree([], null);
          updateWorkbench(task.taskId, { previewTree: null, syncMessage: "" });
        }}
      />

      {compilation && !compilationActive && (
        <CompilationReport
          compilation={compilation}
          resolving={schema.assisting}
          onResolve={(resolutions) => resolveCompilation(task.taskId, compilation.compilationId, resolutions)}
        />
      )}

      <div ref={treeWorkbenchRef} className="grid min-h-[620px] gap-4 scroll-mt-4 2xl:grid-cols-[minmax(360px,0.95fr)_minmax(420px,1.05fr)]">
        <SchemaTreeOutline
          tree={draft.fieldTree || []}
          selectedPath={selectedPath}
          expanded={expanded}
          onSelect={setSelectedPath}
          onToggle={(path) => setExpanded((prev) => ({ ...prev, [path.join(".")]: !prev[path.join(".")] }))}
          onAddTopLevel={addTopLevel}
          onAddChild={addChild}
          onAddSibling={addSibling}
          onDuplicate={duplicate}
          onDelete={remove}
          onMove={move}
        />

        <section className="min-w-0 overflow-hidden rounded-lg border border-line bg-paper-0">
          <div className="grid h-full min-h-0 lg:grid-cols-[minmax(0,1fr)_320px]">
            <SchemaNodeEditor node={selectedNode} onUpdate={updateSelected} />
            <aside className="min-h-0 border-t border-line bg-paper-50 lg:border-l lg:border-t-0">
              <SchemaStructureSummary stats={stats} />
              <SchemaJsonPreview
                tree={draft.fieldTree || []}
                selectedNode={selectedNode}
                previewOpen={previewOpen}
                setPreviewOpen={setPreviewOpen}
                previewMode={previewMode}
                setPreviewMode={setPreviewMode}
              />
            </aside>
          </div>
        </section>
      </div>

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <h2 className="mb-3 text-[14px] font-medium text-ink-900">已冻结字段方案</h2>
        <div className="space-y-2">
          {schema.versions.map((version) => (
            <div key={version.schemaVersion} className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
              <div>
                <div className="font-mono text-[12px] text-ink-800">{version.schemaVersion}</div>
                <div className="text-[11.5px] text-ink-500">{version.schemaMode || "flat_fields"} · {version.fieldCount} 个顶层字段 · {version.baseCollectionVersion}</div>
              </div>
              <button type="button" onClick={() => duplicateToDraft(task.taskId, version.schemaVersion)} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">
                <Copy size={13} />
                复制到草稿
              </button>
            </div>
          ))}
          {schema.versions.length === 0 && <div className="rounded-md border border-dashed border-line bg-paper-50 px-3 py-6 text-center text-[13px] text-ink-500">暂无字段方案版本</div>}
        </div>
      </section>
    </div>
  );
}

function CompilationReport({ compilation, resolving, onResolve }) {
  const unresolvedIds = compilation.coverage?.unresolvedRequirementIds || [];
  const requirements = new Map((compilation.requirements || []).map((item) => [item.requirementId, item]));
  const statusTone = compilation.status === "valid" ? "text-emerald-700" : compilation.status === "needs_review" ? "text-amber" : "text-ink-700";
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[14px] font-medium text-ink-900">Schema 编译报告</h2>
          <div className={`mt-1 font-mono text-[12px] ${statusTone}`}>{compilation.status} · {compilation.sourceFormat} · compiler {compilation.compilerVersion}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Metric label="要求覆盖" value={`${compilation.coverage?.resolved || 0}/${compilation.coverage?.total || 0}`} />
          <Metric label="未决要求" value={compilation.coverage?.unresolved || 0} />
          <Metric label="自动修正" value={(compilation.normalizationChanges || []).length} />
        </div>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
        <ReportBlock
          title="记录模型"
          items={[
            `类型：${compilation.recordSchema?.recordType || "record"}`,
            `粒度：${compilation.recordSchema?.recordUnit || "paper_level"}`,
            `主体：${compilation.recordSchema?.primaryEntity || "paper"}`,
            `身份：${(compilation.recordSchema?.recordIdentityFields || ["paper_id"]).join(", ")}`,
          ]}
          empty="未生成记录模型"
        />
        <ReportBlock title="系统 paper_metadata" items={(compilation.paperMetadataFields || []).map((item) => `paper_metadata.${item}`)} empty="未映射系统字段" />
        <ReportBlock title="全局抽取规则" items={(compilation.globalInstructions || []).map((item) => item.text)} empty="未识别全局规则" />
        <ReportBlock
          title="自动规范化记录"
          items={(compilation.normalizationChanges || []).map((item) => `${item.path || "schema"}: ${item.action}${item.before !== undefined || item.after !== undefined ? ` (${String(item.before ?? "")} → ${String(item.after ?? "")})` : ""}`)}
          empty="未执行自动规范化"
        />
        <ReportBlock title="验证与警告" items={[...(compilation.validationErrors || []).map((item) => `${item.path || "schema"}: ${item.message || item.code}`), ...(compilation.warnings || []).map((item) => item.message || item.code)]} empty="没有验证问题" />
      </div>
      {unresolvedIds.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <div className="mb-2 text-[12px] font-medium text-ink-800">待处理要求</div>
          <div className="space-y-2">
            {unresolvedIds.map((id) => (
              <ResolutionRow
                key={id}
                requirement={requirements.get(id) || { requirementId: id, sourceText: id }}
                metadataKeys={compilation.systemMetadataKeys || []}
                identityKeys={compilation.recordSchema?.recordIdentityFields || ["paper_id"]}
                disabled={resolving}
                onResolve={onResolve}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function ReportBlock({ title, items, empty }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 p-3">
      <div className="text-[11px] font-medium text-ink-500">{title}</div>
      <div className="mt-2 space-y-1 text-[12px] text-ink-700">
        {items.length ? items.slice(0, 12).map((item, index) => <div key={`${item}-${index}`} className="break-words">{item}</div>) : <div className="text-ink-400">{empty}</div>}
      </div>
    </div>
  );
}

function ResolutionRow({ requirement, metadataKeys, identityKeys, disabled, onResolve }) {
  const defaults = schemaResolutionDefaults(requirement);
  const [disposition, setDisposition] = useState(defaults.disposition);
  const [targetPath, setTargetPath] = useState(defaults.targetPath);
  const [reason, setReason] = useState("");
  const targetRequired = ["user_schema", "system_metadata", "record_identity", "constraint"].includes(disposition);
  const changeDisposition = (next) => {
    setDisposition(next);
    if (next === "system_metadata") setTargetPath(metadataKeys[0] ? `paper_metadata.${metadataKeys[0]}` : "");
    else if (next === "record_identity") setTargetPath(defaults.disposition === "record_identity" ? defaults.targetPath : "");
    else if (next === "user_schema") setTargetPath(defaults.disposition === "user_schema" ? defaults.targetPath : "");
    else if (next === "global_instruction" || next === "ignored_with_reason") setTargetPath("");
  };
  const submit = () => {
    const key = toSchemaKey(targetPath.replace(/^data\./, "").split(".").pop());
    const name = requirement.rawName || key;
    const resolution = { requirementId: requirement.requirementId, disposition, targetPath, reason };
    if (disposition === "user_schema") resolution.node = { key, label: name, type: requirement.shapeHint || "string", children: [] };
    onResolve([resolution]);
  };
  return (
    <div className="grid gap-2 rounded-md border border-amber/30 bg-amber/10 p-3 lg:grid-cols-[minmax(220px,1fr)_170px_minmax(180px,0.7fr)_minmax(180px,0.7fr)_auto]">
      <div className="min-w-0">
        <div className="font-mono text-[11px] text-ink-400">{requirement.requirementId}</div>
        <div className="mt-1 text-[12.5px] text-ink-800">{requirement.sourceText}</div>
      </div>
      <select value={disposition} onChange={(event) => changeDisposition(event.target.value)} className={INPUT_CLASS}>
        <option value="user_schema">创建用户字段</option>
        <option value="system_metadata">映射 paper_metadata</option>
        <option value="record_identity">映射记录身份</option>
        <option value="global_instruction">作为全局规则</option>
        <option value="constraint">作为字段约束</option>
        <option value="ignored_with_reason">忽略并说明</option>
      </select>
      {disposition === "system_metadata" ? (
        <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)} className={INPUT_CLASS}>
          <option value="">选择系统字段</option>
          {metadataKeys.map((key) => <option key={key} value={`paper_metadata.${key}`}>{`paper_metadata.${key}`}</option>)}
        </select>
      ) : disposition === "record_identity" ? (
        <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)} className={INPUT_CLASS}>
          <option value="">选择或创建身份字段</option>
          {identityKeys.map((key) => <option key={key} value={`record_identity.${toSchemaKey(key)}`}>{`record_identity.${toSchemaKey(key)}`}</option>)}
          {defaults.targetPath && !identityKeys.some((key) => `record_identity.${toSchemaKey(key)}` === defaults.targetPath) && <option value={defaults.targetPath}>{defaults.targetPath}</option>}
        </select>
      ) : (
        <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} className={INPUT_CLASS} placeholder="目标路径（可选）" />
      )}
      <input value={reason} onChange={(event) => setReason(event.target.value)} className={INPUT_CLASS} placeholder={disposition === "ignored_with_reason" ? "忽略理由（必填）" : "处理说明"} />
      <button type="button" onClick={submit} disabled={disabled || (targetRequired && !targetPath) || (disposition === "ignored_with_reason" && !reason.trim())} className="rounded-md bg-ink-900 px-3 py-2 text-[12px] text-white disabled:opacity-40">确认</button>
    </div>
  );
}

function SchemaSourcePanel({ definitionText, setDefinitionText, applyMode, setApplyMode, previewTree, assisting, assistUnavailable, canSync, syncMessage, progressState, onParse, onSync, onDiscardPreview, onResetTree }) {
  const previewStats = previewTree ? treeStats(previewTree) : null;
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[14px] font-medium text-ink-900">字段定义来源</h2>
          <div className="mt-1 text-[12px] text-ink-500">粘贴 Markdown、JSON 或自然语言字段定义，系统先生成预览结构，确认后再应用。</div>
        </div>
      </div>
      <textarea value={definitionText} onChange={(event) => setDefinitionText(event.target.value)} rows={5} className="w-full resize-y rounded-md border border-line bg-paper-50 px-3 py-2 text-[13px] outline-none focus:border-amber" placeholder="粘贴你自己的字段定义，例如分类、组成、制备、性能、应用等层级说明。" />
      {(assisting || progressState.executionStatus === "failed") && <SchemaCompilationProgress state={progressState} />}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select value={applyMode} onChange={(event) => setApplyMode(event.target.value)} className="rounded-md border border-line bg-paper-50 px-2.5 py-1.5 text-[12px] outline-none focus:border-amber">
          <option value="replace">应用时替换当前结构</option>
          <option value="merge">应用时合并到当前结构</option>
        </select>
        <button type="button" onClick={onParse} disabled={assisting || !definitionText.trim()} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-2.5 py-1.5 text-[12px] text-white disabled:opacity-50">
          {assisting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {assisting ? "解析进行中" : progressState.executionStatus === "failed" ? "重新解析" : "解析为字段结构"}
        </button>
        {previewTree && <button type="button" onClick={onSync} disabled={!canSync} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 disabled:opacity-40">应用到字段树</button>}
        {previewTree && <button type="button" onClick={onDiscardPreview} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">放弃解析结果</button>}
        <button type="button" onClick={onResetTree} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">重置为空结构</button>
        {assistUnavailable && <span className="text-[12px] text-red-600">模型不可用，可继续手动编辑字段树。</span>}
      </div>
      {syncMessage && <div className="mt-2 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">{syncMessage}</div>}
      {previewTree && (
        <div className="mt-3 rounded-md border border-line bg-paper-50 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[12px] font-medium text-ink-800">用户字段树 · 待同步字段结构</div>
            <div className="flex flex-wrap gap-1.5 text-[11px] text-ink-500">
              <span className="rounded border border-line bg-paper-0 px-1.5 py-0.5">顶层 {previewStats.topLevelCount}</span>
              <span className="rounded border border-line bg-paper-0 px-1.5 py-0.5">节点 {previewStats.totalNodeCount}</span>
              <span className="rounded border border-line bg-paper-0 px-1.5 py-0.5">深度 {previewStats.maxDepth}</span>
            </div>
          </div>
          <pre className="max-h-[180px] overflow-auto text-[11.5px] leading-5 text-ink-700">{JSON.stringify(previewTree, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}

function SchemaCompilationProgress({ state }) {
  const [clock, setClock] = useState(Date.now());
  const active = ["queued", "running"].includes(state.executionStatus) || state.phase === "submitting";
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const progress = Math.max(0, Math.min(100, Number(state.progress || 0)));
  const startedAtMs = state.startedAt ? (state.startedAt > 1e12 ? state.startedAt : state.startedAt * 1000) : clock;
  const elapsedSeconds = Math.max(0, Math.floor((clock - startedAtMs) / 1000));
  const connectionText = state.streamState === "reconnecting"
    ? "正在重新连接"
    : state.streamState === "polling"
      ? "已切换为状态查询"
      : state.executionStatus === "queued"
        ? "已进入任务队列"
        : "任务持续运行中";
  return (
    <div className={`mt-3 min-h-[92px] rounded-md border px-3 py-3 ${state.executionStatus === "failed" ? "border-red-200 bg-red-50" : "border-line bg-paper-50"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
        <div className="font-medium text-ink-800">{state.executionStatus === "failed" ? "字段解析失败" : (SCHEMA_PHASE_LABELS[state.phase] || "正在准备字段解析")}</div>
        <div className="text-ink-500">{state.executionStatus === "failed" ? "可重新提交" : `${progress}%`}</div>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-sm bg-paper-200" role="progressbar" aria-label="字段解析进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
        <div
          className={`h-full bg-amber transition-[width] duration-300 ${state.indeterminate && active ? "animate-pulse" : ""}`}
          style={{ width: `${Math.max(progress, active ? 4 : 0)}%` }}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-ink-500">
        <span>{state.executionStatus === "failed" ? (state.error || "解析任务未能完成") : connectionText}</span>
        {active && <span>已用时间 {formatDuration(elapsedSeconds)}</span>}
      </div>
    </div>
  );
}

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}分${String(seconds).padStart(2, "0")}秒` : `${seconds}秒`;
}

function SchemaTreeOutline({ tree, selectedPath, expanded, onSelect, onToggle, onAddTopLevel, onAddChild, onAddSibling, onDuplicate, onDelete, onMove }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-line bg-paper-0">
      <div className="flex flex-col items-stretch sm:flex-row sm:items-center gap-3 border-b border-line px-4 py-3 sm:justify-between">
        <div>
          <h2 className="text-[14px] font-medium text-ink-900">字段树</h2>
          <div className="mt-1 text-[12px] text-ink-500">这里只管理 data 内部结构；左侧滚动，不撑高页面。</div>
        </div>
        <button type="button" onClick={onAddTopLevel} className="inline-flex shrink-0 self-start items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100 sm:self-auto">
          <Plus size={13} />
          新增顶层分组
        </button>
      </div>
      <div className="max-h-[560px] min-h-[420px] overflow-auto p-3">
        {tree.length === 0 ? (
          <div className="rounded-md border border-dashed border-line bg-paper-50 px-4 py-8 text-center">
            <div className="text-[13px] font-medium text-ink-800">尚未定义 data 字段结构</div>
            <div className="mt-1 text-[12px] text-ink-500">请粘贴字段定义并解析，或手动新增顶层分组。系统不会自动填充研究字段。</div>
          </div>
        ) : (
          <div className="space-y-1.5">
            {tree.map((node, index) => (
              <SchemaTreeRow
                key={`${node.key}-${index}`}
                node={node}
                path={[index]}
                selectedPath={selectedPath}
                expanded={expanded}
                onSelect={onSelect}
                onToggle={onToggle}
                onAddChild={onAddChild}
                onAddSibling={onAddSibling}
                onDuplicate={onDuplicate}
                onDelete={onDelete}
                onMove={onMove}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function SchemaTreeRow({ node, path, selectedPath, expanded, onSelect, onToggle, onAddChild, onAddSibling, onDuplicate, onDelete, onMove }) {
  const pathKey = path.join(".");
  const isSelected = selectedPath?.join(".") === pathKey;
  const canHaveChildren = parentSupportsChildren(node.type);
  const isOpen = expanded[pathKey] ?? path.length === 1;
  const childCount = node.children?.length || 0;
  return (
    <div className="min-w-0">
      <div className={`flex min-w-0 flex-wrap sm:flex-nowrap items-center gap-1.5 rounded-md border px-2 py-1.5 ${isSelected ? "border-amber bg-amber/10" : "border-line bg-paper-50 hover:bg-paper-100"}`}>
        <button type="button" onClick={() => (canHaveChildren ? onToggle(path) : undefined)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-ink-500 hover:bg-paper-0">
          {canHaveChildren ? (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <span className="h-[14px] w-[14px]" />}
        </button>
        <button type="button" onClick={() => onSelect(path)} className="min-w-0 flex-1 text-left">
          <div className="truncate text-[12.5px] font-medium text-ink-800">{node.label || node.key || "未命名字段"}</div>
          <div className="truncate font-mono text-[11px] text-ink-400">{node.key || "(empty)"}</div>
        </button>
        <span className="max-w-[88px] shrink-0 truncate rounded border border-line bg-paper-0 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-500">{node.type}</span>
        {childCount > 0 && <span className="hidden shrink-0 text-[11px] text-ink-400 sm:inline">{childCount} 子字段</span>}
        <div className="flex basis-full justify-end sm:basis-auto gap-1 sm:shrink-0 sm:items-center">
          <IconButton label="上移" onClick={() => onMove(path, -1)} icon={<ArrowUp size={12} />} />
          <IconButton label="下移" onClick={() => onMove(path, 1)} icon={<ArrowDown size={12} />} />
          {canHaveChildren && <IconButton label="添加子字段" onClick={() => onAddChild(path)} icon={<Plus size={12} />} />}
          <IconButton label="添加同级" onClick={() => onAddSibling(path)} icon={<Plus size={12} />} />
          <IconButton label="复制" onClick={() => onDuplicate(path)} icon={<Copy size={12} />} />
          <IconButton label="删除此节点" danger onClick={() => onDelete(path)} icon={<Trash2 size={12} />} />
        </div>
      </div>
      {canHaveChildren && isOpen && childCount > 0 && (
        <div className="ml-0 mt-1.5 space-y-1.5 border-l-0 pl-0 sm:ml-5 sm:border-l sm:pl-2 sm:border-line">
          {node.children.map((child, index) => (
            <SchemaTreeRow key={`${child.key}-${index}`} node={child} path={[...path, index]} selectedPath={selectedPath} expanded={expanded} onSelect={onSelect} onToggle={onToggle} onAddChild={onAddChild} onAddSibling={onAddSibling} onDuplicate={onDuplicate} onDelete={onDelete} onMove={onMove} />
          ))}
        </div>
      )}
    </div>
  );
}

function SchemaNodeEditor({ node, onUpdate }) {
  if (!node) {
    return (
      <div className="flex min-h-[420px] items-center justify-center p-6 text-center">
        <div>
          <h2 className="text-[14px] font-medium text-ink-900">字段属性</h2>
          <div className="mt-2 text-[13px] text-ink-500">从左侧字段树选择一个节点后，在这里编辑单个字段。</div>
        </div>
      </div>
    );
  }
  const showAllowedValues = ["enum", "multi_enum"].includes(node.type);
  return (
    <div className="min-h-0 overflow-auto p-4">
      <h2 className="text-[14px] font-medium text-ink-900">字段属性</h2>
      <div className="mt-3 grid gap-3">
        <label className="grid gap-1.5 text-[12px] text-ink-500">
          字段键
          <input value={node.key || ""} onChange={(event) => onUpdate({ key: event.target.value })} className={INPUT_CLASS} placeholder="lower_snake_case" />
        </label>
        <label className="grid gap-1.5 text-[12px] text-ink-500">
          显示名称
          <input value={node.label || ""} onChange={(event) => onUpdate({ label: event.target.value })} className={INPUT_CLASS} placeholder="字段名称" />
        </label>
        <label className="grid gap-1.5 text-[12px] text-ink-500">
          类型
          <select value={node.type || "string"} onChange={(event) => onUpdate({ type: event.target.value })} className={INPUT_CLASS}>
            {TREE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        {node.type === "number" && <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">仅适合纯数字；带单位、范围或原文表述建议使用 string。</div>}
        <label className="grid gap-1.5 text-[12px] text-ink-500">
          字段描述
          <textarea value={node.description || ""} onChange={(event) => onUpdate({ description: event.target.value })} rows={3} className={`${INPUT_CLASS} resize-y`} placeholder="说明这个字段应该表达什么。" />
        </label>
        <label className="grid gap-1.5 text-[12px] text-ink-500">
          抽取指令
          <textarea value={node.extractionInstruction || ""} onChange={(event) => onUpdate({ extractionInstruction: event.target.value })} rows={3} className={`${INPUT_CLASS} resize-y`} placeholder="说明模型如何识别这个字段，保持用户定义的原生 JSON 值。" />
        </label>
        {showAllowedValues && (
          <label className="grid gap-1.5 text-[12px] text-ink-500">
            枚举值
            <textarea value={(node.allowedValues || []).join(", ")} onChange={(event) => onUpdate({ allowedValues: splitList(event.target.value) })} rows={3} className={`${INPUT_CLASS} resize-y`} placeholder="用逗号分隔候选值" />
          </label>
        )}
        <div className="flex flex-wrap gap-3">
          <label className="inline-flex items-center gap-2 text-[12px] text-ink-700"><input type="checkbox" checked={!!node.required} onChange={(event) => onUpdate({ required: event.target.checked })} /> 必填</label>
          <label className="inline-flex items-center gap-2 text-[12px] text-ink-700"><input type="checkbox" checked={node.evidenceRequired !== false} onChange={(event) => onUpdate({ evidenceRequired: event.target.checked })} /> 需要证据</label>
        </div>
      </div>
    </div>
  );
}

function SchemaStructureSummary({ stats }) {
  const items = [
    ["顶层字段数", stats.topLevelCount],
    ["总节点数", stats.totalNodeCount],
    ["叶子字段数", stats.leafCount],
    ["object 数", stats.objectCount],
    ["list_object 数", stats.listObjectCount],
    ["dict 数", stats.dictCount],
    ["enum 数", stats.enumCount],
    ["最大嵌套深度", stats.maxDepth],
  ];
  return (
    <div className="border-b border-line p-4">
      <h2 className="text-[14px] font-medium text-ink-900">结构摘要</h2>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-md border border-line bg-paper-0 px-2.5 py-2">
            <div className="text-[10.5px] text-ink-400">{label}</div>
            <div className="mt-1 text-[15px] font-semibold text-ink-800">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SchemaJsonPreview({ tree, selectedNode, previewOpen, setPreviewOpen, previewMode, setPreviewMode }) {
  const value = previewMode === "selected" && selectedNode ? sampleNode(selectedNode) : sampleRecord(tree);
  return (
    <div className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[14px] font-medium text-ink-900">JSON 预览</h2>
        <button type="button" onClick={() => setPreviewOpen(!previewOpen)} className="rounded-md border border-line px-2 py-1 text-[12px] text-ink-700 hover:bg-paper-100">{previewOpen ? "收起" : "展开"}</button>
      </div>
      <div className="mt-2 flex gap-1">
        <button type="button" onClick={() => setPreviewMode("summary")} className={`rounded px-2 py-1 text-[11px] ${previewMode === "summary" ? "bg-ink-900 text-white" : "border border-line text-ink-600"}`}>完整记录预览</button>
        <button type="button" onClick={() => setPreviewMode("selected")} className={`rounded px-2 py-1 text-[11px] ${previewMode === "selected" ? "bg-ink-900 text-white" : "border border-line text-ink-600"}`}>选中节点预览</button>
      </div>
      {previewOpen ? (
        <div className="mt-3 overflow-hidden rounded-md border border-line bg-paper-0">
          <div className="flex justify-end border-b border-line px-2 py-1.5">
            <button type="button" onClick={() => navigator.clipboard?.writeText(JSON.stringify(value, null, 2))} className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] text-ink-600 hover:bg-paper-100">
              <Copy size={12} />
              复制
            </button>
          </div>
          <pre className="max-h-[300px] overflow-auto p-3 text-[11.5px] leading-5 text-ink-700">{JSON.stringify(value, null, 2)}</pre>
        </div>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-line bg-paper-0 px-3 py-4 text-[12px] text-ink-500">默认收起，避免长 JSON 占用编辑空间。</div>
      )}
    </div>
  );
}

function IconButton({ label, onClick, icon, danger = false }) {
  return (
    <button type="button" title={label} onClick={onClick} className={`inline-flex h-7 w-7 items-center justify-center rounded-md border hover:bg-paper-0 ${danger ? "border-red-200 text-red-600" : "border-line text-ink-700"}`}>
      {icon}
    </button>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 px-3 py-2">
      <div className="text-[11px] text-ink-400">{label}</div>
      <div className="mt-1 text-[13px] font-medium text-ink-800">{value}</div>
    </div>
  );
}

function normalizeDraft(raw, task) {
  const tree = normalizeTree(raw.fieldTree?.length ? raw.fieldTree : treeFromFlatFields(raw.fields || []));
  return {
    ...defaultDraft(task),
    ...raw,
    schemaMode: raw.schemaMode || "nested_material",
    recordSchema: raw.recordSchema || MATERIAL_RECORD_SCHEMA,
    fieldTree: tree,
    fieldGroups: groupsFromTree(tree),
    fields: fieldsFromTree(tree),
  };
}

function withTree(draft, tree) {
  const normalized = normalizeTree(tree);
  return {
    ...draft,
    schemaMode: draft.schemaMode || "nested_material",
    recordSchema: draft.recordSchema || MATERIAL_RECORD_SCHEMA,
    fieldTree: normalized,
    fieldGroups: groupsFromTree(normalized),
    fields: fieldsFromTree(normalized),
  };
}

function validateDraft(draft) {
  const errors = [];
  const keyRe = /^[a-z][a-z0-9_]*$/;
  const identityKeys = new Set(draft.recordSchema?.recordIdentityFields || ["paper_id"]);
  const visit = (nodes, path = "") => {
    const seen = new Set();
    for (const node of nodes || []) {
      const full = path ? `${path}.${node.key}` : node.key;
      if (!keyRe.test(node.key || "")) errors.push(`字段键不合法: ${full || "(空)"}`);
      if (/^req_\d+$/i.test(node.key || "")) errors.push(`内部 requirement ID 不能作为字段: ${full}`);
      if (identityKeys.has(node.key)) errors.push(`身份字段不能出现在 data 字段树: ${full}`);
      if (seen.has(node.key)) errors.push(`同级字段重复: ${full}`);
      seen.add(node.key);
      if (!TREE_TYPES.includes(node.type)) errors.push(`字段类型不合法: ${full}`);
      if (parentSupportsChildren(node.type) && !(node.children || []).length) errors.push(`对象字段需要子字段: ${full}`);
      visit(node.children || [], full);
    }
  };
  visit(draft.fieldTree || []);
  return errors;
}

function splitList(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function siblingNodesAtPath(tree, path) {
  if (!path?.length || path.length === 1) return tree || [];
  const parent = getAtPath(tree || [], path.slice(0, -1));
  return parent?.children || [];
}

function nextSelectionAfterDelete(tree, deletedPath) {
  if (!tree?.length || !deletedPath?.length) return null;
  const siblings = siblingNodesAtPath(tree, deletedPath);
  if (!siblings.length) return deletedPath.length === 1 ? [0] : deletedPath.slice(0, -1);
  const nextIndex = Math.min(deletedPath[deletedPath.length - 1], siblings.length - 1);
  return [...deletedPath.slice(0, -1), nextIndex];
}

function labelForGeneratedKey(baseLabel, key) {
  const match = String(key || "").match(/_(\d+)$/);
  return match ? `${baseLabel} ${match[1]}` : baseLabel;
}

function formatTime(seconds) {
  if (!seconds) return "";
  try {
    return new Date(seconds * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}
