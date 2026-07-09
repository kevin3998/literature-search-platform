export function summarizePromptContract(contract) {
  if (!contract) return [];
  return [
    ["契约版本", contract.promptContractVersion || "-"],
    ["文献集合", contract.collectionVersion || "-"],
    ["字段方案", contract.schemaVersion || "-"],
    ["字段数", (contract.fieldContracts || []).length],
    ["抽取规则", (contract.extractionRules || []).length],
  ];
}

export function buildPromptContractSections(contract) {
  if (!contract) return [];
  const rules = contract.extractionRules || [];
  const recordContract = contract.recordContract || {};
  const fieldContracts = contract.fieldContracts || [];
  const outputJsonContract = contract.outputJsonContract || {};
  return [
    {
      key: "rules",
      kind: "rules",
      title: "抽取规则",
      count: rules.length,
      data: rules,
      copyText: rules.map((rule, index) => `${index + 1}. ${rule}`).join("\n"),
    },
    {
      key: "record",
      kind: "json",
      title: "记录契约",
      data: recordContract,
      copyText: stringify(recordContract),
    },
    {
      key: "fields",
      kind: "fields",
      title: "字段契约",
      count: fieldContracts.length,
      data: fieldContracts,
      copyText: stringify(fieldContracts),
    },
    {
      key: "output",
      kind: "json",
      title: "输出 JSON 契约",
      data: outputJsonContract,
      copyText: stringify(outputJsonContract),
    },
    {
      key: "raw",
      kind: "json",
      title: "原始 JSON",
      data: contract,
      copyText: stringify(contract),
    },
  ];
}

export function stringify(value) {
  return JSON.stringify(value ?? null, null, 2);
}
