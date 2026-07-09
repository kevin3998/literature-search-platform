const BASE = "/api";
let apiUserId = null;

export function setApiUserId(userId) {
  apiUserId = userId ? String(userId) : null;
}

export function clearApiUserId() {
  apiUserId = null;
}

function apiHeaders(headers = {}) {
  return {
    "Content-Type": "application/json",
    ...(apiUserId ? { "X-User-Id": apiUserId } : {}),
    ...headers,
  };
}

function apiUploadHeaders(headers = {}) {
  return {
    ...(apiUserId ? { "X-User-Id": apiUserId } : {}),
    ...headers,
  };
}

function snakeToCamel(key) {
  return key.replace(/_([a-z])/g, (_, char) => char.toUpperCase());
}

function camelizeObject(value) {
  if (Array.isArray(value)) return value.map(camelizeObject);
  if (!value || typeof value !== "object" || value.constructor !== Object) return value;
  return Object.fromEntries(Object.entries(value).map(([key, val]) => [snakeToCamel(key), camelizeObject(val)]));
}

function camelToSnake(key) {
  return key.replace(/[A-Z]/g, (char) => `_${char.toLowerCase()}`);
}

function snakeizeObject(value) {
  if (Array.isArray(value)) return value.map(snakeizeObject);
  if (!value || typeof value !== "object" || value.constructor !== Object) return value;
  return Object.fromEntries(Object.entries(value).map(([key, val]) => [camelToSnake(key), snakeizeObject(val)]));
}

export async function fetchModules() {
  const res = await fetch(`${BASE}/modules`);
  if (!res.ok) throw new Error("加载模块列表失败");
  return res.json();
}

export async function fetchLibrary() {
  const res = await fetch(`${BASE}/library`);
  if (!res.ok) throw new Error("加载文献库失败");
  return res.json();
}

async function apiRequest(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

async function multipartRequest(path, formData, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    method: options.method || "POST",
    body: formData,
    headers: apiUploadHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

async function responseErrorMessage(res, fallback = `请求失败 (${res.status})`) {
  try {
    const body = await res.clone().json();
    if (typeof body.detail === "string") return body.detail;
    if (body.detail) return JSON.stringify(body.detail);
    if (typeof body.message === "string") return body.message;
  } catch {
    try {
      const text = await res.text();
      if (text) return text;
    } catch {
      // keep fallback
    }
  }
  return fallback;
}

export function normalizeSession(raw, moduleId) {
  return {
    id: raw.session_id || raw.id,
    moduleId: raw.module_id || raw.moduleId || moduleId,
    userId: raw.user_id || raw.userId,
    title: raw.title || "新对话",
    status: raw.status || "active",
    tags: raw.tags || [],
    favorite: !!raw.favorite,
    pinned: !!raw.pinned,
    archived: !!raw.archived,
    deletedAt: raw.deleted_at ?? raw.deletedAt ?? null,
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? null,
    lastMessageAt: raw.last_message_at ?? raw.lastMessageAt ?? null,
    messages: raw.messages || [],
    steps: raw.steps || [],
    papers: raw.papers || [],
    searchMeta: raw.searchMeta || null,
    coverage: raw.coverage || null,
    context: raw.context || null,
    linkedArtifacts: raw.linkedArtifacts || [],
    jobs: raw.jobs || [],
    attachments: raw.attachments || [],
    uploadingAttachments: !!raw.uploadingAttachments,
    attachmentError: raw.attachmentError || null,
    liveJobs: raw.liveJobs || {},
    liveArtifacts: raw.liveArtifacts || [],
    liveTrace: raw.liveTrace || [],
    deepSuggestion: raw.deepSuggestion || null,
    streaming: !!raw.streaming,
  };
}

function normalizeAttachmentUsage(raw) {
  if (!raw) return null;
  return {
    attachmentCount: raw.attachment_count ?? raw.attachmentCount ?? 0,
    filenames: raw.filenames || [],
  };
}

function normalizeLiteratureMetadata(raw = {}) {
  const meta = { ...raw };
  const routeLabel = raw.routeLabel || raw.route_label || raw.label || null;
  const failureCode = raw.failureCode || raw.failure_code || null;
  const failureMessage = raw.failureMessage || raw.failure_message || null;
  const usedAttachments = normalizeAttachmentUsage(raw.usedAttachments || raw.used_attachments);
  const usedLibraryStats = raw.usedLibraryStats ?? raw.used_library_stats ?? false;
  const libraryStats = raw.libraryStats || camelizeObject(raw.stats || {});
  if (routeLabel) meta.routeLabel = routeLabel;
  if (failureCode) meta.failureCode = failureCode;
  if (failureMessage) meta.failureMessage = failureMessage;
  if (usedAttachments) meta.usedAttachments = usedAttachments;
  if (usedLibraryStats) meta.usedLibraryStats = true;
  if (Object.keys(libraryStats || {}).length) meta.libraryStats = libraryStats;
  return meta;
}

export function normalizeMessage(raw) {
  const metadata = normalizeLiteratureMetadata(raw.metadata || {});
  const createdAt = raw.created_at ?? raw.createdAt ?? null;
  return {
    id: raw.message_id || raw.messageId || raw.id,
    messageId: raw.message_id || raw.messageId || raw.id,
    sessionId: raw.session_id || raw.sessionId,
    turnId: raw.turn_id || raw.turnId || null,
    role: raw.role,
    content: raw.content,
    error: !!raw.error,
    createdAt,
    at: createdAt ? createdAt * 1000 : null,
    metadata,
    citation: metadata.citation || null,
    roleUsed: metadata.role_used || metadata.roleUsed || null,
    attachments: (metadata.attachments || []).map(normalizeAttachment),
  };
}

function normalizeAttachment(raw) {
  return {
    attachmentId: raw.attachment_id || raw.attachmentId,
    sessionId: raw.session_id || raw.sessionId,
    userId: raw.user_id || raw.userId,
    filename: raw.filename || "附件",
    contentType: raw.content_type || raw.contentType || "",
    status: raw.status || "parsed",
    textPreview: raw.text_preview || raw.textPreview || "",
    charCount: raw.char_count ?? raw.charCount ?? 0,
    error: raw.error || null,
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    deletedAt: raw.deleted_at ?? raw.deletedAt ?? null,
  };
}

function normalizeSearchResult(raw) {
  const queryPlanRaw = raw.query_plan || raw.queryPlan || {};
  return {
    searchResultId: raw.search_result_id || raw.searchResultId,
    sessionId: raw.session_id || raw.sessionId,
    turnId: raw.turn_id || raw.turnId || null,
    query: raw.query || "",
    queryPlan: camelizeObject(queryPlanRaw),
    queryPlanRaw,
    filters: raw.filters || {},
    results: raw.results || [],
    coverage: raw.coverage || {},
    fallbackReason: raw.fallback_reason ?? raw.fallbackReason ?? null,
    breadth: raw.breadth || {},
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

export function normalizeSessionContext(raw) {
  return {
    sessionId: raw.session_id || raw.sessionId,
    recentMessages: (raw.recent_messages || raw.recentMessages || []).map(normalizeMessage),
    recentSearchResults: (raw.recent_search_results || raw.recentSearchResults || []).map(normalizeSearchResult),
    recentEvidence: raw.recent_evidence || raw.recentEvidence || [],
    linkedArtifacts: raw.linked_artifacts || raw.linkedArtifacts || [],
    activeJobs: raw.active_jobs || raw.activeJobs || [],
    researchState: raw.research_state ?? raw.researchState ?? null,
  };
}

export function normalizeExtractionTask(raw) {
  const stats = raw.stats || {};
  return {
    taskId: raw.task_id || raw.taskId,
    userId: raw.user_id || raw.userId,
    name: raw.name || "未命名抽取任务",
    description: raw.description || "",
    status: raw.status || "draft",
    workspaceRelPath: raw.workspace_rel_path || raw.workspaceRelPath || "",
    currentCollectionVersion: raw.current_collection_version ?? raw.currentCollectionVersion ?? null,
    currentSchemaVersion: raw.current_schema_version ?? raw.currentSchemaVersion ?? null,
    modelSettings: raw.model_settings || raw.modelSettings || {},
    stats: {
      paperCount: stats.paper_count ?? stats.paperCount ?? 0,
      fieldCount: stats.field_count ?? stats.fieldCount ?? 0,
      runCount: stats.run_count ?? stats.runCount ?? 0,
      exportCount: stats.export_count ?? stats.exportCount ?? 0,
    },
    archived: !!raw.archived,
    deletedAt: raw.deleted_at ?? raw.deletedAt ?? null,
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? null,
    lastRunAt: raw.last_run_at ?? raw.lastRunAt ?? null,
  };
}

export function normalizeExtractionCandidate(raw) {
  return {
    candidateId: raw.candidate_id || raw.candidateId,
    taskId: raw.task_id || raw.taskId,
    paperId: raw.paper_id || raw.paperId,
    title: raw.title || "",
    authors: raw.authors || [],
    year: raw.year ?? null,
    journal: raw.journal || "",
    doi: raw.doi || "",
    sourcePath: raw.source_path || raw.sourcePath || "",
    indexVersion: raw.index_version ?? raw.indexVersion ?? null,
    candidateSource: raw.candidate_source || raw.candidateSource || "",
    sourceQuery: raw.source_query || raw.sourceQuery || "",
    matchedFields: raw.matched_fields || raw.matchedFields || [],
    metadataScore: raw.metadata_score ?? raw.metadataScore ?? 0,
    llmDecision: raw.llm_decision ?? raw.llmDecision ?? null,
    llmRelevanceScore: raw.llm_relevance_score ?? raw.llmRelevanceScore ?? null,
    llmReason: raw.llm_reason ?? raw.llmReason ?? null,
    userDecision: raw.user_decision || raw.userDecision || "candidate",
    excludeReason: raw.exclude_reason ?? raw.excludeReason ?? null,
    duplicateGroupId: raw.duplicate_group_id ?? raw.duplicateGroupId ?? null,
    canonicalPaperId: raw.canonical_paper_id ?? raw.canonicalPaperId ?? null,
    duplicateReason: raw.duplicate_reason ?? raw.duplicateReason ?? null,
    paperRef: raw.paper_ref || raw.paperRef || {},
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? null,
  };
}

export function normalizeCollectionVersion(raw) {
  return {
    collectionVersion: raw.collection_version || raw.collectionVersion,
    taskId: raw.task_id || raw.taskId,
    paperCount: raw.paper_count ?? raw.paperCount ?? 0,
    summary: raw.summary || {},
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    includedPapers: (raw.included_papers || raw.includedPapers || []).map(camelizeObject),
  };
}

function normalizeCollectionSearchResult(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    created: raw.created ?? 0,
    totalCandidates: raw.total_candidates ?? raw.totalCandidates ?? 0,
    candidates: (raw.candidates || []).map(normalizeExtractionCandidate),
    counts: raw.counts || null,
  };
}

function normalizeCandidateList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    candidates: (raw.candidates || []).map(normalizeExtractionCandidate),
    counts: raw.counts || {},
  };
}

function normalizeCollectionFilterOptions(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    available: raw.available !== false,
    reason: raw.reason || null,
    years: raw.years || [],
    journals: raw.journals || [],
    sites: raw.sites || [],
  };
}

function normalizeFreezeResult(raw) {
  return {
    collectionVersion: raw.collection_version || raw.collectionVersion,
    taskId: raw.task_id || raw.taskId,
    paperCount: raw.paper_count ?? raw.paperCount ?? 0,
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    includedPapers: (raw.included_papers || raw.includedPapers || []).map(camelizeObject),
  };
}

export function normalizeExtractionSchema(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    schemaVersion: raw.schema_version ?? raw.schemaVersion ?? null,
    baseCollectionVersion: raw.base_collection_version ?? raw.baseCollectionVersion ?? null,
    schemaMode: raw.schema_mode || raw.schemaMode || "flat_fields",
    recordSchema: camelizeObject(raw.record_schema || raw.recordSchema || {}),
    fieldTree: (raw.field_tree || raw.fieldTree || []).map(camelizeObject),
    fieldGroups: (raw.field_groups || raw.fieldGroups || []).map(camelizeObject),
    fields: (raw.fields || []).map(camelizeObject),
    fieldCount: raw.field_count ?? raw.fieldCount ?? (raw.fields || []).length,
    changeSummary: camelizeObject(raw.change_summary || raw.changeSummary || {}),
    status: raw.status || "draft",
    validationErrors: raw.validation_errors || raw.validationErrors || [],
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? null,
    frozenAt: raw.frozen_at ?? raw.frozenAt ?? null,
  };
}

function schemaDraftPayload(payload = {}) {
  return {
    schema_mode: payload.schema_mode || payload.schemaMode || "flat_fields",
    record_schema: snakeizeObject(payload.record_schema || payload.recordSchema || {}),
    field_tree: snakeizeObject(payload.field_tree || payload.fieldTree || []),
    field_groups: snakeizeObject(payload.field_groups || payload.fieldGroups || []),
    fields: snakeizeObject(payload.fields || []),
  };
}

function normalizeSchemaVersionList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    versions: (raw.versions || []).map(normalizeExtractionSchema),
  };
}

export function normalizePromptContract(raw) {
  return {
    promptContractVersion: raw.prompt_contract_version || raw.promptContractVersion,
    taskId: raw.task_id || raw.taskId,
    schemaVersion: raw.schema_version || raw.schemaVersion,
    collectionVersion: raw.collection_version || raw.collectionVersion,
    schemaMode: raw.schema_mode || raw.schemaMode || "flat_fields",
    recordContract: camelizeObject(raw.record_contract || raw.recordContract || {}),
    fieldContracts: (raw.field_contracts || raw.fieldContracts || []).map(camelizeObject),
    schemaTreeContract: (raw.schema_tree_contract || raw.schemaTreeContract || []).map(camelizeObject),
    sectionContracts: (raw.section_contracts || raw.sectionContracts || []).map(camelizeObject),
    outputJsonContract: camelizeObject(raw.output_json_contract || raw.outputJsonContract || {}),
    extractionRules: raw.extraction_rules || raw.extractionRules || [],
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizePromptContractList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    versions: (raw.versions || []).map(normalizePromptContract),
  };
}

export function normalizeEvidencePacket(raw) {
  return {
    packetVersion: raw.packet_version || raw.packetVersion,
    taskId: raw.task_id || raw.taskId,
    collectionVersion: raw.collection_version || raw.collectionVersion,
    schemaVersion: raw.schema_version || raw.schemaVersion,
    promptContractVersion: raw.prompt_contract_version || raw.promptContractVersion,
    paperCount: raw.paper_count ?? raw.paperCount ?? 0,
    fieldGroupCount: raw.field_group_count ?? raw.fieldGroupCount ?? 0,
    itemCount: raw.item_count ?? raw.itemCount ?? 0,
    settings: camelizeObject(raw.settings || {}),
    warnings: (raw.warnings || []).map(camelizeObject),
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizeEvidencePacketList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    versions: (raw.versions || []).map(normalizeEvidencePacket),
  };
}

export function normalizeEvidencePacketBuildJob(raw) {
  return {
    buildJobId: raw.build_job_id || raw.buildJobId,
    taskId: raw.task_id || raw.taskId,
    status: raw.status || "queued",
    phase: raw.phase || "resolving_inputs",
    collectionVersion: raw.collection_version || raw.collectionVersion,
    schemaVersion: raw.schema_version || raw.schemaVersion,
    promptContractVersion: raw.prompt_contract_version || raw.promptContractVersion,
    targetPacketVersion: raw.target_packet_version || raw.targetPacketVersion,
    resultPacketVersion: raw.result_packet_version ?? raw.resultPacketVersion ?? null,
    paperCount: raw.paper_count ?? raw.paperCount ?? 0,
    fieldGroupCount: raw.field_group_count ?? raw.fieldGroupCount ?? 0,
    totalItemCount: raw.total_item_count ?? raw.totalItemCount ?? 0,
    processedItemCount: raw.processed_item_count ?? raw.processedItemCount ?? 0,
    warningCount: raw.warning_count ?? raw.warningCount ?? 0,
    currentPaperId: raw.current_paper_id ?? raw.currentPaperId ?? null,
    currentFieldGroup: raw.current_field_group ?? raw.currentFieldGroup ?? null,
    currentQueryMode: raw.current_query_mode ?? raw.currentQueryMode ?? null,
    avgChunksPerItem: raw.avg_chunks_per_item ?? raw.avgChunksPerItem ?? 0,
    slowItemCount: raw.slow_item_count ?? raw.slowItemCount ?? 0,
    lastItemSeconds: raw.last_item_seconds ?? raw.lastItemSeconds ?? null,
    settings: camelizeObject(raw.settings || {}),
    warningsPreview: (raw.warnings_preview || raw.warningsPreview || []).map(camelizeObject),
    error: camelizeObject(raw.error || null),
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    startedAt: raw.started_at ?? raw.startedAt ?? null,
    updatedAt: raw.updated_at ?? raw.updatedAt ?? null,
    completedAt: raw.completed_at ?? raw.completedAt ?? null,
  };
}

function normalizeEvidencePacketBuildJobList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    jobs: (raw.jobs || []).map(normalizeEvidencePacketBuildJob),
  };
}

export function normalizeEvidencePacketItem(raw) {
  return {
    packetItemId: raw.packet_item_id || raw.packetItemId,
    packetVersion: raw.packet_version || raw.packetVersion,
    paperId: raw.paper_id || raw.paperId,
    fieldGroup: raw.field_group || raw.fieldGroup,
    fieldKeys: raw.field_keys || raw.fieldKeys || [],
    constructionQuery: raw.construction_query || raw.constructionQuery || "",
    retrievedSections: (raw.retrieved_sections || raw.retrievedSections || []).map(camelizeObject),
    chunks: (raw.chunks || []).map(camelizeObject),
    tables: (raw.tables || []).map(camelizeObject),
    figures: (raw.figures || []).map(camelizeObject),
    sourcePaths: raw.source_paths || raw.sourcePaths || [],
    warnings: raw.warnings || [],
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizeEvidencePacketItems(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    packetVersion: raw.packet_version || raw.packetVersion,
    items: (raw.items || []).map(normalizeEvidencePacketItem),
    limit: raw.limit ?? null,
    offset: raw.offset ?? 0,
    total: raw.total ?? (raw.items || []).length,
  };
}

export function normalizeExtractionRun(raw) {
  const stats = raw.stats || {};
  return {
    runId: raw.run_id || raw.runId,
    taskId: raw.task_id || raw.taskId,
    status: raw.status || "queued",
    collectionVersion: raw.collection_version || raw.collectionVersion || null,
    schemaVersion: raw.schema_version || raw.schemaVersion || null,
    promptContractVersion: raw.prompt_contract_version || raw.promptContractVersion || null,
    packetVersion: raw.packet_version || raw.packetVersion || null,
    modelSnapshot: camelizeObject(raw.model_snapshot || raw.modelSnapshot || {}),
    stats: {
      packetItemCount: stats.packet_item_count ?? stats.packetItemCount ?? 0,
      completedItemCount: stats.completed_item_count ?? stats.completedItemCount ?? 0,
      failedItemCount: stats.failed_item_count ?? stats.failedItemCount ?? 0,
      recordCount: stats.record_count ?? stats.recordCount ?? 0,
    },
    error: camelizeObject(raw.error || null),
    previousTaskStatus: raw.previous_task_status ?? raw.previousTaskStatus ?? null,
    resumeCount: raw.resume_count ?? raw.resumeCount ?? 0,
    lastHeartbeatAt: raw.last_heartbeat_at ?? raw.lastHeartbeatAt ?? null,
    interruptedAt: raw.interrupted_at ?? raw.interruptedAt ?? null,
    countedAt: raw.counted_at ?? raw.countedAt ?? null,
    recovery: camelizeObject(raw.recovery || {}),
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    startedAt: raw.started_at ?? raw.startedAt ?? null,
    completedAt: raw.completed_at ?? raw.completedAt ?? null,
  };
}

function normalizeExtractionRunList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runs: (raw.runs || []).map(normalizeExtractionRun),
  };
}

export function normalizeExtractionRunItem(raw) {
  return {
    runItemId: raw.run_item_id || raw.runItemId,
    runId: raw.run_id || raw.runId,
    taskId: raw.task_id || raw.taskId,
    packetItemId: raw.packet_item_id || raw.packetItemId,
    paperId: raw.paper_id || raw.paperId,
    fieldGroup: raw.field_group || raw.fieldGroup,
    status: raw.status || "queued",
    prompt: camelizeObject(raw.prompt || {}),
    rawOutput: raw.raw_output ?? raw.rawOutput ?? null,
    parsed: camelizeObject(raw.parsed || null),
    error: camelizeObject(raw.error || null),
    createdAt: raw.created_at ?? raw.createdAt ?? null,
    startedAt: raw.started_at ?? raw.startedAt ?? null,
    completedAt: raw.completed_at ?? raw.completedAt ?? null,
  };
}

function normalizeExtractionRunItems(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    items: (raw.items || []).map(normalizeExtractionRunItem),
  };
}

export function normalizeExtractionRecord(raw) {
  return {
    recordId: raw.record_id || raw.recordId,
    runId: raw.run_id || raw.runId,
    paperId: raw.paper_id || raw.paperId,
    recordType: raw.record_type || raw.recordType || "",
    recordIndex: raw.record_index ?? raw.recordIndex ?? 0,
    recordIdentity: camelizeObject(raw.record_identity || raw.recordIdentity || {}),
    data: camelizeObject(raw.data || {}),
    fields: camelizeObject(raw.fields || {}),
    sourcePacketItemIds: raw.source_packet_item_ids || raw.sourcePacketItemIds || [],
    qualityFlags: raw.quality_flags || raw.qualityFlags || [],
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizeExtractionRecords(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    records: (raw.records || []).map(normalizeExtractionRecord),
  };
}

export function normalizeExtractionRunRecovery(raw) {
  return {
    runId: raw.run_id || raw.runId,
    taskId: raw.task_id || raw.taskId,
    resumable: !!raw.resumable,
    status: raw.status || "",
    completedItemCount: raw.completed_item_count ?? raw.completedItemCount ?? 0,
    failedItemCount: raw.failed_item_count ?? raw.failedItemCount ?? 0,
    interruptedItemCount: raw.interrupted_item_count ?? raw.interruptedItemCount ?? 0,
    queuedItemCount: raw.queued_item_count ?? raw.queuedItemCount ?? 0,
    remainingItemCount: raw.remaining_item_count ?? raw.remainingItemCount ?? 0,
    recordCount: raw.record_count ?? raw.recordCount ?? 0,
    blockers: raw.blockers || [],
    lastError: camelizeObject(raw.last_error ?? raw.lastError ?? null),
  };
}

export function normalizeReviewRun(raw) {
  return normalizeExtractionRun(raw);
}

function normalizeReviewRunList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runs: (raw.runs || []).map(normalizeReviewRun),
  };
}

export function normalizeReviewRow(raw) {
  return {
    recordId: raw.record_id || raw.recordId,
    runId: raw.run_id || raw.runId,
    paperId: raw.paper_id || raw.paperId,
    paper: camelizeObject(raw.paper || {}),
    recordType: raw.record_type || raw.recordType || "",
    recordIndex: raw.record_index ?? raw.recordIndex ?? 0,
    recordIdentity: camelizeObject(raw.record_identity || raw.recordIdentity || {}),
    data: camelizeObject(raw.data || {}),
    baseData: camelizeObject(raw.base_data || raw.baseData || {}),
    fields: camelizeObject(raw.fields || {}),
    recordQualityFlags: raw.record_quality_flags || raw.recordQualityFlags || [],
    reviewPriority: raw.review_priority || raw.reviewPriority || "low",
    reviewStatus: raw.review_status || raw.reviewStatus || "unreviewed",
  };
}

function normalizeReviewTable(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    total: raw.total ?? 0,
    limit: raw.limit ?? 100,
    offset: raw.offset ?? 0,
    fieldKeys: raw.field_keys || raw.fieldKeys || [],
    rows: (raw.rows || []).map(normalizeReviewRow),
  };
}

export function normalizeReviewEvent(raw) {
  return {
    eventId: raw.event_id || raw.eventId,
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    recordId: raw.record_id || raw.recordId,
    fieldKey: raw.field_key || raw.fieldKey,
    eventType: raw.event_type || raw.eventType,
    oldValue: camelizeObject(raw.old_value ?? raw.oldValue ?? null),
    newValue: camelizeObject(raw.new_value ?? raw.newValue ?? null),
    reason: raw.reason || "",
    locked: !!raw.locked,
    targetEventId: raw.target_event_id ?? raw.targetEventId ?? null,
    payload: camelizeObject(raw.payload || {}),
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizeReviewEvents(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    recordId: raw.record_id || raw.recordId,
    events: (raw.events || []).map(normalizeReviewEvent),
  };
}

export function normalizeReviewSuggestion(raw) {
  return camelizeObject(raw || {});
}

export function normalizeMultimodalReviewJob(raw) {
  return {
    ...camelizeObject(raw || {}),
    suggestions: (raw.suggestions || raw.suggestionsPreview || raw.suggestions_preview || []).map(normalizeReviewSuggestion),
    suggestionsPreview: (raw.suggestions_preview || raw.suggestionsPreview || []).map(normalizeReviewSuggestion),
  };
}

function normalizeMultimodalReviewJobList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    jobs: (raw.jobs || []).map(normalizeMultimodalReviewJob),
  };
}

export function normalizeReviewSummary(raw) {
  return camelizeObject(raw || {});
}

export function normalizeReviewQueue(raw) {
  return {
    ...camelizeObject(raw || {}),
    rows: (raw.rows || []).map((row) => ({
      ...normalizeReviewRow(row),
      riskLevel: row.risk_level || row.riskLevel || "low",
      coverage: camelizeObject(row.coverage || {}),
      issues: (row.issues || []).map(normalizeReviewSuggestion),
      suggestions: (row.suggestions || []).map(normalizeReviewSuggestion),
      bulkAcceptEligible: !!(row.bulk_accept_eligible ?? row.bulkAcceptEligible),
    })),
  };
}

function normalizeSuggestionActionResult(raw) {
  return {
    ...camelizeObject(raw || {}),
    suggestion: normalizeReviewSuggestion(raw.suggestion || {}),
    record: raw.record ? normalizeReviewRow(raw.record) : null,
    suggestions: (raw.suggestions || []).map(normalizeReviewSuggestion),
  };
}

export function normalizeExtractionExport(raw) {
  return {
    exportId: raw.export_id || raw.exportId,
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    collectionVersion: raw.collection_version || raw.collectionVersion || null,
    schemaVersion: raw.schema_version || raw.schemaVersion || null,
    recordCount: raw.record_count ?? raw.recordCount ?? 0,
    fieldCount: raw.field_count ?? raw.fieldCount ?? 0,
    topLevelSectionCount: raw.top_level_section_count ?? raw.topLevelSectionCount ?? 0,
    leafPathCount: raw.leaf_path_count ?? raw.leafPathCount ?? 0,
    formats: raw.formats || [],
    files: raw.files || {},
    reviewStatusCounts: camelizeObject(raw.review_status_counts || raw.reviewStatusCounts || {}),
    multimodalProvenance: camelizeObject(raw.multimodal_provenance || raw.multimodalProvenance || {}),
    warnings: raw.warnings || [],
    createdAt: raw.created_at ?? raw.createdAt ?? null,
  };
}

function normalizeExtractionExportList(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    exports: (raw.exports || []).map(normalizeExtractionExport),
  };
}

export function normalizeExportPreview(raw) {
  return {
    taskId: raw.task_id || raw.taskId,
    runId: raw.run_id || raw.runId,
    recordCount: raw.record_count ?? raw.recordCount ?? 0,
    fieldCount: raw.field_count ?? raw.fieldCount ?? 0,
    topLevelSectionCount: raw.top_level_section_count ?? raw.topLevelSectionCount ?? 0,
    leafPathCount: raw.leaf_path_count ?? raw.leafPathCount ?? 0,
    reviewStatusCounts: camelizeObject(raw.review_status_counts || raw.reviewStatusCounts || {}),
    warnings: raw.warnings || [],
  };
}

function decisionPayload(payload = {}) {
  return {
    decision: payload.decision,
    ...(payload.exclude_reason || payload.excludeReason ? { exclude_reason: payload.exclude_reason || payload.excludeReason } : {}),
  };
}

export const sessionApi = {
  list: (moduleId, includeArchived = false) =>
    apiRequest(`/sessions?module_id=${encodeURIComponent(moduleId)}&include_archived=${includeArchived ? "true" : "false"}`).then((rows) => rows.map((row) => normalizeSession(row, moduleId))),
  create: (payload) => apiRequest("/sessions", { method: "POST", body: JSON.stringify(payload) }).then((row) => normalizeSession(row, payload.module_id)),
  get: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}`).then((row) => normalizeSession(row)),
  update: (sessionId, payload) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}`, { method: "PATCH", body: JSON.stringify(payload) }).then((row) => normalizeSession(row)),
  favorite: (sessionId, favorite) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/favorite`, { method: "POST", body: JSON.stringify({ favorite }) }).then((row) => normalizeSession(row)),
  pin: (sessionId, pinned) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/pin`, { method: "POST", body: JSON.stringify({ pinned }) }).then((row) => normalizeSession(row)),
  archive: (sessionId, archived) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/archive`, { method: "POST", body: JSON.stringify({ archived }) }).then((row) => normalizeSession(row)),
  tags: (sessionId, tags) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/tags`, { method: "POST", body: JSON.stringify({ tags }) }).then((row) => normalizeSession(row)),
  delete: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  messages: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/messages`).then((rows) => rows.map(normalizeMessage)),
  attachments: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/attachments`).then((rows) => rows.map(normalizeAttachment)),
  uploadAttachment: (sessionId, file) => {
    const form = new FormData();
    form.append("file", file);
    return multipartRequest(`/sessions/${encodeURIComponent(sessionId)}/attachments`, form).then(normalizeAttachment);
  },
  deleteAttachment: (sessionId, attachmentId) =>
    apiRequest(`/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }),
  deleteLastTurn: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/last-turn`, { method: "DELETE" }),
  context: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/context`).then(normalizeSessionContext),
  artifacts: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/artifacts`),
  jobs: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/jobs`),
  researchState: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/research-state`),
  setPaperStatus: (sessionId, body) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/paper-status`, { method: "POST", body: JSON.stringify(body) }),
  setEvidenceStatus: (sessionId, body) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/evidence-status`, { method: "POST", body: JSON.stringify(body) }),
  updateResearchState: (sessionId, body) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/research-state`, { method: "PATCH", body: JSON.stringify(body) }),
  record: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/record`),
  export: (sessionId) => apiRequest(`/sessions/${encodeURIComponent(sessionId)}/export`),
};

export const settingsApi = {
  get: () => apiRequest("/settings"),
  patch: (payload) => apiRequest("/settings", { method: "PATCH", body: JSON.stringify(payload) }),
  effective: () => apiRequest("/settings/effective"),
  diagnostics: () => apiRequest("/settings/diagnostics"),
  readiness: () => apiRequest("/settings/readiness"),
  testModel: (payload) => apiRequest("/settings/models/test", { method: "POST", body: JSON.stringify(payload) }),
  setSecret: (payload) => apiRequest("/settings/models/secret", { method: "POST", body: JSON.stringify(payload) }),
  deleteSecret: (provider) => apiRequest("/settings/models/secret", { method: "DELETE", body: JSON.stringify({ provider }) }),
  setExternalSourceSecret: (payload) => apiRequest("/settings/external-sources/secret", { method: "POST", body: JSON.stringify(payload) }),
  deleteExternalSourceSecret: (source) => apiRequest("/settings/external-sources/secret", { method: "DELETE", body: JSON.stringify({ source }) }),
  reset: (scope) => apiRequest("/settings/reset", { method: "POST", body: JSON.stringify({ scope }) }),
};

export const modelProfilesApi = {
  list: () => apiRequest("/settings/model-profiles"),
  create: (payload) => apiRequest("/settings/model-profiles", { method: "POST", body: JSON.stringify(payload) }),
  update: (id, payload) => apiRequest(`/settings/model-profiles/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id) => apiRequest(`/settings/model-profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  activate: (id) => apiRequest(`/settings/model-profiles/${encodeURIComponent(id)}/activate`, { method: "POST" }),
  reveal: (id) => apiRequest(`/settings/model-profiles/${encodeURIComponent(id)}/reveal`, { method: "POST" }),
  test: (id) => apiRequest(`/settings/model-profiles/${encodeURIComponent(id)}/test`, { method: "POST" }),
};

/**
 * 调用流式对话接口，每收到一个 SSE event 就调用 onEvent(event)。
 * event.type 取值：step / papers / search_meta / token / citation / done / error，与后端约定一致。
 */
export async function streamChat({ moduleId, sessionId, message, history, options }, onEvent) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: apiHeaders(),
    body: JSON.stringify({
      module_id: moduleId,
      session_id: sessionId,
      message,
      history: history || [],
      options: options || {},
    }),
  });

  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: await responseErrorMessage(res) });
    onEvent({ type: "done" });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      const jsonStr = line.slice(5).trim();
      if (!jsonStr) continue;
      try {
        onEvent(JSON.parse(jsonStr));
      } catch (e) {
        console.error("解析 SSE 事件失败", e, jsonStr);
      }
    }
  }
}

const LS_BASE = "/api/literature-search";

async function jsonRequest(path, options = {}) {
  const res = await fetch(`${LS_BASE}${path}`, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

export const literatureSearchApi = {
  selfcheck: () => jsonRequest("/selfcheck"),
  indexStatus: () => jsonRequest("/index/status"),
  indexHealth: () => jsonRequest("/index/health"),
  vectorStatus: () => jsonRequest("/vector/status"),
  search: (payload) => jsonRequest("/search", { method: "POST", body: JSON.stringify(payload) }),
  acquireEvidence: (payload) => jsonRequest("/acquire-evidence", { method: "POST", body: JSON.stringify(payload) }),
  paperShow: (payload) => jsonRequest("/papers/show", { method: "POST", body: JSON.stringify(payload) }),
  paperSections: (payload) => jsonRequest("/papers/sections", { method: "POST", body: JSON.stringify(payload) }),
  paperChunks: (payload) => jsonRequest("/papers/chunks", { method: "POST", body: JSON.stringify(payload) }),
  evidenceExpand: (payload) => jsonRequest("/evidence/expand", { method: "POST", body: JSON.stringify(payload) }),
  pack: (payload) => jsonRequest("/pack", { method: "POST", body: JSON.stringify(payload) }),
  taskPlan: (payload) => jsonRequest("/task/plan", { method: "POST", body: JSON.stringify(payload) }),
  taskRun: (payload) => jsonRequest("/task/run", { method: "POST", body: JSON.stringify(payload) }),
  run: (payload) => jsonRequest("/run", { method: "POST", body: JSON.stringify(payload) }),
  runs: () => jsonRequest("/runs"),
  runShow: (runId) => jsonRequest(`/runs/${encodeURIComponent(runId)}`),
  runResume: (runId) => jsonRequest(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" }),
  extract: (payload) => jsonRequest("/extract", { method: "POST", body: JSON.stringify(payload) }),
  compare: (payload) => jsonRequest("/compare", { method: "POST", body: JSON.stringify(payload) }),
  analysisBundle: (payload) => jsonRequest("/analysis/bundle", { method: "POST", body: JSON.stringify(payload) }),
  analysisShow: (bundleId) => jsonRequest(`/analysis/${encodeURIComponent(bundleId)}`),
  verifyAnswer: (payload) => jsonRequest("/verify-answer", { method: "POST", body: JSON.stringify(payload) }),
  notesBuild: (payload) => jsonRequest("/notes/build", { method: "POST", body: JSON.stringify(payload) }),
  synthesize: (payload) => jsonRequest("/synthesize", { method: "POST", body: JSON.stringify(payload) }),
  quality: (payload) => jsonRequest("/quality", { method: "POST", body: JSON.stringify(payload) }),
  vectorBuild: (payload) => jsonRequest("/vector/build", { method: "POST", body: JSON.stringify(payload) }),
  artifacts: () => jsonRequest("/artifacts"),
  artifact: (artifactId) => jsonRequest(`/artifacts/${encodeURIComponent(artifactId)}`),
  job: (jobId) => jsonRequest(`/jobs/${encodeURIComponent(jobId)}`),
};

const WORKFLOW_BASE = "/api/workflows";

async function workflowRequest(path, options = {}) {
  const res = await fetch(`${WORKFLOW_BASE}${path}`, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

export const workflowApi = {
  templates: () => workflowRequest("/templates"),
  list: (limit = 50) => workflowRequest(`?limit=${limit}`),
  create: (payload) => workflowRequest("", { method: "POST", body: JSON.stringify(payload) }),
  get: (id) => workflowRequest(`/${encodeURIComponent(id)}`),
  artifact: (id, artifactId) => workflowRequest(`/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}`),
  insights: (id) => workflowRequest(`/${encodeURIComponent(id)}/insights`),
  start: (id) => workflowRequest(`/${encodeURIComponent(id)}/start`, { method: "POST" }),
  resume: (id) => workflowRequest(`/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  pause: (id) => workflowRequest(`/${encodeURIComponent(id)}/pause`, { method: "POST" }),
  remove: (id) => workflowRequest(`/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

const STRUCTURED_EXTRACTION_BASE = "/api/structured-extraction";

async function structuredExtractionRequest(path, options = {}) {
  const res = await fetch(`${STRUCTURED_EXTRACTION_BASE}${path}`, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

export const structuredExtractionApi = {
  listTasks: (includeArchived = false, limit = 100) =>
    structuredExtractionRequest(`/tasks?include_archived=${includeArchived ? "true" : "false"}&limit=${limit}`).then((body) => (body.tasks || []).map(normalizeExtractionTask)),
  createTask: (payload) => structuredExtractionRequest("/tasks", { method: "POST", body: JSON.stringify(payload) }).then(normalizeExtractionTask),
  getTask: (taskId) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}`).then(normalizeExtractionTask),
  updateTask: (taskId, payload) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}`, { method: "PATCH", body: JSON.stringify(payload) }).then(normalizeExtractionTask),
  duplicateTask: (taskId, payload) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/duplicate`, { method: "POST", body: JSON.stringify(payload) }).then(normalizeExtractionTask),
  archiveTask: (taskId, archived) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/archive`, { method: "POST", body: JSON.stringify({ archived }) }).then(normalizeExtractionTask),
  deleteTask: (taskId) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
  searchCollection: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/search`, { method: "POST", body: JSON.stringify(payload) }).then(normalizeCollectionSearchResult),
  getCollectionFilterOptions: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/filter-options`).then(normalizeCollectionFilterOptions),
  listCandidates: (taskId, filters = {}) => {
    const params = new URLSearchParams();
    if (filters.decision) params.set("decision", filters.decision);
    if (filters.source) params.set("source", filters.source);
    if (filters.q) params.set("q", filters.q);
    if (filters.limit !== undefined && filters.limit !== null) params.set("limit", String(filters.limit));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/candidates${suffix}`).then(normalizeCandidateList);
  },
  setCandidateDecision: (taskId, candidateId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/candidates/${encodeURIComponent(candidateId)}/decision`, {
      method: "POST",
      body: JSON.stringify(decisionPayload(payload)),
    }).then(normalizeExtractionCandidate),
  bulkCandidateDecision: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/candidates/bulk-decision`, {
      method: "POST",
      body: JSON.stringify({
        candidate_ids: payload.candidate_ids || payload.candidateIds || [],
        ...decisionPayload(payload),
      }),
    }),
  expandQuestion: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/question-expansion`, { method: "POST", body: JSON.stringify(payload) }).then(camelizeObject),
  screenCandidates: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/llm-screen`, {
      method: "POST",
      body: JSON.stringify({ candidate_ids: payload.candidate_ids || payload.candidateIds || [], prompt: payload.prompt || "" }),
    }).then((body) => ({ ...camelizeObject(body), candidates: (body.candidates || []).map(normalizeExtractionCandidate) })),
  freezeCollection: (taskId) => structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/freeze`, { method: "POST" }).then(normalizeFreezeResult),
  listCollectionVersions: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/versions`).then((body) => ({
      taskId: body.task_id || body.taskId,
      versions: (body.versions || []).map(normalizeCollectionVersion),
    })),
  getCollectionVersion: (taskId, version) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/collection/versions/${encodeURIComponent(version)}`).then(normalizeCollectionVersion),
  getSchemaDraft: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/draft`).then(normalizeExtractionSchema),
  saveSchemaDraft: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/draft`, {
      method: "PUT",
      body: JSON.stringify(schemaDraftPayload(payload)),
    }).then(normalizeExtractionSchema),
  assistSchema: (taskId, payload) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/assist`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(camelizeObject),
  freezeSchema: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/freeze`, { method: "POST" }).then(normalizeExtractionSchema),
  listSchemaVersions: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/versions`).then(normalizeSchemaVersionList),
  getSchemaVersion: (taskId, schemaVersion) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/versions/${encodeURIComponent(schemaVersion)}`).then(normalizeExtractionSchema),
  duplicateSchemaToDraft: (taskId, schemaVersion) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/schema/versions/${encodeURIComponent(schemaVersion)}/duplicate-to-draft`, { method: "POST" }).then(normalizeExtractionSchema),
  compilePromptContract: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/prompt-contract/compile`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizePromptContract),
  listPromptContracts: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/prompt-contract/versions`).then(normalizePromptContractList),
  getPromptContract: (taskId, version) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/prompt-contract/versions/${encodeURIComponent(version)}`).then(normalizePromptContract),
  buildEvidencePacket: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/build`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeEvidencePacket),
  startEvidencePacketBuildJob: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/build-jobs`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeEvidencePacketBuildJob),
  listEvidencePacketBuildJobs: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/build-jobs`).then(normalizeEvidencePacketBuildJobList),
  getEvidencePacketBuildJob: (taskId, buildJobId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/build-jobs/${encodeURIComponent(buildJobId)}`).then(normalizeEvidencePacketBuildJob),
  cancelEvidencePacketBuildJob: (taskId, buildJobId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/build-jobs/${encodeURIComponent(buildJobId)}/cancel`, { method: "POST" }).then(normalizeEvidencePacketBuildJob),
  listEvidencePackets: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/versions`).then(normalizeEvidencePacketList),
  getEvidencePacket: (taskId, version) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/versions/${encodeURIComponent(version)}`).then(normalizeEvidencePacket),
  listEvidencePacketItems: (taskId, version, options = {}) => {
    const params = new URLSearchParams();
    if (options.limit !== undefined && options.limit !== null) params.set("limit", String(options.limit));
    if (options.offset !== undefined && options.offset !== null) params.set("offset", String(options.offset));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/evidence-packets/versions/${encodeURIComponent(version)}/items${suffix}`).then(normalizeEvidencePacketItems);
  },
  startExtractionRun: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeExtractionRun),
  listExtractionRuns: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs`).then(normalizeExtractionRunList),
  getExtractionRun: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}`).then(normalizeExtractionRun),
  listExtractionRunItems: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/items`).then(normalizeExtractionRunItems),
  listExtractionRunRecords: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/records`).then(normalizeExtractionRecords),
  getExtractionRunRecovery: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/recovery`).then(normalizeExtractionRunRecovery),
  resumeExtractionRun: (taskId, runId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/resume`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeExtractionRun),
  cancelExtractionRun: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }).then(normalizeExtractionRun),
  listReviewRuns: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/runs`).then(normalizeReviewRunList),
  listReviewTable: (taskId, filters = {}) => {
    const params = new URLSearchParams();
    if (filters.runId || filters.run_id) params.set("run_id", filters.runId || filters.run_id);
    if (filters.q) params.set("q", filters.q);
    if (filters.fieldKey || filters.field_key) params.set("field_key", filters.fieldKey || filters.field_key);
    if (filters.status) params.set("status", filters.status);
    if (filters.reviewPriority || filters.review_priority) params.set("review_priority", filters.reviewPriority || filters.review_priority);
    if (filters.qualityFlag || filters.quality_flag) params.set("quality_flag", filters.qualityFlag || filters.quality_flag);
    if (filters.missing !== undefined && filters.missing !== null && filters.missing !== "") params.set("missing", String(filters.missing));
    if (filters.limit) params.set("limit", String(filters.limit));
    if (filters.offset) params.set("offset", String(filters.offset));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/table${suffix}`).then(normalizeReviewTable);
  },
  getReviewRecord: (taskId, recordId, runId = null) => {
    const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}${suffix}`).then(normalizeReviewRow);
  },
  listReviewEvents: (taskId, recordId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/events`).then(normalizeReviewEvents),
  acceptReviewField: (taskId, recordId, fieldKey, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/fields/${encodeURIComponent(fieldKey)}/accept`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeReviewRow),
  editReviewField: (taskId, recordId, fieldKey, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/fields/${encodeURIComponent(fieldKey)}/edit`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeReviewRow),
  rejectReviewField: (taskId, recordId, fieldKey, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/fields/${encodeURIComponent(fieldKey)}/reject`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeReviewRow),
  lockReviewField: (taskId, recordId, fieldKey, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/fields/${encodeURIComponent(fieldKey)}/lock`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeReviewRow),
  unlockReviewField: (taskId, recordId, fieldKey, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/records/${encodeURIComponent(recordId)}/fields/${encodeURIComponent(fieldKey)}/unlock`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeReviewRow),
  revertReviewEvent: (taskId, eventId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/events/${encodeURIComponent(eventId)}/revert`, { method: "POST" }).then(normalizeReviewRow),
  bulkReviewAction: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/bulk`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then((body) => ({ ...camelizeObject(body), rows: (body.rows || []).map(normalizeReviewRow) })),
  getReviewSummary: (taskId, runId = null) => {
    const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/summary${suffix}`).then(normalizeReviewSummary);
  },
  listReviewQueue: (taskId, filters = {}) => {
    const params = new URLSearchParams();
    if (filters.runId || filters.run_id) params.set("run_id", filters.runId || filters.run_id);
    if (filters.queue) params.set("queue", filters.queue);
    if (filters.limit) params.set("limit", String(filters.limit));
    if (filters.offset) params.set("offset", String(filters.offset));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/queue${suffix}`).then(normalizeReviewQueue);
  },
  startMultimodalReviewJob: (taskId, runId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/runs/${encodeURIComponent(runId)}/multimodal-jobs`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeMultimodalReviewJob),
  listMultimodalReviewJobs: (taskId, runId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/runs/${encodeURIComponent(runId)}/multimodal-jobs`).then(normalizeMultimodalReviewJobList),
  getMultimodalReviewJob: (taskId, jobId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/multimodal-jobs/${encodeURIComponent(jobId)}`).then(normalizeMultimodalReviewJob),
  cancelMultimodalReviewJob: (taskId, jobId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/multimodal-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }).then(normalizeMultimodalReviewJob),
  acceptReviewSuggestion: (taskId, suggestionId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/suggestions/${encodeURIComponent(suggestionId)}/accept`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeSuggestionActionResult),
  rejectReviewSuggestion: (taskId, suggestionId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/suggestions/${encodeURIComponent(suggestionId)}/reject`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeSuggestionActionResult),
  bulkReviewSuggestions: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/review/suggestions/bulk`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeSuggestionActionResult),
  previewExport: (taskId, runId = null) => {
    const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/exports/preview${suffix}`).then(normalizeExportPreview);
  },
  createExport: (taskId, payload = {}) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/exports`, {
      method: "POST",
      body: JSON.stringify(snakeizeObject(payload || {})),
    }).then(normalizeExtractionExport),
  listExports: (taskId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/exports`).then(normalizeExtractionExportList),
  getExport: (taskId, exportId) =>
    structuredExtractionRequest(`/tasks/${encodeURIComponent(taskId)}/exports/${encodeURIComponent(exportId)}`).then(normalizeExtractionExport),
  downloadExport: async (taskId, exportId, format) => {
    const res = await fetch(`${STRUCTURED_EXTRACTION_BASE}/tasks/${encodeURIComponent(taskId)}/exports/${encodeURIComponent(exportId)}/download?format=${encodeURIComponent(format)}`, {
      headers: apiHeaders(),
    });
    if (!res.ok) throw new Error(await responseErrorMessage(res));
    return res;
  },
};

export async function streamWorkflow(workflowId, onEvent, { after = 0 } = {}) {
  const suffix = after > 0 ? `?after=${encodeURIComponent(after)}` : "";
  const res = await fetch(`${WORKFLOW_BASE}/${encodeURIComponent(workflowId)}/stream${suffix}`, {
    headers: apiHeaders(),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: await responseErrorMessage(res, `工作流事件流请求失败 (${res.status})`) });
    onEvent({ type: "done" });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch (e) {
        console.error("解析工作流事件失败", e, line);
      }
    }
  }
}

const CORPUS_BASE = "/api/corpus";

async function corpusRequest(path, options = {}) {
  const res = await fetch(`${CORPUS_BASE}${path}`, {
    ...options,
    headers: apiHeaders(options.headers),
  });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}

export const corpusApi = {
  dashboard: () => corpusRequest("/dashboard"),
  resolve: (payload) => corpusRequest("/resolve", { method: "POST", body: JSON.stringify(payload) }),
  paperPaths: (payload) => corpusRequest("/paper-paths", { method: "POST", body: JSON.stringify(payload) }),
  maintenanceJobs: (limit = 20) => corpusRequest(`/maintenance/jobs?limit=${limit}`),
  runMaintenance: (action) => corpusRequest(`/maintenance/${encodeURIComponent(action)}`, { method: "POST" }),
};

export async function streamLiteratureSearchJob(jobId, onEvent) {
  const res = await fetch(`${LS_BASE}/jobs/${encodeURIComponent(jobId)}/stream`, {
    headers: apiHeaders(),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: await responseErrorMessage(res, `任务流请求失败 (${res.status})`) });
    onEvent({ type: "done" });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch (e) {
        console.error("解析任务事件失败", e, line);
      }
    }
  }
}
