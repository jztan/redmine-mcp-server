# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

## Features

- **Redmine Integration**: List projects, view/create/update issues
- **MCP Compliant**: Full Model Context Protocol support with FastAPI and Server-Sent Events
- **Flexible Authentication**: Username/password or API key
- **Docker Ready**: Complete containerization support
- **Comprehensive Testing**: Unit, integration, and connection tests

## Quick Start

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
uv run fastapi dev src/redmine_mcp_server/main.py
```

The server runs on `http://localhost:8000` with the MCP endpoint at `/sse`.
For container orchestration, a lightweight health check is available at `/health`.

## Installation

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Access to a Redmine instance

### Configuration

Create and edit your environment configuration:

```bash
cp .env.example .env
```

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
```

**Note:** API key authentication is preferred for security.

## Usage

### Running the Server

```bash
# Development mode (auto-reload)
uv run fastapi dev src/redmine_mcp_server/main.py

# Production mode
uv run python src/redmine_mcp_server/main.py
```

### MCP Client Configuration

Configure your MCP client (e.g., VS Code settings.json):

```json
{
  "mcp": {
    "servers": {
      "redmine": {
        "url": "http://127.0.0.1:8000/sse"
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

## Available MCP Tools

### `get_redmine_issue(issue_id: int, include_journals: bool = True, include_attachments: bool = True)`
Retrieves detailed information about a specific Redmine issue. When
`include_journals` is `True` (default) the returned dictionary also contains a
`"journals"` key with the issue's comments. Set `include_journals=False` to skip
fetching comments for a lighter request. With `include_attachments=True` (the
default) the result includes an `"attachments"` list describing attached files.
Set `include_attachments=False` to omit this metadata.

### `list_redmine_projects()`
Lists all accessible projects in the Redmine instance.

### `list_my_redmine_issues(**filters)`
Lists issues assigned to the authenticated user. Uses the Redmine filter `assigned_to_id="me"`. Additional query parameters can be supplied as keyword arguments.

### `create_redmine_issue(project_id: int, subject: str, description: str = "", **fields)`
Creates a new issue in the specified project. Additional Redmine fields such as `priority_id` can be passed as keyword arguments.

### `update_redmine_issue(issue_id: int, fields: Dict[str, Any])`
Updates an existing issue with the provided fields.

You may supply either ``status_id`` or ``status_name`` to change the issue
status. When ``status_name`` is given the tool resolves the corresponding
identifier automatically.

### `download_redmine_attachment(attachment_id: int, save_dir: str = '.')`
Downloads a file attached to a Redmine issue. Returns the local path of the
saved file.


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
- **FastAPI**: Modern web framework with automatic OpenAPI documentation
- **FastMCP**: Model Context Protocol implementation
- **python-redmine**: Official Redmine Python library
- **Server-Sent Events (SSE)**: Real-time communication transport

### Project Structure

```
redmine-mcp-server/
├── src/redmine_mcp_server/
│   ├── main.py              # FastAPI application entry point
│   └── redmine_handler.py   # MCP tools and Redmine integration
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

Enable debug logging by modifying the FastAPI app initialization in `main.py`.

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
