from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.parse import quote

from api import workflow_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(workflow_router.router)
    return TestClient(app)


class FakeWorkflowStore:
    def __init__(self) -> None:
        self.created_payload = None

    def create(
        self,
        template_id,
        *,
        topic,
        scope="library",
        title=None,
        session_id=None,
        task_profile_id=None,
        scope_options=None,
    ):
        self.created_payload = {
            "template_id": template_id,
            "topic": topic,
            "scope": scope,
            "title": title,
            "session_id": session_id,
            "task_profile_id": task_profile_id,
            "scope_options": scope_options,
        }
        return {
            "workflow_id": "wf_router",
            "template_id": template_id,
            "topic": topic,
            "scope": scope,
            "task_profile_id": task_profile_id or "topic-to-report",
            "scope_lock": {
                "topic": topic,
                "scope": scope,
                "scope_options": scope_options or {},
                "task_profile_id": task_profile_id or "topic-to-report",
                "locked_at": 123.0,
            },
            "status": "draft",
            "manifest": {},
            "steps": [],
        }


def test_create_workflow_accepts_task_profile_and_scope_options(monkeypatch) -> None:
    fake_store = FakeWorkflowStore()
    monkeypatch.setattr(workflow_router, "workflow_store", fake_store)

    response = _client().post(
        "/api/workflows",
        json={
            "template_id": "idea-discovery",
            "topic": "battery interfaces",
            "scope": "library",
            "task_profile_id": "topic-to-report",
            "scope_options": {"year_from": 2020, "limit": 30},
        },
    )

    assert response.status_code == 200
    assert fake_store.created_payload == {
        "template_id": "idea-discovery",
        "topic": "battery interfaces",
        "scope": "library",
        "title": None,
        "session_id": None,
        "task_profile_id": "topic-to-report",
        "scope_options": {"year_from": 2020, "limit": 30},
    }
    assert response.json()["task_profile_id"] == "topic-to-report"


def test_templates_endpoint_returns_task_profiles() -> None:
    response = _client().get("/api/workflows/templates")

    assert response.status_code == 200
    payload = response.json()
    template_ids = {tpl["id"] for tpl in payload["templates"]}
    assert template_ids == {
        "controlled-minimal-evidence",
        "controlled-landscape",
        "controlled-gap-mapping",
        "controlled-idea-generation",
        "controlled-screening",
    }
    assert "idea-discovery" not in template_ids
    assert "controlled-experiment-matrix" not in template_ids
    assert all(step["runner"] == "research-controller" for tpl in payload["templates"] for step in tpl["steps"])
    assert "task_profiles" in payload
    by_id = {profile["profile_id"]: profile for profile in payload["task_profiles"]}
    assert by_id["topic-to-report"]["runnable"] is True
    assert by_id["experiment-plan"]["runnable"] is False


def test_create_workflow_returns_400_for_task_profile_errors(monkeypatch) -> None:
    class RejectingStore:
        def create(self, *args, **kwargs):
            raise ValueError("task profile is not runnable: experiment-plan")

    monkeypatch.setattr(workflow_router, "workflow_store", RejectingStore())

    response = _client().post(
        "/api/workflows",
        json={"template_id": "idea-discovery", "topic": "x", "task_profile_id": "experiment-plan"},
    )

    assert response.status_code == 400
    assert "not runnable" in response.json()["detail"]


def test_artifact_preview_endpoint_checks_owner_and_returns_preview(monkeypatch) -> None:
    calls = []

    class Store:
        def get(self, workflow_id, *, user_id=None):
            calls.append(("get", workflow_id, user_id))
            return {"workflow_id": workflow_id, "user_id": user_id}

    class Orchestrator:
        def artifact_preview(self, workflow_id, artifact_id):
            calls.append(("preview", workflow_id, artifact_id))
            return {
                "workflow_id": workflow_id,
                "artifact_id": artifact_id,
                "artifact_type": "build_minimal_topic_to_evidence_report",
                "label": "最小证据报告",
                "content_type": "markdown",
                "text": "# 最小证据报告",
                "json": None,
            }

    monkeypatch.setattr(workflow_router, "workflow_store", Store())
    monkeypatch.setattr(workflow_router, "workflow_orchestrator", Orchestrator())

    artifact_id = "users/local_user/research_agent/task/reports/minimal_topic_to_evidence_report.md"
    response = _client().get(f"/api/workflows/wf_1/artifacts/{quote(artifact_id, safe='')}", headers={"X-User-Id": "alice"})

    assert response.status_code == 200
    assert response.json()["artifact_id"] == artifact_id
    assert calls == [
        ("get", "wf_1", "alice"),
        ("preview", "wf_1", artifact_id),
    ]


def test_artifact_preview_endpoint_returns_404_for_unknown_artifact(monkeypatch) -> None:
    class Store:
        def get(self, workflow_id, *, user_id=None):
            return {"workflow_id": workflow_id, "user_id": user_id}

    class Orchestrator:
        def artifact_preview(self, workflow_id, artifact_id):
            raise KeyError("artifact not found")

    monkeypatch.setattr(workflow_router, "workflow_store", Store())
    monkeypatch.setattr(workflow_router, "workflow_orchestrator", Orchestrator())

    response = _client().get("/api/workflows/wf_1/artifacts/missing.md")

    assert response.status_code == 404
    assert "artifact not found" in response.json()["detail"]


def test_insights_endpoint_checks_owner_and_returns_summary(monkeypatch) -> None:
    calls = []

    class Store:
        def get(self, workflow_id, *, user_id=None):
            calls.append(("get", workflow_id, user_id))
            return {"workflow_id": workflow_id, "user_id": user_id}

    class Orchestrator:
        def workflow_insights(self, workflow_id):
            calls.append(("insights", workflow_id))
            return {
                "workflow_id": workflow_id,
                "evidence": {"available": False, "card_count": 0, "selected_count": 0, "role_counts": {}, "support_counts": {}, "cards": []},
                "diagnostics": {"available": False, "severity_counts": {"info": 0, "warning": 0, "error": 0}, "items": []},
            }

    monkeypatch.setattr(workflow_router, "workflow_store", Store())
    monkeypatch.setattr(workflow_router, "workflow_orchestrator", Orchestrator())

    response = _client().get("/api/workflows/wf_1/insights", headers={"X-User-Id": "alice"})

    assert response.status_code == 200
    assert response.json()["workflow_id"] == "wf_1"
    assert calls == [
        ("get", "wf_1", "alice"),
        ("insights", "wf_1"),
    ]
