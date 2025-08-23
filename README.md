# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/mcp-redmine.svg)](https://pypi.org/project/mcp-redmine/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

**Now with dual transport support:** Choose between Server-Sent Events (SSE) for traditional MCP clients or HTTP for AWS AgentCore and cloud deployments.

## Features

- **Redmine Integration**: List projects, view/create/update issues, project status summaries
- **Dual Transport Modes**: 
  - **SSE Mode**: Traditional MCP with Server-Sent Events for desktop clients
  - **AWS AgentCore Mode**: HTTP-based for cloud platforms and AWS AgentCore integration
- **MCP Compliant**: Full Model Context Protocol support
- **Flexible Authentication**: Username/password or API key
- **Production Ready**: Health checks, monitoring, and cloud deployment support
- **Docker Ready**: Complete containerization for both transport modes
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

# Run the server (SSE mode - traditional MCP)
uv run fastapi dev src/redmine_mcp_server/main.py

# Or run AWS AgentCore mode (HTTP-based)
uv run python src/redmine_mcp_server/agentcore_server.py
```

**SSE Mode:** Server runs on `http://localhost:8000` with MCP endpoint at `/sse`
**AWS AgentCore Mode:** Server runs on `http://localhost:8000` with MCP endpoint at `/mcp`

Both modes include health checks at `/health` for monitoring and container orchestration.

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
```

**Note:** API key authentication is preferred for security.

## Usage

### Running the Server

#### SSE Mode (Traditional MCP)

```bash
# Development mode (auto-reload)
uv run fastapi dev src/redmine_mcp_server/main.py

# Production mode
uv run python src/redmine_mcp_server/main.py
```

#### AWS AgentCore Mode (HTTP-based)

```bash
# Run AWS AgentCore server
uv run python src/redmine_mcp_server/agentcore_server.py
```

**Choose the right mode:**
- **SSE Mode**: For desktop MCP clients, VS Code extensions
- **AWS AgentCore Mode**: For cloud deployment, HTTP clients, AWS AgentCore integration

### Client Configuration

#### For Traditional MCP Clients (SSE Mode)

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

#### For AWS AgentCore/HTTP Clients

Use direct HTTP POST requests to `/mcp` endpoint:

```bash
# List available tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list", 
    "id": 1
  }'

# Call a tool
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_redmine_projects"
    },
    "id": 2
  }'
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
Downloads a file attached to a Redmine issue.

**Parameters:**
- `attachment_id` (integer, required): The ID of the attachment to download
- `save_dir` (string, optional): Directory to save the file. Default: `"."`

**Returns:** Dictionary with `file_path` of the downloaded file


## Docker Deployment

### SSE Mode (Traditional)

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

### AWS AgentCore Mode (Cloud/HTTP)

```bash
# Configure for AWS AgentCore deployment
cp deployment/agentcore/.env.agentcore.example deployment/agentcore/.env.agentcore
# Edit with your settings

# Local development
docker-compose -f deployment/agentcore/docker-compose.agentcore.yml up --build

# Production deployment (AWS ECR)
cd deployment/agentcore
chmod +x deploy.sh
./deploy.sh

# Cleanup when needed
chmod +x cleanup.sh
./cleanup.sh --dry-run  # Preview cleanup
./cleanup.sh            # Interactive cleanup
```

### Production Deployment

For SSE mode, use the main deployment script:

```bash
chmod +x deploy.sh
./deploy.sh
```

For AWS AgentCore mode, see [deployment/agentcore/README.md](deployment/agentcore/README.md) for detailed deployment instructions.

## Development

### Architecture

The server uses a **dual transport architecture** with shared business logic:

#### Core Components
- **RedmineTools**: Pure Python business logic (shared across modes)
- **python-redmine**: Official Redmine Python library
- **FastAPI**: Modern web framework with health monitoring

#### Transport Modes
- **SSE Mode**: FastMCP + Server-Sent Events for desktop MCP clients
- **AWS AgentCore Mode**: Native FastAPI HTTP endpoints for AWS cloud integration

#### Benefits
- **Consistent behavior** across both transport modes
- **Easy testing** with mockable pure Python tools
- **Production ready** with health checks and monitoring

### Project Structure

```
redmine-mcp-server/
├── src/redmine_mcp_server/
│   ├── main.py              # SSE mode FastAPI server
│   ├── agentcore_server.py  # AWS AgentCore mode HTTP server
│   ├── redmine_handler.py   # SSE mode MCP tools (FastMCP)
│   └── redmine_tools.py     # Shared business logic (pure Python)
├── tests/                   # Comprehensive test suite
│   ├── test_redmine_tools.py        # Unit tests for shared logic
│   └── test_agentcore_integration.py # AgentCore HTTP tests
├── deployment/
│   └── agentcore/           # AWS AgentCore-specific deployment
│       ├── Dockerfile.agentcore
│       ├── deploy.sh
│       └── README.md
├── .env.example            # Environment configuration template
├── Dockerfile              # SSE mode container configuration
├── docker-compose.yml      # SSE mode multi-container setup
├── deploy.sh              # SSE mode deployment automation
└── pyproject.toml         # Project configuration
```

### Adding New Tools

The architecture makes it easy to add new tools that work in both transport modes:

1. **Add business logic** to `src/redmine_mcp_server/redmine_tools.py`:

```python
async def your_new_tool(self, param: str) -> Dict[str, Any]:
    """Tool implementation with business logic"""
    if not self.client:
        return {"error": "Redmine client not initialized."}
    
    try:
        # Your Redmine API calls here
        result = self.client.some_api_call(param)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}
```

2. **Add SSE wrapper** in `src/redmine_mcp_server/redmine_handler.py`:

```python
@mcp.tool()
async def your_new_tool(param: str) -> Dict[str, Any]:
    """Tool description"""
    return await redmine_tools.your_new_tool(param)
```

3. **Add HTTP definition** in `src/redmine_mcp_server/agentcore_server.py` to `TOOL_DEFINITIONS` array.

The tool will automatically be available in both SSE and AWS AgentCore modes.

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
- [AWS AgentCore Deployment Guide](deployment/agentcore/README.md) - Detailed AWS HTTP mode deployment
- [Architecture Clean Slate Plan](docs/AGENTCORE_CLEAN_SLATE_PLAN.md) - Implementation details
