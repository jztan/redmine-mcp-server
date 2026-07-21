"""FastMCP v3 native auth provider factory for the Redmine MCP server.

Builds a RemoteAuthProvider that:
  - Validates opaque OAuth tokens via Doorkeeper RFC 7662 introspection
    (POST {REDMINE_URL}/oauth/introspect).
  - Mounts RFC 9728 protected-resource metadata at
    /.well-known/oauth-protected-resource/mcp.
  - Advertises scopes_supported from oauth_scopes.configured_advertised_scopes()
    (filtered by REDMINE_MCP_READ_ONLY and REDMINE_MCP_SCOPES).

The MCP server's introspection client_id/secret are read from
REDMINE_INTROSPECT_CLIENT_ID / REDMINE_INTROSPECT_CLIENT_SECRET. The
client must be registered in Doorkeeper as a confidential client, and
Doorkeeper's ``allow_token_introspection`` block must permit it to
introspect tokens issued to user-flow OAuth apps (stock Redmine sets
this to ``false`` and must be patched). See docs/oauth-setup.md Step 2.
"""

from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import cors_middleware
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import httpx
import logging
import os
from urllib.parse import urlparse

from ._env import require_introspection_credentials, _oauth_discovery_as
from .oauth_scopes import configured_advertised_scopes

logger = logging.getLogger(__name__)


class RedmineAuthProvider(RemoteAuthProvider):
    """Remote auth provider plus Redmine-specific OAuth helper routes."""

    def __init__(
        self,
        *,
        redmine_url: AnyHttpUrl,
        base_url: str,
        introspect_client_id: str,
        introspect_client_secret: str,
        scopes_supported: list[str],
        discovery_as: str = "redmine",
    ):
        self.redmine_url = redmine_url
        self.discovery_as = discovery_as
        # In self-AS mode the MCP server is the authorization server that
        # clients discover (issuer = base_url); authorize/token still target
        # Redmine. In redmine mode the issuer names Redmine (post-#140).
        issuer_source = base_url if discovery_as == "self" else str(redmine_url)
        self.issuer = AnyHttpUrl(issuer_source)
        verifier = IntrospectionTokenVerifier(
            introspection_url=str(self.redmine_endpoint("/oauth/introspect")),
            client_id=introspect_client_id,
            client_secret=introspect_client_secret,
            # required_scopes is intentionally unset: it would apply a
            # global AND over every token. Per-tool enforcement lives in
            # ScopeEnforcementMiddleware (#185).
        )

        super().__init__(
            token_verifier=verifier,
            authorization_servers=[self.issuer],
            base_url=base_url,
            scopes_supported=scopes_supported,
            resource_name="Redmine MCP Server",
        )

    def redmine_endpoint(self, path: str) -> AnyHttpUrl:
        """Build a Redmine OAuth endpoint URL from the configured Redmine URL."""
        return AnyHttpUrl(
            f"{str(AnyHttpUrl(self.redmine_url)).rstrip('/')}/{path.lstrip('/')}"
        )

    async def oauth_authorization_server(self, request: Request):
        """RFC 8414 authorization-server metadata for Redmine Doorkeeper."""
        metadata = OAuthMetadata(
            issuer=self.issuer,
            authorization_endpoint=self.redmine_endpoint("/oauth/authorize"),
            token_endpoint=self.redmine_endpoint("/oauth/token"),
            revocation_endpoint=self.redmine_endpoint("/oauth/revoke"),
            response_types_supported=["code"],
            grant_types_supported=[
                "authorization_code",
                "refresh_token",
            ],
            code_challenge_methods_supported=["S256"],
            token_endpoint_auth_methods_supported=[
                "client_secret_post",
                "client_secret_basic",
            ],
            scopes_supported=self._scopes_supported,
        )
        return await MetadataHandler(metadata).handle(request)

    async def revoke_token(self, request: Request):
        """Proxy RFC 7009 token revocation to Redmine's Doorkeeper endpoint."""
        token = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()

        if not token:
            content_type = request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    body = await request.json()
                    token = body.get("token")
                except Exception:
                    pass
            else:
                try:
                    form = await request.form()
                    token = form.get("token")
                except Exception:
                    pass

        if not token:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "No token provided",
                },
            )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    str(self.redmine_endpoint("/oauth/revoke")),
                    data={"token": token},
                    timeout=10,
                )
            except httpx.RequestError as e:
                logger.error(f"Failed to reach Redmine for token revocation: {e}")
                return JSONResponse(
                    status_code=502,
                    content={"error": "upstream_unavailable"},
                )

        if response.status_code not in (200, 204):
            logger.warning(
                f"Redmine revocation returned {response.status_code}: "
                f"{response.text}"
            )

        return JSONResponse(status_code=200, content={"success": True})

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        base_path = urlparse(str(self.base_url)).path.rstrip("/")
        metadata_path = f"{base_path}{mcp_path or ''}"

        routes.append(
            Route(
                f"/.well-known/oauth-authorization-server{metadata_path}",
                endpoint=cors_middleware(
                    self.oauth_authorization_server, ["GET", "OPTIONS"]
                ),
                methods=["GET", "OPTIONS"],
            )
        )
        routes.append(Route("/revoke", self.revoke_token, methods=["POST"]))
        return routes


def build_remote_auth() -> RedmineAuthProvider:
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

    return RedmineAuthProvider(
        redmine_url=AnyHttpUrl(redmine_url),
        base_url=base_url,
        introspect_client_id=client_id,
        introspect_client_secret=client_secret,
        scopes_supported=configured_advertised_scopes(),
        discovery_as=_oauth_discovery_as(),
    )
