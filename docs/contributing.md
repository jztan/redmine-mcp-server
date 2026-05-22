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

Tools live under `src/redmine_mcp_server/tools/`, one file per Redmine resource:

| File | Tools |
|---|---|
| `tools/projects.py` | Project listing, versions, members, roles, modules (9 tools) |
| `tools/issues.py` | Issues, search, copy, delete, relations, watchers, notes, categories, subtasks, private notes (13 tools) |
| `tools/time_tracking.py` | Time entries, activities, bulk import (4 tools) |
| `tools/wiki.py` | Wiki page CRUD + rename (1 tool, 6 actions) |
| `tools/files.py` | File upload/download/delete + attachment URLs (4 tools, plus `cleanup_attachment_files` admin-gated) |
| `tools/enumeration.py` | Trackers, statuses, priorities, users, queries (6 tools) |
| `tools/search.py` | Global search across resources (1 tool) |
| `tools/checklists.py` | RedmineUP Checklists plugin (2 tools, gated) |
| `tools/gantt.py` | Gantt chart composite read tool (1 tool) |
| `tools/products.py` | RedmineUP Products plugin (1 tool, gated) |
| `tools/contacts.py` | RedmineUP CRM plugin (1 tool, gated) |
| `tools/documents.py` | DMSF plugin documents (1 tool with list/get/create/update actions, gated) |
| `tools/meta.py` | Server introspection: `get_mcp_server_info` (1 tool, always available) |

Total: **45 MCP tools** unconditionally registered, **plus 1 admin-gated** (`cleanup_attachment_files`, enabled by `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`) for a maximum of 46.

Each `tools/<resource>.py` also owns its resource-specific serializers (`_X_to_dict` helpers).

### Shared helpers

Cross-cutting utilities live as flat private modules:

| Module | Responsibility |
|---|---|
| `_client.py` | Redmine connection (legacy + OAuth), module-level config, logger |
| `_errors.py` | `_handle_redmine_error`, `_scrub_error_message`, `_READ_ONLY_ERROR` |
| `_validation.py` | Input validators (`_is_positive_int`, `_is_valid_project_id`, `_validate_hours`) |
| `_serialization.py` | `wrap_insecure_content`, `_safe_isoformat`, `_iter_capped`, `_named_ref`, `_coerce_json_safe` |
| `_env.py` | Environment-flag accessors (`_is_read_only_mode`, `_is_*_enabled`, `require_introspection_credentials`, `get_health_introspection_ttl_seconds`) |
| `_custom_fields.py` | Custom-field parsing, autofill, and update coercion |
| `_ssrf.py` | SSRF protection for `upload_file`'s `source_url` |
| `_cleanup.py` | Background cleanup task |
| `_http_routes.py` | Starlette routes (`/health` with Doorkeeper introspection probe, `/files/{id}`, `/cleanup/status`) |
| `_decorators.py` | `@action_dispatch` decorator + `ActionMode` enum |
| `_auth.py` | `build_remote_auth()` factory: composes `IntrospectionTokenVerifier` (RFC 7662) into a `RemoteAuthProvider` for FastMCP v3 native auth (OAuth mode only). |
| `_tool_error_middleware.py` | FastMCP middleware that surfaces tool-validation errors with a clean payload. |
| `oauth_scopes.py` | `READ_SCOPES` / `WRITE_SCOPES` inventory + `advertised_scopes()` used by both the protected-resource and AS-metadata discovery documents. |

### Adding a new `manage_X` tool

The 9 `manage_X` tools (plus `manage_redmine_version`) follow a consistent pattern via the `@action_dispatch` decorator. Example:

```python
from .._decorators import ActionMode, action_dispatch

# Per-action handlers (private async functions in the same file)
async def _list_widgets_action(project_id=None, **_):
    # validation, fetch, return
    ...

async def _create_widget_action(project_id=None, name=None, **_):
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

For plugin-gated tools (`manage_product`, `manage_contact`), wrap the dispatcher in a feature-flag check:

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
async def get_issue(issue_id: int, include_journals: bool = True) -> Dict[str, Any]:
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
# Good: MCP tool with clear documentation
@mcp.tool()
async def tool_name(param: str) -> Dict[str, Any]:
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

```markdown
## Description
Brief description of changes

## Related Issue
Fixes #123

## Changes Made
- List of changes
- Additional context

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] CHANGELOG updated
```

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

Maintainers follow this process for releases:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Update `server.json`
4. Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
5. Push tag: `git push origin vX.Y.Z`
6. GitHub Actions automatically publishes to PyPI
7. Create GitHub Release with notes

See [RELEASE_SOP.md](../RELEASE_SOP.md) for complete release procedures.

## Community Guidelines

### Code of Conduct

- Be respectful and professional
- Welcome newcomers
- Provide constructive feedback
- Focus on the issue, not the person

### Communication

- **GitHub Issues**: Bug reports and feature requests
- **Pull Requests**: Code contributions
- **Discussions**: General questions and ideas

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
│   ├── main.py              # FastMCP entry point + OAuth discovery custom_routes
│   ├── server.py            # Owns the shared `mcp = FastMCP(...)` instance with native auth wiring
│   ├── tools/               # 13 per-resource tool modules (45 MCP tools + 1 admin-gated)
│   ├── _auth.py             # RemoteAuthProvider + IntrospectionTokenVerifier factory (OAuth mode)
│   ├── _client.py           # Redmine connection (legacy + OAuth per-request via get_access_token())
│   ├── _errors.py           # Exception → user-friendly dict
│   ├── _validation.py       # Input validators
│   ├── _serialization.py    # Serializer helpers + `wrap_insecure_content`
│   ├── _env.py              # Environment-flag accessors
│   ├── _custom_fields.py    # Custom-field parsing/coercion
│   ├── _ssrf.py             # SSRF protection for upload_file source_url
│   ├── _cleanup.py          # Background attachment cleanup task
│   ├── _http_routes.py      # Starlette routes (/health w/ introspection probe, /files, /cleanup/status)
│   ├── _decorators.py       # `@action_dispatch` decorator + `ActionMode` enum
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

- **`main.py`**: Entry point. Builds the Starlette app via `mcp.http_app()`, registers OAuth discovery + `/revoke` `custom_route` handlers (when `REDMINE_AUTH_MODE=oauth`), and triggers tool registration via `from . import tools`. No Starlette middleware is added — auth lives inside FastMCP via the `auth=` constructor parameter.
- **`server.py`**: Owns the shared `mcp = FastMCP("redmine_mcp_tools", auth=...)` instance imported by every tool module. The `_select_auth_provider(auth_mode)` helper returns `RemoteAuthProvider(...)` in OAuth mode and `None` in legacy mode.
- **`_auth.py`**: Builds the FastMCP v3 native auth provider. `build_remote_auth()` returns a `RemoteAuthProvider` composed of `IntrospectionTokenVerifier` (RFC 7662 against Doorkeeper's `/oauth/introspect`) plus advertised scopes from `oauth_scopes.py`. Reads `REDMINE_INTROSPECT_CLIENT_ID` / `_SECRET` via `_env.require_introspection_credentials()` (fail-fast on startup).
- **`tools/`**: Per-resource tool modules. Each file owns its `@mcp.tool()` definitions and resource-specific serializers (`_X_to_dict` helpers). See [Where things live](#where-things-live) earlier in this guide for the full table.
- **Flat `_X.py` modules**: Cross-cutting helpers (`_client`, `_errors`, `_validation`, `_serialization`, `_env`, `_custom_fields`, `_ssrf`, `_cleanup`, `_http_routes`, `_decorators`, `_auth`, `_tool_error_middleware`). See [Where things live](#where-things-live) for responsibilities.
- **`_client.py`**: In OAuth mode, builds a per-request `Redmine(...)` from the bearer returned by `fastmcp.server.dependencies.get_access_token()`. In legacy mode, caches a singleton built from `REDMINE_API_KEY` or `REDMINE_USERNAME`/`REDMINE_PASSWORD`. (Pre-v2.1: validated tokens via `GET /users/current.json` through a custom `ContextVar`-based middleware; both removed in the v2.1 native-auth migration.)
- **`oauth_scopes.py`**: Single source of truth for `scopes_supported` in the protected-resource and AS-metadata discovery documents. Filters `WRITE_SCOPES` out when `REDMINE_MCP_READ_ONLY=true`.
- **`file_manager.py`**: Attachment file storage manager (UUID-based files + metadata.json with expiry).

This layout was introduced in v2.0 (replacing the previous monolithic `redmine_handler.py`) and updated in v2.1 (auth moved from `oauth_middleware.py` to native FastMCP `auth=` via `_auth.py`).

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

   @mcp.tool()
   async def your_new_tool(param: str) -> Dict[str, Any]:
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
