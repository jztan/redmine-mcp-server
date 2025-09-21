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
import uuid
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from redminelib import Redmine
from redminelib.exceptions import ResourceNotFoundError
from mcp.server.fastmcp import FastMCP
from .file_manager import AttachmentFileManager

# Load environment variables from .env file
load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)  # Adjust path to .env

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

# Configure logging
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("redmine_mcp_tools")


class CleanupTaskManager:
    """Manages the background cleanup task lifecycle."""

    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.manager: Optional[AttachmentFileManager] = None
        self.enabled = False
        self.interval_seconds = 600  # 10 minutes default

    async def start(self):
        """Start the cleanup task if enabled."""
        self.enabled = os.getenv("AUTO_CLEANUP_ENABLED", "false").lower() == "true"

        if not self.enabled:
            logger.info("Automatic cleanup is disabled (AUTO_CLEANUP_ENABLED=false)")
            return

        interval_minutes = float(os.getenv("CLEANUP_INTERVAL_MINUTES", "10"))
        self.interval_seconds = interval_minutes * 60
        attachments_dir = os.getenv("ATTACHMENTS_DIR", "./attachments")

        self.manager = AttachmentFileManager(attachments_dir)

        logger.info(
            f"Starting automatic cleanup task "
            f"(interval: {interval_minutes} minutes, "
            f"directory: {attachments_dir})"
        )

        self.task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """The main cleanup loop."""
        # Initial delay to let server fully start
        await asyncio.sleep(10)

        while True:
            try:
                stats = self.manager.cleanup_expired_files()
                if stats["cleaned_files"] > 0:
                    logger.info(
                        f"Automatic cleanup completed: "
                        f"removed {stats['cleaned_files']} files, "
                        f"freed {stats['cleaned_mb']}MB"
                    )
                else:
                    logger.debug("Automatic cleanup: no expired files found")

                # Wait for next interval
                await asyncio.sleep(self.interval_seconds)

            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled, shutting down")
                raise
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)
                # Continue running, wait before retry
                await asyncio.sleep(min(self.interval_seconds, 300))

    async def stop(self):
        """Stop the cleanup task gracefully."""
        if self.task and not self.task.done():
            logger.info("Stopping cleanup task...")
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
            logger.info("Cleanup task stopped")

    def get_status(self) -> dict:
        """Get current status of cleanup task."""
        return {
            "enabled": self.enabled,
            "running": self.task and not self.task.done() if self.task else False,
            "interval_seconds": self.interval_seconds,
            "storage_stats": self.manager.get_storage_stats() if self.manager else None,
        }


# Initialize cleanup manager
cleanup_manager = CleanupTaskManager()


# Global flag to track if cleanup has been initialized
_cleanup_initialized = False


async def _ensure_cleanup_started():
    """Ensure cleanup task is started (lazy initialization)."""
    global _cleanup_initialized
    if not _cleanup_initialized:
        cleanup_enabled = os.getenv("AUTO_CLEANUP_ENABLED", "false").lower() == "true"
        if cleanup_enabled:
            await cleanup_manager.start()
            _cleanup_initialized = True
            logger.info("Cleanup task initialized via MCP tool call")
        else:
            logger.info("Cleanup disabled (AUTO_CLEANUP_ENABLED=false)")
            # Mark as "initialized" to avoid repeated checks
            _cleanup_initialized = True


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint for container orchestration and monitoring."""
    from starlette.responses import JSONResponse

    # Initialize cleanup task on first health check (lazy initialization)
    await _ensure_cleanup_started()

    return JSONResponse({"status": "ok", "service": "redmine_mcp_tools"})


@mcp.custom_route("/files/{file_id}", methods=["GET"])
async def serve_attachment(request):
    """Serve downloaded attachment files via HTTP."""
    from starlette.responses import FileResponse
    from starlette.exceptions import HTTPException

    file_id = request.path_params["file_id"]

    # Security: Validate file_id format (proper UUID validation)
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    # Load file metadata from UUID directory
    attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))
    uuid_dir = attachments_dir / file_id
    metadata_file = uuid_dir / "metadata.json"

    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")

    try:
        # Read metadata
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        # Check expiry with proper timezone-aware datetime comparison
        expires_at_str = metadata.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                # Clean up expired files
                try:
                    file_path = Path(metadata["file_path"])
                    if file_path.exists():
                        file_path.unlink()
                    metadata_file.unlink()
                    # Remove UUID directory if empty
                    if uuid_dir.exists() and not any(uuid_dir.iterdir()):
                        uuid_dir.rmdir()
                except OSError:
                    pass  # Log but don't fail if cleanup fails
                raise HTTPException(status_code=404, detail="File expired")

        # Validate file path security (must be within UUID directory)
        file_path = Path(metadata["file_path"]).resolve()
        uuid_dir_resolved = uuid_dir.resolve()
        try:
            file_path.relative_to(uuid_dir_resolved)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        # Serve file
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=str(file_path),
            filename=metadata["original_filename"],
            media_type=metadata.get("content_type", "application/octet-stream"),
        )

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Corrupted metadata")
    except ValueError:
        # Invalid datetime format
        raise HTTPException(status_code=500, detail="Invalid metadata format")


@mcp.custom_route("/cleanup/status", methods=["GET"])
async def cleanup_status(request):
    """Get cleanup task status and statistics."""
    from starlette.responses import JSONResponse

    return JSONResponse(cleanup_manager.get_status())


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
        "assigned_to": (
            {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None
        ),
        "created_on": (
            issue.created_on.isoformat()
            if getattr(issue, "created_on", None) is not None
            else None
        ),
        "updated_on": (
            issue.updated_on.isoformat()
            if getattr(issue, "updated_on", None) is not None
            else None
        ),
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
                "user": (
                    {
                        "id": user.id,
                        "name": user.name,
                    }
                    if user is not None
                    else None
                ),
                "notes": notes,
                "created_on": (
                    journal.created_on.isoformat()
                    if getattr(journal, "created_on", None) is not None
                    else None
                ),
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
                "author": (
                    {
                        "id": attachment.author.id,
                        "name": attachment.author.name,
                    }
                    if getattr(attachment, "author", None) is not None
                    else None
                ),
                "created_on": (
                    attachment.created_on.isoformat()
                    if getattr(attachment, "created_on", None) is not None
                    else None
                ),
            }
        )
    return attachments


def _resource_to_dict(resource: Any, resource_type: str) -> Dict[str, Any]:
    """Convert any Redmine resource to a serializable dict for search results.

    Extends the existing _issue_to_dict pattern to handle multiple resource types.

    Args:
        resource: The Redmine resource object to convert
        resource_type: The type of resource (e.g., 'issues', 'projects', 'wiki_pages')

    Returns:
        A dictionary representation of the resource suitable for JSON serialization
    """
    base_dict = {
        "id": getattr(resource, "id", None),
        "type": resource_type,
    }

    # Common fields most resources have
    # Check for title first (search results use this)
    if hasattr(resource, "title") and getattr(resource, "title", None):
        base_dict["title"] = resource.title
    elif hasattr(resource, "name") and getattr(resource, "name", None):
        base_dict["title"] = resource.name
    elif hasattr(resource, "subject") and getattr(resource, "subject", None):
        base_dict["title"] = resource.subject
    else:
        base_dict["title"] = f"{resource_type.title()} {base_dict['id']}"

    # Project information (if available)
    if hasattr(resource, "project"):
        project = getattr(resource, "project")
        if project:
            base_dict["project"] = {
                "id": getattr(project, "id", None),
                "name": getattr(project, "name", "Unknown Project"),
            }

    # Status information (for issues)
    if hasattr(resource, "status"):
        status = getattr(resource, "status")
        if status:
            base_dict["status"] = getattr(status, "name", "Unknown Status")

    # Description/excerpt
    if hasattr(resource, "description"):
        description = getattr(resource, "description", "")
        if description:
            # Create excerpt (first 200 characters)
            if len(description) > 200:
                base_dict["excerpt"] = description[:200] + "..."
            else:
                base_dict["excerpt"] = description

    # Timestamps
    if hasattr(resource, "updated_on") and getattr(resource, "updated_on"):
        base_dict["updated_on"] = resource.updated_on.isoformat()
    elif hasattr(resource, "created_on") and getattr(resource, "created_on"):
        base_dict["updated_on"] = resource.created_on.isoformat()
    elif hasattr(resource, "datetime") and getattr(resource, "datetime"):
        # Search results use 'datetime' field
        datetime_str = getattr(resource, "datetime")
        if isinstance(datetime_str, str):
            base_dict["updated_on"] = datetime_str
        else:
            base_dict["updated_on"] = datetime_str.isoformat()

    # Generate URL (following existing patterns)
    # Check if resource already has URL (search results often include this)
    if hasattr(resource, "url") and getattr(resource, "url", None):
        base_dict["url"] = resource.url
    elif base_dict["id"]:
        redmine_url = os.getenv("REDMINE_URL", "").rstrip("/")
        if redmine_url:
            if resource_type == "issues":
                base_dict["url"] = f"{redmine_url}/issues/{base_dict['id']}"
            elif resource_type == "projects":
                base_dict["url"] = f"{redmine_url}/projects/{base_dict['id']}"
            elif resource_type == "wiki_pages":
                project_id = base_dict.get("project", {}).get("id", "")
                if project_id:
                    page_id = base_dict["id"]
                    wiki_url = f"{redmine_url}/projects/{project_id}/wiki/{page_id}"
                    base_dict["url"] = wiki_url
            else:
                base_dict["url"] = f"{redmine_url}/{resource_type}/{base_dict['id']}"

    return base_dict


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

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()
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
                "description": getattr(project, "description", ""),
                "created_on": (
                    project.created_on.isoformat()
                    if getattr(project, "created_on", None) is not None
                    else None
                ),
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

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()
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
async def search_entire_redmine(
    query: str,
    resource_types: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Search across the entire Redmine instance.

    Args:
        query: Text to search for. Search is case-insensitive
               as determined by the Redmine server configuration.
        resource_types: Filter by resource types (issues, projects, wiki_pages, etc.)
        limit: Maximum number of results to return (max 100)
        offset: Pagination offset

    Returns:
        Dictionary containing search results and metadata

    Note:
        Uses python-redmine's global search method.
        Requires Redmine 3.0.0+ for search API support.

        This tool complements the existing search_redmine_issues() tool:
        - search_redmine_issues(): Simple List[Dict] response, issue-only
        - search_entire_redmine(): Structured Dict response, multi-resource
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Prepare search options following existing pattern
        search_options = {
            "limit": min(limit, 100),  # Enforce reasonable limit
            "offset": offset,
        }

        # Add resource type filtering
        # python-redmine uses boolean flags for each resource type
        if resource_types:
            # Valid resource types with search_hints (confirmed from source)
            valid_types = ["issues", "projects", "wiki_pages", "news", "documents"]
            for resource_type in resource_types:
                if resource_type in valid_types:
                    search_options[resource_type] = True

        # Perform global search using python-redmine
        results = redmine.search(query, **search_options)

        if not results:
            return {
                "results": [],
                "results_by_type": {},
                "total_count": 0,
                "query": query,
            }

        # Process and categorize results
        all_results = []
        results_by_type = {}

        # Process categorized response format from redmine.search()
        # Returns dict with container keys mapped to ResourceSet objects
        # Format: {'issues': ResourceSet, 'projects': ResourceSet, 'unknown': {...}}

        for container_key, resource_set in results.items():
            if container_key == "unknown":
                # Handle unknown resource types (nested dict format)
                for resource_type, resource_list in resource_set.items():
                    type_results = []
                    for resource_data in resource_list:
                        # Convert raw resource data to dict format
                        converted = _resource_to_dict(resource_data, resource_type)
                        type_results.append(converted)

                    all_results.extend(type_results)
                    results_by_type[resource_type] = len(type_results)
            else:
                # Handle ResourceSet objects for known resource types
                type_results = []
                for resource in resource_set:
                    # Use generic resource conversion for all types from search
                    # Search results have limited attributes, so _resource_to_dict
                    # is more appropriate than _issue_to_dict
                    type_results.append(_resource_to_dict(resource, container_key))

                all_results.extend(type_results)
                results_by_type[container_key] = len(type_results)

        return {
            "results": all_results,
            "results_by_type": results_by_type,
            "total_count": len(all_results),
            "query": query,
        }

    except Exception as e:
        # Check for version compatibility errors
        error_msg = str(e).lower()
        if "search" in error_msg and ("not" in error_msg or "unsupported" in error_msg):
            return {"error": "Search requires Redmine 3.0.0 or higher"}

        print(f"Error searching Redmine: {e}")
        return {"error": "An error occurred while searching Redmine."}


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
    attachment_id: int,
    save_dir: str = "attachments",  # Keep compatibility with current signature
    expires_hours: int = None,
) -> Dict[str, Any]:
    """Download a Redmine attachment and return HTTP download URL.

    Args:
        attachment_id: The ID of the attachment to download.
        save_dir: Directory where the file will be saved. Defaults to "attachments".
        expires_hours: Hours until download link expires (default: from
            ATTACHMENT_EXPIRES_MINUTES env var, fallback: 60 minutes)

    Returns:
        A dictionary containing:
        - "download_url": HTTP URL to download the file
        - "filename": Original filename of the attachment
        - "content_type": MIME type of the file
        - "size": Size of the file in bytes
        - "expires_at": ISO timestamp when link expires

        On error, a dictionary with "error" is returned.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        attachment = redmine.attachment.get(attachment_id)

        # Create attachments directory (use configured path if save_dir is default)
        if save_dir == "attachments":
            attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))
        else:
            attachments_dir = Path(save_dir)
        attachments_dir.mkdir(exist_ok=True)

        # Generate unique file ID
        file_id = str(uuid.uuid4())

        # Download using existing approach - keeps original filename
        downloaded_path = attachment.download(savepath=str(attachments_dir))

        # Get file info
        original_filename = getattr(
            attachment, "filename", f"attachment_{attachment_id}"
        )

        # Create organized storage with UUID directory
        uuid_dir = attachments_dir / file_id
        uuid_dir.mkdir(exist_ok=True)

        # Move file to UUID-based location using atomic operations
        final_path = uuid_dir / original_filename
        temp_path = uuid_dir / f"{original_filename}.tmp"

        # Atomic file move with error handling
        try:
            os.rename(downloaded_path, temp_path)
            os.rename(temp_path, final_path)
        except (OSError, IOError) as e:
            # Cleanup on failure
            try:
                if temp_path.exists():
                    temp_path.unlink()
                if Path(downloaded_path).exists():
                    Path(downloaded_path).unlink()
            except OSError:
                pass  # Best effort cleanup
            return {"error": f"Failed to store attachment: {str(e)}"}

        # Get expiry time from environment variable if not specified
        if expires_hours is None:
            expires_minutes = float(os.getenv("ATTACHMENT_EXPIRES_MINUTES", "60"))
            expires_hours = expires_minutes / 60.0

        # Calculate expiry time (timezone-aware)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

        # Store metadata atomically
        metadata = {
            "file_id": file_id,
            "attachment_id": attachment_id,
            "original_filename": original_filename,
            "file_path": str(final_path),
            "content_type": getattr(
                attachment, "content_type", "application/octet-stream"
            ),
            "size": final_path.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        metadata_file = uuid_dir / "metadata.json"
        temp_metadata = uuid_dir / "metadata.json.tmp"

        # Atomic metadata write with error handling
        try:
            with open(temp_metadata, "w") as f:
                json.dump(metadata, f, indent=2)
            os.rename(temp_metadata, metadata_file)
        except (OSError, IOError, json.JSONEncodeError) as e:
            # Cleanup on failure
            try:
                if temp_metadata.exists():
                    temp_metadata.unlink()
                if final_path.exists():
                    final_path.unlink()
            except OSError:
                pass  # Best effort cleanup
            return {"error": f"Failed to save metadata: {str(e)}"}

        # Generate server base URL from environment configuration
        # Use public configuration for external URLs
        public_host = os.getenv("PUBLIC_HOST", os.getenv("SERVER_HOST", "localhost"))
        public_port = os.getenv("PUBLIC_PORT", os.getenv("SERVER_PORT", "8000"))

        # Handle special case of 0.0.0.0 bind address
        if public_host == "0.0.0.0":
            public_host = "localhost"

        download_url = f"http://{public_host}:{public_port}/files/{file_id}"

        return {
            "download_url": download_url,
            "filename": original_filename,
            "content_type": metadata["content_type"],
            "size": metadata["size"],
            "expires_at": metadata["expires_at"],
            "attachment_id": attachment_id,
        }

    except ResourceNotFoundError:
        return {"error": f"Attachment {attachment_id} not found."}
    except Exception as e:
        print(f"Error downloading Redmine attachment {attachment_id}: {e}")
        return {
            "error": f"An error occurred while downloading attachment {attachment_id}."
        }


@mcp.tool()
async def summarize_project_status(project_id: int, days: int = 30) -> Dict[str, Any]:
    """Provide a summary of project status based on issue activity over the
    specified time period.

    Args:
        project_id: The ID of the project to summarize
        days: Number of days to look back for analysis. Defaults to 30.

    Returns:
        A dictionary containing project status summary with issue counts,
        activity metrics, and trends. On error, returns a dictionary with
        an "error" key.
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}

    try:
        # Validate project exists
        try:
            project = redmine.project.get(project_id)
        except ResourceNotFoundError:
            return {"error": f"Project {project_id} not found."}

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        date_filter = f">={start_date.strftime('%Y-%m-%d')}"

        # Get issues created in the date range
        created_issues = list(
            redmine.issue.filter(project_id=project_id, created_on=date_filter)
        )

        # Get issues updated in the date range
        updated_issues = list(
            redmine.issue.filter(project_id=project_id, updated_on=date_filter)
        )

        # Analyze created issues
        created_stats = _analyze_issues(created_issues)

        # Analyze updated issues
        updated_stats = _analyze_issues(updated_issues)

        # Calculate trends
        total_created = len(created_issues)
        total_updated = len(updated_issues)

        # Get all project issues for context
        all_issues = list(redmine.issue.filter(project_id=project_id))
        all_stats = _analyze_issues(all_issues)

        return {
            "project": {
                "id": project.id,
                "name": project.name,
                "identifier": getattr(project, "identifier", ""),
            },
            "analysis_period": {
                "days": days,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
            "recent_activity": {
                "issues_created": total_created,
                "issues_updated": total_updated,
                "created_breakdown": created_stats,
                "updated_breakdown": updated_stats,
            },
            "project_totals": {
                "total_issues": len(all_issues),
                "overall_breakdown": all_stats,
            },
            "insights": {
                "daily_creation_rate": round(total_created / days, 2),
                "daily_update_rate": round(total_updated / days, 2),
                "recent_activity_percentage": round(
                    (total_updated / len(all_issues) * 100) if all_issues else 0, 2
                ),
            },
        }

    except Exception as e:
        print(f"Error summarizing project {project_id}: {e}")
        return {"error": f"An error occurred while summarizing project {project_id}."}


def _analyze_issues(issues: List[Any]) -> Dict[str, Any]:
    """Helper function to analyze a list of issues and return statistics."""
    if not issues:
        return {
            "by_status": {},
            "by_priority": {},
            "by_assignee": {},
            "total": 0,
        }

    status_counts = {}
    priority_counts = {}
    assignee_counts = {}

    for issue in issues:
        # Count by status
        status_name = getattr(issue.status, "name", "Unknown")
        status_counts[status_name] = status_counts.get(status_name, 0) + 1

        # Count by priority
        priority_name = getattr(issue.priority, "name", "Unknown")
        priority_counts[priority_name] = priority_counts.get(priority_name, 0) + 1

        # Count by assignee
        assigned_to = getattr(issue, "assigned_to", None)
        if assigned_to:
            assignee_name = getattr(assigned_to, "name", "Unknown")
            assignee_counts[assignee_name] = assignee_counts.get(assignee_name, 0) + 1
        else:
            assignee_counts["Unassigned"] = assignee_counts.get("Unassigned", 0) + 1

    return {
        "by_status": status_counts,
        "by_priority": priority_counts,
        "by_assignee": assignee_counts,
        "total": len(issues),
    }


@mcp.tool()
async def cleanup_attachment_files() -> Dict[str, Any]:
    """Clean up expired attachment files and return storage statistics.

    Returns:
        A dictionary containing cleanup statistics and current storage usage.
        On error, a dictionary with "error" is returned.
    """
    try:
        attachments_dir = os.getenv("ATTACHMENTS_DIR", "./attachments")
        manager = AttachmentFileManager(attachments_dir)
        cleanup_stats = manager.cleanup_expired_files()
        storage_stats = manager.get_storage_stats()

        return {"cleanup": cleanup_stats, "current_storage": storage_stats}
    except Exception as e:
        print(f"Error during attachment cleanup: {e}")
        return {"error": f"An error occurred during cleanup: {str(e)}"}


if __name__ == "__main__":
    if not redmine:
        print("Redmine client could not be initialized. Some tools may not work.")
        print("Please check your .env file and Redmine server connectivity.")
    # Initialize and run the server
    mcp.run(transport="stdio")
