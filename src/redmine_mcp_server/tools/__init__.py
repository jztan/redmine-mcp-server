"""MCP tool implementations, grouped by Redmine resource.

Importing this package will trigger ``@mcp.tool()`` registration for all 43
tools once the per-resource modules are added (Tasks 3.1 through 3.11).

Currently empty; tool definitions still live in `redmine_handler.py` and are
migrated one resource at a time.
"""

# Tools are imported here as their per-resource modules land. Until Phase 3
# is complete, tool registration still happens via `redmine_handler.py`; this
# __init__ is gradually populated.

from . import checklists  # noqa: F401  -- triggers @mcp.tool() registration
from . import contacts  # noqa: F401  -- triggers @mcp.tool() registration
from . import enumeration  # noqa: F401  -- triggers @mcp.tool() registration
from . import files  # noqa: F401  -- triggers @mcp.tool() registration
from . import gantt  # noqa: F401  -- triggers @mcp.tool() registration
from . import products  # noqa: F401  -- triggers @mcp.tool() registration
from . import projects  # noqa: F401  -- triggers @mcp.tool() registration
from . import search  # noqa: F401  -- triggers @mcp.tool() registration
from . import time_tracking  # noqa: F401  -- triggers @mcp.tool() registration
from . import wiki  # noqa: F401  -- triggers @mcp.tool() registration
