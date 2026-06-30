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

<p align="center">
  <a href="https://redmine-mcp-server.jztan.com">
    <img src="https://raw.githubusercontent.com/jztan/redmine-mcp-server/develop/assets/redmine-mcp-demo.gif" alt="An AI agent triaging a Redmine sprint backlog through redmine-mcp-server" width="820" />
  </a>
</p>

<p align="center"><sub>An AI agent triaging a Redmine sprint through redmine-mcp-server. <a href="https://redmine-mcp-server.jztan.com">Try the live demo →</a></sub></p>

## [Tool reference](./docs/tool-reference.md) | [Changelog](./CHANGELOG.md) | [Contributing](./docs/contributing.md) | [Troubleshooting](./docs/troubleshooting.md)

## Features

- **45 MCP Tools** (plus 1 operator tool gated by `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`): Issues, projects, time tracking, wiki, Gantt, file operations, membership management, products, contacts (CRM), DMSF documents, and more
- **Flexible Authentication**: API key, username/password, or OAuth2 per-user tokens
- **Prompt Injection Protection**: User-controlled content wrapped in boundary tags for safe LLM consumption
- **Read-Only Mode**: Restrict to read-only operations via `REDMINE_MCP_READ_ONLY` environment variable
- **HTTP File Serving**: Secure attachment access via UUID-based URLs with automatic expiry
- **Pagination Support**: Efficiently handle large result sets with configurable limits
- **MCP Compliant**: Full Model Context Protocol support with FastMCP and HTTP transport
- **Docker Ready**: Complete containerization support

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
| `REDMINE_AUTH_MODE` | No | `legacy` | Authentication mode: `legacy`, `legacy-per-user`, `oauth`, or `oauth-proxy` (see [Authentication](#authentication)) |
| `REDMINE_PER_USER_TRUST_PROXY` | Yes* | `false` | Required for `legacy-per-user` mode. Operator attestation: "this server sits behind TLS and my proxy does not forward client `X-Forwarded-Proto`." |
| `REDMINE_PER_USER_AUDIT_IDENTITY` | No | `false` | `legacy-per-user` only: resolve and log the Redmine user ID per request (adds one extra round-trip) |
| `REDMINE_API_KEY` | Yes† | – | API key (legacy mode only) |
| `REDMINE_USERNAME` | Yes† | – | Username for basic auth (legacy mode only) |
| `REDMINE_PASSWORD` | Yes† | – | Password for basic auth (legacy mode only) |
| `REDMINE_MCP_BASE_URL` | Yes‡ | `http://localhost:3040` | Public base URL of this server, no trailing slash (OAuth modes only) |
| `FASTMCP_STREAMABLE_HTTP_PATH` | No | `/mcp` | MCP transport path inside `REDMINE_MCP_BASE_URL` |
| `REDMINE_INTROSPECT_CLIENT_ID` | Yes‡ | – | Doorkeeper OAuth client ID used by the MCP server to introspect Bearer tokens (RFC 7662). Register a confidential OAuth app in Redmine — see [`docs/oauth-setup.md`](docs/oauth-setup.md) Step 2. |
| `REDMINE_INTROSPECT_CLIENT_SECRET` | Yes‡ | – | Secret for the introspection client |
| `REDMINE_MCP_JWT_SIGNING_KEY` | Yes§ | – | Stable signing/encryption key used by FastMCP OAuthProxy tokens and storage |
| `REDMINE_OAUTH_CLIENT_ID` | No | – | Optional upstream Redmine OAuth client ID for `oauth-proxy`; defaults to `REDMINE_INTROSPECT_CLIENT_ID` |
| `REDMINE_OAUTH_CLIENT_SECRET` | No | – | Optional upstream Redmine OAuth client secret for `oauth-proxy`; defaults to `REDMINE_INTROSPECT_CLIENT_SECRET` |
| `FASTMCP_HOME` | No | platform default | FastMCP data directory. In `oauth-proxy` mode, encrypted OAuthProxy state is stored below `FASTMCP_HOME/oauth-proxy/` |
| `REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS` | No | loopback only | `oauth-proxy` client redirect-URI allowlist (glob patterns, comma/space separated). Unset = `http://localhost:*` and `http://127.0.0.1:*`; `*` = allow any |
| `HEALTH_INTROSPECTION_TTL_SECONDS` | No | `30` | TTL (seconds) for the `/health` Doorkeeper introspection probe cache. Set to `0` to disable caching. |
| `SERVER_HOST` | No | `0.0.0.0` | Host/IP the MCP server binds to |
| `SERVER_PORT` | No | `8000` | Port the MCP server listens on |
| `PUBLIC_HOST` | No | `localhost` | Hostname used when generating download URLs |
| `PUBLIC_PORT` | No | `8000` | Public port used for download URLs |
| `REDMINE_PUBLIC_URL` | No | – | Publicly-reachable URL of your Redmine instance. When set, `content_url` values returned on attachments are rewritten from `REDMINE_URL`'s origin to this one (preserving path/query/fragment and any reverse-proxy subpath). Useful when `REDMINE_URL` is the internal container hostname unreachable from MCP clients. When unset, the raw URL Redmine echoes back is returned. |
| `ATTACHMENTS_DIR` | No | `./attachments` | Directory for downloaded attachments |
| `ATTACHMENT_MAX_DOWNLOAD_BYTES` | No | `209715200` (200 MB) | Cap applied to every `get_redmine_attachment` download regardless of content type. Exceeding the cap aborts the download mid-stream and deletes the partial file. |
| `REDMINE_MCP_UPLOAD_FILE_ROOTS` | No | – | Extra directories allowed as `file_path` upload sources (OS path separator-separated). `ATTACHMENTS_DIR` is always allowed. Unset restricts uploads to `ATTACHMENTS_DIR` only. |
| `AUTO_CLEANUP_ENABLED` | No | `true` | Toggle automatic cleanup of expired attachments |
| `CLEANUP_INTERVAL_MINUTES` | No | `10` | Interval for cleanup task |
| `ATTACHMENT_EXPIRES_MINUTES` | No | `60` | Expiry window for generated download URLs |
| `REDMINE_MCP_EXPOSE_ADMIN_TOOLS` | No | `false` | Expose operator/admin tools on the MCP surface. Currently gates `cleanup_attachment_files`. The background cleanup task runs regardless of this flag. |
| `REDMINE_SSL_VERIFY` | No | `true` | Enable/disable SSL certificate verification |
| `REDMINE_SSL_CERT` | No | – | Path to custom CA certificate file |
| `REDMINE_SSL_CLIENT_CERT` | No | – | Path to client certificate for mutual TLS |
| `REDMINE_MCP_READ_ONLY` | No | `false` | Block all write operations (create/update/delete) when set to `true` |
| `REDMINE_AGILE_ENABLED` | No | `false` | Enable RedmineUP Agile plugin support: `get_redmine_issue` returns `story_points`, `agile_sprint_id`, `agile_position`; `update_redmine_issue` accepts `story_points` |
| `REDMINE_CHECKLISTS_ENABLED` | No | `false` | Enable RedmineUP Checklists plugin support: `get_checklist`, `update_checklist_item` (requires Checklists Pro plugin) |
| `REDMINE_PRODUCTS_ENABLED` | No | `false` | Enable RedmineUP Products plugin support: `manage_product` (action=list/get/create/update) |
| `REDMINE_CRM_ENABLED` | No | `false` | Enable RedmineUP CRM plugin support: `manage_contact` (action=list/get/create/update/delete/assign_to_project/remove_from_project) |
| `REDMINE_DMSF_ENABLED` | No | `false` | Enable DMSF document-management plugin support: `manage_document` (action=list/get/create/update). Requires `redmine_dmsf` plugin on the Redmine server. |
| `REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS` | No | `false` | Enable one retry for issue creation by filling missing required custom fields |
| `REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS` | No | `{}` | JSON object mapping required custom field names to fallback values used when creating issues |
| `REDMINE_ALLOW_PRIVATE_FETCH_URLS` | No | `false` | **Warning:** disables all SSRF protection for attachment fetching. Never set to `true` in production. |

*\* Required when `REDMINE_AUTH_MODE=legacy-per-user`.*
*† Required when `REDMINE_AUTH_MODE=legacy`. Either `REDMINE_API_KEY` or `REDMINE_USERNAME`+`REDMINE_PASSWORD` must be set. API key is recommended.*
*‡ Required when `REDMINE_AUTH_MODE=oauth` or `REDMINE_AUTH_MODE=oauth-proxy`.*
*§ Required when `REDMINE_AUTH_MODE=oauth-proxy`.*
Secret values can also be supplied with Docker/Kubernetes-style file variables: `REDMINE_INTROSPECT_CLIENT_SECRET_FILE`, `REDMINE_MCP_JWT_SIGNING_KEY_FILE`, and `REDMINE_OAUTH_CLIENT_SECRET_FILE`.

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

The server supports four authentication modes, selected via `REDMINE_AUTH_MODE`. It defaults to `legacy`, so existing deployments keep working with no changes; OAuth2 support is purely additive.

| Your situation | Mode | Redmine |
|---|---|---|
| Single shared credential, simplest setup | `legacy` (default) | any |
| Multi-user, you control the MCP client | `oauth` | 6.1+ |
| Hosted server, clients self-register (DCR) | `oauth-proxy` | 6.1+ |
| Multi-user, Redmine too old for OAuth | `legacy-per-user` | < 6.1 |

The advanced modes are collapsed below. For full setup, the [OAuth2 Setup Guide](./docs/oauth-setup.md) covers `oauth` and `oauth-proxy`, and the [legacy-per-user guide](./docs/legacy-per-user-auth.md) covers `legacy-per-user`.

### Legacy mode (default)

A single shared credential (API key or username/password) configured once in `.env`. Every request to Redmine uses the same identity.

```bash
REDMINE_AUTH_MODE=legacy        # or omit entirely; this is the default
REDMINE_URL=https://redmine.example.com
REDMINE_API_KEY=your_api_key
# OR:
# REDMINE_USERNAME=your_username
# REDMINE_PASSWORD=your_password
```

<details>
<summary><strong>OAuth2 mode</strong> (multi-user, Redmine 6.1+)</summary>

Each MCP request carries its own `Authorization: Bearer <token>`, so every user authenticates with their own Redmine account. The server validates each token against Doorkeeper's introspection endpoint before forwarding it, and exposes the OAuth2 discovery and `/revoke` endpoints clients need.

```bash
REDMINE_AUTH_MODE=oauth
REDMINE_URL=https://redmine.example.com
REDMINE_MCP_BASE_URL=https://redmine-mcp.example.com   # public URL of this server

# Confidential OAuth app registered in Redmine admin (see setup guide)
REDMINE_INTROSPECT_CLIENT_ID=...
REDMINE_INTROSPECT_CLIENT_SECRET=...
```

You register the OAuth app manually in Redmine admin → **Applications** (no Dynamic Client Registration). Full walkthrough, endpoint reference, and troubleshooting: [OAuth2 Setup Guide](./docs/oauth-setup.md).

</details>

<details>
<summary><strong>OAuthProxy mode</strong> (hosted deployments with client self-registration)</summary>

FastMCP acts as the MCP-facing authorization server: it handles DCR for MCP clients, then redirects users to Redmine as the upstream OAuth provider for consent. Use this when clients (e.g. Claude Desktop, VS Code) expect to register themselves.

```bash
REDMINE_AUTH_MODE=oauth-proxy
REDMINE_URL=https://redmine.example.com
REDMINE_MCP_BASE_URL=https://redmine-mcp.example.com   # public URL of this server

# Confidential OAuth app registered in Redmine admin (see setup guide)
REDMINE_INTROSPECT_CLIENT_ID=...
REDMINE_INTROSPECT_CLIENT_SECRET=...
REDMINE_MCP_JWT_SIGNING_KEY=...
```

The upstream Redmine app must register `${REDMINE_MCP_BASE_URL}/auth/callback` as its redirect URI. Storage, scaling, and credential-reuse notes are in the [OAuth2 Setup Guide](./docs/oauth-setup.md).

</details>

<details>
<summary><strong>legacy-per-user mode</strong> (Redmine older than 6.1)</summary>

For Redmine instances too old for OAuth, each user's MCP client sends its own Redmine API key in an `X-Redmine-API-Key` header. Each request runs as that user's identity with that user's permissions.

**This is an advanced, opt-in mode.** It requires TLS end-to-end and a correctly configured reverse proxy. Read [`docs/legacy-per-user-auth.md`](docs/legacy-per-user-auth.md) for the threat model, firewall guidance, and revocation runbook before enabling it.

**`mcp-remote` (recommended):**

```json
{ "mcpServers": { "redmine": {
  "command": "npx",
  "args": ["mcp-remote", "https://your-host/mcp",
           "--header", "X-Redmine-API-Key:${RM_KEY}"],
  "env": { "RM_KEY": "<your redmine api key>" }
}}}
```

Note the colon with no surrounding spaces in `X-Redmine-API-Key:${RM_KEY}` -- this avoids an arg-escaping bug in Cursor and Claude Desktop on Windows.

**VS Code (`mcp.json`):**

Use `.vscode/mcp.json` (workspace file) or the user profile `mcp.json`. The workspace `.mcp.json` silently drops `headers` (see microsoft/vscode#319528), so do not use that file. Pin VS Code 1.102 or newer.

```json
{
  "servers": {
    "redmine": {
      "type": "http",
      "url": "https://your-host/mcp",
      "headers": { "X-Redmine-API-Key": "${input:rmKey}" },
      "inputs": [{ "id": "rmKey", "type": "promptString",
                   "description": "Redmine API key", "password": true }]
    }
  }
}
```

**Unsupported:** any client that cannot set a custom request header, or that reserves the `Authorization` header for its own OAuth flow.

</details>

## MCP Client Configuration

The server exposes an HTTP endpoint at `http://127.0.0.1:8000/mcp`. Register it with your preferred MCP-compatible agent using the instructions below.

> The examples below assume `legacy` or `oauth` mode. In `legacy-per-user` mode each client must also send an `X-Redmine-API-Key` header; see [legacy-per-user mode](#authentication) above for header-aware configs.

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

This MCP server provides 45 tools for interacting with Redmine (plus 1 operator tool exposed by `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`, and 5 plugin-gated tools that opt in via env vars, for a maximum of 46 when all enabled). For full documentation of every tool, see the [Tool Reference](./docs/tool-reference.md).

**Core tools (40, always available):** Project Management (9), Issue Operations (13), Time Tracking (4), Discovery / Enumeration (6), Search & Wiki (2), File Operations (4), Gantt (1), Meta (1).

**Plugin-gated tools (5, opt in via env var):** Checklists (2), Products (1), Contacts / CRM (1), Documents / DMSF (1). Each requires the matching Redmine plugin installed **and** its env flag set; they stay hidden from `tools/list` otherwise.

**Operator tools (1, admin-gated):** `cleanup_attachment_files`, registered only when `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`.

<details>
<summary><strong>Full tool list with descriptions</strong></summary>

### Core tools (40, always available)

These tools require only a Redmine instance and credentials — no extra plugins or feature flags.

- **Project Management** (9 tools)
  - [`list_redmine_projects`](docs/tool-reference.md#list_redmine_projects) - List all accessible projects
  - [`list_project_issue_custom_fields`](docs/tool-reference.md#list_project_issue_custom_fields) - List issue custom fields configured for a project
  - [`list_redmine_versions`](docs/tool-reference.md#list_redmine_versions) - List versions/milestones for a project
  - [`manage_redmine_version`](docs/tool-reference.md#manage_redmine_version) - Create, update, or delete a version/milestone
  - [`list_project_members`](docs/tool-reference.md#list_project_members) - List members and roles of a project
  - [`summarize_project_status`](docs/tool-reference.md#summarize_project_status) - Get comprehensive project status summary
  - [`list_redmine_roles`](docs/tool-reference.md#list_redmine_roles) - List all roles defined in the Redmine instance (for discovering valid `role_ids`)
  - [`get_project_modules`](docs/tool-reference.md#get_project_modules) - Retrieve the enabled modules for a project
  - [`manage_project_member`](docs/tool-reference.md#manage_project_member) - Add, update, or remove a project membership

- **Issue Operations** (13 tools)
  - [`get_redmine_issue`](docs/tool-reference.md#get_redmine_issue) - Retrieve detailed issue information (supports journal pagination, watchers, relations, children)
  - [`list_redmine_issues`](docs/tool-reference.md#list_redmine_issues) - List issues with flexible filtering (project, status, assignee, etc.)
  - [`search_redmine_issues`](docs/tool-reference.md#search_redmine_issues) - Search issues by text query
  - [`create_redmine_issue`](docs/tool-reference.md#create_redmine_issue) - Create new issues, with optional file attachments via the `uploads` parameter
  - [`update_redmine_issue`](docs/tool-reference.md#update_redmine_issue) - Update existing issues, with optional file attachments via the `uploads` parameter (combine with `notes` to attach files to a journal note)
  - [`delete_redmine_issue`](docs/tool-reference.md#delete_redmine_issue) - Hard-delete an issue with required confirmation flags and a cascade-impact preview before irreversible deletion.
  - [`copy_issue`](docs/tool-reference.md#copy_issue) - Duplicate an existing issue with optional field overrides
  - [`list_subtasks`](docs/tool-reference.md#list_subtasks) - List subtasks (child issues) of a given parent
  - [`get_private_notes`](docs/tool-reference.md#get_private_notes) - Retrieve private notes on an issue
  - [`manage_issue_relation`](docs/tool-reference.md#manage_issue_relation) - List, create, or delete issue relations
  - [`manage_issue_watcher`](docs/tool-reference.md#manage_issue_watcher) - Add or remove a watcher on an issue
  - [`manage_issue_note`](docs/tool-reference.md#manage_issue_note) - Edit a journal note's text or toggle its privacy
  - [`manage_issue_category`](docs/tool-reference.md#manage_issue_category) - List, create, update, or delete issue categories
  - Note: `get_redmine_issue` can include `custom_fields` and `update_redmine_issue` can update custom fields by name (for example `{"size": "S"}`).

- **Time Tracking** (4 tools)
  - [`list_time_entries`](docs/tool-reference.md#list_time_entries) - List time entries with filtering by project, issue, user, and date range
  - [`manage_time_entry`](docs/tool-reference.md#manage_time_entry) - Create or update a time entry (use `user_id` to log on behalf of another user)
  - [`list_time_entry_activities`](docs/tool-reference.md#list_time_entry_activities) - Discover available activity types for time entries
  - [`import_time_entries`](docs/tool-reference.md#import_time_entries) - Bulk import time entries via sequential API calls with per-entry error reporting

- **Discovery / Enumeration** (6 tools): help LLMs find valid IDs before calling create/update tools
  - [`list_redmine_trackers`](docs/tool-reference.md#list_redmine_trackers) - List all trackers (Bug, Feature, Support, etc.)
  - [`list_redmine_issue_statuses`](docs/tool-reference.md#list_redmine_issue_statuses) - List all issue statuses with their `is_closed` flag
  - [`list_redmine_issue_priorities`](docs/tool-reference.md#list_redmine_issue_priorities) - List all priority levels
  - [`list_redmine_users`](docs/tool-reference.md#list_redmine_users) - Filter/list users (admin-only; supports name and group filters)
  - [`get_current_user`](docs/tool-reference.md#get_current_user) - Get the authenticated user's profile (works for non-admins)
  - [`list_redmine_queries`](docs/tool-reference.md#list_redmine_queries) - List saved custom queries (read-only)

- **Search & Wiki** (2 tools)
  - [`search_entire_redmine`](docs/tool-reference.md#search_entire_redmine) - Global search across issues and wiki pages (Redmine 3.3.0+)
  - [`manage_redmine_wiki_page`](docs/tool-reference.md#manage_redmine_wiki_page) - List, get, create, update, delete, or rename wiki pages

- **File Operations** (4 tools)
  - [`list_files`](docs/tool-reference.md#list_files) - List files uploaded to a project's Files section
  - [`upload_file`](docs/tool-reference.md#upload_file) - Upload a new file to a project (from base64 content, a URL, or a server-side `file_path`), optionally tied to a version
  - [`delete_file`](docs/tool-reference.md#delete_file) - Delete a file from a project
  - [`get_redmine_attachment`](docs/tool-reference.md#get_redmine_attachment) - Download an attachment (works in both HTTP and stdio mode)

- **Gantt** (1 tool)
  - [`get_gantt_chart`](docs/tool-reference.md#get_gantt_chart) - Retrieve project timeline data: issues with dates, dependencies, and milestones

- **Meta** (1 tool)
  - [`get_mcp_server_info`](docs/tool-reference.md#get_mcp_server_info) - Report server version, auth mode, read-only state, the authenticated user (`current_user`), and which plugin-gated tool families are enabled. Use to detect deployment lag before relying on a recently-shipped fix, or to confirm who `assigned_to_id="me"` resolves to.

### Plugin-gated tools (5, opt in via env var)

These tools require a corresponding Redmine plugin installed on the server **and** the matching environment variable set to `true` on the MCP server. They stay completely hidden from `tools/list` when their flag is unset.

- **Checklists** (2 tools) — set `REDMINE_CHECKLISTS_ENABLED=true`; requires the [RedmineUP Checklists Pro plugin](https://www.redmineup.com/pages/plugins/checklists)
  - [`get_checklist`](docs/tool-reference.md#get_checklist) - Retrieve all checklist items for an issue
  - [`update_checklist_item`](docs/tool-reference.md#update_checklist_item) - Update a checklist item's text, done state, or position

- **Products** (1 tool) — set `REDMINE_PRODUCTS_ENABLED=true`; requires the [RedmineUP Products plugin](https://www.redmineup.com/pages/plugins/products)
  - [`manage_product`](docs/tool-reference.md#manage_product) - List, get, create, or update products

- **Contacts (CRM)** (1 tool) — set `REDMINE_CRM_ENABLED=true`; requires the [RedmineUP CRM plugin](https://www.redmineup.com/pages/plugins/crm)
  - [`manage_contact`](docs/tool-reference.md#manage_contact) - List, get, create, update, delete, or assign/remove project association for contacts

- **Documents (DMSF)** (1 tool) — set `REDMINE_DMSF_ENABLED=true`; requires the [`redmine_dmsf` plugin](https://github.com/danmunn/redmine_dmsf)
  - [`manage_document`](docs/tool-reference.md#manage_document) - List, get, create (upload), or update (new revision) DMSF documents

### Operator tools (1, admin-gated)

Hidden from `tools/list` by default. Set `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true` to register them on the MCP surface. The underlying background tasks run regardless of this flag — exposing them only adds the option to drive them through MCP.

- [`cleanup_attachment_files`](docs/tool-reference.md#cleanup_attachment_files) - Manually trigger cleanup of expired attachment files (the background cleanup task runs automatically regardless)

</details>


## Docker Deployment

### Quick Start with Docker

```bash
# Configure environment
cp .env.docker.example .env.docker
# Edit .env.docker with your Redmine settings

# Run with docker-compose
docker-compose up --build

# Or run directly
docker build -t redmine-mcp-server .
docker run -p 8000:8000 --env-file .env.docker redmine-mcp-server
```

### Use the Published Image

Prebuilt multi-architecture images (`linux/amd64`, `linux/arm64`) are published to
the GitHub Container Registry on each release, so you can run the server without
building it yourself:

```bash
docker pull ghcr.io/jztan/redmine-mcp-server:latest
docker run -p 8000:8000 --env-file .env.docker ghcr.io/jztan/redmine-mcp-server:latest
```

Pin to an exact version (e.g. `ghcr.io/jztan/redmine-mcp-server:2.2.0`) or track a
minor series (e.g. `:2.2`). Published images are available starting from the next
release.

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

## Contributors

Thank you to everyone who has helped improve this project through code, reviews, testing, and feature requests:

[@sebastianelsner](https://github.com/sebastianelsner) · [@mihajlovicjj](https://github.com/mihajlovicjj) · [@aadnehovda](https://github.com/aadnehovda) · [@martindglaser](https://github.com/martindglaser) · [@Vitexus](https://github.com/Vitexus) · [@timcomport](https://github.com/timcomport) · [@Bricklou](https://github.com/Bricklou)

<a href="https://github.com/jztan/redmine-mcp-server/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=jztan/redmine-mcp-server" alt="Contributors" />
</a>

Per-release contributor credits are listed in the [Changelog](./CHANGELOG.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Additional Resources

- [Roadmap](docs/roadmap.md) - Future development plans
- [Blog: How I linked a legacy system to a modern AI agent with MCP](https://blog.jztan.com/how-i-linked-a-legacy-system-to-a-modern-ai-agent/?utm_source=github&utm_medium=readme&utm_campaign=redmine-mcp-server) - The story behind this project
- [Blog: Designing Reliable MCP Servers: 3 Hard Lessons in Agentic Architecture](https://blog.jztan.com/i-gave-my-ai-agent-full-api-access-it-was-a-mistak/?utm_source=github&utm_medium=readme&utm_campaign=redmine-mcp-server) - Lessons learned building this server
- [Blog: What It Actually Takes to Ship a Production MCP Server for Redmine](https://blog.jztan.com/what-it-actually-takes-to-ship-a-production-mcp-server-for-redmine/?utm_source=github&utm_medium=readme&utm_campaign=redmine-mcp-server) - The full journey from prototype to production
- [Blog: MCP Tool Sprawl: How I Cut 69 Tools to 43 With a Decorator](https://blog.jztan.com/mcp-tool-sprawl-consolidation/?utm_source=github&utm_medium=readme&utm_campaign=redmine-mcp-server) - The major v2 architecture change that consolidated the tools to cut context overhead and sharpen agent tool selection
