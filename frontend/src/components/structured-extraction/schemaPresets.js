export const SCHEMA_TARGET_PRESETS = [
  {
    key: "paper",
    label: "每篇文献一条记录",
    description: "适合抽取论文主题、总体方法、主要结论等论文级信息。",
    recommended: false,
    recordSchema: {
      recordType: "paper_record",
      recordUnit: "paper_level",
      primaryEntity: "paper",
      onePaperMayHaveMultipleRecords: false,
      recordIdentityFields: ["paper_id"],
      deduplicationKeys: ["paper_id"],
      parentRecordType: "",
    },
  },
  {
    key: "material",
    label: "每种材料一条记录",
    description: "适合膜材料、催化剂、吸附剂等材料级抽取。字段固定，但每篇文献可返回多条材料记录。",
    recommended: true,
    recordSchema: {
      recordType: "material_record",
      recordUnit: "material_level",
      primaryEntity: "material",
      onePaperMayHaveMultipleRecords: true,
      recordIdentityFields: ["paper_id", "material_name"],
      deduplicationKeys: ["paper_id", "material_name"],
      parentRecordType: "",
    },
  },
  {
    key: "sample",
    label: "每个样品一条记录",
    description: "适合同一材料存在多个样品、配方或批次的场景。",
    recommended: false,
    recordSchema: {
      recordType: "sample_record",
      recordUnit: "sample_level",
      primaryEntity: "sample",
      onePaperMayHaveMultipleRecords: true,
      recordIdentityFields: ["paper_id", "sample_name"],
      deduplicationKeys: ["paper_id", "sample_name"],
      parentRecordType: "",
    },
  },
  {
    key: "experiment",
    label: "每个实验条件一条记录",
    description: "适合按材料和实验条件区分记录，例如温度、压力、进料组成不同。",
    recommended: false,
    recordSchema: {
      recordType: "experiment_record",
      recordUnit: "experiment_level",
      primaryEntity: "experiment",
      onePaperMayHaveMultipleRecords: true,
      recordIdentityFields: ["paper_id", "material_name", "experiment_condition"],
      deduplicationKeys: ["paper_id", "material_name", "experiment_condition"],
      parentRecordType: "",
    },
  },
  {
    key: "measurement",
    label: "每个测试结果一条记录",
    description: "适合每个测试条件或性能点单独成行，便于后续表格分析。",
    recommended: false,
    recordSchema: {
      recordType: "measurement_record",
      recordUnit: "condition_level",
      primaryEntity: "measurement",
      onePaperMayHaveMultipleRecords: true,
      recordIdentityFields: ["paper_id", "material_name", "test_condition"],
      deduplicationKeys: ["paper_id", "material_name", "test_condition"],
      parentRecordType: "",
    },
  },
];

export function applySchemaPreset(draft, presetKey) {
  const preset = SCHEMA_TARGET_PRESETS.find((item) => item.key === presetKey) || SCHEMA_TARGET_PRESETS[1];
  return {
    ...draft,
    recordSchema: { ...preset.recordSchema },
  };
}

export function matchingSchemaPresetKey(recordSchema = {}) {
  const match = SCHEMA_TARGET_PRESETS.find((preset) => {
    const expected = preset.recordSchema;
    return (
      expected.recordType === recordSchema.recordType &&
      expected.recordUnit === recordSchema.recordUnit &&
      expected.primaryEntity === recordSchema.primaryEntity &&
      sameList(expected.recordIdentityFields, recordSchema.recordIdentityFields || []) &&
      sameList(expected.deduplicationKeys, recordSchema.deduplicationKeys || [])
    );
  });
  return match?.key || "custom";
}

export function schemaConflictMessages(recordSchema = {}) {
  const messages = [];
  const unit = recordSchema.recordUnit || "";
  const identity = recordSchema.recordIdentityFields || [];
  const dedupe = recordSchema.deduplicationKeys || [];
  if (unit && unit !== "paper_level") {
    if (identity.filter((item) => item !== "paper_id").length === 0) {
      messages.push("非论文级记录需要至少一个材料/样品/条件身份字段，不能只使用 paper_id。");
    }
    if (dedupe.filter((item) => item !== "paper_id").length === 0) {
      messages.push("非论文级记录的去重键需要包含 paper_id 之外的字段。");
    }
    if ((recordSchema.primaryEntity || "") === "paper") {
      messages.push("当前记录粒度不是论文级，主要实体不应为 paper。");
    }
    if (!recordSchema.onePaperMayHaveMultipleRecords) {
      messages.push("非论文级记录通常需要允许单篇文献包含多条记录。");
    }
  }
  return messages;
}

function sameList(left, right) {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
