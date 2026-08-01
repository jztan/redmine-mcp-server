# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.x     | ✅        |
| 1.x     | ❌        |
| < 1.0   | ❌        |

Only the latest minor release on the 2.x line receives security updates. Fixes may be back-ported to the final 1.x release at the maintainer's discretion if the issue is severe and the gap is small.

## Reporting a Vulnerability

Please report security issues **privately** via **GitHub Security Advisories**: repository **Security** tab, then **Report a vulnerability**. This creates a private discussion between you and the maintainer and gives both sides a clean audit trail.

**Do not** open a public GitHub issue, pull request, or discussion thread for an unpatched security report.

When reporting, please include:

- A description of the issue and the affected version(s).
- Steps to reproduce, or a minimal proof-of-concept.
- Your assessment of the impact and any suggested mitigation.

### Expected response

- Initial acknowledgment within **7 days**.
- Fix or mitigation plan within **30 days** for HIGH severity (authentication bypass, cross-user data exposure, credential leakage). Longer for MEDIUM/LOW.
- Public disclosure coordinated with the reporter once a fix is released. CVE filing is at the maintainer's discretion based on severity and impact.

## Deployment Model

redmine-mcp-server is an HTTP MCP server (streamable HTTP transport) that proxies a Redmine instance. Four authentication modes are supported, selected via `REDMINE_AUTH_MODE` (see the README *Authentication* section):

- **`legacy`** (default): one set of Redmine credentials from the environment. Intended for personal or single-team deployments where every caller is trusted with those credentials.
- **`legacy-per-user`**: each request carries the calling user's own Redmine API key in an `X-Redmine-API-Key` header, behind a TLS-terminating reverse proxy. Opt-in and fail-closed; for Redmine instances older than 6.1. See `docs/legacy-per-user-auth.md`.
- **`oauth`** and **`oauth-proxy`**: per-request OAuth2 Bearer tokens validated against the Redmine server, so each request acts with the calling user's own Redmine permissions. `oauth-proxy` additionally handles DCR/CIMD onboarding for MCP clients. These are the preferred configurations for multi-user deployments on Redmine 6.1+. See `docs/oauth-setup.md`.

When exposed beyond localhost, the server is expected to sit behind TLS (e.g. a reverse proxy). See `docs/oauth-setup.md` and the *Security Best Practices* section of `docs/tool-reference.md`.

## Threat Model

The server routinely handles two classes of sensitive input: caller credentials (API keys, passwords, OAuth tokens) and attacker-controllable Redmine content (issue descriptions, journal notes, wiki pages, search excerpts, attachment names). The following are **in scope** for security reports:

- **Authentication bypass or cross-user leakage in per-user modes** (`oauth`, `oauth-proxy`, `legacy-per-user`). Requests served with another user's client, tokens or keys cached across requests, or middleware paths that skip credential validation.
- **Read-only mode bypass.** Any write operation that succeeds while `REDMINE_MCP_READ_ONLY=true`.
- **File-serving endpoint flaws** at `/files/{file_id}`: path traversal, symlink escape, predictable file IDs, or files served after expiry.
- **Prompt injection boundary escape.** Redmine-derived content is wrapped in `<insecure-content-{boundary}>` tags via `wrap_insecure_content()`; flaws that let attacker content escape or forge the boundary are in scope.
- **Credential exposure.** API keys, passwords, or Bearer tokens leaking into logs, error messages, generated URLs, or tool responses.

**Out of scope:**

- Vulnerabilities in third-party dependencies (python-redmine, FastMCP, httpx, Starlette, etc.). Please report those to their upstream maintainers; we pick up their fixes via dependency bumps.
- Vulnerabilities in the Redmine server itself or its plugins (Agile, Checklists, CRM, Products). Report those to Redmine or the plugin vendor.
- Prompt-injection attacks that succeed because the consuming LLM agent ignores the documented boundary-tag contract. The contract is stated in the tool documentation; downstream non-compliance is a client-side issue.
- Deployments that ignore the documented setup, e.g. exposing the server to untrusted networks without TLS or without OAuth mode, or sharing legacy-mode credentials with untrusted callers.
- Vulnerabilities requiring an attacker to already have write access to the host filesystem or environment configuration.

## Current Hardening Posture

See `docs/tool-reference.md` (*Security Best Practices*, *File Handling Security*, *Read-Only Mode*, and *Prompt Injection Protection* sections) for the runtime contracts users can rely on. The CHANGELOG `### Security` blocks document each release's specific changes. Key measures currently in place: OAuth Bearer tokens validated against Redmine before any request is served, UUID-based time-limited attachment download URLs with automatic cleanup, path traversal protection on file serving, boundary-tag wrapping of untrusted Redmine content, and an opt-in read-only mode that blocks all write operations.
