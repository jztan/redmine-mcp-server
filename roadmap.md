# Roadmap

## 🎯 Project Status

**Current Version:** v1.2.2 (released 2026-04-25)
**Next Release:** v1.3.0 (cuts from current `develop`; large feature drop — see below)
**Next Major:** v2.0.0 (tool consolidation — breaking)
**MCP Registry Status:** Published

**Test Suite:** 1118 tests passing (1042 unit + 76 integration; 4 skipped behind `REDMINE_AGILE_ENABLED`)
**Total MCP Tools:** 69 (will reduce to ~43 in v2.0)

---

### ✅ Completed Features

#### Core Infrastructure
- [x] FastMCP streamable HTTP transport migration (v0.2.0)
- [x] Native FastMCP v3 core migration (v1.1.0)
  - `fastmcp>=3.0.0,<4`; converted `**kwargs` tools to explicit typed parameters
- [x] Docker containerization with multi-stage builds
- [x] Environment-based configuration with dual `.env` support
- [x] Centralized error handling with 12 error types and actionable messages (v0.10.0)
- [x] Comprehensive test suite (unit, integration, security tests)
- [x] GitHub Actions CI/CD pipeline; dependency-audit workflow with `pip-audit` (v1.1.1)
- [x] Stale issue / lock closed / autoclose label workflows
- [x] PyPI package publishing as `redmine-mcp-server` (v0.4.2)
- [x] MCP Registry preparation with validation (v0.4.3)
- [x] Console script entry point for easy execution
- [x] `.env` loading from current working directory for pip installs (v0.7.1)
- [x] Release SOP documented in `RELEASE_SOP.md` with `scripts/release.py` automation
- [x] Hotfix workflow via `scripts/release.py --hotfix` (v1.2.2)

#### Redmine Integration — Issues & Search
- [x] List, get, create, update issues (`get_redmine_issue`, `list_redmine_issues`, `create_redmine_issue`, `update_redmine_issue`)
  - Selective field returns via `fields` parameter (~96% token reduction)
  - Custom fields by name in `update_redmine_issue` (v0.12.0)
- [x] Search issues by text query with pagination and field selection (v0.7.0)
- [x] Global search across all Redmine resources (v0.9.0; requires Redmine 3.3.0+)
- [x] Journal pagination on `get_redmine_issue` (`journal_limit`/`journal_offset`) (v1.0.0)
- [x] Include flags on `get_redmine_issue` (watchers, relations, children) (v1.0.0)
- [x] Required custom field autofill with auto-retry (v0.12.0; opt-in)
- [x] Smart project status summarization with activity analysis
- [x] **Issue tracking expansion (v1.3 — pending release):**
  - `copy_issue`, `list_subtasks`
  - Issue relations: `list_issue_relations`, `create_issue_relation`, `delete_issue_relation`
  - Watchers: `add_watcher`, `remove_watcher`
  - Journal notes: `edit_note`, `set_note_private`, `get_private_notes`
  - Issue categories: `list_issue_categories`, `create_issue_category`, `update_issue_category`, `delete_issue_category`

#### Redmine Integration — Projects, Versions, Wiki
- [x] List accessible projects (`list_redmine_projects`)
- [x] Project members listing with roles (v1.0.0)
- [x] Project versions/milestones listing (v0.12.0; status filtering)
- [x] Wiki page retrieval, create, update, delete (v0.9.0–v0.10.0)
- [x] **Project & Wiki expansion (v1.3 — pending release):**
  - `manage_redmine_version` — create/update/delete versions in one tool with `action` param
  - `list_redmine_roles`, `get_project_modules`
  - `add_project_member`, `update_project_member`, `remove_project_member`
  - `list_wiki_pages`, `rename_wiki_page` (with silent permission failure detection)

#### Redmine Integration — Time Tracking & Files
- [x] Time tracking — full CRUD (v1.0.0)
  - `list_time_entries`, `create_time_entry`, `update_time_entry`, `list_time_entry_activities`
- [x] Project-scoped activity discovery via `project_id` parameter (v1.2.2)
- [x] Download attachments with HTTP URLs and UUID-based secure storage
- [x] Automatic file cleanup with configurable expiry
- [x] **Time tracking & files expansion (v1.3 — pending release):**
  - `log_time_for_user` — log time on behalf of another user
  - `import_time_entries` — bulk import with per-entry error reporting
  - `list_files`, `upload_file` (with SSRF protection on URL-based uploads), `delete_file`

#### Redmine Integration — Discovery / Enumeration (v1.3 — pending release)
- [x] `list_redmine_trackers`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`
- [x] `list_redmine_users` (admin filter), `get_current_user` (works for non-admins)
- [x] `list_redmine_queries` (saved custom queries; read-only)

#### Redmine Integration — Plugin Support (opt-in)
- [x] **RedmineUP Agile plugin** (v1.2.0; `REDMINE_AGILE_ENABLED=true`)
  - `get_redmine_issue` returns `story_points`, `agile_sprint_id`, `agile_position`
  - `update_redmine_issue` accepts `story_points`
- [x] **RedmineUP Checklists Pro plugin** (v1.3 — pending; `REDMINE_CHECKLISTS_ENABLED=true`)
  - `get_checklist`, `update_checklist_item`, `mark_checklist_done`
- [x] **RedmineUP Products plugin** (v1.3 — pending; `REDMINE_PRODUCTS_ENABLED=true`)
  - `list_products`, `get_product`, `add_product`, `edit_product`
- [x] **RedmineUP CRM plugin** (v1.3 — pending; `REDMINE_CRM_ENABLED=true`)
  - `list_contacts`, `get_contact`, `create_contact`, `edit_contact`, `delete_contact`
  - `assign_contact_to_project`, `remove_contact_from_project`

#### Redmine Integration — Composite Tools (v1.3 — pending release)
- [x] `get_gantt_chart` — composite read tool aggregating issues + versions + relations into a Gantt-shaped response

#### Security & Performance
- [x] Path traversal vulnerability fix (CVE, CVSS 7.5)
- [x] UUID-based secure file storage with HTTP file serving and time-limited URLs
- [x] Server-controlled storage policies; 95% memory reduction with pagination
- [x] MCP security fix (CVE-2025-62518) via mcp v1.19.0 (v0.6.0)
- [x] SSL/TLS certificate configuration support (v0.8.0)
  - Self-signed certs (`REDMINE_SSL_CERT`), mTLS (`REDMINE_SSL_CLIENT_CERT`), verification control (`REDMINE_SSL_VERIFY`)
- [x] Prompt injection protection with `<insecure-content>` boundary tags (v1.0.0)
  - Applied to descriptions, journal notes, wiki text, excerpts, version descriptions, attachment metadata, contact display fields
- [x] Read-only mode via `REDMINE_MCP_READ_ONLY` env var (v1.0.0)
- [x] Patch 14 CVEs across 7 transitive dependencies (v1.1.1)
  - pyjwt, cryptography, starlette, fastapi, urllib3, requests, python-multipart, pygments
- [x] FastMCP v3.2.0 CVE patches: CVE-2025-64340, CVE-2026-27124 (v1.2.0)
- [x] **Security hardening (v1.3 — pending release):**
  - SSRF protection for `upload_file(source_url=...)` with public/private IP gating, redirect re-validation, credentials rejection
  - Container-type fail-closed for `delete_file` (refuse non-Project attachments by default)
  - Int-ID validators reject booleans (Python `True`/`False` are `int` — guards `role_ids`, `user_id`, `group_id`)
  - Error-message secret scrubbing (API keys, Bearer tokens, basic-auth credentials)
  - `_is_valid_project_id` charset restriction `^[a-z0-9][a-z0-9_-]{0,99}$` to prevent URL-path injection in plugin tools
  - `add_product` `status_id` constraint to `{1, 2}`
  - `cryptography` 46.0.6 → 46.0.7 patching CVE-2026-39892

#### Authentication
- [x] API key authentication
- [x] Username/password authentication
- [x] OAuth2 per-user authentication mode (v1.0.0)
  - `REDMINE_AUTH_MODE=oauth` with Bearer token validation
  - OAuth discovery endpoints (RFC 8707, RFC 8414); token revocation (RFC 7009)
  - Per-request client isolation via ContextVar
  - Requires Redmine 6.1+ (Doorkeeper)

#### Documentation & Quality
- [x] Complete tool documentation in `docs/tool-reference.md`
- [x] Separate developer guide in `docs/contributing.md`
- [x] OAuth2 multi-tenant setup guide (`docs/oauth-setup.md`; v1.0.0)
- [x] Comprehensive troubleshooting guide
- [x] CHANGELOG with semantic versioning and contributor credits
- [x] Release SOP in `RELEASE_SOP.md`
- [x] Test coverage tracking via Codecov (v0.8.1)
- [x] PEP 8 compliance via flake8 + black; pre-commit hooks (v1.2.2)
- [x] GitHub issue templates (bug report, feature request)
- [x] Dependabot integration

#### Python Compatibility
- [x] Support Python 3.10+ (v0.5.0); CI tests 3.10, 3.11, 3.12, 3.13

---

### 📅 Planned Releases

#### v1.3.0 — Large Feature Drop (next release; cuts from current `develop`)
*Priority: High | Effort: ready to ship | Status: All work merged into `develop`*

Ships everything currently in `Unreleased`. Highlights:

- **34 new MCP tools** across Issues (14), Projects (5), Time Tracking (2), Files (3), Discovery (6), Wiki (2), Gantt (1), Products (4), Contacts/CRM (7), Checklists (3), and version management (`manage_redmine_version`)
- **Plugin support:** RedmineUP Checklists, Products, and CRM (all opt-in via env flags)
- **Security hardening** — SSRF protection, path-charset validation, secret scrubbing, attachment fail-closed, prompt-injection wrapping on additional fields
- **34 new tests** beyond v1.2.2 (1042 unit total)
- 1031 → 1042 unit tests, 76 integration tests passing

**Behavior changes worth noting in the release notes:**
- `get_gantt_chart` ships with `include_closed=False` default
- List tools now return `Union[List, Dict]` on error (was `[{"error":...}]` for some)
- List tools cap results at 500 items via `_iter_capped`

#### v2.0.0 — Tool Consolidation (breaking)
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

### 🔮 Future (post-v2.0)

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

### 🔧 Maintenance Notes

- Monitor GitHub issues for actual user problems
- Only add features/fixes based on real user feedback
- Keep the codebase simple and maintainable
- Preserve contributor credits in CHANGELOG verbatim

---

**Last Updated:** 2026-05-06 (v1.2.2 current; v1.3 ready to cut; v2.0 consolidation designed)
