import test from "node:test";
import assert from "node:assert/strict";

import {
  emptySchemaWorkbench,
  readSchemaWorkbenchSession,
  updateSchemaWorkbenchMap,
  writeSchemaWorkbenchSession,
} from "../src/components/structured-extraction/schemaWorkbenchState.js";

test("schema workbench state is isolated by extraction task", () => {
  let map = {};
  map = updateSchemaWorkbenchMap(map, "task-a", { definitionText: "A", phase: "semantic_compile", progress: 35 });
  map = updateSchemaWorkbenchMap(map, "task-b", { definitionText: "B" });

  assert.equal(map["task-a"].definitionText, "A");
  assert.equal(map["task-a"].progress, 35);
  assert.equal(map["task-b"].definitionText, "B");
  assert.equal(map["task-b"].progress, 0);
  assert.notEqual(map["task-a"], map["task-b"]);
});

test("schema workbench session serialization restores submitted source and progress", () => {
  const writes = new Map();
  const storage = {
    getItem: (key) => writes.get(key) ?? null,
    setItem: (key, value) => writes.set(key, value),
  };
  const map = updateSchemaWorkbenchMap({}, "task-a", {
    definitionText: "Extract endpoint",
    compilationId: "comp-1",
    executionStatus: "running",
    phase: "semantic_compile",
    progress: 35,
  });

  writeSchemaWorkbenchSession(map, storage);
  const restored = readSchemaWorkbenchSession(storage);

  assert.deepEqual(restored, map);
  assert.deepEqual(emptySchemaWorkbench(), {
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
  });
});
