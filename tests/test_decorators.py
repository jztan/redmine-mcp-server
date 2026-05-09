"""Tests for the @action_dispatch decorator."""

import os
from unittest.mock import patch

import pytest

from redmine_mcp_server._decorators import ActionMode, action_dispatch


class TestActionDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_to_named_action(self):
        called = {}

        async def list_handler(**kwargs):
            called["which"] = "list"
            return {"result": "list"}

        async def create_handler(**kwargs):
            called["which"] = "create"
            return {"result": "create"}

        @action_dispatch(
            {
                "list": ActionMode.READ,
                "create": ActionMode.WRITE,
            }
        )
        async def dispatcher(action, **kwargs):
            return {"list": list_handler, "create": create_handler}

        with patch("redmine_mcp_server._decorators._ensure_cleanup_started"):
            result = await dispatcher(action="list")
        assert result == {"result": "list"}
        assert called["which"] == "list"

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        @action_dispatch({"list": ActionMode.READ})
        async def dispatcher(action, **kwargs):
            return {"list": lambda **_: {"r": 1}}

        result = await dispatcher(action="bogus")
        assert "error" in result
        assert "Invalid action" in result["error"]
        assert "list" in result["error"]

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    async def test_write_blocked_in_read_only(self):
        async def create_handler(**kwargs):
            return {"created": True}

        @action_dispatch({"create": ActionMode.WRITE})
        async def dispatcher(action, **kwargs):
            return {"create": create_handler}

        result = await dispatcher(action="create")
        assert "error" in result
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"REDMINE_MCP_READ_ONLY": "true"})
    async def test_read_allowed_in_read_only(self):
        async def list_handler(**kwargs):
            return ["a", "b"]

        @action_dispatch({"list": ActionMode.READ})
        async def dispatcher(action, **kwargs):
            return {"list": list_handler}

        with patch("redmine_mcp_server._decorators._ensure_cleanup_started"):
            result = await dispatcher(action="list")
        assert result == ["a", "b"]

    @pytest.mark.asyncio
    async def test_write_calls_ensure_cleanup_started(self):
        async def create_handler(**kwargs):
            return {"ok": True}

        @action_dispatch({"create": ActionMode.WRITE})
        async def dispatcher(action, **kwargs):
            return {"create": create_handler}

        with patch(
            "redmine_mcp_server._decorators._ensure_cleanup_started"
        ) as mock_ensure:
            await dispatcher(action="create")
        mock_ensure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_does_not_call_ensure_cleanup_started(self):
        async def list_handler(**kwargs):
            return []

        @action_dispatch({"list": ActionMode.READ})
        async def dispatcher(action, **kwargs):
            return {"list": list_handler}

        with patch(
            "redmine_mcp_server._decorators._ensure_cleanup_started"
        ) as mock_ensure:
            await dispatcher(action="list")
        mock_ensure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_kwargs_forwarded_to_handler(self):
        captured = {}

        async def update_handler(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        @action_dispatch({"update": ActionMode.WRITE})
        async def dispatcher(action, **kwargs):
            return {"update": update_handler}

        with patch("redmine_mcp_server._decorators._ensure_cleanup_started"):
            await dispatcher(action="update", id=42, name="X")
        assert captured == {"id": 42, "name": "X"}
