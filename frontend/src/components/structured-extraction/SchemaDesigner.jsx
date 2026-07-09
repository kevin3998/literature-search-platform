import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Copy, Loader2, Lock, Plus, Save, Sparkles, Trash2 } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
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
  treeFromFlatFields,
  treeStats,
  uniqueNodeKey,
  updateAtPath,
} from "./schemaTreeUtils";

const INPUT_CLASS = "min-h-[34px] min-w-0 rounded-md border border-line bg-paper-0 px-2 py-1.5 text-[12.5px] outline-none focus:border-amber";

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
  const loadDraft = useAppStore((s) => s.loadExtractionSchemaDraft);
  const saveDraft = useAppStore((s) => s.saveExtractionSchemaDraft);
  const assistSchema = useAppStore((s) => s.assistExtractionSchema);
  const freezeSchema = useAppStore((s) => s.freezeExtractionSchema);
  const loadVersions = useAppStore((s) => s.loadExtractionSchemaVersions);
  const duplicateToDraft = useAppStore((s) => s.duplicateExtractionSchemaToDraft);
  const [draft, setDraft] = useState(defaultDraft(task));
  const [definitionText, setDefinitionText] = useState("");
  const [applyMode, setApplyMode] = useState("replace");
  const [previewTree, setPreviewTree] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [selectedPath, setSelectedPath] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewMode, setPreviewMode] = useState("summary");
  const [syncMessage, setSyncMessage] = useState("");
  const treeWorkbenchRef = useRef(null);

  useEffect(() => {
    if (!task?.taskId || !task.currentCollectionVersion) return;
    loadDraft(task.taskId).catch(() => {});
    loadVersions(task.taskId).catch(() => {});
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
      schemaMode: "nested_material",
      recordSchema: MATERIAL_RECORD_SCHEMA,
      fieldTree,
      fieldGroups: groupsFromTree(fieldTree),
      fields: fieldsFromTree(fieldTree),
    });
  };

  const parseDefinition = async () => {
    setSyncMessage("");
    const result = await assistSchema(task.taskId, {
      action: "parse_field_definition",
      instruction: definitionText,
      draft,
    });
    const tree = result?.result?.fieldTree || result?.result?.field_tree || [];
    const normalized = makeTreeKeysUnique(normalizeTree(tree));
    if (normalized.length) setPreviewTree(normalized);
    else {
      setPreviewTree(null);
      setSyncMessage("未解析出可用字段结构，请调整输入后重试。");
    }
  };

  const syncPreviewToTree = () => {
    if (!previewTree) return;
    if ((draft.fieldTree || []).length > 0) {
      const confirmed = typeof window === "undefined" ? true : window.confirm("当前字段树已有内容，同步会替换或合并当前结构。是否继续？");
      if (!confirmed) return;
    }
    const next = makeTreeKeysUnique(applyMode === "merge" ? mergeTree(draft.fieldTree || [], previewTree) : previewTree);
    setTree(next, next.length ? [0] : null);
    setPreviewTree(null);
    setSyncMessage("已同步，下面可以继续手动调整。");
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
            <h2 className="text-[14px] font-medium text-ink-900">材料记录结构</h2>
            <div className="mt-1 text-[12.5px] leading-5 text-ink-500">
              每种材料一条记录 · 记录身份固定为 paper_id + material_name · data 字段完全由你定义。
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
          <Metric label="抽取目标" value="每种材料一条记录" />
          <Metric label="系统身份字段" value="paper_id + material_name" />
          <Metric label="输出格式" value="嵌套 JSON" />
        </div>
      </section>

      <SchemaSourcePanel
        definitionText={definitionText}
        setDefinitionText={setDefinitionText}
        applyMode={applyMode}
        setApplyMode={setApplyMode}
        previewTree={previewTree}
        assisting={schema.assisting}
        assistUnavailable={schema.assistResult?.available === false}
        syncMessage={syncMessage}
        onParse={parseDefinition}
        onSync={syncPreviewToTree}
        onDiscardPreview={() => {
          setPreviewTree(null);
          setSyncMessage("");
        }}
        onResetTree={() => {
          setTree([], null);
          setPreviewTree(null);
          setSyncMessage("");
        }}
      />

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

function SchemaSourcePanel({ definitionText, setDefinitionText, applyMode, setApplyMode, previewTree, assisting, assistUnavailable, syncMessage, onParse, onSync, onDiscardPreview, onResetTree }) {
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
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select value={applyMode} onChange={(event) => setApplyMode(event.target.value)} className="rounded-md border border-line bg-paper-50 px-2.5 py-1.5 text-[12px] outline-none focus:border-amber">
          <option value="replace">应用时替换当前结构</option>
          <option value="merge">应用时合并到当前结构</option>
        </select>
        <button type="button" onClick={onParse} disabled={assisting || !definitionText.trim()} className="inline-flex items-center gap-1.5 rounded-md bg-ink-900 px-2.5 py-1.5 text-[12px] text-white disabled:opacity-50">
          {assisting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          解析为字段结构
        </button>
        {previewTree && <button type="button" onClick={onSync} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">同步到下方字段树</button>}
        {previewTree && <button type="button" onClick={onDiscardPreview} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">放弃解析结果</button>}
        <button type="button" onClick={onResetTree} className="rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">重置为空结构</button>
        {assistUnavailable && <span className="text-[12px] text-red-600">模型不可用，可继续手动编辑字段树。</span>}
      </div>
      {syncMessage && <div className="mt-2 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">{syncMessage}</div>}
      {previewTree && (
        <div className="mt-3 rounded-md border border-line bg-paper-50 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[12px] font-medium text-ink-800">待同步字段结构</div>
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

function SchemaTreeOutline({ tree, selectedPath, expanded, onSelect, onToggle, onAddTopLevel, onAddChild, onAddSibling, onDuplicate, onDelete, onMove }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-line bg-paper-0">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-[14px] font-medium text-ink-900">字段树</h2>
          <div className="mt-1 text-[12px] text-ink-500">这里只管理 data 内部结构；左侧滚动，不撑高页面。</div>
        </div>
        <button type="button" onClick={onAddTopLevel} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[12px] text-ink-700 hover:bg-paper-100">
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
      <div className={`flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1.5 ${isSelected ? "border-amber bg-amber/10" : "border-line bg-paper-50 hover:bg-paper-100"}`}>
        <button type="button" onClick={() => (canHaveChildren ? onToggle(path) : undefined)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-ink-500 hover:bg-paper-0">
          {canHaveChildren ? (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <span className="h-[14px] w-[14px]" />}
        </button>
        <button type="button" onClick={() => onSelect(path)} className="min-w-0 flex-1 text-left">
          <div className="truncate text-[12.5px] font-medium text-ink-800">{node.label || node.key || "未命名字段"}</div>
          <div className="truncate font-mono text-[11px] text-ink-400">{node.key || "(empty)"}</div>
        </button>
        <span className="shrink-0 rounded border border-line bg-paper-0 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-500">{node.type}</span>
        {childCount > 0 && <span className="shrink-0 text-[11px] text-ink-400">{childCount} 子字段</span>}
        <div className="flex shrink-0 items-center gap-1">
          <IconButton label="上移" onClick={() => onMove(path, -1)} icon={<ArrowUp size={12} />} />
          <IconButton label="下移" onClick={() => onMove(path, 1)} icon={<ArrowDown size={12} />} />
          {canHaveChildren && <IconButton label="添加子字段" onClick={() => onAddChild(path)} icon={<Plus size={12} />} />}
          <IconButton label="添加同级" onClick={() => onAddSibling(path)} icon={<Plus size={12} />} />
          <IconButton label="复制" onClick={() => onDuplicate(path)} icon={<Copy size={12} />} />
          <IconButton label="删除此节点" danger onClick={() => onDelete(path)} icon={<Trash2 size={12} />} />
        </div>
      </div>
      {canHaveChildren && isOpen && childCount > 0 && (
        <div className="ml-5 mt-1.5 space-y-1.5 border-l border-line pl-2">
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
    schemaMode: "nested_material",
    recordSchema: MATERIAL_RECORD_SCHEMA,
    fieldTree: tree,
    fieldGroups: groupsFromTree(tree),
    fields: fieldsFromTree(tree),
  };
}

function withTree(draft, tree) {
  const normalized = normalizeTree(tree);
  return {
    ...draft,
    schemaMode: "nested_material",
    recordSchema: MATERIAL_RECORD_SCHEMA,
    fieldTree: normalized,
    fieldGroups: groupsFromTree(normalized),
    fields: fieldsFromTree(normalized),
  };
}

function validateDraft(draft) {
  const errors = [];
  const keyRe = /^[a-z][a-z0-9_]*$/;
  const visit = (nodes, path = "") => {
    const seen = new Set();
    for (const node of nodes || []) {
      const full = path ? `${path}.${node.key}` : node.key;
      if (!keyRe.test(node.key || "")) errors.push(`字段键不合法: ${full || "(空)"}`);
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
