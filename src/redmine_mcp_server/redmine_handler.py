"""
MCP handler for SSE mode - maintains backward compatibility.
Uses shared RedmineTools for consistency with AgentCore mode.

This module provides FastMCP-compatible tools for Server-Sent Events transport.
It wraps the shared RedmineTools class to maintain consistent behavior across
both SSE and HTTP transport modes.
"""
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

try:
    from .redmine_tools import RedmineTools, get_redmine_client
except ImportError:
    # For standalone execution
    from redmine_tools import RedmineTools, get_redmine_client

# Initialize FastMCP server
mcp = FastMCP("redmine_mcp_tools")

# Create tools instance using same logic as AgentCore
redmine_tools = RedmineTools(get_redmine_client())


# Wrap each tool method with MCP decorator


@mcp.tool()
async def get_redmine_issue(
    issue_id: int, include_journals: bool = True, include_attachments: bool = True
) -> Dict[str, Any]:
    """Get detailed information about a Redmine issue."""
    return await redmine_tools.get_redmine_issue(issue_id, include_journals, include_attachments)

@mcp.tool()
async def list_redmine_projects() -> List[Dict[str, Any]]:
    """List all accessible Redmine projects."""
    return await redmine_tools.list_redmine_projects()


@mcp.tool()
async def list_my_redmine_issues(**filters: Any) -> List[Dict[str, Any]]:
    """List issues assigned to the current user."""
    return await redmine_tools.list_my_redmine_issues(**filters)


@mcp.tool()
async def search_redmine_issues(query: str, **options: Any) -> List[Dict[str, Any]]:
    """Search Redmine issues matching a query string."""
    return await redmine_tools.search_redmine_issues(query, **options)


@mcp.tool()
async def create_redmine_issue(
    project_id: int,
    subject: str,
    description: str = "",
    **fields: Any,
) -> Dict[str, Any]:
    """Create a new issue in Redmine."""
    return await redmine_tools.create_redmine_issue(project_id, subject, description, **fields)


@mcp.tool()
async def update_redmine_issue(issue_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing Redmine issue."""
    return await redmine_tools.update_redmine_issue(issue_id, fields)


@mcp.tool()
async def download_redmine_attachment(
    attachment_id: int, save_dir: str = "."
) -> Dict[str, Any]:
    """Download a Redmine attachment and return the saved file path."""
    return await redmine_tools.download_redmine_attachment(attachment_id, save_dir)


@mcp.tool()
async def summarize_project_status(
    project_id: int, days: int = 30
) -> Dict[str, Any]:
    """Provide a summary of project status based on issue activity."""
    return await redmine_tools.summarize_project_status(project_id, days)


if __name__ == "__main__":
    if not redmine_tools.client:
        print("Redmine client could not be initialized. Some tools may not work.")
        print("Please check your .env file and Redmine server connectivity.")
    # Initialize and run the server
    mcp.run(transport='stdio')
