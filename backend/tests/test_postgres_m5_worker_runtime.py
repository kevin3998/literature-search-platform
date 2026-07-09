from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from postgres_test_utils import migrated_postgres_schema


def test_worker_claims_one_job_once_and_uses_priority_order():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            queue = JobQueue(engine)
            low = queue.enqueue("test.low", {}, priority=0)
            high = queue.enqueue("test.high", {}, priority=10)

            first = queue.claim(worker_id="worker-a", queues=["default"])
            second = queue.claim(worker_id="worker-b", queues=["default"])
            third = queue.claim(worker_id="worker-c", queues=["default"])
        finally:
            engine.dispose()

    assert first is not None
    assert first["job_id"] == high["job_id"]
    assert first["attempt_count"] == 1
    assert first["locked_by"] == "worker-a"
    assert second is not None
    assert second["job_id"] == low["job_id"]
    assert third is None


def test_worker_concurrent_claim_does_not_duplicate_jobs():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            queue = JobQueue(engine)
            job = queue.enqueue("test.once", {})

            def claim(worker_id: str):
                return queue.claim(worker_id=worker_id, queues=["default"])

            with ThreadPoolExecutor(max_workers=2) as pool:
                claimed = list(pool.map(claim, ["worker-a", "worker-b"]))
        finally:
            engine.dispose()

    claimed_ids = [item["job_id"] for item in claimed if item]
    assert claimed_ids == [job["job_id"]]


def test_worker_events_are_monotonic_when_appended_concurrently():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            queue = JobQueue(engine)
            job = queue.enqueue("test.events", {})

            def append(index: int):
                queue.append_event(job["job_id"], {"type": "progress", "index": index})

            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(append, range(12)))
            events = queue.events(job["job_id"])
        finally:
            engine.dispose()

    event_indexes = [event["_event_index"] for event in events]
    assert event_indexes == list(range(len(events)))
    assert [event["type"] for event in events].count("progress") == 12


def test_worker_retry_stale_recovery_cancel_and_heartbeat():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            queue = JobQueue(engine)
            retry_job = queue.enqueue("test.retry", {}, max_attempts=2)
            claimed = queue.claim(worker_id="worker-a", queues=["default"])
            queue.fail(claimed["job_id"], "first failure")
            retry_state = queue.get(retry_job["job_id"])

            stale_job = queue.enqueue("test.stale", {}, max_attempts=2)
            stale_claim = queue.claim(worker_id="worker-b", queues=["default"])
            with engine.begin() as conn:
                conn.execute(
                    text("update jobs set locked_at = now() - interval '120 seconds' where job_id = :job_id"),
                    {"job_id": stale_claim["job_id"]},
                )
            recovered = queue.recover_stale_jobs(lease_seconds=60)
            recovered_state = queue.get(stale_job["job_id"])

            queued_cancel = queue.enqueue("test.cancel.queued", {})
            cancelled_queued = queue.cancel(queued_cancel["job_id"])
            running_cancel = queue.enqueue("test.cancel.running", {})
            running_claim = queue.claim(worker_id="worker-c", queues=["default"])
            cancelled_running = queue.cancel(running_claim["job_id"])

            queue.heartbeat(worker_id="worker-a", queues=["default"], metadata={"pid": 123})
            workers = queue.active_workers(max_age_seconds=60)
        finally:
            engine.dispose()

    assert retry_state["status"] == "queued"
    assert retry_state["attempt_count"] == 1
    assert retry_state["error"] == "first failure"
    assert stale_job["job_id"] in recovered
    assert recovered_state["status"] == "queued"
    assert cancelled_queued["status"] == "cancelled"
    assert cancelled_running["status"] == "running"
    assert cancelled_running["cancel_requested"] is True
    assert workers and workers[0]["worker_id"] == "worker-a"


def test_worker_runtime_executes_registered_handler_to_completion():
    from core.db.engine import engine_for_url
    from core.worker.handlers import HandlerRegistry
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            queue = JobQueue(engine)
            registry = HandlerRegistry()

            def handler(job, context):
                context.events.append({"type": "progress", "value": job["payload"]["value"]})
                return {"ok": True, "value": job["payload"]["value"]}

            registry.register("test.handler", handler)
            job = queue.enqueue("test.handler", {"value": 42})
            runtime = WorkerRuntime(queue, registry, worker_id="worker-a", queues=["default"])

            assert runtime.run_once() == 1
            done = queue.get(job["job_id"])
            events = queue.events(job["job_id"])
        finally:
            engine.dispose()

    assert done["status"] == "completed"
    assert done["result"] == {"ok": True, "value": 42}
    assert any(event.get("type") == "progress" and event.get("value") == 42 for event in events)
    assert events[-1]["type"] == "done"


def test_literature_job_runner_submits_without_inline_execution_and_worker_completes():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime

    class FakeService:
        def pack(self, query: str, **_kwargs):
            return {"query": query, "artifact": "research_agent/packs/result.json"}

    with migrated_postgres_schema() as (url, schema):
        from modules.literature_search.job_runner import JobRunner
        from modules.literature_search.job_store import JobStore
        from modules.literature_search.worker_handlers import build_literature_registry

        engine = engine_for_url(url, schema=schema)
        try:
            store = JobStore(engine=engine)
            runner = JobRunner(store, FakeService())
            job = runner.submit("pack", {"query": "graphene"})

            queued = store.get(job["job_id"])
            registry = build_literature_registry(store=store, service=FakeService())
            runtime = WorkerRuntime(JobQueue(engine), registry, worker_id="worker-a", queues=["default"])
            assert runtime.run_once() == 1
            completed = store.get(job["job_id"])
            events = store.events(job["job_id"])
        finally:
            engine.dispose()

    assert queued["status"] == "queued"
    assert completed["status"] == "completed"
    assert completed["result"]["query"] == "graphene"
    assert any(event.get("type") == "artifact" for event in events)


def test_workflow_start_enqueues_and_worker_executes_orchestrator_job():
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime

    class FakeWorkflowStore:
        def __init__(self):
            self.workflow = {
                "workflow_id": "11111111-1111-4111-8111-111111111111",
                "user_id": "22222222-2222-4222-8222-222222222222",
                "status": "draft",
                "started_at": None,
                "manifest": {
                    "steps": [
                        {
                            "step_index": 0,
                            "step_key": "fake",
                            "runner": "fake-runner",
                            "label": "Fake",
                            "available": True,
                        }
                    ]
                },
                "steps": [{"step_index": 0, "status": "pending", "artifact_ids": []}],
                "engine_ref": {},
            }

        def get(self, workflow_id, *, user_id=None):
            assert workflow_id == self.workflow["workflow_id"]
            if user_id and user_id != self.workflow["user_id"]:
                raise KeyError("workflow not found")
            return self.workflow

        def set_engine_ref(self, workflow_id, **changes):
            self.workflow["engine_ref"].update(changes)

        def update_status(self, workflow_id, status, **changes):
            self.workflow["status"] = status
            self.workflow.update(changes)

    class FakeRunner:
        name = "fake-runner"

        def __init__(self):
            self.calls = 0

        def execute(self, workflow_id, step, orch_job_id, *, resume, ctx):
            self.calls += 1
            ctx.store.workflow["steps"][0]["status"] = "done"
            ctx.job_store.add_event(orch_job_id, {"type": "step", "step_index": 0, "status": "done"})

    with migrated_postgres_schema() as (url, schema):
        from modules.literature_search.job_store import JobStore
        from modules.workflow.orchestrator import WorkflowOrchestrator
        from modules.workflow.worker_handlers import build_workflow_registry

        engine = engine_for_url(url, schema=schema)
        try:
            store = FakeWorkflowStore()
            runner = FakeRunner()
            job_store = JobStore(engine=engine)
            with engine.begin() as conn:
                conn.execute(
                    text("insert into users(user_id, display_name) values(:user_id, 'Worker User')"),
                    {"user_id": store.workflow["user_id"]},
                )
            orchestrator = WorkflowOrchestrator(store, job_runner=None, job_store=job_store, service=None, runners={runner.name: runner})

            started = orchestrator.start(store.workflow["workflow_id"], user_id=store.workflow["user_id"])
            assert runner.calls == 0

            registry = build_workflow_registry(orchestrator=orchestrator)
            runtime = WorkerRuntime(JobQueue(engine), registry, worker_id="worker-a", queues=["workflow"])
            assert runtime.run_once() == 1
            job = job_store.get(started["job_id"])
        finally:
            engine.dispose()

    assert runner.calls == 1
    assert store.workflow["status"] == "completed"
    assert job["status"] == "completed"


def test_structured_evidence_packet_build_enqueues_core_job_and_worker_runs(monkeypatch):
    from core.db.engine import engine_for_url
    from core.user_context import UserContext
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime

    with migrated_postgres_schema() as (url, schema):
        from modules.structured_extraction.evidence_packets import StructuredExtractionEvidencePacketService
        from modules.structured_extraction.prompt_contract import StructuredExtractionPromptContractService
        from modules.structured_extraction.schemas import EvidencePacketBuildRequest
        from modules.structured_extraction.store import StructuredExtractionStore
        from modules.structured_extraction.worker_handlers import build_structured_extraction_registry

        engine = engine_for_url(url, schema=schema)
        try:
            user = UserContext(
                user_id="33333333-3333-4333-8333-333333333333",
                workspace_slug="33333333-3333-4333-8333-333333333333",
            )
            with engine.begin() as conn:
                conn.execute(text("insert into users(user_id, display_name) values(:user_id, 'Structured User')"), {"user_id": user.user_id})
            store = StructuredExtractionStore(engine=engine)
            task = store.create_task(name="T", user=user)
            service = StructuredExtractionEvidencePacketService(store, StructuredExtractionPromptContractService(store))

            monkeypatch.setattr(
                service,
                "_build_context",
                lambda task_id, payload, *, user: {
                    "collection_version": "col_v1",
                    "schema_version": "schema_v1",
                    "prompt_contract_version": "pc_v1",
                    "papers": [{"paper_id": "p1"}],
                    "groups": [{"group_key": "default"}],
                    "settings": {"max_chunks_per_group": 1, "max_chars_per_chunk": 200, "include_assets": False},
                },
            )
            calls = {"count": 0}

            def fake_worker(task_id, build_job_id, user_id):
                calls["count"] += 1
                store.conn.execute(
                    "update structured_extraction_evidence_packet_build_jobs set status = 'completed', phase = 'completed' where build_job_id = ?",
                    (build_job_id,),
                )
                store.conn.commit()

            monkeypatch.setattr(service, "_worker_entry", fake_worker)

            build_job = service.start_build_job(task["task_id"], EvidencePacketBuildRequest(), user=user)
            queued = JobQueue(engine).get(build_job["core_job_id"])
            assert calls["count"] == 0

            registry = build_structured_extraction_registry(evidence_packet_service=service)
            runtime = WorkerRuntime(JobQueue(engine), registry, worker_id="worker-a", queues=["structured-extraction"])
            assert runtime.run_once() == 1
            completed = service.get_build_job(task["task_id"], build_job["build_job_id"], user=user)
        finally:
            engine.dispose()

    assert queued["job_type"] == "structured.evidence_packet_build"
    assert queued["status"] == "queued"
    assert calls["count"] == 1
    assert completed["status"] == "completed"


def test_structured_run_and_multimodal_jobs_enqueue_core_jobs(monkeypatch):
    from core.db.engine import engine_for_url
    from core.user_context import UserContext
    from core.worker.queue import JobQueue
    from core.worker.runtime import WorkerRuntime

    with migrated_postgres_schema() as (url, schema):
        from modules.structured_extraction.extraction_runs import StructuredExtractionRunService
        from modules.structured_extraction.multimodal_review import StructuredExtractionMultimodalReviewService
        from modules.structured_extraction.review import StructuredExtractionReviewService
        from modules.structured_extraction.schemas import ExtractionRunStartRequest, MultimodalReviewJobCreateRequest
        from modules.structured_extraction.store import StructuredExtractionStore
        from modules.structured_extraction.worker_handlers import build_structured_extraction_registry

        engine = engine_for_url(url, schema=schema)
        try:
            user = UserContext(
                user_id="44444444-4444-4444-8444-444444444444",
                workspace_slug="44444444-4444-4444-8444-444444444444",
            )
            with engine.begin() as conn:
                conn.execute(text("insert into users(user_id, display_name) values(:user_id, 'Structured User')"), {"user_id": user.user_id})
            store = StructuredExtractionStore(engine=engine)
            task = store.create_task(name="T", user=user)
            run_service = StructuredExtractionRunService(store)
            monkeypatch.setattr(run_service, "_resolve_prompt_contract", lambda *args, **kwargs: {"prompt_contract_version": "pc_v1"})
            monkeypatch.setattr(run_service, "_resolve_packet", lambda *args, **kwargs: {"packet_version": "ep_v1"})
            monkeypatch.setattr(
                run_service,
                "_packet_items",
                lambda *args, **kwargs: [{"packet_item_id": "55555555-5555-4555-8555-555555555555", "paper_id": "p1", "field_group": "default"}],
            )
            monkeypatch.setattr(run_service, "_worker_entry", lambda task_id, run_id, user_id: store.conn.execute("update structured_extraction_runs set status = 'completed' where run_id = ?", (run_id,)) or store.conn.commit())

            run = run_service.start(task["task_id"], ExtractionRunStartRequest(collection_version="col_v1", schema_version="schema_v1"), user=user)
            run_core = JobQueue(engine).get(run["core_job_id"])

            review_service = StructuredExtractionReviewService(store)
            multimodal_service = StructuredExtractionMultimodalReviewService(store, review_service)
            monkeypatch.setattr(multimodal_service, "_model_ready", lambda user_id: {"ready": True, "default_scan_mode": "related_pages_assets", "model_snapshot": {"model": "fake"}})
            monkeypatch.setattr(review_service, "_resolve_run", lambda task_id, *, user, run_id=None: {"run_id": run["run_id"]})
            monkeypatch.setattr(multimodal_service, "_rows", lambda task_id, run_id, *, user: [{"record_id": "66666666-6666-4666-8666-666666666666", "paper_id": "p1", "fields": {"value": {"effective_value": None, "quality_flags": ["missing_required_field"]}}}])

            mm_calls = {"count": 0}

            def fake_mm_worker(task_id, run_id, job_id, user):
                mm_calls["count"] += 1
                store.conn.execute("update structured_extraction_multimodal_review_jobs set status = 'completed' where job_id = ?", (job_id,))
                store.conn.commit()

            monkeypatch.setattr(multimodal_service, "_run_job", fake_mm_worker)
            mm_job = multimodal_service.start_job(task["task_id"], run["run_id"], MultimodalReviewJobCreateRequest(), user=user)
            mm_core = JobQueue(engine).get(mm_job["core_job_id"])

            registry = build_structured_extraction_registry(run_service=run_service, multimodal_review_service=multimodal_service)
            runtime = WorkerRuntime(JobQueue(engine), registry, worker_id="worker-a", queues=["structured-extraction"], max_jobs_per_tick=2)
            assert runtime.run_once() == 2
            completed_run = run_service.get(task["task_id"], run["run_id"], user=user)
            completed_mm = multimodal_service.get_job(task["task_id"], mm_job["job_id"], user=user)
        finally:
            engine.dispose()

    assert run_core["job_type"] == "structured.extraction_run"
    assert mm_core["job_type"] == "structured.multimodal_review"
    assert completed_run["status"] == "completed"
    assert completed_mm["status"] == "completed"
    assert mm_calls["count"] == 1


def test_worker_readiness_reports_warning_error_and_ok(monkeypatch):
    from core.db.engine import engine_for_url
    from core.worker.queue import JobQueue
    from core.worker.readiness import check_worker_heartbeat

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            monkeypatch.setenv("APP_ENV", "development")
            monkeypatch.delenv("WORKER_REQUIRED", raising=False)
            warning = check_worker_heartbeat(engine, max_age_seconds=60)

            monkeypatch.setenv("WORKER_REQUIRED", "true")
            required = check_worker_heartbeat(engine, max_age_seconds=60)

            JobQueue(engine).heartbeat(worker_id="worker-a", queues=["default"])
            ok = check_worker_heartbeat(engine, max_age_seconds=60)
        finally:
            engine.dispose()

    assert warning["status"] == "warning"
    assert required["status"] == "error"
    assert ok["status"] == "ok"
    assert ok["workers"][0]["worker_id"] == "worker-a"
