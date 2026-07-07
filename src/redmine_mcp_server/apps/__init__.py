"""MCP App implementations (interactive ``ui://`` views).

Importing this package triggers registration of each app's ``ui://``
resource and its entry-point/backend tools against the shared ``mcp``
instance, mirroring the ``tools`` package.
"""

from . import triage_board  # noqa: F401  -- triggers app registration
