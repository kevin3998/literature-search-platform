export const TREE_TYPES = [
  "string",
  "number",
  "boolean",
  "enum",
  "multi_enum",
  "date",
  "object",
  "list_object",
  "list_string",
  "dict",
  "evidence_text",
];

export const MATERIAL_RECORD_SCHEMA = {
  recordType: "material_record",
  recordUnit: "material_level",
  primaryEntity: "material",
  onePaperMayHaveMultipleRecords: true,
  recordIdentityFields: ["paper_id", "material_name"],
  deduplicationKeys: ["paper_id", "material_name"],
  parentRecordType: "",
};

const SYSTEM_KEYS = new Set(["paper_id", "material_name"]);

export function newSchemaNode(key = "new_field", label = "新字段", type = "string", children = [], patch = {}) {
  const { unit: _unit, exampleValues: _exampleValues, example_values: _example_values, ...safePatch } = patch || {};
  return {
    key,
    label,
    type: TREE_TYPES.includes(type) ? type : "string",
    description: "",
    extractionInstruction: "",
    required: false,
    evidenceRequired: true,
    allowedValues: [],
    notes: "",
    children: normalizeTree(children),
    ...safePatch,
  };
}

export function uniqueNodeKey(siblings = [], baseKey = "new_field") {
  const cleanBase = String(baseKey || "new_field").trim() || "new_field";
  const existing = new Set((siblings || []).map((node) => node?.key).filter(Boolean));
  if (!existing.has(cleanBase)) return cleanBase;
  let index = 2;
  while (existing.has(`${cleanBase}_${index}`)) index += 1;
  return `${cleanBase}_${index}`;
}

export function makeTreeKeysUnique(nodes = []) {
  const out = [];
  for (const node of nodes || []) {
    const key = uniqueNodeKey(out, node?.key || "field");
    out.push({
      ...node,
      key,
      children: makeTreeKeysUnique(node?.children || []),
    });
  }
  return normalizeTree(out);
}

export function normalizeTree(nodes = []) {
  return (nodes || [])
    .map((node, index) => normalizeNode(node, index + 1))
    .filter((node) => node.key && !SYSTEM_KEYS.has(node.key))
    .map((node, index) => ({ ...node, order: index + 1 }));
}

export function normalizeNode(node = {}, order = 1) {
  const key = String(node.key || "").trim();
  const rawChildren = Array.isArray(node.children) ? node.children : [];
  const children = rawChildren
    .map((child, index) => normalizeNode(child, index + 1))
    .filter((child) => child.key && !SYSTEM_KEYS.has(child.key))
    .map((child, index) => ({ ...child, order: index + 1 }));

  return {
    key,
    label: String(node.label || node.name || key || "").trim(),
    type: TREE_TYPES.includes(node.type) ? node.type : "string",
    description: node.description || "",
    extractionInstruction: node.extractionInstruction || node.extraction_instruction || "",
    required: !!node.required,
    evidenceRequired: node.evidenceRequired ?? node.evidence_required ?? true,
    allowedValues: node.allowedValues || node.allowed_values || [],
    notes: node.notes || "",
    order: Number(node.order || order),
    children,
  };
}

export function fieldsFromTree(tree = []) {
  return (tree || []).map((node, index) => ({
    key: node.key,
    label: node.label || node.key,
    type: ["object", "list_object", "dict"].includes(node.type) ? "object" : node.type,
    groupKey: node.key,
    description: node.description || "",
    extractionInstruction: node.extractionInstruction || "",
    required: !!node.required,
    missingPolicy: "missing",
    evidenceRequired: node.evidenceRequired !== false,
    allowedValues: node.allowedValues || [],
    unit: "",
    validationRule: "",
    exampleValues: [],
    notes: node.notes || "",
    order: index + 1,
  }));
}

export function groupsFromTree(tree = []) {
  return (tree || []).map((node, index) => ({
    groupKey: node.key,
    label: node.label || node.key,
    description: node.description || "",
    order: index + 1,
  }));
}

export function treeFromFlatFields(fields = []) {
  if (!fields?.length) return [];
  return normalizeTree(
    fields.map((field) =>
      newSchemaNode(field.key, field.label || field.key, field.type === "object" ? "object" : field.type || "string", field.type === "object" ? [newSchemaNode("value", "值", "string")] : [], {
        description: field.description || "",
        extractionInstruction: field.extractionInstruction || field.extraction_instruction || "",
        required: !!field.required,
        evidenceRequired: field.evidenceRequired ?? field.evidence_required ?? true,
        allowedValues: field.allowedValues || field.allowed_values || [],
        notes: field.notes || "",
      }),
    ),
  );
}

export function sampleRecord(tree = []) {
  return {
    paper_id: "string",
    material_name: "string",
    record_identity: { paper_id: "string", material_name: "string" },
    data: sampleObject(tree),
  };
}

export function sampleNode(node) {
  if (!node?.key) return {};
  return { [node.key]: sampleValue(node) };
}

export function sampleObject(nodes = []) {
  const out = {};
  for (const node of nodes || []) {
    if (!node?.key) continue;
    out[node.key] = sampleValue(node);
  }
  return out;
}

export function sampleValue(node = {}) {
  if (node.type === "object") return sampleObject(node.children || []);
  if (node.type === "list_object") return [sampleObject(node.children || [])];
  if (node.type === "list_string") return ["string"];
  if (node.type === "dict") return { key: "value" };
  if (node.type === "number") return 0;
  if (node.type === "boolean") return false;
  return "string";
}

export function treeStats(tree = []) {
  const stats = {
    topLevelCount: (tree || []).length,
    totalNodeCount: 0,
    leafCount: 0,
    objectCount: 0,
    listObjectCount: 0,
    dictCount: 0,
    enumCount: 0,
    maxDepth: 0,
  };
  const visit = (nodes, depth) => {
    stats.maxDepth = Math.max(stats.maxDepth, nodes?.length ? depth : 0);
    for (const node of nodes || []) {
      stats.totalNodeCount += 1;
      if (node.type === "object") stats.objectCount += 1;
      if (node.type === "list_object") stats.listObjectCount += 1;
      if (node.type === "dict") stats.dictCount += 1;
      if (["enum", "multi_enum"].includes(node.type)) stats.enumCount += 1;
      if ((node.children || []).length) visit(node.children, depth + 1);
      else stats.leafCount += 1;
    }
  };
  visit(tree, 1);
  return stats;
}

export function parentSupportsChildren(type) {
  return ["object", "list_object"].includes(type);
}

export function getAtPath(nodes = [], path = []) {
  let current = nodes[path[0]];
  for (const index of path.slice(1)) current = current?.children?.[index];
  return current || null;
}

export function updateAtPath(nodes = [], path = [], updater) {
  if (!path.length) return nodes;
  return nodes.map((node, index) => {
    if (index !== path[0]) return node;
    if (path.length === 1) return updater(node);
    return { ...node, children: updateAtPath(node.children || [], path.slice(1), updater) };
  });
}

export function insertSibling(nodes = [], path = [], sibling) {
  if (path.length === 1) return [...nodes.slice(0, path[0] + 1), sibling, ...nodes.slice(path[0] + 1)];
  return nodes.map((node, index) => (index === path[0] ? { ...node, children: insertSibling(node.children || [], path.slice(1), sibling) } : node));
}

export function insertChild(nodes = [], path = [], child) {
  return updateAtPath(nodes, path, (node) => ({
    ...node,
    type: parentSupportsChildren(node.type) ? node.type : "object",
    children: [...(node.children || []), child],
  }));
}

export function deleteAtPath(nodes = [], path = []) {
  if (path.length === 1) return nodes.filter((_, index) => index !== path[0]);
  return nodes.map((node, index) => (index === path[0] ? { ...node, children: deleteAtPath(node.children || [], path.slice(1)) } : node));
}

export function moveNode(nodes = [], path = [], direction = -1) {
  if (path.length === 1) {
    const from = path[0];
    const to = from + direction;
    if (to < 0 || to >= nodes.length) return nodes;
    const next = [...nodes];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    return next;
  }
  return nodes.map((node, index) => (index === path[0] ? { ...node, children: moveNode(node.children || [], path.slice(1), direction) } : node));
}

export function cloneNode(node) {
  if (!node) return newSchemaNode("field", "字段", "string");
  return {
    ...node,
    key: `${node.key || "field"}_copy`,
    label: `${node.label || "字段"} 副本`,
    children: (node.children || []).map(cloneNode),
  };
}

export function mergeTree(existing = [], incoming = []) {
  const out = [...(existing || [])];
  for (const node of incoming || []) {
    const index = out.findIndex((item) => item.key === node.key);
    if (index < 0) out.push(node);
    else out[index] = { ...out[index], ...node, children: mergeTree(out[index].children || [], node.children || []) };
  }
  return normalizeTree(out);
}
