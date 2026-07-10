# Schema Compiler Durable Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make field-definition compilation survive page navigation and browser refresh while presenting durable, phase-based progress from the PostgreSQL worker queue.

**Architecture:** A schema compilation is created before execution, linked to a durable core worker job, and updated through compiler progress callbacks. The frontend owns per-task workbench state in Zustand/sessionStorage and follows compilation events through a reconnectable SSE stream with polling fallback.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, existing core worker queue, Pydantic, React, Zustand, fetch streaming SSE, Node contract tests.

**Execution constraint:** Work locally in the existing dirty worktree. Do not commit, push, sync to the server, modify `.codex/`, or edit the concurrent citation implementation and migration `0006`.

---

### Task 1: Persist asynchronous compilation state

**Files:**
- Modify: `backend/tests/test_schema_compiler_api.py`
- Create: `backend/migrations/versions/0007_schema_compiler_async.py`
- Modify: `backend/core/memory_db.py`
- Modify: `backend/modules/structured_extraction/schema_compilation_store.py`

- [ ] Add failing tests for queued compilation creation, active-job reuse, execution progress updates, completion, and failure.
- [ ] Run `PYTHONPATH=backend pytest -q backend/tests/test_schema_compiler_api.py` and verify failures are caused by missing async state APIs.
- [ ] Add `execution_status`, `phase`, `progress`, `core_job_id`, `request_json`, `error_json`, `started_at`, and `completed_at` in the additive `0007` migration and memory schema, leaving the foundational `0005` migration unchanged.
- [ ] Add store methods `queue`, `active`, `update_progress`, `complete`, and `fail`; keep final compilation validation `status` separate from execution state.
- [ ] Re-run the focused backend tests and confirm they pass.

### Task 2: Report real compiler phases

**Files:**
- Modify: `backend/tests/test_schema_compiler_core.py`
- Modify: `backend/modules/structured_extraction/schema_compiler.py`
- Modify: `backend/modules/structured_extraction/llm_schema.py`

- [ ] Add failing tests that capture ordered progress callbacks for deterministic parsing, first model attempt, normalization, validation, optional targeted repair, and completion.
- [ ] Run the focused core tests and verify the missing callback behavior fails.
- [ ] Add a small progress-event contract and emit only real phase transitions with stable milestone percentages.
- [ ] Thread the callback through `assist_schema` and both model attempts without changing compilation semantics.
- [ ] Re-run core tests and existing Schema Compiler fixtures.

### Task 3: Execute compilation in the existing worker

**Files:**
- Modify: `backend/tests/test_schema_compiler_api.py`
- Modify: `backend/modules/structured_extraction/worker_handlers.py`
- Modify: `backend/modules/structured_extraction/shared.py`
- Modify: `backend/modules/structured_extraction/schema_compilation_store.py`

- [ ] Add failing tests for enqueue payload, handler registration, successful result persistence, and precise failed-phase persistence.
- [ ] Run focused tests and verify failure before production edits.
- [ ] Register `structured.schema_compile` on the `structured-extraction` queue.
- [ ] Reconstruct `UserContext` in the handler, run `assist_schema`, write progress to the compilation row and core job events, and finalize the result.
- [ ] Re-run focused tests.

### Task 4: Add start and reconnectable stream APIs

**Files:**
- Modify: `backend/tests/test_schema_compiler_api.py`
- Modify: `backend/api/structured_extraction_router.py`
- Modify: `backend/modules/structured_extraction/schemas.py`

- [ ] Add failing API tests for `POST /schema/compilations` returning 202, active-job reuse, user isolation, and SSE snapshot/events/done behavior.
- [ ] Run focused API tests and verify expected failures.
- [ ] Add the start endpoint and an SSE endpoint that always emits the current compilation snapshot first, then durable core job events.
- [ ] Preserve existing synchronous assist actions and existing compilation resolve/apply contracts.
- [ ] Re-run focused API tests.

### Task 5: Add frontend stream client and per-task workbench state

**Files:**
- Modify: `frontend/tests/api_client_contract.test.mjs`
- Create: `frontend/src/components/structured-extraction/schemaWorkbenchState.js`
- Modify: `frontend/src/api/client.js`
- Modify: `frontend/src/store/useAppStore.js`

- [ ] Add failing contract tests for start normalization, compilation execution fields, SSE parsing, per-task isolation, and sessionStorage serialization.
- [ ] Run `node --test frontend/tests/api_client_contract.test.mjs` and verify expected failures.
- [ ] Implement start/stream API functions and compilation execution-field normalization.
- [ ] Implement serializable per-task workbench helpers and sessionStorage persistence with safe no-browser behavior.
- [ ] Move stream ownership into Zustand, reconnect on navigation/refresh, and fall back to compilation polling after repeated stream failures.
- [ ] Ensure task-opening resets do not clear other workbenches; delete/archive clears only the matching task.
- [ ] Re-run frontend contract tests.

### Task 6: Build the progress UI and restore workflow

**Files:**
- Modify: `frontend/tests/literature_search_ui_contract.test.mjs`
- Modify: `frontend/src/components/structured-extraction/SchemaDesigner.jsx`

- [ ] Add failing UI contracts for persistent workbench selectors, phase labels, progress semantics, elapsed time, disabled duplicate submission, retry state, and result restoration.
- [ ] Run the focused UI contract test and verify expected failures.
- [ ] Replace component-local source/preview/message state with task workbench actions.
- [ ] Add a stable progress panel with determinate phase milestones and animated model/repair phases; do not simulate timer-based progress.
- [ ] Restore active/latest compilation on mount and show persistent worker errors without clearing source text.
- [ ] Re-run frontend tests and build.

### Task 7: Regression and real browser verification

**Files:**
- Test only; no additional production files expected.

- [ ] Run `PYTHONPATH=backend pytest -q backend/tests/test_schema_compiler_core.py backend/tests/test_schema_compiler_api.py backend/tests/test_postgres_migrations.py`.
- [ ] Run `node --test frontend/tests/*.test.mjs`.
- [ ] Run `PYTHONPATH=backend python -m compileall backend`, `cd frontend && npm run build`, and `git diff --check`.
- [ ] Start local PostgreSQL/backend/worker/frontend using the repository's supported development commands.
- [ ] In a real browser, submit a representative long field definition, verify phase progress, navigate away and back, refresh during execution, and confirm the same compilation resumes and final preview/apply behavior works.
- [ ] Verify the UI at desktop and narrow viewport widths, check console/network failures, and capture the exact local URL and test outcome.
- [ ] Stop only processes started for this verification and leave all changes uncommitted.
