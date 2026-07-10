import test from "node:test";
import assert from "node:assert/strict";

import {
  fieldsFromTree,
  makeTreeKeysUnique,
  mergeTree,
  newSchemaNode,
  normalizeTree,
  sampleNode,
  sampleRecord,
  schemaResolutionDefaults,
  uniqueNodeKey,
  treeStats,
} from "../src/components/structured-extraction/schemaTreeUtils.js";

test("schema resolution defaults keep internal requirement ids out of user fields", () => {
  assert.deepEqual(
    schemaResolutionDefaults({
      requirementId: "req_0010",
      kind: "recordIdentity",
      rawName: "MaterialName",
      constraints: [{ type: "identityCandidates", values: ["MaterialName", "Details"] }],
    }),
    {
      disposition: "record_identity",
      targetPath: "record_identity.material_name",
      fieldName: "MaterialName",
    },
  );
  assert.deepEqual(
    schemaResolutionDefaults({ requirementId: "req_0011", kind: "selectionRule", rawName: "" }),
    { disposition: "global_instruction", targetPath: "", fieldName: "" },
  );
  assert.deepEqual(
    schemaResolutionDefaults({ requirementId: "req_0012", kind: "field", rawName: "" }),
    { disposition: "user_schema", targetPath: "", fieldName: "" },
  );
});

test("normalizeTree removes system identity fields and UI-only unit/example metadata", () => {
  const tree = normalizeTree([
    { key: "paper_id", label: "Paper", type: "string" },
    { key: "material_name", label: "Material", type: "string" },
    {
      key: "performance",
      label: "性能",
      type: "object",
      unit: "LMH",
      exampleValues: ["120 LMH"],
      example_values: ["100 LMH"],
      children: [
        { key: "water_flux", label: "Water flux", type: "string", unit: "LMH", example_values: ["120 LMH"] },
      ],
    },
  ]);

  assert.deepEqual(tree.map((node) => node.key), ["performance"]);
  assert.equal(tree[0].unit, undefined);
  assert.equal(tree[0].exampleValues, undefined);
  assert.equal(tree[0].children[0].unit, undefined);
  assert.equal(tree[0].children[0].exampleValues, undefined);
});

test("treeStats summarizes nested JSON shape", () => {
  const tree = normalizeTree([
    {
      key: "composition",
      label: "组成",
      type: "object",
      children: [
        {
          key: "base_polymers",
          label: "基体聚合物",
          type: "list_object",
          children: [{ key: "name", label: "名称", type: "string" }],
        },
        { key: "ratios", label: "比例", type: "dict" },
      ],
    },
    { key: "classification", label: "分类", type: "enum", allowedValues: ["A", "B"] },
  ]);

  assert.deepEqual(treeStats(tree), {
    topLevelCount: 2,
    totalNodeCount: 5,
    leafCount: 3,
    objectCount: 1,
    listObjectCount: 1,
    dictCount: 1,
    enumCount: 1,
    maxDepth: 3,
  });
});

test("sampleRecord keeps user-defined leaf values as native JSON", () => {
  const tree = normalizeTree([
    { key: "classification", label: "分类", type: "enum", allowedValues: ["A", "B"] },
    { key: "score", label: "评分", type: "number" },
    { key: "flags", label: "标志", type: "list_string" },
  ]);

  assert.deepEqual(sampleRecord([]), {
    paper_id: "string",
    material_name: "string",
    record_identity: { paper_id: "string", material_name: "string" },
    data: {},
  });
  assert.deepEqual(sampleRecord(tree).data, {
    classification: "string",
    score: 0,
    flags: ["string"],
  });
  assert.equal(sampleRecord(tree).data.classification.raw_value, undefined);
  assert.deepEqual(sampleNode(tree[0]), { classification: "string" });
});

test("fieldsFromTree sends compatibility fields without unit or example values", () => {
  const fields = fieldsFromTree([
    newSchemaNode("performance", "性能", "object", [newSchemaNode("water_flux", "水通量", "string")]),
  ]);

  assert.equal(fields[0].key, "performance");
  assert.equal(fields[0].unit, "");
  assert.deepEqual(fields[0].exampleValues, []);
  assert.deepEqual(fields[0].example_values, undefined);
});

test("uniqueNodeKey creates isolated draft section keys so previews do not overwrite sections", () => {
  const tree = normalizeTree([
    newSchemaNode("new_section", "新分组", "object", [newSchemaNode("field", "字段", "string")]),
    newSchemaNode("new_section_2", "新分组 2", "object", [newSchemaNode("field", "字段", "string")]),
  ]);

  const thirdKey = uniqueNodeKey(tree, "new_section");
  const nextTree = normalizeTree([...tree, newSchemaNode(thirdKey, "新分组 3", "object", [newSchemaNode("field", "字段", "string")])]);

  assert.equal(thirdKey, "new_section_3");
  assert.deepEqual(Object.keys(sampleRecord(nextTree).data), ["new_section", "new_section_2", "new_section_3"]);
});

test("parsed tree synchronization keeps duplicate incoming keys from overwriting JSON preview data", () => {
  const parsedTree = makeTreeKeysUnique([
    newSchemaNode("classification", "分类", "object", [newSchemaNode("membrane_type", "膜类型", "string")]),
    newSchemaNode("classification", "分类", "object", [newSchemaNode("category", "类别", "string")]),
  ]);

  assert.deepEqual(parsedTree.map((node) => node.key), ["classification", "classification_2"]);
  assert.deepEqual(Object.keys(sampleRecord(parsedTree).data), ["classification", "classification_2"]);
});

test("parsed tree merge keeps distinct sections and merges matching sections", () => {
  const existing = [newSchemaNode("classification", "分类", "object", [newSchemaNode("membrane_type", "膜类型", "string")])];
  const incoming = [newSchemaNode("classification", "分类", "object", [newSchemaNode("category", "类别", "string")]), newSchemaNode("performance", "性能", "object", [newSchemaNode("flux", "通量", "string")])];

  const merged = mergeTree(existing, incoming);

  assert.deepEqual(merged.map((node) => node.key), ["classification", "performance"]);
  assert.deepEqual(merged[0].children.map((node) => node.key), ["membrane_type", "category"]);
});
