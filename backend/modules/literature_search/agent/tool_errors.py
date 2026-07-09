"""Structured tool-error contract for the agent execution layer (Block 4).

Every tool failure is normalized to a single shape so the LLM can reason about
recovery and the UI can show a short, safe status — instead of a raw
``{"error": str(exc)}`` that leaks absolute paths / provider payloads and gives
the model nothing actionable.

    {
      "ok": false,
      "error": {
        "code": "paper_not_found",
        "message": "No paper matched the provided DOI.",
        "retryable": false,
        "recovery_hint": "Run search first or ask the user for a DOI/paper_id."
      }
    }

``code`` + ``message`` drive the UI; ``retryable`` + ``recovery_hint`` drive the
LLM's next step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Canonical error codes (kept in sync with the block doc).
VALIDATION_ERROR = "validation_error"
PERMISSION_DENIED = "permission_denied"
CONFIRMATION_REQUIRED = "confirmation_required"
TIMEOUT = "timeout"
JOB_FAILED = "job_failed"
PAPER_NOT_FOUND = "paper_not_found"
ARTIFACT_NOT_FOUND = "artifact_not_found"
INDEX_UNAVAILABLE = "index_unavailable"
VECTOR_UNAVAILABLE = "vector_unavailable"
EXTERNAL_PROVIDER_UNAVAILABLE = "external_provider_unavailable"
UNKNOWN_ERROR = "unknown_error"

# Default recovery hints per code; a ToolError may override with a specific one.
_DEFAULT_HINTS: dict[str, str] = {
    VALIDATION_ERROR: "Fix the arguments to match the tool schema and call again.",
    PERMISSION_DENIED: "This action is not available in the current mode; do not retry it.",
    CONFIRMATION_REQUIRED: "Ask the user to confirm the action in plain language before retrying.",
    TIMEOUT: "The tool took too long; narrow the query/scope or try once more.",
    JOB_FAILED: "The background job failed; report the failure and suggest a narrower request.",
    PAPER_NOT_FOUND: "Run search first or ask the user for a DOI, paper_id, or article_id.",
    ARTIFACT_NOT_FOUND: "Create the artifact (pack/run/task) before referencing it.",
    INDEX_UNAVAILABLE: "The local index is unavailable; report this and do not assert facts.",
    VECTOR_UNAVAILABLE: "Vector retrieval is unavailable; fall back to fts/hybrid search.",
    EXTERNAL_PROVIDER_UNAVAILABLE: "An external provider is unavailable; report and try later.",
    UNKNOWN_ERROR: "Report the failure plainly; do not fabricate a result.",
}

RETRYABLE_CODES = {TIMEOUT, EXTERNAL_PROVIDER_UNAVAILABLE}


@dataclass
class ToolError(Exception):
    """A normalized, LLM- and UI-readable tool failure.

    Subclasses ``Exception`` so the execution layer can ``raise`` it for control
    flow (job/timeout paths) and catch it, while ``as_dict()`` gives the wire
    shape returned to the model.
    """

    code: str
    message: str
    retryable: bool = False
    recovery_hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "recovery_hint": self.recovery_hint or _DEFAULT_HINTS.get(self.code, ""),
            },
        }


def make_error(code: str, message: str, *, retryable: bool | None = None, recovery_hint: str | None = None) -> ToolError:
    if retryable is None:
        retryable = code in RETRYABLE_CODES
    return ToolError(code=code, message=message, retryable=retryable, recovery_hint=recovery_hint)


def is_tool_error(content: Any) -> bool:
    return isinstance(content, dict) and content.get("ok") is False and isinstance(content.get("error"), dict)


# --- exception classification --------------------------------------------------

# Lower-cased substrings → error code. The underlying research agent raises plain
# exceptions (ValueError/KeyError/FileNotFoundError) with human messages; we map
# the recognizable ones to stable codes and leave the rest as unknown_error.
_PATTERNS: list[tuple[str, str]] = [
    ("vector", VECTOR_UNAVAILABLE),
    ("embedding", VECTOR_UNAVAILABLE),
    ("index not built", INDEX_UNAVAILABLE),
    ("index unavailable", INDEX_UNAVAILABLE),
    ("no such index", INDEX_UNAVAILABLE),
    ("artifact", ARTIFACT_NOT_FOUND),
    ("run not found", ARTIFACT_NOT_FOUND),
    ("task not found", ARTIFACT_NOT_FOUND),
    ("pack", ARTIFACT_NOT_FOUND),
    ("no paper", PAPER_NOT_FOUND),
    ("paper not found", PAPER_NOT_FOUND),
    ("doi", PAPER_NOT_FOUND),
    ("article_id", PAPER_NOT_FOUND),
    ("not found", PAPER_NOT_FOUND),
    ("timed out", TIMEOUT),
    ("timeout", TIMEOUT),
    ("connection", EXTERNAL_PROVIDER_UNAVAILABLE),
    ("provider", EXTERNAL_PROVIDER_UNAVAILABLE),
    ("rate limit", EXTERNAL_PROVIDER_UNAVAILABLE),
]


def classify_exception(exc: Exception) -> ToolError:
    """Best-effort mapping of an underlying exception to a structured ToolError.

    The raw exception string is redacted (absolute paths stripped) before it is
    surfaced — it goes to the LLM and into the trace.
    """
    if isinstance(exc, TimeoutError):
        return make_error(TIMEOUT, "The tool timed out.")
    raw = str(exc) or exc.__class__.__name__
    lowered = raw.lower()
    code = UNKNOWN_ERROR
    for needle, mapped in _PATTERNS:
        if needle in lowered:
            code = mapped
            break
    return make_error(code, _redact_text(raw))


# --- redaction -----------------------------------------------------------------

_SECRET_KEYS = re.compile(r"(api[_-]?key|secret|token|password|authorization|bearer)", re.IGNORECASE)
# Absolute POSIX paths and home-dir paths; collapse to the trailing leaf so the
# corpus root / machine layout never leaks into records or the LLM context.
_ABS_PATH = re.compile(r"(/[^\s'\"]+/)+([^\s'\"/]+)")
_REDACTED = "[redacted]"


def _redact_text(text: str) -> str:
    return _ABS_PATH.sub(r"…/\2", text)


def redact(value: Any) -> Any:
    """Recursively redact secrets and absolute paths from tool arguments.

    Used for the trace's stored ``arguments`` and any message echoed back. Keys
    that look like credentials are masked entirely; absolute paths are collapsed
    to their leaf; everything else passes through.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEYS.search(key):
                out[key] = _REDACTED
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value
