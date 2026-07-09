from __future__ import annotations

import os

import pytest

from core.user_context import UserContext
from core.workspace_paths import resolve_user_workspace_path, user_workspace_root
from modules.research_workspace.store import ResearchWorkspaceStore


def test_user_workspace_root_defaults_under_runtime_users(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITERATURE_USER_DATA_ROOT", raising=False)

    root = user_workspace_root(UserContext("local_user", "local_user"))

    assert root == tmp_path / ".runtime" / "users" / "local_user"


def test_user_workspace_root_uses_configured_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))

    root = user_workspace_root(UserContext("alice", "alice"))

    assert root == tmp_path / "users" / "alice"


def test_resolve_user_workspace_path_rejects_escaping_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
    user = UserContext("alice", "alice")

    with pytest.raises(ValueError):
        resolve_user_workspace_path(user, "/tmp/outside")
    with pytest.raises(ValueError):
        resolve_user_workspace_path(user, "../outside")


def test_research_workspace_store_can_use_user_scoped_roots(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
    alice_root = user_workspace_root(UserContext("alice", "alice"))
    bob_root = user_workspace_root(UserContext("bob", "bob"))

    alice = ResearchWorkspaceStore(alice_root)
    bob = ResearchWorkspaceStore(bob_root)
    alice_workspace = alice.create_workspace("same_task")
    bob_workspace = bob.create_workspace("same_task")

    assert alice_workspace.workspace_rel_path == "research_agent/research_tasks/same_task"
    assert bob_workspace.workspace_rel_path == "research_agent/research_tasks/same_task"
    assert (alice_root / alice_workspace.workspace_rel_path / "task.md").exists()
    assert (bob_root / bob_workspace.workspace_rel_path / "task.md").exists()
    assert os.path.commonpath([alice_root, bob_root]) == str(tmp_path / "users")
