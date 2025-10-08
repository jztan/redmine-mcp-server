# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/redmine-mcp-server.svg)](https://pypi.org/project/redmine-mcp-server/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/redmine-mcp-server.svg)](https://pypi.org/project/redmine-mcp-server/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)
[![Downloads](https://pepy.tech/badge/redmine-mcp-server)](https://pepy.tech/project/redmine-mcp-server)

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

## Quick Start

1. **Install the package**
   ```bash
   pip install redmine-mcp-server
   ```
2. **Create a `.env` file** using the template below and fill in your Redmine credentials.
3. **Start the server**
   ```bash
   redmine-mcp-server
   ```
4. **Add the server to your MCP client** using one of the guides in [MCP Client Configuration](#mcp-client-configuration).

Once running, the server listens on `http://localhost:8000` with the MCP endpoint at `/mcp`, health check at `/health`, and file serving at `/files/{file_id}`.

## Installation

### Prerequisites

- Python 3.10+ (for local installation)
- Docker (alternative deployment, uses Python 3.13)
- Access to a Redmine instance

### Install from PyPI (Recommended)

```bash
# Install the package
pip install redmine-mcp-server

# Create configuration file .env
cat > .env << 'EOF'
# Redmine connection (required)
REDMINE_URL=https://your-redmine-server.com

# Authentication - Use either API key (recommended) or username/password
REDMINE_API_KEY=your_api_key
# OR use username/password:
# REDMINE_USERNAME=your_username
# REDMINE_PASSWORD=your_password

# Server configuration (optional, defaults shown)
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Public URL for file serving (optional)
PUBLIC_HOST=localhost
PUBLIC_PORT=8000

# File management (optional)
ATTACHMENTS_DIR=./attachments
AUTO_CLEANUP_ENABLED=true
CLEANUP_INTERVAL_MINUTES=10
ATTACHMENT_EXPIRES_MINUTES=60
EOF

# Edit .env with your actual Redmine settings
nano .env  # or use your preferred editor

# Run the server
redmine-mcp-server
# Or alternatively:
python -m redmine_mcp_server.main
```

## Python Version Compatibility

| Deployment Method | Python Version | Support Status |
|------------------|----------------|----------------|
| pip install | 3.10+ | ✅ Full Support |
| Docker | 3.13 (built-in) | ✅ Full Support |

The package is tested on Python 3.10, 3.11, 3.12, and 3.13.

### Install from Source

```bash
# Clone and setup
git clone https://github.com/jztan/redmine-mcp-server
cd redmine-mcp-server

# Install dependencies (using uv)
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

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDMINE_URL` | Yes | – | Base URL of your Redmine instance |
| `REDMINE_API_KEY` | Yes* | – | API key for authentication (*or provide username/password*) |
| `REDMINE_USERNAME` | Yes* | – | Username for basic auth (*use with password when not using API key*) |
| `REDMINE_PASSWORD` | Yes* | – | Password for basic auth |
| `SERVER_HOST` | No | `0.0.0.0` | Host/IP the MCP server binds to |
| `SERVER_PORT` | No | `8000` | Port the MCP server listens on |
| `PUBLIC_HOST` | No | `localhost` | Hostname used when generating download URLs |
| `PUBLIC_PORT` | No | `8000` | Public port used for download URLs |
| `ATTACHMENTS_DIR` | No | `./attachments` | Directory for downloaded attachments |
| `AUTO_CLEANUP_ENABLED` | No | `true` | Toggle automatic cleanup of expired attachments |
| `CLEANUP_INTERVAL_MINUTES` | No | `10` | Interval for cleanup task |
| `ATTACHMENT_EXPIRES_MINUTES` | No | `60` | Expiry window for generated download URLs |

*\* Either `REDMINE_API_KEY` or the combination of `REDMINE_USERNAME` and `REDMINE_PASSWORD` must be provided for authentication. Do not use both methods at the same time.*
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
# If installed from PyPI:
redmine-mcp-server

# If installed from source:
uv run python -m redmine_mcp_server.main
```

The same command is used for both development and production. Configure environment-specific settings in your `.env` file.

### MCP Client Configuration

The server exposes an HTTP endpoint at `http://127.0.0.1:8000/mcp`. Register it with your preferred MCP-compatible agent using the instructions below.

<details>
<summary><strong>Visual Studio Code (Native MCP Support)</strong></summary>

VS Code has built-in MCP support via GitHub Copilot (requires VS Code 1.102+).

**Using CLI (Quickest):**
```bash
code --add-mcp '{"name":"redmine","type":"http","url":"http://127.0.0.1:8000/mcp"}'
```

**Using Command Palette:**
1. Open Command Palette (`Cmd/Ctrl+Shift+P`)
2. Run `MCP: Open User Configuration` (for global) or `MCP: Open Workspace Folder Configuration` (for project-specific)
3. Add the configuration:
   ```json
   {
     "servers": {
       "redmine": {
         "type": "http",
         "url": "http://127.0.0.1:8000/mcp"
       }
     }
   }
   ```
4. Save the file. VS Code will automatically load the MCP server.

**Manual Configuration:**
Create `.vscode/mcp.json` in your workspace (or `mcp.json` in your user profile directory):
```json
{
  "servers": {
    "redmine": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

</details>

<details>
<summary><strong>Claude Code</strong></summary>

Add to Claude Code using the CLI command:

```bash
claude mcp add --transport http redmine http://127.0.0.1:8000/mcp
```

Or configure manually in your Claude Code settings file (`~/.claude.json`):

```json
{
  "mcpServers": {
    "redmine": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

</details>

<details>
<summary><strong>Codex CLI</strong></summary>

Add to Codex CLI using the command:

```bash
codex mcp add redmine -- npx -y mcp-client-http http://127.0.0.1:8000/mcp
```

Or configure manually in `~/.codex/config.toml`:

```toml
[mcp_servers.redmine]
command = "npx"
args = ["-y", "mcp-client-http", "http://127.0.0.1:8000/mcp"]
```

**Note:** Codex CLI primarily supports stdio-based MCP servers. The above uses `mcp-client-http` as a bridge for HTTP transport.

</details>

<details>
<summary><strong>Kiro</strong></summary>

Kiro primarily supports stdio-based MCP servers. For HTTP servers, use an HTTP-to-stdio bridge:

1. Create or edit `.kiro/settings/mcp.json` in your workspace:
   ```json
   {
     "mcpServers": {
       "redmine": {
         "command": "npx",
         "args": [
           "-y",
           "mcp-client-http",
           "http://127.0.0.1:8000/mcp"
         ],
         "disabled": false
       }
     }
   }
   ```
2. Save the file and restart Kiro. The Redmine tools will appear in the MCP panel.

**Note:** Direct HTTP transport support in Kiro is limited. The above configuration uses `mcp-client-http` as a bridge to connect to HTTP MCP servers.

</details>

<details>
<summary><strong>Generic MCP Clients</strong></summary>

Most MCP clients use a standard configuration format. For HTTP servers:

```json
{
  "mcpServers": {
    "redmine": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

For clients that require a command-based approach with HTTP bridge:

```json
{
  "mcpServers": {
    "redmine": {
      "command": "npx",
      "args": ["-y", "mcp-client-http", "http://127.0.0.1:8000/mcp"]
    }
  }
}
```

</details>

### Testing Your Setup

```bash
# Test connection by checking health endpoint
curl http://localhost:8000/health

# For development (source installation only):
python tests/test_connection.py
python tests/run_tests.py --all
```

## Available Tools

This MCP server provides 10 tools for interacting with Redmine. For detailed documentation, see [Tool Reference](./docs/tool-reference.md).

- **Project Management** (2 tools)
  - [`list_redmine_projects`](docs/tool-reference.md#list_redmine_projects) - List all accessible projects
  - [`summarize_project_status`](docs/tool-reference.md#summarize_project_status) - Get comprehensive project status summary

- **Issue Operations** (6 tools)
  - [`get_redmine_issue`](docs/tool-reference.md#get_redmine_issue) - Retrieve detailed issue information
  - [`list_my_redmine_issues`](docs/tool-reference.md#list_my_redmine_issues) - List issues assigned to you (with pagination)
  - [`search_redmine_issues`](docs/tool-reference.md#search_redmine_issues) - Search issues by text query
  - [`create_redmine_issue`](docs/tool-reference.md#create_redmine_issue) - Create new issues
  - [`update_redmine_issue`](docs/tool-reference.md#update_redmine_issue) - Update existing issues

- **File Operations** (2 tools)
  - [`get_redmine_attachment_download_url`](docs/tool-reference.md#get_redmine_attachment_download_url) - Get secure download URLs for attachments
  - [`cleanup_attachment_files`](docs/tool-reference.md#cleanup_attachment_files) - Clean up expired attachment files


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
# Install development dependencies
# For source installation:
uv pip install -e .[dev]

# For PyPI installation:
pip install redmine-mcp-server[dev]
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
- [Roadmap](roadmap.md) - Future development plans
- [Blog: How I linked a legacy system to a modern AI agent with MCP](https://www.thefirstcommit.com/how-i-linked-a-legacy-system-to-a-modern-ai-agent-with-mcp-1b14e634a4b3) - The story behind this project
