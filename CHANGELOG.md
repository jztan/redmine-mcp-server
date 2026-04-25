# Changelog

All notable changes to this project will be documented in this file.


The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
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
- **`copy_issue` data-integrity bug:** When both `copy_subtasks=False` and `copy_attachments=False` were passed, python-redmine's `include or (...)` fallback silently copied both anyway. Now passes a non-empty sentinel so the fallback does not trigger.
- **`log_time_for_user` / `import_time_entries` hours validation:** Now rejects NaN, Infinity, booleans (which Python treats as `int`), and non-numeric types before hitting the API.
- **`import_time_entries` bulk safeguards:** Added a 500-entry batch cap (returns a clear error instead of pinning the event loop for minutes on a massive request). Yields the event loop between entries via `asyncio.sleep(0)` so concurrent MCP requests are not starved. Split the create/serialize try blocks so a post-create serialization failure does not flip a successful create into a reported failure (which would tempt callers to retry and create duplicates).

### Changed
- **List tools now return `Union[List, Dict]` on error** instead of `[{"error": "..."}]`. Affects `list_issue_relations`, `list_subtasks`, `list_issue_categories`, `list_files`, `list_redmine_roles`, `list_redmine_trackers`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`, `list_redmine_users`, `list_redmine_queries`. Callers should check `isinstance(result, dict)` or `"error" in result` to distinguish failure from an empty list. Matches the pre-existing convention of `list_time_entries`, `list_redmine_issues`, and `search_redmine_issues`.
- **List tools now cap results at 500 items** (configurable via `_DEFAULT_LIST_RESULT_CAP` constant) via the new `_iter_capped` helper. Previously unbounded iteration could OOM on projects with tens of thousands of subtasks/relations/files.
- **Module-level constants consolidated:** `_FILE_UPLOAD_MAX_SIZE_BYTES`, `_MAX_FILENAME_LEN`, `_IMPORT_TIME_ENTRIES_MAX_BATCH`, `_DEFAULT_LIST_RESULT_CAP`, `_DOWNLOAD_TIMEOUT`, and `_FILE_DOWNLOAD_MAX_REDIRECTS` are all declared once at the top of the module instead of scattered across different sections. Top-level `import httpx` and `from urllib.parse import unquote, urlparse` hoisted out of function-local imports.

### CI
- Fix `pip-audit` failing on packages not published to PyPI by adding `--no-emit-project` to `uv export` in `dependency-audit.yml`

### Contributors
- @mihajlovicjj — 30 new MCP tools, security hardening, and 82+ new tests ([#89](https://github.com/jztan/redmine-mcp-server/pull/89))

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
