# Troubleshooting Guide

This guide covers common issues and solutions for the Redmine MCP Server.

## Connection Issues

### Cannot Connect to Redmine Server

**Symptoms:**
- "Connection refused" errors
- "Failed to connect to Redmine" messages
- Server health check fails

**Solutions:**

1. **Verify Redmine URL**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_URL

   # Test connectivity with curl
   curl -I https://your-redmine-server.com
   ```

2. **Check Network Connectivity**
   - Ensure you can reach the Redmine server from your network
   - Verify no firewall blocking the connection
   - Check if VPN is required for access

3. **Verify Redmine Server is Running**
   - Access your Redmine URL in a web browser
   - Check with your Redmine administrator if server is up

### Network Timeout Errors

**Symptoms:**
- Requests timing out
- "Connection timeout" errors

**Solutions:**

1. **Increase Timeout Settings**
   - Add longer timeout values in your configuration
   - Check if Redmine server is slow or overloaded

2. **Check Network Speed**
   - Test your internet connection
   - Consider using local network if possible

### SSL Certificate Errors

**Symptoms:**
- "SSL certificate verify failed" errors
- "CERTIFICATE_VERIFY_FAILED" messages
- "SSL: CERTIFICATE_VERIFY_FAILED" in connection errors
- "SSLError" or "CertificateError" messages

**Solutions:**

1. **Use HTTPS URLs**
   ```bash
   # In .env file
   REDMINE_URL=https://your-redmine-server.com  # Not http://
   ```

2. **Self-Signed Certificates**

   If your Redmine server uses a self-signed certificate or internal CA, configure the custom CA certificate:

   ```bash
   # In .env file
   REDMINE_URL=https://redmine.company.com
   REDMINE_API_KEY=your_api_key
   REDMINE_SSL_CERT=/path/to/ca-certificate.crt
   ```

   **Supported certificate formats:** `.pem`, `.crt`, `.cer`

   **Obtaining the certificate:**
   ```bash
   # Export certificate from browser (Chrome/Firefox)
   # Or get from system administrator

   # Or download from server (if accessible)
   openssl s_client -connect redmine.company.com:443 -showcerts < /dev/null 2>/dev/null | \
     openssl x509 -outform PEM > ca-cert.pem
   ```

3. **Mutual TLS (Client Certificates)**

   For environments requiring client certificate authentication:

   **Option A: Separate certificate and key files**
   ```bash
   # In .env file
   REDMINE_URL=https://secure.redmine.com
   REDMINE_API_KEY=your_api_key
   REDMINE_SSL_CERT=/path/to/ca-bundle.pem
   REDMINE_SSL_CLIENT_CERT=/path/to/cert.pem,/path/to/key.pem
   ```

   **Option B: Combined certificate file**
   ```bash
   # In .env file
   REDMINE_SSL_CLIENT_CERT=/path/to/combined-cert.pem
   ```

   **Important:** Private keys must be unencrypted (Python requests library requirement)

   **Removing password from encrypted key:**
   ```bash
   openssl rsa -in encrypted-key.pem -out unencrypted-key.pem
   ```

4. **Disable SSL Verification (Development Only)**

   ⚠️ **WARNING:** Only use in development/testing environments!

   ```bash
   # In .env file
   REDMINE_SSL_VERIFY=false
   ```

   Disabling SSL verification makes your connection vulnerable to man-in-the-middle attacks. Never use in production.

5. **Certificate File Not Found**

   **Symptoms:**
   - "SSL certificate not found: /path/to/cert.pem"
   - "FileNotFoundError" for certificate path

   **Solutions:**
   - Verify the certificate file path is correct
   - Use absolute paths instead of relative paths
   - Check file permissions (must be readable)
   ```bash
   # Verify certificate file exists
   ls -la /path/to/ca-cert.pem

   # Check file permissions
   chmod 644 /path/to/ca-cert.pem
   ```

6. **Certificate Path is a Directory**

   **Symptoms:**
   - "SSL certificate path must be a file, not directory"

   **Solutions:**
   - Specify the actual certificate file, not the directory
   ```bash
   # Wrong
   REDMINE_SSL_CERT=/etc/ssl/certs/

   # Correct
   REDMINE_SSL_CERT=/etc/ssl/certs/ca-bundle.crt
   ```

7. **Certificate Validation Errors with Custom CA**

   **Symptoms:**
   - Still getting SSL errors even with `REDMINE_SSL_CERT` configured

   **Solutions:**
   - Verify you have the correct CA certificate (not the server certificate)
   - Ensure certificate chain is complete
   - Test certificate validation:
   ```bash
   # Test SSL connection with custom CA
   openssl s_client -connect redmine.company.com:443 \
     -CAfile /path/to/ca-cert.pem
   ```

8. **Docker Deployment SSL Configuration**

   When using Docker, mount certificates into container:

   ```bash
   # In docker-compose.yml
   volumes:
     - ./certs:/certs:ro
   ```

   ```bash
   # In .env.docker
   REDMINE_SSL_CERT=/certs/ca-cert.pem
   REDMINE_SSL_CLIENT_CERT=/certs/client-cert.pem,/certs/client-key.pem
   ```

**Troubleshooting Checklist:**
- [ ] Verified `REDMINE_URL` uses `https://`
- [ ] Certificate file exists at specified path
- [ ] Certificate file is readable (permissions 644 or similar)
- [ ] Using correct CA certificate (not server certificate)
- [ ] For mutual TLS: client private key is unencrypted
- [ ] For Docker: certificates mounted into container
- [ ] Tested SSL connection with `openssl s_client`

**See also:** [README.md - SSL Certificate Configuration](../README.md#ssl-certificate-configuration) for configuration examples.

---

## Authentication Issues

### Server Unexpectedly Requires OAuth / "unauthorized" Error

**Symptoms:**
- MCP client fails to connect with `{"error":"unauthorized"}`
- Server returns `401 Unauthorized` with a `WWW-Authenticate: Bearer` header
- Health endpoint shows `"auth_mode":"oauth"` or `"auth_mode":"oauth-proxy"` when you expected legacy mode

**Cause:** The server is running in OAuth mode (`REDMINE_AUTH_MODE=oauth` or `REDMINE_AUTH_MODE=oauth-proxy`) instead of legacy mode. This can happen if:
- `REDMINE_AUTH_MODE` is set in your shell environment (e.g., via `export`), which takes precedence over `.env`
- The `.env` file doesn't explicitly set `REDMINE_AUTH_MODE=legacy`, and a shell variable overrides the default
- The server was started with a previous configuration and hasn't been restarted after changes

**Solutions:**

1. **Check current auth mode**
   ```bash
   # Query the health endpoint
   curl http://localhost:8000/health
   # Look for "auth_mode" in the response
   ```

2. **Check for shell environment overrides**
   ```bash
   # Shell env vars take precedence over .env file
   echo $REDMINE_AUTH_MODE

   # If set, unset it
   unset REDMINE_AUTH_MODE
   ```

3. **Explicitly set auth mode in `.env`**
   ```bash
   # Add to your .env file
   REDMINE_AUTH_MODE=legacy
   ```

4. **Restart the server**
   - Configuration changes require a server restart
   - The auth mode is determined at startup and cannot change at runtime
   ```bash
   # Find and stop the running server
   lsof -i :8000
   kill <PID>

   # Restart
   redmine-mcp-server
   ```

5. **Verify after restart**
   - Check server startup logs for: `Auth mode: legacy`
   - Query health endpoint to confirm: `curl http://localhost:8000/health`

### API Key Not Working

**Symptoms:**
- "401 Unauthorized" errors
- "Invalid API key" messages

**Solutions:**

1. **Verify API Key**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_API_KEY
   ```

2. **Generate New API Key**
   - Log into Redmine web interface
   - Go to "My Account" → "API access key"
   - Click "Show" to view or "Reset" to generate new key
   - Update `.env` with new key

3. **Check API Access is Enabled**
   - Ensure Redmine administrator has enabled REST API
   - Check in Redmine: Administration → Settings → API → "Enable REST web service"

4. **Confirm credentials with the health endpoint (legacy mode)**
   ```bash
   curl http://localhost:8000/health
   ```
   In legacy mode, `/health` probes Redmine with the configured credentials and reports the result under `checks.redmine`:
   - `"redmine": "ok"`: credentials accepted and Redmine reachable.
   - `"redmine": "unreachable"` with `"status": "degraded"`: credentials are present but Redmine rejected them or could not be reached (see `checks.redmine_detail`, e.g. `HTTP 401`).
   - `"redmine": "unconfigured"` with `"status": "ok"`: `REDMINE_URL` or credentials are not set yet (not a runtime failure).

   The response is always HTTP 200 so orchestrators keep treating it as a binary liveness probe; inspect the JSON `status` field for the real state.

### Username/Password Authentication Failed

**Symptoms:**
- "Authentication failed" errors when using username/password

**Solutions:**

1. **Verify Credentials**
   ```bash
   # Check your .env file
   cat .env | grep REDMINE_USERNAME
   cat .env | grep REDMINE_PASSWORD
   ```

2. **Test Credentials**
   - Try logging into Redmine web interface with same credentials
   - Reset password if needed

3. **Use API Key Instead**
   - API key authentication is recommended over username/password
   - More secure and doesn't require password storage

### Permission Denied Errors

**Symptoms:**
- "403 Forbidden" errors
- "You are not authorized to access this resource"

**Solutions:**

1. **Check User Permissions**
   - Verify your Redmine user has necessary project roles
   - Contact project administrator to grant permissions

2. **Project Visibility**
   - Ensure projects are not private or restricted
   - Check project membership settings

---

## Installation Issues

### Import Errors

**Symptoms:**
- `ModuleNotFoundError` or `ImportError`
- "No module named 'redmine_mcp_server'"

**Solutions:**

1. **Install Dependencies**
   ```bash
   # For source installation
   uv pip install -e .

   # For PyPI installation
   pip install redmine-mcp-server
   ```

2. **Activate Virtual Environment**
   ```bash
   # If using virtual environment
   source .venv/bin/activate
   ```

3. **Reinstall Package**
   ```bash
   pip uninstall redmine-mcp-server
   pip install redmine-mcp-server
   ```

### Dependency Conflicts

**Symptoms:**
- "Dependency conflict" errors
- Package version incompatibility errors

**Solutions:**

1. **Use Fresh Virtual Environment**
   ```bash
   # Create new virtual environment
   python -m venv .venv
   source .venv/bin/activate
   pip install redmine-mcp-server
   ```

2. **Update pip and setuptools**
   ```bash
   pip install --upgrade pip setuptools
   ```

### Python Version Incompatibility

**Symptoms:**
- "Python version not supported" errors
- Syntax errors in code

**Solutions:**

1. **Check Python Version**
   ```bash
   python --version  # Should be 3.10 or higher
   ```

2. **Install Correct Python Version**
   - Python 3.10+ required for local installation
   - Use Docker deployment if Python upgrade not possible

---

## Runtime Issues

### Port Conflicts

**Symptoms:**
- "Address already in use" errors
- "Port 8000 is already allocated"

**Solutions:**

1. **Change Server Port**
   ```bash
   # In .env file
   SERVER_PORT=8001  # Use different port
   ```

2. **Find Process Using Port**
   ```bash
   # On macOS/Linux
   lsof -i :8000

   # Kill process if needed
   kill -9 <PID>
   ```

3. **Use Docker Port Mapping**
   ```bash
   # Map to different external port
   docker run -p 8001:8000 redmine-mcp-server
   ```

### File Permission Errors

**Symptoms:**
- "Permission denied" when accessing attachments
- Cannot write to attachments directory

**Solutions:**

1. **Check Directory Permissions**
   ```bash
   # Ensure attachments directory is writable
   chmod 755 ./attachments
   ```

2. **Configure Custom Directory**
   ```bash
   # In .env file
   ATTACHMENTS_DIR=/path/to/writable/directory
   ```

### Attachment Download Failures

**Symptoms:**
- "Failed to download attachment" errors
- File download URLs expire immediately

**Solutions:**

1. **Check Disk Space**
   ```bash
   df -h  # Ensure sufficient space in attachments directory
   ```

2. **Verify Redmine Permissions**
   - Ensure your Redmine user can access attachments
   - Check attachment exists in Redmine

3. **Configure Expiry Time**
   ```bash
   # In .env file
   ATTACHMENT_EXPIRES_MINUTES=120  # Increase expiry time
   ```

4. **Download Cap Exceeded**
   ```
   {"error": "Attachment N exceeds the 209715200-byte download limit."}
   ```
   Default 200 MB cap. Bump for known-large files:
   ```bash
   ATTACHMENT_MAX_DOWNLOAD_BYTES=524288000  # 500 MB
   ```
   The cap is enforced mid-stream and the partial file is deleted on abort, so a too-large attachment doesn't leak storage.

### Attachment `content_url` Returns Unreachable Internal Hostname

**Symptoms:**
- `get_redmine_issue(include_attachments=True)` returns `content_url` like `http://redmine:3000/attachments/...`
- The URL is unreachable from your MCP client (host or open internet)
- Agent may waste a turn `web_fetch`-ing the unreachable URL

**Cause:** Redmine echoes back URLs built from its own configured hostname, which in Docker / reverse-proxy deployments is typically the internal service name. The bare API can't see your public hostname.

**Solution:** set `REDMINE_PUBLIC_URL` to the publicly-reachable URL of your Redmine instance. When set, attachment `content_url` values whose origin matches `REDMINE_URL` are rewritten to the public origin (preserving path / query / fragment / reverse-proxy subpath).

```bash
# In .env file
REDMINE_URL=http://redmine:3000              # internal, used by MCP server
REDMINE_PUBLIC_URL=https://redmine.example.com  # public, returned to clients
```

For subpath-mounted Redmine (`https://example.com/redmine/...`), pass the full URL including the prefix:

```bash
REDMINE_PUBLIC_URL=https://example.com/redmine
```

**Alternative:** if you can't configure a public URL, call `get_redmine_attachment(attachment_id=N)` instead. That tool downloads the bytes server-side and returns either an HTTP URL on the MCP server's own proxy (HTTP mode) or a local file path (stdio mode) — both reachable from your client regardless of Redmine's hostname configuration.

### Agile Fields Missing from Issue Results

**Symptoms:**
- `story_points`, `agile_sprint_id`, `agile_position` not present in `get_redmine_issue` response even though `REDMINE_AGILE_ENABLED=true`

**Solutions:**

1. **Verify `REDMINE_AGILE_ENABLED` is set correctly**
   ```bash
   # In .env file
   REDMINE_AGILE_ENABLED=true
   ```

2. **Grant Agile permissions to the user's role**
   - Go to **Administration → Roles and permissions**
   - Click the role assigned to your API user
   - Scroll to the **Agile** section and check the relevant permissions (e.g. `View board`)
   - Save — without this, the agile endpoint returns 403 even if the module is enabled

3. **Enable the Agile module for the project**
   - Go to Project Settings → Modules in Redmine
   - Check the **Agile** checkbox and save
   - Without this, the agile endpoint returns 403 and fields are silently omitted

4. **Verify the RedmineUP Agile plugin is installed**
   - Access your Redmine administration panel
   - Go to Administration → Plugins and confirm the Agile plugin is listed

### Custom Field Named "story_points" Cannot Be Updated by Name

**Symptoms:**
- Passing `{"story_points": "value"}` in `update_redmine_issue` has no effect on the custom field
- The update succeeds but the custom field value does not change

**Cause:**
The key `story_points` is reserved — it is intercepted before custom field resolution regardless of whether `REDMINE_AGILE_ENABLED` is set. When the plugin is disabled, the value is silently dropped; when enabled, it is routed to the Agile endpoint.

**Solution:**
Use the explicit `custom_fields` format with the field's numeric ID:
```python
update_redmine_issue(
    issue_id=123,
    fields={
        "custom_fields": [{"id": 42, "value": "8"}]
    }
)
```
Find the field ID via `list_project_issue_custom_fields(project_id)`.

### Agile Story Points Update Fails

**Symptoms:**
- `update_redmine_issue` with `story_points` returns an error
- Error message mentions "Story points is invalid"

**Solutions:**

1. **Use a non-negative integer or `null`**
   - Valid values: `0`, `1`, `5`, `8`, etc.
   - Pass `null` to clear story points
   - Negative values (e.g. `-1`) are rejected by Redmine with a 422 error

2. **Check the Agile module is enabled for the project** (see above)

### Memory or Performance Issues

**Symptoms:**
- Slow response times
- High memory usage
- Server crashes

**Solutions:**

1. **Enable Automatic Cleanup**
   ```bash
   # In .env file
   AUTO_CLEANUP_ENABLED=true
   CLEANUP_INTERVAL_MINUTES=10
   ```

2. **Monitor Resource Usage**
   ```bash
   # Check server resources
   docker stats  # For Docker deployment
   htop  # For local deployment
   ```

3. **Reduce Pagination Limits**
   - Use smaller `limit` values in `list_redmine_issues`
   - Default limit is 25 to prevent token overflow

---

## MCP Client Issues

### Server Not Appearing in MCP Client

**Symptoms:**
- Redmine server not listed in client
- Configuration not recognized

**Solutions:**

1. **Verify Configuration Format**
   - Check configuration matches your client's format
   - See [MCP Client Configuration](../README.md#mcp-client-configuration)

2. **Restart MCP Client**
   - Reload VS Code or restart your MCP client
   - Configuration changes may require restart

3. **Check Server is Running**
   ```bash
   # Test health endpoint
   curl http://localhost:8000/health
   ```

### Tools Not Loading

**Symptoms:**
- MCP client connected but no tools available
- "No tools found" messages

**Solutions:**

1. **Verify Server Started Correctly**
   ```bash
   # Check server logs for errors
   redmine-mcp-server
   ```

2. **Test MCP Endpoint**
   ```bash
   # Should return MCP protocol response
   curl http://localhost:8000/mcp
   ```

3. **Reload Client Configuration**
   - Run MCP client's reload/refresh command
   - Reconnect to server

### Deployment Lag — Recently-shipped Tool or Fix Doesn't Appear

**Symptoms:**
- You merged a fix to `develop` (or pulled a release) but the running MCP server still returns the old behavior
- A newly-added tool isn't in the MCP client's tool list
- A docker container shows the right version in `--version` but exposes the old surface

**Cause:** new MCP tools are registered at server *startup* via `@mcp.tool()` decorators, which only run when the Python process loads the module. Behavior changes inside existing tools usually propagate without a restart (the function references in the module are the same), but **new tool registrations require restarting the server process**. In Docker, a bare `docker container restart` re-runs the same image — it doesn't pick up code changes; you need a rebuild.

**Diagnosis:** call `get_mcp_server_info` to read the deployed package version:

```python
get_mcp_server_info()
# -> {"server_version": "1.3.0", "read_only_mode": false, "auth_mode": "legacy",
#     "plugin_flags": {...}}
```

Compare `server_version` against the release / commit you expect. If they don't match, the deployment is stale.

**Solutions:**

1. **Docker (recommended path):** run `./deploy.sh` from the repo root. It rebuilds the image with current source, removes the old container, and starts a fresh one with the correct port mapping (`-p 8000:8000`) and env-file.

   ```bash
   ./deploy.sh
   ```

2. **Docker without the script:**
   ```bash
   docker compose down
   docker compose up -d --build   # --build is the important flag
   ```

   Without `--build`, Docker reuses the cached image, which still has the old code baked in.

3. **Local Python process:** stop the running `redmine-mcp-server` / `uv run python -m redmine_mcp_server.main` and start it again. Editable installs (`uv pip install -e .`) reflect source changes on the next process start.

4. **After restart, reconnect from the client.** In Claude Code, the `/mcp` command refreshes the tool list. Without that step, the client may still show the stale schema even after the server picked up the new code.

### HTTP Transport Errors

**Symptoms:**
- "HTTP transport not supported" errors
- "HTTP transport failed" messages

**Solutions:**

1. **Use HTTP-to-stdio Bridge** (for clients with limited HTTP support)
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

2. **Verify Client Supports HTTP**
   - Check your MCP client's documentation
   - Some clients require specific transport types

---

## Debug & Logging

### Enable Debug Mode

**For Source Installation:**

Edit `src/redmine_mcp_server/main.py`:
```python
# Set debug mode
mcp.settings.debug = True
```

**For Docker Deployment:**

Add to `.env.docker`:
```bash
DEBUG=true
```

### View Server Logs

**Local Deployment:**
```bash
# Logs appear in terminal where server is running
redmine-mcp-server
```

**Docker Deployment:**
```bash
# View container logs
docker logs <container-id>

# Follow logs in real-time
docker logs -f <container-id>
```

### Common Error Messages

#### "redmine client not initialized"

**Cause:** Environment variables not loaded or invalid credentials

**Solution:**
1. Check `.env` file exists and has correct values
2. Verify credentials are valid
3. Ensure `REDMINE_URL` is set

#### "File not found or expired"

**Cause:** Attachment file was cleaned up or URL expired

**Solution:**
1. Re-download the attachment using `get_redmine_attachment`
2. Increase `ATTACHMENT_EXPIRES_MINUTES` in `.env`

#### "Token limit exceeded"

**Cause:** Too many results returned causing MCP token overflow

**Solution:**
1. Use smaller `limit` values in `list_redmine_issues`
2. Use pagination with `offset` parameter
3. Filter results with specific parameters
4. Use `journal_limit` on `get_redmine_issue` to paginate large journal lists

#### "This server is in read-only mode"

**Cause:** The `REDMINE_MCP_READ_ONLY` environment variable is set to `true`, blocking all write operations

**Solution:**
1. If you need write access, set the variable to `false` or remove it:
   ```bash
   # In .env file
   REDMINE_MCP_READ_ONLY=false
   ```
2. If read-only is intentional (e.g., shared/demo instance), use only read tools:
   - `get_redmine_issue`, `list_redmine_issues`, `list_redmine_projects`, `search_redmine_issues`, `search_entire_redmine`, `manage_redmine_wiki_page(action="list"|"get")`, etc.
3. Blocked tools in read-only mode: `create_redmine_issue`, `update_redmine_issue`, plus the write actions of every `manage_X` tool (e.g., `manage_redmine_wiki_page(action="create"|"update"|"delete"|"rename")`, `manage_issue_category(action="create"|"update"|"delete")`, `manage_project_member`, `manage_issue_watcher`, `manage_issue_note`, `manage_time_entry`, `manage_product(action="create"|"update")`, `manage_contact(action="create"|"update"|"delete"|"assign_to_project"|"remove_from_project")`). See [Read-Only Mode](./tool-reference.md#read-only-mode) in the tool reference for the full breakdown.

#### "list_my_redmine_issues not found" / Import errors after upgrade

**Cause:** `list_my_redmine_issues` was removed in v1.0.0

**Solution:**
- Replace all usage with `list_redmine_issues(assigned_to_id='me')`
- The replacement supports the same filters and pagination options

---

## Getting Additional Help

If your issue isn't covered here:

1. **Check GitHub Issues**
   - Search existing issues: https://github.com/jztan/redmine-mcp-server/issues
   - Look for similar problems and solutions

2. **Create New Issue**
   - Provide detailed description of the problem
   - Include error messages and logs
   - Specify your environment (Python version, OS, deployment method)

3. **Review Documentation**
   - [README](../README.md) - Setup and configuration
   - [Tool Reference](./tool-reference.md) - Tool usage details
   - [Contributing](./contributing.md) - Development information

4. **Community Support**
   - Check MCP community resources
   - Review python-redmine library documentation

## OAuth Mode (v2.1+: FastMCP Native Auth Migration)

### Symptom: every MCP request returns 401 (even with a valid bearer)

Native OAuth authentication validates Bearer tokens via Doorkeeper's `/oauth/introspect` endpoint (RFC 7662). If every request returns 401, the cause is usually one of:

1. **Introspection env vars not set.** The server fails fast at startup if `REDMINE_INTROSPECT_CLIENT_ID` or `REDMINE_INTROSPECT_CLIENT_SECRET` is missing in OAuth mode — re-check startup logs.
2. **Introspection client not authorized.** Per RFC 7662 §2.1, a client may introspect tokens only when it is either the token's issuer, holds the `introspection` scope, or matches an `allow_token_introspection` block. Stock Redmine ships with `allow_token_introspection false`. See `docs/oauth-setup.md` Step 2b for the in-place edit of `30-redmine.rb` that grants introspection rights to confidential clients.
3. **Doorkeeper introspection disabled in Redmine's default config.** Redmine ships `allow_token_introspection false`, which makes the `/oauth/introspect` route return 404. Verify with the curl test in `docs/oauth-setup.md` Step 2c.
4. **A standalone `Doorkeeper.configure` initializer silently wiped Redmine's config.** Symptom: Administration → Applications also returns 403 with the log line *"Access to admin panel is forbidden due to Doorkeeper.configure.admin_authenticator being unconfigured"*. Fix: remove any standalone `Doorkeeper.configure` block from `config/initializers/`; apply the introspection change in-place in `30-redmine.rb` instead. See `docs/oauth-setup.md` Step 2b for the why (Doorkeeper's `configure` rebuilds the entire config wholesale).
5. **Token expired.** Check the bearer's `exp` against current time; mint a fresh one if needed.

**Quick diagnostic:** hit `/health` on the MCP server. If `"status": "degraded"` with `"introspection": "unreachable"`, the problem is server-side (introspection endpoint or credentials). If `"status": "ok"`, the introspection client itself works, so the problem is per-token (expired, wrong app, etc.).

### Symptom: `/health` reports `"introspection": "unreachable"`

Likely causes, in order:

- `REDMINE_URL` unreachable from the MCP server's network.
- `REDMINE_INTROSPECT_CLIENT_*` credentials wrong (Doorkeeper returns HTTP 401 on the introspection POST).
- Doorkeeper introspection endpoint disabled.
- TLS verification failing (check `REDMINE_SSL_VERIFY` / `REDMINE_SSL_CERT`).

The probe result is cached for `HEALTH_INTROSPECTION_TTL_SECONDS` (default 30 seconds). Wait that long after fixing the underlying issue before re-checking `/health`.

### Symptom: clients see 401 where they used to see 503

This is by design after the FastMCP v3 auth migration. The previous middleware returned `503 upstream_unavailable` when Redmine was unreachable for token validation; FastMCP's `IntrospectionTokenVerifier` treats transport failures as auth failures and returns 401. Operators monitoring for 503 spikes should switch to:

- Watching `/health` for `"status": "degraded"`, OR
- Monitoring 401-rate spikes correlated with Redmine availability metrics.

### Emergency rollback from OAuth mode

If an OAuth-mode regression is impacting users and a fix is not immediate, fall back to legacy mode without redeploying a previous version:

1. Set `REDMINE_AUTH_MODE=legacy` in the environment.
2. Provide `REDMINE_API_KEY` (or `REDMINE_USERNAME` + `REDMINE_PASSWORD`).
3. Restart the MCP server.

Legacy mode is preserved across versions and behaves identically to pre-OAuth deployments. Clients lose per-user scoping but regain availability.

If a legacy API key isn't available, revert to the previous application version via standard release rollback procedures (`RELEASE_SOP.md`).

### Symptom: clients fetching `/.well-known/oauth-protected-resource` (without `/mcp`) get 404

The v2.1+ release dropped several discovery path aliases. Only these paths remain:

- `GET /.well-known/oauth-protected-resource/mcp` (canonical RFC 9728 §3.1 suffix-scoped form, mounted by `RemoteAuthProvider`)
- `GET /.well-known/oauth-authorization-server/mcp` (path-scoped RFC 8414 form, mirrors Redmine's Doorkeeper AS metadata in direct OAuth mode)

In `REDMINE_AUTH_MODE=oauth-proxy`, the authorization-server metadata describes FastMCP's OAuthProxy endpoints instead.

Clients should follow `WWW-Authenticate: Bearer resource_metadata="..."` headers from 401 responses (RFC 9728 §5.3) rather than guessing paths. If a client hardcodes the dropped variants, update the client; we don't plan to restore aliases.
