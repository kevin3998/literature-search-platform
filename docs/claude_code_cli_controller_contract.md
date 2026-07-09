# Claude Code CLI Controller Contract

## Role

A6 defines the contract between a future CLI-backed controller and the platform runtime. The CLI side may observe a bounded workspace view and emit structured decisions. The platform parses, validates, rejects, audits, and later executes accepted requests.

A6 does not implement the runtime loop, call the CLI, execute skills, update state, update plans, update manifests, or generate research artifacts.

## Platform Boundary

The platform owns:

- Workspace path resolution and path safety.
- Skill registry validation.
- Artifact validation gates.
- State, plan, and manifest updates.
- Skill execution through registered wrappers.
- Audit event persistence.

The CLI must not directly run research skills through shell commands. It must emit a bounded `skill_request`. The platform decides whether that request is accepted and when it is executed.

## Workspace Access

All file references must be workspace-relative. Absolute paths, `..`, and paths that resolve outside the task workspace are rejected.

Typical readable files:

- `task.md`
- `plan.md`
- `state.json`
- `audit/artifact_manifest.json`
- `retrieval/...`
- `evidence/...`
- `ranked_evidence/...`
- `reports/...`

Typical writable artifact directories:

- `retrieval/...`
- `evidence/...`
- `ranked_evidence/...`
- `reports/...`
- `logs/...`

The CLI must not directly modify:

- `state.json`
- `plan.md`
- `audit/artifact_manifest.json`

State, plan, and manifest changes are platform-owned. A CLI decision may include `state_update_intent` or `plan_update_intent`, but A6 only parses those intents. It does not apply them.

## Output Envelope

Every CLI output must be JSON with this schema version:

```json
{
  "schema_version": "cli_controller_contract_v1",
  "task_id": "task_123",
  "decision": {
    "decision_type": "CALL_TOOL",
    "reason": "Retrieve source candidates for the topic.",
    "skill_request": {
      "skill_name": "retrieve_sources",
      "input_artifacts": [],
      "output_artifacts": ["retrieval/source_candidate_packet.json"],
      "parameters": {
        "topic": "large language models in materials discovery"
      },
      "reason": "Need topic-scoped source candidates."
    }
  },
  "notes": [],
  "warnings": []
}
```

Natural-language output is not a valid controller decision. If output cannot be parsed as the envelope, the platform returns `UNPARSEABLE_OUTPUT` or another contract violation.

## Decision Vocabulary

The bounded decision vocabulary is inherited from A2:

- `CALL_TOOL`
- `VALIDATE_ARTIFACT`
- `RETRY_WITH_ADJUSTED_INPUT`
- `BRANCH_PLAN`
- `SKIP_WITH_WARNING`
- `REQUEST_USER_INPUT`
- `STOP_SUCCESS`
- `STOP_BLOCKED`

`CALL_TOOL` requires a `skill_request`. `STOP_SUCCESS` and `STOP_BLOCKED` may omit it.

## Skill Request

`skill_request` has this shape:

```json
{
  "skill_name": "rank_evidence",
  "input_artifacts": ["evidence/evidence_cards.enriched.json"],
  "output_artifacts": ["ranked_evidence/evidence_selection.json"],
  "parameters": {},
  "reason": "Select representative evidence before reporting."
}
```

Validation rules:

- `skill_name` must exist in the A3 registry.
- Stub, disabled, and deprecated skills are rejected for executable requests.
- Input artifacts must be allowed by the read policy.
- Output artifacts must be allowed by the write policy.
- Shell commands are rejected unless a future policy explicitly allows them.
- Database mutation is rejected.
- Schema mutation is rejected.

## Rejection Cases

The contract can reject output with:

- `UNPARSEABLE_OUTPUT`
- `UNKNOWN_DECISION_TYPE`
- `UNREGISTERED_SKILL`
- `DISALLOWED_READ_PATH`
- `DISALLOWED_WRITE_PATH`
- `RAW_RETRIEVAL_TO_REPORT`
- `DATABASE_MUTATION_ATTEMPT`
- `SHELL_COMMAND_NOT_ALLOWED`
- `SCHEMA_MUTATION_ATTEMPT`
- `MISSING_REQUIRED_FIELD`
- `INVALID_ARTIFACT_REFERENCE`
- `OUT_OF_SCOPE_SKILL`

Each violation is structured and can be converted into a controller audit event.

## Raw Retrieval To Report

Report-building skills must not consume `retrieval/...` artifacts directly. Retrieval candidates may include raw chunks or broad source candidates that have not passed Evidence Card extraction, enrichment, ranking, and validation gates.

Reports should consume Evidence Cards, selected evidence, and downstream structured artifacts. This keeps later claims traceable to validated evidence rather than raw retrieval packets.

## A7 Usage

A7 can use this contract to:

1. Build a workspace access policy.
2. Ask the CLI to emit an output envelope.
3. Parse the envelope.
4. Reject violations before execution.
5. Convert accepted decisions to A2 `ControllerDecision`.
6. Convert violations or decisions to A5 `ControllerAuditEvent`.
7. Let the platform runtime execute approved skill wrappers and apply state or manifest updates.

A6 stops at the contract boundary.
