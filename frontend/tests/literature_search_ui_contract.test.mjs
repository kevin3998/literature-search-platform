import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
  citationAriaLabel,
  citationOrdinalLabel,
  evidenceIdLabel,
} from "../src/components/citationLabels.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const componentPath = (name) => resolve(__dirname, "../src/components", name);

test("main sidebar exposes structured extraction as a primary product entry", async () => {
  const source = await readFile(componentPath("Sidebar.jsx"), "utf8");

  assert.match(source, /数据抽取/);
  assert.match(source, /结构化材料数据/);
  assert.match(source, /openStructuredExtraction/);
});

test("main sidebar collapses to an icon rail on narrow screens", async () => {
  const source = await readFile(componentPath("Sidebar.jsx"), "utf8");

  assert.match(source, /w-\[68px\]\s+md:w-\[256px\]/);
  assert.match(source, /hidden\s+md:block/);
});

test("nested schema editor keeps field nodes compact inside the editor column", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");

  assert.doesNotMatch(source, /md:grid-cols-\[28px_1fr_1fr_150px_auto\]/);
  assert.match(source, /2xl:grid-cols/);
  assert.match(source, /min-w-0/);
  assert.match(source, /min-h-\[34px\]/);
});

test("nested schema editor keeps every field action reachable on narrow screens", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");

  assert.match(source, /flex-wrap\s+sm:flex-nowrap/);
  assert.match(source, /basis-full\s+justify-end\s+sm:basis-auto/);
  assert.match(source, /border-l-0\s+pl-0\s+sm:ml-5\s+sm:border-l\s+sm:pl-2/);
  assert.match(source, /flex-col\s+items-stretch\s+sm:flex-row\s+sm:items-center/);
});

test("nested schema editor starts with empty user-defined data fields", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");

  assert.match(source, /fieldTree:\s*\[\]/);
  assert.match(source, /fieldGroups:\s*\[\]/);
  assert.match(source, /fields:\s*\[\]/);
  assert.match(source, /尚未定义 data 字段结构/);
  assert.doesNotMatch(source, /模板/);
  assert.doesNotMatch(source, /materialTemplateTree/);
  assert.doesNotMatch(source, /newNode\("material_name"/);
});

test("nested schema editor is a two-pane workbench without unit or example fields", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");

  assert.match(source, /字段树/);
  assert.match(source, /字段属性/);
  assert.match(source, /结构摘要/);
  assert.match(source, /JSON 预览/);
  assert.match(source, /仅适合纯数字/);
  assert.match(source, /selectedPath/);
  assert.match(source, /SchemaTreeOutline/);
  assert.match(source, /SchemaNodeEditor/);
  assert.doesNotMatch(source, /placeholder="单位"/);
  assert.doesNotMatch(source, /placeholder="示例值"/);
  assert.doesNotMatch(source, /node\.unit/);
  assert.doesNotMatch(source, /exampleValues/);
  assert.doesNotMatch(source, /function TreeNode/);
});

test("schema compiler workbench applies reviewed results into the manual field tree", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");

  assert.match(source, /待同步字段结构/);
  assert.match(source, /应用到字段树/);
  assert.match(source, /放弃解析结果/);
  assert.match(source, /Schema 编译报告/);
  assert.match(source, /系统 paper_metadata/);
  assert.match(source, /记录模型/);
  assert.match(source, /全局抽取规则/);
  assert.match(source, /自动规范化记录/);
  assert.match(source, /用户字段树/);
  assert.match(source, /待处理要求/);
  assert.match(source, /needs_review/);
  assert.match(source, /window\.confirm/);
  assert.match(source, /编译结果包含警告/);
  assert.match(source, /treeWorkbenchRef/);
  assert.match(source, /scrollIntoView/);
  assert.doesNotMatch(source, /应用预览结构/);
  assert.doesNotMatch(source, /解析结果预览/);
});

test("schema compiler keeps per-task workbench state and shows durable phase progress", async () => {
  const component = await readFile(resolve(__dirname, "../src/components/structured-extraction/SchemaDesigner.jsx"), "utf8");
  const store = await readFile(resolve(__dirname, "../src/store/useAppStore.js"), "utf8");

  assert.match(store, /schemaWorkbenchByTask/);
  assert.match(store, /readSchemaWorkbenchSession/);
  assert.match(store, /resumeExtractionSchemaCompilation/);
  assert.match(store, /streamSchemaCompilation/);
  assert.match(store, /pollExtractionSchemaCompilation/);
  assert.match(component, /SchemaCompilationProgress/);
  assert.match(component, /解析进行中/);
  assert.match(component, /已用时间/);
  assert.match(component, /正在调用模型进行语义编译/);
  assert.match(component, /正在定向修复编译结果/);
  assert.doesNotMatch(component, /const \[definitionText, setDefinitionText\] = useState/);
  assert.doesNotMatch(component, /const \[previewTree, setPreviewTree\] = useState/);
});

test("review workbench uses queue based master detail instead of a wide review table", async () => {
  const source = await readFile(resolve(__dirname, "../src/components/structured-extraction/ReviewTable.jsx"), "utf8");

  assert.match(source, /结果审阅控制中心/);
  assert.match(source, /审阅队列/);
  assert.match(source, /全部材料/);
  assert.match(source, /多模态待确认/);
  assert.match(source, /疑似遗漏/);
  assert.match(source, /有效 JSON/);
  assert.match(source, /启动多模态复核/);
  assert.match(source, /批量接受多模态补充/);
  assert.doesNotMatch(source, /<table/);
  assert.doesNotMatch(source, /结果审阅表/);
});

test("settings page keeps multimodal model configuration in the model category", async () => {
  const source = await readFile(componentPath("SettingsModal.jsx"), "utf8");

  assert.match(source, /多模态模型/);
  assert.match(source, /multimodal_enabled/);
  assert.match(source, /multimodal_profile_id/);
  assert.match(source, /multimodal_scan_default/);
  assert.match(source, /检查相关页面与图表/);
});

test("literature search chat workbench stacks instead of forcing a desktop row on narrow screens", async () => {
  const source = await readFile(componentPath("LiteratureSearchWorkbench.jsx"), "utf8");

  assert.match(source, /flex-col\s+lg:flex-row/);
});

test("literature results panel is full width on narrow screens and only fixed width on desktop", async () => {
  const source = await readFile(componentPath("ResultsPanel.jsx"), "utf8");

  assert.match(source, /w-full/);
  assert.match(source, /lg:w-\[380px\]/);
  assert.doesNotMatch(source, /className="w-\[380px\]/);
});

test("literature chat textarea keeps a usable width inside the mobile input row", async () => {
  const source = await readFile(componentPath("ChatPanel.jsx"), "utf8");

  assert.match(source, /min-w-0[^"]*resize-none|resize-none[^"]*min-w-0/);
});

test("citation labels distinguish UI ordinals from real evidence ids", () => {
  assert.equal(citationOrdinalLabel(1), "证据 1");
  assert.equal(citationOrdinalLabel(null), "证据");
  assert.equal(evidenceIdLabel("E12345"), "证据ID：E12345");
  assert.equal(citationAriaLabel(2), "文献证据 2");
});

test("markdown citation renderer uses numeric citation markers", async () => {
  const source = await readFile(componentPath("MarkdownMessage.jsx"), "utf8");

  assert.match(source, /\\d\+/);
  assert.doesNotMatch(source, /\[A-Za-z\]\+\\d/);
  assert.match(source, /e\.alias/);
  assert.match(source, /citation_alias/);
});
