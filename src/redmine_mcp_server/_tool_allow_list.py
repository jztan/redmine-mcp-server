"""Expose only the tools an operator allow-lists.

``REDMINE_MCP_ALLOW_TOOLS`` (or ``REDMINE_MCP_ALLOW_TOOLS_FILE``) names the
tools a deployment offers. At startup ``main.py`` calls
:func:`apply_tool_allow_list` right after :func:`apply_plugin_visibility`,
and every tool outside the list is hidden with the same FastMCP visibility
transforms: it vanishes from ``tools/list`` and ``call_tool`` rejects it.

The pass only ever *disables*. It never enables a listed tool, so a tool
that is both on the allow list and hidden by its plugin flag stays hidden --
the allow list narrows the surface, it cannot widen it. That also means the
pass has to run again after any change to plugin visibility, which is what
the unit tests do.

Granularity is whole tools. A ``manage_X(action=...)`` tool is allowed or
denied as a unit; restricting it to its read actions is what
``REDMINE_MCP_READ_ONLY`` is for.
"""

import logging
from typing import Any, Set

from ._env import get_allowed_tools

logger = logging.getLogger(__name__)

_TOOL_KEY_PREFIX = "tool:"


def registered_tool_names(mcp: Any) -> Set[str]:
    """Every tool name registered on ``mcp``, whether enabled or not.

    FastMCP exposes no synchronous enumeration -- ``list_tools`` and friends
    are all coroutines, and this pass runs synchronously at import time next
    to :func:`apply_plugin_visibility`. So it reads the local provider's
    component registry, whose keys are ``"tool:<name>@<version>"``.
    """
    components = getattr(getattr(mcp, "_local_provider", None), "_components", None)
    if components is None:  # pragma: no cover - guards a FastMCP API change
        logger.warning(
            "Cannot enumerate registered tools; tool allow list not applied. "
            "This build of FastMCP does not expose the component registry "
            "where it is expected."
        )
        return set()
    return {
        key[len(_TOOL_KEY_PREFIX) :].split("@", 1)[0]
        for key in components
        if key.startswith(_TOOL_KEY_PREFIX)
    }


def apply_tool_allow_list(mcp: Any) -> Set[str] | None:
    """Hide every tool outside the configured allow list.

    Returns the set of allowed names that actually exist, or ``None`` when no
    allow list is configured (all tools stay as plugin visibility left them).
    """
    allowed = get_allowed_tools()
    if allowed is None:
        return None

    if not allowed:
        logger.warning(
            "REDMINE_MCP_ALLOW_TOOLS is set but names no tools; ignoring it "
            "and exposing the full tool surface. Remove the variable to make "
            "that explicit, or name the tools to expose."
        )
        return None

    registered = registered_tool_names(mcp)
    if not registered:
        return None

    unknown = sorted(allowed - registered)
    if unknown:
        logger.warning(
            "REDMINE_MCP_ALLOW_TOOLS names %d unknown tool(s), ignored: %s. "
            "Check for typos -- a misspelled name does not expose a tool.",
            len(unknown),
            ", ".join(unknown),
        )

    hidden = registered - allowed
    if hidden:
        mcp.disable(names=hidden)
    return allowed & registered
