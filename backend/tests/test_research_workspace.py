from pathlib import Path

import pytest

from modules.research_workspace import (
    ArtifactManifest,
    ResearchTaskState,
    ResearchWorkspaceStore,
)


STANDARD_DIRS = {
    "retrieval",
    "evidence",
    "ranked_evidence",
    "landscape",
    "gaps",
    "ideas",
    "screening",
    "reports",
    "experiments",
    "claim_ledger",
    "manuscript",
    "logs",
    "audit",
}


def test_create_workspace_initializes_standard_layout(tmp_path: Path) -> None:
    store = ResearchWorkspaceStore(tmp_path)
    workspace = store.create_workspace("task_123")

    root = tmp_path / "research_agent/research_tasks/task_123"
    assert root.exists()
    assert workspace.task_id == "task_123"
    assert workspace.root_rel == "research_agent/research_tasks"
    assert workspace.workspace_rel_path == "research_agent/research_tasks/task_123"
    assert workspace.cli_controller_ready is False

    for dirname in STANDARD_DIRS:
        assert (root / dirname).is_dir()

    assert (root / "task.md").is_file()
    assert (root / "plan.md").is_file()
    assert (root / "state.json").is_file()
    assert (root / "audit/artifact_manifest.json").is_file()


def test_task_plan_state_and_manifest_round_trip(tmp_path: Path) -> None:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace("task_123")

    store.write_task("task_123", "# Task\n\nFind evidence.")
    store.write_plan("task_123", "# Plan\n\nUse local artifacts.")
    assert store.read_task("task_123") == "# Task\n\nFind evidence."
    assert store.read_plan("task_123") == "# Plan\n\nUse local artifacts."

    state = store.read_state("task_123")
    assert state["task_id"] == "task_123"
    assert state["status"] == "initialized"
    assert state["current_phase"] == "workspace"
    assert state["completed_steps"] == []
    assert state["pending_steps"] == []
    assert state["artifact_index"] == {}
    assert state["warnings"] == []
    assert state["blockers"] == []
    assert isinstance(state["created_at"], float)
    assert isinstance(state["updated_at"], float)

    replacement_state = ResearchTaskState(
        task_id="task_123",
        status="running",
        current_phase="planning",
        completed_steps=["workspace_created"],
        pending_steps=["draft_plan"],
        artifact_index={"task": "task.md"},
        warnings=["manual_review_required"],
        blockers=[],
        created_at=state["created_at"],
        updated_at=state["updated_at"],
    )
    written_state = store.write_state("task_123", replacement_state)
    assert written_state["status"] == "running"
    assert store.read_state("task_123")["completed_steps"] == ["workspace_created"]

    artifact_manifest = store.read_artifact_manifest("task_123")
    assert artifact_manifest["task_id"] == "task_123"
    assert artifact_manifest["artifacts"] == []
    assert artifact_manifest["cli_controller_ready"] is False


def test_create_workspace_accepts_initial_content_and_state(tmp_path: Path) -> None:
    store = ResearchWorkspaceStore(tmp_path)
    state = ResearchTaskState(task_id="task_custom", pending_steps=["review_scope"])

    store.create_workspace(
        "task_custom",
        task_markdown="custom task",
        plan_markdown="custom plan",
        state=state,
    )

    assert store.read_task("task_custom") == "custom task"
    assert store.read_plan("task_custom") == "custom plan"
    assert store.read_state("task_custom")["pending_steps"] == ["review_scope"]


def test_artifact_manifest_schema_serializes_to_json_safe_dict() -> None:
    manifest = ArtifactManifest(task_id="task_123")

    assert manifest.as_dict() == {
        "task_id": "task_123",
        "artifacts": [],
        "cli_controller_ready": False,
    }


@pytest.mark.parametrize("task_id", ["", "../escape", "a/b", "a\\b", "..", "task 123"])
def test_invalid_task_ids_are_rejected(tmp_path: Path, task_id: str) -> None:
    store = ResearchWorkspaceStore(tmp_path)

    with pytest.raises(ValueError):
        store.create_workspace(task_id)
    with pytest.raises(ValueError):
        store.read_task(task_id)
    with pytest.raises(ValueError):
        store.resolve_workspace_path(task_id)


@pytest.mark.parametrize("relative_path", ["../outside", "/tmp/outside", "audit/../../outside"])
def test_workspace_path_resolution_rejects_escape_attempts(tmp_path: Path, relative_path: str) -> None:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace("task_123")

    with pytest.raises(ValueError):
        store.resolve_workspace_path("task_123", relative_path)


def test_workspace_path_resolution_allows_safe_relative_paths(tmp_path: Path) -> None:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace("task_123")

    resolved = store.resolve_workspace_path("task_123", "retrieval/source_candidates.json")

    assert resolved == tmp_path / "research_agent/research_tasks/task_123/retrieval/source_candidates.json"


def test_store_rejects_unsafe_root_rel(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ResearchWorkspaceStore(tmp_path, root_rel="/absolute/root")

    with pytest.raises(ValueError):
        ResearchWorkspaceStore(tmp_path, root_rel="../escape")


def test_research_workspace_does_not_import_database_cli_or_runtime_dependencies() -> None:
    module_dir = Path("backend/modules/research_workspace")
    sources = "\n".join(path.read_text(encoding="utf-8") for path in module_dir.glob("*.py"))

    forbidden = [
        "core.memory_db",
        "sqlite",
        "LiteratureResearchService",
        "workflow runner",
        "cli_backed_controller",
        "native_fallback_controller",
        "Claude Code CLI",
    ]
    for token in forbidden:
        assert token not in sources
