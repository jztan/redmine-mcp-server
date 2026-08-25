# Contributing Guide

Thank you for your interest in contributing to the Redmine MCP Server! This guide will help you get started.

## Ways to Contribute

- **Report bugs**: Submit detailed issue reports
- **Suggest features**: Propose new features or improvements
- **Fix issues**: Submit pull requests for bug fixes
- **Add features**: Implement new functionality
- **Improve docs**: Enhance documentation and examples
- **Write tests**: Add test coverage

## Getting Started

### Prerequisites

- Python 3.10+ installed
- Git installed
- Access to a Redmine instance (for testing)
- Familiarity with MCP (Model Context Protocol)

### Development Setup

1. **Fork and Clone**
   ```bash
   # Fork the repository on GitHub first
   git clone https://github.com/YOUR_USERNAME/redmine-mcp-server.git
   cd redmine-mcp-server
   ```

2. **Create Virtual Environment**
   ```bash
   # Using uv (recommended)
   uv venv
   source .venv/bin/activate

   # Or using standard Python
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Development Dependencies**
   ```bash
   # For source installation
   uv pip install -e .[dev]

   # Or using pip
   pip install -e .[dev]
   ```

4. **Configure Environment**
   ```bash
   # Copy example environment file
   cp .env.example .env

   # Edit .env with your Redmine credentials
   # Required: REDMINE_URL, REDMINE_API_KEY (or REDMINE_USERNAME/PASSWORD)
   ```

5. **Verify Setup**
   ```bash
   # Run tests to ensure everything works
   python tests/run_tests.py --all

   # Start the server
   uv run python -m redmine_mcp_server.main
   ```

## Where things live

After v2.0, the codebase is organized by resource:

### Tool implementations

Tools live under `src/redmine_mcp_server/tools/`, one file per Redmine resource; the interactive MCP Apps tools live under `src/redmine_mcp_server/apps/`:

| File | Tools |
|---|---|
| `tools/projects.py` | Project listing, versions, members, roles, modules (10 tools) |
| `tools/issues.py` | Issues, search, copy, delete, relations, watchers, notes, categories, subtasks, private notes (13 tools) |
| `tools/time_tracking.py` | Time entries, activities, bulk import (4 tools) |
| `tools/wiki.py` | Wiki page CRUD + rename (1 tool, 6 actions) |
| `tools/files.py` | File upload/download/delete + attachment URLs (4 tools, plus `cleanup_attachment_files` admin-gated) |
| `tools/enumeration.py` | Trackers, statuses, priorities, users, queries (6 tools) |
| `tools/search.py` | Global search across resources (1 tool) |
| `tools/checklists.py` | RedmineUP Checklists plugin (3 tools, gated) |
| `tools/gantt.py` | Gantt chart composite read tool (1 tool) |
| `tools/products.py` | RedmineUP Products plugin (1 tool, gated) |
| `tools/contacts.py` | RedmineUP CRM plugin (1 tool, gated) |
| `tools/deals.py` | RedmineUP CRM deals (1 tool, gated) |
| `tools/documents.py` | DMSF plugin documents (1 tool with list/get/create/update actions, gated) |
| `tools/meta.py` | Server introspection: `get_mcp_server_info` (1 tool, always available) |
| `apps/triage_board.py` | Interactive Kanban triage board MCP App (2 tools) |
| `apps/project_dashboard.py` | Interactive project dashboard MCP App (2 tools) |

Total: **52 MCP tools** unconditionally registered, **plus 1 admin-gated** (`cleanup_attachment_files`, enabled by `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`) for a maximum of 53.

Each `tools/<resource>.py` also owns its resource-specific serializers (`_X_to_dict` helpers).

### Shared helpers

Cross-cutting utilities live as flat private modules:

| Module | Responsibility |
|---|---|
| `_client.py` | Redmine connection (legacy, `oauth`, and `oauth-proxy`), module-level config, logger |
| `_errors.py` | `_handle_redmine_error`, `_scrub_error_message`, `_READ_ONLY_ERROR` |
| `_validation.py` | Input validators (`_is_positive_int`, `_is_valid_project_id`, `_validate_hours`) |
| `_serialization.py` | `wrap_insecure_content`, `_safe_isoformat`, `_iter_capped`, `_named_ref`, `_coerce_json_safe`, `_normalize_csv_list` |
| `_env.py` | Environment accessors: read-only / plugin flags (`_is_read_only_mode`, `_is_*_enabled`), secret resolution with Docker/Kubernetes `*_FILE` support (`get_secret`, `get_required`, `get_required_secret`), `require_introspection_credentials`, `get_allowed_client_redirect_uris` (oauth-proxy redirect-URI allowlist), `get_health_introspection_ttl_seconds` |
| `_custom_fields.py` | Custom-field parsing, autofill, and update coercion |
| `_ssrf.py` | SSRF protection for `upload_file`'s `source_url` |
| `_cleanup.py` | Background cleanup task |
| `_http_routes.py` | Starlette routes (`/health` with a Doorkeeper introspection probe in `oauth` / `oauth-proxy` modes and a Redmine credential probe in legacy mode, `/files/{id}`, `/cleanup/status`) |
| `_decorators.py` | `@action_dispatch` decorator + `ActionMode` enum |
| `_offload.py` | `@offloaded` decorator and `in_thread()`: run blocking python-redmine work in a worker thread instead of on the event loop |
| `_auth.py` | `RedmineAuthProvider` (a `RemoteAuthProvider` subclass) and its `build_remote_auth()` factory: composes `IntrospectionTokenVerifier` (RFC 7662) and adds the RFC 8414 AS-metadata mirror plus the RFC 7009 `/revoke` route. Used by `oauth` mode. |
| `_oauth_proxy.py` | `build_oauth_proxy()` factory: a FastMCP `OAuthProxy` backed by `IntrospectionTokenVerifier`, proxying `/authorize`, `/token`, and `/revoke` to Doorkeeper with external consent and a loopback-default redirect-URI allowlist. Used by `oauth-proxy` mode. |
| `_mount.py` | Public base-URL helpers (`mcp_base_url`, `mcp_path_for_http_app`, `mcp_mount_prefix`) for serving the authenticated app behind `REDMINE_MCP_BASE_URL`. |
| `_tool_error_middleware.py` | FastMCP middleware that surfaces tool-validation errors with a clean payload. |
| `oauth_scopes.py` | `READ_SCOPES` / `WRITE_SCOPES` inventory + `advertised_scopes()` used by both the protected-resource and AS-metadata discovery documents. |

### Keeping blocking calls off the event loop

python-redmine is synchronous, so any tool that calls it on the event loop
stalls every other request until the call returns, including `/health`
([#216](https://github.com/jztan/redmine-mcp-server/issues/216)). Two rules
follow, and `_get_redmine_client()` enforces them at runtime: it raises if it
is called on the event loop thread.

**Rule 1: if the function has no `await`, make it a plain `def` and decorate it
with `@offloaded`.** This is most tools and every per-action handler.

```python
from .._offload import offloaded

@mcp.tool()
@offloaded
def list_widgets(project_id: int) -> Dict[str, Any]:
    ...
```

**Rule 2: if the function must stay a coroutine because it awaits something,
wrap its synchronous remainder in a nested closure and hand that to
`in_thread()`.**

```python
from .._offload import in_thread

@mcp.tool()
async def get_widget(widget_id: int) -> Dict[str, Any]:
    await _ensure_cleanup_started()

    def _run() -> Dict[str, Any]:
        try:
            widget = _get_redmine_client().widget.get(widget_id)
            return _widget_to_dict(widget)
        except Exception as e:
            return _handle_redmine_error(e, f"fetching widget {widget_id}")

    return await in_thread(_run)
```

Use a nested closure rather than a separate top-level function so parameters
are captured instead of re-declared in a second signature. If the closure
assigns to a name that also exists outside it, add a `nonlocal` for that name,
otherwise Python makes it a closure-local and the read before assignment raises
`UnboundLocalError`.

Move the **whole** synchronous section in one hop, not just the client call.
python-redmine issues its HTTP request on the first iteration of a result set,
not at `.filter()`, and re-fetches on attribute access for a field that was not
included, so iteration and serialization block too.

`tests/test_offload.py` has a static check that fails with the offending file,
line, and function if a blocking call is left on the loop.

### Adding a new `manage_X` tool

The 9 `manage_X` tools (plus `manage_redmine_version`) follow a consistent pattern via the `@action_dispatch` decorator. Example:

```python
from .._decorators import ActionMode, action_dispatch
from .._offload import offloaded

# Per-action handlers (private functions in the same file). They are plain
# `def` carrying @offloaded, so the blocking Redmine work runs in a worker
# thread; action_dispatch awaits them exactly the same way.
@offloaded
def _list_widgets_action(project_id=None, **_):
    # validation, fetch, return
    ...

@offloaded
def _create_widget_action(project_id=None, name=None, **_):
    # validation, create, return
    ...

@mcp.tool()
@action_dispatch({
    "list": ActionMode.READ,
    "create": ActionMode.WRITE,
})
async def manage_widget(action: str, project_id=None, name=None):
    """Docstring with full param/return shape."""
    return {
        "list": _list_widgets_action,
        "create": _create_widget_action,
    }
```

The decorator handles:
- Action validation (returns `{"error": "Invalid action ..."}` on bad input)
- Read-only guard for `WRITE` actions (returns `_READ_ONLY_ERROR` if env enables read-only mode)
- `_ensure_cleanup_started()` for `WRITE` actions
- Routing to the per-action handler

Per-action handlers stay responsible for: their own parameter validation, calling the Redmine API, and wrapping exceptions via `_handle_redmine_error`.

**Important:** keep the public `manage_X` tool's full explicit parameter list (FastMCP rejects `**kwargs` in tool signatures). Only the body changes to return the handler-map dict.

For plugin-gated tools (`manage_product`, `manage_contact`, `manage_deal`), wrap the dispatcher in a feature-flag check:

```python
@mcp.tool()
async def manage_widget(action: str, project_id=None, name=None):
    if not _is_widgets_enabled():
        return dict(_WIDGETS_DISABLED_ERROR)
    return await _manage_widget_dispatch(
        action,
        project_id=project_id,
        name=name,
    )


@action_dispatch({...})
async def _manage_widget_dispatch(action, **kwargs):
    return {...}
```

## Development Workflow

### 1. Create a Branch

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Or a bug fix branch
git checkout -b fix/issue-description
```

### 2. Make Changes

- Write clear, maintainable code
- Follow existing code style and patterns
- Add docstrings to new functions/classes
- Update relevant documentation

### 3. Write Tests

**Test Types:**

- **Unit Tests**: Test individual functions with mocks
- **Integration Tests**: Test with actual Redmine server
- **Security Tests**: Test input validation and security

**Running Tests:**

```bash
# All tests
python tests/run_tests.py --all

# Unit tests only (no external dependencies)
python tests/run_tests.py

# Integration tests (requires Redmine server)
python tests/run_tests.py --integration

# With coverage report
python tests/run_tests.py --coverage
```

**Live CRM Integration Tests:**

`tests/test_crm_integration.py` exercises every REST action the RedmineUP CRM PRO plugin exposes (24 in total, one test each: contacts, contact project links, contact tags, notes, saved queries, deals, deal product lines, deal statuses and deal categories) through the MCP tool functions against a real server. It runs as part of `--integration` and skips itself when `GET /contacts.json` is not 200, so a plain Redmine still passes; the product line test additionally skips without the Products plugin.

The server it targets needs: CRM PRO (deals) and optionally Products installed; the API user's role holding the contact, deal, note and product permissions; the `contacts`, `deals` and `products` modules enabled on the test project; at least one deal status; and a second project the user is a member of (for the contact project association test). Override the defaults with `REDMINE_TEST_PROJECT` (default `testing-project1`) and `REDMINE_TEST_DEAL_STATUS_ID` (default `1`). Every test creates and deletes its own records.

**Live OAuth Integration Tests (v2.1+):**

The unit suite mocks Doorkeeper at the httpx transport boundary. To exercise real Doorkeeper RFC 7662 introspection against a sandbox Redmine:

1. Register an MCP introspection client in the sandbox per `docs/oauth-setup.md` Step 2.
2. Mint a valid bearer for any user-flow OAuth app in the same sandbox.
3. Add the four env vars to your `.env` file:

   ```bash
   REDMINE_URL=https://sandbox-redmine.example.com
   REDMINE_INTROSPECT_CLIENT_ID=...
   REDMINE_INTROSPECT_CLIENT_SECRET=...
   REDMINE_OAUTH_TEST_TOKEN=...
   ```

   The OAuth integration test module calls `load_dotenv()` at import time, so vars in `.env` are picked up automatically — no need to re-export on the command line.

4. Run the full integration suite:

   ```bash
   python tests/run_tests.py --integration
   ```

   …or run just the OAuth subset (needs direct pytest because `run_tests.py` does not forward `-k`):

   ```bash
   python -m pytest tests/test_oauth_integration.py -v -m integration
   ```

If any required env var is missing, the OAuth tests skip with a clear "Live OAuth integration not configured" message — safe to leave in CI.

The destructive `test_revoked_token_rejected` test invalidates the test bearer and is skipped by default. To enable (and lose the bearer):

```bash
RUN_DESTRUCTIVE_TESTS=1 python tests/run_tests.py --integration
```

Re-mint the test bearer through the sandbox's OAuth user-flow before re-running.

**Plugin-gated integration tests:**

Some integration tests need a Redmine plugin installed on the target server, so they are opt-in behind an environment flag and skip with a clear reason otherwise:

| Flag | Plugin | Covers |
|------|--------|--------|
| `REDMINE_AGILE_ENABLED=true` | RedmineUP Agile | `story_points`, `agile_sprint_id`, `agile_position` |
| `REDMINE_TAGS_ENABLED=true` | `additional_tags` | the `tags` array and `tag_list` writes |
| `REDMINE_DRAWIO_ENABLED=true` | `redmine_drawio` | `{{drawio_attach(...)}}` rendering a `.drawio` upload |

The first two are read by the server itself; `REDMINE_DRAWIO_ENABLED` is test-only, since the drawio plugin needs no server-side support (a `.drawio` upload is an ordinary binary attachment). The drawio test asserts against the *rendered* wiki HTML rather than the REST response, because the API returns raw wiki source, which cannot show whether the macro expanded. Set the flag only against a server that has the plugin; without it the test fails rather than skips, which is deliberate: the flag is the opt-in, so a silently broken plugin still surfaces.

```bash
REDMINE_DRAWIO_ENABLED=true python -m pytest tests/test_integration.py -m integration -k drawio
```

**Writing Tests:**

```python
# Example unit test
@pytest.mark.asyncio
async def test_list_projects():
    """Test listing projects with mocked Redmine client."""
    # Test implementation
    pass

# Example integration test
@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_projects_integration():
    """Test listing projects with real Redmine server."""
    # Test implementation
    pass
```

### 4. Code Quality Checks

**PEP 8 Compliance:**

```bash
# Check compliance
uv run flake8 src/ --max-line-length=88

# Auto-format code
uv run black src/ --line-length=88

# Verify formatting without changes
uv run black --check src/
```

**Code Style Guidelines:**

- Maximum line length: 88 characters (Black's default)
- Use type hints where appropriate
- Follow PEP 8 naming conventions
- Write descriptive variable and function names

### 5. Commit Your Changes

**Commit Message Format:**

Follow conventional commits:

```
type: brief description

Detailed explanation (optional)

- List of changes
- Additional context
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `chore`: Maintenance tasks

**Examples:**

```bash
# Feature commit
git commit -m "feat: add support for custom fields in issues"

# Bug fix commit
git commit -m "fix: resolve authentication error with API key"

# Documentation commit
git commit -m "docs: update installation instructions for Python 3.10"
```

**Important:**
- Do NOT include Claude Code attribution in commit messages
- Do NOT append "Generated with [Claude Code]" or "Co-Authored-By: Claude"
- Keep commit messages clean and focused on actual changes

### 6. Push and Create Pull Request

```bash
# Push your branch
git push origin feature/your-feature-name

# Create pull request on GitHub
# Fill in the PR template with:
# - Description of changes
# - Related issue numbers
# - Testing performed
# - Screenshots (if applicable)
```

## Code Guidelines

### Python Style

```python
# Good: Clear function with type hints and docstring
@offloaded
def get_issue(issue_id: int, include_journals: bool = True) -> Dict[str, Any]:
    """
    Retrieve detailed information about a Redmine issue.

    Args:
        issue_id: The ID of the issue to retrieve
        include_journals: Whether to include journal entries

    Returns:
        Dictionary containing issue details

    Raises:
        ValueError: If issue_id is invalid
    """
    # Implementation
    pass
```

### Error Handling

```python
# Good: Proper error handling with user-friendly messages
try:
    issue = redmine.issue.get(issue_id)
    return _issue_to_dict(issue)
except Exception as e:
    return {"error": f"Failed to retrieve issue {issue_id}: {str(e)}"}
```

### MCP Tool Implementation

```python
# Good: MCP tool with clear documentation.
# Plain `def` + @offloaded so the blocking Redmine call runs in a worker
# thread. See "Keeping blocking calls off the event loop" above for the
# case where the tool has to stay a coroutine.
@mcp.tool()
@offloaded
def tool_name(param: str) -> Dict[str, Any]:
    """
    Brief description of what this tool does.

    Args:
        param: Description of parameter

    Returns:
        Description of return value
    """
    # Implementation
    pass
```

## Testing Guidelines

### Test Structure

```python
# tests/test_example.py
import pytest
from unittest.mock import Mock, patch

@pytest.mark.asyncio
async def test_function_success():
    """Test successful execution."""
    # Arrange
    mock_data = {"id": 1, "name": "test"}

    # Act
    result = await function_to_test(mock_data)

    # Assert
    assert result["id"] == 1
    assert result["name"] == "test"

@pytest.mark.asyncio
async def test_function_error():
    """Test error handling."""
    # Test error scenarios
    pass
```

### Test Coverage

- Aim for >80% code coverage
- Test both success and error paths
- Test edge cases and boundary conditions
- Mock external dependencies in unit tests

## Documentation

### Update Documentation When:

- Adding new features or tools
- Changing existing functionality
- Fixing bugs that affect usage
- Adding new configuration options

### Documentation Files:

- `README.md` - Keep concise with references to detailed docs
- `docs/tool-reference.md` - Tool usage details
- `docs/troubleshooting.md` - Common issues and solutions
- `docs/contributing.md` - This file
- `CHANGELOG.md` - Version history

### Documentation Style:

- Use clear, concise language
- Include code examples
- Add links to related documentation
- Keep formatting consistent

## Pull Request Process

### Before Submitting:

1. ✅ All tests pass locally
2. ✅ Code formatted with Black
3. ✅ Flake8 checks pass
4. ✅ Documentation updated
5. ✅ CHANGELOG.md updated (for features/fixes)
6. ✅ Commit messages follow conventions

### PR Template:

GitHub pre-fills new pull requests from
[`.github/PULL_REQUEST_TEMPLATE.md`](../.github/PULL_REQUEST_TEMPLATE.md).
Fill in the Summary, Changes, and Testing sections and work through its
checklist (tests, formatting, CHANGELOG, docs, no manual version bumps,
and both deployment methods verified).

### Review Process:

1. Automated checks run (CI/CD)
2. Maintainer reviews code
3. Address review feedback
4. Approval and merge

## Deployment Compatibility

**Important:** All solutions must work with both deployment methods:

### Local Python Execution
```bash
uv run python -m redmine_mcp_server.main
```
- Uses `.env` for configuration
- For development and debugging

### Docker Deployment
```bash
docker-compose up
```
- Uses `.env.docker` for configuration
- For production deployments

**Always test both deployment methods before submitting!**

## Release Process

Releases are driven entirely by `scripts/release.py`. The script owns every
version-touching action (`pyproject.toml`, `server.json`, `uv.lock`,
`CHANGELOG.md`), the gitflow ceremony, tagging, the GitHub release, and the
MCP Registry publish. **Never bump versions by hand**; contributors only add
entries under `## [Unreleased]` in `CHANGELOG.md`.

See [RELEASE_SOP.md](../RELEASE_SOP.md) for complete release procedures.

## Community Guidelines

### Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](../CODE_OF_CONDUCT.md).
In short:

- Be respectful and professional
- Welcome newcomers
- Provide constructive feedback
- Focus on the issue, not the person

### Communication

- **GitHub Issues**: Bug reports and feature requests
- **Pull Requests**: Code contributions
- **Discussions**: General questions and ideas
- **Security issues**: Report privately via GitHub Security Advisories, see [SECURITY.md](../SECURITY.md)

### Getting Help

- Check [documentation](../README.md)
- Search existing issues
- Review [troubleshooting guide](./troubleshooting.md)
- Ask in GitHub Discussions

## Architecture Overview

### Project Structure

```
redmine-mcp-server/
├── src/redmine_mcp_server/
│   ├── main.py              # Entry point; build_authenticated_app() mounts the MCP app + discovery routes (oauth / oauth-proxy)
│   ├── server.py            # Owns the shared `mcp = FastMCP(...)` instance; _select_auth_provider() picks the auth provider
│   ├── tools/               # 14 per-resource tool modules (52 MCP tools + 1 admin-gated)
│   ├── apps/                # Interactive MCP Apps: triage board + project dashboard (4 tools)
│   ├── _auth.py             # RedmineAuthProvider (introspection + AS-metadata + revoke), oauth mode
│   ├── _oauth_proxy.py      # OAuthProxy factory (DCR + authorize/token/revoke proxy), oauth-proxy mode
│   ├── _mount.py            # Public base-URL / MCP-path / mount-prefix helpers
│   ├── _client.py           # Redmine connection (legacy singleton; per-request bearer for oauth / oauth-proxy)
│   ├── _errors.py           # Exception → user-friendly dict
│   ├── _validation.py       # Input validators
│   ├── _serialization.py    # Serializer helpers + `wrap_insecure_content`
│   ├── _env.py              # Environment-flag accessors
│   ├── _custom_fields.py    # Custom-field parsing/coercion
│   ├── _ssrf.py             # SSRF protection for upload_file source_url
│   ├── _cleanup.py          # Background attachment cleanup task
│   ├── _http_routes.py      # Starlette routes (/health w/ introspection + legacy redmine probe, /files, /cleanup/status)
│   ├── _decorators.py       # `@action_dispatch` decorator + `ActionMode` enum
│   ├── _offload.py          # `@offloaded` / `in_thread()`: keep blocking calls off the event loop
│   ├── _tool_error_middleware.py  # FastMCP middleware that normalizes tool validation errors
│   ├── oauth_scopes.py      # READ_SCOPES / WRITE_SCOPES inventory + advertised_scopes()
│   └── file_manager.py      # Attachment file storage manager
├── tests/                   # Comprehensive test suite
├── docs/                    # Documentation
│   ├── tool-reference.md    # Tool usage documentation
│   ├── troubleshooting.md   # Troubleshooting guide
│   ├── oauth-setup.md       # OAuth2 multi-tenant setup walkthrough
│   └── contributing.md      # This file
├── .env.example            # Environment configuration template
├── Dockerfile              # Container configuration
├── docker-compose.yml      # Multi-container setup
└── pyproject.toml         # Project configuration
```

### Core Components

- **`main.py`**: Entry point. In an authenticated mode (`oauth` or `oauth-proxy`), `build_authenticated_app()` mounts the FastMCP app under the `REDMINE_MCP_BASE_URL` path prefix and adds the provider's `get_well_known_routes()` (discovery) plus `/health`, `/files`, `/cleanup/status`; in legacy mode it returns `mcp.http_app(stateless_http=True)`. Tool registration is triggered via `from . import tools`. No Starlette middleware is added; auth lives inside FastMCP via the `auth=` constructor parameter.
- **`server.py`**: Owns the shared `mcp = FastMCP("redmine_mcp_tools", auth=...)` instance imported by every tool module. `_select_auth_provider(auth_mode)` returns `build_remote_auth()` (a `RedmineAuthProvider`) for `oauth`, `build_oauth_proxy()` (a FastMCP `OAuthProxy`) for `oauth-proxy`, and `None` for legacy.
- **`_auth.py`** (`oauth` mode): `build_remote_auth()` returns a `RedmineAuthProvider`, a `RemoteAuthProvider` subclass that composes `IntrospectionTokenVerifier` (RFC 7662 against Doorkeeper's `/oauth/introspect`) and additionally serves the RFC 8414 AS-metadata mirror and the RFC 7009 `/revoke` route. Reads `REDMINE_INTROSPECT_CLIENT_ID` / `_SECRET` via `_env.require_introspection_credentials()` (fail-fast on startup).
- **`_oauth_proxy.py`** (`oauth-proxy` mode): `build_oauth_proxy()` returns a FastMCP `OAuthProxy` that makes the MCP server the OAuth authorization server for clients (DCR + `/authorize` / `/token` / `/register`) and proxies upstream to Redmine/Doorkeeper, validating tokens with the same `IntrospectionTokenVerifier`. Keeps consent external (`require_authorization_consent="external"`), requires `REDMINE_MCP_JWT_SIGNING_KEY`, and restricts client redirect URIs to loopback by default (`get_allowed_client_redirect_uris()`).
- **`tools/`**: Per-resource tool modules. Each file owns its `@mcp.tool()` definitions and resource-specific serializers (`_X_to_dict` helpers). See [Where things live](#where-things-live) earlier in this guide for the full table.
- **Flat `_X.py` modules**: Cross-cutting helpers (`_client`, `_errors`, `_validation`, `_serialization`, `_env`, `_custom_fields`, `_ssrf`, `_cleanup`, `_http_routes`, `_decorators`, `_auth`, `_oauth_proxy`, `_mount`, `_tool_error_middleware`). See [Where things live](#where-things-live) for responsibilities.
- **`_client.py`**: In `oauth` and `oauth-proxy` modes, builds a per-request `Redmine(...)` from the bearer returned by `fastmcp.server.dependencies.get_access_token()`. In legacy mode, caches a singleton built from `REDMINE_API_KEY` or `REDMINE_USERNAME`/`REDMINE_PASSWORD`. (Pre-v2.1: validated tokens via `GET /users/current.json` through a custom `ContextVar`-based middleware; both removed in the v2.1 native-auth migration.)
- **`oauth_scopes.py`**: Single source of truth for `scopes_supported` in the protected-resource and AS-metadata discovery documents. Filters `WRITE_SCOPES` out when `REDMINE_MCP_READ_ONLY=true`, appends the agile read scope (`view_agile_queries`) when `REDMINE_AGILE_ENABLED=true`, and the tags scopes when `REDMINE_TAGS_ENABLED=true` — `view_issue_tags` (read) always, plus `create_issue_tags`/`edit_issue_tags` (write) unless read-only.
- **`file_manager.py`**: Attachment file storage manager (UUID-based files + metadata.json with expiry).

This layout was introduced in v2.0 (replacing the previous monolithic `redmine_handler.py`), updated in v2.1 (auth moved from `oauth_middleware.py` to native FastMCP `auth=` via `_auth.py`), and extended in v2.3 with the `oauth-proxy` mode (`_oauth_proxy.py`, `_mount.py`, and the `RemoteAuthProvider` → `RedmineAuthProvider` refactor).

### Key Technologies

- **FastMCP**: MCP protocol implementation with HTTP transport
- **python-redmine**: Official Redmine Python library
- **Starlette**: ASGI HTTP framework
- **uvicorn**: ASGI server

### Design Patterns

- Async/await for non-blocking operations
- Error handling with user-friendly error dictionaries
- Per-resource serializer helpers (`_issue_to_dict`, `_project_to_dict`, etc.)
- `@action_dispatch` decorator for `manage_X` tools (action validation, read-only guard, cleanup hook)
- Environment-based configuration with `.env` files

## Adding New Tools

To add a new MCP tool to the server:

1. **Pick the right `tools/<resource>.py` file** (or create a new one if the resource doesn't fit any existing module). See [Where things live](#where-things-live) for the file/resource mapping.

2. **Define the tool** in that file:

   ```python
   from ..server import mcp
   from .._errors import _handle_redmine_error
   from .._offload import offloaded

   @mcp.tool()
   @offloaded
   def your_new_tool(param: str) -> Dict[str, Any]:
       """
       Brief description of what this tool does.

       Args:
           param: Description of the parameter

       Returns:
           Dictionary with results or error information
       """
       try:
           # Your implementation here
           result = perform_operation(param)
           return {"success": True, "data": result}
       except Exception as e:
           return _handle_redmine_error(e, "your_new_tool")
   ```

3. **The tool is automatically registered** — FastMCP discovers tools decorated with `@mcp.tool()` once the module is imported. New `tools/<resource>.py` files must be imported from `tools/__init__.py`.

4. **For `manage_X`-style tools** (multi-action CRUD), use the `@action_dispatch` decorator. See [Adding a new `manage_X` tool](#adding-a-new-manage_x-tool) earlier in this guide.

5. **Test your tool**:
   - Add unit tests in `tests/test_<resource>_tools.py` (or the matching existing file)
   - Add integration tests if it interacts with Redmine
   - Run tests: `python tests/run_tests.py --all`

6. **Document your tool**:
   - Add entry to `docs/tool-reference.md`
   - Include parameters, returns, and examples
   - Update README tool count if needed

## Questions?

- Open an issue for questions
- Check existing documentation
- Review similar contributions
- Ask maintainers for guidance

Thank you for contributing to Redmine MCP Server! 🎉
