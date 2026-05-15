# Roadmap

## 🎯 Project Status

**Current Version:** v2.0.0 (released 2026-05-16)
**Next Release:** TBD (post-v2.0 hardening + native FastMCP v3 auth migration on deck)
**MCP Registry Status:** Published

**Test Suite:** 1339 tests passing (1259 unit + 80 integration; 4 skipped behind `REDMINE_AGILE_ENABLED`)
**Total MCP Tools:** 46 (43 after the v2.0 consolidation, plus `delete_redmine_issue`, `get_mcp_server_info`, `manage_document`)

---

## ✅ Released Versions

For per-release detail, parameter changes, and contributor credits, see [CHANGELOG.md](CHANGELOG.md).

### v2.0.0 — 2026-05-16 (current)
Major release. Structural consolidation, schema-tightening sweep, and LLM-eval-driven usability work. Tool count goes from 69 to 46 (35 single-verb tools folded into 9 `manage_X(action=...)` tools, plus 3 new tools added). See [CHANGELOG.md](CHANGELOG.md) for the full list; full release notes at the [v2.0.0 release page](https://github.com/jztan/redmine-mcp-server/releases/tag/v2.0.0).

- **9 new `manage_X(action=...)` tools** replace 35 single-verb tools (full mapping below in the historical v2.0 plan).
- **3 new tools**: `delete_redmine_issue` (with confirmation gate and cascade preview), `get_mcp_server_info` (deployment-lag detection), `manage_document` (DMSF plugin support, gated by `REDMINE_DMSF_ENABLED`).
- **Schema tightening**: `manage_*.action` is a JSON-schema enum; `limit`/`offset` carry explicit bounds; `list_redmine_issues.status_id` accepts `"open"`/`"closed"`/`"*"`; `assigned_to_id` / `user_id` reject arbitrary strings; new `CleanValidationErrorMiddleware` turns Pydantic dumps into the project's standard `INVALID_ARGUMENTS` envelope.
- **`get_redmine_attachment`** replaces the removed `get_redmine_attachment_download_url`; works in both HTTP and stdio deployments with streaming download, byte-cap abort, and path-traversal protection.
- **`REDMINE_PUBLIC_URL`** rewriter fixes Docker-internal `content_url` values in attachment metadata.
- **`<insecure-content>` wrap policy** tightened: free-text fields stay wrapped, structured metadata (filenames, display names, codes) is returned verbatim.
- **Error envelope consistency**: list/search tools return flat `{"error": ...}` on failure (was sometimes `[{"error": ...}]`); 404s on `get_redmine_attachment` carry `ATTACHMENT_UNAVAILABLE` + hint; create/update validation errors carry `missing_required_fields` + tailored recovery hints.
- **`search_redmine_issues` hydration**: results now carry full issue metadata via a follow-up `/issues.json` call instead of returning `null` fields.
- **Internal refactor**: 6591-line `redmine_handler.py` split into a `tools/` package and flat `_X.py` helpers. Public MCP surface unchanged; **breaking for any consumer importing from internal paths**.
- **Security**: GitHub Actions pinned to commit SHAs; `fastmcp` bumped to 3.2.4 (three patches); `pytest` to 9.0.3 (CVE-2025-71176); `python-multipart` to 0.0.27 (CVE-2026-42561) with explicit lower-bound constraint.

**Tool count:** 69 → 46.

### v1.3.0 — 2026-05-06
Large feature drop. 34 new MCP tools added; 1031 → 1042 unit tests.

- 14 issue-tracking tools: `copy_issue`, `list_subtasks`, issue relations, watchers, journal notes, issue categories
- 5 project tools: `list_redmine_roles`, `get_project_modules`, project member CRUD
- 6 discovery tools: trackers, statuses, priorities, users, current user, queries
- 2 wiki tools: `list_wiki_pages`, `rename_wiki_page` (with silent permission failure detection)
- 1 composite tool: `get_gantt_chart` (issues + versions + relations)
- 4 RedmineUP Products plugin tools (opt-in via `REDMINE_PRODUCTS_ENABLED`)
- 7 RedmineUP CRM/Contacts plugin tools (opt-in via `REDMINE_CRM_ENABLED`)
- 3 RedmineUP Checklists Pro plugin tools (opt-in via `REDMINE_CHECKLISTS_ENABLED`)
- 1 unified version tool: `manage_redmine_version` (replaces three planned tools with one `action`-driven tool)
- 2 time-tracking tools: `log_time_for_user`, `import_time_entries`
- 3 file tools: `list_files`, `upload_file` (with SSRF protection), `delete_file`
- Security hardening: SSRF gating, `_is_valid_project_id` charset restriction, `add_product` `status_id` constraint, secret scrubbing in error messages, prompt-injection wrapping on additional fields, `delete_file` container-type fail-closed

**Behavior changes:** `get_gantt_chart` defaults `include_closed=False`; list tools return `Union[List, Dict]` on error; list tools cap at 500 items via `_iter_capped`.

### v1.2.x line — 2026-04-08 to 2026-04-25
- **v1.2.2** (2026-04-25) — `list_time_entry_activities` accepts `project_id` for project-specific activity discovery; `scripts/release.py --hotfix` workflow
- **v1.2.0** (2026-04-14) — RedmineUP Agile plugin support (`story_points`, `agile_sprint_id`, `agile_position`); FastMCP v3.2.0 CVE patches (CVE-2025-64340, CVE-2026-27124)
- **v1.1.2** (2026-04-08) — Fix `AttributeError: 'str' object has no attribute 'isoformat'` on non-UTC Redmine configurations

### v1.1.x line — FastMCP v3 era (2026-03-21 to 2026-03-31)
- **v1.1.1** (2026-03-31) — 14 CVEs patched across 7 transitive deps (pyjwt, cryptography, starlette, fastapi, urllib3, requests, python-multipart, pygments); `dependency-audit.yml` workflow
- **v1.1.0** (2026-03-21) — FastMCP v3 core migration; `**kwargs` tools converted to explicit typed parameters

### v1.0.0 — 2026-03-14
GA release. Prompt injection protection with `<insecure-content>` boundary tags; read-only mode (`REDMINE_MCP_READ_ONLY`); OAuth2 per-user authentication (RFC 8707/8414/7009); time tracking CRUD; project members; journal pagination and include flags on `get_redmine_issue`; deprecated `list_my_redmine_issues` removed.

### Pre-v1.0 highlights
- **v0.12.x** (Feb-Mar 2026) — custom field handling, `list_project_issue_custom_fields`, `list_redmine_versions`, autofill required custom fields, Docker `421 Misdirected Request` fix
- **v0.11.0** (2026-02-14) — `list_redmine_issues` with flexible filtering and selective field returns
- **v0.10.0** (2026-01-11) — Wiki page editing (create/update/delete), centralized error handler with 12 error types
- **v0.9.x** (Dec 2025) — Global search (`search_entire_redmine`), wiki page retrieval (`get_redmine_wiki_page`), removed deprecated `download_redmine_attachment`
- **v0.8.x** (Dec 2025) — SSL/TLS configuration (self-signed, mTLS, verification control); test coverage tracking via Codecov
- **v0.7.x** (Nov-Dec 2025) — Search optimization with pagination and field selection; pip-install `.env` loading from CWD
- **v0.6.0** (2025-10-25) — MCP security fix CVE-2025-62518 via mcp 1.19.0
- **v0.5.x** (Sep-Oct 2025) — Python 3.10+ support; documentation reorganization
- **v0.4.x** (Sep 2025) — `get_redmine_attachment_download_url` (replaces deprecated download tool, fixes CVSS 7.5 path traversal); PyPI publishing as `redmine-mcp-server`; MCP Registry support
- **v0.2.x – v0.3.x** (Sep 2025) — FastMCP streamable HTTP migration; HTTP file serving with UUID-based URLs; automatic file cleanup
- **v0.1.x** (May-Jun 2025) — Initial release; core issue tools; search, attachments, wiki retrieval

---

## 📅 Planned Releases

*No specific version planned yet — v2.0.0 just shipped. Likely next-cut candidates are tracked in [🔮 Future](#-future-post-v20) below.*

---

## 🔮 Future (post-v2.0)

- [ ] **Native FastMCP v3 Auth Migration** *(Priority: High security; was previously slated for v2.0)*
  - Replace `RedmineOAuthMiddleware` Starlette middleware with FastMCP v3's native `auth=` constructor parameter (`JWTVerifier` / `OAuthProxy` / `MultiAuth`)
  - Closes the medium-likelihood `custom_route` auth bypass risk identified in the FastMCP v3 compatibility analysis
  - Evaluate `JWTVerifier` vs `OAuthProxy` fit for Doorkeeper OAuth flow
  - Verify OAuth discovery endpoints remain functional under native auth
  - Likely v2.1 or v2.2 depending on scope

- [ ] **OpenTelemetry observability**
  - Optional `opentelemetry-sdk` dependency
  - Zero overhead when unconfigured; production-grade tracing (tool calls, Redmine API latency, error rates) when OTEL SDK is present
  - Document OTEL configuration in `docs/contributing.md`

- [ ] **Only if users request:**
  - YAML response format option
  - User instructions file (`REDMINE_INSTRUCTIONS`)
  - Bulk operations beyond `import_time_entries`

---

## 🔧 Maintenance Notes

- Monitor GitHub issues for actual user problems
- Only add features/fixes based on real user feedback
- Keep the codebase simple and maintainable
- Preserve contributor credits in CHANGELOG verbatim

---

**Last Updated:** 2026-05-16 (v2.0.0 released)
