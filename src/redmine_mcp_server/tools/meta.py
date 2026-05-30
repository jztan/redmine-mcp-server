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
string and current-user identity are unambiguously safe.
"""

import logging
from typing import Any, Dict, Optional

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

logger = logging.getLogger("redmine_mcp_server")


async def _fetch_current_user_info() -> Optional[Dict[str, Any]]:
    """Return {id, login, name} for the authenticated user, or None on failure.

    Resolves who ``assigned_to_id="me"`` maps to — crucial when a shared
    or robot API key is in use, where "me" is not the human operator.

    Uses ``GET /users/current.json`` via async httpx — works on Redmine 3.x
    and later. ``/my/account.json`` is not reliably available on older
    Redmine instances. redminelib's ``user.get('current')`` is not used
    because it requires admin rights on some setups.
    """
    try:
        import httpx
        from .. import _client

        url = (_client.REDMINE_URL or "").rstrip("/") + "/users/current.json"
        if not url.startswith("http"):
            return None

        if _client.REDMINE_API_KEY:
            headers = {"X-Redmine-API-Key": _client.REDMINE_API_KEY}
            auth = None
        elif _client.REDMINE_USERNAME and _client.REDMINE_PASSWORD:
            headers = {}
            auth = (_client.REDMINE_USERNAME, _client.REDMINE_PASSWORD)
        else:
            return None

        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, headers=headers, auth=auth)
        if r.status_code != 200:
            return None
        user = r.json().get("user", {})
        firstname = user.get("firstname", "") or ""
        lastname = user.get("lastname", "") or ""
        return {
            "id": user.get("id"),
            "login": user.get("login"),
            "name": f"{firstname} {lastname}".strip() or None,
        }
    except Exception as exc:
        logger.warning("get_mcp_server_info: could not fetch current user: %s", exc)
        return None


@mcp.tool()
async def get_mcp_server_info() -> Dict[str, Any]:
    """Return the MCP server's version, enabled-feature flags, and current user.

    Use this tool to:

    - Detect deployment lag: compare ``server_version`` against the
      release you expect before relying on a recently-shipped fix.
    - Understand who ``"me"`` resolves to: ``current_user`` shows the
      identity behind the configured API key. When a shared or robot API
      key is in use, ``assigned_to_id="me"`` will match **that** account,
      not the human operator — call this tool first if issue queries
      assigned to "me" return unexpectedly empty results.
    - Check which plugin-gated tool families are active.

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
        - ``current_user`` (dict | None): ``{id, login, name}`` for the
          authenticated Redmine user. ``None`` if the server cannot reach
          Redmine (check ``/health`` for connectivity status).
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
            "current_user": {"id": 5, "login": "vitex", "name": "Vítězslav Dvořák"},
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
        "current_user": await _fetch_current_user_info(),
        "plugin_flags": {
            "agile": _is_agile_enabled(),
            "checklists": _is_checklists_enabled(),
            "products": _is_products_enabled(),
            "crm": _is_crm_enabled(),
            "dmsf": _is_dmsf_enabled(),
        },
    }
