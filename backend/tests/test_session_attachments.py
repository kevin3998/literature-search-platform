from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.chat_router as chat_router
    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    monkeypatch.setattr(chat_router, "session_store", store)
    return TestClient(main.app), store, chat_router


def test_session_store_attachment_lifecycle_excludes_deleted(monkeypatch, tmp_path):
    _, store, _ = _client(monkeypatch, tmp_path)
    session = store.create_session(module_id="literature_search", title="附件测试")

    saved = store.create_attachment(
        session["session_id"],
        user_id="local_user",
        filename="note.txt",
        content_type="text/plain",
        extracted_text="alpha beta",
    )

    listed = store.list_attachments(session["session_id"], user_id="local_user")
    context = store.attachments_context(session["session_id"], [saved["attachment_id"]], user_id="local_user")

    assert listed[0]["filename"] == "note.txt"
    assert listed[0]["status"] == "parsed"
    assert listed[0]["char_count"] == len("alpha beta")
    assert context[0]["text"] == "alpha beta"

    store.delete_attachment(session["session_id"], saved["attachment_id"], user_id="local_user")

    assert store.list_attachments(session["session_id"], user_id="local_user") == []
    assert store.attachments_context(session["session_id"], [saved["attachment_id"]], user_id="local_user") == []


def test_attachment_api_upload_txt_list_and_delete(monkeypatch, tmp_path):
    client, _, _ = _client(monkeypatch, tmp_path)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "附件"}).json()

    upload = client.post(
        f"/api/sessions/{session['session_id']}/attachments",
        files={"file": ("note.txt", b"hello attachment", "text/plain")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["filename"] == "note.txt"
    assert body["status"] == "parsed"
    assert body["char_count"] == len("hello attachment")
    assert "hello attachment" in body["text_preview"]
    assert "extracted_text" not in body

    listed = client.get(f"/api/sessions/{session['session_id']}/attachments").json()
    assert [item["attachment_id"] for item in listed] == [body["attachment_id"]]

    deleted = client.delete(f"/api/sessions/{session['session_id']}/attachments/{body['attachment_id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/sessions/{session['session_id']}/attachments").json() == []


def test_attachment_api_upload_pdf_extracts_text(monkeypatch, tmp_path):
    client, _, _ = _client(monkeypatch, tmp_path)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "附件"}).json()
    pdf_bytes = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 70 >>
stream
BT
/F1 18 Tf
72 720 Td
(Hello attachment PDF text) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000311 00000 n 
trailer
<< /Root 1 0 R /Size 6 >>
startxref
430
%%EOF
"""

    upload = client.post(
        f"/api/sessions/{session['session_id']}/attachments",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload.status_code == 200
    assert upload.json()["filename"] == "paper.pdf"
    assert "Hello attachment PDF text" in upload.json()["text_preview"]


def test_attachment_api_rejects_unsupported_files(monkeypatch, tmp_path):
    client, _, _ = _client(monkeypatch, tmp_path)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "附件"}).json()

    response = client.post(
        f"/api/sessions/{session['session_id']}/attachments",
        files={"file": ("image.png", b"not supported", "image/png")},
    )

    assert response.status_code == 400
    assert "仅支持" in response.json()["detail"]


def test_chat_stream_injects_attachment_context_without_changing_query(monkeypatch, tmp_path):
    client, store, chat_router = _client(monkeypatch, tmp_path)
    session = store.create_session(module_id="literature_search", title="附件")
    attachment = store.create_attachment(
        session["session_id"],
        user_id="local_user",
        filename="context.txt",
        content_type="text/plain",
        extracted_text="uploaded context text",
    )
    seen = {}

    class FakeModule:
        async def handle_chat(self, session_id, message, history, options):
            seen["message"] = message
            seen["attachments"] = options.get("_attachments_context")
            yield {"type": "token", "text": "ok"}
            yield {"type": "done"}

    monkeypatch.setattr(chat_router.registry, "get", lambda module_id: FakeModule())

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "module_id": "literature_search",
            "session_id": session["session_id"],
            "message": "原始问题",
            "history": [],
            "options": {"attachment_ids": [attachment["attachment_id"]]},
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert seen["message"] == "原始问题"
    assert seen["attachments"][0]["filename"] == "context.txt"
    assert seen["attachments"][0]["text"] == "uploaded context text"
    assert '"type": "attachment_context"' in body
    assert '"filenames": ["context.txt"]' in body

    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assistant = [message for message in messages if message["role"] == "assistant"][0]
    assert assistant["metadata"]["used_attachments"] == {
        "attachment_count": 1,
        "filenames": ["context.txt"],
    }
