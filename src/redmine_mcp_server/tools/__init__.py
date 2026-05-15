"""MCP tool implementations, grouped by Redmine resource.

Importing this package triggers ``@mcp.tool()`` registration for all tools.
"""

from . import checklists  # noqa: F401  -- triggers @mcp.tool() registration
from . import contacts  # noqa: F401  -- triggers @mcp.tool() registration
from . import documents  # noqa: F401  -- triggers @mcp.tool() registration
from . import enumeration  # noqa: F401  -- triggers @mcp.tool() registration
from . import files  # noqa: F401  -- triggers @mcp.tool() registration
from . import gantt  # noqa: F401  -- triggers @mcp.tool() registration
from . import issues  # noqa: F401  -- triggers @mcp.tool() registration
from . import meta  # noqa: F401  -- triggers @mcp.tool() registration
from . import products  # noqa: F401  -- triggers @mcp.tool() registration
from . import projects  # noqa: F401  -- triggers @mcp.tool() registration
from . import search  # noqa: F401  -- triggers @mcp.tool() registration
from . import time_tracking  # noqa: F401  -- triggers @mcp.tool() registration
from . import wiki  # noqa: F401  -- triggers @mcp.tool() registration
