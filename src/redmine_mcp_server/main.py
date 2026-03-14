"""
Main entry point for the MCP Redmine server.

This module uses FastMCP's native streamable HTTP transport for MCP protocol
communication.
The server runs with built-in HTTP endpoints and handles MCP requests natively.

Endpoints:
    - /mcp: Handles MCP requests via streamable HTTP transport.

Modules:
    - .redmine_handler: Contains the MCP server logic with FastMCP integration.
"""

import logging
import os
import uvicorn
import httpx
from importlib.metadata import version, PackageNotFoundError
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure basic logging before importing modules that log during init
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from .redmine_handler import mcp  # noqa: E402
from .oauth_middleware import RedmineOAuthMiddleware  # noqa: E402

logger = logging.getLogger(__name__)

REDMINE_URL = os.environ.get("REDMINE_URL", "").rstrip("/")
REDMINE_MCP_BASE_URL = os.environ.get(
    "REDMINE_MCP_BASE_URL", "http://localhost:3040"
).rstrip("/")
REDMINE_AUTH_MODE = os.environ.get("REDMINE_AUTH_MODE", "legacy").lower()


def get_version() -> str:
    """Get package version from metadata."""
    try:
        return version("redmine-mcp-server")
    except PackageNotFoundError:
        return "dev"


# --- OAuth2 route handlers (registered conditionally) ---


async def oauth_protected_resource(request: Request):
    """RFC 8707 — Protected Resource Metadata."""
    return JSONResponse(
        {
            "resource": f"{REDMINE_MCP_BASE_URL}/mcp",
            "authorization_servers": [REDMINE_MCP_BASE_URL],
            "bearer_methods_supported": ["header"],
            "resource_name": "Redmine MCP Server",
        }
    )


async def oauth_authorization_server(request: Request):
    """RFC 8414 — Authorization Server Metadata.

    Redmine uses Doorkeeper but does not serve this discovery document itself.
    We serve it manually, pointing to Redmine's real Doorkeeper endpoints.
    """
    return JSONResponse(
        {
            "issuer": REDMINE_MCP_BASE_URL,
            "authorization_endpoint": f"{REDMINE_URL}/oauth/authorize",
            "token_endpoint": f"{REDMINE_URL}/oauth/token",
            "revocation_endpoint": f"{REDMINE_URL}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
            ],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        }
    )


async def revoke_token(request: Request):
    """RFC 7009 — Revoke an OAuth2 access or refresh token.

    Proxies token revocation to Redmine's Doorkeeper /oauth/revoke endpoint.

    Accepts token via:
    - Authorization header: Bearer <token>
    - POST body: {"token": "<token>"} or form-encoded token=<token>

    Returns:
        200 OK on success (per RFC 7009, even if token was already invalid)
        400 Bad Request if no token provided
        502 Bad Gateway if Redmine is unreachable
    """
    token = None

    # Try Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()

    # Fall back to request body
    if not token:
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                token = body.get("token")
            except Exception:
                pass
        else:
            # form-encoded
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

    # Forward revocation to Redmine's Doorkeeper endpoint
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{REDMINE_URL}/oauth/revoke",
                data={"token": token},
                timeout=10,
            )
        except httpx.RequestError as e:
            logger.error(f"Failed to reach Redmine for token revocation: {e}")
            return JSONResponse(
                status_code=502,
                content={"error": "upstream_unavailable"},
            )

    # RFC 7009: return 200 regardless of whether token was valid
    # (to prevent token scanning attacks)
    if response.status_code in (200, 204):
        return JSONResponse(status_code=200, content={"success": True})

    # If Redmine returns an error, log but still return success per RFC 7009
    logger.warning(
        f"Redmine revocation returned {response.status_code}: " f"{response.text}"
    )
    return JSONResponse(status_code=200, content={"success": True})


def register_oauth_routes(target_app):
    """Register OAuth2 discovery and revocation routes on a Starlette app."""
    target_app.add_route(
        "/.well-known/oauth-protected-resource",
        oauth_protected_resource,
        methods=["GET"],
    )
    target_app.add_route(
        "/.well-known/oauth-authorization-server",
        oauth_authorization_server,
        methods=["GET"],
    )
    target_app.add_route("/revoke", revoke_token, methods=["POST"])


# Export the Starlette/FastAPI app for testing and external use
app = mcp.streamable_http_app()

# Register OAuth2 middleware and endpoints only when auth mode is oauth
if REDMINE_AUTH_MODE == "oauth":
    app.add_middleware(RedmineOAuthMiddleware)
    register_oauth_routes(app)


def main():
    """Main entry point for the console script."""
    # Note: .env is already loaded during redmine_handler import

    # Log version and auth mode at startup
    server_version = get_version()
    logger.info(f"Redmine MCP Server v{server_version}")
    logger.info(f"Auth mode: {REDMINE_AUTH_MODE}")

    # Enable stateless HTTP mode (checked at request time by FastMCP)
    mcp.settings.stateless_http = True

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    # Run with our app directly so custom routes (well-known endpoints) are served
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
