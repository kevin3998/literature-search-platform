from __future__ import annotations


def test_backend_app_imports_with_attachment_routes() -> None:
    import multipart  # noqa: F401
    import main

    routes = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/sessions/{session_id}/attachments" in routes
