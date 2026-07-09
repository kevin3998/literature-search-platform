# User Workspace Boundary

## Purpose

This document defines the lightweight user and workspace boundary that prepares the platform for later server deployment and account management.

This is not a full account system. It adds a stable ownership boundary so future login, team sharing, and per-user storage can attach to the existing backend without rewriting sessions, workflows, jobs, artifacts, or research workspaces.

## Current Mode

The platform remains single-user compatible by default:

- requests without identity use `local_user`
- local development behaves as before
- tests and development tools may pass `X-User-Id`
- production must not trust a raw browser-provided `X-User-Id`

In production, a real authentication layer should derive the user context from a signed session, cookie, reverse-proxy identity, or token, then populate the same backend `UserContext`.

## User Context

The backend user boundary is `core.user_context.UserContext`.

`UserContext` contains:

- `user_id`
- `workspace_slug`

The current bridge accepts `X-User-Id` for development and tests. Valid user ids are filesystem-safe slugs using only letters, numbers, `_`, `.`, and `-`. Empty ids, path-like ids, absolute paths, slashes, backslashes, and `..` are rejected.

## Data Ownership

Sessions are the primary ownership anchor.

Session-owned data:

- messages
- turns
- search results
- evidence items
- research state
- paper curation state
- research state events
- tool traces
- session artifact links

These tables remain linked through `session_id`; callers must prove access to the parent session.

Explicitly user-owned data:

- `sessions.user_id`
- `workflow_runs.user_id`
- `jobs.user_id`
- `artifacts.user_id`

Shared platform-level data for now:

- shared literature corpus
- shared search/index data
- global settings
- model profiles and secrets
- corpus maintenance jobs

User-level settings and secrets belong to the future account-management phase.

## File Ownership

User-owned outputs go under:

```text
.runtime/users/{user_id}/
```

Production can override the root:

```bash
export LITERATURE_USER_DATA_ROOT=/srv/literature-agent/users
```

Expected user workspace subdirectories:

```text
research_agent/research_tasks/
research_agent/workflow_ideas/
exports/
uploads/
```

The shared literature corpus remains controlled separately by `LITERATURE_DATA_DIR`.

## API Boundary

The frontend does not implement login yet. It has a small adapter hook for development and tests:

- default: no `X-User-Id` header
- optional: configured user id is sent by the API adapter
- store/UI continue to consume normalized camelCase models

Backend wire format remains snake_case.

## Deployment Notes

For server deployment, mount or back up these roots:

```bash
export LITERATURE_MEMORY_DB_PATH=/srv/literature-agent/platform_memory.sqlite
export LITERATURE_USER_DATA_ROOT=/srv/literature-agent/users
export LITERATURE_DATA_DIR=/srv/literature-agent/shared_literature_data
```

Later account management should replace the development header bridge with authenticated user context. The business stores and workflow runtime should continue receiving the same `user_id` boundary.

## Non-Goals

This boundary does not add:

- signup
- login UI
- passwords
- invitations
- user roles
- team sharing
- user-level model secrets
- database row-level permissions outside the application layer
