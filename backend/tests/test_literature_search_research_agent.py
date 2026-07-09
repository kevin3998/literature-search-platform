from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_bounded_route_rows_skips_fallback_or_when_candidate_limit_is_satisfied():
    from modules.literature_search.service import _bounded_route_rows

    calls = []

    class FakeModule:
        @staticmethod
        def _recall_routes(query):
            return [
                {"name": "phrase", "match": '"large language models"', "score_offset": -3.0},
                {"name": "core_terms", "match": '"large" AND "language"', "score_offset": -1.0},
                {"name": "fallback_or", "match": '"large" OR "language" OR "materials"', "score_offset": 0.0},
            ]

        @staticmethod
        def _row_with_score(row, score):
            item = dict(row)
            item["score"] = score
            return item

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            calls.append(params[0])
            if params[0] == '"large language models"':
                return FakeCursor([
                    {"document_id": 1, "score": 1.0},
                    {"document_id": 2, "score": 2.0},
                ])
            if params[0] == '"large" AND "language"':
                return FakeCursor([
                    {"document_id": 1, "score": 0.5},
                    {"document_id": 2, "score": 1.5},
                ])
            raise AssertionError(f"unexpected route executed: {params[0]}")

    class FakeSearch:
        def _connect(self):
            return FakeConnection()

    rows, plan = _bounded_route_rows(
        FakeSearch(),
        FakeModule,
        query="large language models for materials discovery",
        constraints="",
        params=[],
        candidate_limit=2,
        section_filter=None,
        kind_filter=None,
    )

    assert calls == ['"large language models"', '"large" AND "language"']
    assert [row["document_id"] for row in rows] == [1, 2]
    skipped = [route for route in plan["routes"] if route["name"] == "fallback_or"]
    assert skipped and skipped[0]["skipped"] is True
    assert skipped[0]["skip_reason"] == "candidate_limit_satisfied_before_fallback"


def test_bounded_route_rows_keeps_fallback_or_when_candidate_limit_is_not_satisfied():
    from modules.literature_search.service import _bounded_route_rows

    calls = []

    class FakeModule:
        @staticmethod
        def _recall_routes(query):
            return [
                {"name": "phrase", "match": '"rare phrase"', "score_offset": -3.0},
                {"name": "fallback_or", "match": '"rare" OR "broader"', "score_offset": 0.0},
            ]

        @staticmethod
        def _row_with_score(row, score):
            item = dict(row)
            item["score"] = score
            return item

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            calls.append(params[0])
            if params[0] == '"rare phrase"':
                return FakeCursor([{"document_id": 1, "score": 1.0}])
            if params[0] == '"rare" OR "broader"':
                return FakeCursor([
                    {"document_id": 1, "score": 1.5},
                    {"document_id": 2, "score": 2.0},
                ])
            raise AssertionError(f"unexpected route executed: {params[0]}")

    class FakeSearch:
        def _connect(self):
            return FakeConnection()

    rows, plan = _bounded_route_rows(
        FakeSearch(),
        FakeModule,
        query="rare broader topic",
        constraints="",
        params=[],
        candidate_limit=2,
        section_filter=None,
        kind_filter=None,
    )

    assert calls == ['"rare phrase"', '"rare" OR "broader"']
    assert [row["document_id"] for row in rows] == [1, 2]
    fallback = [route for route in plan["routes"] if route["name"] == "fallback_or"][0]
    assert fallback["matched_documents"] == 2
    assert "skipped" not in fallback


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_service_maps_research_search_payload_to_chat_papers(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_RESEARCH_CODE_DIR", str(tmp_path))
    monkeypatch.setenv("LITERATURE_DATA_DIR", str(tmp_path / "data"))

    from modules.literature_search.service import LiteratureResearchService

    service = LiteratureResearchService(import_research=False)
    payload = {
        "query_plan": {
            "retrieval_requested": "hybrid",
            "retrieval_used": "fts",
            "vector_unavailable_reason": "vector_index_not_built",
        },
        "results": [
            {
                "article_id": 12,
                "doi": "10.1000/example",
                "title": "A Useful Paper",
                "journal": "Journal of Tests",
                "year": "2025",
                "score": 25.0,
                "site": "wiley",
                "matched_terms": ["battery", "stability"],
                "ranking_features": {"retrieval_sources": ["fts"]},
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "kind": "abstract",
                        "confidence": "medium",
                        "source_path": "articles/example/meta.json",
                        "snippet": "A useful evidence snippet.",
                        "paper_id": "10.1000/example",
                    }
                ],
                "evidence_summary": {"confidence": "medium"},
            }
        ],
    }

    papers = service.to_chat_papers(payload)

    # Block 0: the canonical paper_id from the underlying evidence is surfaced
    # at the paper level so every downstream layer references the same identity.
    assert papers[0]["paper_id"] == "10.1000/example"

    assert papers == [
        {
            "id": "10.1000/example",
            "paper_id": "10.1000/example",
            "index_version": None,
            "title": "A Useful Paper",
            "authors": [],
            "year": 2025,
            "venue": "Journal of Tests",
            "citation_count": None,
            "relevance_score": 1.0,
            "abstract": None,
            "snippet": "A useful evidence snippet.",
            "source_path": "articles/example/meta.json",
            "url": "https://doi.org/10.1000/example",
            "tags": ["wiley", "fts", "medium", "battery", "stability"],
            "doi": "10.1000/example",
            "article_id": 12,
            "evidence": payload["results"][0]["evidence"],
            "evidence_summary": {"confidence": "medium"},
            "matched_terms": ["battery", "stability"],
            "retrieval_sources": ["fts"],
        }
    ]


def test_artifact_store_lists_and_reads_research_artifacts(tmp_path):
    from modules.literature_search.artifact_store import ArtifactStore

    root = tmp_path / "research_agent"
    packs = root / "packs"
    packs.mkdir(parents=True)
    (packs / "pack-1.json").write_text(
        json.dumps({"query": "test query", "evidence": [{"evidence_id": "E1"}]}),
        encoding="utf-8",
    )
    (packs / "pack-1.md").write_text("# Pack 1\n", encoding="utf-8")

    store = ArtifactStore(tmp_path)
    artifacts = store.list_artifacts()
    artifact = store.read_artifact(artifacts[0]["artifact_id"])

    assert artifacts[0]["artifact_type"] == "pack"
    assert artifacts[0]["json_path"] == "research_agent/packs/pack-1.json"
    assert artifact["content"]["query"] == "test query"
    assert artifact["markdown"] == "# Pack 1\n"


def test_job_store_records_events_and_completion():
    from modules.literature_search.job_store import JobStore

    store = JobStore()
    job = store.create("task_run", {"question": "q"})
    store.start(job["job_id"])
    store.add_event(job["job_id"], {"type": "stage", "stage": "task", "status": "running"})
    store.complete(job["job_id"], {"ok": True})

    saved = store.get(job["job_id"])
    events = store.events(job["job_id"])

    assert saved["status"] == "completed"
    assert saved["result"] == {"ok": True}
    assert events[-1]["type"] == "done"


def test_literature_search_router_exposes_selfcheck_and_search(monkeypatch):
    from api import literature_search_router
    from main import app

    class FakeService:
        def selfcheck(self):
            return {"agent_name": "literature-research-agent"}

        def search(self, query, **options):
            return {"query": query, "results": [], "query_plan": {"retrieval_used": "fts"}}

    monkeypatch.setattr(literature_search_router, "service", FakeService())
    client = TestClient(app)

    assert client.get("/api/literature-search/selfcheck").json()["agent_name"] == "literature-research-agent"
    response = client.post("/api/literature-search/search", json={"query": "battery"})
    assert response.status_code == 200
    assert response.json()["query"] == "battery"


def test_literature_module_blocks_research_when_llm_is_not_available(monkeypatch):
    from modules.literature_search import module as literature_module
    from modules.literature_search.module import LiteratureSearchModule

    class FakeAdapter:
        async def search(self, query, top_k=8, filters=None):
            raise AssertionError("research QA must require LLM instead of adapter fallback")

    monkeypatch.setattr(literature_module, "REAL_AGENT_AVAILABLE", True)
    monkeypatch.setattr(literature_module, "real_adapter", FakeAdapter())
    monkeypatch.setattr(literature_module.settings_store, "llm_enabled", lambda: False)

    async def collect():
        return [
            event
            async for event in LiteratureSearchModule().handle_chat(
                "s1",
                "question",
                [],
                {"top_k": 1},
            )
        ]

    events = asyncio.run(collect())
    failure = next(event for event in events if event["type"] == "failure_explanation")
    assert failure["code"] == "llm_required_for_research"
    assert not any(event["type"] == "search_meta" for event in events)
    assert not any(event["type"] == "papers" for event in events)
    assert events[-1] == {"type": "done"}
