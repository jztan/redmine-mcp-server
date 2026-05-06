# Roadmap

## 🎯 Project Status

**Current Version:** v1.3.0 (released 2026-05-06)
**Next Release:** v2.0.0 (tool consolidation — breaking; designed)
**MCP Registry Status:** Published

**Test Suite:** 1118 tests passing (1042 unit + 76 integration; 4 skipped behind `REDMINE_AGILE_ENABLED`)
**Total MCP Tools:** 69 (will reduce to ~43 in v2.0)

---

## ✅ Released Versions

For per-release detail, parameter changes, and contributor credits, see [CHANGELOG.md](CHANGELOG.md).

### v1.3.0 — 2026-05-06 (current)
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

### v2.0.0 — Tool Consolidation (next)
*Priority: High | Effort: Medium | Status: Designed; implementation plan ready*

Reduce tool count from 69 to ~43 by folding CRUD-style tools into `manage_X(action=...)` tools following the `manage_redmine_version` pattern. No functionality is lost; old tool names are removed.

**The 9 new `manage_X` tools** (replacing 35 existing tools):

| New tool | Replaces |
|---|---|
| `manage_project_member` | `add_project_member`, `update_project_member`, `remove_project_member` |
| `manage_issue_category` | `list_issue_categories`, `create_issue_category`, `update_issue_category`, `delete_issue_category` |
| `manage_issue_relation` | `list_issue_relations`, `create_issue_relation`, `delete_issue_relation` |
| `manage_issue_watcher` | `add_watcher`, `remove_watcher` |
| `manage_issue_note` | `edit_note`, `set_note_private` |
| `manage_time_entry` | `create_time_entry`, `update_time_entry`, `log_time_for_user` |
| `manage_redmine_wiki_page` | `get_redmine_wiki_page`, `create_redmine_wiki_page`, `update_redmine_wiki_page`, `delete_redmine_wiki_page`, `list_wiki_pages`, `rename_wiki_page` |
| `manage_product` | `list_products`, `get_product`, `add_product`, `edit_product` |
| `manage_contact` | `list_contacts`, `get_contact`, `create_contact`, `edit_contact`, `delete_contact`, `assign_contact_to_project`, `remove_contact_from_project` |

**Tasks:**
- [ ] Land 9 `manage_X` implementations behind a feature branch off post-v1.3 `develop`
- [ ] Reorganize per-tool tests into per-`manage_X` test classes
- [ ] Drop `mark_checklist_done` (use `update_checklist_item(is_done=True)` directly)
- [ ] Update `docs/tool-reference.md`, `README.md`, `CHANGELOG.md` with migration guide
- [ ] Open public heads-up issue before merging

**What stays the same:** the four most-used issue tools (`get_redmine_issue`, `list_redmine_issues`, `create_redmine_issue`, `update_redmine_issue`), `get_gantt_chart`, `get_private_notes`, all discovery/enumeration tools, all file operations, auth, SSL, plugin gating.

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

**Last Updated:** 2026-05-06 (v1.3.0 released; v2.0.0 consolidation designed and ready to start)
