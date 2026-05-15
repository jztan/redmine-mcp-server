"""Meta / introspection tools.

A single ``get_mcp_server_info`` tool that returns the deployed
package version plus a few non-sensitive runtime flags an MCP client
needs in order to detect deployment lag and choose the right call
shape. Surfaced as a tool (not just an HTTP endpoint) so an LLM caller
can check it through the same protocol it already speaks.

What this deliberately does NOT expose:

- ``REDMINE_URL`` / ``REDMINE_API_KEY`` / OAuth secrets -- credentials
  and internal hostnames stay behind the operator-facing config path.
- File system paths (``ATTACHMENTS_DIR``) -- not interesting to a
  caller and faintly leaky.
- The configured ``PUBLIC_HOST`` / ``REDMINE_PUBLIC_URL`` -- these
  could disclose internal routing detail to a caller that doesn't
  need it.

Only the flags that change *call shape* for the caller are exposed:
which auth mode the server is in, which plugin-gated tool families
are enabled, and whether the server is in read-only mode. The version
string is unambiguously safe.
"""

from typing import Any, Dict

from .. import __version__
from .._env import (
    _is_agile_enabled,
    _is_checklists_enabled,
    _is_crm_enabled,
    _is_dmsf_enabled,
    _is_products_enabled,
    _is_read_only_mode,
)
from ..server import mcp


@mcp.tool()
async def get_mcp_server_info() -> Dict[str, Any]:
    """Return the MCP server's version and enabled-feature flags.

    Use this tool to detect deployment lag (the running server may be
    behind a recently-shipped patch) before relying on a fix that
    landed on ``develop`` -- compare ``server_version`` against the
    release / commit you expect.

    Returns:
        A dict with:

        - ``server_version`` (str): the deployed package version (from
          ``importlib.metadata``). The literal ``"0.0.0+unknown"`` when
          the package metadata is unavailable (rare; source-tree runs
          without an editable install).
        - ``read_only_mode`` (bool): whether ``REDMINE_MCP_READ_ONLY``
          is enabled. When ``True``, all write tools refuse with the
          standard read-only error.
        - ``auth_mode`` (str): ``"oauth"`` or ``"legacy"``.
        - ``plugin_flags`` (dict[str, bool]): which plugin-gated tool
          families are enabled. Keys: ``agile``, ``checklists``,
          ``products``, ``crm``, ``dmsf``. ``True`` means the
          corresponding ``manage_*`` / ``get_*`` tools are routable
          and will reach the underlying plugin endpoints; ``False``
          means they will return a "feature disabled" error envelope.

    The response intentionally excludes credentials, internal
    hostnames, file-system paths, and any other operator-config that
    a caller doesn't need to know to choose its call shape.

    Example:
        >>> await get_mcp_server_info()
        {
            "server_version": "1.3.0",
            "read_only_mode": False,
            "auth_mode": "legacy",
            "plugin_flags": {
                "agile": False,
                "checklists": False,
                "products": False,
                "crm": False,
                "dmsf": True,
            },
        }
    """
    import os

    return {
        "server_version": __version__,
        "read_only_mode": _is_read_only_mode(),
        "auth_mode": (os.environ.get("REDMINE_AUTH_MODE") or "legacy").lower(),
        "plugin_flags": {
            "agile": _is_agile_enabled(),
            "checklists": _is_checklists_enabled(),
            "products": _is_products_enabled(),
            "crm": _is_crm_enabled(),
            "dmsf": _is_dmsf_enabled(),
        },
    }
