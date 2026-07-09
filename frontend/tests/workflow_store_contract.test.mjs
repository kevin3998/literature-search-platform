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

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status || 200,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
}

test("createAndStartWorkflow creates a controlled workflow and starts streaming immediately", async () => {
  installWindowStub();
  const calls = [];
  const encoder = new TextEncoder();
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null });
    if (url === "/api/workflows" && options.method === "POST") {
      return jsonResponse({
        workflow_id: "wf_1",
        template_id: "controlled-screening",
        template_name: "新颖性 / 可行性 / 风险筛选",
        topic: "大语言模型在材料发现中的应用",
        status: "draft",
        steps: [],
      });
    }
    if (url === "/api/workflows/wf_1/start" && options.method === "POST") {
      return jsonResponse({ job_id: "job_1", status: "running", stream_url: "/api/workflows/wf_1/stream" });
    }
    if (url === "/api/workflows/wf_1/stream") {
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode('data: {"type":"done"}\n\n'));
            controller.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } }
      );
    }
    if (url === "/api/workflows?limit=50") {
      return jsonResponse({ workflows: [] });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  const detail = await useAppStore.getState().createAndStartWorkflow({
    templateId: "controlled-screening",
    topic: "大语言模型在材料发现中的应用",
    scope: "library+boost",
  });

  assert.equal(detail.workflow_id, "wf_1");
  assert.deepEqual(calls.slice(0, 3).map((call) => [call.method, call.url]), [
    ["POST", "/api/workflows"],
    ["POST", "/api/workflows/wf_1/start"],
    ["GET", "/api/workflows/wf_1/stream"],
  ]);
  assert.equal(calls[0].body.template_id, "controlled-screening");
  assert.equal(calls[0].body.scope, "library+boost");
  assert.equal(useAppStore.getState().workflow.activeId, "wf_1");
  assert.equal(useAppStore.getState().workflow.view, "console");
  assert.equal(useAppStore.getState().workflow.live.status, "running");
});

test("workflow preview actions switch between result, stage, and artifact modes", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET" });
    if (url === "/api/workflows/wf_1/artifacts/users%2Flocal_user%2Fresearch_agent%2Ftask%2Freports%2Fminimal_topic_to_evidence_report.md") {
      return jsonResponse({
        workflow_id: "wf_1",
        artifact_id: "users/local_user/research_agent/task/reports/minimal_topic_to_evidence_report.md",
        artifact_type: "build_minimal_topic_to_evidence_report",
        label: "最小证据报告",
        content_type: "markdown",
        text: "# 最小证据报告",
        json: null,
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  useAppStore.getState().selectWorkflowStage("rank_evidence");
  assert.equal(useAppStore.getState().workflow.preview.mode, "stage");
  assert.equal(useAppStore.getState().workflow.preview.selectedStage, "rank_evidence");

  await useAppStore.getState().selectWorkflowArtifact("users/local_user/research_agent/task/reports/minimal_topic_to_evidence_report.md", "wf_1");
  assert.equal(useAppStore.getState().workflow.preview.mode, "artifact");
  assert.equal(useAppStore.getState().workflow.preview.selectedArtifactId, "users/local_user/research_agent/task/reports/minimal_topic_to_evidence_report.md");
  assert.equal(useAppStore.getState().workflow.preview.artifact.label, "最小证据报告");
  assert.equal(useAppStore.getState().workflow.preview.loading, false);

  useAppStore.getState().selectWorkflowResult();
  assert.equal(useAppStore.getState().workflow.preview.mode, "result");
  assert.equal(useAppStore.getState().workflow.preview.selectedStage, null);
  assert.equal(useAppStore.getState().workflow.preview.selectedArtifactId, null);
  assert.equal(useAppStore.getState().workflow.preview.artifact, null);
  assert.equal(calls[0].url, "/api/workflows/wf_1/artifacts/users%2Flocal_user%2Fresearch_agent%2Ftask%2Freports%2Fminimal_topic_to_evidence_report.md");
});

test("workflow artifact preview failure is stored as a readable error", async () => {
  installWindowStub();
  globalThis.fetch = async () => jsonResponse({ detail: "artifact not found" }, { status: 404 });

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await assert.rejects(
    useAppStore.getState().selectWorkflowArtifact("missing.md", "wf_1"),
    /artifact not found/
  );
  assert.equal(useAppStore.getState().workflow.preview.mode, "artifact");
  assert.equal(useAppStore.getState().workflow.preview.loading, false);
  assert.match(useAppStore.getState().workflow.preview.error, /artifact not found/);
});

test("openWorkflow loads insights without disturbing workflow detail", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url === "/api/workflows/wf_1") {
      return jsonResponse({
        workflow_id: "wf_1",
        status: "completed",
        topic: "材料发现",
        steps: [],
        artifacts: [],
        history_log: [],
        next_event_index: 0,
      });
    }
    if (url === "/api/workflows/wf_1/insights") {
      return jsonResponse({
        workflow_id: "wf_1",
        evidence: {
          available: true,
          card_count: 1,
          selected_count: 1,
          role_counts: { mechanism: 1 },
          support_counts: { supporting: 1 },
          cards: [{ evidence_id: "ecard_1", title: "Paper", selected: true }],
        },
        diagnostics: { available: true, severity_counts: { info: 1, warning: 0, error: 0 }, items: [] },
      });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await useAppStore.getState().openWorkflow("wf_1");

  assert.deepEqual(calls, ["/api/workflows/wf_1", "/api/workflows/wf_1/insights"]);
  assert.equal(useAppStore.getState().workflow.detail.workflow_id, "wf_1");
  assert.equal(useAppStore.getState().workflow.insights.data.evidence.card_count, 1);
  assert.equal(useAppStore.getState().workflow.insights.loading, false);
});

test("workflow insights selection actions switch sidebar and preview modes", async () => {
  installWindowStub();
  globalThis.fetch = async () => jsonResponse({});

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  useAppStore.getState().selectWorkflowSidebarTab("evidence");
  assert.equal(useAppStore.getState().workflow.sidebarTab, "evidence");

  useAppStore.getState().selectWorkflowEvidenceCard("ecard_1");
  assert.equal(useAppStore.getState().workflow.preview.mode, "evidence");
  assert.equal(useAppStore.getState().workflow.preview.selectedEvidenceId, "ecard_1");
  assert.equal(useAppStore.getState().workflow.preview.selectedDiagnosticId, null);

  useAppStore.getState().selectWorkflowDiagnostic("screening_diagnostics");
  assert.equal(useAppStore.getState().workflow.preview.mode, "diagnostic");
  assert.equal(useAppStore.getState().workflow.preview.selectedDiagnosticId, "screening_diagnostics");
  assert.equal(useAppStore.getState().workflow.preview.selectedEvidenceId, null);

  useAppStore.getState().selectWorkflowResult();
  assert.equal(useAppStore.getState().workflow.preview.mode, "result");
  assert.equal(useAppStore.getState().workflow.preview.selectedEvidenceId, null);
  assert.equal(useAppStore.getState().workflow.preview.selectedDiagnosticId, null);
});

test("workflow insights failure preserves console detail and records sidebar error", async () => {
  installWindowStub();
  globalThis.fetch = async (url) => {
    if (url === "/api/workflows/wf_1") {
      return jsonResponse({
        workflow_id: "wf_1",
        status: "completed",
        topic: "材料发现",
        steps: [],
        artifacts: [],
        history_log: [],
        next_event_index: 0,
      });
    }
    if (url === "/api/workflows/wf_1/insights") {
      return jsonResponse({ detail: "insights failed" }, { status: 503 });
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?case=${Date.now()}`);

  await useAppStore.getState().openWorkflow("wf_1");

  assert.equal(useAppStore.getState().workflow.detail.workflow_id, "wf_1");
  assert.match(useAppStore.getState().workflow.insights.error, /insights failed/);
  assert.equal(useAppStore.getState().workflow.insights.data, null);
});
