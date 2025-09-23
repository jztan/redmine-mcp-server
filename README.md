# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

**mcp-name: io.github.jztan/redmine-mcp-server**

## Features

- **Redmine Integration**: List projects, view/create/update issues, download attachments
- **HTTP File Serving**: Secure file access via UUID-based URLs with automatic expiry
- **MCP Compliant**: Full Model Context Protocol support with FastMCP and streamable HTTP transport
- **Flexible Authentication**: Username/password or API key
- **File Management**: Automatic cleanup of expired files with storage statistics
- **Docker Ready**: Complete containerization support
- **Comprehensive Testing**: Unit, integration, and connection tests

## Installation

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Access to a Redmine instance

### Quick Start

```bash
# Clone and setup
git clone https://github.com/jztan/redmine-mcp-server
cd redmine-mcp-server

# Install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your Redmine settings

# Run the server
uv run python -m redmine_mcp_server.main
```

The server runs on `http://localhost:8000` with the MCP endpoint at `/mcp`, health check at `/health`, and file serving at `/files/{file_id}`.

### Configuration

Edit your `.env` file with the following settings:

```env
# Required: Redmine connection
REDMINE_URL=https://your-redmine-server.com

# Authentication (choose one)
REDMINE_USERNAME=your_username
REDMINE_PASSWORD=your_password
# OR
# REDMINE_API_KEY=your_api_key

# Optional: Server settings
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Optional: File management
ATTACHMENTS_DIR=./attachments
AUTO_CLEANUP_ENABLED=true
CLEANUP_INTERVAL_MINUTES=10
ATTACHMENT_EXPIRES_MINUTES=60
```

### File Management Configuration

- **`ATTACHMENTS_DIR`**: Directory where downloaded attachments are stored (default: `./attachments`)
- **`AUTO_CLEANUP_ENABLED`**: Enable automatic cleanup of expired files (default: `true`)
- **`CLEANUP_INTERVAL_MINUTES`**: How often cleanup runs to check for expired files (default: `10` minutes)
- **`ATTACHMENT_EXPIRES_MINUTES`**: Default expiry time for downloaded attachments (default: `60` minutes)

**Example configurations:**
```bash
# Quick cleanup for development/testing
CLEANUP_INTERVAL_MINUTES=1
ATTACHMENT_EXPIRES_MINUTES=5

# Production settings
CLEANUP_INTERVAL_MINUTES=30
ATTACHMENT_EXPIRES_MINUTES=120
```

**Note:** API key authentication is preferred for security.

## Usage

### Running the Server

```bash
uv run python -m redmine_mcp_server.main
```

The same command is used for both development and production. Configure environment-specific settings in your `.env` file.

### MCP Client Configuration

#### Claude Code

Add to Claude Code using the CLI command:

```bash
claude mcp add --transport http redmine http://127.0.0.1:8000/mcp
```

Or configure manually in your Claude Code (~/.claude.json):

```json
{
  "mcpServers": {
    "my-local-server": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

#### Other MCP Clients

Configure your MCP client (e.g., VS Code settings.json):

```json
{
  "mcp": {
    "servers": {
      "redmine": {
        "url": "http://127.0.0.1:8000/mcp"
      }
    }
  }
}
```

### Testing Your Setup

```bash
# Test Redmine connection
python tests/test_connection.py

# Run full test suite
python tests/run_tests.py --all
```

## Available Tools

This MCP server provides the following tools for interacting with your Redmine instance:

### Project Management

#### `list_redmine_projects`
Lists all accessible projects in the Redmine instance.

**Parameters:** None

**Returns:** List of project dictionaries with id, name, identifier, and description

#### `summarize_project_status`
Provide a comprehensive summary of project status based on issue activity over a specified time period.

**Parameters:**
- `project_id` (integer, required): The ID of the project to summarize
- `days` (integer, optional): Number of days to analyze. Default: `30`

**Returns:** Comprehensive project status summary including:
- Recent activity metrics (issues created/updated)
- Status, priority, and assignee breakdowns
- Project totals and overall statistics
- Activity insights and trends

---

### Issue Operations

#### `get_redmine_issue`
Retrieve detailed information about a specific Redmine issue.

**Parameters:**
- `issue_id` (integer, required): The ID of the issue to retrieve
- `include_journals` (boolean, optional): Include journals (comments) in result. Default: `true`
- `include_attachments` (boolean, optional): Include attachments metadata. Default: `true`

**Returns:** Issue dictionary with details, journals, and attachments

#### `list_my_redmine_issues`
Lists issues assigned to the authenticated user.

**Parameters:**
- `**filters` (optional): Additional query parameters (e.g., `status_id`, `project_id`)

**Returns:** List of issue dictionaries assigned to current user

#### `search_redmine_issues`
Search issues using text queries.

**Parameters:**
- `query` (string, required): Text to search for in issues
- `**options` (optional): Additional search options passed to Redmine API

**Returns:** List of matching issue dictionaries

#### `create_redmine_issue`
Creates a new issue in the specified project.

**Parameters:**
- `project_id` (integer, required): Target project ID
- `subject` (string, required): Issue subject/title
- `description` (string, optional): Issue description. Default: `""`
- `**fields` (optional): Additional Redmine fields (e.g., `priority_id`, `assigned_to_id`)

**Returns:** Created issue dictionary

#### `update_redmine_issue`
Updates an existing issue with the provided fields.

**Parameters:**
- `issue_id` (integer, required): ID of the issue to update
- `fields` (object, required): Dictionary of fields to update

**Returns:** Updated issue dictionary

**Note:** You can use either `status_id` or `status_name` in fields. When `status_name` is provided, the tool automatically resolves the corresponding status ID.

---

### File Operations

#### `get_redmine_attachment_download_url(attachment_id)`
Get an HTTP download URL for a Redmine attachment. The attachment is downloaded to server storage and a time-limited URL is returned for client access.

**Parameters:**
- `attachment_id` (int): The ID of the attachment to download

**Returns:**
```json
{
    "download_url": "http://localhost:8000/files/12345678-1234-5678-9abc-123456789012",
    "filename": "document.pdf",
    "content_type": "application/pdf",
    "size": 1024,
    "expires_at": "2025-09-22T10:30:00Z",
    "attachment_id": 123
}
```

**Security Features:**
- Server-controlled storage location and expiry policy
- UUID-based filenames prevent path traversal attacks
- No client control over server configuration

#### `download_redmine_attachment(attachment_id, save_dir, expires_hours)` ⚠️ DEPRECATED
**DEPRECATED:** This function will be removed in v0.5.0. Use `get_redmine_attachment_download_url()` instead.

**Security Warning:** The `save_dir` parameter is vulnerable to path traversal attacks. The `expires_hours` parameter inappropriately exposes server policies to clients.

#### `cleanup_attachment_files`
Removes expired attachment files and provides cleanup statistics.

**Parameters:** None

**Returns:** Cleanup statistics:
- `cleaned_files`: Number of files removed
- `cleaned_bytes`: Total bytes cleaned up
- `cleaned_mb`: Total megabytes cleaned up (rounded)


## Docker Deployment

### Quick Start with Docker

```bash
# Configure environment
cp .env.example .env.docker
# Edit .env.docker with your Redmine settings

# Run with docker-compose
docker-compose up --build

# Or run directly
docker build -t redmine-mcp-server .
docker run -p 8000:8000 --env-file .env.docker redmine-mcp-server
```

### Production Deployment

Use the automated deployment script:

```bash
chmod +x deploy.sh
./deploy.sh
```

## Development

### Architecture

The server is built using:
- **FastMCP**: Model Context Protocol implementation with streamable HTTP transport
- **python-redmine**: Official Redmine Python library

### Project Structure

```
redmine-mcp-server/
├── src/redmine_mcp_server/
│   ├── main.py              # FastMCP application entry point
│   ├── redmine_handler.py   # MCP tools and Redmine integration
│   └── file_manager.py      # Attachment file management and cleanup
├── tests/                   # Comprehensive test suite
├── .env.example            # Environment configuration template
├── Dockerfile              # Container configuration
├── docker-compose.yml      # Multi-container setup
├── deploy.sh              # Deployment automation
└── pyproject.toml         # Project configuration
```

### Adding New Tools

Add your tool function to `src/redmine_mcp_server/redmine_handler.py`:

```python
@mcp.tool()
async def your_new_tool(param: str) -> Dict[str, Any]:
    """Tool description"""
    # Implementation here
    return {"result": "data"}
```

The tool will automatically be available through the MCP interface.

### Testing

The project includes unit tests, integration tests, and connection validation.

**Run tests:**
```bash
# Install test dependencies
uv pip install -e .[test]
```
```bash
# All tests
python tests/run_tests.py --all

# Unit tests only (default)
python tests/run_tests.py

# Integration tests (requires Redmine connection)
python tests/run_tests.py --integration

# With coverage report
python tests/run_tests.py --coverage
```

**Test Requirements:**
- Unit tests: No external dependencies (use mocks)
- Integration tests: Require valid Redmine server connection

## Troubleshooting

### Common Issues

1. **Connection refused**: Verify your `REDMINE_URL` and network connectivity
2. **Authentication failed**: Check your credentials in `.env`
3. **Import errors**: Ensure dependencies are installed: `uv pip install -e .`
4. **Port conflicts**: Modify `SERVER_PORT` in `.env` if port 8000 is in use

### Debug Mode

Enable debug logging by setting `mcp.settings.debug = True` in `main.py`.

## Contributing

Contributions are welcome! Please:

```bash
# Install development dependencies (for code quality and testing)
uv pip install -e .[dev]
```

1. Open an issue for discussion
2. Run the full test suite: `python tests/run_tests.py --all`
3. Run code quality checks:
   ```bash
   # PEP 8 compliance check
   uv run flake8 src/ --max-line-length=88

   # Auto-format code
   uv run black src/ --line-length=88

   # Check formatting without making changes
   uv run black --check src/
   ```
4. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Additional Resources

- [CHANGELOG](CHANGELOG.md) - Detailed version history
- [Roadmap](./roadmap.md) - Future development plans
