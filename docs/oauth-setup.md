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

## Step 2: Register a Doorkeeper Introspection Client

The MCP server validates incoming Bearer tokens by calling Doorkeeper's RFC 7662 introspection endpoint (`POST /oauth/introspect`). To do this it needs its own confidential OAuth application registered in Redmine, separate from the user-flow OAuth app from Step 1.

### 2a. Register the application

1. **Sign in to Redmine as administrator → Administration → Applications → New Application.**
2. Fill in:
   - **Name:** `Redmine MCP Server (introspection)`
   - **Redirect URI:** `urn:ietf:wg:oauth:2.0:oob` (this client never performs the authorization-code dance; the URI is unused but required by the form)
   - **Confidential:** Yes
   - **Scopes:** leave empty
3. Save and note the **Client ID** and **Client Secret**.

> **If the Administration → Applications page returns 403:** Redmine's `admin_authenticator` for Doorkeeper requires REST API to be enabled. Go to **Administration → Settings → API → "Enable REST web service"** and save. (You can also flip this from a Rails console: `Setting.rest_api_enabled = "1"`.)

### 2b. Enable cross-app token introspection in Doorkeeper

Redmine ships with `allow_token_introspection false` hard-coded, which means even an authenticated client cannot introspect a token issued to a different OAuth app. The MCP introspection client needs to introspect tokens issued by the **user-flow** OAuth app (Step 1), so the default has to change.

**Edit Redmine's own initializer in place, on the Redmine server:** `config/initializers/30-redmine.rb`. Find the line:

```ruby
    allow_token_introspection false
```

Replace it with:

```ruby
    allow_token_introspection do |_token, authorized_client, _resource_owner|
      !authorized_client.nil? && authorized_client.confidential?
    end
```

This grants introspection rights to any confidential OAuth client. The MCP introspection client is confidential by configuration (Step 2a). Public clients (e.g., browser-based or native apps registered without a secret) are still rejected. Note: if your user-flow OAuth app from Step 1 is also configured as confidential, it would technically also be permitted to introspect — but only the MCP server uses these credentials in practice.

Restart Redmine after the change.

> **⚠️ Why edit `30-redmine.rb` directly instead of creating a separate initializer?**
>
> Redmine wraps its entire Doorkeeper configuration inside a `Rails.application.config.to_prepare do ... end` block. Doorkeeper's `Doorkeeper.configure do ... end` call **rebuilds the entire `Doorkeeper.config` object from scratch each call** — it does not merge with existing settings. If you add a second `Doorkeeper.configure` block in your own initializer, it wipes Redmine's `admin_authenticator`, `resource_owner_authenticator`, `grant_flows`, `enforce_configured_scopes`, base controller, and every other setting Redmine relies on. The most visible symptom is the entire Administration → Applications page returning 403 with the log warning *"Access to admin panel is forbidden due to Doorkeeper.configure.admin_authenticator being unconfigured"*.
>
> The only safe way to override a single Doorkeeper option in a Redmine deployment is to edit the existing `Doorkeeper.configure` block in `30-redmine.rb` in place. Track the change as a deployment patch (e.g., a Dockerfile `RUN sed -i ...` step) so it survives Redmine upgrades.

### 2c. Verify

```bash
curl -X POST $REDMINE_URL/oauth/introspect \
  -u "$REDMINE_INTROSPECT_CLIENT_ID:$REDMINE_INTROSPECT_CLIENT_SECRET" \
  -d "token=any-test-token&token_type_hint=access_token"
```

Expected response: `200 OK` with body `{"active":false}`. The `false` is correct (the synthetic token isn't real); what matters is that you got `200`, not `401` or `404`.

Common failure modes:
- **`404 Page not found`** — the `/oauth/introspect` route isn't mounted. Confirm step 2b was applied and Redmine was restarted; the route is only mounted when `allow_token_introspection` is something other than `false`.
- **`401 invalid_client`** — the introspection client's `client_id` / `client_secret` are wrong, or the application isn't marked confidential.
- **`200 {"active": false}` for a *known-valid* user-flow bearer** — your `allow_token_introspection` block is returning falsy for the introspecting client. Confirm the introspection client is confidential and that your block matches the example in Step 2b.

## Step 3: Configure the MCP Server

```bash
REDMINE_AUTH_MODE=oauth
REDMINE_URL=https://redmine.example.com
REDMINE_MCP_BASE_URL=https://mcp.example.com   # public URL of this server

# Introspection client (from Step 2)
REDMINE_INTROSPECT_CLIENT_ID=<UID from Redmine>
REDMINE_INTROSPECT_CLIENT_SECRET=<Secret from Redmine>

# Optional: /health introspection probe cache TTL in seconds (default 30)
# HEALTH_INTROSPECTION_TTL_SECONDS=30
```

Set these in `.env` (local) or `.env.docker` (Docker). Legacy credentials are not needed in OAuth mode.

**Startup behavior:** When `REDMINE_AUTH_MODE=oauth` is set, the server fails fast at startup if `REDMINE_INTROSPECT_CLIENT_ID` or `REDMINE_INTROSPECT_CLIENT_SECRET` is missing — better to surface the misconfiguration immediately than to return 401 on every request.

## Step 4: Start and Verify

```bash
# Local
uv run python -m redmine_mcp_server.main

# Docker
docker-compose up --build -d
```

Verify discovery endpoints:
```bash
# RFC 9728 protected-resource metadata (mounted by FastMCP RemoteAuthProvider)
curl http://localhost:8000/.well-known/oauth-protected-resource/mcp

# RFC 8414 authorization-server metadata (mirror of Redmine's Doorkeeper)
curl http://localhost:8000/.well-known/oauth-authorization-server/mcp

# /health probes Doorkeeper introspection in OAuth mode
curl http://localhost:8000/health
# {"status": "ok", "checks": {"introspection": "ok"}, ...}
```

If `/health` returns `"status": "degraded"` with `"introspection": "unreachable"`, the introspection client is misconfigured (see Step 2 — verify the client is **confidential** and that the `allow_token_introspection` block in `30-redmine.rb` was applied per Step 2b).

## Step 5: Connect Your MCP Client

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
| `{"error": "invalid_token"}` | Token failed Doorkeeper introspection (revoked, expired, or invalid) | Test with `curl $REDMINE_URL/oauth/introspect -u "$REDMINE_INTROSPECT_CLIENT_ID:$REDMINE_INTROSPECT_CLIENT_SECRET" -d "token=<bearer>&token_type_hint=access_token"` |
| Every MCP call returns 401 | Introspection client not authorized to introspect tokens of other apps | Re-check Step 2b's `allow_token_introspection` block in `30-redmine.rb`. Confirm the introspection client is **Confidential: Yes**. |
| `/health` returns `status: "degraded"` | Introspection endpoint unreachable | Check `REDMINE_URL`, introspection credentials, and Doorkeeper's `allow_token_introspection` setting |
| Server fails to start: "Missing env var(s): REDMINE_INTROSPECT_CLIENT_ID..." | OAuth mode requires introspection creds | Register the introspection client per Step 2, set `REDMINE_INTROSPECT_CLIENT_ID` / `_SECRET` |
| Discovery endpoints 404 | Not in OAuth mode, or hitting wrong path | Ensure `REDMINE_AUTH_MODE=oauth`. Note: the canonical paths are `/.well-known/oauth-protected-resource/mcp` (suffix-scoped per RFC 9728 §3.1) and `/.well-known/oauth-authorization-server/mcp` |
| Token works in Redmine but not MCP | Wrong `REDMINE_URL` | In Docker, use internal hostname (e.g., `http://redmine:3000`) |
| "Applications" menu missing | Redmine too old | Requires Redmine 6.1+ |

For more diagnostic flows (including the "all MCP requests return 401" symptom flow and emergency rollback to legacy mode), see `docs/troubleshooting.md`.
