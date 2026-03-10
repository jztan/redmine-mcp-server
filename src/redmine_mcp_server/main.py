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

REDMINE_URL = os.environ["REDMINE_URL"].rstrip("/")
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


# Export the Starlette/FastAPI app for testing and external use
app = mcp.streamable_http_app()

# Register OAuth2 middleware only when auth mode is oauth
if REDMINE_AUTH_MODE == "oauth":
    app.add_middleware(RedmineOAuthMiddleware)


# RFC 8707 — Protected Resource Metadata
@app.route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request):
    return JSONResponse(
        {
            "resource": f"{REDMINE_MCP_BASE_URL}/mcp",
            "authorization_servers": [REDMINE_MCP_BASE_URL],
            "bearer_methods_supported": ["header"],
            "resource_name": "Redmine MCP Server",
        }
    )


# RFC 8414 — Authorization Server Metadata
# Redmine uses Doorkeeper but does not serve this discovery document itself.
# We serve it manually, pointing to Redmine's real Doorkeeper endpoints.
@app.route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_server(request: Request):
    return JSONResponse(
        {
            "issuer": REDMINE_MCP_BASE_URL,
            "authorization_endpoint": f"{REDMINE_URL}/oauth/authorize",
            "token_endpoint": f"{REDMINE_URL}/oauth/token",
            "revocation_endpoint": f"{REDMINE_URL}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        }
    )


def main():
    """Main entry point for the console script."""
    # Note: .env is already loaded during redmine_handler import

    # Log version at startup
    server_version = get_version()
    logger.info(f"Redmine MCP Server v{server_version}")

    # Enable stateless HTTP mode (checked at request time by FastMCP)
    mcp.settings.stateless_http = True

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    # Run with our app directly so custom routes (well-known endpoints) are served
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
