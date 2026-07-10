"""Structured ToolSpec registry — the single source of truth for agent tools.

Block 4 promotes the old flat ``_QUICK_TOOLS`` / ``_DEEP_TOOLS`` lists into one
:class:`ToolSpec` per tool, carrying the LLM JSON schema *plus* the governance
metadata the execution layer needs: permission level, which agent modes may see
it, how it runs (direct vs job), timeout, and retry policy.

Gating is now spec-driven: ``ToolRegistry`` exposes exactly the tools whose
``agent_modes`` include the active mode. Admin / destructive tools are simply
absent from every agent mode in v1 (they are reached only via maintenance
routes), which satisfies "management actions are never auto-triggered".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bump when an input/output schema changes in a breaking way. Mostly useful for
# M2 export / audit replay; a constant placeholder is enough for now.
SCHEMA_VERSION = "1"

# Permission levels.
READ_ONLY = "read_only"
STATE_CREATING = "state_creating"
STATE_MUTATING = "state_mutating"
ADMIN_MAINTENANCE = "admin_maintenance"
DESTRUCTIVE = "destructive"

# Execution modes.
DIRECT = "direct"
JOB_REQUIRED = "job_required"
JOB_PREFERRED = "job_preferred"


# --- tool definitions (OpenAI function-calling schema) --------------------------

_DEFINITIONS: dict[str, dict[str, Any]] = {
    "search": {
        "description": (
            "Search the local literature library and return candidate papers with "
            "evidence snippets. Each evidence item carries a numeric citation alias "
            "you must use to cite claims, e.g. [1]. Prefer retrieval=hybrid; use fts for exact terms."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search query"},
                "limit": {"type": "integer", "description": "max papers (default 8)"},
                "retrieval": {"type": "string", "enum": ["hybrid", "fts", "vector"]},
                "profile": {"type": "string", "enum": ["default", "review", "idea", "data"]},
                "section": {"type": "string", "description": "restrict to a normalized section"},
                "kind": {"type": "string", "description": "evidence surface, e.g. table_row"},
                "year_from": {"type": "integer"},
                "year_to": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    "paper_sections": {
        "description": "Show the normalized section structure of one paper (by doi or article_id).",
        "parameters": {
            "type": "object",
            "properties": {
                "doi": {"type": "string"},
                "article_id": {"type": "integer"},
            },
        },
    },
    "paper_chunks": {
        "description": "Show text chunks of one paper, optionally restricted to a section.",
        "parameters": {
            "type": "object",
            "properties": {
                "doi": {"type": "string"},
                "article_id": {"type": "integer"},
                "section": {"type": "string"},
            },
        },
    },
    "evidence_expand": {
        "description": "Expand local table/figure assets linked to a paper paragraph or a labeled asset.",
        "parameters": {
            "type": "object",
            "properties": {
                "doi": {"type": "string"},
                "article_id": {"type": "integer"},
                "label": {"type": "string", "description": "e.g. 'Table 2'"},
            },
        },
    },
    "pack": {
        "description": (
            "Build an evidence pack for a multi-paper, cited answer. Use before "
            "composing a comparison or statistics-heavy response."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget": {"type": "integer", "description": "token budget (default 12000)"},
                "task": {"type": "string", "enum": ["default", "stats"]},
            },
            "required": ["query"],
        },
    },
    "task_run": {
        "description": "Run a multi-step research task and read its evidence artifact before answering.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "budget": {"type": "integer"},
                "scope": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    "run": {
        "description": "Run a complex, auditable research run with stage artifacts and a readable summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "budget": {"type": "integer"},
            },
            "required": ["question"],
        },
    },
    "extract": {
        "description": "Extract structured metric rows (value, unit, source) from table/CSV evidence.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    "compare": {
        "description": "Generate a lightweight comparison table from extracted metrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "sort_by": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "verify_answer": {
        "description": "Check whether a Markdown answer is supported by a run/task/pack artifact.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer_text": {"type": "string"},
                "run_id": {"type": "string"},
                "task_id": {"type": "string"},
                "pack_path": {"type": "string"},
            },
            "required": ["answer_text"],
        },
    },
    "quality": {
        "description": "Audit coverage, source paths, and conflict signals of a run/task/pack draft.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "task_id": {"type": "string"},
                "pack_path": {"type": "string"},
            },
        },
    },
}


@dataclass(frozen=True)
class ToolSpec:
    """Governance + schema metadata for one agent tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    permission_level: str
    agent_modes: tuple[str, ...]
    execution_mode: str = DIRECT
    timeout_seconds: float = 30.0
    max_retries: int = 0
    requires_confirmation: bool = False
    state_change_type: str | None = None  # what it creates/mutates, for the trace
    artifact_types: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION
    display_name: str | None = None

    @property
    def is_job(self) -> bool:
        return self.execution_mode == JOB_REQUIRED


def _spec(name: str, **kwargs: Any) -> ToolSpec:
    definition = _DEFINITIONS[name]
    return ToolSpec(
        name=name,
        description=definition["description"],
        input_schema=definition["parameters"],
        **kwargs,
    )


# v1 governs the EXISTING agent tools (no new tools). Admin/destructive
# maintenance tools (index_refresh / vector_build / delete) are intentionally
# NOT registered in any agent mode — they stay on maintenance routes only.
_TOOL_SPECS: dict[str, ToolSpec] = {
    "search": _spec(
        "search", permission_level=READ_ONLY, agent_modes=("quick", "deep"),
        execution_mode=DIRECT, timeout_seconds=30.0, max_retries=0,
    ),
    "paper_sections": _spec(
        "paper_sections", permission_level=READ_ONLY, agent_modes=("quick", "deep"),
        execution_mode=DIRECT, timeout_seconds=20.0,
    ),
    "paper_chunks": _spec(
        "paper_chunks", permission_level=READ_ONLY, agent_modes=("quick", "deep"),
        execution_mode=DIRECT, timeout_seconds=20.0,
    ),
    "evidence_expand": _spec(
        "evidence_expand", permission_level=READ_ONLY, agent_modes=("quick", "deep"),
        execution_mode=DIRECT, timeout_seconds=20.0,
    ),
    "pack": _spec(
        # job_preferred: may run as a job, but v1 keeps it direct so the delicate
        # pack→citation evidence registration path stays unchanged.
        "pack", permission_level=STATE_CREATING, agent_modes=("quick", "deep"),
        execution_mode=JOB_PREFERRED, timeout_seconds=120.0,
        state_change_type="evidence_pack", artifact_types=("pack",),
    ),
    "task_run": _spec(
        "task_run", permission_level=STATE_CREATING, agent_modes=("deep",),
        execution_mode=JOB_REQUIRED, timeout_seconds=600.0,
        state_change_type="task", artifact_types=("task",),
    ),
    "run": _spec(
        "run", permission_level=STATE_CREATING, agent_modes=("deep",),
        execution_mode=JOB_REQUIRED, timeout_seconds=900.0,
        state_change_type="run", artifact_types=("run", "report"),
    ),
    "extract": _spec(
        "extract", permission_level=STATE_CREATING, agent_modes=("deep",),
        execution_mode=JOB_REQUIRED, timeout_seconds=300.0,
        state_change_type="extraction", artifact_types=("extraction",),
    ),
    "compare": _spec(
        "compare", permission_level=STATE_CREATING, agent_modes=("deep",),
        execution_mode=JOB_REQUIRED, timeout_seconds=300.0,
        state_change_type="comparison", artifact_types=("comparison",),
    ),
    "verify_answer": _spec(
        "verify_answer", permission_level=READ_ONLY, agent_modes=("deep",),
        execution_mode=DIRECT, timeout_seconds=60.0,
    ),
    "quality": _spec(
        "quality", permission_level=READ_ONLY, agent_modes=("deep",),
        execution_mode=DIRECT, timeout_seconds=60.0,
    ),
}


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Minimal JSON-schema check (required / type / enum). Returns an error
    message, or None if valid.

    Deliberately lenient — unknown extra keys are allowed (models occasionally
    add stray fields) — but it catches the failures that actually break a tool
    call: a missing required field, a wrong scalar type, or an out-of-enum value.
    Avoids a hard ``jsonschema`` dependency (absent from the runtime env).
    """
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    for key in schema.get("required") or []:
        if arguments.get(key) is None:
            return f"missing required field: {key}"
    properties = schema.get("properties") or {}
    for key, value in arguments.items():
        if value is None:
            continue
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue  # undeclared key — tolerate
        expected = prop.get("type")
        types = _JSON_TYPES.get(expected) if isinstance(expected, str) else None
        if types is not None:
            # bool is an int subclass — never accept it for integer/number.
            if isinstance(value, bool) and expected in {"integer", "number"}:
                return f"field {key} must be {expected}"
            if not isinstance(value, types):
                return f"field {key} must be {expected}"
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            return f"field {key} must be one of {enum}"
    return None


def specs_for_mode(answer_mode: str) -> list[ToolSpec]:
    """Tools exposed to the agent in the given mode, in registry order."""
    mode = "deep" if answer_mode == "deep" else "quick"
    return [spec for spec in _TOOL_SPECS.values() if mode in spec.agent_modes]


def get_spec(name: str) -> ToolSpec | None:
    return _TOOL_SPECS.get(name)
