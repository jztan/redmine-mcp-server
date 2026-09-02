"""Expose only the tools an operator allow-lists.

``REDMINE_MCP_ALLOW_TOOLS`` (or ``REDMINE_MCP_ALLOW_TOOLS_FILE``) names the
tools a deployment offers. Everything else disappears from ``tools/list`` and
``call_tool`` refuses it.

Enforced by middleware, in the shape of :mod:`._scope_middleware`:
``on_list_tools`` filters whatever list it is handed and ``on_call_tool``
checks the name it is given. Both work on data the framework passes in, so
there is no registry to read and nothing that can widen the surface if FastMCP
moves its internals. That property is the point -- an allow list that fails
open is worse than none, because the operator believes a restriction is in
force while it is not.

The list narrows only. It runs alongside plugin visibility rather than
replacing it, so a listed tool whose plugin flag is off stays hidden:
allow-listing ``manage_deal`` does not substitute for
``REDMINE_DEALS_ENABLED=true``.

Granularity is whole tools. A ``manage_X(action=...)`` tool is allowed or
denied as a unit; restricting it to its read actions is what
``REDMINE_MCP_READ_ONLY`` is for, and the two compose.

The typo warning is separate and deliberately best-effort. It reads the local
provider's component registry -- private API -- to tell a misspelled name from
a real one, and stays quiet if that registry ever moves. A warning that
misfires costs nothing; enforcement never depends on it.
"""

import logging
from typing import Any, Optional, Set

from fastmcp.server.middleware import Middleware

from ._env import get_allowed_tools
from ._tool_error_middleware import build_error_tool_result

logger = logging.getLogger(__name__)

_TOOL_KEY_PREFIX = "tool:"

# Tools that exist but are registered only under a flag, so a correctly
# spelled name can be absent from the registry. Allow-listing one of these
# with its flag off is a no-op, not a typo, and must not be reported as one.
CONDITIONALLY_REGISTERED = frozenset({"cleanup_attachment_files"})


def _denial_payload(tool_name: str) -> dict[str, Any]:
    return {
        "error": f"Tool {tool_name!r} is not on this deployment's allow list.",
        "hint": (
            "The operator restricted the exposed tools with "
            "REDMINE_MCP_ALLOW_TOOLS. Ask them to add it if you need it."
        ),
        "code": "TOOL_NOT_ALLOWED",
    }


class ToolAllowListMiddleware(Middleware):
    """Hide and refuse every tool outside the configured allow list."""

    def __init__(self, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    @property
    def allowed(self) -> frozenset[str]:
        return self._allowed

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        return [tool for tool in tools if tool.name in self._allowed]

    async def on_call_tool(self, context, call_next):
        tool_name = context.message.name
        if tool_name not in self._allowed:
            logger.info("Denying %r: not on the tool allow list.", tool_name)
            return await build_error_tool_result(context, _denial_payload(tool_name))
        return await call_next(context)


def registered_tool_names(mcp: Any) -> Set[str]:
    """Every tool name registered on ``mcp``, or an empty set if unknowable.

    Best-effort and private-API: FastMCP exposes no synchronous enumeration,
    and this runs at import time. Used only to spot typos, never to decide
    what is exposed -- so an empty result costs a warning, not a restriction.
    """
    components = getattr(getattr(mcp, "_local_provider", None), "_components", None)
    if components is None:
        return set()
    return {
        key[len(_TOOL_KEY_PREFIX) :].split("@", 1)[0]
        for key in components
        if key.startswith(_TOOL_KEY_PREFIX)
    }


def warn_about_unknown_names(mcp: Any, allowed: Set[str]) -> None:
    """Log the allow-listed names this server does not have."""
    registered = registered_tool_names(mcp)
    if not registered:
        logger.debug(
            "Cannot enumerate registered tools, so allow-listed names are not "
            "checked for typos. The allow list itself is unaffected."
        )
        return
    unknown = sorted(allowed - registered - CONDITIONALLY_REGISTERED)
    if unknown:
        logger.warning(
            "REDMINE_MCP_ALLOW_TOOLS names %d tool(s) this server does not "
            "have, ignored: %s. Check for typos.",
            len(unknown),
            ", ".join(unknown),
        )


def build_tool_allow_list(mcp: Any) -> Optional[ToolAllowListMiddleware]:
    """Return the middleware for the configured allow list, or ``None``.

    ``None`` means no allow list is configured and every tool stays exposed,
    as before. A configured but empty list raises: it cannot be what an
    operator meant, and treating it as "expose everything" would turn a
    misconfiguration into a silently wider surface.
    """
    allowed = get_allowed_tools()
    if allowed is None:
        return None
    if not allowed:
        raise RuntimeError(
            "REDMINE_MCP_ALLOW_TOOLS is set but names no tools. Remove the "
            "variable to expose every tool, or name the tools to expose. "
            "Refusing to start rather than guess."
        )
    warn_about_unknown_names(mcp, allowed)
    return ToolAllowListMiddleware(frozenset(allowed))
