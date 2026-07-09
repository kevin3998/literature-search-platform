"""Block 0: index_refresh streams real per-article progress events."""
from __future__ import annotations

from modules.literature_search.job_runner import JobRunner
from modules.literature_search.job_store import JobStore


class _FakeService:
    """Stub service whose index_build drives the progress callback like the real one."""

    def __init__(self, total: int):
        self.total = total

    def index_build(self, *, progress=None):
        for current in range(1, self.total + 1):
            if progress:
                progress(
                    {
                        "current": current,
                        "total": self.total,
                        "indexed_articles": current,
                        "documents": current * 2,
                    }
                )
        return {"indexed_articles": self.total, "indexed_documents": self.total * 2, "warnings": 0}


def test_index_refresh_emits_throttled_progress(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.sqlite")
    runner = JobRunner(store, _FakeService(total=2500))
    job = store.create("index_refresh", {})

    result = runner._index_refresh(job["job_id"], {})
    assert result["indexed_articles"] == 2500

    events = store.events(job["job_id"])
    progress = [e for e in events if e.get("type") == "progress"]
    assert progress, "expected at least one progress event"
    # throttled: far fewer than 2500 events, but the final one is always emitted
    assert len(progress) < 2500
    last = progress[-1]
    assert last["current"] == 2500
    assert last["total"] == 2500
    assert "2500/2500" in last["phase"]


def test_reap_orphaned_jobs_marks_non_terminal_as_interrupted(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.sqlite")
    queued = store.create("index_refresh", {})  # stays queued
    running = store.create("run", {})
    store.start(running["job_id"])  # running
    done = store.create("health_check", {})
    store.complete(done["job_id"], {"ok": True})  # terminal — must be left alone

    reaped = store.reap_orphaned_jobs()

    assert set(reaped) == {queued["job_id"], running["job_id"]}
    assert store.get(queued["job_id"])["status"] == "interrupted"
    assert store.get(running["job_id"])["status"] == "interrupted"
    assert store.get(done["job_id"])["status"] == "completed"
    # a terminal event is appended so any reconnecting SSE stream stops cleanly
    assert any(e.get("type") == "done" for e in store.events(running["job_id"]))
    # second call is a no-op (nothing left non-terminal)
    assert store.reap_orphaned_jobs() == []


def test_index_refresh_progress_is_monotonic(tmp_path):
    store = JobStore(db_path=tmp_path / "jobs.sqlite")
    runner = JobRunner(store, _FakeService(total=50))
    job = store.create("index_refresh", {})
    runner._index_refresh(job["job_id"], {})

    currents = [e["current"] for e in store.events(job["job_id"]) if e.get("type") == "progress"]
    assert currents == sorted(currents)
    assert currents[-1] == 50  # final emitted even when total is small/fast
