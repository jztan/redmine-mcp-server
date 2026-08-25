"""Show plugin-gated tools on the MCP surface only when their plugin is on.

Every plugin tool registers with ``tags={plugin_tag(family)}``. At startup
``main.py`` calls :func:`apply_plugin_visibility`, which turns each family
on or off with FastMCP's visibility transforms. Disabled tools vanish from
``tools/list`` and ``call_tool`` rejects them, so a vanilla Redmine no
longer advertises tools that can only answer "feature disabled".

The call-time guards inside each tool stay: they protect direct Python
callers and the unit tests, which invoke the function objects directly.

Transforms are re-entrant (the later ``enable``/``disable`` wins), which is
what lets tests flip a flag and re-apply without reloading modules.
"""

from typing import Any, Callable, Dict

from ._env import (
    _is_checklists_enabled,
    _is_crm_enabled,
    _is_deals_enabled,
    _is_dmsf_enabled,
    _is_products_enabled,
)

# family -> "is this family's plugin enabled?"
PLUGIN_FLAGS: Dict[str, Callable[[], bool]] = {
    "checklists": _is_checklists_enabled,
    "crm": _is_crm_enabled,
    "deals": _is_deals_enabled,
    "products": _is_products_enabled,
    "dmsf": _is_dmsf_enabled,
}


def plugin_tag(family: str) -> str:
    """The FastMCP tag carried by every tool of ``family``."""
    return f"plugin:{family}"


def apply_plugin_visibility(mcp: Any) -> Dict[str, bool]:
    """Enable or disable each plugin family per its flag. Returns the state."""
    state: Dict[str, bool] = {}
    for family, is_enabled in PLUGIN_FLAGS.items():
        enabled = is_enabled()
        tags = {plugin_tag(family)}
        if enabled:
            mcp.enable(tags=tags)
        else:
            mcp.disable(tags=tags)
        state[family] = enabled
    return state


def enable_all_plugin_tools(mcp: Any) -> None:
    """Make every plugin family visible regardless of flags (tests)."""
    for family in PLUGIN_FLAGS:
        mcp.enable(tags={plugin_tag(family)})
