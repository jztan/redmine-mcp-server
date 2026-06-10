"""HTTP mount configuration for authenticated MCP deployments."""

from __future__ import annotations

import os
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://localhost:3040"
DEFAULT_MCP_PATH = "/mcp"


def _clean_url(value: str) -> str:
    return value.rstrip("/")


def _clean_path(value: str) -> str:
    path = value.strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/") or "/"


def mcp_base_url() -> str:
    """Public base URL of the authenticated OAuth/MCP app."""
    return _clean_url(os.getenv("REDMINE_MCP_BASE_URL", DEFAULT_BASE_URL))


def mcp_path_for_http_app() -> str:
    """MCP transport path inside the authenticated app."""
    return _clean_path(os.getenv("FASTMCP_STREAMABLE_HTTP_PATH", DEFAULT_MCP_PATH))


def mcp_mount_prefix() -> str:
    """ASGI mount prefix derived from the public base URL path."""
    path = urlparse(mcp_base_url()).path.rstrip("/")
    return path or "/"
