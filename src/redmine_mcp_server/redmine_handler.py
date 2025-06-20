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
from typing import Any, Dict, List

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
# It's better to initialize it once if possible, or handle initialization within tools.
# For simplicity, we'll initialize it globally here. If the environment variables
# are missing, the client remains ``None`` so tools can handle it gracefully.
redmine = None
if REDMINE_URL and (REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)):
    try:
        if REDMINE_API_KEY:
            redmine = Redmine(REDMINE_URL, key=REDMINE_API_KEY)
        else:
            redmine = Redmine(
                REDMINE_URL, username=REDMINE_USERNAME, password=REDMINE_PASSWORD
            )
    except Exception as e:
        print(f"Error initializing Redmine client: {e}")
        redmine = None

# Initialize FastMCP server
mcp = FastMCP("redmine_mcp_tools")


def _issue_to_dict(issue: Any) -> Dict[str, Any]:
    """Convert a python-redmine Issue object to a serializable dict."""
    assigned = getattr(issue, "assigned_to", None)

    return {
        "id": issue.id,
        "subject": issue.subject,
        "description": getattr(issue, "description", ""),
        "project": {"id": issue.project.id, "name": issue.project.name},
        "status": {"id": issue.status.id, "name": issue.status.name},
        "priority": {"id": issue.priority.id, "name": issue.priority.name},
        "author": {"id": issue.author.id, "name": issue.author.name},
        "assigned_to": {
            "id": assigned.id,
            "name": assigned.name,
        }
        if assigned is not None
        else None,
        "created_on": issue.created_on.isoformat()
        if getattr(issue, "created_on", None) is not None
        else None,
        "updated_on": issue.updated_on.isoformat()
        if getattr(issue, "updated_on", None) is not None
        else None,
    }


def _journals_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert journals on an issue object to a list of dicts."""
    raw_journals = getattr(issue, "journals", None)
    if raw_journals is None:
        return []

    journals: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_journals)
    except TypeError:
        return []

    for journal in iterator:
        notes = getattr(journal, "notes", "")
        if not notes:
            continue
        user = getattr(journal, "user", None)
        journals.append(
            {
                "id": journal.id,
                "user": {
                    "id": user.id,
                    "name": user.name,
                }
                if user is not None
                else None,
                "notes": notes,
                "created_on": journal.created_on.isoformat() if getattr(journal, "created_on", None) is not None else None,
            }
        )
    return journals


def _attachments_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert attachments on an issue object to a list of dicts."""
    raw_attachments = getattr(issue, "attachments", None)
    if raw_attachments is None:
        return []

    attachments: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_attachments)
    except TypeError:
        return []

    for attachment in iterator:
        attachments.append(
            {
                "id": attachment.id,
                "filename": getattr(attachment, "filename", ""),
                "filesize": getattr(attachment, "filesize", 0),
                "content_type": getattr(attachment, "content_type", ""),
                "description": getattr(attachment, "description", ""),
                "content_url": getattr(attachment, "content_url", ""),
                "author": {
                    "id": attachment.author.id,
                    "name": attachment.author.name,
                }
                if getattr(attachment, "author", None) is not None
                else None,
                "created_on": attachment.created_on.isoformat()
                if getattr(attachment, "created_on", None) is not None
                else None,
            }
        )
    return attachments


@mcp.tool()
async def get_redmine_issue(
    issue_id: int, include_journals: bool = True, include_attachments: bool = True
) -> Dict[str, Any]:
    """Retrieve a specific Redmine issue by ID.

    Args:
        issue_id: The ID of the issue to retrieve
        include_journals: Whether to include journals (comments) in the result.
            Defaults to ``True``.
        include_attachments: Whether to include attachments metadata in the
            result. Defaults to ``True``.

    Returns:
        A dictionary containing issue details. If ``include_journals`` is ``True``
        and the issue has journals, they will be returned under the ``"journals"``
        key. If ``include_attachments`` is ``True`` and attachments exist they
        will be returned under the ``"attachments"`` key. On failure a dictionary
        with an ``"error"`` key is returned.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}
    try:
        # python-redmine is synchronous, so we don't use await here for the library call
        includes = []
        if include_journals:
            includes.append("journals")
        if include_attachments:
            includes.append("attachments")

        if includes:
            issue = redmine.issue.get(issue_id, include=",".join(includes))
        else:
            issue = redmine.issue.get(issue_id)

        result = _issue_to_dict(issue)
        if include_journals:
            result["journals"] = _journals_to_list(issue)
        if include_attachments:
            result["attachments"] = _attachments_to_list(issue)

        return result
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
                "created_on": project.created_on.isoformat() if getattr(project, 'created_on', None) is not None else None,
            }
            for project in projects
        ]
    except Exception as e:
        print(f"Error listing Redmine projects: {e}")
        return [{"error": "An error occurred while listing projects."}]


@mcp.tool()
async def list_my_redmine_issues(**filters: Any) -> List[Dict[str, Any]]:
    """List issues assigned to the authenticated user.

    This uses the Redmine REST API filter ``assigned_to_id='me'`` to
    retrieve issues for the current user. Additional filters can be
    supplied via keyword arguments.
    """
    if not redmine:
        return [{"error": "Redmine client not initialized."}]
    try:
        issues = redmine.issue.filter(assigned_to_id="me", **filters)
        return [_issue_to_dict(issue) for issue in issues]
    except Exception as e:
        print(f"Error listing issues assigned to current user: {e}")
        return [{"error": "An error occurred while listing issues."}]


@mcp.tool()
async def search_redmine_issues(query: str, **options: Any) -> List[Dict[str, Any]]:
    """Search Redmine issues matching a query string.

    Args:
        query: Text to search for in issues.
        **options: Additional search options passed directly to the
            underlying python-redmine ``search`` API.

    Returns:
        A list of issue dictionaries. If no issues are found an empty list
        is returned. On error a list containing a single dictionary with an
        ``"error"`` key is returned.
    """
    if not redmine:
        return [{"error": "Redmine client not initialized."}]

    try:
        results = redmine.issue.search(query, **options)
        if results is None:
            return []
        return [_issue_to_dict(issue) for issue in results]
    except Exception as e:
        print(f"Error searching Redmine issues: {e}")
        return [{"error": "An error occurred while searching issues."}]


@mcp.tool()
async def create_redmine_issue(
    project_id: int,
    subject: str,
    description: str = "",
    **fields: Any,
) -> Dict[str, Any]:
    """Create a new issue in Redmine."""
    if not redmine:
        return {"error": "Redmine client not initialized."}
    try:
        issue = redmine.issue.create(
            project_id=project_id, subject=subject, description=description, **fields
        )
        return _issue_to_dict(issue)
    except Exception as e:
        print(f"Error creating Redmine issue: {e}")
        return {"error": "An error occurred while creating the issue."}


@mcp.tool()
async def update_redmine_issue(issue_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing Redmine issue.

    In addition to standard Redmine fields, a ``status_name`` key may be
    provided in ``fields``. When present and ``status_id`` is not supplied, the
    function will look up the corresponding status ID and use it for the update.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}

    # Convert status name to id if requested
    if "status_name" in fields and "status_id" not in fields:
        name = str(fields.pop("status_name")).lower()
        try:
            statuses = redmine.issue_status.all()
            for status in statuses:
                if getattr(status, "name", "").lower() == name:
                    fields["status_id"] = status.id
                    break
        except Exception as e:
            print(f"Error resolving status name '{name}': {e}")

    try:
        redmine.issue.update(issue_id, **fields)
        updated_issue = redmine.issue.get(issue_id)
        return _issue_to_dict(updated_issue)
    except ResourceNotFoundError:
        return {"error": f"Issue {issue_id} not found."}
    except Exception as e:
        print(f"Error updating Redmine issue {issue_id}: {e}")
        return {"error": f"An error occurred while updating issue {issue_id}."}


@mcp.tool()
async def download_redmine_attachment(
    attachment_id: int, save_dir: str = "."
) -> Dict[str, Any]:
    """Download a Redmine attachment and return the saved file path.

    Args:
        attachment_id: The ID of the attachment to download.
        save_dir: Directory where the file will be saved. Defaults to the
            current directory.

    Returns:
        A dictionary with ``"file_path"`` pointing to the saved file. On
        error, a dictionary with ``"error"`` is returned.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}
    try:
        attachment = redmine.attachment.get(attachment_id)
        # Ensure the save directory exists to avoid FileNotFoundError
        os.makedirs(save_dir, exist_ok=True)
        file_path = attachment.download(savepath=save_dir)
        return {"file_path": file_path}
    except ResourceNotFoundError:
        return {"error": f"Attachment {attachment_id} not found."}
    except Exception as e:
        print(f"Error downloading Redmine attachment {attachment_id}: {e}")
        return {
            "error": f"An error occurred while downloading attachment {attachment_id}."
        }

if __name__ == "__main__":
    if not redmine:
        print("Redmine client could not be initialized. Some tools may not work.")
        print("Please check your .env file and Redmine server connectivity.")
    # Initialize and run the server
    mcp.run(transport='stdio')
