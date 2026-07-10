export const SCHEMA_WORKBENCH_SESSION_KEY = "structuredExtraction:schemaWorkbenches:v1";

export function emptySchemaWorkbench(patch = {}) {
  return {
    definitionText: "",
    applyMode: "replace",
    previewTree: null,
    syncMessage: "",
    compilationId: null,
    dismissedCompilationId: null,
    executionStatus: null,
    phase: null,
    progress: 0,
    indeterminate: false,
    startedAt: null,
    updatedAt: null,
    streamState: "idle",
    error: null,
    ...patch,
  };
}

export function updateSchemaWorkbenchMap(current, taskId, patch) {
  if (!taskId) return current || {};
  const map = current || {};
  return {
    ...map,
    [taskId]: emptySchemaWorkbench({ ...(map[taskId] || {}), ...(patch || {}) }),
  };
}

export function readSchemaWorkbenchSession(storage = browserSessionStorage()) {
  if (!storage) return {};
  try {
    const parsed = JSON.parse(storage.getItem(SCHEMA_WORKBENCH_SESSION_KEY) || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).map(([taskId, value]) => [taskId, emptySchemaWorkbench(value)]));
  } catch {
    return {};
  }
}

export function writeSchemaWorkbenchSession(map, storage = browserSessionStorage()) {
  if (!storage) return;
  try {
    storage.setItem(SCHEMA_WORKBENCH_SESSION_KEY, JSON.stringify(map || {}));
  } catch {
    // Storage may be disabled or full; Zustand still preserves in-tab navigation.
  }
}

function browserSessionStorage() {
  return typeof window !== "undefined" ? window.sessionStorage : null;
}
