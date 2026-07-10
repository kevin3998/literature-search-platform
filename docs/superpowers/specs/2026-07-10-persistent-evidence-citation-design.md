# Persistent Evidence Citation Design

Date: 2026-07-10

## Summary

This design replaces the current turn-local evidence ID citation behavior with a persistent citation system for newly generated literature-search answers.

The current system lets the model cite evidence IDs such as `[E6082756]`, then validates those IDs against the evidence available in the current agent loop. This fails in follow-up turns when the model reuses citations from an earlier answer but the earlier evidence is no longer present in the limited `recent_evidence` set. In the observed server case, the warning IDs were real first-turn evidence, not fabricated citations. The failure came from losing the cross-turn evidence boundary.

The new system separates four concepts:

- `source_locator`: where the evidence came from in the retrieval/index system.
- `evidence_uid`: a stable platform evidence identity derived from source identity and content hash.
- `citation_alias`: the short citation marker visible to the model and user, such as `[1]`.
- `message_citation`: the durable record that maps one assistant message's alias to the exact evidence snapshot used at generation time.

Only new messages are covered. During this development phase, old messages without persistent citation records are not migrated or repaired.

## Goals

- New assistant answers use short numeric citations: `[1]`, `[2]`, `[3]`.
- Only evidence actually included in the LLM prompt can receive a citation alias.
- Only aliased evidence can be cited.
- Every legal citation in a new assistant message is saved as a durable `message_citations` row.
- Each saved citation includes the full evidence chunk snapshot, not only a short snippet.
- Follow-up turns can resolve previous-message citations from persisted `message_citations`, not from truncated `recent_evidence`.
- Citation audit no longer reports real previous-turn evidence as missing simply because it fell outside the recent evidence limit.
- UI continues to render compact citation chips and citation footer evidence lists.

## Non-Goals

- No old-message migration.
- No lazy backfill from legacy `[E#]` metadata.
- No long-term formal support for legacy `[E#]` citations as the new protocol.
- No globally unique visible citation numbers across a session.
- No cross-session citation reuse.
- No PDF page-level or bounding-box citation locator in this phase.
- No complex citation inspector UI in this phase.

## Current Problem

Relevant current behavior:

- `backend/modules/literature_search/agent/loop.py` keeps `self._available_evidence` for citation validation.
- Tool evidence and recent evidence are registered into that map.
- Final answer citation audit extracts IDs from the answer and checks whether each ID exists in the current available set.
- `backend/core/session_store.py` currently returns only a limited recent evidence set in session context.
- Assistant message metadata stores `citation.used_evidence`, but there is no authoritative message-to-evidence citation table.

This means a follow-up answer can contain citation IDs that were valid in a previous assistant answer but are not valid in the current loop. The audit then labels them as missing. That warning does not necessarily mean hallucination; it can mean the system forgot the previous evidence boundary.

## Data Model

### `evidence_records`

`evidence_records` stores stable platform-level evidence identity.

Suggested fields:

```text
evidence_record_id uuid primary key
evidence_uid text unique not null
source_type text not null
paper_id text
paper_stable_id text
doi text
title text
section_id text
chunk_index integer
index_version integer
source_locator_json jsonb not null default '{}'
content_hash text not null
latest_metadata_json jsonb not null default '{}'
created_at timestamptz not null
updated_at timestamptz not null
```

`evidence_uid` should not be the existing `E{documents.id}`. It should be derived from a normalized source identity plus content hash:

```text
ev_<sha256(canonical_json({
  source_type,
  paper_stable_id,
  section_id,
  chunk_index,
  content_hash
}))>
```

`paper_stable_id` priority:

```text
doi -> pmid -> arxiv_id -> corpus paper_id -> source_path/title fallback
```

The UID represents the evidence text identity, not a retrieval result ID.

### `message_citations`

`message_citations` stores what one assistant message actually cited.

Suggested fields:

```text
message_citation_id uuid primary key
message_id uuid not null references messages(message_id) on delete cascade
session_id uuid not null references sessions(session_id) on delete cascade
turn_id uuid references turns(turn_id) on delete set null
alias text not null
citation_marker text not null
evidence_uid text not null
evidence_record_id uuid references evidence_records(evidence_record_id)
source_locator_json jsonb not null default '{}'
paper_snapshot_json jsonb not null default '{}'
chunk_snapshot_text text not null
chunk_snapshot_hash text not null
display_snippet text
citation_context text
created_at timestamptz not null
unique(message_id, alias)
```

Indexes:

```text
index(message_id)
index(session_id, created_at)
index(turn_id)
index(evidence_uid)
unique(message_id, alias)
```

`evidence_items` remains a session retrieval/process log. It is not the authoritative record of final answer citations.

`messages.metadata_json.citation` remains a display and audit summary. The authoritative mapping is `message_citations`.

## Citation Protocol

New model-visible citations use only numeric aliases:

```text
[1], [2], [3]
```

The model should not cite `evidence_uid`, `documents.id`, `paper_id`, or any internal locator.

Each assistant message owns its own alias namespace. Different assistant messages can both use `[1]`. Internally, previous citations are resolved by:

```text
message_id + alias
```

The current in-progress answer resolves aliases by:

```text
turn_id + alias
```

or by the in-memory current-turn manifest before the assistant message is persisted.

Full-width numeric markers such as `【1】` may be parsed as equivalent to `[1]` to handle Chinese model output, but the prompt should instruct the model to use half-width square brackets.

## Turn Manifest

Before evidence enters the LLM prompt, the backend builds a current-turn citation manifest.

Example manifest item:

```json
{
  "alias": "1",
  "marker": "[1]",
  "evidence_uid": "ev_abc123",
  "source_locator": {
    "source_type": "literature_search",
    "document_id": 6082756,
    "paper_id": "paper_x",
    "section_id": "results",
    "chunk_index": 12,
    "index_version": 4
  },
  "paper": {
    "title": "...",
    "doi": "...",
    "year": 2024,
    "journal": "..."
  },
  "chunk_text": "Full evidence chunk text...",
  "display_snippet": "Short display snippet..."
}
```

The LLM sees a compact rendered form:

```text
[1] Title, year, section
Evidence text: ...
```

It does not see `evidence_uid` or internal document IDs as citable identifiers.

Hard rule:

```text
Only evidence included in the LLM prompt gets an alias.
Only aliases in the current or historical manifest can be cited.
```

This prevents the model from citing a tool result that was returned somewhere in the system but not actually visible in its prompt.

## Backend Components

Add a focused module:

```text
backend/modules/literature_search/agent/citations.py
```

Responsibilities:

```text
normalize_chunk_text(text)
content_hash(text)
paper_stable_id(evidence)
build_evidence_uid(evidence)
build_turn_manifest(evidence_items)
parse_citation_markers(answer)
resolve_citations(answer, current_manifest, historical_manifest)
build_message_citation_rows(message_id, resolved_citations)
```

Add an in-loop registry object:

```text
CitationRegistry
- current_manifest: alias -> evidence snapshot
- historical_manifest: message_id + alias -> previous citation snapshot
- register_tool_evidence(evidence_items)
- render_for_prompt(...)
- resolve_answer(answer)
```

The registry keeps citation-specific state out of the main agent loop.

## Generation Flow

Target flow:

```text
tool search/pack
-> collect citable evidence
-> CitationRegistry assigns aliases
-> tool response rendered to LLM with [1]/[2] markers
-> LLM answer
-> parse citation markers
-> resolve markers against current and historical manifests
-> emit citation event
-> append assistant message
-> insert message_citations
```

`session_store.append()` should return the created `message_id`. After appending the assistant message, the chat router records resolved citations:

```python
message_id = session_store.append(... assistant message ...)
session_store.record_message_citations(message_id, resolved_citations)
```

If recording citation rows fails for a new cited answer, the operation should be treated as a backend consistency failure. Persistent citations are core state, not optional decoration.

## Follow-Up Context

`session_store.context()` should add `recent_citations` alongside current `recent_messages` and `recent_evidence`.

Suggested shape:

```json
[
  {
    "message_id": "...",
    "turn_id": "...",
    "answer_excerpt": "...",
    "citations": [
      {
        "alias": "1",
        "title": "...",
        "doi": "...",
        "section": "...",
        "display_snippet": "...",
        "evidence_uid": "ev_..."
      }
    ]
  }
]
```

The agent should include historical citation summaries when the current user message is a follow-up. Examples include messages like "才 10 篇文献吗", "这些证据里", "上一轮提到的", or other context-dependent questions.

The prompt should distinguish historical citations from current-turn citations:

```text
Historical citations from previous assistant messages:
Message <id>:
[1] Zhang et al., 2023, Methods, ...

Use historical citations only when referring to previous answer content.
For new claims, use current retrieved evidence.
```

The historical prompt does not need to include every full chunk by default. Full chunks are stored in `message_citations` for audit and later retrieval. The prompt should include enough metadata and snippet text for the model to understand references to prior answers.

## Citation Audit Rules

For new messages:

- Legal alias in current manifest: verified current citation.
- Legal alias in historical manifest: verified historical citation.
- Alias not found in either manifest: `audit_status = "unverified"` and include it in `missing_ids`.
- No citations while current prompt contains citable evidence: `audit_status = "uncited"`.
- Citations disabled by settings: `audit_status = "off"`.

Illegal aliases are not written to `message_citations`.

Legal aliases are written to `message_citations` with full chunk snapshots.

`messages.metadata_json.citation` should include display-ready summary fields:

```json
{
  "audit_status": "verified",
  "cited_ids": ["1", "2"],
  "missing_ids": [],
  "used_evidence": [
    {
      "alias": "1",
      "evidence_uid": "ev_...",
      "title": "...",
      "section": "...",
      "snippet": "..."
    }
  ],
  "available_count": 8
}
```

## Frontend Behavior

`frontend/src/components/MarkdownMessage.jsx` should parse numeric citation markers:

```text
[1], [2], 【1】, 【2】
```

`frontend/src/components/MessageBubble.jsx` should continue to render:

- inline citation chips;
- hover/focus tooltip with title, section, snippet;
- citation footer with used evidence;
- warning state for missing aliases.

The UI should not expose internal IDs such as `E6082756`, `documents.id`, or `evidence_uid` as the primary citation label.

The footer should rely on backend-provided `citation.used_evidence`, which is derived from resolved citation records for new messages.

## Testing Plan

Backend tests:

- `build_evidence_uid()` returns the same UID for the same stable paper identity, section, chunk index, and normalized chunk text.
- Different chunk text produces a different UID.
- The turn manifest assigns aliases only to evidence rendered into the LLM prompt.
- Citation parser accepts `[1]` and `【1】`.
- `[99]` is marked missing when absent from current and historical manifests.
- Legal citations write `message_citations` rows.
- Saved rows include full `chunk_snapshot_text`.
- `session_store.context()` returns `recent_citations`.
- Follow-up resolution can validate historical citations without relying on `recent_evidence`.
- No-citation answers with available citable evidence are marked `uncited`.
- `session_store.append()` returning `message_id` does not break existing callers.

Frontend tests:

- `MarkdownMessage` renders numeric citation chips.
- Citation footer displays backend `used_evidence`.
- Missing aliases render as unverified.
- The literature search view model reads the new citation shape.

Integration tests:

- First turn retrieves evidence and answers with `[1]`, `[2]`.
- Assistant message saves `message_citations`.
- Follow-up question references prior answer.
- Follow-up answer can reuse historical citations without missing-ID warnings.

## Rollout

Development rollout only:

1. Add citation tables and store methods.
2. Add citation utility module and unit tests.
3. Change agent tool rendering to numeric aliases.
4. Change final citation audit to resolve aliases through manifests.
5. Persist `message_citations` after assistant message append.
6. Add `recent_citations` to session context.
7. Update frontend parser and tests.
8. Run backend and frontend contract tests.

Old sessions are not migrated. During development, old messages may still show legacy citation behavior or warnings.

## Acceptance Criteria

- A new literature-search answer with valid citations saves durable `message_citations`.
- Each saved citation includes full chunk text, source locator, paper snapshot, alias, and evidence UID.
- A follow-up turn can validate a previous answer's citation even if that evidence is not in `recent_evidence`.
- Fabricated numeric aliases are still flagged.
- The frontend shows compact numeric citation chips and footer evidence.
- The system no longer treats real previous-turn citations as missing solely because of recent evidence truncation.
