# Redmine MCP Server

[![PyPI Version](https://img.shields.io/pypi/v/redmine-mcp-server.svg)](https://pypi.org/project/redmine-mcp-server/)
[![License](https://img.shields.io/github/license/jztan/redmine-mcp-server.svg)](LICENSE)
[![Python Version](https://img.shields.io/pypi/pyversions/redmine-mcp-server.svg)](https://pypi.org/project/redmine-mcp-server/)
[![GitHub Issues](https://img.shields.io/github/issues/jztan/redmine-mcp-server.svg)](https://github.com/jztan/redmine-mcp-server/issues)
[![CI](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml/badge.svg)](https://github.com/jztan/redmine-mcp-server/actions/workflows/pr-tests.yml)
[![Coverage](https://codecov.io/gh/jztan/redmine-mcp-server/branch/master/graph/badge.svg)](https://codecov.io/gh/jztan/redmine-mcp-server)
[![Downloads](https://pepy.tech/badge/redmine-mcp-server)](https://pepy.tech/project/redmine-mcp-server)

A Model Context Protocol (MCP) server that integrates with Redmine project management systems. This server provides seamless access to Redmine data through MCP tools, enabling AI assistants to interact with your Redmine instance.

**mcp-name: io.github.jztan/redmine-mcp-server**

## [Tool reference](./docs/tool-reference.md) | [Changelog](./CHANGELOG.md) | [Contributing](./docs/contributing.md) | [Troubleshooting](./docs/troubleshooting.md)

## Features

- **Redmine Integration**: List projects, view/create/update issues, download attachments
- **HTTP File Serving**: Secure file access via UUID-based URLs with automatic expiry
- **MCP Compliant**: Full Model Context Protocol support with FastMCP and streamable HTTP transport
- **Flexible Authentication**: API key, username/password, or OAuth2 per-user tokens
- **File Management**: Automatic cleanup of expired files with storage statistics
- **Docker Ready**: Complete containerization support
- **Pagination Support**: Efficiently handle large issue lists with configurable limits
- **Read-Only Mode**: Restrict to read-only operations via `REDMINE_MCP_READ_ONLY` environment variable
- **Prompt Injection Protection**: User-controlled content wrapped in boundary tags for safe LLM consumption

## Quick Start

1. **Install the package**
   ```bash
   pip install redmine-mcp-server
   ```
2. **Create a `.env` file** with your Redmine credentials (see [Installation](#installation) for template)
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

The server runs on `http://localhost:8000` with the MCP endpoint at `/mcp`, health check at `/health`, and file serving at `/files/{file_id}`.

### Environment Variables Configuration

<details>
<summary><strong>Environment Variables</strong></summary>

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDMINE_URL` | Yes | – | Base URL of your Redmine instance |
| `REDMINE_AUTH_MODE` | No | `legacy` | Authentication mode: `legacy` or `oauth` (see [Authentication](#authentication)) |
| `REDMINE_API_KEY` | Yes† | – | API key (legacy mode only) |
| `REDMINE_USERNAME` | Yes† | – | Username for basic auth (legacy mode only) |
| `REDMINE_PASSWORD` | Yes† | – | Password for basic auth (legacy mode only) |
| `REDMINE_MCP_BASE_URL` | Yes‡ | `http://localhost:3040` | Public base URL of this server, no trailing slash (OAuth mode only) |
| `SERVER_HOST` | No | `0.0.0.0` | Host/IP the MCP server binds to |
| `SERVER_PORT` | No | `8000` | Port the MCP server listens on |
| `PUBLIC_HOST` | No | `localhost` | Hostname used when generating download URLs |
| `PUBLIC_PORT` | No | `8000` | Public port used for download URLs |
| `ATTACHMENTS_DIR` | No | `./attachments` | Directory for downloaded attachments |
| `AUTO_CLEANUP_ENABLED` | No | `true` | Toggle automatic cleanup of expired attachments |
| `CLEANUP_INTERVAL_MINUTES` | No | `10` | Interval for cleanup task |
| `ATTACHMENT_EXPIRES_MINUTES` | No | `60` | Expiry window for generated download URLs |
| `REDMINE_SSL_VERIFY` | No | `true` | Enable/disable SSL certificate verification |
| `REDMINE_SSL_CERT` | No | – | Path to custom CA certificate file |
| `REDMINE_SSL_CLIENT_CERT` | No | – | Path to client certificate for mutual TLS |
| `REDMINE_MCP_READ_ONLY` | No | `false` | Block all write operations (create/update/delete) when set to `true` |
| `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS` | No | `false` | Enable one retry for issue creation by filling missing required custom fields |
| `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` | No | `{}` | JSON object mapping required custom field names to fallback values used when creating issues |

*† Required when `REDMINE_AUTH_MODE=legacy`. Either `REDMINE_API_KEY` or `REDMINE_USERNAME`+`REDMINE_PASSWORD` must be set. API key is recommended.*
*‡ Required when `REDMINE_AUTH_MODE=oauth`.*

When `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true`, `create_redmine_issue` retries once on relevant custom-field validation errors (for example `<Field Name> cannot be blank` or `<Field Name> is not included in the list`) and fills values only from:
- the Redmine custom field `default_value`, or
- `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS`

Example:

```bash
REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true
REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS='{"Required Field A":"Value A","Required Field B":"Value B"}'
```

</details>

### SSL Certificate Configuration

Configure SSL certificate handling for Redmine servers with self-signed certificates or internal CA infrastructure.

<details>
<summary><strong>Self-Signed Certificates</strong></summary>

If your Redmine server uses a self-signed certificate or internal CA:

```bash
# In .env file
REDMINE_URL=https://redmine.company.com
REDMINE_API_KEY=your_api_key
REDMINE_SSL_CERT=/path/to/ca-certificate.crt
```

Supported certificate formats: `.pem`, `.crt`, `.cer`

</details>

<details>
<summary><strong>Mutual TLS (Client Certificates)</strong></summary>

For environments requiring client certificate authentication:

```bash
# In .env file
REDMINE_URL=https://secure.redmine.com
REDMINE_API_KEY=your_api_key
REDMINE_SSL_CERT=/path/to/ca-bundle.pem
REDMINE_SSL_CLIENT_CERT=/path/to/cert.pem,/path/to/key.pem
```

**Note**: Private keys must be unencrypted (Python requests library requirement).

</details>

<details>
<summary><strong>Disable SSL Verification (Development Only)</strong></summary>

⚠️ **WARNING**: Only use in development/testing environments!

```bash
# In .env file
REDMINE_SSL_VERIFY=false
```

Disabling SSL verification makes your connection vulnerable to man-in-the-middle attacks.

</details>

For SSL troubleshooting, see the [Troubleshooting Guide](./docs/troubleshooting.md#ssl-certificate-errors).

## Authentication

The server supports two authentication modes, selected via `REDMINE_AUTH_MODE`.

> **Backward compatibility**: `REDMINE_AUTH_MODE` defaults to `legacy`, so all existing deployments continue to work without any configuration changes. OAuth2 support is purely additive — nothing breaks if you never set the variable.

### Legacy mode (default)

Uses a single shared credential — either an API key or a username/password pair — configured once in `.env`. Every request to Redmine uses the same identity.

```bash
REDMINE_AUTH_MODE=legacy        # or omit entirely — this is the default
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=your_api_key
# OR:
# REDMINE_USERNAME=your_username
# REDMINE_PASSWORD=your_password
```

### OAuth2 mode

> **Requires Redmine 6.1 or newer.** OAuth2 support (via the Doorkeeper gem) was introduced in Redmine 6.1.

Each MCP request carries its own `Authorization: Bearer <token>` header. The server validates the token against `GET /users/current.json` on Redmine before forwarding it. This enables multi-user deployments where each user authenticates with their own Redmine account.

```bash
REDMINE_AUTH_MODE=oauth
REDMINE_URL=https://redmine.example.com
REDMINE_MCP_BASE_URL=https://redmine-mcp.example.com   # public URL of this server
```

In OAuth mode the server also exposes OAuth2 discovery and token management endpoints:

| Endpoint | Standard | Purpose |
|----------|----------|---------|
| `/.well-known/oauth-protected-resource` | RFC 8707 | Tells clients where to find the authorization server |
| `/.well-known/oauth-authorization-server` | RFC 8414 | Advertises Redmine's Doorkeeper OAuth endpoints |
| `POST /revoke` | RFC 7009 | Revokes an OAuth2 token (proxies to Redmine's `/oauth/revoke`) |

Redmine uses the [Doorkeeper](https://github.com/doorkeeper-gem/doorkeeper) gem for OAuth2 but does not serve the RFC 8414 discovery document itself. This server serves it on Redmine's behalf, pointing to Redmine's real `/oauth/authorize`, `/oauth/token`, and `/oauth/revoke` endpoints.

**Prerequisites for OAuth mode:**
- An OAuth application registered in Redmine admin → **Applications** with the callback URL of your client
- A client that handles the authorization code flow, stores the resulting token per user, and sends it as `Authorization: Bearer <token>` on every MCP request
- No Dynamic Client Registration (DCR) is required — register the application manually in Redmine admin

For step-by-step setup instructions, see the [OAuth2 Setup Guide](./docs/oauth-setup.md).

## MCP Client Configuration

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
<summary><strong>Claude Desktop (macOS & Windows)</strong></summary>

Claude Desktop's config file supports stdio transport only. Use FastMCP's proxy via `uv` to bridge to this HTTP server.

**Setup:**
1. Open Claude Desktop
2. Click the **Claude** menu (macOS menu bar / Windows title bar) > **Settings...**
3. Click the **Developer** tab > **Edit Config**
4. Add the following configuration:

```json
{
  "mcpServers": {
    "redmine": {
      "command": "uv",
      "args": [
        "run",
        "--with", "fastmcp",
        "fastmcp",
        "run",
        "http://127.0.0.1:8000/mcp"
      ]
    }
  }
}
```

5. Save the file, then **fully quit and restart** Claude Desktop
6. Look for the tools icon in the input area to verify the connection

**Config file locations:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Note:** The Redmine MCP server must be running before starting Claude Desktop.

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
```

## Available Tools

This MCP server provides 21 tools for interacting with Redmine. For detailed documentation, see [Tool Reference](./docs/tool-reference.md).

- **Project Management** (5 tools)
  - [`list_redmine_projects`](docs/tool-reference.md#list_redmine_projects) - List all accessible projects
  - [`list_project_issue_custom_fields`](docs/tool-reference.md#list_project_issue_custom_fields) - List issue custom fields configured for a project
  - [`list_redmine_versions`](docs/tool-reference.md#list_redmine_versions) - List versions/milestones for a project
  - [`list_project_members`](docs/tool-reference.md#list_project_members) - List members and roles of a project
  - [`summarize_project_status`](docs/tool-reference.md#summarize_project_status) - Get comprehensive project status summary

- **Issue Operations** (5 tools)
  - [`get_redmine_issue`](docs/tool-reference.md#get_redmine_issue) - Retrieve detailed issue information (supports journal pagination, watchers, relations, children)
  - [`list_redmine_issues`](docs/tool-reference.md#list_redmine_issues) - List issues with flexible filtering (project, status, assignee, etc.)
  - [`search_redmine_issues`](docs/tool-reference.md#search_redmine_issues) - Search issues by text query
  - [`create_redmine_issue`](docs/tool-reference.md#create_redmine_issue) - Create new issues
  - [`update_redmine_issue`](docs/tool-reference.md#update_redmine_issue) - Update existing issues
  - Note: `get_redmine_issue` can include `custom_fields` and `update_redmine_issue` can update custom fields by name (for example `{"size": "S"}`).

- **Time Tracking** (4 tools)
  - [`list_time_entries`](docs/tool-reference.md#list_time_entries) - List time entries with filtering by project, issue, user, and date range
  - [`create_time_entry`](docs/tool-reference.md#create_time_entry) - Log time against projects or issues
  - [`update_time_entry`](docs/tool-reference.md#update_time_entry) - Modify existing time entries
  - [`list_time_entry_activities`](docs/tool-reference.md#list_time_entry_activities) - Discover available activity types for time entries

- **Search & Wiki** (5 tools)
  - [`search_entire_redmine`](docs/tool-reference.md#search_entire_redmine) - Global search across issues and wiki pages (Redmine 3.3.0+)
  - [`get_redmine_wiki_page`](docs/tool-reference.md#get_redmine_wiki_page) - Retrieve wiki page content
  - [`create_redmine_wiki_page`](docs/tool-reference.md#create_redmine_wiki_page) - Create new wiki pages
  - [`update_redmine_wiki_page`](docs/tool-reference.md#update_redmine_wiki_page) - Update existing wiki pages
  - [`delete_redmine_wiki_page`](docs/tool-reference.md#delete_redmine_wiki_page) - Delete wiki pages

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

## Troubleshooting

If you run into any issues, checkout our [troubleshooting guide](./docs/troubleshooting.md).

## Contributing

Contributions are welcome! Please see our [contributing guide](./docs/contributing.md) for details.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Additional Resources

- [Tool Reference](./docs/tool-reference.md) - Complete tool documentation
- [Troubleshooting Guide](./docs/troubleshooting.md) - Common issues and solutions
- [Contributing Guide](./docs/contributing.md) - Development setup and guidelines
- [Changelog](./CHANGELOG.md) - Detailed version history
- [Roadmap](roadmap.md) - Future development plans
- [Blog: How I linked a legacy system to a modern AI agent with MCP](https://blog.jztan.com/how-i-linked-a-legacy-system-to-a-modern-ai-agent/) - The story behind this project
- [Blog: Designing Reliable MCP Servers: 3 Hard Lessons in Agentic Architecture](https://blog.jztan.com/i-gave-my-ai-agent-full-api-access-it-was-a-mistak/) - Lessons learned building this server
