import { failureLabel, paperEmptyReason, routeEmptyReason, routeLabel } from "./literatureSearchLabels.js";

export function paperKey(paper) {
  return String(paper?.id || paper?.paper_id || paper?.paperId || paper?.doi || paper?.title || "");
}

function paperIdentityKeys(paper) {
  const keys = [
    paper?.key,
    paper?.id,
    paper?.paper_id,
    paper?.paperId,
    paper?.doi,
    paper?.article_id != null ? `article:${paper.article_id}` : null,
    paper?.articleId != null ? `article:${paper.articleId}` : null,
  ];
  return [...new Set(keys.filter((key) => key !== undefined && key !== null && String(key).trim()).map((key) => String(key)))];
}

export function evidenceKey(evidence) {
  return String(evidence?.alias || evidence?.citation_alias || evidence?.evidence_id || evidence?.evidenceId || evidence?.evidence_ids?.[0] || evidence?.evidence_item_id || evidence?.evidenceItemId || evidence?.source_path || evidence?.title || "");
}

export function detailValueText(value, fallback = "未提供") {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) {
    const text = value.map((item) => detailValueText(item, "")).filter(Boolean).join(", ");
    return text || fallback;
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function identityValues(value) {
  if (value === undefined || value === null || value === "") return [];
  if (Array.isArray(value)) return value.flatMap(identityValues);
  if (typeof value === "object") return Object.values(value).flatMap(identityValues);
  return [String(value)];
}

export function evidenceCitationAlias(evidence) {
  const alias = evidence?.alias || evidence?.citation_alias || evidence?.citationAlias;
  if (alias) return String(alias);
  const evidenceId = evidence?.evidence_id || evidence?.evidenceId;
  return /^\d+$/.test(String(evidenceId || "")) ? String(evidenceId) : null;
}

export function evidenceInternalIds(evidence) {
  const alias = evidenceCitationAlias(evidence);
  const ids = [
    ...identityValues(evidence?.evidence_ids || evidence?.evidenceIds),
    ...identityValues(evidence?.source_evidence_id || evidence?.sourceEvidenceId),
    ...identityValues(evidence?.equivalent_source_evidence_ids || evidence?.equivalentSourceEvidenceIds),
    ...identityValues(evidence?.evidence_id || evidence?.evidenceId),
  ].filter((id) => id && id !== String(alias || ""));
  return [...new Set(ids)];
}

function evidenceSourceNamespace(evidence) {
  const explicit = evidence?.source_namespace || evidence?.sourceNamespace;
  if (explicit) return String(explicit).trim().toLowerCase();
  const sourceType = String(evidence?.source_type || evidence?.sourceType || "").trim().toLowerCase();
  if (["pack", "evidence_pack"].includes(sourceType)) return "evidence_pack";
  if (["", "literature_search", "research_index", "search", "paper_chunks"].includes(sourceType)) {
    return "research_index";
  }
  return sourceType;
}

export function evidenceIdentityKeys(evidence) {
  const alias = evidenceCitationAlias(evidence);
  const namespace = evidenceSourceNamespace(evidence);
  const sectionId = evidence?.section_id ?? evidence?.sectionId ?? "";
  const chunkIndex = evidence?.chunk_index ?? evidence?.chunkIndex ?? "";
  const keys = [
    ...(alias ? [`alias:${alias}`] : []),
    ...evidenceInternalIds(evidence).map((id) => `source:${namespace}:${id}`),
    ...identityValues(evidence?.evidence_item_id || evidence?.evidenceItemId).map((id) => `item:${id}`),
    ...identityValues(evidence?.source_path || evidence?.sourcePath)
      .map((path) => `path:${namespace}:${path}|section:${sectionId}|chunk:${chunkIndex}`),
  ];
  return [...new Set(keys.filter(Boolean))];
}

export function latestAssistantMessage(messages = []) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "assistant") return messages[i];
  }
  return null;
}

export function latestCitation(messages = []) {
  return latestAssistantMessage(messages)?.citation || null;
}

function camelizeShallow(value) {
  if (!value || typeof value !== "object") return {};
  const toCamel = (key) => key.replace(/_([a-z])/g, (_, char) => char.toUpperCase());
  return Object.fromEntries(Object.entries(value).map(([key, val]) => [toCamel(key), val]));
}

function normalizeUsedAttachments(value) {
  if (!value) return null;
  return {
    attachmentCount: value.attachmentCount ?? value.attachment_count ?? 0,
    filenames: value.filenames || [],
  };
}

export function latestAssistantMetadata(session) {
  const message = latestAssistantMessage(session?.messages || []);
  const raw = message?.metadata || {};
  const stats = raw.libraryStats || camelizeShallow(raw.stats || {});
  const usedAttachments = normalizeUsedAttachments(raw.usedAttachments || raw.used_attachments);
  return {
    ...raw,
    route: raw.route || null,
    routeLabel: raw.routeLabel || raw.route_label || raw.label || routeLabel(raw.route),
    failureCode: raw.failureCode || raw.failure_code || null,
    failureMessage: raw.failureMessage || raw.failure_message || "",
    usedAttachments,
    usedLibraryStats: !!(raw.usedLibraryStats ?? raw.used_library_stats),
    libraryStats: stats,
  };
}

function withSummary(items, summary) {
  Object.defineProperty(items, "summary", {
    value: summary,
    enumerable: false,
    configurable: true,
  });
  return items;
}

export function buildEvidenceItems(session) {
  const meta = latestAssistantMetadata(session);
  const citation = latestCitation(session?.messages || []);
  const items = (citation?.used_evidence || []).map((item, index) => ({
    ...item,
    id: evidenceKey(item) || `evidence_${index + 1}`,
    citationAlias: evidenceCitationAlias(item),
  }));
  return withSummary(items, {
    sourceKind: "literature_evidence",
    emptyReason: items.length ? "" : routeEmptyReason(meta.route, meta.failureCode, meta.failureMessage),
  });
}

function evidenceStatusFromPool(session, evidence) {
  const pool = session?.researchState?.evidence_pool?.recent || [];
  const identities = new Set(evidenceIdentityKeys(evidence));
  return pool.find((item) => evidenceIdentityKeys(item).some((key) => identities.has(key)));
}

export function buildSessionEvidenceItems(session) {
  const current = buildEvidenceItems(session).map((item) => ({ ...item, isCurrent: true }));
  const currentByIdentity = new Map();
  for (const item of current) {
    for (const key of evidenceIdentityKeys(item)) {
      if (!currentByIdentity.has(key)) currentByIdentity.set(key, item);
    }
  }
  const pool = (session?.researchState?.evidence_pool?.recent || []).map((item, index) => {
    const key = evidenceKey(item) || item.evidence_item_id || `pool_evidence_${index + 1}`;
    const currentItem = evidenceIdentityKeys(item).map((identity) => currentByIdentity.get(identity)).find(Boolean);
    return {
      ...item,
      ...currentItem,
      ...item,
      id: item.evidence_item_id || key,
      evidenceItemId: item.evidence_item_id || item.evidenceItemId || null,
      citationAlias: currentItem?.citationAlias || evidenceCitationAlias(item),
      status: item.status || "candidate",
      note: item.note || null,
      isCurrent: !!currentItem,
      sourceKind: "session_evidence_pool",
    };
  });
  const pooledKeys = new Set(pool.flatMap((item) => evidenceIdentityKeys(item)));
  const missingCurrent = current
    .filter((item) => !evidenceIdentityKeys(item).some((key) => pooledKeys.has(key)))
    .map((item, index) => ({
      ...item,
      id: item.evidenceItemId || item.evidence_item_id || item.id || `current_evidence_${index + 1}`,
      evidenceItemId: item.evidence_item_id || item.evidenceItemId || null,
      status: item.status || evidenceStatusFromPool(session, item)?.status || "candidate",
      note: item.note || evidenceStatusFromPool(session, item)?.note || null,
      sourceKind: "current_literature_evidence",
    }));
  return [...pool, ...missingCurrent];
}

export function buildFilteredEvidenceItems(session, filter = "current") {
  const all = buildSessionEvidenceItems(session);
  if (filter === "pool") return all;
  if (filter === "current") return all.filter((item) => item.isCurrent);
  return all.filter((item) => item.status === filter);
}

export function buildEvidenceSummary(session) {
  const current = buildEvidenceItems(session);
  const pool = session?.researchState?.evidence_pool || {};
  const counts = pool.status_counts || pool.statusCounts || {};
  return {
    current: current.length,
    total: pool.total ?? buildSessionEvidenceItems(session).length,
    candidate: counts.candidate || 0,
    accepted: counts.accepted || 0,
    excluded: counts.excluded || 0,
    needsReview: counts.needs_review || counts.needsReview || 0,
  };
}

export function buildPaperItems(session) {
  const meta = latestAssistantMetadata(session);
  const statePapers = session?.researchState?.candidate_papers || session?.researchState?.candidatePapers || [];
  const currentPapers = session?.papers || [];
  const source = statePapers.length ? statePapers : currentPapers;
  const currentByKey = new Map();
  for (const paper of currentPapers) {
    for (const key of paperIdentityKeys(paper)) currentByKey.set(key, paper);
  }
  const items = source.map((paper, index) => {
    const currentPaper = paperIdentityKeys(paper).map((key) => currentByKey.get(key)).find(Boolean);
    return {
      ...(currentPaper || {}),
      ...paper,
      id: paper.key || paperKey(paper) || `paper_${index + 1}`,
      status: paper.status || "candidate",
      evidenceCount: paper.evidence_count ?? paper.evidenceCount ?? paper.evidence?.length ?? currentPaper?.evidence?.length ?? 0,
      isCurrent: !!currentPaper,
      ordinal: index + 1,
    };
  });
  return withSummary(items, {
    sourceKind: "candidate_papers",
    emptyReason: items.length ? "" : paperEmptyReason(meta.route, meta.failureCode, meta.failureMessage),
  });
}

export function buildPaperSummary(session) {
  const papers = buildPaperItems(session);
  const counts = session?.researchState?.paper_status_counts || session?.researchState?.paperStatusCounts || {};
  return {
    current: (session?.papers || []).length,
    total: papers.length,
    candidate: counts.candidate || 0,
    accepted: counts.accepted || 0,
    excluded: counts.excluded || 0,
    needsReview: counts.needs_review || counts.needsReview || 0,
  };
}

const COVERAGE_LABEL = {
  sufficient: "证据较充分",
  partial: "可部分回答",
  weak: "证据偏少",
  none: "未找到可用证据",
  ok: "已有覆盖信息",
};

const PERMISSION_LABEL = {
  grounded: "证据充分",
  partially_grounded: "部分有支持",
  hypothesis: "推断为主",
  conflicting: "证据冲突",
  not_answerable: "证据不足",
};

function auditSeverityFromCitation(citation) {
  if (!citation) return "info";
  if (citation.audit_status === "unverified" || citation.audit_status === "uncited" || citation.missing_ids?.length) {
    return "warning";
  }
  return "ok";
}

export function buildAuditItems(session) {
  const meta = latestAssistantMetadata(session);
  const citation = latestCitation(session?.messages || []);
  const coverage = session?.coverage || null;
  const searchMeta = session?.searchMeta || null;
  const trace = session?.liveTrace || [];
  const items = [];
  const suggestedActions = buildSuggestedActions(session);

  if (suggestedActions.length) {
    items.push({
      id: "suggested_actions",
      label: "建议下一步",
      severity: "info",
      summary: `可执行建议 ${suggestedActions.length} 项`,
      data: { actions: suggestedActions },
    });
  }

  if (meta.route) {
    const label = routeLabel(meta.route, meta.routeLabel);
    items.push({
      id: "route",
      label: "意图分流",
      severity: meta.failureCode ? "warning" : "info",
      summary: `本轮被识别为：${label}`,
      data: { route: meta.route, label },
    });
  }

  if (meta.failureCode || meta.failureMessage) {
    items.push({
      id: "failure",
      label: "失败 / 边界说明",
      severity: meta.failureCode === "tool_timeout_failed" ? "error" : "warning",
      summary: failureLabel(meta.failureCode, meta.failureMessage),
      data: { code: meta.failureCode, message: meta.failureMessage },
    });
  }

  if (meta.usedAttachments?.attachmentCount || meta.usedAttachments?.filenames?.length) {
    const names = meta.usedAttachments.filenames || [];
    items.push({
      id: "attachments",
      label: "上传附件",
      severity: "info",
      summary: names.length ? `本轮使用上传附件：${names.join("、")}` : `本轮使用 ${meta.usedAttachments.attachmentCount} 个上传附件`,
      data: meta.usedAttachments,
    });
  }

  if (meta.usedLibraryStats || Object.keys(meta.libraryStats || {}).length) {
    const stats = meta.libraryStats || {};
    items.push({
      id: "library_status",
      label: "文献库状态",
      severity: "info",
      summary: stats.paperCount != null ? `读取本地文献库统计：${stats.paperCount} 篇文献` : "读取本地文献库统计",
      data: stats,
    });
  }

  if (citation) {
    const usedCount = citation.used_evidence?.length || 0;
    const permission = citation.answer_permission || citation.grounding_summary?.answer_permission;
    items.push({
      id: "citation",
      label: "引用校验",
      severity: auditSeverityFromCitation(citation),
      summary: citation.missing_ids?.length
        ? `${citation.missing_ids.length} 个引用未找到对应证据`
        : `${PERMISSION_LABEL[permission] || "引用校验完成"}，已用证据 ${usedCount} 条`,
      data: citation,
    });
  }

  if (coverage) {
    const status = coverage.status || coverage.coverage_status;
    items.push({
      id: "coverage",
      label: "证据覆盖",
      severity: status === "none" || status === "weak" ? "warning" : "info",
      summary: COVERAGE_LABEL[status] || "已有覆盖诊断",
      data: coverage,
    });
  }

  if (searchMeta) {
    const retrieval = searchMeta.retrieval_used || searchMeta.retrievalUsed || searchMeta.queryPlan?.retrievalUsed;
    const vectorReason = searchMeta.vector_unavailable_reason || searchMeta.query_plan?.vector_unavailable_reason;
    items.push({
      id: "retrieval",
      label: "检索策略",
      severity: vectorReason ? "warning" : "info",
      summary: retrieval ? `本轮使用 ${retrieval} 检索` : "已记录本轮检索策略",
      data: searchMeta,
    });
  }

  if (trace.length > 0) {
    const errorCount = trace.filter((item) => item.status === "error").length;
    items.push({
      id: "trace",
      label: "工具执行",
      severity: errorCount ? "warning" : "info",
      summary: errorCount ? `${errorCount} 次工具调用出现错误` : `记录 ${trace.length} 次工具调用`,
      data: trace,
    });
  }

  return items;
}

export function findEvidence(session, evidenceId) {
  return findSessionEvidence(session, evidenceId) || buildEvidenceItems(session).find((item) => item.id === evidenceId) || null;
}

export function findPaper(session, paperId) {
  return buildPaperItems(session).find((item) => item.id === paperId) || null;
}

export function findAudit(session, auditId) {
  return buildAuditItems(session).find((item) => item.id === auditId) || null;
}

export function findSessionEvidence(session, evidenceId) {
  return buildSessionEvidenceItems(session).find((item) => item.id === evidenceId || item.evidenceItemId === evidenceId || item.evidence_item_id === evidenceId) || null;
}

export function buildSuggestedActions(session) {
  const meta = latestAssistantMetadata(session);
  const citation = latestCitation(session?.messages || []);
  const evidenceSummary = buildEvidenceSummary(session);
  const paperSummary = buildPaperSummary(session);
  const actions = [];
  const add = (id, label, description, action = id) => {
    if (!actions.some((item) => item.id === id)) actions.push({ id, label, description, action });
  };

  if (meta.failureCode === "attachment_missing" || meta.route === "attachment_missing") {
    add("upload_attachment", "上传附件", "当前会话没有可用附件，上传 txt/pdf 后再提问。", "open_attachment_picker");
  }
  if (meta.route === "plain_help" || meta.route === "plain_chat") {
    add("switch_evidence_mode", "切到证据审阅", "如果要查文献，切换到证据审阅后提出研究问题。", "set_evidence_mode");
  }
  if (meta.route?.startsWith("library_")) {
    add("ask_research_question", "继续主题检索", "基于当前文献库状态，继续提出具体研究主题。", "focus_answer");
  }
  if (["no_candidate_papers", "library_not_empty_but_no_query_hit"].includes(meta.failureCode)) {
    add("broaden_query", "放宽或改写主题", "减少限定词、替换关键词，或把问题拆成更小的主题。", "focus_answer");
    add("switch_deep_mode", "切到深度分析", "让系统尝试更完整的检索和分析过程。", "set_deep_mode");
  }
  if (meta.failureCode === "no_usable_evidence") {
    add("switch_deep_mode", "切到深度分析", "当前证据不足，可以切换深度分析扩大证据收集。", "set_deep_mode");
    add("upload_attachment", "上传补充材料", "上传综述、笔记或论文 PDF 作为当前会话上下文。", "open_attachment_picker");
  }
  if (citation?.audit_status === "unverified" || citation?.audit_status === "uncited" || citation?.missing_ids?.length) {
    add("switch_evidence_mode", "切到证据审阅", "引用校验有警告，建议优先核对证据。", "set_evidence_mode");
  }
  if (evidenceSummary.needsReview || paperSummary.needsReview) {
    add("review_pending_items", "处理待复核项", "先完成待复核证据或文献，再继续分析。", "review_pending_items");
  }
  return actions;
}
