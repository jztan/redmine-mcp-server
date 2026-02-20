# Roadmap

## 🎯 Project Status

**Current Version:** v0.12.0 (PyPI Published)
**MCP Registry Status:** Published

### ✅ Completed Features

#### Core Infrastructure
- [x] FastMCP streamable HTTP transport migration (v0.2.0)
- [x] Docker containerization with multi-stage builds
- [x] Environment-based configuration with dual .env support
- [x] Enhanced error handling and structured logging
- [x] Comprehensive test suite (unit, integration, security tests)
- [x] GitHub Actions CI/CD pipeline
- [x] Stale issue management workflow (auto-close inactive issues)
- [x] Lock closed issues workflow (prevent zombie threads)
- [x] Remove autoclose label workflow (respond to user activity)
- [x] PyPI package publishing as `redmine-mcp-server` (v0.4.2)
- [x] MCP Registry preparation with validation (v0.4.3)
- [x] Console script entry point for easy execution
- [x] .env loading from current working directory for pip installs (v0.7.1)

#### Redmine Integration
- [x] List accessible projects
- [x] Get issue details with comments and attachments
- [x] Create and update issues with field resolution
- [x] List issues assigned to current user
- [x] Server-side pagination with token management (v0.4.0)
- [x] Search issues by text query with pagination and field selection (v0.7.0)
- [x] Global search across all Redmine resources (v0.9.0)
  - Search issues, wiki pages, and other resources with `search_entire_redmine()`
  - Server-side pagination with configurable limit and offset
  - Requires Redmine 3.3.0+
- [x] Wiki page retrieval with version history (v0.9.0)
  - `get_redmine_wiki_page()` for retrieving wiki content
  - Optional version parameter for specific page versions
  - Attachment metadata support
- [x] Wiki page editing — create, update, delete (v0.10.0)
- [x] Centralized error handling with 12 error types and actionable messages (v0.10.0)
- [x] General-purpose issue listing with flexible filtering (v0.11.0)
  - `list_redmine_issues()` with project, status, tracker, assignee, priority filters
  - Selective field returns via `fields` parameter (~96% token reduction)
- [x] Project versions/milestones listing with status filtering (v0.12.0)
  - `list_redmine_versions()` with open/locked/closed filtering
- [x] Required custom field autofill with auto-retry on validation errors (v0.12.0)
  - Opt-in via `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true`
  - Fills from Redmine defaults or `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` env var
- [x] Download attachments with HTTP URLs
- [x] Smart project status summarization with activity analysis
- [x] Automatic status name to ID resolution

#### Security & Performance
- [x] Path traversal vulnerability fix (CVE, CVSS 7.5)
- [x] UUID-based secure file storage
- [x] Automatic file cleanup with configurable expiry
- [x] HTTP file serving endpoint with time-limited URLs
- [x] Server-controlled storage policies
- [x] 95% memory reduction with pagination
- [x] 87% faster response times
- [x] MCP security fix (CVE-2025-62518) via mcp v1.19.0 (v0.6.0)
- [x] SSL/TLS certificate configuration support (v0.8.0)
  - Self-signed certificates (`REDMINE_SSL_CERT`)
  - Mutual TLS/mTLS (`REDMINE_SSL_CLIENT_CERT`)
  - SSL verification control (`REDMINE_SSL_VERIFY`)
  - Dynamic test certificate generation (removed private keys from repo)

#### Documentation & Quality
- [x] Complete API documentation with examples
- [x] PyPI installation instructions
- [x] PEP 8 compliance with flake8 and black
- [x] Comprehensive README with tool descriptions
- [x] CHANGELOG with semantic versioning
- [x] Separated documentation structure (v0.5.2)
  - `docs/tool-reference.md` - Complete tool documentation
  - `docs/troubleshooting.md` - Comprehensive troubleshooting guide
  - `docs/contributing.md` - Developer guide
- [x] Test coverage tracking via Codecov integration (v0.8.1)
- [x] GitHub issue templates (bug report, feature request) (v0.8.1)
- [x] Dependabot integration for automated dependency updates (v0.8.1)
- [x] 457 tests with 98% coverage (v0.12.0)

#### Python Compatibility
- [x] **Support Python 3.10+** (v0.5.0)
  - Tested with Python 3.10, 3.11, 3.12, 3.13
  - `requires-python = ">=3.10"` in pyproject.toml
  - CI tests multiple Python versions

### 📋 Planned Features

#### v1.0.0: Production/Stable
- [ ] Remove deprecated `list_my_redmine_issues` (breaking change)
- [ ] Prompt injection protection with `<insecure-content>` boundary tags
- [ ] Read-only mode via `REDMINE_MCP_READ_ONLY` env var
- [ ] Journal pagination on `get_redmine_issue` (`journal_limit`/`journal_offset`)
- [ ] Include flags on `get_redmine_issue` (watchers, relations, children)
- [ ] Version bump to 1.0.0, Development Status → Production/Stable

#### Future (Only if Users Request)
- [ ] YAML response format option
- [ ] User instructions file (`REDMINE_INSTRUCTIONS`)
- [ ] Bulk operations

### 🔧 Maintenance Notes

- Monitor GitHub issues for actual user problems
- Only add features/fixes based on real user feedback
- Keep the codebase simple and maintainable

---

**Last Updated:** 2026-02-20 (v0.12.0)
