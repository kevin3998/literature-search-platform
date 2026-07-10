import { create } from "zustand";
import { authApi, corpusApi, fetchModules, fetchLibrary, literatureSearchApi, modelProfilesApi, sessionApi, settingsApi, streamChat, streamLiteratureSearchJob, structuredExtractionApi, workflowApi, streamWorkflow } from "../api/client.js";

// Block 7/10: human-readable status text for the workflow run log.
const STEP_STATUS_TEXT = { running: "执行中", done: "完成", failed: "失败", blocked: "已阻塞", pending: "待执行", skipped: "已跳过", unavailable: "敬请期待" };
const ACTIVE_EVIDENCE_BUILD_STATUSES = new Set(["queued", "running", "cancelling"]);

const EMPTY_WORKFLOW_LIVE = {
  steps: {},
  stages: {},
  artifacts: [],
  log: [],
  output: "",
  pauseRequested: false,
  status: null,
  error: null,
  streaming: false,
  streamId: null,
  nextEventIndex: 0,
  seenEventKeys: {},
};

function emptyWorkflowLive(patch = {}) {
  return { ...EMPTY_WORKFLOW_LIVE, ...patch };
}

const EMPTY_WORKFLOW_PREVIEW = {
  mode: "result",
  selectedStage: null,
  selectedArtifactId: null,
  selectedEvidenceId: null,
  selectedDiagnosticId: null,
  artifact: null,
  loading: false,
  error: null,
};

function emptyWorkflowPreview(patch = {}) {
  return { ...EMPTY_WORKFLOW_PREVIEW, ...patch };
}

const EMPTY_WORKFLOW_INSIGHTS = {
  loading: false,
  error: null,
  data: null,
};

function emptyWorkflowInsights(patch = {}) {
  return { ...EMPTY_WORKFLOW_INSIGHTS, ...patch };
}

const EMPTY_LITERATURE_PREVIEW = {
  mode: "answer",
  selectedEvidenceId: null,
  selectedPaperId: null,
  selectedAuditId: null,
};

function emptyLiteraturePreview(patch = {}) {
  return { ...EMPTY_LITERATURE_PREVIEW, ...patch };
}

function isMissingSessionError(error) {
  const message = String(error?.message || error || "").toLowerCase();
  return message.includes("session not found") || message.includes("not found") || message.includes("未找到");
}

function camelizeShallow(value) {
  if (!value || typeof value !== "object") return {};
  const toCamel = (key) => key.replace(/_([a-z])/g, (_, char) => char.toUpperCase());
  return Object.fromEntries(Object.entries(value).map(([key, val]) => [toCamel(key), val]));
}

function updateAssistantMetadata(messages, patch) {
  if (!messages.length) return messages;
  const lastIdx = messages.length - 1;
  const current = messages[lastIdx] || {};
  messages[lastIdx] = {
    ...current,
    metadata: {
      ...(current.metadata || {}),
      ...patch,
    },
  };
  return messages;
}

function workflowEventKey(event) {
  if (event?._event_index !== undefined && event?._event_index !== null) return `idx:${event._event_index}`;
  return `${event?.type || "event"}:${event?.ts || ""}:${event?.stage || ""}:${event?.step_index ?? ""}:${event?.artifact_id || ""}:${event?.text || event?.message || ""}`;
}

function workflowOutputFromDetail(detail) {
  const steps = detail?.steps || [];
  const artifactOutput = (pattern) =>
    steps.find((s) => (s.artifact_ids || []).some((id) => pattern.test(id)) && s.output_text)?.output_text || "";
  return (
    artifactOutput(/screening\/idea_screening_results\.md$/) ||
    artifactOutput(/ideas\/candidate_ideas\.md$/) ||
    artifactOutput(/gaps\/gap_map\.md$/) ||
    artifactOutput(/landscape\/literature_landscape\.md$/) ||
    artifactOutput(/reports\/minimal_topic_to_evidence_report\.md$/) ||
    artifactOutput(/IDEA_REPORT_.*\.md$/) ||
    artifactOutput(/NOVELTY_CHECK_.*\.md$/) ||
    artifactOutput(/IDEA_CANDIDATES_.*\.md$/) ||
    [...steps].reverse().find((s) => s.output_text)?.output_text ||
    ""
  );
}

const EMPTY_EXTRACTION_COLLECTION = {
  candidates: [],
  versions: [],
  activeVersion: null,
  searchResult: null,
  expansion: null,
  selectedCandidateIds: {},
  filterOptions: { available: true, reason: null, years: [], journals: [], sites: [] },
  loading: false,
  screening: false,
  freezing: false,
  filters: { decision: "", source: "", q: "" },
  error: null,
};

function emptyExtractionCollection(patch = {}) {
  return {
    ...EMPTY_EXTRACTION_COLLECTION,
    filters: { ...EMPTY_EXTRACTION_COLLECTION.filters },
    filterOptions: { ...EMPTY_EXTRACTION_COLLECTION.filterOptions },
    ...patch,
  };
}

const EMPTY_EXTRACTION_SCHEMA = {
  draft: null,
  versions: [],
  activeVersion: null,
  assistResult: null,
  loading: false,
  saving: false,
  assisting: false,
  freezing: false,
  error: null,
};

function emptyExtractionSchema(patch = {}) {
  return { ...EMPTY_EXTRACTION_SCHEMA, ...patch };
}

const EMPTY_EXTRACTION_PREPARATION = {
  promptContracts: [],
  activePromptContract: null,
  evidencePackets: [],
  activeEvidencePacket: null,
  buildJobs: [],
  activeBuildJob: null,
  packetItems: [],
  packetItemsPagination: { limit: 200, offset: 0, total: 0 },
  compiling: false,
  building: false,
  cancellingBuild: false,
  pollingBuild: false,
  loading: false,
  error: null,
};

function emptyExtractionPreparation(patch = {}) {
  return {
    ...EMPTY_EXTRACTION_PREPARATION,
    packetItemsPagination: { ...EMPTY_EXTRACTION_PREPARATION.packetItemsPagination },
    ...patch,
  };
}

const EMPTY_EXTRACTION_RUNS = {
  items: [],
  activeRun: null,
  runItems: [],
  records: [],
  starting: false,
  cancelling: false,
  resuming: false,
  loading: false,
  polling: false,
  recovery: null,
  error: null,
};

function emptyExtractionRuns(patch = {}) {
  return { ...EMPTY_EXTRACTION_RUNS, ...patch };
}

const EMPTY_EXTRACTION_REVIEW = {
  runs: [],
  activeRunId: null,
  rows: [],
  queueRows: [],
  selectedQueue: "all",
  summary: null,
  multimodalJobs: [],
  activeMultimodalJob: null,
  activeRecord: null,
  events: [],
  filters: { q: "", fieldKey: "", status: "", reviewPriority: "", qualityFlag: "", missing: "" },
  pagination: { limit: 100, offset: 0, total: 0 },
  queuePagination: { limit: 100, offset: 0, total: 0 },
  loading: false,
  saving: false,
  multimodalStarting: false,
  multimodalPolling: false,
  multimodalCancelling: false,
  error: null,
};

function emptyExtractionReview(patch = {}) {
  return {
    ...EMPTY_EXTRACTION_REVIEW,
    filters: { ...EMPTY_EXTRACTION_REVIEW.filters },
    pagination: { ...EMPTY_EXTRACTION_REVIEW.pagination },
    queuePagination: { ...EMPTY_EXTRACTION_REVIEW.queuePagination },
    ...patch,
  };
}

const EMPTY_EXTRACTION_EXPORTS = {
  runs: [],
  preview: null,
  items: [],
  activeExport: null,
  selectedRunId: null,
  selectedFormats: { csv: true, json: true, xlsx: true, markdown: true },
  creating: false,
  loading: false,
  downloading: false,
  error: null,
};

function emptyExtractionExports(patch = {}) {
  return {
    ...EMPTY_EXTRACTION_EXPORTS,
    selectedFormats: { ...EMPTY_EXTRACTION_EXPORTS.selectedFormats },
    ...patch,
  };
}

function pruneSelection(selectedCandidateIds, candidates) {
  const available = new Set((candidates || []).map((item) => item.candidateId));
  return Object.fromEntries(Object.entries(selectedCandidateIds || {}).filter(([candidateId]) => available.has(candidateId)));
}

function selectedExportFormats(selectedFormats = {}) {
  return Object.entries(selectedFormats)
    .filter(([, enabled]) => !!enabled)
    .map(([format]) => format);
}

function filenameFromContentDisposition(header, fallback) {
  if (!header) return fallback;
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1].replace(/"/g, ""));
  const match = header.match(/filename="?([^";]+)"?/i);
  return match?.[1] || fallback;
}

export const useAppStore = create((set, get) => ({
  modules: [],
  modulesLoaded: false,
  activeModuleId: null,
  currentUser: null,
  auth: {
    status: "checking",
    mode: "login",
    error: null,
    loading: false,
  },
  appError: null,

  setAppError(message) {
    set({ appError: message ? { message, at: Date.now() } : null });
  },

  clearAppError() {
    set({ appError: null });
  },

  async bootstrapAuth() {
    set((state) => ({ auth: { ...state.auth, status: "checking", error: null, loading: false } }));
    try {
      const user = await authApi.me();
      set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", error: null, loading: false } }));
      await get().loadModules();
    } catch {
      set((state) => ({
        currentUser: null,
        modulesLoaded: true,
        auth: { ...state.auth, status: "login_required", error: null, loading: false },
      }));
    }
  },

  setAuthMode(mode) {
    set((state) => ({ auth: { ...state.auth, mode, error: null } }));
  },

  async authLogin(payload) {
    set((state) => ({ auth: { ...state.auth, loading: true, error: null } }));
    try {
      const user = await authApi.login(payload);
      set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", loading: false, error: null } }));
      await get().loadModules();
      return user;
    } catch (e) {
      set((state) => ({ auth: { ...state.auth, loading: false, error: e.message || "登录失败" } }));
      return null;
    }
  },

  async authSignup(payload) {
    set((state) => ({ auth: { ...state.auth, loading: true, error: null } }));
    try {
      const user = await authApi.signup(payload);
      set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", loading: false, error: null } }));
      await get().loadModules();
      return user;
    } catch (e) {
      set((state) => ({ auth: { ...state.auth, loading: false, error: e.message || "注册失败" } }));
      return null;
    }
  },

  async authLogout() {
    await authApi.logout().catch(() => {});
    set({
      modules: [],
      modulesLoaded: true,
      activeModuleId: null,
      currentUser: null,
      appError: null,
      homeOpen: true,
      workflowOpen: false,
      structuredExtractionOpen: false,
      sessionsById: {},
      sessionOrderByModule: {},
      activeSessionByModule: {},
      sessionContextMenu: null,
      library: [],
      libraryLoaded: false,
      auth: { status: "login_required", mode: "login", error: null, loading: false },
    });
  },

  // Research Index Health is the home page shown after startup (Block 0).
  homeOpen: true,
  home: {
    dashboard: null,
    loading: false,
    error: null,
    maintenance: { runningAction: null, jobId: null, events: [], error: null, startedAt: null, completedAt: null, lastStatus: null, lastAction: null },
  },

  sessionsById: {},
  sessionOrderByModule: {}, // moduleId -> [sessionId, ...] 最近在前
  activeSessionByModule: {},
  sessionContextMenu: null,

  library: [],
  libraryLoaded: false,
  rightPanelTab: "evidence", // 'evidence' | 'papers' | 'audit'

  // Block 4b: tools are an Agent-internal capability.普通用户只从 Chat 进入;
  // the manual tool consoles are gated behind this developer toggle (UI-only
  // preference, persisted in localStorage — not a backend permission setting).
  developerMode: window.localStorage.getItem("developerMode") === "1",
  // Per-turn research intent: quick = read-only first; deep = exposes the job
  // tools (run/task_run/extract/compare). Sent as options.answer_mode.
  chatAnswerMode: "quick",
  // Block 6c: active specialist role (subagent). "general" = free-form chat with
  // the full tool set; the others gate tools + prepend a role prompt. Sent as
  // options.role. analysis/synthesis/report force deep mode on the backend.
  chatRole: "general",

  settings: {
    open: false,
    activeTab: "general",
    values: null,
    draft: null,
    effective: null,
    diagnostics: null,
    readiness: null,
    modelTest: null,
    loading: false,
    saving: false,
    error: null,
    dirty: false,
  },

  modelProfiles: {
    items: [],
    loading: false,
    error: null,
    testById: {},
  },

  literatureSearch: {
    activeToolTab: "chat",
    evidenceFilter: "current",
    preview: emptyLiteraturePreview(),
    status: {},
    searchResults: null,
    selectedPaper: null,
    selectedEvidence: null,
    jobsById: {},
    activeJobId: null,
    artifacts: [],
    selectedArtifact: null,
    toolResult: null,
    loading: false,
    error: null,
  },

  // Block 7/10: the Deep Research Task Engine surface — a top-level view
  // co-equal with Chat (not a Workbench tab). workflowOpen drives App routing.
  workflowOpen: false,
  workflow: {
    view: "gallery", // 'gallery' | 'console'
    categories: [],
    templates: [],
    list: [],
    activeId: null,
    detail: null,
    // Live SSE overlay during a run (merged over `detail` in the console).
    live: emptyWorkflowLive(),
    preview: emptyWorkflowPreview(),
    insights: emptyWorkflowInsights(),
    sidebarTab: "artifacts",
    creating: false,
    loading: false,
    error: null,
  },

  structuredExtractionOpen: false,
  structuredExtraction: {
    view: "list",
    tasks: [],
    activeTaskId: null,
    activeTask: null,
    collection: emptyExtractionCollection(),
    schema: emptyExtractionSchema(),
    preparation: emptyExtractionPreparation(),
    runs: emptyExtractionRuns(),
    review: emptyExtractionReview(),
    exports: emptyExtractionExports(),
    loading: false,
    creating: false,
    error: null,
  },

  openHome() {
    set({ homeOpen: true, workflowOpen: false, structuredExtractionOpen: false });
    get().updateSettings({ open: false });
    get().loadHomeDashboard();
  },

  // ---- Block 7/10: workflow (Deep Research Task Engine) ----
  async openWorkflows() {
    set({ workflowOpen: true, homeOpen: false, structuredExtractionOpen: false });
    get().updateSettings({ open: false });
    set((state) => ({ workflow: { ...state.workflow, view: "gallery", activeId: null, detail: null } }));
    await Promise.all([get().loadWorkflowTemplates(), get().loadWorkflowList()]);
  },

  async openStructuredExtraction() {
    set({ structuredExtractionOpen: true, homeOpen: false, workflowOpen: false });
    get().updateSettings({ open: false });
    await get().loadExtractionTasks();
  },

  async loadExtractionTasks() {
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, loading: true, error: null } }));
    try {
      const tasks = await structuredExtractionApi.listTasks();
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, tasks, loading: false } }));
      return tasks;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, loading: false, error: e.message } }));
      throw e;
    }
  },

  async createExtractionTask({ name, description }) {
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, creating: true, error: null } }));
    try {
      const task = await structuredExtractionApi.createTask({ name, description: description || "" });
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          creating: false,
          view: "detail",
          tasks: [task, ...state.structuredExtraction.tasks.filter((item) => item.taskId !== task.taskId)],
          activeTaskId: task.taskId,
          activeTask: task,
          collection: emptyExtractionCollection(),
          schema: emptyExtractionSchema(),
          preparation: emptyExtractionPreparation(),
          runs: emptyExtractionRuns(),
          review: emptyExtractionReview(),
          exports: emptyExtractionExports(),
        },
      }));
      return task;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, creating: false, error: e.message } }));
      throw e;
    }
  },

  async openExtractionTask(taskId) {
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, loading: true, error: null, activeTaskId: taskId } }));
    try {
      const task = await structuredExtractionApi.getTask(taskId);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          loading: false,
          view: "detail",
          activeTaskId: task.taskId,
          activeTask: task,
          collection: emptyExtractionCollection(),
          schema: emptyExtractionSchema(),
          preparation: emptyExtractionPreparation(),
          runs: emptyExtractionRuns(),
          review: emptyExtractionReview(),
          exports: emptyExtractionExports(),
        },
      }));
      return task;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, loading: false, error: e.message } }));
      throw e;
    }
  },

  async updateExtractionTask(taskId, patch) {
    try {
      const task = await structuredExtractionApi.updateTask(taskId, patch);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          tasks: state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item),
          activeTask: state.structuredExtraction.activeTaskId === task.taskId ? task : state.structuredExtraction.activeTask,
        },
      }));
      return task;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, error: e.message } }));
      throw e;
    }
  },

  async duplicateExtractionTask(taskId, options = {}) {
    try {
      const source = get().structuredExtraction.tasks.find((item) => item.taskId === taskId) || get().structuredExtraction.activeTask;
      const task = await structuredExtractionApi.duplicateTask(taskId, {
        name: options.name || `${source?.name || "抽取任务"} copy`,
        copy_model_settings: options.copyModelSettings !== false,
      });
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, tasks: [task, ...state.structuredExtraction.tasks] } }));
      return task;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, error: e.message } }));
      throw e;
    }
  },

  async archiveExtractionTask(taskId, archived = true) {
    try {
      const task = await structuredExtractionApi.archiveTask(taskId, archived);
      set((state) => {
        const tasks = archived ? state.structuredExtraction.tasks.filter((item) => item.taskId !== taskId) : state.structuredExtraction.tasks.map((item) => item.taskId === taskId ? task : item);
        const leavingActive = archived && state.structuredExtraction.activeTaskId === taskId;
        return {
          structuredExtraction: {
            ...state.structuredExtraction,
            view: leavingActive ? "list" : state.structuredExtraction.view,
            tasks,
            activeTaskId: leavingActive ? null : state.structuredExtraction.activeTaskId,
            activeTask: leavingActive ? null : state.structuredExtraction.activeTask,
            collection: leavingActive ? emptyExtractionCollection() : state.structuredExtraction.collection,
            schema: leavingActive ? emptyExtractionSchema() : state.structuredExtraction.schema,
            preparation: leavingActive ? emptyExtractionPreparation() : state.structuredExtraction.preparation,
            runs: leavingActive ? emptyExtractionRuns() : state.structuredExtraction.runs,
            review: leavingActive ? emptyExtractionReview() : state.structuredExtraction.review,
            exports: leavingActive ? emptyExtractionExports() : state.structuredExtraction.exports,
          },
        };
      });
      return task;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, error: e.message } }));
      throw e;
    }
  },

  async deleteExtractionTask(taskId) {
    try {
      await structuredExtractionApi.deleteTask(taskId);
      set((state) => {
        const leavingActive = state.structuredExtraction.activeTaskId === taskId;
        return {
          structuredExtraction: {
            ...state.structuredExtraction,
            view: leavingActive ? "list" : state.structuredExtraction.view,
            tasks: state.structuredExtraction.tasks.filter((item) => item.taskId !== taskId),
            activeTaskId: leavingActive ? null : state.structuredExtraction.activeTaskId,
            activeTask: leavingActive ? null : state.structuredExtraction.activeTask,
            collection: leavingActive ? emptyExtractionCollection() : state.structuredExtraction.collection,
            schema: leavingActive ? emptyExtractionSchema() : state.structuredExtraction.schema,
            preparation: leavingActive ? emptyExtractionPreparation() : state.structuredExtraction.preparation,
            runs: leavingActive ? emptyExtractionRuns() : state.structuredExtraction.runs,
            review: leavingActive ? emptyExtractionReview() : state.structuredExtraction.review,
            exports: leavingActive ? emptyExtractionExports() : state.structuredExtraction.exports,
          },
        };
      });
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, error: e.message } }));
      throw e;
    }
  },

  backToExtractionTasks() {
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        view: "list",
        activeTaskId: null,
        activeTask: null,
        collection: emptyExtractionCollection(),
        schema: emptyExtractionSchema(),
        preparation: emptyExtractionPreparation(),
        runs: emptyExtractionRuns(),
        review: emptyExtractionReview(),
        exports: emptyExtractionExports(),
      },
    }));
    get().loadExtractionTasks().catch(() => {});
  },

  async loadExtractionCandidates(taskId, filters = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    const nextFilters = filters || get().structuredExtraction.collection.filters;
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        collection: { ...state.structuredExtraction.collection, loading: true, error: null, filters: { ...state.structuredExtraction.collection.filters, ...nextFilters } },
      },
    }));
    try {
      const result = await structuredExtractionApi.listCandidates(id, { ...nextFilters, limit: 0 });
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          collection: {
            ...state.structuredExtraction.collection,
            candidates: result.candidates,
            loading: false,
            selectedCandidateIds: pruneSelection(state.structuredExtraction.collection.selectedCandidateIds, result.candidates),
          },
        },
      }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionCollectionFilterOptions(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    try {
      const filterOptions = await structuredExtractionApi.getCollectionFilterOptions(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          collection: { ...state.structuredExtraction.collection, filterOptions },
        },
      }));
      return filterOptions;
    } catch (e) {
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          collection: { ...state.structuredExtraction.collection, error: e.message },
        },
      }));
      throw e;
    }
  },

  async searchExtractionCollection(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, loading: true, error: null } } }));
    try {
      const result = await structuredExtractionApi.searchCollection(id, payload);
      const task = await structuredExtractionApi.getTask(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          activeTask: task,
          tasks: state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item),
          collection: {
            ...state.structuredExtraction.collection,
            candidates: result.candidates,
            searchResult: result,
            loading: false,
            selectedCandidateIds: {},
          },
        },
      }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async setExtractionCandidateDecision(taskId, candidateId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    try {
      const candidate = await structuredExtractionApi.setCandidateDecision(id, candidateId, payload);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          collection: {
            ...state.structuredExtraction.collection,
            candidates: state.structuredExtraction.collection.candidates.map((item) => item.candidateId === candidate.candidateId ? candidate : item),
          },
        },
      }));
      return candidate;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, error: e.message } } }));
      throw e;
    }
  },

  async bulkExtractionCandidateDecision(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    try {
      const result = await structuredExtractionApi.bulkCandidateDecision(id, payload);
      await get().loadExtractionCandidates(id);
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, error: e.message } } }));
      throw e;
    }
  },

  async expandExtractionQuestion(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, loading: true, error: null } } }));
    try {
      const expansion = await structuredExtractionApi.expandQuestion(id, payload);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, expansion, loading: false } } }));
      return expansion;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async screenExtractionCandidates(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, screening: true, error: null } } }));
    try {
      const result = await structuredExtractionApi.screenCandidates(id, payload);
      await get().loadExtractionCandidates(id);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, screening: false } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, screening: false, error: e.message } } }));
      throw e;
    }
  },

  async freezeExtractionCollection(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, freezing: true, error: null } } }));
    try {
      const frozen = await structuredExtractionApi.freezeCollection(id);
      const task = await structuredExtractionApi.getTask(id);
      const versions = await structuredExtractionApi.listCollectionVersions(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          activeTask: task,
          tasks: state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item),
          collection: {
            ...state.structuredExtraction.collection,
            versions: versions.versions,
            activeVersion: frozen,
            freezing: false,
          },
          preparation: emptyExtractionPreparation(),
          runs: emptyExtractionRuns(),
          review: emptyExtractionReview(),
          exports: emptyExtractionExports(),
        },
      }));
      return frozen;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, freezing: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionCollectionVersions(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    try {
      const result = await structuredExtractionApi.listCollectionVersions(id);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, versions: result.versions } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, collection: { ...state.structuredExtraction.collection, error: e.message } } }));
      throw e;
    }
  },

  setExtractionCollectionFilters(filters) {
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        collection: { ...state.structuredExtraction.collection, filters: { ...state.structuredExtraction.collection.filters, ...filters } },
      },
    }));
  },

  toggleExtractionCandidateSelection(candidateId, selected = null) {
    set((state) => {
      const current = !!state.structuredExtraction.collection.selectedCandidateIds[candidateId];
      const nextValue = selected === null ? !current : !!selected;
      const selectedCandidateIds = { ...state.structuredExtraction.collection.selectedCandidateIds };
      if (nextValue) selectedCandidateIds[candidateId] = true;
      else delete selectedCandidateIds[candidateId];
      return {
        structuredExtraction: {
          ...state.structuredExtraction,
          collection: { ...state.structuredExtraction.collection, selectedCandidateIds },
        },
      };
    });
  },

  async loadExtractionSchemaDraft(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, loading: true, error: null } } }));
    try {
      const draft = await structuredExtractionApi.getSchemaDraft(id);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, draft, loading: false } } }));
      return draft;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async saveExtractionSchemaDraft(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, saving: true, error: null } } }));
    try {
      const draft = await structuredExtractionApi.saveSchemaDraft(id, payload);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, draft, saving: false } } }));
      return draft;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, saving: false, error: e.message } } }));
      throw e;
    }
  },

  async assistExtractionSchema(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, assisting: true, error: null } } }));
    try {
      const assistResult = await structuredExtractionApi.assistSchema(id, payload);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, assistResult, assisting: false } } }));
      return assistResult;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, assisting: false, error: e.message } } }));
      throw e;
    }
  },

  async freezeExtractionSchema(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, freezing: true, error: null } } }));
    try {
      const frozen = await structuredExtractionApi.freezeSchema(id);
      const task = await structuredExtractionApi.getTask(id);
      const versions = await structuredExtractionApi.listSchemaVersions(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          activeTask: task,
          tasks: state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item),
          schema: {
            ...state.structuredExtraction.schema,
            activeVersion: frozen,
            versions: versions.versions,
            freezing: false,
          },
          preparation: emptyExtractionPreparation(),
          runs: emptyExtractionRuns(),
          review: emptyExtractionReview(),
          exports: emptyExtractionExports(),
        },
      }));
      return frozen;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, freezing: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionSchemaVersions(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    try {
      const result = await structuredExtractionApi.listSchemaVersions(id);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, versions: result.versions } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, error: e.message } } }));
      throw e;
    }
  },

  async duplicateExtractionSchemaToDraft(taskId, schemaVersion) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !schemaVersion) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, loading: true, error: null } } }));
    try {
      const draft = await structuredExtractionApi.duplicateSchemaToDraft(id, schemaVersion);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, draft, loading: false } } }));
      return draft;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, schema: { ...state.structuredExtraction.schema, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionPreparation(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, loading: true, error: null } } }));
    try {
      const [contractsResult, packetsResult, jobsResult] = await Promise.all([
        structuredExtractionApi.listPromptContracts(id),
        structuredExtractionApi.listEvidencePackets(id),
        structuredExtractionApi.listEvidencePacketBuildJobs(id),
      ]);
      const promptContracts = contractsResult.versions || [];
      const evidencePackets = packetsResult.versions || [];
      const buildJobs = jobsResult.jobs || [];
      const activePromptContract = promptContracts[0] || null;
      const activeEvidencePacket = evidencePackets[0] || null;
      const activeBuildJob = buildJobs.find((job) => ACTIVE_EVIDENCE_BUILD_STATUSES.has(job.status)) || buildJobs[0] || null;
      let packetItems = [];
      let packetItemsPagination = { limit: 200, offset: 0, total: 0 };
      if (activeEvidencePacket?.packetVersion) {
        const itemsResult = await structuredExtractionApi.listEvidencePacketItems(id, activeEvidencePacket.packetVersion, { limit: 200, offset: 0 });
        packetItems = itemsResult.items || [];
        packetItemsPagination = { limit: itemsResult.limit || 200, offset: itemsResult.offset || 0, total: itemsResult.total ?? packetItems.length };
      }
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          preparation: {
            ...state.structuredExtraction.preparation,
            promptContracts,
            activePromptContract,
            evidencePackets,
            activeEvidencePacket,
            buildJobs,
            activeBuildJob,
            packetItems,
            packetItemsPagination,
            building: !!activeBuildJob && ACTIVE_EVIDENCE_BUILD_STATUSES.has(activeBuildJob.status),
            loading: false,
          },
        },
      }));
      return { promptContracts, evidencePackets, buildJobs, packetItems };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async compileExtractionPromptContract(taskId, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, compiling: true, error: null } } }));
    try {
      const contract = await structuredExtractionApi.compilePromptContract(id, payload);
      const result = await structuredExtractionApi.listPromptContracts(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          preparation: {
            ...state.structuredExtraction.preparation,
            promptContracts: result.versions || [],
            activePromptContract: contract,
            compiling: false,
          },
        },
      }));
      return contract;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, compiling: false, error: e.message } } }));
      throw e;
    }
  },

  async buildExtractionEvidencePacket(taskId, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, building: true, error: null } } }));
    try {
      const job = await structuredExtractionApi.startEvidencePacketBuildJob(id, payload);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          preparation: {
            ...state.structuredExtraction.preparation,
            activeBuildJob: job,
            buildJobs: [job, ...state.structuredExtraction.preparation.buildJobs.filter((item) => item.buildJobId !== job.buildJobId)],
            building: ACTIVE_EVIDENCE_BUILD_STATUSES.has(job.status),
          },
        },
      }));
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, building: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionEvidencePacketBuildJob(taskId, buildJobId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !buildJobId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, pollingBuild: true, error: null } } }));
    try {
      const job = await structuredExtractionApi.getEvidencePacketBuildJob(id, buildJobId);
      let nextPatch = {
        activeBuildJob: job,
        buildJobs: [job, ...get().structuredExtraction.preparation.buildJobs.filter((item) => item.buildJobId !== job.buildJobId)],
        building: ACTIVE_EVIDENCE_BUILD_STATUSES.has(job.status),
        pollingBuild: false,
      };
      if (job.status === "completed" && job.resultPacketVersion) {
        const packetsResult = await structuredExtractionApi.listEvidencePackets(id);
        const packet = (packetsResult.versions || []).find((item) => item.packetVersion === job.resultPacketVersion) || packetsResult.versions?.[0] || null;
        let packetItems = [];
        let packetItemsPagination = { limit: 200, offset: 0, total: 0 };
        if (packet?.packetVersion) {
          const itemsResult = await structuredExtractionApi.listEvidencePacketItems(id, packet.packetVersion, { limit: 200, offset: 0 });
          packetItems = itemsResult.items || [];
          packetItemsPagination = { limit: itemsResult.limit || 200, offset: itemsResult.offset || 0, total: itemsResult.total ?? packetItems.length };
        }
        nextPatch = {
          ...nextPatch,
          evidencePackets: packetsResult.versions || [],
          activeEvidencePacket: packet,
          packetItems,
          packetItemsPagination,
        };
      }
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, ...nextPatch } } }));
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, pollingBuild: false, building: false, error: e.message } } }));
      throw e;
    }
  },

  async cancelExtractionEvidencePacketBuildJob(taskId, buildJobId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !buildJobId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, cancellingBuild: true, error: null } } }));
    try {
      const job = await structuredExtractionApi.cancelEvidencePacketBuildJob(id, buildJobId);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          preparation: {
            ...state.structuredExtraction.preparation,
            activeBuildJob: job,
            buildJobs: [job, ...state.structuredExtraction.preparation.buildJobs.filter((item) => item.buildJobId !== job.buildJobId)],
            building: ACTIVE_EVIDENCE_BUILD_STATUSES.has(job.status),
            cancellingBuild: false,
          },
        },
      }));
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, cancellingBuild: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionEvidencePacketItems(taskId, packetVersion, options = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !packetVersion) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, loading: true, error: null } } }));
    try {
      const pagination = get().structuredExtraction.preparation.packetItemsPagination || { limit: 200, offset: 0 };
      const result = await structuredExtractionApi.listEvidencePacketItems(id, packetVersion, {
        limit: options.limit ?? pagination.limit ?? 200,
        offset: options.offset ?? pagination.offset ?? 0,
      });
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          preparation: {
            ...state.structuredExtraction.preparation,
            packetItems: result.items || [],
            packetItemsPagination: { limit: result.limit || 200, offset: result.offset || 0, total: result.total ?? (result.items || []).length },
            loading: false,
          },
        },
      }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, preparation: { ...state.structuredExtraction.preparation, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionRuns(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: true, error: null } } }));
    try {
      const result = await structuredExtractionApi.listExtractionRuns(id);
      const items = result.runs || [];
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          runs: {
            ...state.structuredExtraction.runs,
            items,
            activeRun: state.structuredExtraction.runs.activeRun || items[0] || null,
            loading: false,
          },
        },
      }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async startExtractionRun(taskId, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, starting: true, error: null } } }));
    try {
      const run = await structuredExtractionApi.startExtractionRun(id, payload);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          runs: {
            ...state.structuredExtraction.runs,
            items: [run, ...state.structuredExtraction.runs.items.filter((item) => item.runId !== run.runId)],
            activeRun: run,
            runItems: [],
            records: [],
            starting: false,
          },
        },
      }));
      await get().loadExtractionRunDetail(id, run.runId);
      return run;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, starting: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionRunDetail(taskId, runId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.runs.activeRun?.runId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: true, error: null } } }));
    try {
      const [run, itemsResult, recordsResult] = await Promise.all([
        structuredExtractionApi.getExtractionRun(id, rid),
        structuredExtractionApi.listExtractionRunItems(id, rid),
        structuredExtractionApi.listExtractionRunRecords(id, rid),
      ]);
      const terminal = ["completed", "completed_with_errors", "failed", "cancelled", "interrupted"].includes(run.status);
      const task = terminal ? await structuredExtractionApi.getTask(id) : get().structuredExtraction.activeTask;
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          activeTask: task,
          tasks: task ? state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item) : state.structuredExtraction.tasks,
          runs: {
            ...state.structuredExtraction.runs,
            items: state.structuredExtraction.runs.items.map((item) => item.runId === run.runId ? run : item),
            activeRun: run,
            runItems: itemsResult.items || [],
            records: recordsResult.records || [],
            loading: false,
            polling: !terminal,
          },
        },
      }));
      return { run, items: itemsResult.items || [], records: recordsResult.records || [] };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: false, polling: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionRunRecovery(taskId, runId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.runs.activeRun?.runId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: true, error: null } } }));
    try {
      const recovery = await structuredExtractionApi.getExtractionRunRecovery(id, rid);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, recovery, loading: false } } }));
      return recovery;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async resumeExtractionRun(taskId, runId, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.runs.activeRun?.runId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, resuming: true, error: null } } }));
    try {
      const run = await structuredExtractionApi.resumeExtractionRun(id, rid, payload);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          runs: {
            ...state.structuredExtraction.runs,
            items: state.structuredExtraction.runs.items.map((item) => item.runId === run.runId ? run : item),
            activeRun: run,
            recovery: null,
            resuming: false,
            polling: true,
          },
        },
      }));
      await get().loadExtractionRunDetail(id, run.runId);
      return run;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, resuming: false, error: e.message } } }));
      throw e;
    }
  },

  async cancelExtractionRun(taskId, runId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.runs.activeRun?.runId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, cancelling: true, error: null } } }));
    try {
      const run = await structuredExtractionApi.cancelExtractionRun(id, rid);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          runs: {
            ...state.structuredExtraction.runs,
            items: state.structuredExtraction.runs.items.map((item) => item.runId === run.runId ? run : item),
            activeRun: run,
            cancelling: false,
          },
        },
      }));
      return run;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, runs: { ...state.structuredExtraction.runs, cancelling: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionReview(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: true, error: null } } }));
    try {
      const runsResult = await structuredExtractionApi.listReviewRuns(id);
      const runs = runsResult.runs || [];
      const activeRunId = get().structuredExtraction.review.activeRunId || runs[0]?.runId || null;
      let table = { rows: [], total: 0, limit: 100, offset: 0, fieldKeys: [] };
      let summary = null;
      let queue = { rows: [], total: 0, limit: 100, offset: 0 };
      let jobs = { jobs: [] };
      if (activeRunId) {
        [table, summary, queue, jobs] = await Promise.all([
          structuredExtractionApi.listReviewTable(id, { ...get().structuredExtraction.review.filters, runId: activeRunId, limit: get().structuredExtraction.review.pagination.limit }),
          structuredExtractionApi.getReviewSummary(id, activeRunId),
          structuredExtractionApi.listReviewQueue(id, { runId: activeRunId, queue: get().structuredExtraction.review.selectedQueue, limit: get().structuredExtraction.review.queuePagination.limit }),
          structuredExtractionApi.listMultimodalReviewJobs(id, activeRunId),
        ]);
      }
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            runs,
            activeRunId,
            rows: table.rows || [],
            summary,
            queueRows: queue.rows || [],
            multimodalJobs: jobs.jobs || [],
            activeMultimodalJob: (jobs.jobs || [])[0] || state.structuredExtraction.review.activeMultimodalJob,
            pagination: { ...state.structuredExtraction.review.pagination, total: table.total || 0, limit: table.limit || 100, offset: table.offset || 0 },
            queuePagination: { ...state.structuredExtraction.review.queuePagination, total: queue.total || 0, limit: queue.limit || 100, offset: queue.offset || 0 },
            loading: false,
          },
        },
      }));
      return { runs, table };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadReviewTable(taskId, filters = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    const current = get().structuredExtraction.review;
    const nextFilters = filters ? { ...current.filters, ...filters } : current.filters;
    const activeRunId = nextFilters.runId || current.activeRunId;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: true, error: null, filters: nextFilters, activeRunId } } }));
    try {
      const table = await structuredExtractionApi.listReviewTable(id, { ...nextFilters, runId: activeRunId, limit: current.pagination.limit, offset: current.pagination.offset });
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            activeRunId: table.runId || activeRunId,
            rows: table.rows || [],
            pagination: { limit: table.limit || 100, offset: table.offset || 0, total: table.total || 0 },
            loading: false,
          },
        },
      }));
      return table;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadReviewSummary(taskId, runId = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.review.activeRunId;
    if (!id || !rid) return null;
    try {
      const summary = await structuredExtractionApi.getReviewSummary(id, rid);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: { ...state.structuredExtraction.review, summary, error: null },
        },
      }));
      return summary;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, error: e.message } } }));
      throw e;
    }
  },

  async loadReviewQueue(taskId, options = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const current = get().structuredExtraction.review;
    const rid = options.runId || current.activeRunId;
    const queueName = options.queue || current.selectedQueue || "all";
    if (!id || !rid) return null;
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        review: { ...state.structuredExtraction.review, loading: true, error: null, selectedQueue: queueName },
      },
    }));
    try {
      const queue = await structuredExtractionApi.listReviewQueue(id, {
        runId: rid,
        queue: queueName,
        limit: options.limit || current.queuePagination.limit,
        offset: options.offset ?? current.queuePagination.offset,
      });
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            activeRunId: queue.runId || rid,
            selectedQueue: queue.queue || queueName,
            queueRows: queue.rows || [],
            queuePagination: { limit: queue.limit || 100, offset: queue.offset || 0, total: queue.total || 0 },
            loading: false,
          },
        },
      }));
      return queue;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async loadMultimodalReviewJobs(taskId, runId = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.review.activeRunId;
    if (!id || !rid) return null;
    try {
      const jobs = await structuredExtractionApi.listMultimodalReviewJobs(id, rid);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            multimodalJobs: jobs.jobs || [],
            activeMultimodalJob: (jobs.jobs || [])[0] || state.structuredExtraction.review.activeMultimodalJob,
            error: null,
          },
        },
      }));
      return jobs;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, error: e.message } } }));
      throw e;
    }
  },

  async startMultimodalReviewJob(taskId, runId = null, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.review.activeRunId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, multimodalStarting: true, error: null } } }));
    try {
      const job = await structuredExtractionApi.startMultimodalReviewJob(id, rid, payload);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            activeMultimodalJob: job,
            multimodalJobs: [job, ...state.structuredExtraction.review.multimodalJobs.filter((item) => item.jobId !== job.jobId)],
            multimodalStarting: false,
          },
        },
      }));
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, multimodalStarting: false, error: e.message } } }));
      throw e;
    }
  },

  async refreshMultimodalReviewJob(taskId, jobId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !jobId) return null;
    try {
      const job = await structuredExtractionApi.getMultimodalReviewJob(id, jobId);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: {
            ...state.structuredExtraction.review,
            activeMultimodalJob: job,
            multimodalJobs: [job, ...state.structuredExtraction.review.multimodalJobs.filter((item) => item.jobId !== job.jobId)],
            error: null,
          },
        },
      }));
      if (["completed", "failed", "cancelled"].includes(job.status)) {
        await Promise.allSettled([
          get().loadReviewSummary(id, job.runId),
          get().loadReviewQueue(id, { runId: job.runId }),
          get().loadReviewTable(id, { runId: job.runId }),
        ]);
      }
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, error: e.message } } }));
      throw e;
    }
  },

  async cancelMultimodalReviewJob(taskId, jobId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !jobId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, multimodalCancelling: true, error: null } } }));
    try {
      const job = await structuredExtractionApi.cancelMultimodalReviewJob(id, jobId);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: { ...state.structuredExtraction.review, activeMultimodalJob: job, multimodalCancelling: false },
        },
      }));
      return job;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, multimodalCancelling: false, error: e.message } } }));
      throw e;
    }
  },

  async applyReviewSuggestion(taskId, suggestionId, action, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !suggestionId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: true, error: null } } }));
    try {
      const fn = action === "reject" ? structuredExtractionApi.rejectReviewSuggestion : structuredExtractionApi.acceptReviewSuggestion;
      const result = await fn(id, suggestionId, payload);
      const recordId = result.record?.recordId || get().structuredExtraction.review.activeRecord?.recordId;
      if (recordId) {
        const events = await structuredExtractionApi.listReviewEvents(id, recordId);
        set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, activeRecord: result.record || state.structuredExtraction.review.activeRecord, events: events.events || [] } } }));
      }
      await Promise.allSettled([get().loadReviewSummary(id), get().loadReviewQueue(id), get().loadReviewTable(id)]);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false, error: e.message } } }));
      throw e;
    }
  },

  async bulkReviewSuggestions(taskId, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: true, error: null } } }));
    try {
      const result = await structuredExtractionApi.bulkReviewSuggestions(id, payload);
      await Promise.allSettled([get().loadReviewSummary(id), get().loadReviewQueue(id), get().loadReviewTable(id)]);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false, error: e.message } } }));
      throw e;
    }
  },

  setReviewFilters(filters) {
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        review: { ...state.structuredExtraction.review, filters: { ...state.structuredExtraction.review.filters, ...filters } },
      },
    }));
  },

  async openReviewRecord(taskId, recordId, runId = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.review.activeRunId;
    if (!id || !recordId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: true, error: null } } }));
    try {
      const [record, events] = await Promise.all([
        structuredExtractionApi.getReviewRecord(id, recordId, rid),
        structuredExtractionApi.listReviewEvents(id, recordId),
      ]);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: { ...state.structuredExtraction.review, activeRecord: record, events: events.events || [], loading: false },
        },
      }));
      return { record, events: events.events || [] };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async applyReviewFieldAction(taskId, recordId, fieldKey, action, payload = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !recordId || !fieldKey) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: true, error: null } } }));
    try {
      const apiByAction = {
        accept: structuredExtractionApi.acceptReviewField,
        edit: structuredExtractionApi.editReviewField,
        reject: structuredExtractionApi.rejectReviewField,
        lock: structuredExtractionApi.lockReviewField,
        unlock: structuredExtractionApi.unlockReviewField,
      };
      const fn = apiByAction[action];
      if (!fn) throw new Error("unsupported_review_action");
      const record = await fn(id, recordId, fieldKey, payload);
      const events = await structuredExtractionApi.listReviewEvents(id, recordId);
      await get().loadReviewTable(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: { ...state.structuredExtraction.review, activeRecord: record, events: events.events || [], saving: false },
        },
      }));
      return record;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false, error: e.message } } }));
      throw e;
    }
  },

  async revertReviewEvent(taskId, eventId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const activeRecord = get().structuredExtraction.review.activeRecord;
    if (!id || !eventId) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: true, error: null } } }));
    try {
      const record = await structuredExtractionApi.revertReviewEvent(id, eventId);
      const events = await structuredExtractionApi.listReviewEvents(id, record.recordId || activeRecord?.recordId);
      await get().loadReviewTable(id);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          review: { ...state.structuredExtraction.review, activeRecord: record, events: events.events || [], saving: false },
        },
      }));
      return record;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false, error: e.message } } }));
      throw e;
    }
  },

  async bulkReviewAction(taskId, payload) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: true, error: null } } }));
    try {
      const result = await structuredExtractionApi.bulkReviewAction(id, payload);
      await get().loadReviewTable(id);
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false } } }));
      return result;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, review: { ...state.structuredExtraction.review, saving: false, error: e.message } } }));
      throw e;
    }
  },

  async loadExtractionExports(taskId) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, loading: true, error: null } } }));
    try {
      const [runsResult, exportsResult] = await Promise.all([
        structuredExtractionApi.listReviewRuns(id),
        structuredExtractionApi.listExports(id),
      ]);
      const runs = runsResult.runs || [];
      const items = exportsResult.exports || [];
      const currentRunId = get().structuredExtraction.exports.selectedRunId;
      const selectedRunId = runs.some((run) => run.runId === currentRunId) ? currentRunId : runs[0]?.runId || null;
      let preview = null;
      if (selectedRunId) {
        preview = await structuredExtractionApi.previewExport(id, selectedRunId);
      }
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          exports: {
            ...state.structuredExtraction.exports,
            runs,
            items,
            selectedRunId,
            preview,
            activeExport: state.structuredExtraction.exports.activeExport || items[0] || null,
            loading: false,
          },
        },
      }));
      return { runs, exports: items, preview };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async previewExtractionExport(taskId, runId = null) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    const rid = runId || get().structuredExtraction.exports.selectedRunId;
    if (!id || !rid) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, loading: true, error: null, selectedRunId: rid } } }));
    try {
      const preview = await structuredExtractionApi.previewExport(id, rid);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          exports: { ...state.structuredExtraction.exports, preview, selectedRunId: rid, loading: false },
        },
      }));
      return preview;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, loading: false, error: e.message } } }));
      throw e;
    }
  },

  async createExtractionExport(taskId, options = {}) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id) return null;
    const current = get().structuredExtraction.exports;
    const formats = options.formats || selectedExportFormats(current.selectedFormats);
    const runId = options.runId || current.selectedRunId;
    if (!runId) throw new Error("请先选择一个已完成的抽取运行");
    if (!formats.length) throw new Error("请至少选择一种导出格式");
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, creating: true, error: null } } }));
    try {
      const created = await structuredExtractionApi.createExport(id, {
        runId,
        formats,
        includeRejected: options.includeRejected ?? false,
        includeBaseValues: options.includeBaseValues ?? true,
        includeReviewMetadata: options.includeReviewMetadata ?? true,
      });
      const [exportsResult, task, preview] = await Promise.all([
        structuredExtractionApi.listExports(id),
        structuredExtractionApi.getTask(id),
        structuredExtractionApi.previewExport(id, runId),
      ]);
      set((state) => ({
        structuredExtraction: {
          ...state.structuredExtraction,
          activeTask: task,
          tasks: state.structuredExtraction.tasks.map((item) => item.taskId === task.taskId ? task : item),
          exports: {
            ...state.structuredExtraction.exports,
            items: exportsResult.exports || [],
            activeExport: created,
            preview,
            selectedRunId: runId,
            creating: false,
          },
        },
      }));
      return created;
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, creating: false, error: e.message } } }));
      throw e;
    }
  },

  async downloadExtractionExport(taskId, exportId, format) {
    const id = taskId || get().structuredExtraction.activeTaskId;
    if (!id || !exportId || !format) return null;
    set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, downloading: true, error: null } } }));
    try {
      const response = await structuredExtractionApi.downloadExport(id, exportId, format);
      const blob = await response.blob();
      const ext = format === "markdown" ? "md" : format;
      const filename = filenameFromContentDisposition(response.headers.get("Content-Disposition"), `${exportId}.${ext}`);
      if (typeof window !== "undefined" && typeof document !== "undefined") {
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.URL.revokeObjectURL(url);
      }
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, downloading: false } } }));
      return { blob, filename };
    } catch (e) {
      set((state) => ({ structuredExtraction: { ...state.structuredExtraction, exports: { ...state.structuredExtraction.exports, downloading: false, error: e.message } } }));
      throw e;
    }
  },

  setExtractionExportFormats(formats) {
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        exports: {
          ...state.structuredExtraction.exports,
          selectedFormats: { ...state.structuredExtraction.exports.selectedFormats, ...formats },
        },
      },
    }));
  },

  setExtractionExportRun(runId) {
    set((state) => ({
      structuredExtraction: {
        ...state.structuredExtraction,
        exports: { ...state.structuredExtraction.exports, selectedRunId: runId },
      },
    }));
  },

  async loadWorkflowTemplates() {
    try {
      const { templates, categories } = await workflowApi.templates();
      set((state) => ({ workflow: { ...state.workflow, templates, categories: categories || [] } }));
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, error: e.message } }));
    }
  },

  async loadWorkflowList() {
    try {
      const { workflows } = await workflowApi.list();
      set((state) => ({ workflow: { ...state.workflow, list: workflows } }));
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, error: e.message } }));
    }
  },

  async createWorkflow({ templateId, topic, scope }) {
    set((state) => ({ workflow: { ...state.workflow, creating: true, error: null } }));
    try {
      const detail = await workflowApi.create({ template_id: templateId, topic, scope: scope || "library" });
      set((state) => ({
        workflow: {
          ...state.workflow,
          creating: false,
          activeId: detail.workflow_id,
          detail,
          view: "console",
          live: emptyWorkflowLive({ status: detail.status }),
          preview: emptyWorkflowPreview(),
          insights: emptyWorkflowInsights(),
          sidebarTab: "artifacts",
        },
      }));
      get().loadWorkflowList();
      return detail;
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, creating: false, error: e.message } }));
      throw e;
    }
  },

  async createAndStartWorkflow({ templateId, topic, scope }) {
    set((state) => ({ workflow: { ...state.workflow, creating: true, error: null } }));
    try {
      const detail = await workflowApi.create({ template_id: templateId, topic, scope: scope || "library" });
      set((state) => ({
        workflow: {
          ...state.workflow,
          creating: false,
          activeId: detail.workflow_id,
          detail,
          view: "console",
          live: emptyWorkflowLive({ status: "running", streaming: true }),
          preview: emptyWorkflowPreview(),
          insights: emptyWorkflowInsights(),
          sidebarTab: "artifacts",
        },
      }));
      await workflowApi.start(detail.workflow_id);
      get()._streamWorkflow(detail.workflow_id, { after: 0, preserveOutput: false });
      get().loadWorkflowList();
      return detail;
    } catch (e) {
      set((state) => ({
        workflow: {
          ...state.workflow,
          creating: false,
          error: e.message,
          live: { ...state.workflow.live, streaming: false, error: e.message },
        },
      }));
      throw e;
    }
  },

  async openWorkflow(workflowId) {
    set((state) => ({ workflow: { ...state.workflow, loading: true, activeId: workflowId, view: "console", error: null, preview: emptyWorkflowPreview(), insights: emptyWorkflowInsights() } }));
    try {
      const detail = await workflowApi.get(workflowId);
      // Rehydrate history so re-entering a finished run isn't blank: latest
      // agent-step generated content + the run log rebuilt from persisted events.
      const histOutput = workflowOutputFromDetail(detail);
      const histLog = detail.history_log || [];
      const nextEventIndex = typeof detail.next_event_index === "number" ? detail.next_event_index : 0;
      set((state) => ({
        workflow: { ...state.workflow, loading: false, detail, live: emptyWorkflowLive({ artifacts: detail.artifacts || [], log: histLog, output: histOutput, status: detail.status, nextEventIndex }) },
      }));
      await get().loadWorkflowInsights(workflowId);
      // Reconnect to a live stream if the run is in flight.
      if (detail.status === "running") get()._streamWorkflow(workflowId, { after: nextEventIndex, preserveOutput: true });
      return detail;
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, loading: false, error: e.message } }));
      throw e;
    }
  },

  backToGallery() {
    set((state) => ({ workflow: { ...state.workflow, view: "gallery", activeId: null, detail: null, preview: emptyWorkflowPreview(), insights: emptyWorkflowInsights(), sidebarTab: "artifacts" } }));
    get().loadWorkflowList();
  },

  async loadWorkflowInsights(workflowId) {
    const id = workflowId || get().workflow.activeId;
    if (!id) return null;
    set((state) => ({ workflow: { ...state.workflow, insights: emptyWorkflowInsights({ loading: true }) } }));
    try {
      const data = await workflowApi.insights(id);
      set((state) => ({ workflow: { ...state.workflow, insights: emptyWorkflowInsights({ data }) } }));
      return data;
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, insights: emptyWorkflowInsights({ error: e.message }) } }));
      return null;
    }
  },

  selectWorkflowSidebarTab(tab) {
    set((state) => ({ workflow: { ...state.workflow, sidebarTab: tab || "artifacts" } }));
  },

  selectWorkflowResult() {
    set((state) => ({ workflow: { ...state.workflow, preview: emptyWorkflowPreview() } }));
  },

  selectWorkflowStage(stageId) {
    set((state) => ({
      workflow: {
        ...state.workflow,
        preview: emptyWorkflowPreview({ mode: "stage", selectedStage: stageId }),
      },
    }));
  },

  selectWorkflowEvidenceCard(evidenceId) {
    set((state) => ({
      workflow: {
        ...state.workflow,
        preview: emptyWorkflowPreview({ mode: "evidence", selectedEvidenceId: evidenceId }),
      },
    }));
  },

  selectWorkflowDiagnostic(diagnosticId) {
    set((state) => ({
      workflow: {
        ...state.workflow,
        preview: emptyWorkflowPreview({ mode: "diagnostic", selectedDiagnosticId: diagnosticId }),
      },
    }));
  },

  async selectWorkflowArtifact(artifactId, workflowId) {
    const id = workflowId || get().workflow.activeId;
    if (!id || !artifactId) return null;
    set((state) => ({
      workflow: {
        ...state.workflow,
        preview: emptyWorkflowPreview({ mode: "artifact", selectedArtifactId: artifactId, loading: true }),
      },
    }));
    try {
      const artifact = await workflowApi.artifact(id, artifactId);
      set((state) => ({
        workflow: {
          ...state.workflow,
          preview: emptyWorkflowPreview({ mode: "artifact", selectedArtifactId: artifactId, artifact }),
        },
      }));
      return artifact;
    } catch (e) {
      set((state) => ({
        workflow: {
          ...state.workflow,
          preview: emptyWorkflowPreview({ mode: "artifact", selectedArtifactId: artifactId, error: e.message }),
        },
      }));
      throw e;
    }
  },

  async startWorkflow(workflowId, { resume = false } = {}) {
    const id = workflowId || get().workflow.activeId;
    if (!id) return;
    set((state) => ({ workflow: { ...state.workflow, live: emptyWorkflowLive({ artifacts: state.workflow.detail?.artifacts || [], status: "running", streaming: true }) } }));
    try {
      if (resume) await workflowApi.resume(id);
      else await workflowApi.start(id);
      get()._streamWorkflow(id, { after: 0, preserveOutput: false });
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, live: { ...state.workflow.live, streaming: false, error: e.message } } }));
    }
  },

  async pauseWorkflow(workflowId) {
    const id = workflowId || get().workflow.activeId;
    if (!id) return;
    // Pause is cooperative (between steps) — a single corpus/agent step can't be
    // interrupted mid-flight. Give immediate feedback so it doesn't feel ignored.
    set((state) => ({ workflow: { ...state.workflow, live: { ...state.workflow.live, pauseRequested: true, log: [...(state.workflow.live.log || []), { at: Date.now(), line: "已请求暂停 · 将在当前步骤完成后生效" }] } } }));
    try {
      await workflowApi.pause(id);
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, error: e.message } }));
    }
  },

  async deleteWorkflow(workflowId) {
    try {
      await workflowApi.remove(workflowId);
      if (get().workflow.activeId === workflowId) get().backToGallery();
      else get().loadWorkflowList();
    } catch (e) {
      set((state) => ({ workflow: { ...state.workflow, error: e.message } }));
    }
  },

  _streamWorkflow(workflowId, { after = 0, preserveOutput = false } = {}) {
    const streamId = `${workflowId}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
    set((state) => ({
      workflow: {
        ...state.workflow,
        live: {
          ...state.workflow.live,
          streamId,
          streaming: true,
          nextEventIndex: after,
          ...(preserveOutput ? {} : { output: "" }),
        },
      },
    }));
    const appendLog = (line, at = Date.now()) =>
      set((state) => {
        if (state.workflow.live.streamId !== streamId) return {};
        return { workflow: { ...state.workflow, live: { ...state.workflow.live, log: [...(state.workflow.live.log || []), { at, line }] } } };
      });
    // Throttle token→output: agent-step emits many small deltas; committing each
    // one re-rendered the whole console (the jank the user saw). Buffer the text
    // and flush a few times per second.
    let tokenBuf = "";
    let flushTimer = null;
    const flushTokens = () => {
      flushTimer = null;
      if (!tokenBuf) return;
      const chunk = tokenBuf;
      tokenBuf = "";
      set((state) => {
        if (state.workflow.live.streamId !== streamId) return {};
        return { workflow: { ...state.workflow, live: { ...state.workflow.live, output: (state.workflow.live.output || "") + chunk } } };
      });
    };
    streamWorkflow(workflowId, (event) => {
      const key = workflowEventKey(event);
      let duplicate = false;
      set((state) => {
        if (state.workflow.live.streamId !== streamId) {
          duplicate = true;
          return {};
        }
        if (state.workflow.live.seenEventKeys?.[key]) {
          duplicate = true;
          return {};
        }
        return {
          workflow: {
            ...state.workflow,
            live: {
              ...state.workflow.live,
              seenEventKeys: { ...(state.workflow.live.seenEventKeys || {}), [key]: true },
              nextEventIndex: event?._event_index !== undefined ? Number(event._event_index) + 1 : state.workflow.live.nextEventIndex,
            },
          },
        };
      });
      if (duplicate) return;
      const type = event.type;
      if (type === "token") {
        tokenBuf += event.text || "";
        if (!flushTimer) flushTimer = setTimeout(flushTokens, 220);
      } else if (type === "step") {
        if (event.status === "running") tokenBuf = "";  // new step → drop buffered tail
        set((state) => (state.workflow.live.streamId === streamId
          ? { workflow: { ...state.workflow, live: { ...state.workflow.live, steps: { ...state.workflow.live.steps, [event.step_index]: { status: event.status, error: event.error, failed_stage: event.failed_stage } } } } }
          : {}));
        appendLog(`步骤「${event.label || event.step_key}」${STEP_STATUS_TEXT[event.status] || event.status}${event.error ? `：${event.error}` : ""}`, event.ts ? event.ts * 1000 : Date.now());
      } else if (type === "stage" && event.stage && event.stage !== "job") {
        set((state) => (state.workflow.live.streamId === streamId
          ? { workflow: { ...state.workflow, live: { ...state.workflow.live, stages: { ...state.workflow.live.stages, [event.stage]: event.status } } } }
          : {}));
        appendLog(`阶段「${event.label || event.stage}」${STEP_STATUS_TEXT[event.status] || event.status}`, event.ts ? event.ts * 1000 : Date.now());
      } else if (type === "artifact") {
        set((state) => {
          if (state.workflow.live.streamId !== streamId) return {};
          const exists = state.workflow.live.artifacts.some((a) => a.artifact_id === event.artifact_id);
          if (exists) return {};
          return { workflow: { ...state.workflow, live: { ...state.workflow.live, artifacts: [...state.workflow.live.artifacts, event] } } };
        });
        appendLog(`产出：${event.label || event.artifact_type || event.artifact_id}`, event.ts ? event.ts * 1000 : Date.now());
      } else if (type === "workflow_status") {
        set((state) => (state.workflow.live.streamId === streamId
          ? { workflow: { ...state.workflow, live: { ...state.workflow.live, status: event.status } } }
          : {}));
      } else if (type === "error") {
        set((state) => (state.workflow.live.streamId === streamId
          ? { workflow: { ...state.workflow, live: { ...state.workflow.live, error: event.message } } }
          : {}));
        appendLog(`错误：${event.message || ""}`, event.ts ? event.ts * 1000 : Date.now());
      } else if (type === "done") {
        if (flushTimer) clearTimeout(flushTimer);
        flushTokens();  // commit any buffered tail before settling
        set((state) => (state.workflow.live.streamId === streamId
          ? { workflow: { ...state.workflow, live: { ...state.workflow.live, streaming: false } } }
          : {}));
        // Re-fetch authoritative persisted state once the run settles.
        const activeId = get().workflow.activeId;
        if (activeId === workflowId) {
          workflowApi.get(workflowId).then((detail) => {
            set((state) => (state.workflow.activeId === workflowId
              ? {
                workflow: {
                  ...state.workflow,
                  detail,
                  live: {
                    ...state.workflow.live,
                    artifacts: detail.artifacts || state.workflow.live.artifacts,
                    output: state.workflow.live.output || workflowOutputFromDetail(detail),
                    status: detail.status,
                  },
                },
              }
              : {}));
            get().loadWorkflowInsights(workflowId);
          }).catch(() => {});
        }
        get().loadWorkflowList();
      }
    }, { after });
  },

  async loadHomeDashboard() {
    set((state) => ({ home: { ...state.home, loading: true, error: null } }));
    try {
      const dashboard = await corpusApi.dashboard();
      set((state) => ({ home: { ...state.home, dashboard, loading: false } }));
      return dashboard;
    } catch (e) {
      set((state) => ({ home: { ...state.home, loading: false, error: e.message } }));
      throw e;
    }
  },

  async runMaintenance(action) {
    set((state) => ({
      home: {
        ...state.home,
        maintenance: {
          runningAction: action,
          jobId: null,
          events: [],
          error: null,
          startedAt: Date.now(),
          completedAt: null,
          lastStatus: null,
          lastAction: action,
        },
      },
    }));
    try {
      const job = await corpusApi.runMaintenance(action);
      set((state) => ({
        home: { ...state.home, maintenance: { ...state.home.maintenance, jobId: job.job_id } },
      }));
      streamLiteratureSearchJob(job.job_id, async (event) => {
        set((state) => ({
          home: {
            ...state.home,
            maintenance: { ...state.home.maintenance, events: [...state.home.maintenance.events, event] },
          },
        }));
        if (event.type === "error") {
          set((state) => ({
            home: { ...state.home, maintenance: { ...state.home.maintenance, error: event.message || "任务失败", lastStatus: "failed" } },
          }));
        }
        if (event.type === "done" || event.type === "error") {
          set((state) => ({
            home: {
              ...state.home,
              maintenance: {
                ...state.home.maintenance,
                runningAction: null,
                completedAt: Date.now(),
                lastStatus: state.home.maintenance.lastStatus || "completed",
              },
            },
          }));
          await get().loadHomeDashboard();
        }
      });
      return job;
    } catch (e) {
      set((state) => ({
        home: {
          ...state.home,
          maintenance: { ...state.home.maintenance, runningAction: null, error: e.message, lastStatus: "failed", completedAt: Date.now() },
        },
      }));
      throw e;
    }
  },

  async loadModules() {
    try {
      const modules = await fetchModules();
      set({ modules, modulesLoaded: true, appError: null });
      get().loadHomeDashboard().catch(() => {});
      if (modules.length && !get().activeModuleId) {
        let defaultModule = modules[0].id;
        try {
          const effective = await settingsApi.effective();
          get().updateSettings({ effective });
          const configured = effective["general.default_module"]?.value;
          if (configured && modules.some((m) => m.id === configured)) defaultModule = configured;
          const defaultTab = effective["general.default_literature_tab"]?.value;
          if (defaultTab) get().setLiteratureToolTab(defaultTab);
        } catch {
          // Settings are optional for boot; keep the platform usable if this endpoint fails.
        }
        await get().selectModule(defaultModule);
        // Preload a default module/session in the background, but land on the
        // Research Index Health home page after startup (Block 0).
        set({ homeOpen: true });
      }
    } catch (e) {
      set({ modulesLoaded: true });
      get().setAppError(`后端连接失败：${e.message || "无法加载模块"}`);
    }
  },

  async loadLibrary() {
    const library = await fetchLibrary();
    set({ library, libraryLoaded: true });
  },

  async loadSessions(moduleId) {
    const sessions = await sessionApi.list(moduleId);
    const sessionsById = { ...get().sessionsById };
    const order = [];
    for (const raw of sessions) {
      const s = { ...raw, ...(sessionsById[raw.id] || {}) };
      s.title = raw.title || s.title;
      s.tags = raw.tags || [];
      s.favorite = !!raw.favorite;
      s.pinned = !!raw.pinned;
      s.archived = !!raw.archived;
      s.deletedAt = raw.deletedAt;
      s.updatedAt = raw.updatedAt;
      sessionsById[s.id] = s;
      order.push(s.id);
    }
    set((state) => ({
      sessionsById,
      sessionOrderByModule: { ...state.sessionOrderByModule, [moduleId]: order },
    }));
    return order;
  },

  async selectModule(moduleId) {
    try {
      get().closeSessionContextMenu();
      get().updateSettings({ open: false });
      const state = get();
      let order = await get().loadSessions(moduleId);
      let activeId = state.activeSessionByModule[moduleId];
      let createdFresh = false;
      const remembered = window.localStorage.getItem(`activeSession:${moduleId}`);
      if (remembered && order.includes(remembered)) activeId = remembered;

      if (!activeId || !order.includes(activeId)) {
        if (order.length === 0) {
          const created = await sessionApi.create({ module_id: moduleId, title: "新对话" });
          const s = created;
          createdFresh = true;
          set((current) => ({
            sessionsById: { ...current.sessionsById, [s.id]: s },
            sessionOrderByModule: { ...current.sessionOrderByModule, [moduleId]: [s.id] },
          }));
          order = [s.id];
          activeId = s.id;
        } else {
          activeId = order[0];
        }
      }

      set({
        activeModuleId: moduleId,
        homeOpen: false,
        workflowOpen: false,
        structuredExtractionOpen: false,
        appError: null,
        activeSessionByModule: { ...get().activeSessionByModule, [moduleId]: activeId },
        rightPanelTab: "evidence",
        literatureSearch: { ...get().literatureSearch, preview: emptyLiteraturePreview() },
      });
      if (createdFresh) {
        window.localStorage.setItem(`activeSession:${moduleId}`, activeId);
        return get().sessionsById[activeId] || null;
      }
      try {
        await get().selectSession(moduleId, activeId);
      } catch (sessionError) {
        if (!isMissingSessionError(sessionError)) throw sessionError;
        const staleId = activeId;
        const nextId = order.find((id) => id !== staleId);
        set((current) => {
          const { [staleId]: _removed, ...remainingSessions } = current.sessionsById;
          return {
            sessionsById: remainingSessions,
            sessionOrderByModule: {
              ...current.sessionOrderByModule,
              [moduleId]: (current.sessionOrderByModule[moduleId] || []).filter((id) => id !== staleId),
            },
          };
        });
        if (nextId) {
          await get().selectSession(moduleId, nextId);
        } else {
          window.localStorage.removeItem(`activeSession:${moduleId}`);
          await get().newSession(moduleId);
        }
      }
    } catch (e) {
      get().setAppError(`打开会话失败：${e.message || "请检查后端服务"}`);
      return null;
    }
  },

  async newSession(moduleId) {
    if (moduleId !== "literature_search") return null;
    try {
      const created = await sessionApi.create({ module_id: moduleId, title: "新对话" });
      const s = created;
      set((state) => ({
        appError: null,
        sessionsById: { ...state.sessionsById, [s.id]: s },
        sessionOrderByModule: { ...state.sessionOrderByModule, [moduleId]: [s.id, ...(state.sessionOrderByModule[moduleId] || [])] },
        activeSessionByModule: { ...state.activeSessionByModule, [moduleId]: s.id },
        rightPanelTab: "evidence",
        literatureSearch: { ...state.literatureSearch, preview: emptyLiteraturePreview() },
      }));
      window.localStorage.setItem(`activeSession:${moduleId}`, s.id);
      return s;
    } catch (e) {
      get().setAppError(`新建会话失败：${e.message || "请检查后端服务"}`);
      return null;
    }
  },

  async selectSession(moduleId, sessionId) {
    try {
      const [messages, context, artifacts, jobs, researchState, attachments] = await Promise.all([
        sessionApi.messages(sessionId),
        sessionApi.context(sessionId),
        sessionApi.artifacts(sessionId),
        sessionApi.jobs(sessionId),
        sessionApi.researchState(sessionId).catch(() => null),
        sessionApi.attachments(sessionId).catch(() => []),
      ]);
      const recentSearch = context.recentSearchResults?.[0];
      const retrievalUsed = recentSearch?.queryPlan?.retrievalUsed || recentSearch?.queryPlanRaw?.retrieval_used;
      set((state) => ({
        // Opening a conversation always leaves the index-health home view, so a
        // sidebar click / new session / context-menu "打开" actually shows the chat.
        // (Startup re-opens home explicitly in loadModules AFTER this runs.)
        homeOpen: false,
        workflowOpen: false,
        structuredExtractionOpen: false,
        appError: null,
        activeSessionByModule: { ...state.activeSessionByModule, [moduleId]: sessionId },
        literatureSearch: { ...state.literatureSearch, preview: emptyLiteraturePreview() },
        sessionsById: {
          ...state.sessionsById,
          [sessionId]: {
            ...(state.sessionsById[sessionId] || { id: sessionId, moduleId, title: "新对话" }),
            messages,
            steps: [],
            papers: recentSearch?.results || [],
            searchMeta: recentSearch
              ? {
                  type: "search_meta",
                  queryPlan: recentSearch.queryPlan,
                  retrievalUsed,
                  query_plan: recentSearch.queryPlanRaw,
                  retrieval_used: retrievalUsed,
                }
              : null,
            coverage: recentSearch ? { ...(recentSearch.coverage || {}), breadth: recentSearch.breadth || null } : null,
            context,
            linkedArtifacts: artifacts,
            jobs,
            researchState,
            attachments,
            uploadingAttachments: false,
            attachmentError: null,
            streaming: false,
          },
        },
      }));
      window.localStorage.setItem(`activeSession:${moduleId}`, sessionId);
    } catch (e) {
      get().setAppError(`加载会话失败：${e.message || "请检查后端服务"}`);
      throw e;
    }
  },


  // Block 6a: refresh just the Shared Research State (e.g. after a turn ends or
  // the panel is opened) without re-loading the whole session.
  async loadResearchState() {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId) return;
    try {
      const researchState = await sessionApi.researchState(sessionId);
      get().updateSession(sessionId, (s) => ({ ...s, researchState }));
    } catch {
      // best-effort; the panel keeps the last good state
    }
  },

  // Block 6b: curate a candidate paper (accept / exclude / needs_review). The
  // endpoint returns the refreshed research state so the panel re-renders at once.
  async setPaperStatus(paperId, status, note) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId) return;
    const researchState = await sessionApi.setPaperStatus(sessionId, { paper_id: paperId, status, note });
    get().updateSession(sessionId, (s) => ({ ...s, researchState }));
  },

  async setEvidenceStatus(evidenceItemId, status, note) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId || !evidenceItemId) return;
    const researchState = await sessionApi.setEvidenceStatus(sessionId, {
      evidence_item_id: evidenceItemId,
      status,
      note,
    });
    get().updateSession(sessionId, (s) => ({ ...s, researchState }));
  },

  setLiteratureEvidenceFilter(filter) {
    const allowed = ["current", "pool", "accepted", "needs_review", "excluded"];
    const next = allowed.includes(filter) ? filter : "current";
    set((state) => ({ literatureSearch: { ...state.literatureSearch, evidenceFilter: next } }));
  },

  // Block 6b: author non-derivable facts (objective / stage / excluded
  // directions / open questions / next actions). Returns refreshed state.
  async updateResearchState(fields) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId) return;
    const researchState = await sessionApi.updateResearchState(sessionId, fields);
    get().updateSession(sessionId, (s) => ({ ...s, researchState }));
  },

  setRightPanelTab(tab) {
    const next = ["evidence", "papers", "audit"].includes(tab) ? tab : "evidence";
    set({ rightPanelTab: next });
  },

  selectLiteratureAnswer() {
    set((state) => ({ literatureSearch: { ...state.literatureSearch, preview: emptyLiteraturePreview() } }));
  },

  selectLiteratureEvidence(evidenceId) {
    set((state) => ({
      literatureSearch: {
        ...state.literatureSearch,
        preview: emptyLiteraturePreview({ mode: "evidence", selectedEvidenceId: evidenceId || null }),
      },
    }));
  },

  selectLiteraturePaper(paperId) {
    set((state) => ({
      literatureSearch: {
        ...state.literatureSearch,
        preview: emptyLiteraturePreview({ mode: "paper", selectedPaperId: paperId || null }),
      },
    }));
  },

  selectLiteratureAudit(auditId) {
    set((state) => ({
      literatureSearch: {
        ...state.literatureSearch,
        preview: emptyLiteraturePreview({ mode: "audit", selectedAuditId: auditId || null }),
      },
    }));
  },

  setDeveloperMode(on) {
    window.localStorage.setItem("developerMode", on ? "1" : "0");
    set({ developerMode: !!on });
    // Leaving developer mode while parked on a tool console → return to Chat.
    if (!on) get().setLiteratureToolTab("chat");
  },

  setChatAnswerMode(mode) {
    set({ chatAnswerMode: mode === "deep" ? "deep" : "quick" });
  },

  setChatRole(role) {
    set({ chatRole: role || "general" });
  },

  setChatResearchMode(mode) {
    if (mode === "deep") {
      set({ chatRole: "analysis", chatAnswerMode: "deep" });
    } else if (mode === "evidence") {
      set({ chatRole: "retrieval", chatAnswerMode: "quick" });
    } else {
      set({ chatRole: "general", chatAnswerMode: "quick" });
    }
  },

  // Block 5: user confirms a deep-research suggestion → switch the intent to deep
  // and re-run the SAME question (one mode source of truth: chatAnswerMode).
  startDeepResearch(question) {
    const sessionId = get().activeSessionByModule[get().activeModuleId];
    if (sessionId) get().updateSession(sessionId, (s) => ({ ...s, deepSuggestion: null }));
    set({ chatAnswerMode: "deep" });
    if (question && question.trim()) get().sendMessage(question.trim());
  },

  getActiveSession() {
    const state = get();
    const sessionId = state.activeSessionByModule[state.activeModuleId];
    return state.sessionsById[sessionId];
  },

  updateSession(sessionId, updater) {
    set((state) => {
      const prev = state.sessionsById[sessionId];
      if (!prev) return {};
      return { sessionsById: { ...state.sessionsById, [sessionId]: updater(prev) } };
    });
  },

  async uploadLiteratureAttachments(files) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId || !files?.length) return [];
    get().updateSession(sessionId, (s) => ({ ...s, uploadingAttachments: true, attachmentError: null }));
    const uploaded = [];
    try {
      for (const file of files) {
        const item = await sessionApi.uploadAttachment(sessionId, file);
        uploaded.push(item);
        get().updateSession(sessionId, (s) => ({
          ...s,
          attachments: [...(s.attachments || []).filter((a) => a.attachmentId !== item.attachmentId), item],
        }));
      }
      get().updateSession(sessionId, (s) => ({ ...s, uploadingAttachments: false, attachmentError: null }));
      return uploaded;
    } catch (e) {
      get().updateSession(sessionId, (s) => ({ ...s, uploadingAttachments: false, attachmentError: e.message || "附件上传失败" }));
      throw e;
    }
  },

  async deleteLiteratureAttachment(attachmentId) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId || !attachmentId) return null;
    await sessionApi.deleteAttachment(sessionId, attachmentId);
    get().updateSession(sessionId, (s) => ({
      ...s,
      attachments: (s.attachments || []).filter((item) => item.attachmentId !== attachmentId),
    }));
    return { deleted: true, attachmentId };
  },

  async sendMessage(text) {
    const state = get();
    const moduleId = state.activeModuleId;
    const sessionId = state.activeSessionByModule[moduleId];
    if (!moduleId || !sessionId || !text.trim()) return;

    let session = state.sessionsById[sessionId];
    get().selectLiteratureAnswer();

    // Re-edit resend: replace the last turn (drop it locally + on the backend)
    // only now, at send time — never on the edit click itself.
    if (session.editing) {
      let lastUserIdx = -1;
      for (let i = session.messages.length - 1; i >= 0; i--) {
        if (session.messages[i].role === "user") { lastUserIdx = i; break; }
      }
      try {
        await sessionApi.deleteLastTurn(sessionId);
      } catch {
        // if the backend delete fails the resend still proceeds as a new turn
      }
      get().updateSession(sessionId, (s) => ({
        ...s,
        editing: false,
        steps: [],
        searchMeta: null,
        coverage: null,
        messages: lastUserIdx >= 0 ? s.messages.slice(0, lastUserIdx) : s.messages,
      }));
      session = get().sessionsById[sessionId];
    }

    const history = session.messages.map((m) => ({ role: m.role, content: m.content }));

    const activeAttachments = (session.attachments || []).filter((item) => item.status === "parsed");
    const now = Date.now();
    get().updateSession(sessionId, (s) => ({
      ...s,
      title: s.messages.length === 0 ? text.slice(0, 24) : s.title,
      messages: [
        ...s.messages,
        { role: "user", content: text, at: now, attachments: activeAttachments.map(({ attachmentId, filename, status, charCount }) => ({ attachmentId, filename, status, charCount })) },
        { role: "assistant", content: "", at: now, roleUsed: get().chatRole, metadata: {} },
      ],
      steps: [],
      searchMeta: null,
      coverage: null,
      liveJobs: {},
      liveArtifacts: [],
      liveTrace: [],
      deepSuggestion: null,
      streaming: true,
      groundingChecking: false,
    }));

    const onEvent = (event) => {
      get().updateSession(sessionId, (s) => {
        const messages = [...s.messages];
        const lastIdx = messages.length - 1;

        if (event.type === "step") {
          const steps = [...s.steps];
          const idx = steps.findIndex((st) => st.label === event.label);
          if (idx >= 0) steps[idx] = { label: event.label, status: event.status, detail: event.detail };
          else steps.push({ label: event.label, status: event.status, detail: event.detail });
          return { ...s, steps };
        }
        if (event.type === "papers") {
          return { ...s, papers: event.papers };
        }
        if (event.type === "search_meta") {
          return { ...s, searchMeta: event };
        }
        if (event.type === "coverage") {
          return { ...s, coverage: event };
        }
        if (event.type === "intent_route") {
          return {
            ...s,
            messages: updateAssistantMetadata(messages, {
              route: event.route || null,
              routeLabel: event.label || null,
            }),
          };
        }
        if (event.type === "failure_explanation") {
          return {
            ...s,
            messages: updateAssistantMetadata(messages, {
              failureCode: event.code || null,
              failureMessage: event.message || "",
            }),
          };
        }
        if (event.type === "attachment_context") {
          return {
            ...s,
            messages: updateAssistantMetadata(messages, {
              usedAttachments: {
                attachmentCount: event.attachment_count ?? event.attachmentCount ?? 0,
                filenames: event.filenames || [],
              },
            }),
          };
        }
        if (event.type === "library_status") {
          return {
            ...s,
            messages: updateAssistantMetadata(messages, {
              usedLibraryStats: true,
              libraryStats: camelizeShallow(event.stats || {}),
            }),
          };
        }
        // Block 4b: surface the tool execution layer's job/artifact/trace events
        // (forwarded by 4a) in the Chat path instead of dropping them.
        if (event.type === "job") {
          const liveJobs = { ...s.liveJobs };
          const prev = liveJobs[event.job_id] || {};
          liveJobs[event.job_id] = {
            ...prev,
            job_id: event.job_id,
            job_type: event.job_type || prev.job_type,
            status: event.status || prev.status || "running",
            label: event.label || prev.label,
          };
          return { ...s, liveJobs };
        }
        if (event.type === "stage" || event.type === "progress") {
          const liveJobs = { ...s.liveJobs };
          const job = liveJobs[event.job_id];
          if (job) {
            liveJobs[event.job_id] = {
              ...job,
              phase: event.phase || event.label || job.phase,
              current: event.current ?? job.current,
              total: event.total ?? job.total,
              status: event.status === "running" || !event.status ? job.status : event.status,
            };
            return { ...s, liveJobs };
          }
          return s;
        }
        if (event.type === "artifact") {
          if (s.liveArtifacts.some((a) => a.artifact_id === event.artifact_id)) return s;
          return { ...s, liveArtifacts: [...s.liveArtifacts, event] };
        }
        if (event.type === "tool_trace") {
          // The job's terminal status arrives with its trace — mark any live job
          // it created done/failed so the progress strip stops pulsing.
          let liveJobs = s.liveJobs;
          const jobIds = event.jobs_created || [];
          if (jobIds.length) {
            liveJobs = { ...s.liveJobs };
            for (const jid of jobIds) {
              if (liveJobs[jid]) {
                liveJobs[jid] = { ...liveJobs[jid], status: event.status === "error" ? "failed" : "completed" };
              }
            }
          }
          return { ...s, liveJobs, liveTrace: [...s.liveTrace, event] };
        }
        if (event.type === "deep_research_suggestion") {
          // Block 5: quick-mode advisory only — never auto-escalates. The user
          // confirms via the card, which re-runs the question in deep mode.
          return { ...s, deepSuggestion: event };
        }
        if (event.type === "answer_reset") {
          // A prior turn's narration is process, not the answer — clear the
          // bubble so the next turn (final answer) replaces it.
          messages[lastIdx] = { ...messages[lastIdx], content: "" };
          return { ...s, messages };
        }
        if (event.type === "token") {
          messages[lastIdx] = {
            ...messages[lastIdx],
            content: messages[lastIdx].content + event.text,
          };
          return { ...s, messages };
        }
        if (event.type === "grounding_status") {
          // Block 3: the streamed answer is a provisional draft until the gate
          // resolves; the bubble shows a "校对中" state during this window.
          return { ...s, groundingChecking: event.state === "checking" };
        }
        if (event.type === "citation") {
          // Gate resolved → the answer is now final (and may have been rewritten).
          messages[lastIdx] = { ...messages[lastIdx], citation: event };
          return { ...s, messages, groundingChecking: false };
        }
        if (event.type === "error") {
          messages[lastIdx] = {
            ...messages[lastIdx],
            content: messages[lastIdx].content + `\n\n⚠ ${event.message}`,
            error: true,
          };
          return { ...s, messages };
        }
        if (event.type === "done") {
          return { ...s, streaming: false, groundingChecking: false };
        }
        return s;
      });
    };

    try {
      await streamChat(
        {
          moduleId,
          sessionId,
          message: text,
          history,
          options: {
            answer_mode: get().chatAnswerMode,
            role: get().chatRole,
            attachment_ids: activeAttachments.map((item) => item.attachmentId),
          },
        },
        onEvent
      );
      await get().loadSessions(moduleId);
      await get().selectSession(moduleId, sessionId);
    } catch (e) {
      onEvent({ type: "error", message: e.message || "网络错误" });
      onEvent({ type: "done" });
    }
  },

  // Re-edit the last sent question. NON-destructive: this only prefills the
  // composer and marks the session as "editing". The conversation stays intact;
  // the last turn is replaced only when the user actually resends (see
  // sendMessage), so clicking 编辑 never clears the chat.
  editLastMessage() {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId) return "";
    const session = get().sessionsById[sessionId];
    if (!session || session.streaming) return "";
    const msgs = session.messages;
    let lastUserIdx = -1;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === "user") { lastUserIdx = i; break; }
    }
    if (lastUserIdx < 0) return "";
    get().updateSession(sessionId, (s) => ({ ...s, editing: true }));
    return msgs[lastUserIdx].content;
  },

  cancelEdit() {
    const sessionId = get().activeSessionByModule[get().activeModuleId];
    if (sessionId) get().updateSession(sessionId, (s) => ({ ...s, editing: false }));
  },

  async loadActiveRecord() {
    const sid = get().activeSessionByModule[get().activeModuleId];
    if (!sid) return null;
    return sessionApi.record(sid);
  },

  async exportActiveSession() {
    const sid = get().activeSessionByModule[get().activeModuleId];
    if (!sid) return;
    const { filename, content } = await sessionApi.export(sid);
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "research-record.md";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  setLiteratureToolTab(tab) {
    set((state) => ({
      literatureSearch: { ...state.literatureSearch, activeToolTab: tab },
    }));
  },

  updateLiteratureSearch(patch) {
    set((state) => ({
      literatureSearch: { ...state.literatureSearch, ...patch },
    }));
  },

  updateSettings(patch) {
    set((state) => ({
      settings: { ...state.settings, ...patch },
    }));
  },

  async openSettings(tab = "general") {
    get().updateSettings({ open: true, activeTab: tab, error: null });
    await get().loadSettings();
  },

  closeSettings() {
    get().updateSettings({ open: false, dirty: false });
  },

  setSettingsTab(tab) {
    get().updateSettings({ activeTab: tab });
  },

  async loadSettings() {
    get().updateSettings({ loading: true, error: null });
    try {
      const [values, effective, diagnostics, readiness] = await Promise.all([
        settingsApi.get(),
        settingsApi.effective(),
        settingsApi.diagnostics(),
        settingsApi.readiness(),
      ]);
      get().updateSettings({
        values,
        draft: structuredClone(values),
        effective,
        diagnostics,
        readiness,
        loading: false,
        dirty: false,
      });
      return values;
    } catch (e) {
      get().updateSettings({ loading: false, error: e.message });
      throw e;
    }
  },

  editSettings(scope, key, value) {
    set((state) => ({
      settings: {
        ...state.settings,
        dirty: true,
        draft: {
          ...(state.settings.draft || {}),
          [scope]: {
            ...((state.settings.draft || {})[scope] || {}),
            [key]: value,
          },
        },
      },
    }));
  },

  async saveSettings(scope) {
    const draft = get().settings.draft || {};
    const payload = scope ? { [scope]: draft[scope] || {} } : draft;
    return get()._persistSettings(() => settingsApi.patch(payload));
  },

  // Save only the given fields (each `[scope, key]`), grouped into a partial
  // patch. Lets a UI category that spans multiple backend scopes (e.g. 智能体
  // touches `agent` + `memory`) save without disturbing other categories' fields.
  async saveCategory(fields) {
    const draft = get().settings.draft || {};
    const payload = {};
    for (const [scope, key] of fields) {
      if (!(scope in payload)) payload[scope] = {};
      payload[scope][key] = (draft[scope] || {})[key];
    }
    return get()._persistSettings(() => settingsApi.patch(payload));
  },

  // Revert only the given fields in the draft back to the last-saved values.
  resetCategory(fields) {
    set((state) => {
      const values = state.settings.values || {};
      const draft = structuredClone(state.settings.draft || {});
      for (const [scope, key] of fields) {
        draft[scope] = draft[scope] || {};
        draft[scope][key] = (values[scope] || {})[key];
      }
      return { settings: { ...state.settings, draft } };
    });
  },

  async resetSettings(scope) {
    return get()._persistSettings(() => settingsApi.reset(scope));
  },

  // Shared tail for save/reset: run the mutation, then refresh the runtime mirrors
  // (values/draft/effective/diagnostics/readiness) so Ready/Not-Ready stays current.
  async _persistSettings(mutate) {
    get().updateSettings({ saving: true, error: null });
    try {
      const values = await mutate();
      const [effective, diagnostics, readiness] = await Promise.all([
        settingsApi.effective(),
        settingsApi.diagnostics(),
        settingsApi.readiness(),
      ]);
      get().updateSettings({
        values,
        draft: structuredClone(values),
        effective,
        diagnostics,
        readiness,
        saving: false,
        dirty: false,
      });
      const defaultTab = effective["general.default_literature_tab"]?.value;
      if (defaultTab) get().setLiteratureToolTab(defaultTab);
      return values;
    } catch (e) {
      get().updateSettings({ saving: false, error: e.message });
      throw e;
    }
  },

  async refreshDiagnostics() {
    get().updateSettings({ loading: true, error: null });
    try {
      const diagnostics = await settingsApi.diagnostics();
      get().updateSettings({ diagnostics, loading: false });
      return diagnostics;
    } catch (e) {
      get().updateSettings({ loading: false, error: e.message });
      throw e;
    }
  },

  async testModelSettings(payload = {}) {
    get().updateSettings({ loading: true, error: null, modelTest: null });
    try {
      const result = await settingsApi.testModel(payload);
      get().updateSettings({ loading: false, modelTest: result });
      return result;
    } catch (e) {
      get().updateSettings({ loading: false, error: e.message });
      throw e;
    }
  },

  // Refresh runtime mirrors (values + effective) WITHOUT touching the draft, so
  // unsaved edits (provider, chat_model, ...) survive a key save/clear.
  async refreshSettingsStatus() {
    try {
      const [values, effective, readiness] = await Promise.all([
        settingsApi.get(),
        settingsApi.effective(),
        settingsApi.readiness(),
      ]);
      get().updateSettings({ values, effective, readiness });
    } catch (e) {
      get().updateSettings({ error: e.message });
    }
  },

  async saveModelSecret(provider, apiKey) {
    get().updateSettings({ saving: true, error: null });
    try {
      // Persist the current model draft first so provider/chat_model are saved
      // together with the key; otherwise the status refresh would show provider
      // "none" (the selection lived only in the unsaved draft).
      const draft = get().settings.draft || {};
      await settingsApi.patch({ models: draft.models || {} });
      await settingsApi.setSecret({ provider, api_key: apiKey });
      await get().refreshSettingsStatus();
      get().updateSettings({ saving: false });
    } catch (e) {
      get().updateSettings({ saving: false, error: e.message });
      throw e;
    }
  },

  async clearModelSecret(provider) {
    get().updateSettings({ saving: true, error: null });
    try {
      await settingsApi.deleteSecret(provider);
      await get().refreshSettingsStatus();
      get().updateSettings({ saving: false });
    } catch (e) {
      get().updateSettings({ saving: false, error: e.message });
      throw e;
    }
  },

  async saveExternalSourceSecret(source, apiKey) {
    get().updateSettings({ saving: true, error: null });
    try {
      await settingsApi.setExternalSourceSecret({ source, api_key: apiKey });
      await get().loadSettings();
      get().updateSettings({ saving: false });
    } catch (e) {
      get().updateSettings({ saving: false, error: e.message });
      throw e;
    }
  },

  async clearExternalSourceSecret(source) {
    get().updateSettings({ saving: true, error: null });
    try {
      await settingsApi.deleteExternalSourceSecret(source);
      await get().loadSettings();
      get().updateSettings({ saving: false });
    } catch (e) {
      get().updateSettings({ saving: false, error: e.message });
      throw e;
    }
  },

  updateModelProfiles(patch) {
    set((state) => ({ modelProfiles: { ...state.modelProfiles, ...patch } }));
  },

  async loadModelProfiles() {
    get().updateModelProfiles({ loading: true, error: null });
    try {
      const items = await modelProfilesApi.list();
      get().updateModelProfiles({ items, loading: false });
      return items;
    } catch (e) {
      get().updateModelProfiles({ loading: false, error: e.message });
      throw e;
    }
  },

  async createModelProfile(payload) {
    get().updateModelProfiles({ error: null });
    try {
      await modelProfilesApi.create(payload);
      await get().loadModelProfiles();
    } catch (e) {
      get().updateModelProfiles({ error: e.message });
      throw e;
    }
  },

  async updateModelProfile(id, payload) {
    get().updateModelProfiles({ error: null });
    try {
      await modelProfilesApi.update(id, payload);
      await get().loadModelProfiles();
      await get().refreshSettingsStatus();
    } catch (e) {
      get().updateModelProfiles({ error: e.message });
      throw e;
    }
  },

  async removeModelProfile(id) {
    try {
      await modelProfilesApi.remove(id);
      await get().loadModelProfiles();
      await get().refreshSettingsStatus();
    } catch (e) {
      get().updateModelProfiles({ error: e.message });
      throw e;
    }
  },

  async activateModelProfile(id) {
    try {
      await modelProfilesApi.activate(id);
      await get().loadModelProfiles();
      // refresh effective/values so models scope + agent_chat_ready reflect the switch
      await get().refreshSettingsStatus();
    } catch (e) {
      get().updateModelProfiles({ error: e.message });
      throw e;
    }
  },

  async revealModelProfile(id) {
    const { api_key } = await modelProfilesApi.reveal(id);
    return api_key;
  },

  async testModelProfile(id) {
    get().updateModelProfiles({ error: null });
    try {
      const result = await modelProfilesApi.test(id);
      get().updateModelProfiles({ testById: { ...get().modelProfiles.testById, [id]: result } });
      return result;
    } catch (e) {
      get().updateModelProfiles({ error: e.message });
      throw e;
    }
  },

  async loadLiteratureStatus() {
    get().updateLiteratureSearch({ loading: true, error: null });
    try {
      const [selfcheck, indexStatus, vectorStatus] = await Promise.allSettled([
        literatureSearchApi.selfcheck(),
        literatureSearchApi.indexStatus(),
        literatureSearchApi.vectorStatus(),
      ]);
      get().updateLiteratureSearch({
        loading: false,
        status: {
          selfcheck: selfcheck.status === "fulfilled" ? selfcheck.value : { error: selfcheck.reason.message },
          indexStatus: indexStatus.status === "fulfilled" ? indexStatus.value : { error: indexStatus.reason.message },
          vectorStatus: vectorStatus.status === "fulfilled" ? vectorStatus.value : { error: vectorStatus.reason.message },
        },
      });
    } catch (e) {
      get().updateLiteratureSearch({ loading: false, error: e.message });
    }
  },

  async runLiteratureSearch(payload) {
    get().updateLiteratureSearch({ loading: true, error: null });
    try {
      // Block 2: the Search tab consumes the auditable acquisition packet
      // (coverage / breadth / evidence_candidates) instead of the legacy result.
      const result = await literatureSearchApi.acquireEvidence(payload);
      get().updateLiteratureSearch({ loading: false, searchResults: result, toolResult: result });
      return result;
    } catch (e) {
      get().updateLiteratureSearch({ loading: false, error: e.message });
      throw e;
    }
  },

  async callLiteratureTool(apiName, payload, resultKey = "toolResult") {
    get().updateLiteratureSearch({ loading: true, error: null });
    try {
      const result = await literatureSearchApi[apiName](payload);
      get().updateLiteratureSearch({ loading: false, [resultKey]: result, toolResult: result });
      return result;
    } catch (e) {
      get().updateLiteratureSearch({ loading: false, error: e.message });
      throw e;
    }
  },

  async startLiteratureJob(apiName, payload) {
    get().updateLiteratureSearch({ loading: true, error: null });
    try {
      const activeSessionId = get().activeSessionByModule[get().activeModuleId];
      const job = await literatureSearchApi[apiName]({ ...payload, session_id: activeSessionId });
      get().updateLiteratureSearch({
        loading: false,
        activeJobId: job.job_id,
        jobsById: {
          ...get().literatureSearch.jobsById,
          [job.job_id]: { ...job, events: [] },
        },
      });
      streamLiteratureSearchJob(job.job_id, async (event) => {
        const state = get().literatureSearch;
        const current = state.jobsById[job.job_id] || job;
        const status = event.type === "done" ? "completed" : event.type === "error" ? "failed" : current.status || "running";
        get().updateLiteratureSearch({
          jobsById: {
            ...state.jobsById,
            [job.job_id]: { ...current, status, events: [...(current.events || []), event] },
          },
        });
        if (event.type === "artifact" || event.type === "done") {
          await get().loadLiteratureArtifacts();
          if (activeSessionId) await get().selectSession(get().activeModuleId, activeSessionId);
        }
      });
      return job;
    } catch (e) {
      get().updateLiteratureSearch({ loading: false, error: e.message });
      throw e;
    }
  },

  async loadLiteratureArtifacts() {
    try {
      const artifacts = await literatureSearchApi.artifacts();
      get().updateLiteratureSearch({ artifacts });
      return artifacts;
    } catch (e) {
      get().updateLiteratureSearch({ error: e.message });
      return [];
    }
  },

  async selectLiteratureArtifact(artifactId) {
    get().updateLiteratureSearch({ loading: true, error: null });
    try {
      const artifact = await literatureSearchApi.artifact(artifactId);
      get().updateLiteratureSearch({ loading: false, selectedArtifact: artifact, toolResult: artifact });
      return artifact;
    } catch (e) {
      get().updateLiteratureSearch({ loading: false, error: e.message });
      throw e;
    }
  },

  async updateActiveSessionMeta(patch) {
    const moduleId = get().activeModuleId;
    const sessionId = get().activeSessionByModule[moduleId];
    if (!sessionId) return;
    const updated = await sessionApi.update(sessionId, patch);
    set((state) => ({
      sessionsById: {
        ...state.sessionsById,
        [sessionId]: {
          ...(state.sessionsById[sessionId] || {}),
          title: updated.title,
          tags: updated.tags || [],
          favorite: !!updated.favorite,
          archived: !!updated.archived,
          updatedAt: updated.updatedAt,
          moduleId,
        },
      },
    }));
    await get().loadSessions(moduleId);
  },

  async updateSessionMeta(sessionId, patch) {
    const updated = await sessionApi.update(sessionId, patch);
    const moduleId = updated.moduleId || get().sessionsById[sessionId]?.moduleId || get().activeModuleId;
    set((state) => ({
      sessionsById: {
        ...state.sessionsById,
        [sessionId]: {
          ...(state.sessionsById[sessionId] || {}),
          title: updated.title,
          tags: updated.tags || [],
          favorite: !!updated.favorite,
          pinned: !!updated.pinned,
          archived: !!updated.archived,
          deletedAt: updated.deletedAt,
          updatedAt: updated.updatedAt,
          moduleId,
        },
      },
    }));
    await get().loadSessions(moduleId);
  },

  async favoriteSession(sessionId, favorite) {
    const updated = await sessionApi.favorite(sessionId, favorite);
    const moduleId = updated.moduleId || get().sessionsById[sessionId]?.moduleId || get().activeModuleId;
    set((state) => ({
      sessionsById: { ...state.sessionsById, [sessionId]: { ...(state.sessionsById[sessionId] || {}), favorite: updated.favorite } },
    }));
    await get().loadSessions(moduleId);
  },

  async pinSession(sessionId, pinned) {
    const updated = await sessionApi.pin(sessionId, pinned);
    const moduleId = updated.moduleId || get().sessionsById[sessionId]?.moduleId || get().activeModuleId;
    set((state) => ({
      sessionsById: { ...state.sessionsById, [sessionId]: { ...(state.sessionsById[sessionId] || {}), pinned: updated.pinned } },
    }));
    await get().loadSessions(moduleId);
  },

  async archiveSession(sessionId, archived = true) {
    const moduleId = get().activeModuleId;
    await sessionApi.archive(sessionId, archived);
    await get().loadSessions(moduleId);
    const order = get().sessionOrderByModule[moduleId] || [];
    if (get().activeSessionByModule[moduleId] === sessionId && order.length) {
      await get().selectSession(moduleId, order[0]);
    } else if (get().activeSessionByModule[moduleId] === sessionId) {
      await get().newSession(moduleId);
    }
  },

  async deleteSession(sessionId) {
    const moduleId = get().activeModuleId;
    await sessionApi.delete(sessionId);
    set((state) => {
      const { [sessionId]: _removed, ...remaining } = state.sessionsById;
      return { sessionsById: remaining };
    });
    await get().loadSessions(moduleId);
    const order = get().sessionOrderByModule[moduleId] || [];
    if (get().activeSessionByModule[moduleId] === sessionId) {
      if (order.length) await get().selectSession(moduleId, order[0]);
      else await get().newSession(moduleId);
    }
  },

  async tagSession(sessionId, tags) {
    const updated = await sessionApi.tags(sessionId, tags);
    const moduleId = updated.moduleId || get().sessionsById[sessionId]?.moduleId || get().activeModuleId;
    set((state) => ({
      sessionsById: { ...state.sessionsById, [sessionId]: { ...(state.sessionsById[sessionId] || {}), tags: updated.tags } },
    }));
    await get().loadSessions(moduleId);
  },

  openSessionContextMenu(sessionId, x, y) {
    set({ sessionContextMenu: { sessionId, x, y } });
  },

  closeSessionContextMenu() {
    set({ sessionContextMenu: null });
  },
}));
