"""Redmine MCP server.

The ``__version__`` attribute is resolved from the installed package
metadata at import time and falls back to the literal placeholder when
the package is not installed (e.g. when running the tests against a
source tree without ``uv pip install -e .``). It is exposed via the
``get_mcp_server_info`` tool so an MCP client can detect deployment
lag before relying on a recently-shipped fix.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("redmine-mcp-server")
except PackageNotFoundError:  # pragma: no cover - editable / source-tree case
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
