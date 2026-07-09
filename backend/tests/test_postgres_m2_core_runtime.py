from __future__ import annotations

import importlib
import re
import sys

from fastapi.testclient import TestClient

from postgres_test_utils import migrated_postgres_schema

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _reload_core_runtime_modules():
    modules = [
        "main",
        "api.settings_router",
        "api.modules_router",
        "api.chat_router",
        "core.user_store",
        "core.user_context",
        "core.secret_store",
        "core.model_profiles",
        "core.settings_store",
        "core.session_store",
    ]
    for name in modules:
        sys.modules.pop(name, None)
        if "." in name:
            package_name, attribute = name.rsplit(".", 1)
            package = sys.modules.get(package_name)
            if package is not None and hasattr(package, attribute):
                delattr(package, attribute)
    import_order = [
        "core.user_store",
        "core.user_context",
        "core.secret_store",
        "core.model_profiles",
        "core.settings_store",
        "core.session_store",
        "api.modules_router",
        "api.settings_router",
        "api.chat_router",
        "main",
    ]
    loaded = {}
    for name in import_order:
        loaded[name] = importlib.import_module(name)
    return loaded


def test_me_uses_internal_uuid_and_dev_subject_identity():
    with migrated_postgres_schema():
        modules = _reload_core_runtime_modules()
        client = TestClient(modules["main"].app)

        local = client.get("/api/me").json()
        alice = client.get("/api/me", headers={"X-User-Id": "alice"}).json()
        alice_again = client.get("/api/me", headers={"X-User-Id": "alice"}).json()

    assert UUID_RE.match(local["user_id"])
    assert local["subject"] == "local_user"
    assert local["display_name"] == "local_user"
    assert local["auth_mode"] == "dev-header"
    assert UUID_RE.match(alice["user_id"])
    assert alice["subject"] == "alice"
    assert alice["display_name"] == "alice"
    assert alice_again["user_id"] == alice["user_id"]
    assert alice["user_id"] != local["user_id"]


def test_settings_profiles_and_secrets_are_isolated_per_user():
    with migrated_postgres_schema():
        modules = _reload_core_runtime_modules()
        client = TestClient(modules["main"].app)

        alice_patch = client.patch(
            "/api/settings",
            headers={"X-User-Id": "alice"},
            json={"retrieval": {"default_limit": 17}},
        )
        bob_settings = client.get("/api/settings", headers={"X-User-Id": "bob"}).json()
        alice_profile = client.post(
            "/api/settings/model-profiles",
            headers={"X-User-Id": "alice"},
            json={
                "name": "Alice OpenAI",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-test",
                "api_key": "sk-alice-secret",
            },
        ).json()
        client.post(f"/api/settings/model-profiles/{alice_profile['id']}/activate", headers={"X-User-Id": "alice"})
        alice_profiles = client.get("/api/settings/model-profiles", headers={"X-User-Id": "alice"}).json()
        bob_profiles = client.get("/api/settings/model-profiles", headers={"X-User-Id": "bob"}).json()
        alice_effective = client.get("/api/settings/effective", headers={"X-User-Id": "alice"}).json()
        bob_effective = client.get("/api/settings/effective", headers={"X-User-Id": "bob"}).json()

    assert alice_patch.status_code == 200
    assert alice_patch.json()["retrieval"]["default_limit"] == 17
    assert bob_settings["retrieval"]["default_limit"] != 17
    assert alice_profiles[0]["has_key"] is True
    assert alice_profiles[0]["key_masked"] == "sk-ali...cret"
    assert bob_profiles == []
    assert alice_effective["models.provider"]["value"] == "openai"
    assert bob_effective["models.provider"]["value"] == "none"


def test_sessions_use_uuid_ids_bundle_and_cross_user_404():
    with migrated_postgres_schema():
        modules = _reload_core_runtime_modules()
        client = TestClient(modules["main"].app)

        created = client.post(
            "/api/sessions",
            headers={"X-User-Id": "alice"},
            json={"module_id": "literature_search", "title": "Alice session"},
        ).json()
        session_id = created["session_id"]
        messages = client.get(f"/api/sessions/{session_id}/messages", headers={"X-User-Id": "alice"}).json()
        bundle = client.get(f"/api/sessions/{session_id}/bundle", headers={"X-User-Id": "alice"}).json()
        bob_get = client.get(f"/api/sessions/{session_id}", headers={"X-User-Id": "bob"})
        bob_bundle = client.get(f"/api/sessions/{session_id}/bundle", headers={"X-User-Id": "bob"})

    assert UUID_RE.match(session_id)
    assert created["id"] == session_id
    assert created["user_id"] != "alice"
    assert messages == []
    assert set(bundle) == {"session", "messages", "context", "artifacts", "jobs", "research_state", "attachments"}
    assert bundle["session"]["session_id"] == session_id
    assert bob_get.status_code == 404
    assert bob_bundle.status_code == 404
