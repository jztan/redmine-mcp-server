"""FastMCP server instance.

The single source of truth for the `mcp` object that all `@mcp.tool()`
decorators register against. Tool modules import `mcp` from here.

Importing this module does NOT register any tools -- only `tools/__init__.py`
(via `from . import tools` in `main.py`) triggers tool registration.
"""

from fastmcp import FastMCP

mcp = FastMCP("redmine_mcp_tools")
