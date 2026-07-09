import test from "node:test";
import assert from "node:assert/strict";

import { buildPromptContractSections, summarizePromptContract } from "../src/components/structured-extraction/promptContractViewModel.js";

const contract = {
  promptContractVersion: "pc_v1",
  collectionVersion: "col_v1",
  schemaVersion: "schema_v1",
  createdAt: 1720000000,
  recordContract: {
    recordType: "membrane_sample",
    recordUnit: "sample_level",
    primaryEntity: "membrane",
    recordIdentityFields: ["paper_id", "membrane_name"],
  },
  fieldContracts: [
    {
      key: "water_flux",
      label: "水通量",
      type: "number",
      groupKey: "performance",
      required: true,
      evidenceRequired: true,
      unit: "LMH",
    },
  ],
  outputJsonContract: { records: [{ fields: { water_flux: {} } }] },
  extractionRules: ["Do not guess values.", "Return missing when unsupported."],
};

test("summarizePromptContract returns Chinese-facing summary metrics", () => {
  const summary = summarizePromptContract(contract);

  assert.deepEqual(summary, [
    ["契约版本", "pc_v1"],
    ["文献集合", "col_v1"],
    ["字段方案", "schema_v1"],
    ["字段数", 1],
    ["抽取规则", 2],
  ]);
});

test("buildPromptContractSections creates collapsible Chinese sections with copyable text", () => {
  const sections = buildPromptContractSections(contract);

  assert.deepEqual(sections.map((section) => section.title), [
    "抽取规则",
    "记录契约",
    "字段契约",
    "输出 JSON 契约",
    "原始 JSON",
  ]);
  assert.equal(sections[0].kind, "rules");
  assert.equal(sections[2].kind, "fields");
  assert.match(sections[0].copyText, /Do not guess values/);
  assert.match(sections[2].copyText, /water_flux/);
  assert.match(sections[4].copyText, /"promptContractVersion": "pc_v1"/);
});
