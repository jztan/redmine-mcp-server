"""FastMCP middleware enforcing per-tool OAuth scopes (#185).

In oauth / oauth-proxy modes, Doorkeeper scopes are advertised and
carried by access tokens but were historically never checked at the
tool boundary: any active token could invoke any tool, and only
Redmine's role check applied. This middleware closes that gap.

Model:
  - ``TOOL_SCOPES`` (oauth_scopes.py) maps every tool to the scopes it
    requires; the token must hold ALL of them. Deny by default: a tool
    without a map entry is refused.
  - ``manage_X(action=...)`` tools use per-action entries keyed on the
    structured ``action`` argument. Unknown actions pass through so the
    tool's own invalid-action error surfaces.
  - ``admin`` scope bypasses the check entirely, matching Redmine's own
    semantics (admin bypasses per-permission checks).
  - ``update_redmine_issue`` carries a notes-only carve-out: a call whose
    ``fields`` contain nothing but ``notes``/``private_notes`` (no
    ``uploads``) requires ``add_issue_notes`` instead of ``edit_issues``,
    mirroring Redmine's own note-adding permission check.
  - No access token (legacy / legacy-per-user modes, background tasks)
    means no enforcement: those modes have no scopes to check.
  - ``list_tools`` responses are filtered to tools the token can use;
    ``call_tool`` remains the actual security boundary.

The verifier's ``required_scopes`` stays unset by design: it is a
global AND over every token, which is the wrong model for per-tool
requirements (see tests/test_auth_factory.py).
"""

import logging
from typing import Any, Dict

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from ._tool_error_middleware import build_error_tool_result
from .oauth_scopes import TOOL_SCOPES, required_scopes_for_call, tool_visible_for

logger = logging.getLogger(__name__)


def _denial_payload(missing: frozenset, granted: set) -> Dict[str, Any]:
    missing_str = ", ".join(sorted(missing))
    return {
        "error": ("Access token lacks required OAuth scope(s): " f"{missing_str}."),
        "hint": (
            "Re-authorize with the missing scope(s) included, or ask the "
            "Redmine administrator to add them to the OAuth application. "
            f"Missing scopes: {missing_str}. "
            f"Granted scopes: {', '.join(sorted(granted)) or '(none)'}."
        ),
        "code": "INSUFFICIENT_SCOPE",
    }


def _unmapped_payload(tool_name: str) -> Dict[str, Any]:
    return {
        "error": (f"Tool '{tool_name}' has no scope mapping; denying by default."),
        "hint": (
            "This is a server-side omission. Add the tool to TOOL_SCOPES "
            "in oauth_scopes.py."
        ),
        "code": "INSUFFICIENT_SCOPE",
    }


class ScopeEnforcementMiddleware(Middleware):
    """Deny tool calls whose access token lacks the mapped scopes."""

    async def on_call_tool(self, context, call_next):
        token = get_access_token()
        if token is None:
            return await call_next(context)

        granted = set(token.scopes or [])
        if "admin" in granted:
            return await call_next(context)

        tool_name = context.message.name
        entry = TOOL_SCOPES.get(tool_name)
        if entry is None:
            logger.warning(
                "Denying call to unmapped tool %r (deny-by-default)", tool_name
            )
            return await build_error_tool_result(context, _unmapped_payload(tool_name))

        required = required_scopes_for_call(tool_name, entry, context.message.arguments)
        if required is None:
            # Per-action entry with unknown/missing action: let the
            # tool's own validation produce the error.
            return await call_next(context)

        missing = required - granted
        if missing:
            logger.info(
                "Denying %r: token lacks scope(s) %s",
                tool_name,
                ", ".join(sorted(missing)),
            )
            return await build_error_tool_result(
                context, _denial_payload(missing, granted)
            )

        return await call_next(context)

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        token = get_access_token()
        if token is None:
            return tools

        granted = set(token.scopes or [])
        if "admin" in granted:
            return tools

        visible = []
        for tool in tools:
            entry = TOOL_SCOPES.get(tool.name)
            if entry is not None and tool_visible_for(tool.name, entry, granted):
                visible.append(tool)
        return visible
