import test from "node:test";
import assert from "node:assert/strict";

function installWindowStub() {
  const data = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (key) => data.get(key) ?? null,
      setItem: (key, value) => data.set(key, String(value)),
      removeItem: (key) => data.delete(key),
    },
    prompt: () => null,
    confirm: () => false,
  };
}

test("literature search research modes map to existing chat role and depth options", async () => {
  installWindowStub();
  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  useAppStore.getState().setChatResearchMode("quick");
  assert.equal(useAppStore.getState().chatRole, "general");
  assert.equal(useAppStore.getState().chatAnswerMode, "quick");

  useAppStore.getState().setChatResearchMode("evidence");
  assert.equal(useAppStore.getState().chatRole, "retrieval");
  assert.equal(useAppStore.getState().chatAnswerMode, "quick");

  useAppStore.getState().setChatResearchMode("deep");
  assert.equal(useAppStore.getState().chatRole, "analysis");
  assert.equal(useAppStore.getState().chatAnswerMode, "deep");
});

test("literature search preview actions switch between answer and detail modes", async () => {
  installWindowStub();
  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  useAppStore.getState().selectLiteratureEvidence("E1");
  assert.equal(useAppStore.getState().literatureSearch.preview.mode, "evidence");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedEvidenceId, "E1");

  useAppStore.getState().selectLiteraturePaper("P1");
  assert.equal(useAppStore.getState().literatureSearch.preview.mode, "paper");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedPaperId, "P1");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedEvidenceId, null);

  useAppStore.getState().selectLiteratureAudit("coverage");
  assert.equal(useAppStore.getState().literatureSearch.preview.mode, "audit");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedAuditId, "coverage");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedPaperId, null);

  useAppStore.getState().selectLiteratureAnswer();
  assert.equal(useAppStore.getState().literatureSearch.preview.mode, "answer");
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedEvidenceId, null);
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedPaperId, null);
  assert.equal(useAppStore.getState().literatureSearch.preview.selectedAuditId, null);
});

test("auth bootstrap shows login required when me returns 401", async () => {
  installWindowStub();
  globalThis.fetch = async (url) => {
    if (url === "/api/auth/me") {
      return new Response(JSON.stringify({ detail: "not authenticated" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?auth401=${Date.now()}`);
  await useAppStore.getState().bootstrapAuth();

  assert.equal(useAppStore.getState().auth.status, "login_required");
  assert.equal(useAppStore.getState().currentUser, null);
  assert.equal(useAppStore.getState().modulesLoaded, true);
});

test("auth bootstrap loads modules when user is authenticated", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", credentials: options.credentials });
    if (url === "/api/auth/me") {
      return new Response(
        JSON.stringify({ user_id: "u1", email: "alice@example.com", display_name: "Alice", role: "admin", status: "active" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/modules") {
      return new Response(JSON.stringify([{ id: "literature_search", name: "文献检索分析", status: "active" }]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/settings/effective") {
      return new Response(JSON.stringify({ "general.default_module": { value: "literature_search" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/corpus/dashboard") {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions?module_id=literature_search&include_archived=false") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions" && options.method === "POST") {
      return new Response(
        JSON.stringify({
          session_id: "s_boot",
          module_id: "literature_search",
          user_id: "u1",
          title: "新对话",
          status: "active",
          tags: [],
          favorite: false,
          pinned: false,
          archived: false,
          deleted_at: null,
          created_at: 1,
          updated_at: 1,
          last_message_at: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?auth200=${Date.now()}`);
  await useAppStore.getState().bootstrapAuth();

  assert.equal(useAppStore.getState().auth.status, "authenticated");
  assert.equal(useAppStore.getState().currentUser.email, "alice@example.com");
  assert.ok(calls.some((call) => call.url === "/api/modules" && call.credentials === "include"));
  assert.equal(useAppStore.getState().activeModuleId, "literature_search");
});

test("regular user settings load avoids admin diagnostics and readiness endpoints", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url === "/api/settings") {
      return new Response(JSON.stringify({ general: {}, models: {}, retrieval: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/settings/effective") {
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?settingsUser=${Date.now()}`);
  useAppStore.setState({ currentUser: { user_id: "u1", role: "user", status: "active" } });
  await useAppStore.getState().loadSettings();

  assert.deepEqual(calls, ["/api/settings", "/api/settings/effective"]);
  assert.equal(useAppStore.getState().settings.diagnostics, null);
  assert.equal(useAppStore.getState().settings.readiness, null);
});

test("admin settings load includes diagnostics and readiness endpoints", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url === "/api/settings") {
      return new Response(JSON.stringify({ general: {}, models: {}, retrieval: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/settings/effective") {
      return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/settings/diagnostics") {
      return new Response(JSON.stringify({ checks: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/settings/readiness") {
      return new Response(JSON.stringify({ ready: true }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?settingsAdmin=${Date.now()}`);
  useAppStore.setState({ currentUser: { user_id: "admin-1", role: "admin", status: "active" } });
  await useAppStore.getState().loadSettings();

  assert.ok(calls.includes("/api/settings/diagnostics"));
  assert.ok(calls.includes("/api/settings/readiness"));
  assert.deepEqual(useAppStore.getState().settings.diagnostics, { checks: [] });
  assert.deepEqual(useAppStore.getState().settings.readiness, { ready: true });
});

test("selectModule opens an auto-created empty literature session without requiring detail hydration", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET" });
    if (url === "/api/sessions?module_id=literature_search&include_archived=false") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions" && options.method === "POST") {
      return new Response(
        JSON.stringify({
          session_id: "s_new",
          module_id: "literature_search",
          user_id: "local_user",
          title: "新对话",
          status: "active",
          tags: [],
          favorite: false,
          pinned: false,
          archived: false,
          deleted_at: null,
          created_at: 1,
          updated_at: 1,
          last_message_at: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (String(url).startsWith("/api/sessions/s_new/")) {
      return new Response(JSON.stringify({ detail: "detail unavailable" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await useAppStore.getState().selectModule("literature_search");

  assert.equal(useAppStore.getState().appError, null);
  assert.equal(useAppStore.getState().activeModuleId, "literature_search");
  assert.equal(useAppStore.getState().activeSessionByModule.literature_search, "s_new");
  assert.equal(useAppStore.getState().sessionsById.s_new.messages.length, 0);
  assert.deepEqual(calls.map((call) => [call.method, call.url]), [
    ["GET", "/api/sessions?module_id=literature_search&include_archived=false"],
    ["POST", "/api/sessions"],
  ]);
});

test("selectModule recovers from a stale remembered session detail by opening the next available session", async () => {
  installWindowStub();
  window.localStorage.setItem("activeSession:literature_search", "s_stale");
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET" });
    if (url === "/api/sessions?module_id=literature_search&include_archived=false") {
      return new Response(
        JSON.stringify([
          {
            session_id: "s_stale",
            module_id: "literature_search",
            user_id: "local_user",
            title: "过期会话",
            status: "active",
            tags: [],
            favorite: false,
            pinned: false,
            archived: false,
            deleted_at: null,
            created_at: 1,
            updated_at: 3,
            last_message_at: null,
          },
          {
            session_id: "s_good",
            module_id: "literature_search",
            user_id: "local_user",
            title: "可用会话",
            status: "active",
            tags: [],
            favorite: false,
            pinned: false,
            archived: false,
            deleted_at: null,
            created_at: 2,
            updated_at: 2,
            last_message_at: null,
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (String(url).startsWith("/api/sessions/s_stale/")) {
      return new Response(JSON.stringify({ detail: "session not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/sessions/s_good/messages") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions/s_good/context") {
      return new Response(
        JSON.stringify({
          session_id: "s_good",
          recent_messages: [],
          recent_search_results: [],
          recent_evidence: [],
          linked_artifacts: [],
          active_jobs: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/sessions/s_good/artifacts" || url === "/api/sessions/s_good/jobs" || url === "/api/sessions/s_good/attachments") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions/s_good/research-state") {
      return new Response(JSON.stringify(null), { status: 404, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await useAppStore.getState().selectModule("literature_search");

  assert.equal(useAppStore.getState().appError, null);
  assert.equal(useAppStore.getState().activeSessionByModule.literature_search, "s_good");
  assert.equal(window.localStorage.getItem("activeSession:literature_search"), "s_good");
  assert.deepEqual(
    calls.filter((call) => call.url.includes("/messages")).map((call) => call.url),
    ["/api/sessions/s_stale/messages", "/api/sessions/s_good/messages"]
  );
});

test("selectModule creates a fresh session when the only remembered session is stale", async () => {
  installWindowStub();
  window.localStorage.setItem("activeSession:literature_search", "s_stale");
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET" });
    if (url === "/api/sessions?module_id=literature_search&include_archived=false") {
      return new Response(
        JSON.stringify([
          {
            session_id: "s_stale",
            module_id: "literature_search",
            user_id: "local_user",
            title: "过期会话",
            status: "active",
            tags: [],
            favorite: false,
            pinned: false,
            archived: false,
            deleted_at: null,
            created_at: 1,
            updated_at: 1,
            last_message_at: null,
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (String(url).startsWith("/api/sessions/s_stale/")) {
      return new Response(JSON.stringify({ detail: "session not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/sessions" && options.method === "POST") {
      return new Response(
        JSON.stringify({
          session_id: "s_new_after_stale",
          module_id: "literature_search",
          user_id: "local_user",
          title: "新对话",
          status: "active",
          tags: [],
          favorite: false,
          pinned: false,
          archived: false,
          deleted_at: null,
          created_at: 2,
          updated_at: 2,
          last_message_at: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await useAppStore.getState().selectModule("literature_search");

  assert.equal(useAppStore.getState().appError, null);
  assert.equal(useAppStore.getState().activeSessionByModule.literature_search, "s_new_after_stale");
  assert.equal(window.localStorage.getItem("activeSession:literature_search"), "s_new_after_stale");
  assert.ok(!useAppStore.getState().sessionsById.s_stale);
});

test("upload and delete literature attachments update the active session", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", body: options.body });
    if (url === "/api/sessions/s1/attachments" && options.method === "POST") {
      return new Response(
        JSON.stringify({
          attachment_id: "att_1",
          session_id: "s1",
          filename: "note.txt",
          content_type: "text/plain",
          status: "parsed",
          text_preview: "hello",
          char_count: 5,
          created_at: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/sessions/s1/attachments/att_1" && options.method === "DELETE") {
      return new Response(JSON.stringify({ deleted: true }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);
  useAppStore.setState({
    activeModuleId: "literature_search",
    activeSessionByModule: { literature_search: "s1" },
    sessionsById: {
      s1: { id: "s1", moduleId: "literature_search", messages: [], attachments: [], uploadingAttachments: false, attachmentError: null },
    },
  });

  await useAppStore.getState().uploadLiteratureAttachments([new File(["hello"], "note.txt", { type: "text/plain" })]);
  assert.equal(useAppStore.getState().sessionsById.s1.attachments[0].attachmentId, "att_1");
  assert.equal(useAppStore.getState().sessionsById.s1.uploadingAttachments, false);

  await useAppStore.getState().deleteLiteratureAttachment("att_1");
  assert.equal(useAppStore.getState().sessionsById.s1.attachments.length, 0);
});

test("setEvidenceStatus updates active session research state and evidence filter", async () => {
  installWindowStub();
  let requestBody = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url === "/api/sessions/s1/evidence-status" && options.method === "POST") {
      requestBody = JSON.parse(options.body);
      return new Response(
        JSON.stringify({
          session_id: "s1",
          evidence_pool: {
            total: 1,
            status_counts: { accepted: 1 },
            recent: [{ evidence_item_id: "evitem_1", evidence_id: "E1", status: "accepted", note: "关键证据" }],
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);
  useAppStore.setState({
    activeModuleId: "literature_search",
    activeSessionByModule: { literature_search: "s1" },
    sessionsById: { s1: { id: "s1", moduleId: "literature_search", messages: [], researchState: null } },
  });

  useAppStore.getState().setLiteratureEvidenceFilter("accepted");
  await useAppStore.getState().setEvidenceStatus("evitem_1", "accepted", "关键证据");

  assert.equal(useAppStore.getState().literatureSearch.evidenceFilter, "accepted");
  assert.deepEqual(requestBody, { evidence_item_id: "evitem_1", status: "accepted", note: "关键证据" });
  assert.equal(useAppStore.getState().sessionsById.s1.researchState.evidence_pool.status_counts.accepted, 1);
});

test("sendMessage includes parsed active attachment ids and records them on the user message", async () => {
  installWindowStub();
  const events = [];
  let requestBody = null;
  globalThis.fetch = async (url, options = {}) => {
    if (url === "/api/chat/stream") {
      requestBody = JSON.parse(options.body);
      return new Response('data: {"type":"token","text":"ok"}\\n\\ndata: {"type":"done"}\\n\\n', {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
    if (url === "/api/sessions?module_id=literature_search&include_archived=false") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions/s1/messages") {
      return new Response(
        JSON.stringify([
          {
            message_id: "m1",
            session_id: "s1",
            turn_id: "t1",
            role: "user",
            content: "结合附件分析",
            created_at: 1,
            metadata: { attachments: [{ attachment_id: "att_1", filename: "note.txt", status: "parsed", char_count: 5 }] },
          },
          {
            message_id: "m2",
            session_id: "s1",
            turn_id: "t1",
            role: "assistant",
            content: "ok",
            created_at: 2,
            metadata: {},
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/sessions/s1/context") {
      return new Response(
        JSON.stringify({ session_id: "s1", recent_messages: [], recent_search_results: [], recent_evidence: [], linked_artifacts: [], active_jobs: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/sessions/s1/artifacts" || url === "/api/sessions/s1/jobs") {
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url === "/api/sessions/s1/research-state") {
      return new Response(JSON.stringify(null), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);
  useAppStore.setState({
    modules: [{ id: "literature_search", name: "文献检索分析" }],
    activeModuleId: "literature_search",
    activeSessionByModule: { literature_search: "s1" },
    sessionsById: {
      s1: {
        id: "s1",
        moduleId: "literature_search",
        messages: [],
        attachments: [{ attachmentId: "att_1", filename: "note.txt", status: "parsed", charCount: 5 }],
        uploadingAttachments: false,
        attachmentError: null,
      },
    },
  });

  await useAppStore.getState().sendMessage("结合附件分析");
  events.push(...useAppStore.getState().sessionsById.s1.messages);

  assert.deepEqual(requestBody.options.attachment_ids, ["att_1"]);
  assert.equal(events[0].attachments[0].filename, "note.txt");
});

test("sendMessage records lightweight route, failure, attachment and library status events on assistant metadata", async () => {
  installWindowStub();
  globalThis.fetch = async (url, options = {}) => {
    if (url === "/api/chat/stream") {
      return new Response(
        [
          'data: {"type":"intent_route","route":"library_count","label":"文献库状态"}',
          'data: {"type":"library_status","stats":{"paper_count":3,"year_range":[2020,2024]}}',
          'data: {"type":"attachment_context","attachment_count":1,"filenames":["note.txt"]}',
          'data: {"type":"failure_explanation","code":"attachment_missing","message":"当前会话没有可用附件。"}',
          'data: {"type":"token","text":"ok"}',
          'data: {"type":"done"}',
          "",
        ].join("\n\n"),
        { status: 200, headers: { "Content-Type": "text/event-stream" } }
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);
  useAppStore.setState({
    modules: [{ id: "literature_search", name: "文献检索分析" }],
    activeModuleId: "literature_search",
    activeSessionByModule: { literature_search: "s1" },
    sessionsById: {
      s1: {
        id: "s1",
        moduleId: "literature_search",
        messages: [],
        attachments: [{ attachmentId: "att_1", filename: "note.txt", status: "parsed", charCount: 5 }],
        uploadingAttachments: false,
        attachmentError: null,
      },
    },
  });

  await useAppStore.getState().sendMessage("当前文献库中一共有多少文献？");

  const assistant = useAppStore.getState().sessionsById.s1.messages.find((message) => message.role === "assistant");
  assert.equal(assistant.metadata.route, "library_count");
  assert.equal(assistant.metadata.routeLabel, "文献库状态");
  assert.equal(assistant.metadata.usedLibraryStats, true);
  assert.equal(assistant.metadata.libraryStats.paperCount, 3);
  assert.equal(assistant.metadata.usedAttachments.attachmentCount, 1);
  assert.deepEqual(assistant.metadata.usedAttachments.filenames, ["note.txt"]);
  assert.equal(assistant.metadata.failureCode, "attachment_missing");
  assert.equal(assistant.metadata.failureMessage, "当前会话没有可用附件。");
});
