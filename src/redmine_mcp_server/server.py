"""FastMCP server instance.

The single source of truth for the `mcp` object that all `@mcp.tool()`
decorators register against. Tool modules import `mcp` from here.

Importing this module does NOT register any tools -- only `tools/__init__.py`
(via `from . import tools` in `main.py`) triggers tool registration.

In OAuth mode (``REDMINE_AUTH_MODE=oauth``), the FastMCP instance is
constructed with a ``RemoteAuthProvider`` that validates Bearer tokens
against Doorkeeper's RFC 7662 introspection endpoint. In OAuth proxy mode
(``REDMINE_AUTH_MODE=oauth-proxy``), FastMCP's ``OAuthProxy`` handles client
registration and the authorization code flow, then validates upstream Redmine
tokens with the same introspection endpoint. In legacy mode the instance is
built without ``auth=`` and behaves as before.
"""

import os

from fastmcp import FastMCP

from ._tool_error_middleware import CleanValidationErrorMiddleware

REDMINE_AUTH_MODE = os.environ.get("REDMINE_AUTH_MODE", "legacy").lower()


def _select_auth_provider(auth_mode: str):
    """Return the FastMCP auth provider for the given mode, or None.

    Extracted so tests can exercise the selection without reloading this
    module (a reload mutates the global ``mcp`` instance and disrupts
    tool registration in other test modules).
    """
    if auth_mode == "oauth":
        from ._auth import build_remote_auth

        return build_remote_auth()
    if auth_mode == "oauth-proxy":
        from ._oauth_proxy import build_oauth_proxy

        return build_oauth_proxy()
    return None


AUTH_PROVIDER = _select_auth_provider(REDMINE_AUTH_MODE)

mcp = FastMCP("redmine_mcp_tools", auth=AUTH_PROVIDER)
mcp.add_middleware(CleanValidationErrorMiddleware())
