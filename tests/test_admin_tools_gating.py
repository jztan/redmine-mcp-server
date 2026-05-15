"""Tests for the admin-tools gating flag (#115).

``cleanup_attachment_files`` is an operator / cron helper -- the
background cleanup task in ``_cleanup.py`` already runs it on the
configured interval, so an LLM agent should almost never need to
invoke it. Gating it off the default MCP surface removes a piece of
discovery-noise. Operators who drive cleanup via the MCP surface set
``REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`` to opt in.

The gate is evaluated at module-import time on
``tools/files.py``, so these tests verify the import-time behavior
by checking the live tool list (which reflects the env state at the
time the module was loaded).
"""

from importlib import reload

import pytest
from fastmcp import Client

from redmine_mcp_server import server as _server  # noqa: F401
from redmine_mcp_server import tools  # noqa: F401


@pytest.mark.asyncio
async def test_cleanup_tool_not_registered_by_default():
    """Default behavior: the admin tool must not appear in tools/list."""
    async with Client(_server.mcp) as client:
        names = {t.name for t in await client.list_tools()}

    # In the test environment, REDMINE_MCP_EXPOSE_ADMIN_TOOLS is unset
    # (or explicitly false) so the cleanup tool should be hidden.
    # Some test invocations set it for their own purpose; skip in
    # that case rather than fail spuriously.
    import os

    if os.environ.get("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("env opts the admin tool in; this is the off-path test")
    assert "cleanup_attachment_files" not in names


def test_admin_flag_helper_returns_false_when_unset(monkeypatch):
    monkeypatch.delenv("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", raising=False)
    # Helper is the source of truth used at import time.
    from redmine_mcp_server._env import _admin_tools_enabled

    assert _admin_tools_enabled() is False


def test_admin_flag_helper_returns_true_when_set(monkeypatch):
    for truthy in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", truthy)
        from redmine_mcp_server._env import _admin_tools_enabled

        assert _admin_tools_enabled() is True


def test_admin_flag_helper_returns_false_for_falsy_values(monkeypatch):
    for falsy in ("false", "0", "no", "off", "", "garbage"):
        monkeypatch.setenv("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", falsy)
        from redmine_mcp_server._env import _admin_tools_enabled

        assert _admin_tools_enabled() is False


def test_function_still_importable_when_gated_off():
    """Direct Python callers (internal code, tests, scripts) must still
    be able to import and call cleanup_attachment_files even when the
    MCP-surface gate is off. The gate only affects tool discoverability,
    not function existence."""
    from redmine_mcp_server.tools.files import cleanup_attachment_files

    assert callable(cleanup_attachment_files)


@pytest.mark.asyncio
async def test_opt_in_registers_the_tool(monkeypatch):
    """Reloading the files module with the env var set should register
    the tool on the MCP surface."""
    monkeypatch.setenv("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", "true")

    from redmine_mcp_server.tools import files as files_module

    reload(files_module)

    async with Client(_server.mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert "cleanup_attachment_files" in names

    # Restore the default-off behavior so subsequent tests see the
    # baseline state. Reloading after a delenv requires the env to be
    # unset at reload time.
    monkeypatch.delenv("REDMINE_MCP_EXPOSE_ADMIN_TOOLS", raising=False)
    reload(files_module)
