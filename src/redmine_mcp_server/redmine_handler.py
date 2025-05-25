"""
MCP tools for Redmine integration.

This module provides Model Context Protocol (MCP) tools for interacting with Redmine
project management systems. It includes functionality to retrieve issue details,
list projects, and manage Redmine data through MCP-compatible interfaces.

The module handles authentication via either API key or username/password credentials,
and provides comprehensive error handling for network and authentication issues.

Tools provided:
    - get_redmine_issue: Retrieve detailed information about a specific issue
    - list_redmine_projects: Get a list of all accessible Redmine projects

Environment Variables Required:
    - REDMINE_URL: Base URL of the Redmine instance
    - REDMINE_API_KEY: API key for authentication (preferred), OR
    - REDMINE_USERNAME + REDMINE_PASSWORD: Username/password authentication

Dependencies:
    - redminelib: Python library for Redmine API interactions
    - python-dotenv: Environment variable management
    - mcp.server.fastmcp: FastMCP server implementation
"""
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from redminelib import Redmine
from redminelib.exceptions import ResourceNotFoundError
from mcp.server.fastmcp import FastMCP

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env')) # Adjust path to .env

REDMINE_URL = os.getenv("REDMINE_URL")
REDMINE_USERNAME = os.getenv("REDMINE_USERNAME")
REDMINE_PASSWORD = os.getenv("REDMINE_PASSWORD")
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY")

# Initialize Redmine client
# It's better to initialize it once if possible, or handle initialization within tools
# For simplicity, we'll initialize it globally here.
# Ensure error handling if credentials are not set.
if not REDMINE_URL:
    raise ValueError("REDMINE_URL not set in .env file")

try:
    if REDMINE_API_KEY:
        redmine = Redmine(REDMINE_URL, key=REDMINE_API_KEY)
    elif REDMINE_USERNAME and REDMINE_PASSWORD:
        redmine = Redmine(REDMINE_URL, username=REDMINE_USERNAME, password=REDMINE_PASSWORD)
    else:
        raise ValueError("Redmine credentials (API Key or Username/Password) not fully set in .env file")
except Exception as e:
    print(f"Error initializing Redmine client: {e}")
    # Depending on FastMCP, you might want to prevent server start or handle this gracefully
    redmine = None # Set to None so tools can check

# Initialize FastMCP server
mcp = FastMCP("redmine_mcp_tools")


@mcp.tool()
async def get_redmine_issue(issue_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves details for a specific Redmine issue by its ID.
    Args:
        issue_id: The ID of the Redmine issue.
    Returns:
        A dictionary containing issue details or None if not found or error.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}
    try:
        # python-redmine is synchronous, so we don't use await here for the library call
        issue = redmine.issue.get(issue_id)
        # Convert issue object to a dictionary for easier serialization
        return {
            "id": issue.id,
            "subject": issue.subject,
            "description": getattr(issue, 'description', ''),
            "project": {"id": issue.project.id, "name": issue.project.name},
            "status": {"id": issue.status.id, "name": issue.status.name},
            "priority": {"id": issue.priority.id, "name": issue.priority.name},
            "author": {"id": issue.author.id, "name": issue.author.name},
            "assigned_to": {"id": issue.assigned_to.id, "name": issue.assigned_to.name} if hasattr(issue, 'assigned_to') else None,
            "created_on": issue.created_on.isoformat() if hasattr(issue, 'created_on') else None,
            "updated_on": issue.updated_on.isoformat() if hasattr(issue, 'updated_on') else None,
        }
    except ResourceNotFoundError:
        return {"error": f"Issue {issue_id} not found."}
    except Exception as e:
        # Log the full error for debugging
        print(f"Error fetching Redmine issue {issue_id}: {e}")
        return {"error": f"An error occurred while fetching issue {issue_id}."}

@mcp.tool()
async def list_redmine_projects() -> List[Dict[str, Any]]:
    """
    Lists all accessible projects in Redmine.
    Returns:
        A list of dictionaries, each representing a project.
    """
    if not redmine:
        return [{"error": "Redmine client not initialized."}]
    try:
        projects = redmine.project.all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "identifier": project.identifier,
                "description": getattr(project, 'description', ''),
                "created_on": project.created_on.isoformat() if hasattr(project, 'created_on') else None,
            }
            for project in projects
        ]
    except Exception as e:
        print(f"Error listing Redmine projects: {e}")
        return [{"error": "An error occurred while listing projects."}]


if __name__ == "__main__":
    if not redmine:
        print("Redmine client could not be initialized. Some tools may not work.")
        print("Please check your .env file and Redmine server connectivity.")
    # Initialize and run the server
    mcp.run(transport='stdio')
