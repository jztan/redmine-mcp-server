"""Tests for the get_mcp_server_info tool (#124).

Used by MCP clients (especially LLM-driven evaluators) to detect
deployment lag before re-probing a recently-shipped fix. Must always
be safely callable, must never expose credentials / hostnames / paths,
and must reflect runtime feature flags accurately.
"""

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401
from redmine_mcp_server import tools  # noqa: F401


@pytest.mark.asyncio
async def test_returns_a_version_string():
    """Always returns a server_version string, even when package
    metadata is unavailable (the fallback path)."""
    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})

    info = result.data
    assert isinstance(info.get("server_version"), str)
    assert info["server_version"]  # not empty


@pytest.mark.asyncio
async def test_returns_no_arg_schema():
    """The tool must take no arguments -- a caller checking deployment
    lag should not have to pass anything."""
    async with Client(_server.mcp) as client:
        listed = {t.name: t for t in await client.list_tools()}

    assert "get_mcp_server_info" in listed
    schema = listed["get_mcp_server_info"].inputSchema or {}
    assert schema.get("properties", {}) == {}
    assert not schema.get("required")


@pytest.mark.asyncio
async def test_reflects_plugin_flags(monkeypatch):
    """The plugin_flags dict tracks REDMINE_*_ENABLED env vars so a
    caller can choose its call shape without guessing whether the
    matching tool family is reachable."""
    monkeypatch.setenv("REDMINE_DMSF_ENABLED", "true")
    monkeypatch.setenv("REDMINE_AGILE_ENABLED", "false")

    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})

    flags = result.data["plugin_flags"]
    assert flags["dmsf"] is True
    assert flags["agile"] is False
    # The complete plugin-flag set is pinned: changes here are
    # intentional (new plugin family) and should fail CI loudly until
    # both the tool and this test are updated.
    assert set(flags.keys()) == {
        "agile",
        "checklists",
        "products",
        "crm",
        "dmsf",
    }


@pytest.mark.asyncio
async def test_reflects_read_only_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "true")
    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})
    assert result.data["read_only_mode"] is True

    monkeypatch.setenv("REDMINE_MCP_READ_ONLY", "false")
    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})
    assert result.data["read_only_mode"] is False


@pytest.mark.asyncio
async def test_reflects_auth_mode(monkeypatch):
    monkeypatch.setenv("REDMINE_AUTH_MODE", "oauth")
    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})
    assert result.data["auth_mode"] == "oauth"

    monkeypatch.delenv("REDMINE_AUTH_MODE", raising=False)
    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})
    # Default is legacy when the env var is unset.
    assert result.data["auth_mode"] == "legacy"


@pytest.mark.asyncio
async def test_does_not_leak_credentials_or_hostnames(monkeypatch):
    """Defense-in-depth: a regression that added REDMINE_URL or an
    API key to the response would be a security leak. Pin the response
    shape so that can't happen silently."""
    monkeypatch.setenv("REDMINE_URL", "https://internal.example.com")
    monkeypatch.setenv("REDMINE_API_KEY", "secret-key-do-not-leak")
    monkeypatch.setenv("PUBLIC_HOST", "do-not-leak.example.com")
    monkeypatch.setenv("REDMINE_PUBLIC_URL", "https://leakable.example.com")

    async with Client(_server.mcp) as client:
        result = await client.call_tool("get_mcp_server_info", {})

    flat = repr(result.data)
    for leaky in (
        "internal.example.com",
        "secret-key-do-not-leak",
        "do-not-leak.example.com",
        "leakable.example.com",
        "REDMINE_URL",
        "REDMINE_API_KEY",
    ):
        assert leaky not in flat, (
            f"get_mcp_server_info leaked {leaky!r} in its response. "
            "The tool must only surface non-sensitive metadata."
        )

    # The keys it IS allowed to surface are pinned.
    assert set(result.data.keys()) == {
        "server_version",
        "read_only_mode",
        "auth_mode",
        "plugin_flags",
    }


def test_package_version_is_importable():
    """The __version__ attribute is the source of truth for
    server_version. Imports from the package root must keep working."""
    from redmine_mcp_server import __version__

    assert isinstance(__version__, str)
    assert __version__  # not empty
