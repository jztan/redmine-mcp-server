# OAuth2 Multi-Tenant Setup Guide

Set up the MCP server so each user authenticates with their own Redmine account.

**Requirements:** Redmine 6.1+ and admin access to register an OAuth application.

## Step 1: Register an OAuth App in Redmine

1. Log in as admin → **Administration → Applications** → **New Application**
2. Fill in:
   - **Name:** `MCP Server`
   - **Redirect URI:** `http://127.0.0.1:PORT/callback` (see redirect URIs below)
   - **Confidential:** Yes
3. Save and note the **Client ID** and **Client Secret**

## Step 2: Configure the MCP Server

```bash
REDMINE_AUTH_MODE=oauth
REDMINE_URL=https://redmine.example.com
REDMINE_MCP_BASE_URL=https://mcp.example.com   # public URL of this server
```

Set these in `.env` (local) or `.env.docker` (Docker). Legacy credentials are not needed in OAuth mode.

## Step 3: Start and Verify

```bash
# Local
uv run python -m redmine_mcp_server.main

# Docker
docker-compose up --build -d
```

Verify discovery endpoints:
```bash
curl http://localhost:8000/.well-known/oauth-protected-resource
curl http://localhost:8000/.well-known/oauth-authorization-server
```

## Step 4: Connect Your MCP Client

MCP clients handle the OAuth flow automatically — when connecting to the server, the client opens a browser for the user to log in to Redmine. No manual token management needed.

### Client Compatibility

| Client | OAuth2 | Notes |
|--------|--------|-------|
| **VS Code** (1.102+) | Yes | Full OAuth 2.1 with PKCE and DCR |
| **Claude Code** | Yes | Auto browser flow on 401. Use `--callback-port` for fixed port |
| **Claude Desktop** | Yes | Via Settings → Connectors. Requires DCR |
| **Codex CLI** | Yes | Use `codex mcp login`. Configurable callback port |
| **Kiro** | Yes | Configurable `oauth.redirectUri`. Implementation is newer |

### Redirect URIs

Set this in Redmine's OAuth app (Step 1) to match your client:

| Client | Redirect URI |
|--------|-------------|
| VS Code | `http://127.0.0.1:PORT/callback` |
| Claude Code | `http://127.0.0.1:PORT/oauth/callback` |
| Codex CLI | `http://127.0.0.1:PORT/callback` |
| Kiro | Configurable via `oauth.redirectUri` |

> **Note on DCR:** Some clients (Claude Desktop, VS Code) expect Dynamic Client Registration. Redmine's Doorkeeper does not support DCR, so you must pre-register the app manually (Step 1) and configure the client with the `client_id`/`client_secret`.

## Migrating from Legacy Mode

1. Set `REDMINE_AUTH_MODE=oauth` and restart — no downtime needed
2. Remove legacy credentials from `.env` once confirmed working
3. To rollback: set `REDMINE_AUTH_MODE=legacy` (or remove the variable)

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `{"error": "unauthorized"}` | Missing Bearer token | Check client is sending `Authorization` header |
| `{"error": "invalid_token"}` | Token expired/revoked | Test directly: `curl -H "Authorization: Bearer <token>" REDMINE_URL/users/current.json` |
| Discovery endpoints 404 | Not in OAuth mode | Ensure `REDMINE_AUTH_MODE=oauth` is set |
| Token works in Redmine but not MCP | Wrong `REDMINE_URL` | In Docker, use internal hostname (e.g., `http://redmine:3000`) |
| "Applications" menu missing | Redmine too old | Requires Redmine 6.1+ |
