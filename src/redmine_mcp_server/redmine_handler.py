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
    - fastmcp: FastMCP server implementation
"""

import ipaddress  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import socket  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import asyncio  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import unquote, urlparse  # noqa: F401  -- re-exported

import httpx  # noqa: F401  -- re-exported so tests can patch via redmine_handler
from redminelib import Redmine  # noqa: F401  -- re-exported for test patching
from redminelib.exceptions import (  # noqa: F401  -- re-exported for back-compat
    ResourceNotFoundError,
    VersionMismatchError,
    ValidationError,
)
from ._validation import (  # noqa: F401  -- re-exported for back-compat during refactor
    _PROJECT_ID_PATTERN,
    _is_positive_int,
    _is_valid_project_id,
    _validate_hours,
)
from ._serialization import (  # noqa: F401  re-exported for back-compat
    _DEFAULT_LIST_RESULT_CAP,
    _REDMINE_API_PAGE_CAP,
    _coerce_json_safe,
    _iter_capped,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from ._env import (  # noqa: F401  -- re-exported for back-compat during refactor
    _is_agile_enabled,
    _is_checklists_enabled,
    _is_crm_enabled,
    _is_products_enabled,
    _is_read_only_mode,
    _is_true_env,
)
from ._errors import (  # noqa: F401  -- re-exported for back-compat during refactor
    _READ_ONLY_ERROR,
    _SECRET_SCRUB_PATTERNS,
    _handle_redmine_error,
    _scrub_error_message,
)
from ._client import (  # noqa: F401  -- re-exported for back-compat during refactor
    REDMINE_API_KEY,
    REDMINE_AUTH_MODE,
    REDMINE_PASSWORD,
    REDMINE_SSL_CERT,
    REDMINE_SSL_CLIENT_CERT,
    REDMINE_SSL_VERIFY,
    REDMINE_URL,
    REDMINE_USERNAME,
    _build_legacy_client,
    _build_requests_config,
    _env_loaded,
    _env_paths,
    _get_redmine_client,
    _legacy_client,
    logger,
    redmine,
)
from ._cleanup import (  # noqa: F401  -- re-exported for back-compat during refactor
    CleanupTaskManager,
    _ensure_cleanup_started,
    cleanup_manager,
)
from ._ssrf import (  # noqa: F401  -- re-exported for back-compat during refactor
    _CONTROL_CHAR_RE,
    _DOWNLOAD_TIMEOUT,
    _FILE_DOWNLOAD_MAX_REDIRECTS,
    _MAX_FILENAME_LEN,
    _allow_private_fetch_urls,
    _download_file_url,
    _extract_content_disposition_filename,
    _is_hostname_safe_for_fetch,
    _is_ip_publicly_routable,
    _make_pinned_client,
    _sanitize_filename,
    _validate_fetch_url,
)
from ._custom_fields import (  # noqa: F401  -- re-exported for back-compat
    _DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES,
    _STANDARD_ISSUE_UPDATE_FIELDS,
    _augment_fields_with_required_custom_fields,
    _coerce_update_custom_fields,
    _extract_missing_required_field_names,
    _extract_possible_values,
    _is_allowed_custom_field_value,
    _is_missing_custom_field_value,
    _is_required_custom_field_autofill_enabled,
    _is_standard_issue_update_key,
    _load_required_custom_field_defaults,
    _map_named_custom_fields_for_update,
    _normalize_field_label,
    _parse_create_issue_fields,
    _parse_optional_object_payload,
    _resolve_project_issue_custom_fields,
    _resolve_required_custom_field_value,
    _upsert_custom_field_entry,
)

if not REDMINE_URL:
    logger.warning(
        "REDMINE_URL not set. "
        "Please create a .env file in your working directory with REDMINE_URL defined."
    )
elif REDMINE_AUTH_MODE != "oauth" and not (
    REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)
):
    logger.warning(
        "No Redmine authentication configured. "
        "Please set REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD "
        "in your .env file, or set REDMINE_AUTH_MODE=oauth."
    )


# Initialize FastMCP server
# Re-exported for back-compat during refactor
from .server import mcp  # noqa: E402,F401

# Re-exported for back-compat during refactor
from ._http_routes import (  # noqa: E402,F401
    cleanup_status,
    health_check,
    serve_attachment,
)

# Register HTTP routes on the FastMCP instance. Functions live in _http_routes
# but the @mcp.custom_route decorator must be applied here where `mcp` exists.
mcp.custom_route("/health", methods=["GET"])(health_check)
mcp.custom_route("/files/{file_id}", methods=["GET"])(serve_attachment)
mcp.custom_route("/cleanup/status", methods=["GET"])(cleanup_status)


def _fetch_agile_data(issue_id: int) -> Dict[str, Any]:
    """Fetch agile fields for an issue from the RedmineUP Agile endpoint.

    Returns a dict with story_points, agile_sprint_id, and agile_position.
    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/issues/{issue_id}/agile_data.json"
    payload = client.engine.request("get", url)
    agile_data = payload.get("agile_data", {}) or {}
    return {
        "story_points": agile_data.get("story_points"),
        "agile_sprint_id": agile_data.get("agile_sprint_id"),
        "agile_position": agile_data.get("position"),
    }


def _apply_agile_story_points(issue_id: int, story_points) -> None:
    """Write story_points for an issue via the RedmineUP Agile endpoint.

    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/issues/{issue_id}.json"
    payload = json.dumps(
        {"issue": {"agile_data_attributes": {"story_points": story_points}}}
    )
    client.engine.request(
        "put",
        url,
        headers={"Content-Type": "application/json"},
        data=payload,
    )


# ---------------------------------------------------------------------------
# Module-level limits and timeouts.
# ---------------------------------------------------------------------------


def _custom_fields_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert issue custom_fields to a serializable list."""
    raw_custom_fields = getattr(issue, "custom_fields", None)
    if raw_custom_fields is None:
        return []

    custom_fields: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_custom_fields)
    except TypeError:
        return []

    for custom_field in iterator:
        if isinstance(custom_field, dict):
            field_id = custom_field.get("id")
            field_name = custom_field.get("name")
            field_value = custom_field.get("value")
        else:
            field_id = getattr(custom_field, "id", None)
            field_name = getattr(custom_field, "name", None)
            field_value = getattr(custom_field, "value", None)

        custom_fields.append(
            {
                "id": field_id,
                "name": field_name,
                "value": _coerce_json_safe(field_value),
            }
        )

    return custom_fields


def _issue_to_dict(issue: Any, include_custom_fields: bool = False) -> Dict[str, Any]:
    """Convert a python-redmine Issue object to a serializable dict."""
    # Use getattr for all potentially missing attributes (search API may not return all)
    assigned = getattr(issue, "assigned_to", None)
    project = getattr(issue, "project", None)
    status = getattr(issue, "status", None)
    priority = getattr(issue, "priority", None)
    author = getattr(issue, "author", None)

    issue_dict = {
        "id": getattr(issue, "id", None),
        "subject": getattr(issue, "subject", ""),
        "description": wrap_insecure_content(getattr(issue, "description", "")),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "status": (
            {"id": status.id, "name": status.name} if status is not None else None
        ),
        "priority": (
            {"id": priority.id, "name": priority.name} if priority is not None else None
        ),
        "author": (
            {"id": author.id, "name": author.name} if author is not None else None
        ),
        "assigned_to": (
            {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None
        ),
        "created_on": _safe_isoformat(getattr(issue, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(issue, "updated_on", None)),
    }

    if include_custom_fields:
        issue_dict["custom_fields"] = _custom_fields_to_list(issue)

    return issue_dict


def _issue_to_dict_selective(
    issue: Any, fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Convert a python-redmine Issue object to a dict with selected fields.

    Args:
        issue: The python-redmine Issue object to convert.
        fields: List of field names to include. If None, ["*"], or ["all"],
                returns all fields (same as _issue_to_dict). Invalid or
                missing fields are silently skipped.

    Available fields:
        - id: Issue ID
        - subject: Issue subject/title
        - description: Issue description
        - project: Project info (dict with id and name)
        - status: Status info (dict with id and name)
        - priority: Priority info (dict with id and name)
        - author: Author info (dict with id and name)
        - assigned_to: Assigned user info (dict with id and name, or None)
        - created_on: Creation timestamp (ISO format)
        - updated_on: Last update timestamp (ISO format)

    Returns:
        Dictionary containing only the requested fields.

    Examples:
        >>> _issue_to_dict_selective(issue, ["id", "subject"])
        {"id": 123, "subject": "Bug fix"}

        >>> _issue_to_dict_selective(issue, ["*"])
        # Returns all fields (same as _issue_to_dict)

        >>> _issue_to_dict_selective(issue, None)
        # Returns all fields (same as _issue_to_dict)
    """
    # Handle "all fields" cases
    if fields is None or fields == ["*"] or fields == ["all"]:
        return _issue_to_dict(issue)

    # Build field mapping with all available fields
    # Use getattr for all potentially missing attributes (search API may not return all)
    assigned = getattr(issue, "assigned_to", None)
    project = getattr(issue, "project", None)
    status = getattr(issue, "status", None)
    priority = getattr(issue, "priority", None)
    author = getattr(issue, "author", None)

    all_fields = {
        "id": getattr(issue, "id", None),
        "subject": getattr(issue, "subject", ""),
        "description": wrap_insecure_content(getattr(issue, "description", "")),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "status": (
            {"id": status.id, "name": status.name} if status is not None else None
        ),
        "priority": (
            {"id": priority.id, "name": priority.name} if priority is not None else None
        ),
        "author": (
            {"id": author.id, "name": author.name} if author is not None else None
        ),
        "assigned_to": (
            {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None
        ),
        "created_on": _safe_isoformat(getattr(issue, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(issue, "updated_on", None)),
    }

    # Return only requested fields (silently skip invalid field names)
    return {key: all_fields[key] for key in fields if key in all_fields}


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
                "notes": wrap_insecure_content(notes),
                "created_on": _safe_isoformat(getattr(journal, "created_on", None)),
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
                # filename and description are attacker-controllable
                # (anyone who can attach to an issue sets them). Wrap
                # them in <insecure-content> boundary tags — matches the
                # treatment in _file_to_dict for project files.
                "filename": wrap_insecure_content(getattr(attachment, "filename", "")),
                "filesize": getattr(attachment, "filesize", 0),
                "content_type": getattr(attachment, "content_type", ""),
                "description": wrap_insecure_content(
                    getattr(attachment, "description", "")
                ),
                "content_url": getattr(attachment, "content_url", ""),
                "author": _named_ref(getattr(attachment, "author", None)),
                "created_on": _safe_isoformat(getattr(attachment, "created_on", None)),
            }
        )
    return attachments


def _version_to_dict(version: Any) -> Dict[str, Any]:
    """Convert a python-redmine Version object to a serializable dict."""
    project = getattr(version, "project", None)
    return {
        "id": getattr(version, "id", None),
        "name": getattr(version, "name", ""),
        "description": wrap_insecure_content(getattr(version, "description", "")),
        "status": getattr(version, "status", ""),
        "due_date": (
            str(version.due_date)
            if getattr(version, "due_date", None) is not None
            else None
        ),
        "sharing": getattr(version, "sharing", ""),
        "wiki_page_title": getattr(version, "wiki_page_title", ""),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "created_on": _safe_isoformat(getattr(version, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(version, "updated_on", None)),
    }


def _custom_field_trackers_to_list(custom_field: Any) -> List[Dict[str, Any]]:
    """Serialize custom field tracker bindings into a predictable list."""
    raw_trackers = getattr(custom_field, "trackers", None)
    if raw_trackers is None:
        return []

    try:
        iterator = iter(raw_trackers)
    except TypeError:
        return []

    trackers: List[Dict[str, Any]] = []
    for tracker in iterator:
        tracker_id = None
        tracker_name = None

        if isinstance(tracker, dict):
            tracker_id = tracker.get("id")
            tracker_name = tracker.get("name")
        else:
            tracker_id = getattr(tracker, "id", None)
            tracker_name = getattr(tracker, "name", None)

        if tracker_id is None and tracker_name is None:
            continue

        if tracker_id is not None:
            try:
                tracker_id = int(tracker_id)
            except (TypeError, ValueError):
                tracker_id = str(tracker_id)

        trackers.append({"id": tracker_id, "name": tracker_name})

    return trackers


def _custom_field_applies_to_tracker(
    custom_field: Any, tracker_id: Optional[int]
) -> bool:
    """Return whether a custom field is available for the given tracker."""
    if tracker_id is None:
        return True

    trackers = _custom_field_trackers_to_list(custom_field)
    if not trackers:
        # No tracker restrictions exposed by Redmine -> treat as globally available.
        return True

    for tracker in trackers:
        if tracker.get("id") == tracker_id:
            return True

    return False


def _custom_field_to_dict(custom_field: Any) -> Dict[str, Any]:
    """Convert project issue custom field metadata to a serializable dict."""
    return {
        "id": getattr(custom_field, "id", None),
        "name": getattr(custom_field, "name", ""),
        "field_format": getattr(custom_field, "field_format", ""),
        "is_required": bool(getattr(custom_field, "is_required", False)),
        "multiple": bool(getattr(custom_field, "multiple", False)),
        "default_value": getattr(custom_field, "default_value", None),
        "possible_values": _extract_possible_values(custom_field),
        "trackers": _custom_field_trackers_to_list(custom_field),
    }


@mcp.tool()
async def get_redmine_issue(
    issue_id: int,
    include_journals: bool = True,
    include_attachments: bool = True,
    include_custom_fields: bool = True,
    journal_limit: Optional[int] = None,
    journal_offset: int = 0,
    include_watchers: bool = False,
    include_relations: bool = False,
    include_children: bool = False,
) -> Dict[str, Any]:
    """Retrieve a specific Redmine issue by ID.

    Args:
        issue_id: The ID of the issue to retrieve
        include_journals: Whether to include journals (comments) in the result.
            Defaults to ``True``.
        include_attachments: Whether to include attachments metadata in the
            result. Defaults to ``True``.
        include_custom_fields: Whether to include custom fields in the
            result. Defaults to ``True``.
        journal_limit: Maximum number of journals to return. When set,
            enables journal pagination and adds ``journal_pagination``
            metadata to the response.
        journal_offset: Number of journals to skip (used with
            ``journal_limit``). Defaults to ``0``.

    Returns:
        A dictionary containing issue details. If ``include_journals`` is ``True``
        and the issue has journals, they will be returned under the ``"journals"``
        key. If ``include_attachments`` is ``True`` and attachments exist they
        will be returned under the ``"attachments"`` key. On failure a dictionary
        with an ``"error"`` key is returned.
        When ``REDMINE_AGILE_ENABLED=true``, the result also includes
        ``story_points``, ``agile_sprint_id``, and ``agile_position``
        fetched from the RedmineUP Agile plugin endpoint (omitted
        silently on any failure).
    """

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()
    try:
        # python-redmine is synchronous, so we don't use await here for the library call
        includes = []
        if include_journals:
            includes.append("journals")
        if include_attachments:
            includes.append("attachments")
        if include_watchers:
            includes.append("watchers")
        if include_relations:
            includes.append("relations")
        if include_children:
            includes.append("children")

        if includes:
            issue = _get_redmine_client().issue.get(
                issue_id, include=",".join(includes)
            )
        else:
            issue = _get_redmine_client().issue.get(issue_id)

        result = _issue_to_dict(issue, include_custom_fields=include_custom_fields)
        if include_journals:
            all_journals = _journals_to_list(issue)
            if journal_limit is not None:
                total = len(all_journals)
                offset = journal_offset
                paginated = all_journals[offset : offset + journal_limit]
                result["journals"] = paginated
                result["journal_pagination"] = {
                    "total": total,
                    "offset": offset,
                    "limit": journal_limit,
                    "count": len(paginated),
                    "has_more": (offset + journal_limit) < total,
                }
            else:
                result["journals"] = all_journals
        if include_attachments:
            result["attachments"] = _attachments_to_list(issue)

        if include_watchers:
            raw = getattr(issue, "watchers", None) or []
            result["watchers"] = [{"id": w.id, "name": w.name} for w in raw]
        if include_relations:
            raw = getattr(issue, "relations", None) or []
            result["relations"] = [
                {
                    "id": r.id,
                    "issue_id": r.issue_id,
                    "issue_to_id": r.issue_to_id,
                    "relation_type": r.relation_type,
                }
                for r in raw
            ]
        if include_children:
            raw = getattr(issue, "children", None) or []
            result["children"] = [
                {
                    "id": c.id,
                    "subject": getattr(c, "subject", ""),
                    "tracker": (
                        {"id": c.tracker.id, "name": c.tracker.name}
                        if getattr(c, "tracker", None)
                        else None
                    ),
                }
                for c in raw
            ]

        if _is_agile_enabled():
            try:
                agile = _fetch_agile_data(issue_id)
                result.update(agile)
            except Exception:
                pass  # Silently omit agile fields on any failure

        return result
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def list_redmine_projects() -> List[Dict[str, Any]]:
    """
    Lists all accessible projects in Redmine.
    Returns:
        A list of dictionaries, each representing a project.
    """
    try:
        projects = _get_redmine_client().project.all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "identifier": project.identifier,
                "description": getattr(project, "description", ""),
                "created_on": _safe_isoformat(getattr(project, "created_on", None)),
            }
            for project in projects
        ]
    except Exception as e:
        return [_handle_redmine_error(e, "listing projects")]


@mcp.tool()
async def list_project_issue_custom_fields(
    project_id: Union[str, int], tracker_id: Optional[Union[str, int]] = None
) -> List[Dict[str, Any]]:
    """List issue custom fields configured for a project.

    Args:
        project_id: Project identifier (ID number or string identifier).
        tracker_id: Optional tracker ID to filter custom fields by applicability.

    Returns:
        A list of custom field metadata dictionaries. On failure a list containing
        a single dictionary with an ``"error"`` key is returned.
    """

    parsed_tracker_id: Optional[int] = None
    if tracker_id is not None:
        try:
            parsed_tracker_id = int(tracker_id)
        except (TypeError, ValueError):
            return [
                {
                    "error": (
                        f"Invalid tracker_id '{tracker_id}'. "
                        "Expected an integer tracker ID."
                    )
                }
            ]

    await _ensure_cleanup_started()

    try:
        project = _get_redmine_client().project.get(
            project_id, include="issue_custom_fields"
        )
        custom_fields = getattr(project, "issue_custom_fields", None) or []

        result: List[Dict[str, Any]] = []
        for custom_field in custom_fields:
            if not _custom_field_applies_to_tracker(custom_field, parsed_tracker_id):
                continue
            result.append(_custom_field_to_dict(custom_field))

        return result
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing issue custom fields for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


@mcp.tool()
async def list_redmine_versions(
    project_id: Union[str, int],
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List versions (roadmap milestones) for a Redmine project.

    Args:
        project_id: The project ID (numeric) or identifier (string).
        status_filter: Optional filter by version status.
            Allowed values: open, locked, closed.
            When None, all versions are returned.

    Returns:
        A list of version dictionaries. On failure a list containing
        a single dictionary with an ``"error"`` key is returned.
    """

    # Validate status_filter before making API call
    valid_statuses = {"open", "locked", "closed"}
    if status_filter is not None:
        status_filter = str(status_filter).lower()
        if status_filter not in valid_statuses:
            return [
                {
                    "error": (
                        f"Invalid status_filter '{status_filter}'. "
                        f"Allowed values: open, locked, closed"
                    )
                }
            ]

    await _ensure_cleanup_started()
    try:
        versions = _get_redmine_client().version.filter(project_id=project_id)
        result = []
        for version in versions:
            if status_filter is not None:
                if getattr(version, "status", "") != status_filter:
                    continue
            result.append(_version_to_dict(version))
        return result
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing versions for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


@mcp.tool()
async def manage_redmine_version(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    version_id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    due_date: Optional[str] = None,
    sharing: Optional[str] = None,
    wiki_page_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Create, update, or delete a Redmine version (milestone/roadmap entry).

    Args:
        action: Operation to perform. One of: ``create``, ``update``,
            ``delete``.
        project_id: Project ID or string identifier. Required for
            ``action="create"``.
        version_id: Numeric version ID. Required for ``action="update"``
            and ``action="delete"``.
        name: Version name. Required for ``action="create"``, optional
            for ``action="update"``.
        description: Version description text.
        status: Version status. Allowed values: ``open``, ``locked``,
            ``closed``. Defaults to ``open`` on create.
        due_date: Due date in ``YYYY-MM-DD`` format.
        sharing: Sharing scope. Allowed values: ``none``, ``descendants``,
            ``hierarchy``, ``tree``, ``system``. Defaults to ``none`` on
            create.
        wiki_page_title: Associated wiki page title.

    Returns:
        For ``create``/``update``: full version dictionary.
        For ``delete``: ``{"success": True, "version_id": ...,
        "message": "..."}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"create", "update", "delete"}
    _valid_statuses = {"open", "locked", "closed"}

    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: create, update, delete"}

    if status is not None and status not in _valid_statuses:
        return {"error": f"Invalid status '{status}'. Allowed: open, locked, closed"}

    if action == "create":
        if project_id is None:
            return {"error": "project_id is required for action 'create'"}
        if name is None:
            return {"error": "name is required for action 'create'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        optional_fields: Dict[str, Any] = {
            "status": status if status is not None else "open",
            "sharing": sharing if sharing is not None else "none",
        }
        if description is not None:
            optional_fields["description"] = description
        if due_date is not None:
            optional_fields["due_date"] = due_date
        if wiki_page_title is not None:
            optional_fields["wiki_page_title"] = wiki_page_title

        try:
            version = _get_redmine_client().version.create(
                project_id=project_id,
                name=name,
                **optional_fields,
            )
            return _version_to_dict(version)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating version '{name}' in project {project_id}",
                {"resource_type": "version", "resource_id": name},
            )

    elif action == "update":
        if version_id is None:
            return {"error": "version_id is required for action 'update'"}

        _candidates = {
            "name": name,
            "description": description,
            "status": status,
            "due_date": due_date,
            "sharing": sharing,
            "wiki_page_title": wiki_page_title,
        }
        update_fields = {k: v for k, v in _candidates.items() if v is not None}

        if not update_fields:
            return {"error": "At least one field must be provided to update"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().version.update(version_id, **update_fields)
            version = _get_redmine_client().version.get(version_id)
            return _version_to_dict(version)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating version {version_id}",
                {"resource_type": "version", "resource_id": version_id},
            )

    else:  # action == "delete"
        if version_id is None:
            return {"error": "version_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().version.delete(version_id)
            return {
                "success": True,
                "version_id": version_id,
                "message": "Version deleted successfully.",
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting version {version_id}",
                {"resource_type": "version", "resource_id": version_id},
            )


@mcp.tool()
async def list_redmine_issues(
    project_id: Optional[Union[int, str]] = None,
    status_id: Optional[int] = None,
    tracker_id: Optional[int] = None,
    assigned_to_id: Optional[Union[int, str]] = None,
    priority_id: Optional[int] = None,
    fixed_version_id: Optional[int] = None,
    sort: Optional[str] = None,
    limit: Optional[int] = 25,
    offset: int = 0,
    include_pagination_info: bool = False,
    fields: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List Redmine issues with flexible filtering and pagination support.

    A general-purpose tool for listing issues from Redmine. Supports
    filtering by project, status, assignee, tracker, priority, and any
    other Redmine issue filter. Use this to list all issues in a project,
    find unassigned issues, or apply any combination of filters.

    Args:
        project_id: Filter by project (ID or string identifier).
        status_id: Filter by status ID.
        tracker_id: Filter by tracker ID.
        assigned_to_id: Filter by assignee. Use a numeric user ID or the
            special value 'me' to retrieve issues assigned to the currently
            authenticated user.
        priority_id: Filter by priority ID.
        fixed_version_id: Filter by target version/milestone ID.
        sort: Sort order (e.g., "updated_on:desc").
        limit: Maximum number of issues to return (default: 25, max: 1000).
        offset: Number of issues to skip for pagination (default: 0).
        include_pagination_info: Return structured response with pagination
            metadata (default: False).
        fields: List of field names to include in results (default: all).
            Available: id, subject, description, project, status, priority,
            author, assigned_to, created_on, updated_on.
        filters: Additional Redmine API filter parameters as a dict. Use this
            for any filter not listed above (e.g., {"cf_1": "value"}).

    Returns:
        List[Dict] (default) or Dict with 'issues' and 'pagination' keys.
        Issues are limited to prevent token overflow (25,000 token MCP limit).

    Examples:
        >>> await list_redmine_issues(project_id=1)
        [{"id": 1, "subject": "Issue 1", ...}, ...]

        >>> await list_redmine_issues(project_id="my-project", status_id=1)
        [{"id": 2, "subject": "Open issue", ...}, ...]

        >>> await list_redmine_issues(
        ...     project_id=1, limit=25, offset=50, include_pagination_info=True
        ... )
        {
            "issues": [...],
            "pagination": {"total": 150, "has_next": True, "next_offset": 75, ...}
        }

        >>> await list_redmine_issues(
        ...     project_id=1, fields=["id", "subject", "status"]
        ... )
        [{"id": 1, "subject": "Bug fix", "status": {...}}, ...]

    Performance:
        - Memory efficient: Uses server-side pagination
        - Token efficient: Default limit keeps response under 2000 tokens
        - Further reduce tokens: Use fields parameter for minimal data transfer
        - Time efficient: Typically <500ms for limit=25
    """

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Build Redmine API filter dict from explicit parameters
        redmine_api_filters: Dict[str, Any] = {}
        if project_id is not None:
            redmine_api_filters["project_id"] = project_id
        if status_id is not None:
            redmine_api_filters["status_id"] = status_id
        if tracker_id is not None:
            redmine_api_filters["tracker_id"] = tracker_id
        if assigned_to_id is not None:
            redmine_api_filters["assigned_to_id"] = assigned_to_id
        if priority_id is not None:
            redmine_api_filters["priority_id"] = priority_id
        if fixed_version_id is not None:
            redmine_api_filters["fixed_version_id"] = fixed_version_id
        if sort is not None:
            redmine_api_filters["sort"] = sort
        # Merge additional arbitrary Redmine filters if provided
        if filters:
            redmine_api_filters.update(filters)
        filters = redmine_api_filters

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
            "offset": offset,
            "limit": min(limit or 25, 100),  # Redmine API max per request
            **filters,
        }

        # Get paginated issues from Redmine
        logging.debug(
            f"Calling _get_redmine_client().issue.filter with: {redmine_filters}"
        )
        issues = _get_redmine_client().issue.filter(**redmine_filters)

        # Convert ResourceSet to list (triggers server-side pagination)
        issues_list = list(issues)
        logging.debug(
            f"Retrieved {len(issues_list)} issues with offset={offset}, limit={limit}"
        )

        # Convert to dictionaries with optional field selection
        result_issues = [
            _issue_to_dict_selective(issue, fields) for issue in issues_list
        ]

        # Handle metadata response format
        if include_pagination_info:
            # Get total count from a separate query without offset/limit
            try:
                # Create clean query for total count (no pagination parameters)
                count_filters = {**filters}
                count_query = _get_redmine_client().issue.filter(**count_filters)
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
        return [_handle_redmine_error(e, "listing issues")]


@mcp.tool()
async def search_redmine_issues(
    query: str,
    limit: Optional[int] = 25,
    offset: int = 0,
    include_pagination_info: bool = False,
    fields: Optional[List[str]] = None,
    scope: Optional[str] = None,
    open_issues: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Search Redmine issues matching a query string with pagination support.

    Performs text search across issues using the Redmine Search API.
    Supports server-side pagination to prevent MCP token overflow.

    Args:
        query: Text to search for in issues.
        limit: Maximum number of issues to return (default: 25, max: 1000).
        offset: Number of issues to skip for pagination (default: 0).
        include_pagination_info: Return structured response with pagination
            metadata (default: False).
        fields: List of field names to include in results (default: all).
            Available: id, subject, description, project, status, priority,
            author, assigned_to, created_on, updated_on.
        scope: Search scope. Values: "all", "my_project", "subprojects".
        open_issues: Search only open issues (default: False).
        options: Additional Redmine Search API parameters as a dict.

    Returns:
        List[Dict] (default) or Dict with 'issues' and 'pagination' keys.
        Issues are limited to prevent token overflow (25,000 token MCP limit).

    Examples:
        >>> await search_redmine_issues("bug fix")
        [{"id": 1, "subject": "Bug in login", ...}, ...]

        >>> await search_redmine_issues(
        ...     "performance", limit=10, offset=0, include_pagination_info=True
        ... )
        {
            "issues": [...],
            "pagination": {"limit": 10, "offset": 0, "has_next": True, ...}
        }

        >>> await search_redmine_issues("urgent", fields=["id", "subject", "status"])
        [{"id": 1, "subject": "Critical bug", "status": {...}}, ...]

        >>> await search_redmine_issues("bug", scope="my_project", open_issues=True)
        [{"id": 1, "subject": "Open bug in my project", ...}, ...]

    Note:
        The Redmine Search API does not provide total_count. Pagination
        metadata uses conservative estimation: has_next=True if result
        count equals limit.

        Search API Limitations: The Search API supports text search with
        scope and open_issues filters only. For advanced filtering by
        project_id, status_id, priority_id, etc., use list_redmine_issues()
        instead, which uses the Issues API with full filter support.

    Performance:
        - Memory efficient: Uses server-side pagination
        - Token efficient: Default limit keeps response under 2000 tokens
        - Further reduce tokens: Use fields parameter for minimal data transfer
    """

    try:
        # Build search options dict from explicit parameters
        search_options: Dict[str, Any] = {}
        if scope is not None:
            search_options["scope"] = scope
        if open_issues:
            search_options["open_issues"] = open_issues
        # Merge additional arbitrary search options if provided
        if options:
            search_options.update(options)
        options = search_options

        # Log request for monitoring
        option_keys = list(options.keys()) if options else []
        logging.info(
            f"Search request: query='{query}', limit={limit}, "
            f"offset={offset}, options={option_keys}"
        )

        # Validate and sanitize limit parameter
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
                    f"Limit {original_limit} exceeds maximum 1000, "
                    f"capped to {limit}"
                )

        # Validate offset
        if not isinstance(offset, int) or offset < 0:
            logging.warning(f"Invalid offset {offset}, reset to 0")
            offset = 0

        # Pass offset and limit to Redmine Search API
        search_params = {"offset": offset, "limit": limit, **options}

        # Perform search with pagination
        logging.debug(
            f"Calling _get_redmine_client().issue.search with: {search_params}"
        )
        results = _get_redmine_client().issue.search(query, **search_params)

        if results is None:
            results = []

        # Convert results to list
        issues_list = list(results)
        logging.debug(
            f"Retrieved {len(issues_list)} issues with "
            f"offset={offset}, limit={limit}"
        )

        # Convert to dictionaries with optional field selection
        result_issues = [
            _issue_to_dict_selective(issue, fields) for issue in issues_list
        ]

        # Handle metadata response format
        if include_pagination_info:
            # Search API doesn't provide total_count
            # Use conservative estimation
            pagination_info = {
                "limit": limit,
                "offset": offset,
                "count": len(result_issues),
                "has_next": len(result_issues) == limit,
                "has_previous": offset > 0,
                "next_offset": (
                    offset + limit if len(result_issues) == limit else None
                ),
                "previous_offset": max(0, offset - limit) if offset > 0 else None,
            }

            result = {"issues": result_issues, "pagination": pagination_info}

            logging.info(
                f"Returning paginated search response: " f"{len(result_issues)} issues"
            )
            return result

        # Log success and return simple list
        logging.info(f"Successfully searched and retrieved {len(result_issues)} issues")
        return result_issues

    except Exception as e:
        return _handle_redmine_error(e, f"searching issues with query '{query}'")


@mcp.tool()
async def create_redmine_issue(
    project_id: int,
    subject: str,
    description: str = "",
    fields: Optional[Union[Dict[str, Any], str]] = None,
    extra_fields: Optional[Union[Dict[str, Any], str]] = None,
) -> Dict[str, Any]:
    """Create a new issue in Redmine.

    Compatibility notes:
    - Supports serialized ``fields`` payload (JSON object string)
    - Supports optional ``extra_fields`` payload as object/JSON string
    - Retries once with auto-filled required custom fields if Redmine reports
      relevant validation errors on required custom fields (e.g. blank/invalid)
      and
      ``REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true``.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    try:
        issue_fields = _parse_create_issue_fields(fields)
    except ValueError as e:
        return {"error": str(e)}

    try:
        parsed_extra_fields = _parse_optional_object_payload(
            extra_fields, "extra_fields"
        )
    except ValueError as e:
        return {"error": str(e)}

    if parsed_extra_fields:
        issue_fields.update(parsed_extra_fields)

    # Prevent callers from overriding explicit positional parameters.
    issue_fields.pop("project_id", None)
    issue_fields.pop("subject", None)
    issue_fields.pop("description", None)
    issue_fields.pop("extra_fields", None)

    try:
        issue = _get_redmine_client().issue.create(
            project_id=project_id,
            subject=subject,
            description=description,
            **issue_fields,
        )
        return _issue_to_dict(issue)
    except ValidationError as e:
        if not _is_required_custom_field_autofill_enabled():
            return _handle_redmine_error(e, f"creating issue in project {project_id}")

        missing_names = _extract_missing_required_field_names(str(e))
        if not missing_names:
            return _handle_redmine_error(e, f"creating issue in project {project_id}")

        try:
            retry_fields = _augment_fields_with_required_custom_fields(
                project_id=project_id,
                issue_fields=issue_fields,
                missing_field_names=missing_names,
            )

            # Retry only when we have actually augmented payload.
            if retry_fields == issue_fields:
                return _handle_redmine_error(
                    e, f"creating issue in project {project_id}"
                )

            logger.info(
                "Retrying issue creation with auto-filled custom fields: %s",
                missing_names,
            )
            issue = _get_redmine_client().issue.create(
                project_id=project_id,
                subject=subject,
                description=description,
                **retry_fields,
            )
            return _issue_to_dict(issue)
        except Exception as retry_error:
            return _handle_redmine_error(
                retry_error, f"creating issue in project {project_id}"
            )
    except Exception as e:
        return _handle_redmine_error(e, f"creating issue in project {project_id}")


@mcp.tool()
async def update_redmine_issue(issue_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing Redmine issue.

    In addition to standard Redmine fields, a ``status_name`` key may be
    provided in ``fields``. When present and ``status_id`` is not supplied, the
    function will look up the corresponding status ID and use it for the update.

    When ``REDMINE_AGILE_ENABLED=true``, a ``story_points`` key may also be
    provided in ``fields``; it is routed to the RedmineUP Agile plugin endpoint
    separately and is not passed to the standard Redmine update. When
    ``REDMINE_AGILE_ENABLED=false`` (default), ``story_points`` is silently
    ignored.

    Non-standard keys in ``fields`` are treated as candidate custom-field names.
    When a matching project custom field is found, it is translated into
    ``custom_fields`` entries for Redmine update payloads.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    update_fields = dict(fields)

    # Extract agile fields — not understood by python-redmine.
    # Use explicit key presence check so story_points=None (clear) still triggers
    # the agile endpoint (story_points is not None would skip it).
    story_points = None
    agile_update_needed = False
    if _is_agile_enabled():
        if "story_points" in update_fields:
            story_points = update_fields.pop("story_points")
            agile_update_needed = True
    else:
        update_fields.pop("story_points", None)

    # Convert status name to id if requested
    if "status_name" in update_fields and "status_id" not in update_fields:
        name = str(update_fields.pop("status_name")).lower()
        try:
            statuses = _get_redmine_client().issue_status.all()
            for status in statuses:
                if getattr(status, "name", "").lower() == name:
                    update_fields["status_id"] = status.id
                    break
        except Exception as e:
            logger.warning(f"Error resolving status name '{name}': {e}")

    try:
        if update_fields:
            update_fields = _map_named_custom_fields_for_update(issue_id, update_fields)
            _get_redmine_client().issue.update(issue_id, **update_fields)
        if agile_update_needed:
            try:
                _apply_agile_story_points(issue_id, story_points)
            except Exception as agile_e:
                return _handle_redmine_error(
                    agile_e,
                    f"updating agile story_points for issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )
        updated_issue = _get_redmine_client().issue.get(issue_id)
        return _issue_to_dict(updated_issue, include_custom_fields=True)
    except ValidationError as e:
        if not _is_required_custom_field_autofill_enabled():
            return _handle_redmine_error(
                e,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

        missing_names = _extract_missing_required_field_names(str(e))
        if not missing_names:
            return _handle_redmine_error(
                e,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

        try:
            issue = _get_redmine_client().issue.get(issue_id)
            project = getattr(issue, "project", None)
            project_id = getattr(project, "id", None)
            if project_id is None:
                return _handle_redmine_error(
                    e,
                    f"updating issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )

            retry_fields = _augment_fields_with_required_custom_fields(
                project_id=project_id,
                issue_fields=update_fields,
                missing_field_names=missing_names,
            )

            # Retry only when we have actually augmented payload.
            if retry_fields == update_fields:
                return _handle_redmine_error(
                    e,
                    f"updating issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )

            logger.info(
                "Retrying issue update with auto-filled custom fields: %s",
                missing_names,
            )
            _get_redmine_client().issue.update(issue_id, **retry_fields)
            if agile_update_needed:
                try:
                    _apply_agile_story_points(issue_id, story_points)
                except Exception as agile_e:
                    return _handle_redmine_error(
                        agile_e,
                        f"updating agile story_points for issue {issue_id}",
                        {"resource_type": "issue", "resource_id": issue_id},
                    )
            updated_issue = _get_redmine_client().issue.get(issue_id)
            return _issue_to_dict(updated_issue, include_custom_fields=True)
        except Exception as retry_error:
            return _handle_redmine_error(
                retry_error,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


# ---------------------------------------------------------------------------
# Issue tracking helpers (relations, categories, journals)
# ---------------------------------------------------------------------------


_VALID_ISSUE_RELATION_TYPES: Set[str] = {
    "relates",
    "duplicates",
    "duplicated",
    "blocks",
    "blocked",
    "precedes",
    "follows",
    "copied_to",
    "copied_from",
}


def _issue_relation_to_dict(relation: Any) -> Dict[str, Any]:
    """Convert a python-redmine IssueRelation object to a serializable dict."""
    return {
        "id": getattr(relation, "id", None),
        "issue_id": getattr(relation, "issue_id", None),
        "issue_to_id": getattr(relation, "issue_to_id", None),
        "relation_type": getattr(relation, "relation_type", None),
        "delay": getattr(relation, "delay", None),
    }


def _issue_category_to_dict(category: Any) -> Dict[str, Any]:
    """Convert a python-redmine IssueCategory object to a serializable dict."""
    project = getattr(category, "project", None)
    assigned_to = getattr(category, "assigned_to", None)
    return {
        "id": getattr(category, "id", None),
        "name": wrap_insecure_content(getattr(category, "name", "")),
        "project": _named_ref(project),
        "assigned_to": _named_ref(assigned_to),
    }


def _journal_to_dict(journal: Any, include_private_flag: bool = True) -> Dict[str, Any]:
    """Convert a python-redmine IssueJournal to a serializable dict.

    Unlike `_journals_to_list`, this helper preserves empty-notes entries
    (since they can still carry field-change details) and optionally exposes
    the ``private_notes`` flag.
    """
    user = getattr(journal, "user", None)
    notes = getattr(journal, "notes", "") or ""
    entry: Dict[str, Any] = {
        "id": getattr(journal, "id", None),
        "user": (
            {"id": user.id, "name": getattr(user, "name", "")}
            if user is not None
            else None
        ),
        "notes": wrap_insecure_content(notes) if notes else "",
        "created_on": _safe_isoformat(getattr(journal, "created_on", None)),
    }
    if include_private_flag:
        entry["private_notes"] = bool(getattr(journal, "private_notes", False))
    return entry


# ---------------------------------------------------------------------------
# Issue tracking tools (copy, relations, subtasks, notes, watchers, categories)
# ---------------------------------------------------------------------------


@mcp.tool()
async def copy_issue(
    issue_id: int,
    project_id: Optional[Union[str, int]] = None,
    subject: Optional[str] = None,
    link_original: bool = True,
    copy_subtasks: bool = True,
    copy_attachments: bool = True,
    field_overrides: Optional[Union[Dict[str, Any], str]] = None,
) -> Dict[str, Any]:
    """Duplicate an existing Redmine issue with optional field overrides.

    Uses Redmine's native copy mechanism (``copy_from`` parameter) which
    preserves the original issue's fields while allowing selected overrides.

    Args:
        issue_id: ID of the source issue to copy.
        project_id: Target project for the new issue (ID or identifier).
            Defaults to the source issue's project when omitted.
        subject: Optional new subject for the copy. Defaults to the source
            issue's subject when omitted.
        link_original: When True (default), creates a ``copied_to``/
            ``copied_from`` relation between the original and the copy.
        copy_subtasks: When True (default), the source issue's subtasks are
            recursively copied.
        copy_attachments: When True (default), attachments are copied to
            the new issue.
        field_overrides: Optional dict (or JSON object string) of field
            values to override on the copy (e.g.,
            ``{"assigned_to_id": 5, "description": "..."}``).

    Returns:
        Dictionary containing the newly created issue. On failure a dict
        with an ``"error"`` key is returned.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    try:
        overrides = _parse_optional_object_payload(field_overrides, "field_overrides")
    except ValueError as e:
        return {"error": str(e)}

    # Prevent accidental overwrite of resolved positional-like params.
    overrides.pop("issue_id", None)
    overrides.pop("copy_from", None)

    if project_id is not None:
        overrides["project_id"] = project_id
    if subject is not None:
        overrides["subject"] = subject

    # python-redmine's copy() does `include or ('subtasks', 'attachments')`
    # (managers/standard.py:22-32) — meaning an EMPTY tuple is falsy and
    # silently falls back to copying both. We must pass a sentinel list
    # ['none'] when both flags are False so the library sees truthy input
    # without actually including subtasks or attachments.
    # Any other non-empty input (e.g. ['none']) produces no matching
    # copy_* parameter and therefore copies nothing.
    include_parts: List[str] = []
    if copy_subtasks:
        include_parts.append("subtasks")
    if copy_attachments:
        include_parts.append("attachments")
    if not include_parts:
        # Sentinel prevents the library's default-fallback. "none" is not a
        # recognized include, so no copy_none=1 is added to the request.
        include_parts = ["none"]
    include_tuple = tuple(include_parts)

    try:
        new_issue = _get_redmine_client().issue.copy(
            issue_id,
            link_original=link_original,
            include=include_tuple,
            **overrides,
        )
        return _issue_to_dict(new_issue, include_custom_fields=True)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"copying issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_relation(
    action: str,
    issue_id: Optional[int] = None,
    issue_to_id: Optional[int] = None,
    relation_id: Optional[int] = None,
    relation_type: Optional[str] = None,
    delay: Optional[int] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, create, or delete a Redmine issue relation.

    Args:
        action: One of: ``list``, ``create``, ``delete``.
        issue_id: Source issue ID. Required for ``list`` and ``create``.
        issue_to_id: Target issue ID. Required for ``create``.
        relation_id: Relation ID. Required for ``delete``.
        relation_type: One of: ``relates``, ``duplicates``, ``duplicated``,
            ``blocks``, ``blocked``, ``precedes``, ``follows``,
            ``copied_to``, ``copied_from``. Defaults to ``relates`` for
            ``create``.
        delay: Delay in days for ``precedes`` / ``follows`` relations.

    Returns:
        ``list``: list of relation dicts.
        ``create``: relation dict.
        ``delete``: ``{"success": True, "deleted_relation_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"list", "create", "delete"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: list, create, delete"}

    if action == "list":
        if issue_id is None:
            return {"error": "issue_id is required for action 'list'"}
        try:
            relations = _get_redmine_client().issue_relation.filter(issue_id=issue_id)
            return [_issue_relation_to_dict(r) for r in _iter_capped(relations)]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing relations for issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

    elif action == "create":
        if issue_id is None:
            return {"error": "issue_id is required for action 'create'"}
        if issue_to_id is None:
            return {"error": "issue_to_id is required for action 'create'"}

        _rt = relation_type if relation_type is not None else "relates"
        if _rt not in _VALID_ISSUE_RELATION_TYPES:
            return {
                "error": (
                    f"Invalid relation_type '{_rt}'. Must be one of: "
                    f"{', '.join(sorted(_VALID_ISSUE_RELATION_TYPES))}."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params: Dict[str, Any] = {
                "issue_id": issue_id,
                "issue_to_id": issue_to_id,
                "relation_type": _rt,
            }
            if delay is not None:
                params["delay"] = delay
            relation = _get_redmine_client().issue_relation.create(**params)
            return _issue_relation_to_dict(relation)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating relation from issue {issue_id} to {issue_to_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

    else:  # action == "delete"
        if relation_id is None:
            return {"error": "relation_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().issue_relation.delete(relation_id)
            return {"success": True, "deleted_relation_id": relation_id}
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting relation {relation_id}",
                {"resource_type": "relation", "resource_id": relation_id},
            )


@mcp.tool()
async def list_subtasks(
    issue_id: int,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List subtasks (child issues) of a given Redmine issue.

    Retrieves all issues whose ``parent_issue_id`` equals the given
    ``issue_id``. To create a new subtask, use ``create_redmine_issue``
    with the ``parent_issue_id`` field set.

    Args:
        issue_id: ID of the parent issue.

    Returns:
        List of child issue dictionaries. On failure a list containing a
        single dictionary with an ``"error"`` key is returned.
    """
    try:
        # Include closed subtasks as well (status_id=*) to match Redmine's
        # parent/child display.
        children = _get_redmine_client().issue.filter(
            parent_id=issue_id,
            status_id="*",
        )
        return [_issue_to_dict(c) for c in _iter_capped(children)]
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing subtasks for issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_watcher(
    action: str,
    issue_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """Add or remove a watcher on a Redmine issue. Requires Redmine 2.3.0+.

    Args:
        action: One of: ``add``, ``remove``.
        issue_id: ID of the issue.
        user_id: ID of the user to add or remove as a watcher.

    Returns:
        ``{"success": True, "issue_id": ..., "user_id": ...}`` on success.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"add", "remove"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: add, remove"}

    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}
    if not _is_positive_int(user_id):
        return {"error": "user_id must be a positive integer."}

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    await _ensure_cleanup_started()

    try:
        issue = _get_redmine_client().issue.get(issue_id)
        if action == "add":
            issue.watcher.add(user_id)
        else:
            issue.watcher.remove(user_id)
        return {"success": True, "issue_id": issue_id, "user_id": user_id}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"{action}ing watcher {user_id} on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_note(
    action: str,
    journal_id: int,
    notes: Optional[str] = None,
    private_notes: Optional[bool] = None,
    is_private: Optional[bool] = None,
) -> Dict[str, Any]:
    """Edit text or toggle privacy of a Redmine journal (issue note).

    Both actions are writes and are blocked in read-only mode.

    Args:
        action: One of: ``edit``, ``set_private``.
        journal_id: ID of the journal entry (required for both actions).
        notes: New notes text for ``edit`` (required; may be empty string
            to clear the note).
        private_notes: Optionally toggle private flag during ``edit``.
        is_private: Required for ``set_private`` -- ``True`` to mark
            private, ``False`` to make public.

    Returns:
        ``edit``: ``{"success": True, "journal_id": ..., "notes": ...,
        "private_notes": ...}``.
        ``set_private``: ``{"success": True, "journal_id": ...,
        "private_notes": <bool>}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"edit", "set_private"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: edit, set_private"}

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    if action == "edit":
        if notes is None:
            return {"error": "notes is required for action 'edit'"}
        try:
            params: Dict[str, Any] = {"notes": notes}
            if private_notes is not None:
                params["private_notes"] = bool(private_notes)
            _get_redmine_client().issue_journal.update(journal_id, **params)
            return {
                "success": True,
                "journal_id": journal_id,
                "notes": notes,
                "private_notes": (
                    bool(private_notes) if private_notes is not None else None
                ),
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"editing journal {journal_id}",
                {"resource_type": "journal", "resource_id": journal_id},
            )

    else:  # action == "set_private"
        if is_private is None:
            return {"error": "is_private is required for action 'set_private'"}
        try:
            _get_redmine_client().issue_journal.update(
                journal_id, private_notes=bool(is_private)
            )
            return {
                "success": True,
                "journal_id": journal_id,
                "private_notes": bool(is_private),
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating privacy of journal {journal_id}",
                {"resource_type": "journal", "resource_id": journal_id},
            )


@mcp.tool()
async def get_private_notes(issue_id: int) -> List[Dict[str, Any]]:
    """Retrieve only the private notes/journals of a Redmine issue.

    Fetches the issue's journals and filters for entries where
    ``private_notes`` is true. The authenticated user must have the
    "View private notes" permission for non-empty results.

    Args:
        issue_id: ID of the issue.

    Returns:
        List of private journal dictionaries, each containing ``id``,
        ``user``, ``notes``, ``created_on``, and ``private_notes: true``.
        On failure a list with a single ``"error"`` dict is returned.
    """
    try:
        issue = _get_redmine_client().issue.get(issue_id, include="journals")
        raw_journals = getattr(issue, "journals", None) or []

        private: List[Dict[str, Any]] = []
        try:
            iterator = iter(raw_journals)
        except TypeError:
            return []

        for journal in iterator:
            if not bool(getattr(journal, "private_notes", False)):
                continue
            # Skip entries with no notes body (private detail-only records).
            if not getattr(journal, "notes", ""):
                continue
            private.append(_journal_to_dict(journal, include_private_flag=True))
        return private
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"fetching private notes for issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )
        ]


@mcp.tool()
async def manage_issue_category(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    category_id: Optional[int] = None,
    name: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    reassign_to_id: Optional[int] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, create, update, or delete a Redmine issue category.

    Args:
        action: One of: ``list``, ``create``, ``update``, ``delete``.
        project_id: Project ID or identifier. Required for ``list`` and
            ``create``.
        category_id: Category ID. Required for ``update`` and ``delete``.
        name: Category name. Required for ``create``, optional for
            ``update`` (cannot be blank).
        assigned_to_id: Default assignee user ID. Optional for ``create``
            and ``update``.
        reassign_to_id: Reassign existing issues to this category ID on
            ``delete``. Optional.

    Returns:
        ``list``: list of category dicts.
        ``create``/``update``: category dict.
        ``delete``: ``{"success": True, "deleted_category_id": ...,
        "reassigned_to_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"list", "create", "update", "delete"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. " "Allowed: list, create, update, delete"
            )
        }

    if action == "list":
        if project_id is None:
            return {"error": "project_id is required for action 'list'"}
        try:
            categories = _get_redmine_client().issue_category.filter(
                project_id=project_id
            )
            return [_issue_category_to_dict(c) for c in _iter_capped(categories)]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing issue categories for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "create":
        if project_id is None:
            return {"error": "project_id is required for action 'create'"}
        if not name or not name.strip():
            return {"error": "Category 'name' is required."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params: Dict[str, Any] = {
                "project_id": project_id,
                "name": name.strip(),
            }
            if assigned_to_id is not None:
                params["assigned_to_id"] = assigned_to_id
            category = _get_redmine_client().issue_category.create(**params)
            return _issue_category_to_dict(category)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating issue category in project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "update":
        if category_id is None:
            return {"error": "category_id is required for action 'update'"}

        update_params: Dict[str, Any] = {}
        if name is not None:
            stripped = name.strip()
            if not stripped:
                return {"error": "Category 'name' cannot be empty."}
            update_params["name"] = stripped
        if assigned_to_id is not None:
            update_params["assigned_to_id"] = assigned_to_id

        if not update_params:
            return {"error": "No fields provided for update."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            client = _get_redmine_client()
            client.issue_category.update(category_id, **update_params)
            updated = client.issue_category.get(category_id)
            return _issue_category_to_dict(updated)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating issue category {category_id}",
                {"resource_type": "issue_category", "resource_id": category_id},
            )

    else:  # action == "delete"
        if category_id is None:
            return {"error": "category_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params = {}
            if reassign_to_id is not None:
                params["reassign_to_id"] = reassign_to_id
            _get_redmine_client().issue_category.delete(category_id, **params)
            return {
                "success": True,
                "deleted_category_id": category_id,
                "reassigned_to_id": reassign_to_id,
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting issue category {category_id}",
                {"resource_type": "issue_category", "resource_id": category_id},
            )


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

    try:
        # Validate project exists
        try:
            project = _get_redmine_client().project.get(project_id)
        except ResourceNotFoundError:
            return {"error": f"Project {project_id} not found."}

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        date_filter = f">={start_date.strftime('%Y-%m-%d')}"

        # Get issues created in the date range
        created_issues = list(
            _get_redmine_client().issue.filter(
                project_id=project_id, created_on=date_filter
            )
        )

        # Get issues updated in the date range
        updated_issues = list(
            _get_redmine_client().issue.filter(
                project_id=project_id, updated_on=date_filter
            )
        )

        # Analyze created issues
        created_stats = _analyze_issues(created_issues)

        # Analyze updated issues
        updated_stats = _analyze_issues(updated_issues)

        # Calculate trends
        total_created = len(created_issues)
        total_updated = len(updated_issues)

        # Get all project issues for context
        all_issues = list(_get_redmine_client().issue.filter(project_id=project_id))
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
        return _handle_redmine_error(
            e,
            f"summarizing project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


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


def _membership_to_dict(membership: Any) -> Dict[str, Any]:
    """Convert a project membership to a serializable dict."""
    user = getattr(membership, "user", None)
    group = getattr(membership, "group", None)
    project = getattr(membership, "project", None)
    roles = getattr(membership, "roles", None) or []

    result: Dict[str, Any] = {
        "id": getattr(membership, "id", None),
    }

    # User or group (memberships can be for either)
    if user is not None:
        result["user"] = _named_ref(user)
        result["group"] = None
    elif group is not None:
        result["user"] = None
        result["group"] = _named_ref(group)
    else:
        result["user"] = None
        result["group"] = None

    # Project info
    result["project"] = _named_ref(project)

    # Roles
    result["roles"] = []
    try:
        for role in roles:
            if isinstance(role, dict):
                result["roles"].append(
                    {
                        "id": role.get("id"),
                        "name": wrap_insecure_content(role.get("name", "")),
                    }
                )
            else:
                result["roles"].append(
                    {
                        "id": getattr(role, "id", None),
                        "name": wrap_insecure_content(getattr(role, "name", "")),
                    }
                )
    except TypeError:
        pass  # roles not iterable

    return result


@mcp.tool()
async def list_project_members(
    project_id: Union[str, int],
) -> List[Dict[str, Any]]:
    """List members of a Redmine project.

    Returns all users and groups that are members of the specified project,
    along with their assigned roles.

    Args:
        project_id: Project identifier (ID number or string identifier)

    Returns:
        A list of membership dictionaries containing user/group info and roles.
        On failure, a list containing a single dictionary with an "error" key.

    Examples:
        >>> await list_project_members("my-project")
        [
            {
                "id": 1,
                "user": {"id": 5, "name": "John Doe"},
                "group": null,
                "project": {"id": 1, "name": "My Project"},
                "roles": [{"id": 3, "name": "Developer"}]
            },
            ...
        ]
    """
    try:
        memberships = _get_redmine_client().project_membership.filter(
            project_id=project_id
        )
        return [_membership_to_dict(m) for m in memberships]
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing members for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


# ---------------------------------------------------------------------------
# Project tools: modules + membership management
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_redmine_roles() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all roles defined in the Redmine instance.

    Returns basic role metadata (``id`` and ``name``) for every role
    configured in Redmine. Use this tool BEFORE calling
    ``add_project_member`` or ``update_project_member`` to discover the
    correct ``role_ids`` — role IDs vary between Redmine instances and
    must not be guessed.

    Returns:
        A list of role dictionaries, each with ``id`` and ``name``.
        On failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_roles()
        [
            {"id": 3, "name": "Manager"},
            {"id": 4, "name": "Developer"},
            {"id": 5, "name": "Reporter"}
        ]
    """
    try:
        roles = _get_redmine_client().role.all()
        return [
            {
                "id": getattr(r, "id", None),
                "name": getattr(r, "name", ""),
            }
            for r in roles
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing roles")


@mcp.tool()
async def get_project_modules(
    project_id: Union[str, int],
) -> Dict[str, Any]:
    """Retrieve the enabled modules for a Redmine project.

    Modules control which features are visible/usable in a project
    (e.g., ``issue_tracking``, ``time_tracking``, ``wiki``, ``repository``).

    Args:
        project_id: Project identifier (numeric ID or string identifier).

    Returns:
        Dictionary with ``project_id``, ``project_name`` and
        ``enabled_modules`` (list of module name strings). On failure a
        dict with an ``"error"`` key is returned.

    Example:
        >>> await get_project_modules("my-project")
        {
            "project_id": 1,
            "project_name": "My Project",
            "enabled_modules": ["issue_tracking", "wiki", "time_tracking"]
        }
    """
    try:
        project = _get_redmine_client().project.get(
            project_id, include="enabled_modules"
        )
        raw_modules = getattr(project, "enabled_modules", None) or []

        module_names: List[str] = []
        try:
            iterator = iter(raw_modules)
        except TypeError:
            iterator = iter(())

        for mod in iterator:
            # python-redmine's Project.encode() converts enabled_modules
            # to a plain list of strings. Older versions / raw HTTP
            # responses may return dicts or resource-like objects.
            if isinstance(mod, str):
                name = mod
            elif isinstance(mod, dict):
                name = mod.get("name")
            else:
                name = getattr(mod, "name", None)
            if name:
                module_names.append(str(name))

        return {
            "project_id": getattr(project, "id", None),
            "project_name": getattr(project, "name", ""),
            "enabled_modules": module_names,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"getting modules for project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


@mcp.tool()
async def manage_project_member(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    membership_id: Optional[int] = None,
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    role_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Add, update, or remove a Redmine project membership.

    Args:
        action: Operation to perform. One of: ``add``, ``update``, ``remove``.
        project_id: Project ID or identifier. Required for ``action="add"``.
        membership_id: Membership ID. Required for ``action="update"`` and
            ``action="remove"``.
        user_id: User ID. Exactly one of ``user_id`` or ``group_id`` required
            for ``action="add"``.
        group_id: Group ID. Exactly one of ``user_id`` or ``group_id`` required
            for ``action="add"``.
        role_ids: Non-empty list of role IDs. Required for ``action="add"``
            and ``action="update"``. Use ``list_redmine_roles`` to discover
            valid role IDs.

    Returns:
        For ``add``/``update``: membership dictionary.
        For ``remove``: ``{"success": True, "deleted_membership_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"add", "update", "remove"}
    if action not in _valid_actions:
        return {"error": (f"Invalid action '{action}'. Allowed: add, update, remove")}

    if action == "add":
        if project_id is None:
            return {"error": "project_id is required for action 'add'"}
        if (user_id is None) == (group_id is None):
            return {"error": "Exactly one of user_id or group_id must be provided."}
        principal_candidate = user_id if user_id is not None else group_id
        if not _is_positive_int(principal_candidate):
            return {"error": "user_id / group_id must be a positive integer."}
        if not role_ids:
            return {
                "error": (
                    "At least one role_id must be provided. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }
        if not isinstance(role_ids, list) or not all(
            _is_positive_int(r) for r in role_ids
        ):
            return {
                "error": (
                    "role_ids must be a list of positive integers. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        # Redmine's POST /projects/{id}/memberships endpoint uses `user_id`
        # for BOTH users and groups (shared principal ID namespace).
        principal_id = user_id if user_id is not None else group_id

        try:
            membership = _get_redmine_client().project_membership.create(
                project_id=project_id,
                user_id=principal_id,
                role_ids=role_ids,
            )
            return _membership_to_dict(membership)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"adding member to project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "update":
        if membership_id is None:
            return {"error": "membership_id is required for action 'update'"}
        if not role_ids:
            return {
                "error": (
                    "At least one role_id must be provided. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }
        if not isinstance(role_ids, list) or not all(
            _is_positive_int(r) for r in role_ids
        ):
            return {
                "error": (
                    "role_ids must be a list of positive integers. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            client = _get_redmine_client()
            client.project_membership.update(membership_id, role_ids=role_ids)
            updated = client.project_membership.get(membership_id)
            return _membership_to_dict(updated)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating project membership {membership_id}",
                {"resource_type": "membership", "resource_id": membership_id},
            )

    else:  # action == "remove"
        if membership_id is None:
            return {"error": "membership_id is required for action 'remove'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().project_membership.delete(membership_id)
            return {
                "success": True,
                "deleted_membership_id": membership_id,
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"removing project membership {membership_id}",
                {"resource_type": "membership", "resource_id": membership_id},
            )


# ---------------------------------------------------------------------------
# Time tracking tools: list, manage, activities, bulk import
#
# Tool definitions live in ``tools/time_tracking.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.time_tracking import (  # noqa: E402,F401
    _IMPORT_TIME_ENTRIES_MAX_BATCH,
    _time_entry_to_dict,
    import_time_entries,
    list_time_entries,
    list_time_entry_activities,
    manage_time_entry,
)

# ---------------------------------------------------------------------------
# Discovery / enumeration tools
#
# Tool definitions live in ``tools/enumeration.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.enumeration import (  # noqa: E402,F401
    get_current_user,
    list_redmine_issue_priorities,
    list_redmine_issue_statuses,
    list_redmine_queries,
    list_redmine_trackers,
    list_redmine_users,
)

# ---------------------------------------------------------------------------
# Products tools (requires RedmineUP Products plugin)
#
# Tool definition lives in ``tools/products.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.products import (  # noqa: E402,F401
    _PRODUCT_WRITABLE_FIELDS,
    _PRODUCTS_DISABLED_ERROR,
    _product_to_dict,
    manage_product,
)

# ---------------------------------------------------------------------------
# Gantt tool (composite — uses core REST API only, no plugin required)
#
# Tool definition lives in ``tools/gantt.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.gantt import (  # noqa: E402,F401
    _gantt_issue_to_dict,
    _gantt_version_to_dict,
    get_gantt_chart,
)

# ---------------------------------------------------------------------------
# Checklists tools (requires RedmineUP Checklists plugin)
#
# Tool definitions live in ``tools/checklists.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.checklists import (  # noqa: E402,F401
    _fetch_checklist_items,
    _update_checklist_item_api,
    get_checklist,
    update_checklist_item,
)

# ---------------------------------------------------------------------------
# Contacts tool (requires RedmineUP CRM plugin)
#
# Tool definition lives in ``tools/contacts.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.contacts import (  # noqa: E402,F401
    _CONTACT_WRITABLE_FIELDS,
    _CRM_DISABLED_ERROR,
    _contact_to_dict,
    manage_contact,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.files import (  # noqa: E402,F401
    _FILE_UPLOAD_MAX_SIZE_BYTES,
    _file_to_dict,
    cleanup_attachment_files,
    delete_file,
    get_redmine_attachment_download_url,
    list_files,
    upload_file,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.search import (  # noqa: E402,F401
    _resource_to_dict,
    search_entire_redmine,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.wiki import (  # noqa: E402,F401
    _wiki_page_to_dict,
    manage_redmine_wiki_page,
)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")
