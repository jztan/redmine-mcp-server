# Roadmap

## 🎯 Project Status

**Current Version:** v0.7.1 (PyPI Published)
**MCP Registry Status:** Published

### ✅ Completed Features

#### Core Infrastructure
- [x] FastMCP streamable HTTP transport migration (v0.2.0)
- [x] Docker containerization with multi-stage builds
- [x] Environment-based configuration with dual .env support
- [x] Enhanced error handling and structured logging
- [x] Comprehensive test suite (unit, integration, security tests)
- [x] GitHub Actions CI/CD pipeline
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
- [x] Global search across all Redmine resources (issues, projects, wikis, news, documents)
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
- [x] SSL/TLS certificate configuration support (v0.7.0+)
  - Self-signed certificates (`REDMINE_SSL_CERT`)
  - Mutual TLS/mTLS (`REDMINE_SSL_CLIENT_CERT`)
  - SSL verification control (`REDMINE_SSL_VERIFY`)

#### Documentation & Quality
- [x] Complete API documentation with examples
- [x] PyPI installation instructions
- [x] PEP 8 compliance with flake8 and black
- [x] Comprehensive README with tool descriptions
- [x] CHANGELOG with semantic versioning
- [x] Development guidelines in CLAUDE.md
- [x] Separated documentation structure (v0.5.2)
  - `docs/tool-reference.md` - Complete tool documentation
  - `docs/troubleshooting.md` - Comprehensive troubleshooting guide
  - `docs/contributing.md` - Developer guide

#### Python Compatibility
- [x] **Support Python 3.10+** (v0.5.0)
  - Tested with Python 3.10, 3.11, 3.12, 3.13
  - `requires-python = ">=3.10"` in pyproject.toml
  - CI tests multiple Python versions

### 📋 Planned Features

#### Phase 4: Growth-Focused Improvements
- [ ] **Example Claude Code recipes** (HIGH PRIORITY - drives adoption):
  - Sprint Planning Assistant
  - Daily Standup Reporter
  - Issue Triage Helper
  - Release Notes Generator
  - Project Health Check
- [ ] Clear connection error messages:
  - "Failed to connect to Redmine" → "Cannot connect to {REDMINE_URL}. Check: 1) URL is correct, 2) Network access, 3) Redmine is running"
  - "401 Unauthorized" → "Authentication failed. Check your API key or username/password in .env"
  - "403 Forbidden" → "Access denied. Your Redmine user lacks permission for this action"

#### Future (Only if Users Request)
- [ ] Custom field support
- [ ] Bulk operations
- [ ] User lookup tool
- [ ] Wiki page management

### 🔧 Maintenance Notes

- Monitor GitHub issues for actual user problems
- Only add features/fixes based on real user feedback
- Keep the codebase simple and maintainable

---

**Last Updated:** 2025-12-02 (v0.7.1)
