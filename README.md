# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

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

# Install test dependencies (optional)
uv pip install -e .[test]

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
CLEANUP_INTERVAL_HOURS=1
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

#### `download_redmine_attachment`
Downloads a file attached to a Redmine issue and provides HTTP access via secure URLs.

**Parameters:**
- `attachment_id` (integer, required): The ID of the attachment to download
- `save_dir` (string, optional): Directory to save the file. Default: `"attachments"`
- `expires_hours` (integer, optional): File expiry time in hours. Default: `24`

**Returns:** Dictionary with download details:
- `download_url`: HTTP URL for accessing the file (`/files/{uuid}`)
- `filename`: Original filename
- `content_type`: MIME type of the file
- `size`: File size in bytes
- `expires_at`: ISO timestamp when file expires
- `attachment_id`: Original attachment ID

**Example Response:**
```json
{
  "download_url": "http://localhost:8000/files/550e8400-e29b-41d4-a716-446655440000",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size": 1024,
  "expires_at": "2025-09-21T08:00:00Z",
  "attachment_id": 123
}
```

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

1. Open an issue for discussion
2. Run the full test suite: `python tests/run_tests.py --all`
3. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Additional Resources

- [CHANGELOG](CHANGELOG.md) - Detailed version history
- [Roadmap](./roadmap.md) - Future development plans
