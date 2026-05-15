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

    Errors that belong to the same root parameter (typical for Union /
    Literal types, where each branch contributes its own error) are
    collapsed into a single message so the LLM sees "expected int or
    one of 'open','closed','*'" instead of just the first branch's
    complaint. Remaining errors land under ``additional_errors``.
    """
    errors = exc.errors(include_url=False, include_context=False)
    if not errors:
        return {
            "error": "Invalid arguments.",
            "code": "INVALID_ARGUMENTS",
        }

    # Group by root parameter (first element of `loc`). Pydantic emits
    # one error per Union branch with `loc = (param_name, branch_tag)`,
    # so the root is the parameter the caller actually passed.
    primary_root = str(errors[0]["loc"][0]) if errors[0].get("loc") else ""
    same_root = [e for e in errors if e.get("loc") and str(e["loc"][0]) == primary_root]

    input_value = errors[0].get("input")
    error_type = errors[0].get("type", "")
    is_missing = error_type in ("missing", "missing_argument")

    if len(same_root) > 1:
        # Combine all branch messages for the same parameter into one
        # sentence: "Input should be a valid integer | one of 'open'..."
        combined = " or ".join(
            e.get("msg", "invalid value").strip().rstrip(".") for e in same_root
        )
        msg = combined
    else:
        msg = same_root[0].get("msg") or "invalid value"

    if is_missing:
        # "missing_argument" surfaces the entire args dict as input_value,
        # which makes "Got {} (type=dict)" technically true but useless to
        # an LLM caller. Tell them which parameter is missing instead.
        error_text = (
            f"Missing required argument '{primary_root}'."
            if primary_root
            else "Missing required arguments."
        )
        hint_text = (
            "Add this argument to the call; see the tool description for "
            "its accepted shape."
        )
    else:
        error_text = (
            f"Invalid value for parameter '{primary_root}': {msg}"
            if primary_root
            else f"Invalid arguments: {msg}"
        )
        hint_text = (
            f"Got {input_value!r} (type={type(input_value).__name__}). "
            "Check the tool's argument schema; see the tool description for "
            "accepted shapes."
        )

    payload: Dict[str, Any] = {
        "error": error_text,
        "hint": hint_text,
        "code": "INVALID_ARGUMENTS",
    }

    other = [e for e in errors if e not in same_root]
    if other:
        payload["additional_errors"] = [
            {
                "loc": ".".join(str(p) for p in e.get("loc", ())),
                "msg": e.get("msg"),
            }
            for e in other
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

            # Honor FastMCP's output-schema wrap convention. Tools whose
            # return type is not a plain dict (e.g. Union[List, Dict])
            # get an outputSchema with ``x-fastmcp-wrap-result: True``;
            # the client-side parser looks for the value under a
            # ``result`` key and trips a misleading
            # "Output validation error: 'result' is a required property"
            # if we hand it a flat dict instead. Detect that case and
            # mirror the wrapping so the envelope reaches the caller
            # intact regardless of return-type shape.
            wrap_result = False
            try:
                fastmcp_ctx = getattr(context, "fastmcp_context", None)
                if fastmcp_ctx is not None:
                    tool = await fastmcp_ctx.fastmcp.get_tool(context.message.name)
                    output_schema = getattr(tool, "output_schema", None) or {}
                    wrap_result = bool(output_schema.get("x-fastmcp-wrap-result"))
            except Exception:
                # Tool lookup failures are non-fatal: the envelope is
                # still readable via ``content``; the only cost is that
                # strict clients may surface the wrap-result mismatch.
                wrap_result = False

            structured: Dict[str, Any] = {"result": payload} if wrap_result else payload
            meta = {"fastmcp": {"wrap_result": True}} if wrap_result else None
            return ToolResult(
                content=[TextContent(type="text", text=json.dumps(payload))],
                structured_content=structured,
                meta=meta,
            )
