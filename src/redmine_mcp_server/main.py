"""
Main entry point for the MCP Redmine server.

This module uses FastMCP's native HTTP transport for MCP protocol communication.
The server runs with built-in HTTP endpoints and handles MCP requests natively.

Endpoints:
    - /mcp: Handles MCP requests via streamable HTTP transport.

Modules:
    - .tools: Per-resource MCP tool registrations (issues, projects, ...).
    - .server: Shared FastMCP instance.
"""

import logging
import os
import uvicorn
from importlib.metadata import version, PackageNotFoundError
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# Configure basic logging before importing modules that log during init
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from . import tools  # noqa: E402,F401  -- triggers @mcp.tool registration
from . import _http_routes  # noqa: E402,F401  -- registers HTTP custom routes
from .server import AUTH_PROVIDER, mcp  # noqa: E402
from ._mount import (  # noqa: E402
    mcp_mount_prefix,
    mcp_path_for_http_app,
)

logger = logging.getLogger(__name__)

REDMINE_AUTH_MODE = os.environ.get("REDMINE_AUTH_MODE", "legacy").lower()
AUTHENTICATED_AUTH_MODES = {"oauth", "oauth-proxy"}


def get_version() -> str:
    """Get package version from metadata."""
    try:
        return version("redmine-mcp-server")
    except PackageNotFoundError:
        return "dev"


def build_authenticated_app(mcp_instance, auth_provider):
    """Build a mounted ASGI app for authenticated modes."""
    mcp_path = mcp_path_for_http_app()
    mcp_app = mcp_instance.http_app(path=mcp_path, stateless_http=True)

    routes = list(auth_provider.get_well_known_routes(mcp_path=mcp_path))
    routes.extend(
        [
            Route("/health", _http_routes.health_check, methods=["GET"]),
            Route(
                "/files/{file_id}",
                _http_routes.serve_attachment,
                methods=["GET"],
            ),
            Route(
                "/cleanup/status",
                _http_routes.cleanup_status,
                methods=["GET"],
            ),
            Mount(mcp_mount_prefix(), app=mcp_app),
        ]
    )
    return Starlette(routes=routes, lifespan=mcp_app.lifespan)


def build_app():
    """Build the ASGI app."""
    if REDMINE_AUTH_MODE == "legacy-per-user":
        from ._per_user import assert_startup_attestation

        assert_startup_attestation()

    if REDMINE_AUTH_MODE in AUTHENTICATED_AUTH_MODES and AUTH_PROVIDER is not None:
        return build_authenticated_app(mcp, AUTH_PROVIDER)

    return mcp.http_app(stateless_http=True)


# Export the Starlette app for testing and external use
app = build_app()

# Log version at module load time so it appears regardless of how the server is started
logger.info("Redmine MCP Server v%s", get_version())
logger.info("Auth mode: %s", REDMINE_AUTH_MODE)


def main():
    """Main entry point for the console script."""
    # Note: .env is already loaded during _client import
    # Note: version/auth mode are logged at module level
    # (works for both direct and uvicorn invocation)

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    # Run with our app directly so custom routes (well-known endpoints) are served
    uvicorn.run(app, host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
