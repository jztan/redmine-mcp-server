"""FastMCP v3 native auth provider factory for the Redmine MCP server.

Builds a RemoteAuthProvider that:
  - Validates opaque OAuth tokens via Doorkeeper RFC 7662 introspection
    (POST {REDMINE_URL}/oauth/introspect).
  - Mounts RFC 9728 protected-resource metadata at
    /.well-known/oauth-protected-resource/mcp.
  - Advertises scopes_supported from oauth_scopes.advertised_scopes()
    (filtered when REDMINE_MCP_READ_ONLY=true).

The MCP server's introspection client_id/secret are read from
REDMINE_INTROSPECT_CLIENT_ID / REDMINE_INTROSPECT_CLIENT_SECRET. The
client must be registered in Doorkeeper as a confidential client with
protected_resource? permission (or the `introspection` scope) so it can
introspect tokens issued to user-flow OAuth apps. See docs/oauth-setup.md.
"""

import os

from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from pydantic import AnyHttpUrl

from ._env import require_introspection_credentials
from .oauth_scopes import advertised_scopes


def build_remote_auth() -> RemoteAuthProvider:
    """Construct the RemoteAuthProvider for OAuth-mode startup.

    Raises RuntimeError if required env vars are missing — let the server
    fail fast at boot rather than 401 every request.
    """
    redmine_url = (os.environ.get("REDMINE_URL") or "").rstrip("/")
    base_url = (
        os.environ.get("REDMINE_MCP_BASE_URL") or "http://localhost:3040"
    ).rstrip("/")
    if not redmine_url:
        raise RuntimeError(
            "REDMINE_URL must be set for OAuth mode. See docs/oauth-setup.md."
        )

    client_id, client_secret = require_introspection_credentials()

    verifier = IntrospectionTokenVerifier(
        introspection_url=f"{redmine_url}/oauth/introspect",
        client_id=client_id,
        client_secret=client_secret,
        # required_scopes is intentionally unset: today we advertise scopes
        # but do not gate tool calls on them. Per-tool scope enforcement is
        # a follow-up roadmap item.
    )

    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(redmine_url)],
        base_url=base_url,
        scopes_supported=advertised_scopes(),
        resource_name="Redmine MCP Server",
    )
