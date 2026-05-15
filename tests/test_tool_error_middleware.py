"""Tests for the Pydantic-validation-error boundary middleware (#108)."""

import json

import pytest
from fastmcp import Client, FastMCP

from redmine_mcp_server._tool_error_middleware import (
    CleanValidationErrorMiddleware,
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

    return mcp


class TestCleanValidationErrorMiddleware:
    @pytest.mark.asyncio
    async def test_type_mismatch_returns_clean_envelope(self, server):
        async with Client(server) as client:
            result = await client.call_tool("needs_int", {"x": "open"})

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
            result = await client.call_tool("needs_int", {"x": "not-an-int"})

        # Clients that prefer structured_content must see the same
        # envelope, not a half-empty response.
        assert result.structured_content is not None
        assert result.structured_content["code"] == "INVALID_ARGUMENTS"
