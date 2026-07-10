from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from core.user_context import UserContext, current_user


@pytest.fixture(autouse=True)
def _postgres_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
    monkeypatch.setenv("DB_SCHEMA", "literature_agent_test")


def _client_for(router, user: UserContext) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: user
    app.include_router(router)
    return TestClient(app)


def test_corpus_maintenance_jobs_requires_admin(monkeypatch):
    from api import corpus_router

    class FakeJobStore:
        def list_jobs(self, **_kwargs):
            return [{"job_id": "job-1", "job_type": "index_refresh", "status": "completed"}]

    monkeypatch.setattr(corpus_router, "job_store", FakeJobStore())

    user_client = _client_for(corpus_router.router, UserContext(user_id="user-1", workspace_slug="user-1", role="user"))
    admin_client = _client_for(corpus_router.router, UserContext(user_id="admin-1", workspace_slug="admin-1", role="admin"))

    user_response = user_client.get("/api/corpus/maintenance/jobs")
    admin_response = admin_client.get("/api/corpus/maintenance/jobs")

    assert user_response.status_code == 403
    assert user_response.json()["detail"] == "admin role required"
    assert admin_response.status_code == 200
    assert admin_response.json()[0]["job_id"] == "job-1"


def test_corpus_dashboard_is_simplified_for_regular_users(monkeypatch):
    from api import corpus_router

    class FakeCorpus:
        def dashboard(self, *, role: str, recent_jobs):
            return {
                "overall_status": "warning",
                "index_db_path": "/srv/private/research_index.sqlite",
                "summary": {"documents": 12},
                "coverage": {"papers": 3, "sections": 4, "chunks": 5, "vector_records": 0},
                "vector": {"built": False, "reason": "vector_index_not_built"},
                "warnings": ["vector_not_built"],
                "capabilities": {
                    "role": role,
                    "can_maintain": role == "admin",
                    "maintenance_actions": ["health_check", "index_refresh", "vector_build"] if role == "admin" else [],
                },
                "recent_jobs": recent_jobs,
                "running_maintenance": {"job_id": "job-running", "job_type": "index_refresh"},
                "integrity": {"sampled": 10, "broken_count": 0},
            }

    class FakeJobStore:
        def list_jobs(self, **_kwargs):
            return [{"job_id": "job-secret", "job_type": "vector_build", "status": "failed", "error": "worker details"}]

        def latest_event(self, *_args):
            return {"phase": "private progress"}

    monkeypatch.setattr(corpus_router, "corpus", lambda: FakeCorpus())
    monkeypatch.setattr(corpus_router, "job_store", FakeJobStore())

    response = _client_for(corpus_router.router, UserContext(user_id="user-1", workspace_slug="user-1", role="user")).get(
        "/api/corpus/dashboard"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"]["role"] == "viewer"
    assert body["capabilities"]["can_maintain"] is False
    assert body["capabilities"]["maintenance_actions"] == []
    assert "index_db_path" not in body
    assert "recent_jobs" not in body
    assert "running_maintenance" not in body
    assert "integrity" not in body
    assert body["warnings"] == []
    assert body["vector"] == {"built": False}


def test_vector_build_requires_admin(monkeypatch):
    from api import literature_search_router

    class FakeJobRunner:
        called = False

        def submit(self, *_args, **_kwargs):
            self.called = True
            return {"job_id": "vector-job", "status": "queued"}

    fake_runner = FakeJobRunner()
    monkeypatch.setattr(literature_search_router, "job_runner", fake_runner)

    user_client = _client_for(
        literature_search_router.router,
        UserContext(user_id="user-1", workspace_slug="user-1", role="user"),
    )
    admin_client = _client_for(
        literature_search_router.router,
        UserContext(user_id="admin-1", workspace_slug="admin-1", role="admin"),
    )

    user_response = user_client.post("/api/literature-search/vector/build", json={})
    admin_response = admin_client.post("/api/literature-search/vector/build", json={})

    assert user_response.status_code == 403
    assert user_response.json()["detail"] == "admin role required"
    assert admin_response.status_code == 200
    assert admin_response.json()["job_id"] == "vector-job"
    assert fake_runner.called is True


def test_settings_diagnostics_and_readiness_require_admin(monkeypatch):
    from api import settings_router

    class FakeSettingsStore:
        def diagnostics(self, **_kwargs):
            return {"overall": "ok"}

        def readiness(self, **_kwargs):
            return {"ready": True}

    monkeypatch.setattr(settings_router, "settings_store", FakeSettingsStore())

    user_client = _client_for(settings_router.router, UserContext(user_id="user-1", workspace_slug="user-1", role="user"))
    admin_client = _client_for(settings_router.router, UserContext(user_id="admin-1", workspace_slug="admin-1", role="admin"))

    assert user_client.get("/api/settings/diagnostics").status_code == 403
    assert user_client.get("/api/settings/readiness").status_code == 403
    assert admin_client.get("/api/settings/diagnostics").status_code == 200
    assert admin_client.get("/api/settings/readiness").status_code == 200


def test_regular_user_settings_are_limited_to_models_and_retrieval(monkeypatch):
    from api import settings_router

    class FakeSettingsStore:
        patched_payload = None

        def get_settings(self, **_kwargs):
            return {
                "general": {"platform_name": "Platform", "default_module": "literature_search"},
                "models": {"temperature": 0.2},
                "retrieval": {"default_limit": 10},
                "agent": {"enabled": True},
                "research_agent": {"data_dir": "/srv/private"},
                "diagnostics": {"last_run": None},
            }

        def effective(self, **_kwargs):
            return {
                "general.default_module": {"value": "literature_search"},
                "general.default_literature_tab": {"value": "chat"},
                "general.platform_name": {"value": "Platform"},
                "models.temperature": {"value": 0.2},
                "retrieval.default_limit": {"value": 10},
                "research_agent.data_dir": {"value": "/srv/private"},
                "agent.enabled": {"value": True},
            }

        def patch(self, payload, **_kwargs):
            self.patched_payload = payload
            return self.get_settings()

    fake_store = FakeSettingsStore()
    monkeypatch.setattr(settings_router, "settings_store", fake_store)

    user_client = _client_for(settings_router.router, UserContext(user_id="user-1", workspace_slug="user-1", role="user"))

    settings_response = user_client.get("/api/settings")
    effective_response = user_client.get("/api/settings/effective")
    allowed_patch = user_client.patch("/api/settings", json={"models": {"temperature": 0.1}, "retrieval": {"default_limit": 5}})
    blocked_patch = user_client.patch("/api/settings", json={"agent": {"enabled": False}})
    blocked_reset = user_client.post("/api/settings/reset", json={"scope": "agent"})

    assert settings_response.status_code == 200
    assert set(settings_response.json()) == {"models", "retrieval"}
    assert effective_response.status_code == 200
    assert set(effective_response.json()) == {
        "general.default_module",
        "general.default_literature_tab",
        "models.temperature",
        "retrieval.default_limit",
    }
    assert allowed_patch.status_code == 200
    assert fake_store.patched_payload == {"models": {"temperature": 0.1}, "retrieval": {"default_limit": 5}}
    assert blocked_patch.status_code == 403
    assert blocked_reset.status_code == 403


def test_external_source_secrets_require_admin(monkeypatch):
    from api import settings_router

    user_client = _client_for(settings_router.router, UserContext(user_id="user-1", workspace_slug="user-1", role="user"))

    set_response = user_client.post("/api/settings/external-sources/secret", json={"source": "exa", "api_key": "secret"})
    delete_response = user_client.request("DELETE", "/api/settings/external-sources/secret", json={"source": "exa"})

    assert set_response.status_code == 403
    assert delete_response.status_code == 403
