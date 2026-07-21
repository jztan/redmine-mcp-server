# OAuth2 Multi-Tenant Setup Guide

Set up the MCP server so each user authenticates with their own Redmine account.

**Requirements:** Redmine 6.1+ and admin access to register an OAuth application.

This guide covers both direct Redmine Bearer-token mode (`REDMINE_AUTH_MODE=oauth`) and hosted OAuthProxy mode (`REDMINE_AUTH_MODE=oauth-proxy`). In `oauth-proxy` mode, FastMCP handles DCR/CIMD for MCP clients and uses Redmine as the upstream OAuth provider and external consent screen.

## Step 1: Register an OAuth App in Redmine

1. Log in as admin → **Administration → Applications** → **New Application**
2. Fill in:
   - **Name:** `MCP Server`
   - **Redirect URI:** `http://127.0.0.1:PORT/callback` for direct OAuth mode, or `${REDMINE_MCP_BASE_URL}/auth/callback` for OAuthProxy mode
   - **Confidential:** Yes
3. Save and note the **Client ID** and **Client Secret**

## Step 2: Register a Doorkeeper Introspection Client

The MCP server validates incoming Bearer tokens by calling Doorkeeper's RFC 7662 introspection endpoint (`POST /oauth/introspect`). To do this it needs a confidential OAuth application registered in Redmine. In `oauth-proxy` mode this can be the same app from Step 1; a separate app is only useful for independent credential rotation or clearer audit labels.

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
# Or: REDMINE_INTROSPECT_CLIENT_SECRET_FILE=/run/secrets/redmine_introspect_client_secret

# Optional: /health introspection probe cache TTL in seconds (default 30)
# HEALTH_INTROSPECTION_TTL_SECONDS=30
```

For OAuthProxy mode, use `REDMINE_AUTH_MODE=oauth-proxy` and add a stable proxy signing key:

```bash
REDMINE_AUTH_MODE=oauth-proxy
REDMINE_MCP_JWT_SIGNING_KEY=<stable-random-secret>
# Or: REDMINE_MCP_JWT_SIGNING_KEY_FILE=/run/secrets/redmine_mcp_jwt_signing_key

# Optional: mount this directory to persistent storage in container deployments.
# OAuthProxy stores encrypted state below FASTMCP_HOME/oauth-proxy/.
# FASTMCP_HOME=/app/data/fastmcp

# Optional: restrict which client redirect URIs are accepted (see note below).
# Unset = loopback only. "*" = allow any. Or list patterns for hosted clients.
# REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS=https://app.example.com/*

# Optional: use a separate upstream Redmine OAuth app.
# If unset, REDMINE_INTROSPECT_CLIENT_ID / _SECRET are reused.
# REDMINE_OAUTH_CLIENT_ID=<UID from Redmine>
# REDMINE_OAUTH_CLIENT_SECRET=<Secret from Redmine>
# Or: REDMINE_OAUTH_CLIENT_SECRET_FILE=/run/secrets/redmine_oauth_client_secret
```

Set these in `.env` (local) or `.env.docker` (Docker). Legacy credentials are not needed in OAuth mode.

**Client redirect-URI allowlist:** In `oauth-proxy` mode an MCP client registers its own redirect URI via Dynamic Client Registration. By default the server accepts only loopback targets (`http://localhost:*` and `http://127.0.0.1:*`), which fits local MCP clients (Claude Desktop, Codex CLI, `mcp-remote`) while preventing a registered client from pointing the flow at a remote URL. To support a hosted client with a non-loopback redirect URI, set `REDMINE_MCP_ALLOWED_CLIENT_REDIRECT_URIS` to a comma- or space-separated list of glob patterns (for example `https://app.example.com/*`). Set it to `*` to restore the permissive "accept any redirect URI" behaviour. External consent on Redmine and forwarded PKCE remain in effect regardless of this setting.

**Upstream OAuth client:** When `REDMINE_OAUTH_CLIENT_ID` / `REDMINE_OAUTH_CLIENT_SECRET` are unset, the introspection client (Step 2) is reused as the upstream authorization client. That client therefore needs more than introspection rights: it must have the **authorization code** grant enabled and `${REDMINE_MCP_BASE_URL}/auth/callback` registered as a redirect URI, otherwise `/authorize` fails upstream. This is already true if the introspection client is the Step 1 user-flow app; if you registered a separate introspection-only app, either enable the authorization code grant and redirect URI on it or set `REDMINE_OAUTH_CLIENT_ID` / `REDMINE_OAUTH_CLIENT_SECRET` to a dedicated upstream app.

**Storage and scaling:** OAuthProxy keeps client registrations, in-flight authorization transactions, and upstream-token mappings in an encrypted file store under `FASTMCP_HOME/oauth-proxy/`. This store is **node-local**, so a request that registers on one instance and continues on another will fail. Run `oauth-proxy` mode as a single replica, or with sticky sessions, unless you provide a shared `OAuthProxy` `client_storage` backend. Mounting `FASTMCP_HOME` to a persistent volume addresses durability across restarts but not cross-replica consistency.

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

# RFC 8414 authorization-server metadata
#   oauth mode: served at the /mcp-suffixed path (issuer is the Redmine URL)
#   oauth-proxy mode: served at the root path (issuer is REDMINE_MCP_BASE_URL),
#                     so the /mcp-suffixed URL 404s
curl http://localhost:8000/.well-known/oauth-authorization-server/mcp   # oauth mode
curl http://localhost:8000/.well-known/oauth-authorization-server       # oauth-proxy mode

# OAuthProxy mode also exposes DCR
curl -I http://localhost:8000/register

# /health probes Doorkeeper introspection in OAuth mode
curl http://localhost:8000/health
# {"status": "ok", "checks": {"introspection": "ok"}, ...}
```

If `/health` returns `"status": "degraded"` with `"introspection": "unreachable"`, the introspection client is misconfigured (see Step 2 — verify the client is **confidential** and that the `allow_token_introspection` block in `30-redmine.rb` was applied per Step 2b).

### Endpoints exposed in OAuth mode

In both `oauth` and `oauth-proxy` modes the server exposes the OAuth2 metadata and token-management endpoints that MCP clients rely on:

| Endpoint | Standard | Purpose |
|----------|----------|---------|
| `/.well-known/oauth-protected-resource/mcp` | RFC 9728 §3.1 | Tells clients where to find the authorization server (mounted by FastMCP `RemoteAuthProvider`) |
| `/.well-known/oauth-authorization-server/mcp` | RFC 8414 | Advertises Redmine's Doorkeeper OAuth endpoints, scoped to this MCP resource |
| `POST /revoke` | RFC 7009 | Revokes an OAuth2 token (proxies to Redmine's `/oauth/revoke`) |

Redmine uses the [Doorkeeper](https://github.com/doorkeeper-gem/doorkeeper) gem for OAuth2 but does not serve the RFC 8414 discovery document itself. This server serves path-scoped metadata on Redmine's behalf, pointing to Redmine's real `/oauth/authorize`, `/oauth/token`, and `/oauth/revoke` endpoints.

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
> Use `REDMINE_AUTH_MODE=oauth-proxy` when MCP clients need DCR/CIMD onboarding.

## Scope Enforcement

The server enforces OAuth scopes per tool (on by default). Every MCP
tool maps to the Redmine permission scopes it needs, and a
call is refused with code `INSUFFICIENT_SCOPE` when the access token
does not carry them. `tools/list` only shows the tools the token can
use. Tokens with the `admin` scope bypass the check, matching Redmine's
own semantics.

The authoritative tool-to-scope map is `TOOL_SCOPES` in
`src/redmine_mcp_server/oauth_scopes.py`.

Notes:

- The map gates each tool's base permission. Argument-conditional
  permissions (for example `manage_subtasks` when changing
  `parent_issue_id`, or tag scopes for `tag_list`) are still enforced
  by Redmine itself.
- RedmineUP plugin tools (`manage_product`, `manage_contact`,
  checklists) cannot require plugin scopes because those are not
  advertised; Redmine enforces its own plugin permissions for them.
- A notes-only `update_redmine_issue` call (fields containing nothing but
  `notes` / `private_notes`, no uploads) requires `add_issue_notes` instead
  of `edit_issues`, mirroring Redmine's own note-adding permission.

### Tokens issued before scope enforcement

Tokens obtained before scopes were requested (or from OAuth apps with a
blank scope list) introspect with empty scopes and will be denied for
every tool. Fix: update the OAuth application's scopes in Redmine,
disconnect and re-authorize the MCP client so a new consent grants the
scopes. As a temporary bridge you can set:

```bash
REDMINE_OAUTH_SCOPE_ENFORCEMENT=off
```

which restores the pre-enforcement behavior (any active token can call
any tool) and logs a warning at startup. Re-enable it once clients have
re-consented.

### Cursor and self-AS discovery

Some MCP clients (for example Cursor) discover the authorization server by
probing its canonical RFC 8414 well-known location. Because stock `oauth`
mode names Redmine as the authorization server and no released Redmine
Doorkeeper serves `/.well-known/oauth-authorization-server`, those clients
fail discovery.

Set `REDMINE_OAUTH_DISCOVERY_AS=self` so this server advertises itself as the
authorization server (issuer = `REDMINE_MCP_BASE_URL`) and serves the RFC 8414
document at its own canonical well-known location. Authorize and token
requests still go directly to Redmine `/oauth/authorize` and `/oauth/token`,
so the client keeps using its static confidential client registered in
Redmine. This mode is opt-in; the default `redmine` mode is unchanged.

If the Redmine OAuth Application enables only a subset of permissions, also
set `REDMINE_MCP_SCOPES` to that subset so the advertised `scopes_supported`
matches what the Application can grant and consent does not fail with
`invalid_scope`.

The `oauth-proxy` mode is a different model (this server proxies authorize and
token and issues its own client registrations); it is the alternative when you
want a full authorization-server gateway rather than direct-to-Redmine consent.

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
