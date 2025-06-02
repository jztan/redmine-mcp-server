# Redmine MCP Server

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

## Features

- **Project Management**: List all accessible Redmine projects
- **Issue Tracking**: Retrieve detailed information about specific Redmine issues
- **Advanced Issue Filtering**: Filter and sort issues by project, status, assignee with pagination
- **Group Assignment Support**: Include issues assigned to user's groups with smart discovery
- **Multiple Authentication**: Support for both username/password and API key authentication
- **FastAPI Integration**: RESTful API with Server-Sent Events (SSE) for real-time communication
- **MCP Compatibility**: Full compatibility with Model Context Protocol standards
- **Docker Support**: Ready for containerized deployment

## Architecture

The server is built using:
- **FastAPI**: Modern, fast web framework for building APIs
- **FastMCP**: Model Context Protocol implementation
- **python-redmine**: Official Redmine Python library
- **Server-Sent Events (SSE)**: Real-time communication transport

## Project Structure

```
redmine-mcp-server/
├── src/
│   └── redmine_mcp_server/
│       ├── __init__.py
│       ├── main.py              # FastAPI application entry point
│       └── redmine_handler.py   # MCP tools and Redmine integration
├── tests/
│   ├── conftest.py             # Test configuration and fixtures
│   ├── run_tests.py            # Advanced test runner with coverage
│   ├── test_connection.py      # Connection and infrastructure tests
│   ├── test_integration.py     # End-to-end integration tests
│   └── test_redmine_handler.py # Unit tests for MCP tools
├── .env.example                # Environment configuration template
├── .env                        # Environment configuration (not in git)
├── .env.docker                 # Docker environment configuration
├── .gitignore                  # Git ignore rules
├── pytest.ini                 # Test configuration
├── pyproject.toml              # Project configuration and dependencies
├── uv.lock                     # Dependency lock file
├── Dockerfile                  # Container configuration
├── docker-compose.yml          # Multi-container setup
├── deploy.sh                   # Deployment automation script
└── README.md                   # This file
```

## Installation

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Access to a Redmine instance

### Setup

1. **Clone the repository** (when available):
   ```bash
   git clone https://github.com/jztan/redmine-mcp-server
   cd redmine-mcp-server
   ```

2. **Install dependencies using uv**:
   ```bash
   uv venv
   source .venv/bin/activate  # On macOS/Linux
   uv pip install -e .
   ```

3. **Install development dependencies (for testing)**:
   ```bash
   uv pip install pytest pytest-asyncio pytest-cov
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your Redmine configuration:
   ```env
   # Option 1: Username and Password
   REDMINE_URL=https://your-redmine-server.com
   REDMINE_USERNAME=your_username
   REDMINE_PASSWORD=your_password
   
   # Option 2: API Key (alternative)
   # REDMINE_API_KEY=your_api_key
   
   # Server configuration
   SERVER_HOST=0.0.0.0
   SERVER_PORT=8000
   ```

## Usage

### Running the Server

#### Development Mode
```bash
uv run fastapi dev src/redmine_mcp_server/main.py
```

#### Production Mode
```bash
uv run python src/redmine_mcp_server/main.py
```

The server will start on `http://localhost:8000` with the MCP endpoint available at `/sse`.

### Testing Connection

Test your Redmine connection:
```bash
python tests/test_connection.py
```

Or test using our test runner:
```bash
python tests/run_tests.py --integration
```

### MCP Client Configuration

Add to your MCP client configuration (e.g., VS Code settings.json):

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

## Available MCP Tools

### `get_redmine_issue(issue_id: int)`
Retrieves detailed information about a specific Redmine issue.

**Parameters:**
- `issue_id`: The ID of the Redmine issue

**Returns:**
```json
{
  "id": 123,
  "subject": "Issue title",
  "description": "Issue description",
  "project": {"id": 1, "name": "Project Name"},
  "status": {"id": 1, "name": "New"},
  "priority": {"id": 2, "name": "Normal"},
  "author": {"id": 1, "name": "Author Name"},
  "assigned_to": {"id": 2, "name": "Assignee Name"},
  "created_on": "2025-01-01T00:00:00",
  "updated_on": "2025-01-02T00:00:00"
}
```

### `list_redmine_projects()`
Lists all accessible projects in the Redmine instance.

**Returns:**
```json
[
  {
    "id": 1,
    "name": "Project Name",
    "identifier": "project-identifier",
    "description": "Project description",
    "created_on": "2025-01-01T00:00:00"
  }
]
```

### `list_my_redmine_issues(...)`
Lists Redmine issues with filtering and sorting options, defaulting to issues assigned to the current user.

**Parameters:**
- `project_id` (optional): Filter by specific project ID
- `status_id` (optional): Filter by status ID or name (e.g., 'open', 'closed')
- `assigned_to_id` (optional): Filter by assignee ('me' or specific user ID). Defaults to 'me'
- `sort` (optional): Sorting criteria (e.g., 'priority:desc', 'updated_on:asc')
- `limit` (optional): Number of issues to return. Defaults to 25
- `offset` (optional): Offset for pagination. Defaults to 0

**Examples:**
```python
# Get my issues (default behavior)
await list_my_redmine_issues()

# Get open issues in project 1, sorted by priority
await list_my_redmine_issues(project_id=1, status_id='open', sort='priority:desc')

# Get issues assigned to specific user with pagination
await list_my_redmine_issues(assigned_to_id='123', limit=10, offset=20)
```

**Returns:**
```json
[
  {
    "id": 123,
    "subject": "Issue title",
    "description": "Issue description",
    "project": {"id": 1, "name": "Project Name"},
    "status": {"id": 1, "name": "New"},
    "priority": {"id": 2, "name": "Normal"},
    "author": {"id": 1, "name": "Author Name"},
    "assigned_to": {"id": 2, "name": "Assignee Name"},
    "created_on": "2025-01-01T00:00:00",
    "updated_on": "2025-01-02T00:00:00"
  }
]
```

## Development

### Dependencies

Core dependencies are managed in `pyproject.toml`:
- `fastapi[standard]>=0.115.12` - Web framework
- `mcp[cli]>=1.9.1` - Model Context Protocol
- `python-redmine>=2.5.0` - Redmine API client
- `python-dotenv>=1.0.0` - Environment configuration
- `httpx>=0.28.1` - HTTP client
- `uvicorn` - ASGI server

### Adding New Tools

1. Add your tool function to `src/redmine_mcp_server/redmine_handler.py`:
   ```python
   @mcp.tool()
   async def your_new_tool(param: str) -> Dict[str, Any]:
       """Tool description"""
       # Implementation here
       return {"result": "data"}
   ```

2. The tool will automatically be available through the MCP interface.

### Testing



#### Running Tests

**Run all tests:**
```bash
python tests/run_tests.py --all
```

**Run unit tests only (default):**
```bash
python tests/run_tests.py
```

**Run integration tests only:**
```bash
python tests/run_tests.py --integration
```

**Run with coverage report:**
```bash
python tests/run_tests.py --coverage
```

**Run specific test file:**
```bash
python tests/run_tests.py --file test_redmine_handler.py
```

**Verbose output:**
```bash
python tests/run_tests.py --all --verbose
```

#### Test Requirements
- Unit tests: No external dependencies (use mocks)
- Integration tests: Require valid Redmine server connection
- All tests: Automatically check dependencies (pytest, pytest-asyncio)

#### Coverage Report
After running tests with `--coverage`, view the HTML coverage report:
```bash
open htmlcov/index.html
```

## Authentication

The server supports two authentication methods:

### Username/Password
```env
REDMINE_URL=https://your-redmine-server.com
REDMINE_USERNAME=your_username
REDMINE_PASSWORD=your_password
```

### API Key
```env
REDMINE_URL=https://your-redmine-server.com
REDMINE_API_KEY=your_api_key
```

**Note:** API key authentication is preferred for security reasons.

## Docker Support

The project includes complete Docker containerization support for easy deployment.

### Quick Start with Docker

**Using docker-compose (recommended):**
```bash
# Copy and configure environment
cp .env.example .env.docker
# Edit .env.docker with your Redmine settings

# Build and run
docker-compose up --build
```

**Using Docker directly:**
```bash
# Build the image
docker build -t redmine-mcp-server .

# Run the container
docker run -p 8000:8000 --env-file .env.docker redmine-mcp-server
```

### Docker Testing

**Test the running container:**
```bash
# Check if container is running
docker ps

# Test MCP endpoints
curl http://localhost:8000/messages/
curl http://localhost:8000/sse

# View container logs
docker logs redmine-mcp-server
```

### Docker Configuration

The Docker setup includes:
- **Multi-stage build** for optimized image size
- **Security hardening** with non-root user
- **Health checks** for container monitoring
- **Environment-based configuration**
- **Automated deployment script** (`deploy.sh`)

### Production Deployment

Use the included deployment script:
```bash
chmod +x deploy.sh
./deploy.sh
```

This script handles:
- Environment validation
- Container building and deployment
- Health check verification
- Rollback on failure

## Security Considerations

- Never commit your `.env` file to version control
- Use API keys instead of passwords when possible
- Ensure your Redmine server uses HTTPS in production
- Restrict MCP server access to trusted networks

## Troubleshooting

### Common Issues

1. **Connection refused**: Ensure your Redmine URL is correct and accessible
2. **Authentication failed**: Verify your credentials in the `.env` file
3. **Import errors**: Make sure all dependencies are installed with `uv pip install -e .`
4. **Port conflicts**: The default port 8000 might be in use, modify `SERVER_PORT` in `.env`

### Debug Mode

Enable debug logging by modifying the FastAPI app initialization in `main.py`.

## Contributing

This project is planned to be open-sourced. Contributions will be welcome once the repository is public.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Roadmap

For detailed information about planned features, current development status, and future enhancements, see [ROADMAP.md](ROADMAP.md).