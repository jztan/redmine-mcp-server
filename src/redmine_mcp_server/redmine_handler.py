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
from typing import Any, Dict, List, Optional, Union

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
            _cleanup_initialized = (
                True  # Mark as "initialized" to avoid repeated checks
            )


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
async def list_my_redmine_issues(
    **filters: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List issues assigned to the authenticated user with pagination support.

    This uses the Redmine REST API filter ``assigned_to_id='me'`` to
    retrieve issues for the current user. Supports server-side pagination
    to prevent MCP token overflow and improve performance.

    Args:
        **filters: Keyword arguments for filtering issues:
            - limit: Maximum number of issues to return (default: 25, max: 1000)
            - offset: Number of issues to skip for pagination (default: 0)
            - include_pagination_info: Return structured response with metadata
                                   (default: False)
            - sort: Sort order (e.g., "updated_on:desc")
            - status_id: Filter by status ID
            - project_id: Filter by project ID
            - [other Redmine API filters]

    Returns:
        List[Dict] (default) or Dict with 'issues' and 'pagination' keys.
        Issues are limited to prevent token overflow (25,000 token MCP limit).

    Examples:
        >>> await list_my_redmine_issues(limit=10)
        [{"id": 1, "subject": "Issue 1", ...}, ...]

        >>> await list_my_redmine_issues(
        ...     limit=25, offset=50, include_pagination_info=True
        ... )
        {
            "issues": [...],
            "pagination": {"total": 150, "has_next": True, "next_offset": 75, ...}
        }

    Performance:
        - Memory efficient: Uses server-side pagination
        - Token efficient: Default limit keeps response under 2000 tokens
        - Time efficient: Typically <500ms for limit=25
    """
    if not redmine:
        logging.error("Redmine client not initialized")
        return [{"error": "Redmine client not initialized."}]

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Handle MCP interface wrapping parameters in 'filters' key
        if "filters" in filters and isinstance(filters["filters"], dict):
            actual_filters = filters["filters"]
        else:
            actual_filters = filters

        # Extract pagination parameters
        limit = actual_filters.pop("limit", 25)
        offset = actual_filters.pop("offset", 0)
        include_pagination_info = actual_filters.pop("include_pagination_info", False)

        # Use actual_filters for remaining Redmine filters
        filters = actual_filters

        # Log request for monitoring
        filter_keys = list(filters.keys()) if filters else []
        logging.info(
            f"Pagination request: limit={limit}, offset={offset}, filters={filter_keys}"
        )

        # Validate and sanitize parameters
        if limit is not None:
            if not isinstance(limit, int):
                try:
                    limit = int(limit)
                except (ValueError, TypeError):
                    logging.warning(
                        f"Invalid limit type {type(limit)}, using default 25"
                    )
                    limit = 25

            if limit <= 0:
                logging.debug(f"Limit {limit} <= 0, returning empty result")
                empty_result = []
                if include_pagination_info:
                    empty_result = {
                        "issues": [],
                        "pagination": {
                            "total": 0,
                            "limit": limit,
                            "offset": offset,
                            "count": 0,
                            "has_next": False,
                            "has_previous": False,
                            "next_offset": None,
                            "previous_offset": None,
                        },
                    }
                return empty_result

            # Cap at reasonable maximum
            original_limit = limit
            limit = min(limit, 1000)
            if original_limit > limit:
                logging.warning(
                    f"Limit {original_limit} exceeds maximum 1000, capped to {limit}"
                )

        # Validate offset
        if not isinstance(offset, int) or offset < 0:
            logging.warning(f"Invalid offset {offset}, reset to 0")
            offset = 0

        # Use python-redmine ResourceSet native pagination
        # Server-side filtering more efficient than client-side
        redmine_filters = {
            "assigned_to_id": "me",
            "offset": offset,
            "limit": min(limit or 25, 100),  # Redmine API max per request
            **filters,
        }

        # Get paginated issues from Redmine
        logging.debug(f"Calling redmine.issue.filter with: {redmine_filters}")
        issues = redmine.issue.filter(**redmine_filters)

        # Convert ResourceSet to list (triggers server-side pagination)
        issues_list = list(issues)
        logging.debug(
            f"Retrieved {len(issues_list)} issues with offset={offset}, limit={limit}"
        )

        # Convert to dictionaries
        result_issues = [_issue_to_dict(issue) for issue in issues_list]

        # Handle metadata response format
        if include_pagination_info:
            # Get total count from a separate query without offset/limit
            try:
                # Create clean query for total count (no pagination parameters)
                count_filters = {"assigned_to_id": "me", **filters}
                count_query = redmine.issue.filter(**count_filters)
                # Must evaluate the query first to get accurate total_count
                list(count_query)  # Trigger evaluation
                total_count = count_query.total_count
                logging.debug(f"Got total count from separate query: {total_count}")
            except Exception as e:
                logging.warning(
                    f"Could not get total count: {e}, using estimated value"
                )
                # For unknown total, use a conservative estimate
                if len(result_issues) == limit:
                    # If we got a full page, there might be more
                    total_count = offset + len(result_issues) + 1
                else:
                    # If we got less than requested, this is likely the end
                    total_count = offset + len(result_issues)

            pagination_info = {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "count": len(result_issues),
                "has_next": len(result_issues) == limit,
                "has_previous": offset > 0,
                "next_offset": offset + limit if len(result_issues) == limit else None,
                "previous_offset": max(0, offset - limit) if offset > 0 else None,
            }

            result = {"issues": result_issues, "pagination": pagination_info}

            logging.info(
                f"Returning paginated response: {len(result_issues)} issues, "
                f"total={total_count}"
            )
            return result

        # Log success and return simple list
        logging.info(f"Successfully retrieved {len(result_issues)} issues")
        return result_issues

    except Exception as e:
        logging.error(
            f"Error listing issues assigned to current user: {e}", exc_info=True
        )
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
    attachment_id: int,
    save_dir: str = "attachments",  # Keep compatibility with current signature
    expires_hours: int = None,
) -> Dict[str, Any]:
    """Download a Redmine attachment and return HTTP download URL.

    ⚠️  DEPRECATED: This function will be removed in v0.5.0
    📝 Use get_redmine_attachment_download_url(attachment_id) instead

    SECURITY WARNING: save_dir parameter allows path traversal attacks.
    expires_hours parameter exposes server policies to clients.

    Args:
        attachment_id: The ID of the attachment to download
        save_dir: DEPRECATED - Storage controlled by server configuration
        expires_hours: DEPRECATED - Expiry controlled by server configuration

    Returns:
        Same format as get_redmine_attachment_download_url()
    """
    # Log deprecation warning
    logger.warning(
        f"download_redmine_attachment is DEPRECATED and will be removed in v0.5.0. "
        f"Use get_redmine_attachment_download_url({attachment_id}) instead. "
        f"Called with save_dir='{save_dir}', expires_hours={expires_hours}"
    )

    # Security validation for save_dir parameter
    if save_dir != "attachments":
        logger.error(
            f"SECURITY: Rejected save_dir parameter '{save_dir}' - "
            f"potential path traversal attack. Using server default."
        )

    # Delegate to secure implementation (ignoring deprecated parameters)
    return await get_redmine_attachment_download_url(attachment_id)


@mcp.tool()
async def get_redmine_attachment_download_url(
    attachment_id: int,
) -> Dict[str, Any]:
    """Get HTTP download URL for a Redmine attachment.

    Downloads the attachment to server storage and returns a time-limited
    HTTP URL that clients can use to download the file. Expiry time and
    storage location are controlled by server configuration.

    Args:
        attachment_id: The ID of the attachment to retrieve

    Returns:
        Dict containing download_url, filename, content_type, size,
        expires_at, and attachment_id

    Raises:
        ResourceNotFoundError: If attachment ID doesn't exist
        Exception: For other download or processing errors
    """
    if not redmine:
        return {"error": "Redmine client not initialized."}

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Get attachment metadata from Redmine
        attachment = redmine.attachment.get(attachment_id)

        # Server-controlled configuration (secure)
        attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))
        expires_minutes = float(os.getenv("ATTACHMENT_EXPIRES_MINUTES", "60"))

        # Create secure storage directory
        attachments_dir.mkdir(parents=True, exist_ok=True)

        # Generate secure UUID-based filename
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

        # Calculate expiry time (timezone-aware)
        expires_hours = expires_minutes / 60.0
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

        # Store metadata atomically (following existing pattern)
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
        except (OSError, IOError, ValueError) as e:
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
        logger.error(
            f"Error in get_redmine_attachment_download_url {attachment_id}: {e}"
        )
        return {"error": f"Failed to prepare attachment download: {str(e)}"}


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
