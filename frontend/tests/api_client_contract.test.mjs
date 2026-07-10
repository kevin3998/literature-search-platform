import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { clearApiUserId, sessionApi, setApiUserId, settingsApi, streamChat, streamWorkflow, structuredExtractionApi, workflowApi } from "../src/api/client.js";
import { applySchemaPreset, schemaConflictMessages } from "../src/components/structured-extraction/schemaPresets.js";

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status || 200,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
}

test("settings model profiles keep actions visible and offer supported DeepSeek models", async () => {
  const source = await readFile(new URL("../src/components/SettingsModal.jsx", import.meta.url), "utf8");

  assert.ok(source.includes("const DEEPSEEK_MODELS = ["));
  assert.match(source, /deepseek-chat/);
  assert.match(source, /deepseek-reasoner/);
  assert.ok(source.includes("deepseek-model-options"));
  assert.match(source, /data-testid=\"model-profile-actions\"/);
  assert.ok(!source.includes('<table className="w-full text-[13px]">'));
});

test("authApi uses cookie credentials and account mutations include csrf", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", credentials: options.credentials, headers: options.headers || {}, body: options.body });
    if (url === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-1" });
    if (url === "/api/auth/me") return jsonResponse({ user_id: "u1", email: "alice@example.com", display_name: "Alice", role: "admin", status: "active" });
    return jsonResponse({ ok: true });
  };

  const { authApi, accountApi } = await import(`../src/api/client.js?auth=${Date.now()}`);

  await authApi.me();
  await accountApi.updateProfile({ display_name: "Alice Chen" });

  assert.equal(calls[0].url, "/api/auth/me");
  assert.equal(calls[0].credentials, "include");
  assert.equal(calls[1].url, "/api/auth/csrf");
  assert.equal(calls[1].credentials, "include");
  assert.equal(calls[2].url, "/api/account/profile");
  assert.equal(calls[2].headers["X-CSRF-Token"], "csrf-1");
  assert.equal(calls[2].credentials, "include");
});

test("adminApi uses csrf headers for mutations and wraps query params", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", credentials: options.credentials, headers: options.headers || {}, body: options.body });
    if (url === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-admin" });
    return jsonResponse({ users: [], audit_events: [], ok: true });
  };

  const { adminApi } = await import(`../src/api/client.js?admin=${Date.now()}`);

  await adminApi.users({ query: "alice", limit: 25 });
  await adminApi.updateUser("user 1", { status: "disabled" });

  assert.equal(calls[0].url, "/api/admin/users?query=alice&limit=25");
  assert.equal(calls[0].credentials, "include");
  assert.equal(calls[1].url, "/api/auth/csrf");
  assert.equal(calls[2].url, "/api/admin/users/user%201");
  assert.equal(calls[2].method, "PATCH");
  assert.equal(calls[2].headers["X-CSRF-Token"], "csrf-admin");
  assert.deepEqual(JSON.parse(calls[2].body), { status: "disabled" });
});

test("sessionApi normalizes backend snake_case sessions into frontend camelCase models", async () => {
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return jsonResponse([
      {
        session_id: "s1",
        module_id: "literature_search",
        user_id: "u1",
        title: "Paper chat",
        status: "active",
        tags: ["tag"],
        favorite: 1,
        pinned: 0,
        archived: 0,
        deleted_at: null,
        created_at: 10,
        updated_at: 11,
        last_message_at: 12,
      },
    ]);
  };

  const sessions = await sessionApi.list("literature_search");

  assert.equal(requestedUrl, "/api/sessions?module_id=literature_search&include_archived=false");
  assert.deepEqual(sessions[0], {
    id: "s1",
    moduleId: "literature_search",
    userId: "u1",
    title: "Paper chat",
    status: "active",
    tags: ["tag"],
    favorite: true,
    pinned: false,
    archived: false,
    deletedAt: null,
    createdAt: 10,
    updatedAt: 11,
    lastMessageAt: 12,
    messages: [],
    steps: [],
    papers: [],
    searchMeta: null,
    coverage: null,
    context: null,
    linkedArtifacts: [],
    jobs: [],
    attachments: [],
    uploadingAttachments: false,
    attachmentError: null,
    liveJobs: {},
    liveArtifacts: [],
    liveTrace: [],
    deepSuggestion: null,
    streaming: false,
  });
});

test("session API omits X-User-Id by default and sends it after adapter configuration", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, headers: options.headers || {} });
    return jsonResponse([]);
  };

  clearApiUserId();
  await sessionApi.list("literature_search");
  setApiUserId("alice");
  await sessionApi.list("literature_search");
  clearApiUserId();

  assert.equal(calls[0].headers["X-User-Id"], undefined);
  assert.equal(calls[1].headers["X-User-Id"], "alice");
});

test("sessionApi normalizes backend snake_case messages and context", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url.endsWith("/messages")) {
      return jsonResponse([
        {
          message_id: "m1",
          session_id: "s1",
          turn_id: "t1",
          role: "assistant",
          content: "answer",
          error: false,
          created_at: 20,
          metadata: {
            role_used: "general",
            citation: { status: "ok" },
            route: "library_count",
            label: "文献库状态",
            failure_code: "attachment_missing",
            failure_message: "当前会话没有可用附件。",
            used_attachments: { attachment_count: 1, filenames: ["note.txt"] },
            used_library_stats: true,
            stats: { paper_count: 3 },
          },
        },
      ]);
    }
    return jsonResponse({
      session_id: "s1",
      recent_messages: [],
      recent_search_results: [
        {
          search_result_id: "sr1",
          query_plan: { retrieval_used: "fts" },
          coverage: { status: "ok" },
          breadth: { source_count: 1 },
          results: [{ title: "P" }],
          created_at: 30,
        },
      ],
      recent_evidence: [],
      linked_artifacts: [],
      active_jobs: [],
      research_state: null,
    });
  };

  const messages = await sessionApi.messages("s1");
  const context = await sessionApi.context("s1");

  assert.deepEqual(calls, ["/api/sessions/s1/messages", "/api/sessions/s1/context"]);
  assert.deepEqual(messages[0], {
    id: "m1",
    messageId: "m1",
    sessionId: "s1",
    turnId: "t1",
    role: "assistant",
    content: "answer",
    error: false,
    createdAt: 20,
    at: 20000,
    metadata: {
      role_used: "general",
      citation: { status: "ok" },
      route: "library_count",
      label: "文献库状态",
      routeLabel: "文献库状态",
      failure_code: "attachment_missing",
      failure_message: "当前会话没有可用附件。",
      failureCode: "attachment_missing",
      failureMessage: "当前会话没有可用附件。",
      used_attachments: { attachment_count: 1, filenames: ["note.txt"] },
      usedAttachments: { attachmentCount: 1, filenames: ["note.txt"] },
      used_library_stats: true,
      usedLibraryStats: true,
      stats: { paper_count: 3 },
      libraryStats: { paperCount: 3 },
    },
    citation: { status: "ok" },
    roleUsed: "general",
    attachments: [],
  });
  assert.equal(context.sessionId, "s1");
  assert.equal(context.recentSearchResults[0].searchResultId, "sr1");
  assert.equal(context.recentSearchResults[0].queryPlan.retrievalUsed, "fts");
  assert.equal(context.recentSearchResults[0].createdAt, 30);
});

test("streamChat sends the backend snake_case chat contract", async () => {
  let requestBody = null;
  let requestHeaders = null;
  globalThis.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    requestHeaders = options.headers;
    return new Response("data: {\"type\":\"done\"}\\n\\n", {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  };

  setApiUserId("alice");
  await streamChat(
    { moduleId: "literature_search", sessionId: "s1", message: "hello", history: [], options: {} },
    () => {}
  );
  clearApiUserId();

  assert.equal(requestBody.module_id, "literature_search");
  assert.equal(requestBody.session_id, "s1");
  assert.equal(requestBody.moduleId, undefined);
  assert.equal(requestBody.sessionId, undefined);
  assert.equal(requestHeaders["X-User-Id"], "alice");
});

test("sessionApi uploads session attachments with multipart form data", async () => {
  let requestedUrl = null;
  let requestBody = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestBody = options.body;
    requestHeaders = options.headers;
    return jsonResponse({
      attachment_id: "att_1",
      session_id: "s1",
      filename: "note.txt",
      content_type: "text/plain",
      status: "parsed",
      text_preview: "hello",
      char_count: 5,
      created_at: 1,
    });
  };

  const file = new File(["hello"], "note.txt", { type: "text/plain" });
  const uploaded = await sessionApi.uploadAttachment("s1", file);

  assert.equal(requestedUrl, "/api/sessions/s1/attachments");
  assert.equal(requestHeaders["Content-Type"], undefined);
  assert.equal(requestBody instanceof FormData, true);
  assert.equal(uploaded.attachmentId, "att_1");
  assert.equal(uploaded.filename, "note.txt");
});

test("sessionApi sets session evidence status with snake_case payload", async () => {
  let requestedUrl = null;
  let requestBody = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestBody = JSON.parse(options.body);
    return jsonResponse({
      session_id: "s1",
      evidence_pool: {
        total: 1,
        status_counts: { accepted: 1 },
        recent: [{ evidence_item_id: "evitem_1", evidence_id: "E1", status: "accepted" }],
      },
    });
  };

  const state = await sessionApi.setEvidenceStatus("s1", {
    evidence_item_id: "evitem_1",
    status: "accepted",
    note: "关键证据",
  });

  assert.equal(requestedUrl, "/api/sessions/s1/evidence-status");
  assert.deepEqual(requestBody, { evidence_item_id: "evitem_1", status: "accepted", note: "关键证据" });
  assert.equal(state.evidence_pool.status_counts.accepted, 1);
});

test("streamChat parses SSE events split across network chunks", async () => {
  const encoder = new TextEncoder();
  const events = [];
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"type":"token","text":"he'));
          controller.enqueue(encoder.encode('llo"}\n\ndata: {"type":"done"}\n\n'));
          controller.close();
        },
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } }
    );

  await streamChat(
    { moduleId: "literature_search", sessionId: "s1", message: "hello", history: [], options: {} },
    (event) => events.push(event)
  );

  assert.deepEqual(events, [
    { type: "token", text: "hello" },
    { type: "done" },
  ]);
});

test("streamChat surfaces backend error detail instead of a silent generic failure", async () => {
  const events = [];
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "readiness failed: sessions.read" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });

  await streamChat(
    { moduleId: "literature_search", sessionId: "s1", message: "hello", history: [], options: {} },
    (event) => events.push(event)
  );

  assert.deepEqual(events, [
    { type: "error", message: "readiness failed: sessions.read" },
    { type: "done" },
  ]);
});

test("settings and workflow APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "workflow contract failed" }, { status: 503 });

  await assert.rejects(settingsApi.readiness(), /workflow contract failed/);
  await assert.rejects(workflowApi.templates(), /workflow contract failed/);
});

test("workflowApi requests artifact preview with encoded workflow and artifact ids", async () => {
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return jsonResponse({
      workflow_id: "wf/1",
      artifact_id: "users/local_user/research_agent/task/screening/idea_screening_results.md",
      content_type: "markdown",
      text: "# 筛选摘要",
      json: null,
    });
  };

  const preview = await workflowApi.artifact("wf/1", "users/local_user/research_agent/task/screening/idea_screening_results.md");

  assert.equal(requestedUrl, "/api/workflows/wf%2F1/artifacts/users%2Flocal_user%2Fresearch_agent%2Ftask%2Fscreening%2Fidea_screening_results.md");
  assert.equal(preview.content_type, "markdown");
});

test("workflowApi requests workflow insights with encoded workflow id", async () => {
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return jsonResponse({
      workflow_id: "wf/1",
      evidence: { available: false, card_count: 0, selected_count: 0, role_counts: {}, support_counts: {}, cards: [] },
      diagnostics: { available: false, severity_counts: { info: 0, warning: 0, error: 0 }, items: [] },
    });
  };

  const insights = await workflowApi.insights("wf/1");

  assert.equal(requestedUrl, "/api/workflows/wf%2F1/insights");
  assert.equal(insights.workflow_id, "wf/1");
});

test("structuredExtractionApi lists and normalizes task contracts", async () => {
  let requestedUrl = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestHeaders = options.headers || {};
    return jsonResponse({
      tasks: [
        {
          task_id: "11111111-1111-4111-8111-111111111111",
          user_id: "alice",
          name: "Data extraction",
          description: "",
          status: "draft",
          workspace_rel_path: "research_agent/structured_extraction/tasks/11111111-1111-4111-8111-111111111111",
          current_collection_version: null,
          current_schema_version: null,
          model_settings: {},
          stats: { paper_count: 1 },
          archived: 0,
          deleted_at: null,
          created_at: 10,
          updated_at: 11,
          last_run_at: null,
        },
      ],
    });
  };

  setApiUserId("alice");
  const tasks = await structuredExtractionApi.listTasks();
  clearApiUserId();

  assert.equal(requestedUrl, "/api/structured-extraction/tasks?include_archived=false&limit=100");
  assert.equal(requestHeaders["X-User-Id"], "alice");
  assert.deepEqual(tasks[0], {
    taskId: "11111111-1111-4111-8111-111111111111",
    userId: "alice",
    name: "Data extraction",
    description: "",
    status: "draft",
    workspaceRelPath: "research_agent/structured_extraction/tasks/11111111-1111-4111-8111-111111111111",
    currentCollectionVersion: null,
    currentSchemaVersion: null,
    modelSettings: {},
    stats: { paperCount: 1, fieldCount: 0, runCount: 0, exportCount: 0 },
    archived: false,
    deletedAt: null,
    createdAt: 10,
    updatedAt: 11,
    lastRunAt: null,
  });
});

test("structuredExtractionApi preserves backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "structured task failed" }, { status: 500 });

  await assert.rejects(structuredExtractionApi.listTasks(), /structured task failed/);
});

test("structuredExtractionApi collection search sends contract and normalizes candidates", async () => {
  let requestedUrl = null;
  let requestBody = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestBody = JSON.parse(options.body);
    requestHeaders = options.headers || {};
    return jsonResponse({
      created: 1,
      total_candidates: 1,
      candidates: [
        {
          candidate_id: "33333333-3333-4333-8333-333333333333",
          task_id: "22222222-2222-4222-8222-222222222222",
          paper_id: "p1",
          title: "Membrane paper",
          authors: ["Alice"],
          year: 2024,
          journal: "Water Research",
          doi: "10.1/x",
          source_path: "articles/1/fulltext.md",
          index_version: 3,
          candidate_source: "metadata_search",
          source_query: "membrane",
          matched_fields: ["title"],
          metadata_score: 0.72,
          llm_decision: null,
          llm_relevance_score: null,
          llm_reason: null,
          user_decision: "candidate",
          exclude_reason: null,
          duplicate_group_id: null,
          canonical_paper_id: null,
        },
      ],
    });
  };

  setApiUserId("alice");
  const result = await structuredExtractionApi.searchCollection("22222222-2222-4222-8222-222222222222", { query: "membrane", limit: 50 });
  clearApiUserId();

  assert.equal(requestedUrl, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/collection/search");
  assert.deepEqual(requestBody, { query: "membrane", limit: 50 });
  assert.equal(requestHeaders["X-User-Id"], "alice");
  assert.equal(result.created, 1);
  assert.equal(result.totalCandidates, 1);
  assert.deepEqual(result.candidates[0], {
    candidateId: "33333333-3333-4333-8333-333333333333",
    taskId: "22222222-2222-4222-8222-222222222222",
    paperId: "p1",
    title: "Membrane paper",
    authors: ["Alice"],
    year: 2024,
    journal: "Water Research",
    doi: "10.1/x",
    sourcePath: "articles/1/fulltext.md",
    indexVersion: 3,
    candidateSource: "metadata_search",
    sourceQuery: "membrane",
    matchedFields: ["title"],
    metadataScore: 0.72,
    llmDecision: null,
    llmRelevanceScore: null,
    llmReason: null,
    userDecision: "candidate",
    excludeReason: null,
    duplicateGroupId: null,
    canonicalPaperId: null,
    duplicateReason: null,
    paperRef: {},
    createdAt: null,
    updatedAt: null,
  });
});

test("structuredExtractionApi collection search preserves unlimited limit contract", async () => {
  let requestBody = null;
  globalThis.fetch = async (_url, options = {}) => {
    requestBody = JSON.parse(options.body);
    return jsonResponse({ created: 0, total_candidates: 0, candidates: [] });
  };

  await structuredExtractionApi.searchCollection("22222222-2222-4222-8222-222222222222", { query: "membrane", limit: null });

  assert.deepEqual(requestBody, { query: "membrane", limit: null });
});

test("structuredExtractionApi candidate list can request unlimited rows", async () => {
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", candidates: [], counts: {} });
  };

  await structuredExtractionApi.listCandidates("22222222-2222-4222-8222-222222222222", { limit: 0 });

  assert.equal(requestedUrl, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/collection/candidates?limit=0");
});

test("structuredExtractionApi collection filter options sends user header and normalizes response", async () => {
  let requestedUrl = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestHeaders = options.headers || {};
    return jsonResponse({
      task_id: "22222222-2222-4222-8222-222222222222",
      available: true,
      reason: null,
      years: [2022, 2023, 2024],
      journals: ["Journal of Membrane Science"],
      sites: ["elsevier"],
    });
  };

  setApiUserId("alice");
  const result = await structuredExtractionApi.getCollectionFilterOptions("22222222-2222-4222-8222-222222222222");
  clearApiUserId();

  assert.equal(requestedUrl, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/collection/filter-options");
  assert.equal(requestHeaders["X-User-Id"], "alice");
  assert.deepEqual(result, {
    taskId: "22222222-2222-4222-8222-222222222222",
    available: true,
    reason: null,
    years: [2022, 2023, 2024],
    journals: ["Journal of Membrane Science"],
    sites: ["elsevier"],
  });
});

test("structuredExtractionApi collection decision and freeze preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "freeze requires at least one included candidate" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.freezeCollection("22222222-2222-4222-8222-222222222222"), /requires at least one included/);
  await assert.rejects(
    structuredExtractionApi.setCandidateDecision("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", { decision: "exclude", exclude_reason: "other" }),
    /requires at least one included/
  );
});

test("structuredExtractionApi candidate decision can restore a row to candidate", async () => {
  let requestBody = null;
  globalThis.fetch = async (_url, options = {}) => {
    requestBody = JSON.parse(options.body);
    return jsonResponse({ candidate_id: "33333333-3333-4333-8333-333333333333", task_id: "22222222-2222-4222-8222-222222222222", paper_id: "p1", user_decision: "candidate" });
  };

  const candidate = await structuredExtractionApi.setCandidateDecision("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", { decision: "candidate" });

  assert.deepEqual(requestBody, { decision: "candidate" });
  assert.equal(candidate.userDecision, "candidate");
});

test("structuredExtractionApi schema draft saves contract and normalizes schema models", async () => {
  let requestedUrl = null;
  let requestBody = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestBody = JSON.parse(options.body);
    requestHeaders = options.headers || {};
    return jsonResponse({
      task_id: "22222222-2222-4222-8222-222222222222",
      schema_version: null,
      base_collection_version: "col_v1",
      schema_mode: "nested_material",
      record_schema: {
        record_type: "membrane_sample",
        record_unit: "sample_level",
        primary_entity: "membrane",
        one_paper_may_have_multiple_records: true,
        record_identity_fields: ["paper_id", "membrane_name"],
        deduplication_keys: ["paper_id", "membrane_name"],
        parent_record_type: null,
      },
      field_tree: [{ key: "material_name", label: "材料名称", type: "string", required: true, evidence_required: true, order: 1 }],
      field_groups: [{ group_key: "material_identity", label: "材料身份", description: "", order: 1 }],
      fields: [
        {
          key: "membrane_name",
          label: "膜名称",
          type: "string",
          group_key: "material_identity",
          description: "",
          extraction_instruction: "",
          required: true,
          missing_policy: "missing",
          evidence_required: true,
          allowed_values: [],
          unit: "",
          validation_rule: "",
          example_values: [],
          notes: "",
          order: 1,
        },
      ],
      status: "draft",
      validation_errors: [],
      created_at: 10,
      updated_at: 11,
      frozen_at: null,
    });
  };

  const payload = {
    schemaMode: "nested_material",
    recordSchema: { recordType: "membrane_sample", recordUnit: "sample_level" },
    fieldTree: [{ key: "material_name", label: "材料名称", type: "string", required: true, evidenceRequired: true }],
    fieldGroups: [{ groupKey: "material_identity", label: "材料身份" }],
    fields: [{ key: "membrane_name", label: "膜名称", type: "string", groupKey: "material_identity" }],
  };
  setApiUserId("alice");
  const draft = await structuredExtractionApi.saveSchemaDraft("22222222-2222-4222-8222-222222222222", payload);
  clearApiUserId();

  assert.equal(requestedUrl, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/schema/draft");
  assert.deepEqual(requestBody, {
    schema_mode: "nested_material",
    record_schema: { record_type: "membrane_sample", record_unit: "sample_level" },
    field_tree: [{ key: "material_name", label: "材料名称", type: "string", required: true, evidence_required: true }],
    field_groups: [{ group_key: "material_identity", label: "材料身份" }],
    fields: [{ key: "membrane_name", label: "膜名称", type: "string", group_key: "material_identity" }],
  });
  assert.equal(requestHeaders["X-User-Id"], "alice");
  assert.equal(draft.taskId, "22222222-2222-4222-8222-222222222222");
  assert.equal(draft.schemaVersion, null);
  assert.equal(draft.baseCollectionVersion, "col_v1");
  assert.equal(draft.schemaMode, "nested_material");
  assert.equal(draft.recordSchema.recordType, "membrane_sample");
  assert.equal(draft.fieldTree[0].evidenceRequired, true);
  assert.equal(draft.recordSchema.onePaperMayHaveMultipleRecords, true);
  assert.equal(draft.fieldGroups[0].groupKey, "material_identity");
  assert.equal(draft.fields[0].groupKey, "material_identity");
  assert.equal(draft.fields[0].evidenceRequired, true);
  assert.equal(draft.createdAt, 10);
  assert.equal(draft.frozenAt, null);
});

test("structuredExtractionApi schema freeze preserves backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "schema_fields_required" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.freezeSchema("22222222-2222-4222-8222-222222222222"), /schema_fields_required/);
});

test("structuredExtractionApi prompt contract compile sends contract and normalizes response", async () => {
  let requestedUrl = null;
  let requestBody = null;
  let requestHeaders = null;
  globalThis.fetch = async (url, options = {}) => {
    requestedUrl = url;
    requestBody = JSON.parse(options.body);
    requestHeaders = options.headers || {};
    return jsonResponse({
      prompt_contract_version: "pc_v1",
      task_id: "22222222-2222-4222-8222-222222222222",
      schema_version: "schema_v1",
      collection_version: "col_v1",
      schema_mode: "nested_material",
      record_contract: { record_unit: "sample_level" },
      field_contracts: [{ key: "water_flux", evidence_required: true }],
      schema_tree_contract: [{ key: "composition", type: "object" }],
      section_contracts: [{ section_key: "composition", node: { key: "composition" } }],
      output_json_contract: { record_unit: "sample_level" },
      extraction_rules: ["Do not guess"],
      created_at: 10,
    });
  };

  setApiUserId("alice");
  const contract = await structuredExtractionApi.compilePromptContract("22222222-2222-4222-8222-222222222222", { schemaVersion: "schema_v1", collectionVersion: "col_v1" });
  clearApiUserId();

  assert.equal(requestedUrl, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/prompt-contract/compile");
  assert.deepEqual(requestBody, { schema_version: "schema_v1", collection_version: "col_v1" });
  assert.equal(requestHeaders["X-User-Id"], "alice");
  assert.equal(contract.promptContractVersion, "pc_v1");
  assert.equal(contract.schemaMode, "nested_material");
  assert.equal(contract.schemaTreeContract[0].key, "composition");
  assert.equal(contract.sectionContracts[0].sectionKey, "composition");
  assert.equal(contract.fieldContracts[0].evidenceRequired, true);
  assert.equal(contract.outputJsonContract.recordUnit, "sample_level");
});

test("structuredExtractionApi evidence packet build normalizes versions and items", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/build")) {
      return jsonResponse({
        packet_version: "ep_v1",
        task_id: "22222222-2222-4222-8222-222222222222",
        collection_version: "col_v1",
        schema_version: "schema_v1",
        prompt_contract_version: "pc_v1",
        paper_count: 2,
        field_group_count: 2,
        item_count: 4,
        created_at: 20,
        warnings: [{ paper_id: "p1", warning: "metadata_fallback_used" }],
      });
    }
    return jsonResponse({
      task_id: "22222222-2222-4222-8222-222222222222",
      packet_version: "ep_v1",
      items: [
        {
          packet_item_id: "77777777-7777-4777-8777-777777777777",
          packet_version: "ep_v1",
          paper_id: "p1",
          field_group: "performance",
          field_keys: ["water_flux"],
          construction_query: "performance water_flux",
          retrieved_sections: [],
          chunks: [{ evidence_id: "E1", source_path: "a.md", score: 0.5 }],
          tables: [],
          figures: [],
          source_paths: ["a.md"],
          warnings: [],
        },
      ],
    });
  };

  setApiUserId("alice");
  const packet = await structuredExtractionApi.buildEvidencePacket("22222222-2222-4222-8222-222222222222", { promptContractVersion: "pc_v1", maxChunksPerGroup: 2 });
  const items = await structuredExtractionApi.listEvidencePacketItems("22222222-2222-4222-8222-222222222222", "ep_v1");
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/evidence-packets/build");
  assert.deepEqual(calls[0].body, { prompt_contract_version: "pc_v1", max_chunks_per_group: 2 });
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(packet.packetVersion, "ep_v1");
  assert.equal(packet.promptContractVersion, "pc_v1");
  assert.equal(packet.fieldGroupCount, 2);
  assert.equal(items.items[0].packetItemId, "77777777-7777-4777-8777-777777777777");
  assert.equal(items.items[0].fieldKeys[0], "water_flux");
});

test("structuredExtractionApi evidence packet build jobs send contracts and normalize progress", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/build-jobs") && options.method === "POST") {
      return jsonResponse({
        build_job_id: "88888888-8888-4888-8888-888888888888",
        task_id: "22222222-2222-4222-8222-222222222222",
        status: "running",
        phase: "building_items",
        collection_version: "col_v1",
        schema_version: "schema_v1",
        prompt_contract_version: "pc_v1",
        target_packet_version: "ep_v2",
        result_packet_version: null,
        paper_count: 2,
        field_group_count: 3,
        total_item_count: 6,
        processed_item_count: 2,
        warning_count: 1,
        current_paper_id: "p1",
        current_field_group: "performance",
        current_query_mode: "article_id",
        avg_chunks_per_item: 3.5,
        slow_item_count: 1,
        last_item_seconds: 4.2,
        settings: { max_chunks_per_group: 2 },
        warnings_preview: [{ paper_id: "p1", warning: "metadata_fallback_used" }],
        error: null,
        created_at: 1,
        started_at: 2,
        updated_at: 3,
        completed_at: null,
      });
    }
    if (url.endsWith("/build-jobs/88888888-8888-4888-8888-888888888888/cancel")) {
      return jsonResponse({ build_job_id: "88888888-8888-4888-8888-888888888888", task_id: "22222222-2222-4222-8222-222222222222", status: "cancelling", phase: "building_items", created_at: 1, updated_at: 4 });
    }
    if (url.endsWith("/build-jobs/88888888-8888-4888-8888-888888888888")) {
      return jsonResponse({ build_job_id: "88888888-8888-4888-8888-888888888888", task_id: "22222222-2222-4222-8222-222222222222", status: "completed", phase: "completed", result_packet_version: "ep_v2", created_at: 1, updated_at: 5, completed_at: 5 });
    }
    if (url.endsWith("/build-jobs")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", jobs: [{ build_job_id: "88888888-8888-4888-8888-888888888888", task_id: "22222222-2222-4222-8222-222222222222", status: "running", phase: "building_items", created_at: 1, updated_at: 3 }] });
    }
    return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", packet_version: "ep_v2", limit: 10, offset: 20, total: 42, items: [] });
  };

  setApiUserId("alice");
  const started = await structuredExtractionApi.startEvidencePacketBuildJob("22222222-2222-4222-8222-222222222222", { promptContractVersion: "pc_v1", maxChunksPerGroup: 2 });
  const listed = await structuredExtractionApi.listEvidencePacketBuildJobs("22222222-2222-4222-8222-222222222222");
  const loaded = await structuredExtractionApi.getEvidencePacketBuildJob("22222222-2222-4222-8222-222222222222", "88888888-8888-4888-8888-888888888888");
  const cancelled = await structuredExtractionApi.cancelEvidencePacketBuildJob("22222222-2222-4222-8222-222222222222", "88888888-8888-4888-8888-888888888888");
  const items = await structuredExtractionApi.listEvidencePacketItems("22222222-2222-4222-8222-222222222222", "ep_v2", { limit: 10, offset: 20 });
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/evidence-packets/build-jobs");
  assert.deepEqual(calls[0].body, { prompt_contract_version: "pc_v1", max_chunks_per_group: 2 });
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(started.buildJobId, "88888888-8888-4888-8888-888888888888");
  assert.equal(started.targetPacketVersion, "ep_v2");
  assert.equal(started.processedItemCount, 2);
  assert.equal(started.currentQueryMode, "article_id");
  assert.equal(started.avgChunksPerItem, 3.5);
  assert.equal(started.slowItemCount, 1);
  assert.equal(started.lastItemSeconds, 4.2);
  assert.equal(started.warningsPreview[0].paperId, "p1");
  assert.equal(listed.jobs[0].buildJobId, "88888888-8888-4888-8888-888888888888");
  assert.equal(loaded.resultPacketVersion, "ep_v2");
  assert.equal(cancelled.status, "cancelling");
  assert.equal(calls[4].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/evidence-packets/versions/ep_v2/items?limit=10&offset=20");
  assert.equal(items.total, 42);
});

test("structuredExtractionApi preparation APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "prompt_contract_required" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.buildEvidencePacket("22222222-2222-4222-8222-222222222222"), /prompt_contract_required/);
  await assert.rejects(structuredExtractionApi.startEvidencePacketBuildJob("22222222-2222-4222-8222-222222222222"), /prompt_contract_required/);
});

test("schema target presets generate material-level identity and detect conflicts", () => {
  const draft = { recordSchema: {}, fields: [], fieldGroups: [] };
  const material = applySchemaPreset(draft, "material");

  assert.equal(material.recordSchema.recordType, "material_record");
  assert.equal(material.recordSchema.recordUnit, "material_level");
  assert.equal(material.recordSchema.primaryEntity, "material");
  assert.deepEqual(material.recordSchema.recordIdentityFields, ["paper_id", "material_name"]);
  assert.deepEqual(material.recordSchema.deduplicationKeys, ["paper_id", "material_name"]);
  assert.equal(material.recordSchema.onePaperMayHaveMultipleRecords, true);

  const conflicts = schemaConflictMessages({
    recordType: "paper_record",
    recordUnit: "material_level",
    primaryEntity: "paper",
    recordIdentityFields: ["paper_id"],
    deduplicationKeys: ["paper_id"],
    onePaperMayHaveMultipleRecords: false,
  });
  assert.equal(conflicts.length, 4);
  assert.match(conflicts.join(" "), /不能只使用 paper_id/);
});

test("structuredExtractionApi extraction run APIs send contracts and normalize responses", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/runs") && options.method === "POST") {
      return jsonResponse({
        run_id: "44444444-4444-4444-8444-444444444444",
        task_id: "22222222-2222-4222-8222-222222222222",
        status: "queued",
        collection_version: "col_v1",
        schema_version: "schema_v1",
        prompt_contract_version: "pc_v1",
        packet_version: "ep_v1",
        model_snapshot: { provider: "fake", model: "strong", strong: true },
        stats: { packet_item_count: 2, completed_item_count: 0, failed_item_count: 0, record_count: 0 },
        error: null,
        created_at: 1,
        started_at: null,
        completed_at: null,
      });
    }
    if (url.endsWith("/runs")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", runs: [{ run_id: "44444444-4444-4444-8444-444444444444", task_id: "22222222-2222-4222-8222-222222222222", status: "completed", stats: { record_count: 1 } }] });
    }
    if (url.endsWith("/items")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        items: [{ run_item_id: "55555555-5555-4555-8555-555555555555", packet_item_id: "77777777-7777-4777-8777-777777777777", paper_id: "p1", field_group: "performance", status: "completed", error: null }],
      });
    }
    if (url.endsWith("/records")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        records: [{ record_id: "66666666-6666-4666-8666-666666666666", run_id: "44444444-4444-4444-8444-444444444444", paper_id: "p1", record_identity: { membrane_name: "PES-ZW" }, fields: { water_flux: { raw_value: "120 LMH" } }, source_packet_item_ids: ["77777777-7777-4777-8777-777777777777"], quality_flags: [], created_at: 2 }],
      });
    }
    if (url.endsWith("/cancel")) {
      return jsonResponse({ run_id: "44444444-4444-4444-8444-444444444444", task_id: "22222222-2222-4222-8222-222222222222", status: "cancelling", stats: {} });
    }
    return jsonResponse({ run_id: "44444444-4444-4444-8444-444444444444", task_id: "22222222-2222-4222-8222-222222222222", status: "completed", model_snapshot: { provider: "fake" }, stats: { record_count: 1 } });
  };

  setApiUserId("alice");
  const run = await structuredExtractionApi.startExtractionRun("22222222-2222-4222-8222-222222222222", { packetVersion: "ep_v1" });
  const runs = await structuredExtractionApi.listExtractionRuns("22222222-2222-4222-8222-222222222222");
  const detail = await structuredExtractionApi.getExtractionRun("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const items = await structuredExtractionApi.listExtractionRunItems("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const records = await structuredExtractionApi.listExtractionRunRecords("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const cancelled = await structuredExtractionApi.cancelExtractionRun("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/runs");
  assert.deepEqual(calls[0].body, { packet_version: "ep_v1" });
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(run.runId, "44444444-4444-4444-8444-444444444444");
  assert.equal(run.packetVersion, "ep_v1");
  assert.equal(run.modelSnapshot.strong, true);
  assert.equal(run.stats.packetItemCount, 2);
  assert.equal(runs.runs[0].recordCount ?? runs.runs[0].stats.recordCount, 1);
  assert.equal(detail.status, "completed");
  assert.equal(items.items[0].runItemId, "55555555-5555-4555-8555-555555555555");
  assert.equal(items.items[0].fieldGroup, "performance");
  assert.equal(records.records[0].recordIdentity.membraneName, "PES-ZW");
  assert.equal(records.records[0].fields.waterFlux.rawValue, "120 LMH");
  assert.equal(cancelled.status, "cancelling");
});

test("structuredExtractionApi extraction run APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "evidence_packet_not_found" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.startExtractionRun("22222222-2222-4222-8222-222222222222", { packetVersion: "missing" }), /evidence_packet_not_found/);
});

test("structuredExtractionApi run recovery APIs send contracts and normalize responses", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/recovery")) {
      return jsonResponse({
        run_id: "44444444-4444-4444-8444-444444444444",
        task_id: "22222222-2222-4222-8222-222222222222",
        resumable: true,
        status: "interrupted",
        completed_item_count: 2,
        failed_item_count: 1,
        interrupted_item_count: 1,
        queued_item_count: 0,
        remaining_item_count: 2,
        record_count: 1,
        blockers: [],
        last_error: { reason: "process_restarted" },
      });
    }
    return jsonResponse({
      run_id: "44444444-4444-4444-8444-444444444444",
      task_id: "22222222-2222-4222-8222-222222222222",
      status: "queued",
      resume_count: 1,
      recovery: { reason: "manual_resume" },
      stats: { packet_item_count: 4 },
    });
  };

  setApiUserId("alice");
  const recovery = await structuredExtractionApi.getExtractionRunRecovery("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const resumed = await structuredExtractionApi.resumeExtractionRun("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444", { retryFailedItems: true, reason: "manual_resume" });
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/runs/44444444-4444-4444-8444-444444444444/recovery");
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(calls[1].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/runs/44444444-4444-4444-8444-444444444444/resume");
  assert.deepEqual(calls[1].body, { retry_failed_items: true, reason: "manual_resume" });
  assert.equal(recovery.runId, "44444444-4444-4444-8444-444444444444");
  assert.equal(recovery.resumable, true);
  assert.equal(recovery.interruptedItemCount, 1);
  assert.equal(recovery.remainingItemCount, 2);
  assert.equal(recovery.lastError.reason, "process_restarted");
  assert.equal(resumed.runId, "44444444-4444-4444-8444-444444444444");
  assert.equal(resumed.resumeCount, 1);
});

test("structuredExtractionApi run recovery APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "run_locked_by_review_or_export" }, { status: 409 });

  await assert.rejects(structuredExtractionApi.resumeExtractionRun("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444"), /run_locked_by_review_or_export/);
});

test("structuredExtractionApi review APIs send contracts and normalize responses", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/review/runs")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", runs: [{ run_id: "44444444-4444-4444-8444-444444444444", status: "completed", stats: { record_count: 1 } }] });
    }
    if (url.includes("/review/table")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        total: 1,
        limit: 100,
        offset: 0,
        field_keys: ["water_flux"],
        rows: [
          {
            record_id: "66666666-6666-4666-8666-666666666666",
            run_id: "44444444-4444-4444-8444-444444444444",
            paper_id: "p1",
            paper: { title: "Paper", year: 2024 },
            record_identity: { membrane_name: "PES-ZW" },
            data: { composition: { base_polymers: [{ name: "PES" }] } },
            fields: {
              water_flux: {
                field_key: "water_flux",
                label: "Water flux",
                base_value: { raw_value: "120 LMH" },
                effective_value: { raw_value: "121 LMH" },
                status: "edited",
                locked: true,
                quality_flags: ["no_evidence"],
                review_priority: "medium",
                last_event_id: 2,
              },
            },
            review_priority: "medium",
            review_status: "partially_reviewed",
          },
        ],
      });
    }
    if (url.endsWith("/events") && options.method !== "POST") {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", record_id: "66666666-6666-4666-8666-666666666666", events: [{ event_id: 2, event_type: "edit_field", field_key: "water_flux", new_value: { raw_value: "121 LMH" } }] });
    }
    if (url.endsWith("/bulk")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", updated: 1, rows: [] });
    }
    if (url.endsWith("/revert")) {
      return jsonResponse({ record_id: "66666666-6666-4666-8666-666666666666", fields: { water_flux: { status: "accepted" } } });
    }
    return jsonResponse({ record_id: "66666666-6666-4666-8666-666666666666", fields: { water_flux: { field_key: "water_flux", status: "edited", effective_value: { raw_value: "121 LMH" } } } });
  };

  setApiUserId("alice");
  const runs = await structuredExtractionApi.listReviewRuns("22222222-2222-4222-8222-222222222222");
  const table = await structuredExtractionApi.listReviewTable("22222222-2222-4222-8222-222222222222", { runId: "44444444-4444-4444-8444-444444444444", fieldKey: "water_flux", missing: true });
  const detail = await structuredExtractionApi.getReviewRecord("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "44444444-4444-4444-8444-444444444444");
  const events = await structuredExtractionApi.listReviewEvents("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666");
  const edited = await structuredExtractionApi.editReviewField("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "water_flux", { value: { rawValue: "121 LMH" }, reason: "fix", locked: true });
  await structuredExtractionApi.acceptReviewField("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "water_flux", { reason: "ok" });
  await structuredExtractionApi.rejectReviewField("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "water_flux", { reason: "bad" });
  await structuredExtractionApi.lockReviewField("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "water_flux", { reason: "manual" });
  await structuredExtractionApi.unlockReviewField("22222222-2222-4222-8222-222222222222", "66666666-6666-4666-8666-666666666666", "water_flux", { reason: "manual" });
  await structuredExtractionApi.revertReviewEvent("22222222-2222-4222-8222-222222222222", 2);
  await structuredExtractionApi.bulkReviewAction("22222222-2222-4222-8222-222222222222", { items: [{ recordId: "66666666-6666-4666-8666-666666666666", fieldKey: "water_flux" }], action: "accept_field", reason: "batch" });
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/review/runs");
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(calls[1].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/review/table?run_id=44444444-4444-4444-8444-444444444444&field_key=water_flux&missing=true");
  assert.equal(runs.runs[0].runId, "44444444-4444-4444-8444-444444444444");
  assert.equal(table.rows[0].recordIdentity.membraneName, "PES-ZW");
  assert.equal(table.rows[0].data.composition.basePolymers[0].name, "PES");
  assert.equal(table.rows[0].fields.waterFlux.effectiveValue.rawValue, "121 LMH");
  assert.equal(detail.fields.waterFlux.status, "edited");
  assert.equal(events.events[0].eventId, 2);
  assert.deepEqual(calls[4].body, { value: { raw_value: "121 LMH" }, reason: "fix", locked: true });
  assert.equal(edited.fields.waterFlux.effectiveValue.rawValue, "121 LMH");
  assert.deepEqual(calls[10].body, { items: [{ record_id: "66666666-6666-4666-8666-666666666666", field_key: "water_flux" }], action: "accept_field", reason: "batch" });
});

test("structuredExtractionApi review APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "review_run_required" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.listReviewTable("22222222-2222-4222-8222-222222222222"), /review_run_required/);
});

test("structuredExtractionApi multimodal review APIs send contracts and normalize responses", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.includes("/review/summary")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        record_count: 2,
        risk_counts: { low: 1, high: 1 },
        coverage_counts: { reported: 3, not_reported: 2 },
        pending_suggestion_count: 1,
        bulk_accept_eligible_count: 1,
        multimodal_ready: true,
      });
    }
    if (url.includes("/review/queue")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        queue: "multimodal_pending",
        total: 1,
        rows: [
          {
            record_id: "66666666-6666-4666-8666-666666666666",
            run_id: "44444444-4444-4444-8444-444444444444",
            paper_id: "p1",
            record_identity: { material_name: "PES-ZW" },
            risk_level: "medium",
            coverage: { performance: "reported" },
            issues: [],
            suggestions: [{ suggestion_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", field_key: "performance", action: "suggest_edit", status: "pending", provenance: { source: "multimodal" } }],
          },
        ],
      });
    }
    if (url.endsWith("/multimodal-jobs") && options.method === "POST") {
      return jsonResponse({
        job_id: "99999999-9999-4999-8999-999999999999",
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        status: "running",
        scan_mode: "related_pages_assets",
        processed_item_count: 1,
        total_item_count: 3,
        suggestion_count: 1,
        issue_count: 0,
        suggestions_preview: [{ suggestion_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", field_key: "performance" }],
      });
    }
    if (url.endsWith("/multimodal-jobs/99999999-9999-4999-8999-999999999999/cancel")) {
      return jsonResponse({ job_id: "99999999-9999-4999-8999-999999999999", task_id: "22222222-2222-4222-8222-222222222222", run_id: "44444444-4444-4444-8444-444444444444", status: "cancelled", scan_mode: "related_pages_assets" });
    }
    if (url.endsWith("/multimodal-jobs/99999999-9999-4999-8999-999999999999")) {
      return jsonResponse({
        job_id: "99999999-9999-4999-8999-999999999999",
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        status: "completed",
        scan_mode: "related_pages_assets",
        processed_item_count: 3,
        total_item_count: 3,
        suggestions: [{ suggestion_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", field_key: "performance", provenance: { source: "multimodal", job_id: "99999999-9999-4999-8999-999999999999" } }],
      });
    }
    if (url.endsWith("/multimodal-jobs")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", run_id: "44444444-4444-4444-8444-444444444444", jobs: [{ job_id: "99999999-9999-4999-8999-999999999999", status: "completed", scan_mode: "related_pages_assets" }] });
    }
    if (url.endsWith("/suggestions/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/accept")) {
      return jsonResponse({
        suggestion: { suggestion_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status: "accepted", field_key: "performance" },
        record: { record_id: "66666666-6666-4666-8666-666666666666", fields: { performance: { status: "multimodal_pending", provenance: { source: "multimodal" } } } },
      });
    }
    if (url.endsWith("/suggestions/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/reject")) {
      return jsonResponse({ suggestion: { suggestion_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status: "rejected" } });
    }
    if (url.endsWith("/suggestions/bulk")) {
      return jsonResponse({ task_id: "22222222-2222-4222-8222-222222222222", updated: 1, suggestions: [{ suggestion_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", status: "accepted" }] });
    }
    return jsonResponse({});
  };

  setApiUserId("alice");
  const summary = await structuredExtractionApi.getReviewSummary("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const queue = await structuredExtractionApi.listReviewQueue("22222222-2222-4222-8222-222222222222", { runId: "44444444-4444-4444-8444-444444444444", queue: "multimodal_pending" });
  const started = await structuredExtractionApi.startMultimodalReviewJob("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444", { scanMode: "related_pages_assets", reason: "run check" });
  const jobs = await structuredExtractionApi.listMultimodalReviewJobs("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const job = await structuredExtractionApi.getMultimodalReviewJob("22222222-2222-4222-8222-222222222222", "99999999-9999-4999-8999-999999999999");
  const cancelled = await structuredExtractionApi.cancelMultimodalReviewJob("22222222-2222-4222-8222-222222222222", "99999999-9999-4999-8999-999999999999");
  const accepted = await structuredExtractionApi.acceptReviewSuggestion("22222222-2222-4222-8222-222222222222", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", { reason: "ok" });
  const rejected = await structuredExtractionApi.rejectReviewSuggestion("22222222-2222-4222-8222-222222222222", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", { reason: "bad" });
  const bulk = await structuredExtractionApi.bulkReviewSuggestions("22222222-2222-4222-8222-222222222222", { suggestionIds: ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"], action: "accept", reason: "batch" });
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/review/summary?run_id=44444444-4444-4444-8444-444444444444");
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(calls[1].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/review/queue?run_id=44444444-4444-4444-8444-444444444444&queue=multimodal_pending");
  assert.equal(calls[2].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/review/runs/44444444-4444-4444-8444-444444444444/multimodal-jobs");
  assert.deepEqual(calls[2].body, { scan_mode: "related_pages_assets", reason: "run check" });
  assert.equal(summary.pendingSuggestionCount, 1);
  assert.equal(queue.rows[0].suggestions[0].suggestionId, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  assert.equal(started.scanMode, "related_pages_assets");
  assert.equal(jobs.jobs[0].jobId, "99999999-9999-4999-8999-999999999999");
  assert.equal(job.suggestions[0].provenance.jobId, "99999999-9999-4999-8999-999999999999");
  assert.equal(cancelled.status, "cancelled");
  assert.equal(accepted.record.fields.performance.status, "multimodal_pending");
  assert.equal(rejected.suggestion.status, "rejected");
  assert.deepEqual(calls[8].body, { suggestion_ids: ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"], action: "accept", reason: "batch" });
  assert.equal(bulk.updated, 1);
});

test("structuredExtractionApi multimodal review APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "multimodal_model_not_configured" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.startMultimodalReviewJob("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444"), /multimodal_model_not_configured/);
});

test("structuredExtractionApi export APIs send contracts and normalize responses", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options, body: options.body ? JSON.parse(options.body) : null, headers: options.headers || {} });
    if (url.endsWith("/exports/preview?run_id=44444444-4444-4444-8444-444444444444")) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        record_count: 1,
        field_count: 2,
        top_level_section_count: 6,
        leaf_path_count: 12,
        review_status_counts: { unreviewed: 1 },
        warnings: ["unreviewed_fields_present"],
      });
    }
    if (url.endsWith("/exports") && !options.method) {
      return jsonResponse({
        task_id: "22222222-2222-4222-8222-222222222222",
        exports: [
          {
            export_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            task_id: "22222222-2222-4222-8222-222222222222",
            run_id: "44444444-4444-4444-8444-444444444444",
            collection_version: "col_v1",
            schema_version: "schema_v1",
            record_count: 1,
            field_count: 2,
            top_level_section_count: 6,
            leaf_path_count: 12,
            formats: ["csv", "json"],
            files: { csv: "records.csv" },
            review_status_counts: { unreviewed: 1 },
            warnings: [],
            created_at: 10,
          },
        ],
      });
    }
    if (url.endsWith("/exports") && options.method === "POST") {
      return jsonResponse({
        export_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        collection_version: "col_v1",
        schema_version: "schema_v1",
        record_count: 1,
        field_count: 2,
        top_level_section_count: 6,
        leaf_path_count: 12,
        formats: ["csv", "json", "xlsx", "markdown"],
        files: { json: "records.json" },
        review_status_counts: { reviewed: 1 },
        warnings: [],
        created_at: 11,
      });
    }
    if (url.endsWith("/exports/cccccccc-cccc-4ccc-8ccc-cccccccccccc")) {
      return jsonResponse({
        export_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        task_id: "22222222-2222-4222-8222-222222222222",
        run_id: "44444444-4444-4444-8444-444444444444",
        collection_version: "col_v1",
        schema_version: "schema_v1",
        record_count: 1,
        field_count: 2,
        top_level_section_count: 6,
        leaf_path_count: 12,
        formats: ["csv"],
        files: {},
        review_status_counts: {},
        warnings: [],
        created_at: 10,
      });
    }
    return new Response("csv", { status: 200, headers: { "Content-Type": "text/csv" } });
  };

  setApiUserId("alice");
  const preview = await structuredExtractionApi.previewExport("22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444");
  const list = await structuredExtractionApi.listExports("22222222-2222-4222-8222-222222222222");
  const created = await structuredExtractionApi.createExport("22222222-2222-4222-8222-222222222222", {
    runId: "44444444-4444-4444-8444-444444444444",
    formats: ["csv", "json", "xlsx", "markdown"],
    includeRejected: false,
    includeBaseValues: true,
    includeReviewMetadata: true,
  });
  const detail = await structuredExtractionApi.getExport("22222222-2222-4222-8222-222222222222", "cccccccc-cccc-4ccc-8ccc-cccccccccccc");
  const download = await structuredExtractionApi.downloadExport("22222222-2222-4222-8222-222222222222", "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "csv");
  clearApiUserId();

  assert.equal(calls[0].url, "/api/structured-extraction/tasks/22222222-2222-4222-8222-222222222222/exports/preview?run_id=44444444-4444-4444-8444-444444444444");
  assert.equal(calls[0].headers["X-User-Id"], "alice");
  assert.equal(preview.recordCount, 1);
  assert.equal(preview.topLevelSectionCount, 6);
  assert.equal(preview.leafPathCount, 12);
  assert.equal(preview.reviewStatusCounts.unreviewed, 1);
  assert.equal(list.exports[0].exportId, "cccccccc-cccc-4ccc-8ccc-cccccccccccc");
  assert.equal(calls[2].body.run_id, "44444444-4444-4444-8444-444444444444");
  assert.deepEqual(calls[2].body.formats, ["csv", "json", "xlsx", "markdown"]);
  assert.equal(calls[2].body.include_base_values, true);
  assert.equal(created.exportId, "dddddddd-dddd-4ddd-8ddd-dddddddddddd");
  assert.equal(detail.exportId, "cccccccc-cccc-4ccc-8ccc-cccccccccccc");
  assert.equal(await download.text(), "csv");
});

test("structuredExtractionApi export APIs preserve backend error detail", async () => {
  globalThis.fetch = async () => jsonResponse({ detail: "export failed" }, { status: 400 });

  await assert.rejects(structuredExtractionApi.createExport("22222222-2222-4222-8222-222222222222", { formats: ["csv"] }), /export failed/);
});

test("streamWorkflow surfaces backend error detail", async () => {
  const events = [];
  let requestHeaders = null;
  globalThis.fetch = async (_url, options = {}) => {
    requestHeaders = options.headers || {};
    return jsonResponse({ detail: "workflow stream unavailable" }, { status: 409 });
  };

  setApiUserId("alice");
  await streamWorkflow("wf1", (event) => events.push(event));
  clearApiUserId();

  assert.deepEqual(events, [
    { type: "error", message: "workflow stream unavailable" },
    { type: "done" },
  ]);
  assert.equal(requestHeaders["X-User-Id"], "alice");
});
