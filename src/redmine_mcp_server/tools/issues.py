"""Issue tools: get/list/search/create/update/copy issues, plus subtasks,
relations, watchers, notes, and categories.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Set, Union

from redminelib.exceptions import ValidationError

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client, logger
from .._custom_fields import (
    _augment_fields_with_required_custom_fields,
    _extract_missing_required_field_names,
    _is_required_custom_field_autofill_enabled,
    _map_named_custom_fields_for_update,
    _parse_create_issue_fields,
    _parse_optional_object_payload,
)
from .._decorators import ActionMode, action_dispatch
from .._env import _is_agile_enabled, _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
from .._serialization import (
    _coerce_json_safe,
    _iter_capped,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int
from ..server import mcp

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


def _fetch_agile_data(issue_id: int) -> Dict[str, Any]:
    """Fetch agile fields for an issue from the RedmineUP Agile endpoint.

    Returns a dict with story_points, agile_sprint_id, and agile_position.
    Raises on any HTTP error (caller is responsible for catching).
    """
    # Lazy lookup so tests patching
    # `_client.REDMINE_URL` are observed at call time.
    from .. import _client

    client = _get_redmine_client()
    url = f"{_client.REDMINE_URL}/issues/{issue_id}/agile_data.json"
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
    # Lazy lookup so tests patching
    # `_client.REDMINE_URL` are observed at call time.
    from .. import _client

    client = _get_redmine_client()
    url = f"{_client.REDMINE_URL}/issues/{issue_id}.json"
    payload = json.dumps(
        {"issue": {"agile_data_attributes": {"story_points": story_points}}}
    )
    client.engine.request(
        "put",
        url,
        headers={"Content-Type": "application/json"},
        data=payload,
    )


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


async def _list_issue_relations_action(
    issue_id: Optional[int] = None,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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


async def _create_issue_relation_action(
    issue_id: Optional[int] = None,
    issue_to_id: Optional[int] = None,
    relation_type: Optional[str] = None,
    delay: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
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


async def _delete_issue_relation_action(
    relation_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if relation_id is None:
        return {"error": "relation_id is required for action 'delete'"}

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
@action_dispatch(
    {
        "list": ActionMode.READ,
        "create": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
    }
)
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
    return {
        "list": _list_issue_relations_action,
        "create": _create_issue_relation_action,
        "delete": _delete_issue_relation_action,
    }


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


async def _add_issue_watcher_action(
    issue_id: Optional[int] = None,
    user_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}
    if not _is_positive_int(user_id):
        return {"error": "user_id must be a positive integer."}

    try:
        issue = _get_redmine_client().issue.get(issue_id)
        issue.watcher.add(user_id)
        return {"success": True, "issue_id": issue_id, "user_id": user_id}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"adding watcher {user_id} on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


async def _remove_issue_watcher_action(
    issue_id: Optional[int] = None,
    user_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}
    if not _is_positive_int(user_id):
        return {"error": "user_id must be a positive integer."}

    try:
        issue = _get_redmine_client().issue.get(issue_id)
        issue.watcher.remove(user_id)
        return {"success": True, "issue_id": issue_id, "user_id": user_id}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"removing watcher {user_id} on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
@action_dispatch(
    {
        "add": ActionMode.WRITE,
        "remove": ActionMode.WRITE,
    }
)
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
    return {
        "add": _add_issue_watcher_action,
        "remove": _remove_issue_watcher_action,
    }


async def _edit_issue_note_action(
    journal_id: Optional[int] = None,
    notes: Optional[str] = None,
    private_notes: Optional[bool] = None,
    **_: Any,
) -> Dict[str, Any]:
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


async def _set_private_issue_note_action(
    journal_id: Optional[int] = None,
    is_private: Optional[bool] = None,
    **_: Any,
) -> Dict[str, Any]:
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
@action_dispatch(
    {
        "edit": ActionMode.WRITE,
        "set_private": ActionMode.WRITE,
    }
)
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
    return {
        "edit": _edit_issue_note_action,
        "set_private": _set_private_issue_note_action,
    }


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


async def _list_issue_categories_action(
    project_id: Optional[Union[str, int]] = None,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    if project_id is None:
        return {"error": "project_id is required for action 'list'"}
    try:
        categories = _get_redmine_client().issue_category.filter(project_id=project_id)
        return [_issue_category_to_dict(c) for c in _iter_capped(categories)]
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing issue categories for project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


async def _create_issue_category_action(
    project_id: Optional[Union[str, int]] = None,
    name: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if project_id is None:
        return {"error": "project_id is required for action 'create'"}
    if not name or not name.strip():
        return {"error": "Category 'name' is required."}

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


async def _update_issue_category_action(
    category_id: Optional[int] = None,
    name: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
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


async def _delete_issue_category_action(
    category_id: Optional[int] = None,
    reassign_to_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if category_id is None:
        return {"error": "category_id is required for action 'delete'"}

    try:
        params: Dict[str, Any] = {}
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
@action_dispatch(
    {
        "list": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
    }
)
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
    return {
        "list": _list_issue_categories_action,
        "create": _create_issue_category_action,
        "update": _update_issue_category_action,
        "delete": _delete_issue_category_action,
    }
