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
- `CLAUDE.md` - Development guidance

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
│   ├── main.py              # FastMCP application entry point
│   ├── redmine_handler.py   # MCP tools and Redmine integration
│   └── file_manager.py      # Attachment file management and cleanup
├── tests/                   # Comprehensive test suite
├── docs/                    # Documentation
│   ├── tool-reference.md    # Tool usage documentation
│   ├── troubleshooting.md   # Troubleshooting guide
│   └── contributing.md      # This file
├── .env.example            # Environment configuration template
├── Dockerfile              # Container configuration
├── docker-compose.yml      # Multi-container setup
├── deploy.sh              # Deployment automation
└── pyproject.toml         # Project configuration
```

### Core Components

- **main.py**: FastMCP application entry point with HTTP server
- **redmine_handler.py**: MCP tools implementation using python-redmine
- **file_manager.py**: Attachment file management and cleanup utilities

### Key Technologies

- **FastMCP**: MCP protocol implementation with streamable HTTP transport
- **python-redmine**: Official Redmine Python library
- **FastAPI**: HTTP server framework
- **uvicorn**: ASGI server

### Design Patterns

- Async/await for non-blocking operations
- Error handling with user-friendly error dictionaries
- Helper functions for data conversion (_issue_to_dict, etc.)
- Environment-based configuration with .env files

## Adding New Tools

To add a new MCP tool to the server:

1. **Define the tool** in `src/redmine_mcp_server/redmine_handler.py`:

   ```python
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
           return {"error": f"Failed to execute tool: {str(e)}"}
   ```

2. **The tool is automatically registered** - FastMCP discovers tools decorated with `@mcp.tool()`

3. **Test your tool**:
   - Add unit tests in `tests/test_redmine_handler.py`
   - Add integration tests if it interacts with Redmine
   - Run tests: `python tests/run_tests.py --all`

4. **Document your tool**:
   - Add entry to `docs/tool-reference.md`
   - Include parameters, returns, and examples
   - Update README tool count if needed

## Questions?

- Open an issue for questions
- Check existing documentation
- Review similar contributions
- Ask maintainers for guidance

Thank you for contributing to Redmine MCP Server! 🎉
