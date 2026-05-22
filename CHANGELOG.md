# Changelog

All notable changes to this project will be documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **OAuth mode now uses FastMCP v3 native auth.** The hand-rolled `RedmineOAuthMiddleware` (Starlette `BaseHTTPMiddleware`) is replaced by `RemoteAuthProvider(token_verifier=IntrospectionTokenVerifier(...))`. Token validation moves from `GET /users/current.json` to Doorkeeper's RFC 7662 introspection endpoint (`POST /oauth/introspect`), exposing the token's actual scopes via `AccessToken.claims`. This closes the medium-likelihood `custom_route` middleware-skip-list auth-bypass risk identified in the FastMCP v3 compatibility analysis.

### Breaking
- **Two new required env vars in OAuth mode**: `REDMINE_INTROSPECT_CLIENT_ID` and `REDMINE_INTROSPECT_CLIENT_SECRET`. Operators register a confidential OAuth client in Redmine and patch Doorkeeper's `allow_token_introspection` block (stock Redmine ships with `allow_token_introspection false`). See [`docs/oauth-setup.md`](docs/oauth-setup.md) Step 2 for the walkthrough. Server fails fast at startup if either env var is missing.
- **Discovery path aliases dropped.** Only the canonical paths remain:
  - `GET /.well-known/oauth-protected-resource/mcp` (RFC 9728 §3.1 suffix-scoped, mounted natively by `RemoteAuthProvider`)
  - `GET /.well-known/oauth-authorization-server` (canonical root, kept as `custom_route` mirror of Redmine's Doorkeeper AS metadata)

  These previously-served paths now return 404: `/.well-known/oauth-protected-resource` (root), `/mcp/.well-known/oauth-protected-resource` (prefix), `/.well-known/oauth-authorization-server/mcp` (suffix), `/mcp/.well-known/oauth-authorization-server` (prefix). Clients should follow `WWW-Authenticate: Bearer resource_metadata="..."` headers from 401 responses for RFC 9728 §5.3 compliant discovery.
- **Upstream introspection failures now return 401 instead of 503.** When Doorkeeper is unreachable, the previous behavior was `503 upstream_unavailable`. FastMCP's `IntrospectionTokenVerifier` treats transport failures as auth failures, so clients see 401. Operators monitoring 503 spikes as an upstream-Redmine-down signal should switch to monitoring 401-rate or watch `/health`'s new introspection probe (see Added).

### Added
- `/health` now probes Doorkeeper's introspection endpoint in OAuth mode and surfaces the result as `{"status": "ok"|"degraded", "checks": {"introspection": "ok"|"unreachable", "introspection_detail": "..."}}`. Response remains HTTP 200 so container orchestrators continue treating the endpoint as a binary liveness probe; monitoring systems should inspect the JSON `status` field. Results cached per `HEALTH_INTROSPECTION_TTL_SECONDS` (default 30s) to avoid hammering Doorkeeper on every health check.
- Live OAuth integration test suite (`tests/test_oauth_integration.py`) that exercises real Doorkeeper introspection against a sandbox Redmine. Runs only under `--integration` with sandbox creds, skips cleanly with a clear message when unconfigured. See [`docs/contributing.md`](docs/contributing.md) "Live OAuth Integration Tests".
- Structured warning logs on introspection upstream failures (`introspection_upstream_failure status_code=... url=...`) so log-based alerting can distinguish real upstream issues from per-token 401s.

### Removed
- `src/redmine_mcp_server/oauth_middleware.py` (replaced by FastMCP native auth in `src/redmine_mcp_server/_auth.py`).
- `tests/test_oauth_middleware.py` (replaced by `tests/test_oauth_auth.py` and `tests/test_oauth_discovery.py`).

### Documentation
- `docs/oauth-setup.md`: Step 2 rewritten with a Redmine-specific gotcha. The previously recommended approach of adding a separate `config/initializers/doorkeeper.rb` with a fresh `Doorkeeper.configure` block silently wipes Redmine's entire Doorkeeper configuration (admin_authenticator, resource_owner_authenticator, grant_flows, scopes), because Doorkeeper's `configure` rebuilds the Config wholesale rather than merging. The only safe override is editing the existing `Doorkeeper.configure` block in Redmine's `config/initializers/30-redmine.rb` in place. Also adds a note that `Setting.rest_api_enabled` must be true for Administration → Applications to be accessible.
- `docs/troubleshooting.md`: "all MCP requests return 401" diagnostic flow gains an entry for the standalone-initializer wipe symptom, which is otherwise indistinguishable from a misconfigured introspection client without checking the Doorkeeper warning log.
- `docs/contributing.md`: Reorganized the live OAuth integration test instructions around `.env`-based configuration (which the test module now honors). `python tests/run_tests.py --integration` runs both general and OAuth integration suites. For OAuth-only filtering, the doc points at `python -m pytest tests/test_oauth_integration.py` directly because `run_tests.py` does not forward `-k`-style filters.
- **Docs audit pass** (no behavior changes):
  - `README.md`: Corrected stale tool counts — "44 MCP Tools" → "45 + 1 admin-gated"; "46 tools" header → "45 (+1)"; Issue Operations "(12 tools)" → "(13 tools)" to match `tools/issues.py`.
  - `docs/contributing.md`: Rewrote the architecture section for the v2.1 surface. Removed stale references to `oauth_middleware.py`, the `ContextVar`-based token mechanism, and the `GET /users/current.json` validation path. Added `_auth.py`, `oauth_scopes.py`, `_tool_error_middleware.py` and the missing `tools/documents.py` / `tools/meta.py` modules to the inventory tables. Updated counts: 13 tool modules (was 11), 45 tools + 1 admin-gated (was 43).
  - `docs/tool-reference.md`: Completed the read-only mode tool list in §157-176. The previous summary omitted `copy_issue`, `upload_file`, `delete_file`, `import_time_entries`, `update_checklist_item`, `manage_redmine_version`, and `manage_document` — all of which actually gate writes via `ActionMode.WRITE` per the per-tool sections.
  - `roadmap.md`: Refreshed the Project Status block — v2.0.0 → v2.0.1 current, v2.1 noted as merged-to-develop, test count 1339 → 1365 (1285 unit + 80 integration). Updated "Last Updated" stamp.
  - `docs/oauth-setup.md`, `docs/troubleshooting.md`, `src/redmine_mcp_server/_env.py`, `src/redmine_mcp_server/_auth.py`, `tests/test_oauth_integration.py`: Unified the operator-facing terminology around "confidential" rather than `protected_resource?`. Doorkeeper's `Application#protected_resource?` is an alias for `confidential?` and isn't a separate UI toggle in Redmine's Admin → Applications form, so describing the requirement as "confidential" matches what operators actually click.

### Dependencies
- Bump `fastmcp` from 3.2.4 to 3.3.1 ([#128](https://github.com/jztan/redmine-mcp-server/pull/128)). Includes OAuth proxy hardening (silent-consent AS-in-the-middle guard, redirect URI dot-segment rejection, per-token response cache partitioning), `OAuthProxy.update_scopes()` public API, streamable-HTTP transport shutdown fix, and OTEL semconv compliance for list operations. The 3.3 packaging split (introducing `fastmcp-slim`) preserves all public import paths; 3.3.1 hotfixes a circular-import regression in 3.3.0.
- Bump `uvicorn` from 0.46.0 to 0.47.0 ([#127](https://github.com/jztan/redmine-mcp-server/pull/127)). Upstream adds an `ssl_context_factory` hook, eagerly imports the ASGI app in the parent process, and fixes `fd=0` handling under reload/workers. No behavioral impact for this server.

### Fixed
- `tests/test_oauth_integration.py` now calls `python-dotenv`'s `load_dotenv()` at module-import time, so `REDMINE_URL` (and any other config) defined in `.env` is honored by the integration suite without having to re-export the var on the command line. Previously the test module read `os.environ` directly at import time, which meant the suite skipped with "Missing: REDMINE_URL" unless the var was set in the shell, even when it was already in `.env` for the running server.

## [2.0.1] - 2026-05-22
### Security
- Bump `urllib3` from 2.6.3 to 2.7.0, patching CVE-2026-44431 and CVE-2026-44432; added explicit lower-bound constraint (`urllib3>=2.7.0,<3`) in `pyproject.toml` to prevent silent regression to vulnerable versions (urllib3 is a transitive dep via `requests` / `python-redmine`, so it had no direct floor before this).

### Fixed
- OAuth discovery documents now advertise `scopes_supported` on both `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`. Without this field, MCP clients fell back to Doorkeeper's default scopes (`view_project`, `search_project`, `view_members`), so tools needing other permissions (`list_redmine_issues`, `get_redmine_issue`, `list_time_entries`, `list_redmine_versions`, `summarize_project_status`, and similar) returned 403 against OAuth-mediated requests. Read-only mode (`REDMINE_MCP_READ_ONLY=true`) hides write scopes from the advertised list. Resolves [#130](https://github.com/jztan/redmine-mcp-server/issues/130).
- OAuth discovery documents are now also served at path-aliased locations (`/mcp/.well-known/...` and `/.well-known/.../mcp`) so MCP clients that don't query the canonical root paths can still bootstrap the OAuth flow.
- OAuth discovery now advertises Redmine's actual document permissions (`add_documents`, `edit_documents`, `delete_documents`) instead of the inferred-but-nonexistent `manage_documents`. The original #130 fix derived the scope from the `manage_X` pattern used by `manage_wiki`/`manage_versions`/`manage_files`, but Redmine's documents subsystem uses the granular `add_/edit_/delete_` triad (same shape as issues). Redmine 6 / Doorkeeper enforces `enforce_configured_scopes` against `Redmine::AccessControl.permissions`, so advertising `manage_documents` caused `/oauth/authorize` to reject the consent request with `invalid_scope: requested scope is invalid, unknown, or malformed`, breaking the entire OAuth flow for any client that requested the full advertised scope set. Added a regression guard `tests/test_oauth_scopes.py::test_advertised_scopes_are_real_redmine_permissions` that checks every advertised scope against a committed snapshot of `Redmine::AccessControl.permissions` (`tests/fixtures/redmine_6_permissions.txt`), so future pattern-based inference mistakes fail in unit tests rather than at a customer's consent screen.

### Contributors

- @timcomport, reported [#130](https://github.com/jztan/redmine-mcp-server/issues/130) with detailed diagnosis, reproduction steps, and analysis of prior PR #85's limitations.
- @aadnehovda, contributed the path-aliased discovery endpoints concept via [`codex-dcr-compat`](https://github.com/aadnehovda/redmine-mcp-server/tree/codex-dcr-compat) fork, and identified the invalid `manage_documents` scope via live-test against Redmine 6 / Doorkeeper.

## [2.0.0] - 2026-05-16
### Added
- **`delete_redmine_issue`**: new tool exposing irreversible issue deletion via Redmine's `DELETE /issues/{id}.json`. The MCP surface previously had `create_redmine_issue` / `update_redmine_issue` / `copy_issue` / `get_redmine_issue` but no way to delete, so operators had to drop to the Redmine UI or python-redmine directly. Named to sit alongside the other `*_redmine_issue` lifecycle tools rather than under the `manage_X(action=...)` pattern, since there is only one verb. Mirrors the `delete_file` safety pattern: refuses unless `confirm_delete=True`, with a structured `impact` preview (cascade counts for children, journals, attachments, time entries, inbound relations) in the refusal envelope. Subtask cascade requires a second opt-in (`confirm_delete_with_children=True`) so silent subtask destruction can't happen on a single misclick. Read-only mode blocks the call before any Redmine round-trip. Structured for the agent path (clear error codes `CONFIRMATION_REQUIRED` / `CHILDREN_PRESENT` / `NOT_FOUND`) and the operator path (explicit cascade preview). 14 tests in `tests/test_delete_redmine_issue.py` cover the gate, the cascade preview, 404 handling at fetch and at delete time, invalid input, and read-only blocking ([#120](https://github.com/jztan/redmine-mcp-server/issues/120)). Tool count: 45 → 46.
- **`get_mcp_server_info`** (no args, always callable): returns `{server_version, read_only_mode, auth_mode, plugin_flags: {agile, checklists, products, crm, dmsf}}`. Surfaced as an MCP tool so an LLM caller can detect deployment lag before relying on a recently-shipped fix -- compare `server_version` against the release / commit you expect. The response intentionally excludes credentials, internal hostnames, and file-system paths; only flags that change *call shape* are surfaced. Package version is sourced from installed metadata via `importlib.metadata`. Drift-guard: a regression test pins the exact set of returned keys plus the plugin-flag inventory so a future leak of `REDMINE_URL` / `REDMINE_API_KEY` / `PUBLIC_HOST` into this response would fail CI loudly ([#124](https://github.com/jztan/redmine-mcp-server/issues/124)). Tool count: 44 → 45.
- **`manage_document`** (gated by `REDMINE_DMSF_ENABLED=true`): single MCP tool covering DMSF (Document Management System for Files) plugin operations via an `action` parameter. Requires the `redmine_dmsf` plugin (GPL v2) on the Redmine server.
  - `action="list"`: list documents in a project (or a specific DMSF folder via `folder_id`); supports `limit` (capped at Redmine's server-side 100/request)
  - `action="get"`: fetch a single document's metadata by `document_id`
  - `action="create"`: upload a new document — two-step under the hood (`POST /uploads.json` to get a token, then `POST /projects/{id}/dmsf/commit_files.json` with metadata). Accepts `content_base64` (raw bytes as base64), `filename`, `title`, `description`, `comment`, `folder_id`, `version`, `custom_fields`. Decoded payload capped at 50 MiB.
  - `action="update"`: update metadata fields (`title`, `description`, `comment`, `custom_fields`) by creating a **new revision** — DMSF is versioned and does not support in-place mutation. DMSF filenames are immutable; to replace file content, `create` a new revision with the same filename.
  - User-controlled fields (`filename`, `title`, `description`, `name`, plus nested `author.name`) wrapped in `<insecure-content>` boundary tags
  - Write actions respect `REDMINE_MCP_READ_ONLY` and require `_is_valid_project_id` / `_is_positive_int` validation on path parameters
  - Whitelist filtering on `update` rejects unknown / immutable keys (e.g., `filename`) with a clear error pointing at the create-new-revision workaround
  - 31 new unit tests covering feature-flag gating, all four actions, read-only mode, validation paths, base64 decoding errors, size-cap rejection, response shape variants (`{dmsf: [...]}` vs bare list)
- `REDMINE_DMSF_ENABLED` environment variable (default `false`) documented in `.env.example`, `.env.docker.example`, and README
- `_is_dmsf_enabled()` helper in `_env.py`

### Changed
- Renamed `.env.docker` (previously tracked-but-gitignored placeholder, which trapped local edits as ongoing "modified" status and risked accidental commit of real credentials) to `.env.docker.example`, matching the `.env.example` convention. Users now copy `.env.docker.example` to `.env.docker`, which stays untracked. `deploy.sh` and the README quick-start were updated to copy from the new template name.

### Changed
- **List/search tools now return a flat `{"error": ...}` envelope on failure (was sometimes `[{"error": ...}]`)**: before #117 several list-shaped tools (`list_redmine_projects`, `list_project_issue_custom_fields`, `list_redmine_versions`, `list_project_members`, `list_time_entries`, `list_time_entry_activities`, `list_redmine_issues`, and the validation-error paths inside several others) returned their error envelope wrapped in a single-element list to satisfy a strict `List[Dict[str, Any]]` return type. An agent that wanted to distinguish "failed call" from "empty result" had to check `len(result) == 1 and "error" in result[0]` for some tools and `isinstance(result, dict) and "error" in result` for others. After #117 every list/search tool's return type is widened to `Union[List, Dict]` and the failure path returns the flat `{"error": ...}` shape consistently. Backward-incompatible for callers that were keying off the array-wrapped form; the new shape matches the convention every other tool already follows. Drift-guard in `tests/test_list_error_envelope_consolidation.py` parametrizes across the list-tool surface and asserts a controlled exception inside each one produces a dict envelope, never an array ([#117](https://github.com/jztan/redmine-mcp-server/issues/117)).

### Fixed
- **Wiki attachments now expose `content_url` and `author` (cross-tool shape symmetry)**: `manage_redmine_wiki_page(action="get", include_attachments=True)` used to return each attachment without `content_url` or `author`, while `get_redmine_issue(include_attachments=True)` returned both. The asymmetry cost an agent a turn when handing off between the two read paths. Both code paths now route through a single new helper `_attachment_to_dict()` in `_serialization.py`, so the dict shape is identical: `{id, filename, filesize, content_type, description, content_url, author, created_on}`. Wrap policy from #109 is preserved consistently (filename verbatim, description wrapped, author via `_named_ref`), and `content_url` is routed through `_rewrite_to_public_url` (#110) so `REDMINE_PUBLIC_URL` rewriting also applies to wiki attachments now. The shared helper means future attachment-serialization changes touch one site instead of three (issue, wiki, project file all use it -- DMSF still has its own raw-dict serializer because its payload shape differs, but the wrap policy lines up). A regression test in `tests/test_attachment_shape_symmetry.py` pins the canonical key set and asserts the issue and wiki paths produce identical dicts (modulo the wrap-tag nonce on `description`) ([#118](https://github.com/jztan/redmine-mcp-server/issues/118)).

### Added
- **`create_redmine_issue` now accepts custom fields by name in `fields`**: `fields={"Department": "Engineering"}` is resolved to `custom_fields=[{"id": N, "value": "Engineering"}]` automatically, bringing create to parity with `update_redmine_issue`. The shared resolution helper (`_resolve_named_custom_fields` in `_custom_fields.py`) is called from both paths: the update wrapper still does its issue-id-to-project-id lookup, the create wrapper takes `project_id` directly. Ambiguous names raise; values are validated against the field's `possible_values`. Closes the verification-thread asymmetry surfaced during #119 round-8; the validation-error hint is simplified now that the name-keyed shape works on both tools ([#123](https://github.com/jztan/redmine-mcp-server/issues/123)).

### Changed
- **Padded `get_redmine_issue` and `create_redmine_issue` descriptions for tool_search recall**: the first sentence of each docstring now includes synonym phrasings (`get_redmine_issue`: "fetch issue details", "view a ticket", "show a bug report", "get issue with comments"; `create_redmine_issue`: "open a ticket", "file a bug", "submit a feature request", "log a support case", "report a task") so semantic-search-based tool discovery hits them on the call shapes an agent actually reaches for. Eval-driven: \`tool_search\` was missing \`get_redmine_issue\` on common phrasings until a multi-word query like "retrieve single issue with attachments journals" landed. The terse one-liner descriptions were doing too little work given how high-traffic these two tools are. Cross-references to neighbor tools (\`list_redmine_issues\`, \`search_redmine_issues\`, \`copy_issue\`, \`update_redmine_issue\`) added at the same time so an agent landing on the wrong one is steered to the right one without an extra round trip ([#113](https://github.com/jztan/redmine-mcp-server/issues/113)).
- **`import_time_entries.entries` no longer accepts a JSON-string variant**: tightened from `Union[List[Dict], str]` to `List[Dict[str, Any]]`. The string-then-parse path was an MCP oddity (most clients pass arrays natively), introduced a parallel error mode, and prevented the FastMCP boundary middleware from validating per-entry shape up front. Now the schema rejects strings/scalars at the boundary with the standard `INVALID_ARGUMENTS` envelope from #108; direct Python callers passing a non-list hit a defense-in-depth guard with the same shape. Removes one line of unused `import json` from the module ([#114](https://github.com/jztan/redmine-mcp-server/issues/114)).
- **`cleanup_attachment_files` is now operator-gated**: the tool is no longer registered on the default MCP surface. It is admin/cron-style functionality (the background cleanup task in `_cleanup.py` already runs on the `CLEANUP_INTERVAL_MINUTES` schedule, so an LLM agent should almost never need it) and was creating discovery-noise an agent could waste a turn investigating. Operators driving cleanup through the MCP surface set the new **`REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`** env var to opt in; the function remains importable directly for internal callers (tests, scripts) regardless of the flag. The underlying background cleanup behavior is unchanged ([#115](https://github.com/jztan/redmine-mcp-server/issues/115)).
- **`create_redmine_issue` / `update_redmine_issue` validation-error envelope now carries a tailored recovery hint**: when Redmine rejects with `"<field> cannot be blank"` / `"is not included in the list"` / `"is invalid"`, the returned error dict is augmented with `missing_required_fields` (parsed names) and a `hint` whose body branches on whether the failing fields are Redmine standard fields, custom fields, or both. **Standard fields** (Subject, Priority, Tracker, Status, Assignee, etc.) get a hint pointing at the top-level / `fields={"priority_id": N}` shape with a pointer to the relevant discovery tool (`list_redmine_issue_priorities` etc.). **Custom-looking fields** get a hint covering the working `extra_fields={"custom_fields": [{"id": N, "value": "..."}]}` shape on create, the name-keyed shape on update, and the `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS` retry path. The custom-field branch also carries the #119 discovery-mismatch caveat: `list_project_issue_custom_fields` only reflects the field-definition `is_required` flag, while workflow rules, role-based field permissions, and tracker-bound required-field settings can still require fields at create/update time. `list_project_issue_custom_fields` docstring updated with the same caveat plus the create/update recovery asymmetry (name-keyed shortcut on update only; tracked separately in #123) ([#119](https://github.com/jztan/redmine-mcp-server/issues/119)).
- **`manage_document` aligned with the post-#109 / #111 / #112 conventions**: the DMSF document-management tool that landed in PR #104 was prepared before the wrap-policy, bounded-limit, and action-enum changes shipped, so it carried three small drifts at merge time. Cleaned up: (1) `action` is now `Literal["list", "get", "create", "update"]` so the JSON schema exposes the enum to strict MCP clients; (2) `limit` is `Annotated[int, Field(ge=1, le=100)]` so out-of-range values are rejected at the FastMCP boundary by `CleanValidationErrorMiddleware` (#108); (3) `_document_to_dict` now returns `filename`, `name`, `title`, and `author.name` verbatim (only `description` stays wrapped), matching the wrap policy from #109. The three drift-guard fixtures (`tests/test_manage_action_schema.py`, `tests/test_limit_offset_schema.py`, `tests/test_wrap_policy.py`) now cover `manage_document` so future drift fails CI loudly ([#122](https://github.com/jztan/redmine-mcp-server/issues/122)).
- **`list_redmine_issues.assigned_to_id` and `list_time_entries.user_id` now reject arbitrary strings**: both filter parameters used to be typed `Optional[Union[int, str]]` so they could accept the Redmine sentinel `"me"`, but the wide `str` branch also silently accepted any other string (`assigned_to_id="garbage"` returned `[]` -- the classic "agent reasons over the wrong count" footgun). Tightened to `Optional[Union[int, Literal["me"]]]` so the JSON schema renders the string branch as a `const: "me"` enum, and `CleanValidationErrorMiddleware` (#108) rejects out-of-set values at the FastMCP boundary with the standardized `INVALID_ARGUMENTS` envelope listing both accepted shapes. Backward-incompatible only for callers that were passing strings other than `"me"` -- those calls were silently returning empty results, so the new error is strictly an improvement. Write-side `user_id` / `assigned_to_id` parameters (create/update/manage tools, `manage_project_member`, `manage_issue_watcher`, `manage_time_entry`) are unaffected -- they were already correctly typed as `Optional[int]` ([#116](https://github.com/jztan/redmine-mcp-server/issues/116)).
- **Stop wrapping structured-metadata fields in `<insecure-content>` boundary tags**: the wrapping was originally applied to every user-controllable string returned by the server (filenames, display names, short labels) on the theory that any text from Redmine could carry a prompt-injection payload. In practice, the wrapping created downstream friction (filenames had to be stripped before being used as paths/URLs/identifiers; assistant-rendered names showed boundary tags) without materially raising the bar against short-label injection. Following the eval recommendation in #109, the policy is now: **free-text fields stay wrapped** (`description`, `notes`, journal content, time-entry `comments`, wiki page `text`, search `excerpt`, attachment `description`, version/product/contact `description`/`background`); **structured metadata is returned verbatim** (filenames, all `_named_ref` display names -- author, version, project, tracker, status, role, etc. -- issue/checklist subjects, product/contact name fields, codes, identifiers). Affected return shapes: `get_redmine_issue.attachments[*].filename`, `get_redmine_attachment.filename`, `list_files`/`upload_file` filename, contact `first_name`/`last_name`/`middle_name`/`company`/`job_title`/`assigned_to.name`, product `name`/`code`/`project.name`/`category.name`, issue category `name`, project member role `name`, gantt issue `subject` and version `name`. Backward-incompatible for any caller that explicitly stripped wrapper tags from these fields -- such callers can simplify. A pinning regression test in `tests/test_wrap_policy.py` documents both halves of the policy so accidental drift fails CI ([#109](https://github.com/jztan/redmine-mcp-server/issues/109)).

### Added
- **`limit` and `offset` now carry explicit bounds in the JSON schema**: every list/search tool's `limit` and `offset` parameter is now annotated with `Annotated[int, Field(ge=..., le=...)]` (or `Optional[int]` for `journal_limit`, where `None` semantically means "no pagination") so strict MCP clients see the bounds, and out-of-range values are rejected at the FastMCP boundary by `CleanValidationErrorMiddleware` (#108) with the standardized `INVALID_ARGUMENTS` envelope. Previously, three tools (`list_redmine_issues.limit`, `search_redmine_issues.limit`, `get_redmine_issue.journal_limit`) rendered as the `any`-shaped `Optional[int]` with no constraints, and even the `int`-typed ones had no bounds despite their docstrings claiming caps. Affected tools and caps: `get_gantt_chart.limit` (1-500), `get_redmine_issue.journal_limit/journal_offset` (1-1000 / 0+), `list_redmine_issues.limit/offset` (1-1000 / 0+), `list_redmine_users.limit/offset` (1-100 / 0+), `list_time_entries.limit/offset` (1-100 / 0+), `manage_contact.limit` (1-100), `manage_product.limit` (1-100), `search_entire_redmine.limit/offset` (1-100 / 0+), `search_redmine_issues.limit/offset` (1-1000 / 0+). Existing defensive runtime clamping (e.g. `min(limit, 1000)`) is left in place for direct Python callers, where Pydantic validation does not run ([#111](https://github.com/jztan/redmine-mcp-server/issues/111)).
- **`REDMINE_PUBLIC_URL` env var + serializer-layer URL rewrite**: when Redmine is configured with an internal hostname (typical in Docker, e.g. `http://redmine:3000`), the `content_url` it echoes back on attachments is unreachable from MCP clients on the host or the open internet, and a less-careful agent can waste a turn web-fetching it. A new `_rewrite_to_public_url()` helper rewrites any URL whose scheme+host+port matches `REDMINE_URL`'s origin to use `REDMINE_PUBLIC_URL`'s origin instead, preserving path/query/fragment; foreign URLs (CDN-hosted assets, pre-rewritten values) are left untouched. Applied at the serializer layer (`_file_to_dict`, `_attachments_to_list`) so every code path returning attachment metadata benefits. The internal download path in `get_redmine_attachment` deliberately uses the raw URL — that call goes server-to-Redmine and must stay on the internal hostname. When `REDMINE_PUBLIC_URL` is unset (the default), the raw URL is returned and callers can fall back to `get_redmine_attachment` for a sandbox-safe download URL via the MCP server's proxy ([#110](https://github.com/jztan/redmine-mcp-server/issues/110)).
- **`manage_*` tools: `action` is now a JSON-schema enum** instead of a free-form string. The 10 `manage_X` tools (`manage_contact`, `manage_issue_category`, `manage_issue_note`, `manage_issue_relation`, `manage_issue_watcher`, `manage_product`, `manage_project_member`, `manage_redmine_version`, `manage_redmine_wiki_page`, `manage_time_entry`) declare `action` as a `Literal[...]` so strict MCP clients can validate the value, permissive clients get autocomplete, and invalid actions are rejected at the FastMCP boundary (with the standardized `INVALID_ARGUMENTS` envelope from #108) rather than reaching the dispatch decorator. A schema regression test pins each tool's allowed action set so drift between the dispatch spec and the public signature breaks loudly ([#112](https://github.com/jztan/redmine-mcp-server/issues/112)).
- **`list_redmine_issues`**: `status_id` now accepts Redmine's documented sentinel strings (`"open"`, `"closed"`, `"*"`) in addition to a numeric status ID. Previously, passing `status_id="open"` (the first thing many LLM callers reach for, and the shape Redmine's REST API itself accepts) failed with a raw Pydantic int-parsing error; callers had to discover the `filters={"status_id": "open"}` escape hatch. The widened type (`int | Literal["open", "closed", "*"]`) is reflected in the tool's JSON schema, so strict MCP clients also see the new accepted values ([#107](https://github.com/jztan/redmine-mcp-server/issues/107)).
- **Pydantic-validation-error boundary middleware**: a new FastMCP middleware (`CleanValidationErrorMiddleware`) intercepts argument-validation `pydantic.ValidationError`s raised before the tool body runs and returns the project's standard envelope (`{"error", "hint", "code": "INVALID_ARGUMENTS", additional_errors?}`) as both text and `structured_content`. Previously, the raw Pydantic v2 dump (including `errors.pydantic.dev` URLs) leaked through to the MCP caller, which was verbose and not actionable inside an LLM loop. The middleware honors FastMCP's `x-fastmcp-wrap-result` output-schema convention (tools returning `Union[List, Dict]`, etc.), so the envelope reaches strict clients intact instead of tripping a misleading "Output validation error: 'result' is a required property" on the client side. Union/Literal mismatches collapse all branch complaints into a single `error` message ("expected int or one of 'open','closed','*'"). Missing-required-argument errors name the parameter explicitly instead of echoing the whole args dict ([#108](https://github.com/jztan/redmine-mcp-server/issues/108)).

### Fixed
- **`get_redmine_attachment`**: when Redmine's `GET /attachments/{id}.json` returns 404, the tool now returns a structured envelope (`code: ATTACHMENT_UNAVAILABLE`, `upstream_status: 404`, plus a `hint`) instead of a bare `"Attachment N not found."` message. Redmine collapses three distinct conditions into the same 404 (genuine deletion, lack of view permission on the container, and orphan metadata whose underlying file is unreadable on the server's disk); callers that see the attachment via `get_redmine_issue(include_attachments=True)` but get 404 here are usually hitting one of the last two. The new hint surfaces those causes and points to the embed path as the workaround so LLM callers can recover without a second wrong-tool round-trip ([#106](https://github.com/jztan/redmine-mcp-server/issues/106)).
- **`search_redmine_issues`**: previously returned `null` for `subject`, `status`, `priority`, `project`, `assigned_to`, `author`, `created_on`, and `updated_on` regardless of what `fields` requested, because Redmine's `/search.json` endpoint only populates `id` and a description snippet. The tool now transparently hydrates each search hit via `/issues.json` (with `status_id="*"` so closed matches still hydrate), preserving search relevance order and falling back per-issue to the sparse search result for any id missing from the hydration response (e.g., deleted between calls). Hydration is skipped when `fields` only requests `id` and/or `description`, so the lightweight one-call path is still available. Hydration failures are logged and degrade gracefully to the previous sparse behavior rather than raising. Large id sets are batched at 100 ids per `/issues.json` call to stay within typical URL-length limits.

### Security
- Pin all GitHub Actions to immutable commit SHAs across all workflows to prevent supply chain attacks via tag hijacking (`actions/checkout`, `actions/setup-python`, `astral-sh/setup-uv`, `actions/github-script`, `codecov/codecov-action`). Version tags are preserved as inline comments.
- Bump `fastmcp` from 3.2.0 to 3.2.4, patching three security issues: FileUpload now validates actual decoded base64 size instead of trusting client-reported size; proxy client no longer forwards inbound HTTP headers to unrelated remote servers; AuthKit auto-binds token audience to resource URL per RFC 8707, closing a token-reuse gap.
- Bump `pytest` from 9.0.2 to 9.0.3, patching CVE-2025-71176 (insecure temporary directory usage).
- Bump `python-multipart` from 0.0.26 to 0.0.27, patching CVE-2026-42561; added explicit lower-bound constraint to prevent silent regression to vulnerable versions.

### CI
- Bump `astral-sh/setup-uv` from v4 to v7 (node24, faster version resolution for `>=` specifiers)
- Bump `actions/github-script` from v8 to v9
- Bump `codecov/codecov-action` from v5 to v6

### Added
- **`get_redmine_attachment`**: unified attachment retrieval tool that works in both HTTP and stdio deployments
  - Downloads the attachment to local disk and returns an HTTP URI (`uri_type: "http"`) when `PUBLIC_HOST` (or `SERVER_HOST`) resolves to an external hostname, or an absolute local `file_path` (`uri_type: "file"`) in stdio mode -- the model does not need to know which mode is active
  - Streaming download with configurable byte-cap abort (`ATTACHMENT_MAX_DOWNLOAD_BYTES`, default 200 MB); partial files are deleted on abort
  - Atomic temp-file rename pattern (`{filename}.tmp` -> final) consistent with existing file tools
  - All stored files go through the existing `AttachmentFileManager` expiry and cleanup cycle
  - `filename` in the response is wrapped in `<insecure-content>` boundary tags (attacker-controlled)
  - Path traversal protection: filename sanitized to basename before writing to disk
  - Host resolution follows the same fallback chain as the existing tool: `PUBLIC_HOST` -> `SERVER_HOST` -> `localhost`; port resolved via `PUBLIC_PORT` -> `SERVER_PORT` -> `8000`
- **`ATTACHMENT_MAX_DOWNLOAD_BYTES`** environment variable (default `209715200`, 200 MB): cap applied to all `get_redmine_attachment` downloads regardless of content type
- **`_get_int_env(var, default)`** helper in `_env.py` for numeric environment variables (all existing helpers are boolean `_is_*` functions)
- **10 new unit tests** covering HTTP mode, stdio mode, `SERVER_HOST` fallback, absolute `file_path`, filename injection wrapping, byte-cap abort, metadata.json cleanup registration, path traversal sanitization, cap-abort leaving no partial files, and 404 error handling

### Removed
- **`get_redmine_attachment_download_url`**: removed in this major version. Use `get_redmine_attachment` instead, which works in both HTTP and stdio deployments.

### Changed
- Consolidated 35 MCP tools into 9 `manage_X` tools, reducing total tool count from 69 to 43:
  - `add_project_member`, `update_project_member`, `remove_project_member` -> `manage_project_member(action=...)`
  - `list_issue_categories`, `create_issue_category`, `update_issue_category`, `delete_issue_category` -> `manage_issue_category(action=...)`
  - `list_issue_relations`, `create_issue_relation`, `delete_issue_relation` -> `manage_issue_relation(action=...)`
  - `add_watcher`, `remove_watcher` -> `manage_issue_watcher(action=...)`
  - `edit_note`, `set_note_private` -> `manage_issue_note(action=...)` (`get_private_notes` kept standalone)
  - `create_time_entry`, `update_time_entry`, `log_time_for_user` -> `manage_time_entry(action=...)`
  - `get_redmine_wiki_page`, `create_redmine_wiki_page`, `update_redmine_wiki_page`, `delete_redmine_wiki_page`, `list_wiki_pages`, `rename_wiki_page` -> `manage_redmine_wiki_page(action=...)`
  - `list_products`, `get_product`, `add_product`, `edit_product` -> `manage_product(action=...)` (still gated by `REDMINE_PRODUCTS_ENABLED=true`)
  - `list_contacts`, `get_contact`, `create_contact`, `edit_contact`, `delete_contact`, `assign_contact_to_project`, `remove_contact_from_project` -> `manage_contact(action=...)` (still gated by `REDMINE_CRM_ENABLED=true`)
  - `mark_checklist_done` removed: use `update_checklist_item(is_done=True)` directly
- `manage_time_entry(action="create", user_id=...)` replaces `log_time_for_user`
- Verb normalization: `add_product` / `edit_product` map to `manage_product(action="create"|"update")`; `create_contact` / `edit_contact` map to `manage_contact(action="create"|"update")` to match the dominant CRUD pattern in the codebase
- Response shape change: callers of `mark_checklist_done` previously received `{"is_done": bool}`; the equivalent `update_checklist_item` call returns `{"updated_fields": ["is_done"]}`
- Read-only mode: write actions within `manage_X` tools are blocked; read actions (`list`, `get`) remain available
- Refactored `redmine_handler.py` (6591 lines) into a `tools/` package and focused private modules. The 43 MCP tools now live in 11 per-resource files under `src/redmine_mcp_server/tools/`, with shared helpers in flat `_X.py` modules (`_client.py`, `_errors.py`, `_validation.py`, `_serialization.py`, `_env.py`, `_custom_fields.py`, `_ssrf.py`, `_cleanup.py`, `_http_routes.py`). Public MCP surface is unchanged (same 43 tools, parameters, return shapes, read-only behavior). **Breaking for any consumer importing from internal paths**: external code using `from redmine_mcp_server.redmine_handler import ...` must migrate to the new module paths (e.g., `from redmine_mcp_server.tools.projects import manage_project_member`, `from redmine_mcp_server._validation import _is_positive_int`). The `redmine_handler` module is removed in v2.0.0.
- Codified the `manage_X(action=...)` pattern via a new `@action_dispatch` decorator in `_decorators.py`. The 9 `manage_X` tools (plus `manage_redmine_version`) now declare their action set as `{action: ActionMode.READ|WRITE}` and the decorator handles validation, read-only guards, and cleanup-task initialization. Future `manage_X` tools should use this decorator for consistency.

### Contributors
- @mihajlovicjj: added `manage_document` tool for DMSF (Document Management System for Files) plugin support, with 31 new tests covering list/get/create/update across feature-flag gating, dispatch routing, two-step upload, byte-cap enforcement, and validation paths ([#104](https://github.com/jztan/redmine-mcp-server/pull/104))

## [1.3.0] - 2026-05-06
### Added
- **Wiki management (2 new tools, no plugin required):**
  - `list_wiki_pages` — list every wiki page in a project (titles, versions, parents, timestamps)
  - `rename_wiki_page` — rename/move a wiki page with optional redirect (`PUT /projects/{id}/wiki/{old}.json` with `title` parameter); detects silent permission failures by re-fetching the page after the rename
- `REDMINE_PRODUCTS_ENABLED=true` opt-in support for RedmineUP Products plugin:
  - `list_products` — list products, optionally filtered by project
  - `get_product` — retrieve a single product by ID
  - `add_product` — create a new product (name + status_id required; supports description, price, currency, code, project_id, category_id, tag_list, custom_fields)
  - `edit_product` — update product fields (whitelist filter on writable fields)
- **Gantt chart (1 new tool, no plugin required):**
  - `get_gantt_chart` — composite tool that aggregates issues + versions + relations into a structured Gantt response (start/due dates, progress, parent_id, precedes/blocks dependencies, milestones); supports date-range filters and `include_closed` flag
- `REDMINE_CRM_ENABLED=true` opt-in support for RedmineUP CRM plugin:
  - `list_contacts` — list contacts with project/search/tags/assignee filters
  - `get_contact` — retrieve a single contact (with optional `include=notes,deals,contacts`)
  - `edit_contact` — update contact fields (whitelist filter)
  - `create_contact` — create a new contact in a project (with first_name, last_name, company, email, phone, visibility, etc.)
  - `delete_contact` — delete a contact entirely
  - `assign_contact_to_project` — add an existing contact to an additional project
  - `remove_contact_from_project` — remove a contact from a project (without deleting it)
- **`manage_redmine_version`**: single MCP tool for full version lifecycle management (create, update, delete) via an `action` parameter
  - `action="create"`: create a version in a project with optional `description`, `status`, `due_date`, `sharing`, `wiki_page_title`; defaults to `status="open"` and `sharing="none"`
  - `action="update"`: update any subset of fields on an existing version by `version_id`
  - `action="delete"`: delete a version by `version_id`
  - Validates `action` and `status` values client-side with actionable error messages
  - Respects `REDMINE_MCP_READ_ONLY` mode
  - **21 new unit tests** covering all three actions, defaults enforcement, meta-param exclusion, read-only mode, and API error paths
- `REDMINE_CHECKLISTS_ENABLED=true` opt-in support for RedmineUP Checklists Pro plugin:
  - **`get_checklist`**: retrieve all checklist items for an issue (id, subject, is_done, position, timestamps)
  - **`update_checklist_item`**: update a checklist item's text, done state, or position
  - **`mark_checklist_done`**: convenience tool to toggle done/undone state of a checklist item
- `REDMINE_AGILE_ENABLED=true` opt-in support for RedmineUP Agile plugin: `get_redmine_issue` auto-includes `story_points`, `agile_sprint_id`, and `agile_position`; `update_redmine_issue` accepts `story_points` in the `fields` dict
- **14 new MCP tools for Issue Tracking:**
  - **Copying and hierarchy:**
    - `copy_issue` — duplicate an existing issue via Redmine's native `copy_from` mechanism, with optional field overrides and support for copying subtasks/attachments
    - `list_subtasks` — list child issues of a given parent (subtasks are created via existing `create_redmine_issue` with `parent_issue_id`)
  - **Issue relations (blocks, duplicates, precedes, etc.):**
    - `list_issue_relations` — list all relations for an issue
    - `create_issue_relation` — create a relation between two issues; validates `relation_type` against Redmine's taxonomy
    - `delete_issue_relation` — delete a relation by ID
  - **Watchers:**
    - `add_watcher` — add a user to an issue's watcher list (Redmine 2.3.0+)
    - `remove_watcher` — remove a user from an issue's watcher list
  - **Journal/note management:**
    - `edit_note` — update an existing journal note's text and/or `private_notes` flag via `PUT /journals/{id}.json`
    - `get_private_notes` — retrieve only the private notes on an issue (requires "View private notes" permission)
    - `set_note_private` — toggle the private/public state of an existing journal note
  - **Issue categories:**
    - `list_issue_categories` — list all categories for a project
    - `create_issue_category` — create a new category (optionally with a default assignee)
    - `update_issue_category` — rename a category or change its default assignee
    - `delete_issue_category` — delete a category with optional `reassign_to_id` to move existing issues
- **55 new unit tests** covering all new tools (read-only mode enforcement, success paths, error paths, helper conversions)
- **5 new MCP tools for Projects:**
  - `list_redmine_roles` — list all roles defined in the Redmine instance; use before `add_project_member`/`update_project_member` to discover valid `role_ids` (role IDs vary between Redmine instances)
  - `get_project_modules` — retrieve enabled modules for a project via `?include=enabled_modules`
  - `add_project_member` — add a user or group to a project with assigned roles; validates that exactly one of `user_id` or `group_id` is provided
  - `update_project_member` — update the roles of an existing membership
  - `remove_project_member` — remove a membership (inherited memberships from parent projects surface as a 422 validation error)
- `role_ids` validation errors in `add_project_member` / `update_project_member` now hint at `list_redmine_roles` to prevent AI agents from hallucinating role IDs
- **33 new unit tests** for project tools covering modules retrieval (including dict-format fallback for older Redmine versions), role discovery, membership CRUD, validation errors, read-only mode enforcement, error paths, and error-message discoverability hints
- **2 new MCP tools for Time Tracking:**
  - `log_time_for_user` — create a time entry on behalf of another user via the `user_id` parameter on `POST /time_entries.json`; requires `log_time_for_other_users` permission on the target project
  - `import_time_entries` — bulk import multiple time entries via sequential API calls (Redmine has no native bulk endpoint); accepts a list of dicts or JSON array string, captures per-entry errors, and returns `{total, succeeded, failed, created, errors}` so partial imports still yield useful feedback; supports `stop_on_error` flag
- Add missing `REDMINE_MCP_READ_ONLY` enforcement to existing `create_time_entry` tool
- **23 new unit tests** for time tracking tools covering success paths, per-entry validation (missing hours, negative hours, missing target), JSON string input, partial failure handling, `stop_on_error`, field whitelisting, read-only mode, and Redmine-version permission quirks
- **3 new MCP tools for Files:**
  - `list_files` — list files uploaded to a project's Files section (core Redmine "Files" module, distinct from issue attachments and DMSF documents); returns filename, filesize, content type, description, download URL, author, optional version/release
  - `upload_file` — upload a new file via Redmine's two-step upload (`POST /uploads.json` for token, then `POST /projects/{id}/files.json`). Accepts either `source_url` (HTTP/HTTPS URL the server downloads from) or `content_base64` (raw bytes encoded as base64); the URL path enables chaining with other MCP tools that return download URLs (e.g., Google Drive MCP). Streaming download with 30s timeout, follows redirects, infers filename from URL path or `Content-Disposition` header. 50 MiB size cap
  - `delete_file` — delete a project file via `DELETE /attachments/{id}.json`
- **36 new unit tests** for file tools covering base64 encoding/decoding, URL-based download (success, invalid schemes, HTTP errors, timeouts, empty body, Content-Disposition filename fallback), size limits, read-only mode, missing/conflicting content sources, and Redmine error paths
- **6 new MCP Discovery / Enumeration tools** to help LLMs find valid IDs without guessing:
  - `list_redmine_trackers` — list all trackers (issue types like Bug, Feature, Support) for discovering valid `tracker_id` values
  - `list_redmine_issue_statuses` — list all issue statuses with their `is_closed` flag for discovering valid `status_id` values
  - `list_redmine_issue_priorities` — list all priority levels via `enumeration.filter(resource="issue_priorities")`
  - `list_redmine_users` — filter/list users with optional `name` and `group_id` filters (admin-only, limit clamped to 1-100)
  - `get_current_user` — retrieve the authenticated user's profile via `GET /my/account.json` (works for non-admins; useful when a user says "do X for me")
  - `list_redmine_queries` — list all saved custom queries visible to the current user (read-only; Redmine's API does not support CRUD on queries)
- **20 new unit tests** for discovery tools covering success paths, empty results, limit clamping, filter parameters, and permission-denied error paths

### Security
- **SSRF protection for `upload_file(source_url=...)`:** The server now resolves every URL hop and rejects non-public destinations (loopback, RFC1918, link-local including cloud metadata services like `169.254.169.254`, reserved, multicast). Redirects are followed manually with per-hop revalidation to defeat public-to-private 302 bypasses. Capped at 5 redirect hops. URLs with embedded credentials (`http://user:pass@host`) are refused up front to prevent credential leakage across redirects. SSRF error messages no longer include the resolved IP (logged at WARNING level instead) to avoid leaking internal network topology. Opt-in dev override: `REDMINE_ALLOW_PRIVATE_FETCH_URLS=true`. (Note: DNS rebinding between our check and httpx's connect is a theoretical residual risk; IP pinning was evaluated but broke TLS SNI for real CDNs.)
- **`delete_file` is now fail-closed on ambiguous `container_type`:** Previously, if Redmine (or an older python-redmine version) returned `None` or an empty string for `container_type`, the project-scope guard was skipped and the attachment was deleted. Now any non-`"Project"` value refuses the delete, with an explicit `confirm_delete_any_attachment=True` flag for bypass.
- **Int-ID validators reject booleans and non-positive values:** Python treats `True`/`False` as `int`, so `role_ids=[True]` would silently assign role ID 1 (often an elevated role). New `_is_positive_int` helper is applied to `role_ids`, `user_id`, and `group_id` parameters in `add_project_member`, `update_project_member`, `add_watcher`, `remove_watcher`, and `log_time_for_user`.
- **Attacker-controlled display names wrapped:** New `_named_ref()` helper wraps `user.name`, `author.name`, and `version.name` fields (all user-controlled) in `<insecure-content>` boundary tags. Applied via `_named_ref` to `_file_to_dict` and `_attachments_to_list` (previously, attachment filenames/descriptions were only wrapped in the new `list_files` output but NOT in `get_redmine_issue(include_attachments=True)` -- now consistent across both).
- **Prompt-injection hardening:** `filename`, `description`, and time-entry `comments` returned from `list_files`/`upload_file`/`log_time_for_user`/`import_time_entries` are now wrapped in `<insecure-content>` boundary tags (matching existing issue/journal/description handling). Prevents attacker-controllable Redmine metadata from being treated as trusted instructions by downstream LLMs.
- **Error-message secret scrubbing:** `_handle_redmine_error` now redacts API keys (`?key=`, `X-Redmine-API-Key`), Bearer tokens, HTTP basic-auth credentials, and the configured `REDMINE_API_KEY` before returning errors to MCP callers. Logs still see the raw message.
- **Content-Disposition filename sanitization:** URL-inferred and header-derived filenames are URL-decoded, stripped of path components (defeats `../../../etc/passwd` traversal on both POSIX and Windows), rejected if they contain null bytes or control characters, and capped at 255 chars.
- **`delete_file` container-type check:** Since Redmine's `DELETE /attachments/{id}.json` removes any attachment by ID (including issue/wiki attachments), `delete_file` now verifies the target is a project file before deleting. Callers can bypass with `confirm_delete_any_attachment=True`.
- Bump `cryptography` from 46.0.6 to 46.0.7, patching CVE-2026-39892 (out-of-bounds read via non-contiguous buffers)

### Fixed
- **`_is_valid_project_id` URL-path safety:** Restricts string identifiers to Redmine's documented charset (`^[a-z0-9][a-z0-9_-]{0,99}$`), rejecting `/`, `?`, `#`, `..`, whitespace, and uppercase before they can be interpolated into URL paths in the new Wiki/Products/CRM tools.
- **`add_product` `status_id` constraint:** Now rejects values other than `1` (Active) or `2` (Inactive) instead of forwarding arbitrary positive integers to the API.
- **`copy_issue` data-integrity bug:** When both `copy_subtasks=False` and `copy_attachments=False` were passed, python-redmine's `include or (...)` fallback silently copied both anyway. Now passes a non-empty sentinel so the fallback does not trigger.
- **`log_time_for_user` / `import_time_entries` hours validation:** Now rejects NaN, Infinity, booleans (which Python treats as `int`), and non-numeric types before hitting the API.
- **`import_time_entries` bulk safeguards:** Added a 500-entry batch cap (returns a clear error instead of pinning the event loop for minutes on a massive request). Yields the event loop between entries via `asyncio.sleep(0)` so concurrent MCP requests are not starved. Split the create/serialize try blocks so a post-create serialization failure does not flip a successful create into a reported failure (which would tempt callers to retry and create duplicates).

### Changed
- **`get_gantt_chart` default `include_closed` is now `False`.** Pass `include_closed=True` to retain prior behavior. Keeps response size and pagination cost low on long-lived projects.
- **List tools now return `Union[List, Dict]` on error** instead of `[{"error": "..."}]`. Affects `list_issue_relations`, `list_subtasks`, `list_issue_categories`, `list_files`, `list_redmine_roles`, `list_redmine_trackers`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`, `list_redmine_users`, `list_redmine_queries`. Callers should check `isinstance(result, dict)` or `"error" in result` to distinguish failure from an empty list. Matches the pre-existing convention of `list_time_entries`, `list_redmine_issues`, and `search_redmine_issues`.
- **List tools now cap results at 500 items** (configurable via `_DEFAULT_LIST_RESULT_CAP` constant) via the new `_iter_capped` helper. Previously unbounded iteration could OOM on projects with tens of thousands of subtasks/relations/files.
- **Module-level constants consolidated:** `_FILE_UPLOAD_MAX_SIZE_BYTES`, `_MAX_FILENAME_LEN`, `_IMPORT_TIME_ENTRIES_MAX_BATCH`, `_DEFAULT_LIST_RESULT_CAP`, `_DOWNLOAD_TIMEOUT`, and `_FILE_DOWNLOAD_MAX_REDIRECTS` are all declared once at the top of the module instead of scattered across different sections. Top-level `import httpx` and `from urllib.parse import unquote, urlparse` hoisted out of function-local imports.

### CI
- Fix `pip-audit` failing on packages not published to PyPI by adding `--no-emit-project` to `uv export` in `dependency-audit.yml`

### Contributors
- @mihajlovicjj — 30 new MCP tools, security hardening, and 82+ new tests ([#89](https://github.com/jztan/redmine-mcp-server/pull/89))
- @mihajlovicjj: 14 new MCP tools (Wiki, Products, Gantt, Contacts), security hardening, and 86 new tests ([#98](https://github.com/jztan/redmine-mcp-server/pull/98))

## [1.2.2] - 2026-04-25
### Changed
- `list_time_entry_activities` now accepts an optional `project_id` parameter to return project-specific activity IDs (fixes `"Activity is not included in the list"` errors when creating time entries for projects with custom activities)
- `scripts/release.py` now supports `--hotfix` flag to finish a `hotfix/*` branch: bumps patch version, merges to `master` (tagged), merges back to `develop`, and deletes the hotfix branch
- `scripts/release.py` `merge_back_to_develop` now detects merge conflicts and exits with actionable instructions (resolve conflicts, stage files, commit, delete branch) instead of crashing with an unhandled error

## [1.2.0] - 2026-04-14
### Added
- `REDMINE_AGILE_ENABLED=true` opt-in support for RedmineUP Agile plugin: `get_redmine_issue` auto-includes `story_points`, `agile_sprint_id`, and `agile_position`; `update_redmine_issue` accepts `story_points` in the `fields` dict

### Security
- Bump `fastmcp` from 3.1.1 to 3.2.0, patching CVE-2025-64340 and CVE-2026-27124

### CI
- Fix `pip-audit` failing on packages not published to PyPI by adding `--no-emit-project` to `uv export` in `dependency-audit.yml`

## [1.1.2] - 2026-04-08
### Fixed
- Fix `AttributeError: 'str' object has no attribute 'isoformat'` crash when Redmine server returns date fields as pre-formatted strings instead of datetime objects (affects non-UTC timezone configurations and certain Redmine versions)

### Tests
- Expand `test_safe_isoformat.py` with coverage for `_issue_to_dict_selective` and `list_redmine_projects` -- the two paths omitted from the original PR

### Contributors
- @mihajlovicjj -- reported and fixed the `isoformat` crash on non-UTC Redmine configurations ([#82](https://github.com/jztan/redmine-mcp-server/pull/82))

## [1.1.1] - 2026-03-31
### Security
- Patch 14 CVEs across 7 transitive dependencies: pyjwt 2.12.1 (CVE-2026-32597), cryptography 46.0.6 (CVE-2026-26007, CVE-2026-34073), starlette 1.0.0 / fastapi 0.135.2 (CVE-2025-54121, CVE-2025-62727), urllib3 2.6.3 (CVE-2025-50181/82, CVE-2025-66418/71, CVE-2026-21441), requests 2.33.1 (CVE-2024-47081, CVE-2026-25645), python-multipart 0.0.22 (CVE-2026-24486), pygments 2.20.0 (CVE-2026-4539)

### CI
- Add `dependency-audit.yml` workflow: lockfile integrity check (`uv lock --check`), CVE scanning via `pip-audit`, and PR step summary flagging lockfile changes for supply-chain review
- Pin upper bounds on all runtime and dev dependencies in `pyproject.toml` to prevent unexpected major-version upgrades
- Upgrade CI workflows to `actions/checkout@v6` and `actions/setup-python@v6`
- Replace manual venv activation with `astral-sh/setup-uv@v4` and `uv sync --locked` for reproducible installs
- Use `uv run` for all tool invocations (`flake8`, `black`, `pytest`) instead of sourcing `.venv`

## [1.1.0] - 2026-03-21
### Fixed
- Version and auth mode are now logged at module import time, ensuring they appear in Docker deployments where the server is started via `uvicorn main:app` directly (bypassing `main()`)
- Pass `log_config=None` to `uvicorn.run()` to preserve the configured logging format in local deployments

### Changed
- Migrated from `mcp[cli]>=1.25.0,<2` to `fastmcp>=3.0.0,<4` (standalone FastMCP v3 package)

### Dependencies
- Bump `uvicorn` from 0.40.0 to 0.42.0
- Bump `black` from 26.1.0 to 26.3.1
- Bump `python-dotenv` from 1.2.1 to 1.2.2
- Updated import from `mcp.server.fastmcp` to `fastmcp`
- Replaced `mcp.streamable_http_app()` with `mcp.http_app(stateless_http=True)` (v3 API)
- Removed `mcp.settings.stateless_http` runtime mutation (`stateless_http` is now passed to `http_app()`)
- Removed `host=` parameter from `FastMCP()` constructor (not a valid v3 parameter; DNS rebinding protection removed from FastMCP v3 entirely -- no behaviour change for Docker deployments)
- Converted `list_redmine_issues` and `search_redmine_issues` from `**kwargs` to explicit parameters (FastMCP v3 no longer supports `**kwargs` tool functions); additional arbitrary filters still available via `filters={}` / `options={}` dict parameters

## [1.0.0] - 2026-03-14
### Added
- **New MCP Tool: `list_project_members`** - List members and groups of a Redmine project
  - Returns user/group info along with assigned roles
  - Supports both numeric project IDs and string identifiers
- **New MCP Tools: Time Tracking** - Full time entry management
  - `list_time_entries` - List time entries with filtering by project, issue, user, and date range
  - `create_time_entry` - Log time against projects or issues with activity and date support
  - `update_time_entry` - Modify existing time entries (hours, comments, activity, date)
  - `list_time_entry_activities` - Discover available activity types (Development, Design, etc.) for time entry creation
  - All tools support pagination and use `_get_redmine_client()` for OAuth compatibility
- **50 new unit tests** for project members and time tracking tools (`test_project_members.py`, `test_time_entries.py`)
- **26 new integration tests** covering all 21 MCP tools with zero skips -- includes project members (4), time entries (7), custom fields (3), search issues (3), summarize project (3), global search (4), and cleanup (2)
- **OAuth2 per-user authentication mode** (`REDMINE_AUTH_MODE=oauth`)
  - New `oauth_middleware.py`: Starlette middleware that validates `Authorization: Bearer <token>` headers against Redmine's `/users/current.json` before forwarding MCP requests
  - Per-request token isolation via `contextvars.ContextVar` -- safe under async concurrent load
  - `GET /.well-known/oauth-protected-resource` endpoint (RFC 8707) -- points MCP clients to the authorization server
  - `GET /.well-known/oauth-authorization-server` endpoint (RFC 8414) -- advertises Redmine's Doorkeeper OAuth endpoints (`/oauth/authorize`, `/oauth/token`, `/oauth/revoke`) since Redmine does not serve this document itself
  - `POST /revoke` endpoint (RFC 7009) -- proxies token revocation to Redmine's `/oauth/revoke`, enabling proper disconnect flow from MCP clients
  - PKCE (`S256`) and both `client_secret_post` / `client_secret_basic` token endpoint auth methods advertised
  - Requires Redmine 6.1+ (Doorkeeper OAuth2 support)
- **`REDMINE_AUTH_MODE` environment variable** -- selects `legacy` (default) or `oauth` mode; legacy mode is unchanged so existing deployments require no changes
- **`REDMINE_MCP_BASE_URL` environment variable** -- public base URL of this server, used in OAuth discovery documents (only required in oauth mode)
- **`_get_redmine_client()` factory function** in `redmine_handler.py` -- creates a per-request Redmine client using OAuth token -> API key -> username/password priority; replaces the module-level shared client
- **33 new unit tests** for OAuth middleware, discovery endpoints, token revocation, and auth selection logic (`tests/test_oauth_middleware.py`)
- **Prompt Injection Protection** - User-controlled content from Redmine is now wrapped in unique boundary tags to prevent prompt injection attacks against LLM consumers
  - New `wrap_insecure_content()` function wraps non-empty strings in `<insecure-content-{boundary}>` tags with a random 16-character hex boundary per call
  - Applied to 6 helper functions: `_issue_to_dict` (description), `_issue_to_dict_selective` (description), `_journals_to_list` (notes), `_resource_to_dict` (excerpt), `_wiki_page_to_dict` (text), `_version_to_dict` (description)
  - 22 new tests in `test_prompt_injection.py`
- **Read-Only Mode** - Block all write operations via `REDMINE_MCP_READ_ONLY=true` environment variable
  - Guards 5 write tools: `create_redmine_issue`, `update_redmine_issue`, `create_redmine_wiki_page`, `update_redmine_wiki_page`, `delete_redmine_wiki_page`
  - Read tools (`get_redmine_issue`, `list_redmine_projects`, `list_redmine_issues`, etc.) remain fully functional
  - Local operations (`cleanup_attachment_files`) are not restricted
  - 15 new tests in `test_read_only_mode.py`
  - Updated `.env.example` and `.env.docker` with `REDMINE_MCP_READ_ONLY` variable
- **Journal Pagination on `get_redmine_issue`** - New `journal_limit` and `journal_offset` parameters for paginating through issue journals
  - When `journal_limit` is set, response includes `journal_pagination` metadata (`total`, `offset`, `limit`, `count`, `has_more`)
  - Default behavior unchanged (returns all journals without pagination metadata)
  - 9 new tests covering limit, offset, combined pagination, edge cases, and backward compatibility
- **Include Flags on `get_redmine_issue`** - Three new boolean parameters for fetching additional issue data
  - `include_watchers` (default: `false`) - Returns watcher list with `id` and `name`
  - `include_relations` (default: `false`) - Returns issue relations with `id`, `issue_id`, `issue_to_id`, `relation_type`
  - `include_children` (default: `false`) - Returns child issues with `id`, `subject`, `tracker`
  - All flags default to `false` for backward compatibility
  - Include parameters are passed to the Redmine API for server-side inclusion
  - 11 new tests covering all flags, combinations, missing attributes, and structure validation

### Breaking
- **Removed `list_my_redmine_issues`** - Deprecated since v0.11.0. Use `list_redmine_issues(assigned_to_id='me')` instead.
  - All references in docstrings updated to point to `list_redmine_issues()`

### Fixed
- **Custom routes (well-known endpoints) not served at runtime** -- `mcp.run()` created a fresh internal app discarding route registrations; switched to `uvicorn.run(app, ...)` so the decorated app instance is always what serves requests
- **`REDMINE_URL` KeyError at import time** -- `oauth_middleware.py` now uses `os.environ.get()` instead of `os.environ[]`, so the server starts cleanly even if `REDMINE_URL` is not set before import
- **Legacy client recreated on every tool call** -- `_get_redmine_client()` now caches a singleton `_legacy_client` in legacy mode instead of building a new `Redmine()` instance per request
- **OAuth routes exposed in legacy mode** -- well-known endpoints and `/revoke` are now only registered when `REDMINE_AUTH_MODE=oauth`

### Changed
- `main()` now runs via `uvicorn.run(app, ...)` directly instead of `mcp.run(transport="streamable-http")` to ensure custom route registrations are preserved

### Improved
- **Code Quality** - Added `.flake8` config for Black compatibility (E203 ignore)

### Contributors
- @mihajlovicjj -- OAuth2 per-user authentication, `/revoke` endpoint, discovery endpoints, and 33 new tests ([#71](https://github.com/jztan/redmine-mcp-server/pull/71))
- @mihajlovicjj -- Project members and time tracking tools with 50 new tests ([#72](https://github.com/jztan/redmine-mcp-server/pull/72))

## [0.12.1] - 2026-03-05

### Fixed
- **421 Misdirected Request in Docker/public deployments** ([#69](https://github.com/jztan/redmine-mcp-server/issues/69))
  - Pass `SERVER_HOST` to FastMCP so DNS rebinding protection is configured correctly
  - When host is `0.0.0.0` (Docker/public), FastMCP skips auto-enabling DNS rebinding protection, avoiding 421 errors for connections via public IPs

## [0.12.0] - 2026-02-19

### Added
- **New MCP Tool: `list_project_issue_custom_fields`** - Discover issue custom fields for a Redmine project
  - Lists custom field metadata (`id`, `name`, `field_format`, `is_required`, `multiple`, `default_value`)
  - Includes allowed values (`possible_values`) and tracker bindings (`trackers`)
  - Optional `tracker_id` filter to show only fields applicable to a specific tracker
  - 7 unit tests covering serialization, filtering, validation, and error handling
- **New MCP Tool: `list_redmine_versions`** - List versions/milestones for a Redmine project
  - Filter by `project_id` (numeric or string identifier)
  - Optional `status_filter` parameter (open, locked, closed)
  - Client-side filtering with input validation
  - 18 unit tests covering helper, basic functionality, filtering, and error handling
  - 6 integration tests for project ID, string identifier, structure, filtering, and error handling
- **`fixed_version_id` filter** documented for `list_redmine_issues` tool
- **Claude Desktop MCP client configuration** added to README with stdio transport via FastMCP proxy
- `get_redmine_issue` now supports `include_custom_fields` (default: `true`) and can return serialized issue `custom_fields`.
- `update_redmine_issue` now supports updating custom fields by name (for example `{"size": "S"}`) by resolving project custom-field metadata.

### Fixed
- **Required custom field handling** for `create_redmine_issue` and `update_redmine_issue` ([#65](https://github.com/jztan/redmine-mcp-server/issues/65))
  - Auto-retry on validation errors for missing required custom fields (e.g., "cannot be blank", "is not included in the list")
  - Fills values from Redmine custom field `default_value` or `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` env var
  - Opt-in via `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true` environment variable
  - `create_redmine_issue` now accepts `fields` as a JSON object string for flexible custom field payloads
  - Added `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` env var for specifying fallback values per field name
  - Updated `.env.example` and `.env.docker` with new environment variables

### Breaking
- **`create_redmine_issue` `extra_fields` parameter** -- Previously, passing `extra_fields` as a plain string would forward it directly to Redmine as an attribute. Now it is parsed as a JSON object (or dict) and merged into the issue payload. Callers who relied on the old behaviour of sending a raw `extra_fields` string attribute should migrate to `fields` or provide a JSON object string instead.

### Changed
- **Dependency Updates**
  - `black` upgraded from 25.12.0 to 26.1.0
- Improved issue update validation for named custom fields with clear errors when values are not allowed for the target custom field.

### Contributors
- @sebastianelsner -- custom field discovery tool, required custom field handling, and custom field update support ([#65](https://github.com/jztan/redmine-mcp-server/pull/65), [#66](https://github.com/jztan/redmine-mcp-server/pull/66))

### Improved
- **Test Coverage** - 44 new unit tests for custom field helper functions (`redmine_handler.py` lines 474-640)
  - Covers `_is_true_env`, `_normalize_field_label`, `_parse_create_issue_fields`, `_extract_possible_values`, `_extract_missing_required_field_names`, `_load_required_custom_field_defaults`, `_is_missing_custom_field_value`, `_is_allowed_custom_field_value`, `_resolve_required_custom_field_value`
  - `redmine_handler.py` coverage improved from 94% to 97% (with integration tests)
  - Overall coverage improved from 95% to 98%
- **Documentation** - Updated README and tool-reference.md
  - Tool count updated from 15 to 17
  - Added `list_project_issue_custom_fields` to Project Management category in README
  - Added full `list_project_issue_custom_fields` documentation to tool-reference.md
  - Added `list_redmine_versions` to Project Management category in README
  - Added full tool documentation to tool-reference.md with parameters, examples, and usage guidance
  - Documented `fixed_version_id` parameter for `list_redmine_issues`

## [0.11.0] - 2026-02-14

### Added
- **New MCP Tool: `list_redmine_issues`** - General-purpose issue listing with flexible filtering ([#64](https://github.com/jztan/redmine-mcp-server/issues/64))
  - Filter by `project_id`, `status_id`, `tracker_id`, `assigned_to_id`, `priority_id`, `sort`
  - `assigned_to_id` supports numeric user IDs or `'me'` for the authenticated user
  - `fields` parameter for selective field returns to reduce token usage
  - Full pagination support with `limit`, `offset`, and `include_pagination_info`
  - Supports string project identifiers (e.g., `"my-project"`) in addition to numeric IDs
- **Comprehensive Test Suite** - 34 unit tests and 15 integration tests for the new tool
  - Covers filters, pagination, field selection, combined filters, error handling, and MCP parameter unwrapping
  - Integration tests verify real Redmine API behavior including sort order and field selection

### Changed
- **`list_my_redmine_issues` refactored** as a thin wrapper around `list_redmine_issues(assigned_to_id='me')`
  - Full backward compatibility maintained
  - All existing calls continue to work unchanged

### Deprecated
- **`list_my_redmine_issues`** - Will be removed in a future release
  - Use `list_redmine_issues(assigned_to_id='me')` instead
  - Wrapper delegates all parameters to `list_redmine_issues`

### Improved
- **Documentation** - Updated README and tool-reference.md
  - Tool count updated from 14 to 15
  - Tool reference now the single source of truth for tool documentation

## [0.10.0] - 2026-01-11

### Added
- **Wiki Page Editing** - Three new MCP tools for full wiki page lifecycle management
  - `create_redmine_wiki_page(project_id, wiki_page_title, text, comments)` - Create new wiki pages
  - `update_redmine_wiki_page(project_id, wiki_page_title, text, comments)` - Update existing wiki pages
  - `delete_redmine_wiki_page(project_id, wiki_page_title)` - Delete wiki pages
  - Includes change log comment support for create/update operations
  - 17 new tests with comprehensive error handling coverage
- **Centralized Error Handler** - New `_handle_redmine_error()` function for consistent, actionable error messages
  - Handles 12 error types: SSL, connection, timeout, auth, forbidden, server error, validation, version mismatch, protocol, not found, and more
  - Error messages include specific error types, actionable guidance, and relevant context (URLs, resource IDs, environment variables)
  - All 10 MCP tools updated to use centralized error handling
  - 21 new tests added for comprehensive error handling coverage

### Changed
- **Logging Improvements** - Replaced remaining `print()` statements with proper `logger` calls throughout codebase

### Improved
- **Code Coverage Target** - Increased Codecov target from 70% to 80%
- **Test Coverage** - Improved `redmine_handler.py` coverage from 93% to 99%
  - Added 29 new tests covering edge cases and error handling paths
  - Total test count increased from 302 to 331
  - Only 5 module initialization lines remain uncovered (import-time code)
- **Documentation** - Added MCP architecture lessons blog post to README resources section

## [0.9.1] - 2026-01-04

### Removed
- **BREAKING**: Removed deprecated `download_redmine_attachment()` function
  - Was deprecated in v0.4.0 with security advisory (CWE-22, CVSS 7.5)
  - Use `get_redmine_attachment_download_url()` instead for secure attachment downloads

### Changed
- **Dependency Updates**
  - `mcp[cli]` pinned to >=1.25.0,<2 (from >=1.19.0) for latest stable v1.x
  - `uvicorn` upgraded from 0.38.0 to 0.40.0

### Improved
- **Test Coverage** - Improved from 76% to 88% with comprehensive test suite enhancements
- **CI/CD** - Moved coverage upload from PR workflow to publish workflow

## [0.9.0] - 2025-12-21

### Added
- **Global Search Tool** - `search_entire_redmine(query, resources, limit, offset)` for searching across issues and wiki pages
  - Supports resource type filtering (`issues`, `wiki_pages`)
  - Server-side pagination with configurable limit (max 100) and offset
  - Returns categorized results with count breakdown by type
  - Requires Redmine 3.3.0+ for search API support
- **Wiki Page Retrieval** - `get_redmine_wiki_page(project_id, wiki_page_title, version, include_attachments)` for retrieving wiki content
  - Supports both string and integer project identifiers
  - Optional version parameter for retrieving specific page versions
  - Optional attachment metadata inclusion
  - Returns full page content with author and project info
- **Version Logging** - Server now logs version at startup

### Changed
- **Logging Improvements** - Replaced `print()` with `logging` module for consistent log formatting

## [0.8.1] - 2025-12-11

### Added
- **Test Coverage Badge** - Added test coverage tracking via Codecov integration
- **Unit Tests for AttachmentFileManager** - Comprehensive test coverage for file management module

### Changed
- **Dependency Updates** - Updated core and development dependencies to latest versions
  - `python-dotenv` upgraded from 1.1.0 to 1.2.1
  - `pytest-mock` upgraded from 3.14.1 to 3.15.1
  - `pytest-cov` upgraded from 6.2.1 to 7.0.0
  - `pytest` upgraded from 8.4.0 to 9.0.2
  - `uvicorn` upgraded from 0.34.2 to 0.38.0
  - `pytest-asyncio` upgraded from 1.0.0 to 1.3.0
  - `black` upgraded from 25.9.0 to 25.12.0
- **CI/CD Improvements** - Updated GitHub Actions dependencies
  - `actions/checkout` upgraded from 4 to 6
  - `actions/setup-python` upgraded from 5 to 6
  - `actions/github-script` upgraded from 7 to 8

### Improved
- **Issue Management Workflows** - Added GitHub issue templates and automation
  - Bug report and feature request issue templates
  - Stale issue manager workflow for automatic issue cleanup
  - Lock closed issues workflow
  - Auto-close label removal workflow
- **Dependabot Integration** - Configured automated dependency updates for uv, GitHub Actions, and Docker

## [0.8.0] - 2025-12-08

### Security
- **Removed private keys from repository** - Addresses GitGuardian secret exposure alert
  - Test SSL certificates now generated dynamically in CI/CD pipeline
  - Added `generate-test-certs.sh` script for local and CI certificate generation
  - Updated `.gitignore` to exclude all generated certificate files
  - Private keys no longer stored in version control

### Added
- **SSL Certificate Configuration** - Comprehensive SSL/TLS support for secure Redmine connections
  - **Self-Signed Certificates** - `REDMINE_SSL_CERT` environment variable for custom CA certificates
    - Support for `.pem`, `.crt`, `.cer` certificate formats
    - Path validation with existence and file type checks
    - Clear error messages for troubleshooting
  - **Mutual TLS (mTLS)** - `REDMINE_SSL_CLIENT_CERT` environment variable for client certificate authentication
    - Support for separate certificate and key files (comma-separated format)
    - Support for combined certificate files
    - Compatibility with unencrypted private keys (Python requests requirement)
  - **SSL Verification Control** - `REDMINE_SSL_VERIFY` environment variable to enable/disable verification
    - Defaults to `true` for security (secure by default)
    - Warning logs when SSL verification is disabled
    - Development/testing flexibility with explicit configuration
  - **Integration Testing** - 9 comprehensive integration tests with real SSL certificates
    - Test certificate generation using OpenSSL
    - Validation of all SSL configuration scenarios
    - Certificate path resolution and error handling tests

### Changed
- Enhanced Redmine client initialization with SSL configuration support
- Updated environment variable parsing for SSL options
- Improved error handling for SSL certificate validation

### Improved
- **Security** - Secure by default with SSL verification enabled
  - Certificate path validation prevents configuration errors
  - Clear warnings for insecure configurations (SSL disabled)
  - Comprehensive logging for SSL setup and errors
- **Flexibility** - Support for various SSL deployment scenarios
  - Self-signed certificates for internal infrastructure
  - Mutual TLS for high-security environments
  - Docker-compatible certificate mounting
- **Documentation** - Extensive updates across all documentation:
  - **README.md** - New SSL Certificate Configuration section with examples
    - Environment variables table updated with SSL options
    - Collapsible sections for different SSL scenarios
    - Link to troubleshooting guide for SSL issues
  - **docs/troubleshooting.md** - Comprehensive SSL troubleshooting section
    - 8 detailed troubleshooting scenarios with solutions
    - OpenSSL command examples for certificate validation
    - Docker deployment SSL configuration guide
    - Troubleshooting checklist for common issues
  - **docs/tool-reference.md** - New Security Best Practices section
    - SSL/TLS configuration best practices
    - Authentication security guidelines
    - File handling security features
    - Docker deployment security recommendations

### Fixed
- **CI/CD** - Added SSL certificate generation step to PyPI publish workflow
  - Tests were failing in GitHub Actions due to missing test certificates
  - Certificate generation now runs before tests in all CI workflows

## [0.7.1] - 2025-12-02

### Fixed
- **Critical: Redmine client initialization failure when installed via pip** ([#40](https://github.com/jztan/redmine-mcp-server/issues/40))
  - `.env` file is now loaded from the current working directory first, then falls back to package directory
  - Previously, the server only looked for `.env` relative to the installed package location (site-packages), causing "Redmine client not initialized" errors for pip-installed users
  - Added helpful warning messages when `REDMINE_URL` or authentication credentials are missing
  - Removed redundant `load_dotenv()` call from `main.py` to avoid duplicate initialization

### Added
- **Regression Tests** - Added 8 new tests in `test_env_loading.py` to prevent future regressions:
  - Tests for `.env` loading from current working directory
  - Tests for warning messages when configuration is missing
  - Tests for CWD precedence over package directory

### Migration Notes
- **No Breaking Changes** - Existing configurations continue to work
- **Recommended** - Place your `.env` file in the directory where you run the server (current working directory)
- **Fallback** - If no `.env` found in CWD, the package directory is checked as before

## [0.7.0] - 2025-11-29

### Added
- **Search Optimization** - Comprehensive enhancements to `search_redmine_issues()` to prevent MCP token overflow
  - **Pagination Support** - Server-side pagination with `limit` (default: 25, max: 1000) and `offset` parameters
  - **Field Selection** - Optional `fields` parameter for selective field inclusion to reduce token usage
  - **Native Search Filters** - Support for Redmine Search API native filters:
    - `scope` parameter (values: "all", "my_project", "subprojects")
    - `open_issues` parameter for filtering open issues only
  - **Pagination Metadata** - Optional structured response with `include_pagination_info` parameter
  - **Helper Function** - Added `_issue_to_dict_selective()` for efficient field filtering

### Changed
- **Default Behavior** - `search_redmine_issues()` now returns max 25 issues by default (was unlimited)
  - Prevents MCP token overflow (25,000 token limit)
  - Use `limit` parameter to customize page size
  - Fully backward compatible for existing usage patterns

### Improved
- **Performance** - Significant improvements for search operations:
  - Memory efficient: Uses server-side pagination
  - Token efficient: Default limit keeps responses under 2,000 tokens
  - ~95% token reduction possible with minimal field selection
  - ~87% faster response times for large result sets
- **Documentation** - Comprehensive updates:
  - Updated `docs/tool-reference.md` with detailed search parameters and examples
  - Added "When to Use" guidance (search vs list_my_redmine_issues)
  - Documented Search API limitations and filtering capabilities
  - Added performance tips and best practices

## [0.6.0] - 2025-10-25

### Changed
- **Dependency Updates** - Updated core dependencies to latest versions
  - `fastapi[standard]` upgraded from >=0.115.12 to >=0.120.0
  - `mcp[cli]` upgraded from >=1.14.1 to >=1.19.0

### Security
- **MCP Security Fix** - Includes security patch from MCP v1.19.0 (CVE-2025-62518)

### Improved
- **FastAPI Enhancements** - Benefits from latest bug fixes and improvements
- **MCP Protocol Improvements** - Enhanced capabilities from latest updates

## [0.5.2] - 2025-10-09

### Documentation
- **Major README reorganization** - Comprehensive cleanup for professional, user-focused documentation
  - Created separate documentation guides:
    - `docs/tool-reference.md` - Complete tool documentation with examples
    - `docs/troubleshooting.md` - Comprehensive troubleshooting guide
    - `docs/contributing.md` - Complete developer guide with setup, testing, and contribution guidelines
  - Refactored MCP client configurations with collapsible `<details>` sections
  - Removed development-focused content from README (moved to contributing guide)

## [0.5.1] - 2025-10-08

### Documentation
- **Updated MCP client configurations** - Comprehensive update to all MCP client setup instructions
  - VS Code: Added native MCP support with CLI, Command Palette, and manual configuration methods
  - Codex CLI: New section with CLI command and TOML configuration format
  - Kiro: Updated to use mcp-client-http bridge for HTTP transport compatibility
  - Generic clients: Expanded with both HTTP and command-based configuration formats

## [0.5.0] - 2025-09-25

### Added
- **Python 3.10+ support** - Expanded compatibility from Python 3.13+ to Python 3.10+
- CI/CD matrix testing across Python 3.10, 3.11, 3.12, and 3.13 versions

### Changed
- **BREAKING**: Minimum Python requirement lowered from 3.13+ to 3.10+
- Updated project classifiers to include Python 3.10, 3.11, and 3.12

## [0.4.5] - 2025-09-24

### Improved
- Enhanced PyPI installation documentation with step-by-step instructions

## [0.4.4] - 2025-09-23

### Fixed
- PyPI badges and links in README now point to correct package name `redmine-mcp-server`

## [0.4.3] - 2025-09-23

### Added
- MCP Registry support with server.json configuration

## [0.4.2] - 2025-09-23

### Added
- PyPI package publishing support as `redmine-mcp-server`
- Console script entry point: `redmine-mcp-server` command

## [0.4.1] - 2025-09-23

### Fixed
- GitHub Actions CI test failure in security validation tests

## [0.4.0] - 2025-09-22

### Added
- `get_redmine_attachment_download_url()` - Secure replacement for attachment downloads
- Comprehensive security validation test suite

### Deprecated
- `download_redmine_attachment()` - Use `get_redmine_attachment_download_url()` instead
  - SECURITY: `save_dir` parameter vulnerable to path traversal (CWE-22, CVSS 7.5)
  - Will be removed in v0.5.0

### Security
- **CRITICAL**: Fixed path traversal vulnerability in attachment downloads (CVSS 7.5)

## [0.3.1] - 2025-09-21

### Fixed
- Integration test compatibility with new attachment download API format

## [0.3.0] - 2025-09-21

### Added
- **Automatic file cleanup system** with configurable intervals and expiry times
- `AUTO_CLEANUP_ENABLED` environment variable for enabling/disabling automatic cleanup (default: true)
- `CLEANUP_INTERVAL_MINUTES` environment variable for cleanup frequency (default: 10 minutes)
- `ATTACHMENT_EXPIRES_MINUTES` environment variable for default attachment expiry (default: 60 minutes)
- Background cleanup task with lazy initialization via MCP tool calls

### Changed
- **BREAKING**: `CLEANUP_INTERVAL_HOURS` replaced with `CLEANUP_INTERVAL_MINUTES` for finer control

## [0.2.1] - 2025-09-20

### Added
- HTTP file serving endpoint (`/files/{file_id}`) for downloaded attachments
- Secure UUID-based file URLs with automatic expiry (24 hours default)
- New `file_manager.py` module for attachment storage and cleanup management

### Changed
- **BREAKING**: `download_redmine_attachment` now returns `download_url` instead of `file_path`

## [0.2.0] - 2025-09-20

### Changed
- **BREAKING**: Migrated from FastAPI/SSE to FastMCP streamable HTTP transport
- **BREAKING**: MCP endpoint changed from `/sse` to `/mcp`

## [0.1.6] - 2025-06-19
### Added
- New MCP tool `search_redmine_issues` for querying issues by text.

## [0.1.5] - 2025-06-18
### Added
- `get_redmine_issue` can now return attachment metadata via a new `include_attachments` parameter.
- New MCP tool `download_redmine_attachment` for downloading attachments.

## [0.1.4] - 2025-05-28

### Removed
- Deprecated `get_redmine_issue_comments` tool. Use `get_redmine_issue` with `include_journals=True` to retrieve comments.

### Changed
- `get_redmine_issue` now includes issue journals by default.

## [0.1.3] - 2025-05-27

### Added
- New MCP tool `list_my_redmine_issues` for retrieving issues assigned to the current user
- New MCP tool `get_redmine_issue_comments` for retrieving issue comments

## [0.1.2] - 2025-05-26

### Changed
- Roadmap moved to its own document

### Added
- New MCP tools `create_redmine_issue` and `update_redmine_issue` for managing issues

## [0.1.1] - 2025-05-25

### Changed
- Updated project documentation with correct repository URLs
- Updated LICENSE with proper copyright (2025 Kevin Tan and contributors)

## [0.1.0] - 2025-05-25

### Added
- Initial release of Redmine MCP Server
- MIT License for open source distribution
- Core MCP server implementation with FastAPI and SSE transport
- Two primary MCP tools:
  - `get_redmine_issue(issue_id)` - Retrieve detailed issue information
  - `list_redmine_projects()` - List all accessible Redmine projects
- Comprehensive authentication support (username/password and API key)
- Docker containerization support

[2.0.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v2.0.1
[2.0.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v2.0.0
[1.3.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.3.0
[1.2.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.2.0
[1.1.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.1.2
[1.1.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.1.1
[1.1.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.1.0
[1.0.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v1.0.0
[0.12.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.12.1
[0.12.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.12.0
[0.11.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.11.0
[0.10.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.10.0
[0.9.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.9.1
[0.9.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.9.0
[0.8.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.8.1
[0.8.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.8.0
[0.7.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.7.1
[0.7.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.7.0
[0.6.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.6.0
[0.5.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.2
[0.5.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.1
[0.5.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.5.0
[0.4.5]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.5
[0.4.4]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.4
[0.4.3]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.3
[0.4.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.2
[0.4.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.1
[0.4.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.4.0
[0.3.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.3.1
[0.3.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.3.0
[0.2.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.2.1
[0.2.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.2.0
[0.1.6]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.6
[0.1.5]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.5
[0.1.4]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.4
[0.1.3]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.3
[0.1.2]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.2
[0.1.1]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.1
[0.1.0]: https://github.com/jztan/redmine-mcp-server/releases/tag/v0.1.0
