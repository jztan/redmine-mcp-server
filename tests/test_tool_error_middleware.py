"""Tests for the Pydantic-validation-error boundary middleware (#108)."""

import json
from typing import Any, Dict, List, Literal, Optional, Union

import pytest
from fastmcp import Client, FastMCP

from redmine_mcp_server._tool_error_middleware import (
    CleanValidationErrorMiddleware,
    ToolErrorFlagMiddleware,
)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mcp.add_middleware(CleanValidationErrorMiddleware())

    @mcp.tool()
    async def needs_int(x: int) -> dict:
        return {"x": x}

    @mcp.tool()
    async def needs_int_or_sentinel(
        status_id: int | str | None = None,
    ) -> dict:
        return {"status_id": status_id}

    # Mirrors the real list_redmine_issues return type, which is what
    # triggered the "Output validation error: 'result' is a required
    # property" regression reported during verification of #108.
    @mcp.tool()
    async def union_return(
        status_id: Optional[Union[int, Literal["open", "closed", "*"]]] = None,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        return [{"status_id": status_id}]

    return mcp


class TestCleanValidationErrorMiddleware:
    @pytest.mark.asyncio
    async def test_type_mismatch_returns_clean_envelope(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "needs_int", {"x": "open"}, raise_on_error=False
            )

        # Result is now a successful ToolResult carrying the error
        # envelope, not a raised ToolError -- the client side gets a
        # parseable object instead of a stringified Pydantic dump.
        payload = json.loads(result.content[0].text)
        assert payload["code"] == "INVALID_ARGUMENTS"
        assert "parameter 'x'" in payload["error"]
        # The verbose pydantic URL must NOT leak into the response.
        assert "errors.pydantic.dev" not in payload["error"]
        assert "errors.pydantic.dev" not in payload["hint"]
        # Hint includes the offending value to help the LLM recover.
        assert "'open'" in payload["hint"]
        assert "str" in payload["hint"]

    @pytest.mark.asyncio
    async def test_valid_arguments_pass_through_unchanged(self, server):
        async with Client(server) as client:
            result = await client.call_tool("needs_int", {"x": 42})

        # Happy path must not be touched by the middleware.
        assert result.structured_content == {"x": 42}

    @pytest.mark.asyncio
    async def test_envelope_also_emitted_as_structured_content(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "needs_int", {"x": "not-an-int"}, raise_on_error=False
            )

        # Clients that prefer structured_content must see the same
        # envelope, not a half-empty response.
        assert result.structured_content is not None
        assert result.structured_content["code"] == "INVALID_ARGUMENTS"

    @pytest.mark.asyncio
    async def test_union_literal_mismatch_returns_envelope_not_output_error(
        self, server
    ):
        """Regression test for the #108 follow-up bug.

        A value that fails BOTH branches of an
        ``Optional[Union[int, Literal[...]]]`` argument used to bypass
        the middleware envelope and surface as
        ``Output validation error: 'result' is a required property``,
        because tools returning ``Union[List, Dict]`` get an output
        schema marked ``x-fastmcp-wrap-result: True`` and the
        middleware wasn't honoring the wrap convention.
        """
        async with Client(server) as client:
            result = await client.call_tool(
                "union_return",
                {"status_id": "notavalidsentinel"},
                raise_on_error=False,
            )

        # The "result is a required property" string MUST NOT appear:
        # that was the user-visible regression.
        text = result.content[0].text
        assert "result" not in text or "required property" not in text
        assert "Output validation error" not in text

        # An error result is not parsed into ``data``; the envelope sits
        # under ``result`` in the structured content.
        assert result.is_error
        payload = result.structured_content["result"]
        assert payload["code"] == "INVALID_ARGUMENTS"
        # The envelope should mention BOTH branches of the union --
        # int and the literal sentinels -- not just the int complaint.
        assert "integer" in payload["error"].lower()
        assert "open" in payload["error"] or "literal" in payload["error"].lower()
        # Hint must accurately echo the offending value.
        assert "notavalidsentinel" in payload["hint"]

    @pytest.mark.asyncio
    async def test_union_literal_valid_sentinel_still_passes(self, server):
        """Valid sentinels keep working after the wrap-result fix."""
        async with Client(server) as client:
            result = await client.call_tool("union_return", {"status_id": "open"})
        # data unwraps to the actual list-of-dict return value.
        assert result.data == [{"status_id": "open"}]

    @pytest.mark.asyncio
    async def test_missing_required_argument_names_the_parameter(self, server):
        """Missing-required errors must say WHICH parameter is missing.

        Pydantic surfaces the whole args dict as ``input_value`` for
        missing-argument errors, which used to produce a misleading
        "Got {} (type=dict)" hint. The middleware now special-cases
        this so the LLM sees the parameter name.
        """
        async with Client(server) as client:
            result = await client.call_tool("needs_int", {}, raise_on_error=False)

        payload = result.structured_content
        assert payload["code"] == "INVALID_ARGUMENTS"
        assert "'x'" in payload["error"]
        assert "missing" in payload["error"].lower()
        # Must NOT echo the whole args dict back to the caller.
        assert "Got {}" not in payload["hint"]
        assert "Got {} " not in payload["hint"]


@pytest.fixture
def flagged_server():
    mcp = FastMCP("test")
    mcp.add_middleware(ToolErrorFlagMiddleware())
    mcp.add_middleware(CleanValidationErrorMiddleware())

    @mcp.tool()
    async def plain_error() -> Dict[str, Any]:
        return {"error": "Access denied.", "code": "FORBIDDEN"}

    @mcp.tool()
    async def plain_error_without_code() -> Dict[str, Any]:
        return {"error": "Something went wrong."}

    # A Union return type makes FastMCP wrap the payload under "result".
    @mcp.tool()
    async def wrapped_error() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        return {"error": "Cannot connect to Redmine.", "code": "CONNECTION_FAILED"}

    @mcp.tool()
    async def wrapped_error_without_code() -> (
        Union[List[Dict[str, Any]], Dict[str, Any]]
    ):
        return {"error": "Something went wrong."}

    @mcp.tool()
    async def error_with_empty_code() -> Dict[str, Any]:
        return {"error": "Something went wrong.", "code": ""}

    @mcp.tool()
    async def null_error() -> Dict[str, Any]:
        return {"id": 1, "error": None}

    @mcp.tool()
    async def success() -> Dict[str, Any]:
        return {"id": 1, "subject": "fine"}

    @mcp.tool()
    async def wrapped_success() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        return [{"id": 1}]

    @mcp.tool()
    async def needs_int(x: int) -> dict:
        return {"x": x}

    return mcp


class TestToolErrorFlagMiddleware:
    @pytest.mark.asyncio
    async def test_unwrapped_error_sets_is_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool("plain_error", {}, raise_on_error=False)

        assert result.is_error
        # The envelope reaches the caller unchanged in both places.
        expected = {"error": "Access denied.", "code": "FORBIDDEN"}
        assert result.structured_content == expected
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_wrapped_error_sets_is_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool("wrapped_error", {}, raise_on_error=False)

        assert result.is_error
        expected = {"error": "Cannot connect to Redmine.", "code": "CONNECTION_FAILED"}
        assert result.structured_content == {"result": expected}
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_missing_code_becomes_unknown_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool(
                "plain_error_without_code", {}, raise_on_error=False
            )

        assert result.is_error
        expected = {"error": "Something went wrong.", "code": "UNKNOWN_ERROR"}
        assert result.structured_content == expected
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_missing_code_in_wrapped_envelope_becomes_unknown_error(
        self, flagged_server
    ):
        async with Client(flagged_server) as client:
            result = await client.call_tool(
                "wrapped_error_without_code", {}, raise_on_error=False
            )

        assert result.is_error
        expected = {"error": "Something went wrong.", "code": "UNKNOWN_ERROR"}
        assert result.structured_content == {"result": expected}
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_empty_code_becomes_unknown_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool(
                "error_with_empty_code", {}, raise_on_error=False
            )

        assert result.is_error
        expected = {"error": "Something went wrong.", "code": "UNKNOWN_ERROR"}
        assert result.structured_content == expected
        assert json.loads(result.content[0].text) == expected

    @pytest.mark.asyncio
    async def test_null_error_is_not_an_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool("null_error", {})

        assert result.is_error is False
        assert result.structured_content == {"id": 1, "error": None}

    @pytest.mark.asyncio
    async def test_success_stays_not_an_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool("success", {})
            wrapped = await client.call_tool("wrapped_success", {})

        assert result.is_error is False
        assert result.structured_content == {"id": 1, "subject": "fine"}
        assert wrapped.is_error is False
        assert wrapped.data == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_argument_validation_error_sets_is_error(self, flagged_server):
        async with Client(flagged_server) as client:
            result = await client.call_tool(
                "needs_int", {"x": "open"}, raise_on_error=False
            )

        assert result.is_error
        assert result.structured_content["code"] == "INVALID_ARGUMENTS"

    @pytest.mark.asyncio
    async def test_build_error_tool_result_sets_is_error(self, server):
        # Without the flag middleware: build_error_tool_result sets it itself.
        async with Client(server) as client:
            result = await client.call_tool(
                "needs_int", {"x": "open"}, raise_on_error=False
            )

        assert result.is_error


def test_flag_middleware_is_registered_outermost():
    from redmine_mcp_server.server import _register_middlewares

    instance = FastMCP("test")
    _register_middlewares(instance, auth_provider=None)
    names = [type(mw).__name__ for mw in instance.middleware]
    # FastMCP runs the list in order, so earlier means further out.
    assert names.index("ToolErrorFlagMiddleware") < names.index(
        "CleanValidationErrorMiddleware"
    )
