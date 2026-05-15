"""FastMCP middleware that converts raw Pydantic argument-validation
errors into the project's standard ``{"error", "hint", "code"}``
envelope.

Without this middleware, calling a tool with a wrongly-typed argument
surfaces a verbose Pydantic v2 error string (with ``errors.pydantic.dev``
URLs) that is not actionable inside an LLM loop. The shape we produce
matches the rest of the API (see ``_errors._handle_redmine_error``).

Output validation errors are left untouched: they indicate a server-side
bug in tool construction, not bad caller input, and the LLM should not
be silently fed a "your input was wrong" message for them.
"""

import json
from typing import Any, Dict

from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from pydantic import ValidationError


def _format_argument_error(exc: ValidationError) -> Dict[str, Any]:
    """Build the standard error envelope from a Pydantic ValidationError.

    Only the first error is surfaced verbatim in ``error``/``hint``;
    additional errors are appended as a compact list under
    ``additional_errors`` so an LLM can still see them without parsing a
    multi-line blob.
    """
    errors = exc.errors(include_url=False, include_context=False)
    if not errors:
        return {
            "error": "Invalid arguments.",
            "code": "INVALID_ARGUMENTS",
        }

    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()))
    input_value = first.get("input")
    msg = first.get("msg") or "invalid value"

    payload: Dict[str, Any] = {
        "error": (
            f"Invalid value for parameter '{loc}': {msg}"
            if loc
            else f"Invalid arguments: {msg}"
        ),
        "hint": (
            f"Got {input_value!r} (type={type(input_value).__name__}). "
            "Check the tool's argument schema; see the tool description for "
            "accepted shapes."
        ),
        "code": "INVALID_ARGUMENTS",
    }

    if len(errors) > 1:
        payload["additional_errors"] = [
            {
                "loc": ".".join(str(p) for p in e.get("loc", ())),
                "msg": e.get("msg"),
            }
            for e in errors[1:]
        ]

    return payload


class CleanValidationErrorMiddleware(Middleware):
    """Catches argument-validation Pydantic errors at the tool boundary."""

    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except ValidationError as exc:
            # Argument validation runs before the tool body, so any
            # ValidationError raised through here is caller-input-shaped.
            # (Tool bodies that raise ValidationError internally would
            # also be caught here, which is acceptable: such errors
            # almost always indicate bad data passed into a pydantic
            # model anyway.)
            payload = _format_argument_error(exc)
            return ToolResult(
                content=[TextContent(type="text", text=json.dumps(payload))],
                structured_content=payload,
            )
