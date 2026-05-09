"""Time tracking tools: list, manage (create/update), activities, bulk import."""

import asyncio
import json
from typing import Any, Dict, List, Optional, Union

from .._client import _get_redmine_client, logger
from .._decorators import ActionMode, action_dispatch
from .._env import _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error, _scrub_error_message
from .._serialization import (
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _validate_hours
from ..server import mcp

# Maximum entries in a single `import_time_entries` call. Redmine has no
# native bulk endpoint, so each entry is a sequential synchronous HTTP
# call; capping the batch prevents a single tool invocation from pinning
# the event loop for minutes.
_IMPORT_TIME_ENTRIES_MAX_BATCH = 500


def _time_entry_to_dict(time_entry: Any) -> Dict[str, Any]:
    """Convert a time entry to a serializable dict."""
    user = getattr(time_entry, "user", None)
    project = getattr(time_entry, "project", None)
    issue = getattr(time_entry, "issue", None)
    activity = getattr(time_entry, "activity", None)

    # `comments` is user-controlled free-form text. Wrap it in
    # <insecure-content> boundary tags so downstream LLMs treat it as
    # untrusted data rather than instructions.
    return {
        "id": getattr(time_entry, "id", None),
        "hours": getattr(time_entry, "hours", 0),
        "comments": wrap_insecure_content(getattr(time_entry, "comments", "")),
        "spent_on": (
            str(time_entry.spent_on)
            if getattr(time_entry, "spent_on", None) is not None
            else None
        ),
        "user": _named_ref(user),
        "project": _named_ref(project),
        "issue": ({"id": getattr(issue, "id", None)} if issue is not None else None),
        "activity": (_named_ref(activity) if activity is not None else None),
        "created_on": _safe_isoformat(getattr(time_entry, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(time_entry, "updated_on", None)),
    }


@mcp.tool()
async def list_time_entries(
    project_id: Optional[Union[str, int]] = None,
    issue_id: Optional[int] = None,
    user_id: Optional[Union[str, int]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List time entries from Redmine with filtering and pagination.

    Retrieve time entries with optional filtering by project, issue, user,
    and date range. Supports pagination for handling large result sets.

    Args:
        project_id: Filter by project (ID number or string identifier).
        issue_id: Filter by issue ID.
        user_id: Filter by user ID. Use "me" for current user.
        from_date: Start date filter (YYYY-MM-DD format).
        to_date: End date filter (YYYY-MM-DD format).
        limit: Maximum number of entries to return (default: 25, max: 100).
        offset: Number of entries to skip for pagination (default: 0).

    Returns:
        A list of time entry dictionaries. On failure, a list containing
        a single dictionary with an "error" key.

    Examples:
        >>> await list_time_entries(project_id="my-project")
        [{"id": 1, "hours": 2.5, "comments": "Bug fix", ...}, ...]

        >>> await list_time_entries(issue_id=123, from_date="2024-01-01")
        [{"id": 2, "hours": 1.0, "issue": {"id": 123}, ...}, ...]

        >>> await list_time_entries(user_id="me", limit=10)
        [{"id": 3, "hours": 4.0, "user": {"id": 5, "name": "Current User"}, ...}]
    """
    try:
        # Build filter parameters
        filters: Dict[str, Any] = {
            "limit": min(limit, 100),
            "offset": offset,
        }

        if project_id is not None:
            filters["project_id"] = project_id
        if issue_id is not None:
            filters["issue_id"] = issue_id
        if user_id is not None:
            filters["user_id"] = user_id
        if from_date is not None:
            filters["from_date"] = from_date
        if to_date is not None:
            filters["to_date"] = to_date

        time_entries = _get_redmine_client().time_entry.filter(**filters)
        return [_time_entry_to_dict(te) for te in time_entries]

    except Exception as e:
        return [_handle_redmine_error(e, "listing time entries")]


async def _create_time_entry_action(
    hours: Optional[float] = None,
    project_id: Optional[Union[str, int]] = None,
    issue_id: Optional[int] = None,
    user_id: Optional[int] = None,
    activity_id: Optional[int] = None,
    comments: Optional[str] = None,
    spent_on: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if project_id is None and issue_id is None:
        return {"error": "Either project_id or issue_id must be provided."}

    hours_error = _validate_hours(hours)
    if hours_error is not None:
        return {"error": hours_error}

    if user_id is not None and not _is_positive_int(user_id):
        return {"error": "user_id must be a positive integer."}

    try:
        params: Dict[str, Any] = {"hours": hours}
        if project_id is not None:
            params["project_id"] = project_id
        if issue_id is not None:
            params["issue_id"] = issue_id
        if user_id is not None:
            params["user_id"] = user_id
        if activity_id is not None:
            params["activity_id"] = activity_id
        if comments is not None:
            params["comments"] = comments
        if spent_on is not None:
            params["spent_on"] = spent_on
        time_entry = _get_redmine_client().time_entry.create(**params)
        return _time_entry_to_dict(time_entry)
    except Exception as e:
        context = {}
        if issue_id:
            context = {"resource_type": "issue", "resource_id": issue_id}
        elif project_id:
            context = {"resource_type": "project", "resource_id": project_id}
        return _handle_redmine_error(e, "creating time entry", context)


async def _update_time_entry_action(
    time_entry_id: Optional[int] = None,
    hours: Optional[float] = None,
    activity_id: Optional[int] = None,
    comments: Optional[str] = None,
    spent_on: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if time_entry_id is None:
        return {"error": "time_entry_id is required for action 'update'"}

    update_params: Dict[str, Any] = {}
    if hours is not None:
        hours_error = _validate_hours(hours)
        if hours_error is not None:
            return {"error": hours_error}
        update_params["hours"] = hours
    if activity_id is not None:
        update_params["activity_id"] = activity_id
    if comments is not None:
        update_params["comments"] = comments
    if spent_on is not None:
        update_params["spent_on"] = spent_on

    if not update_params:
        return {"error": "No fields provided for update."}

    try:
        client = _get_redmine_client()
        client.time_entry.update(time_entry_id, **update_params)
        updated = client.time_entry.get(time_entry_id)
        return _time_entry_to_dict(updated)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating time entry {time_entry_id}",
            {"resource_type": "time entry", "resource_id": time_entry_id},
        )


@mcp.tool()
@action_dispatch(
    {
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
    }
)
async def manage_time_entry(
    action: str,
    hours: Optional[float] = None,
    project_id: Optional[Union[str, int]] = None,
    issue_id: Optional[int] = None,
    user_id: Optional[int] = None,
    time_entry_id: Optional[int] = None,
    activity_id: Optional[int] = None,
    comments: Optional[str] = None,
    spent_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a Redmine time entry.

    Args:
        action: One of: ``create``, ``update``.
        hours: Hours spent. Required for ``create``; optional for
            ``update`` (must be positive if provided).
        project_id: Project to log against. Required for ``create`` if
            ``issue_id`` is not provided.
        issue_id: Issue to log against. Required for ``create`` if
            ``project_id`` is not provided.
        user_id: Log on behalf of this user (``create`` only). Requires
            ``log_time_for_other_users`` permission.
        time_entry_id: Entry to update. Required for ``update``.
        activity_id: Activity ID (optional for both actions).
        comments: Description. Empty string clears the field on
            ``update``.
        spent_on: Date in ``YYYY-MM-DD`` format (optional).

    Returns:
        Time entry dictionary, or ``{"error": "..."}``.
    """
    return {
        "create": _create_time_entry_action,
        "update": _update_time_entry_action,
    }


@mcp.tool()
async def list_time_entry_activities(
    project_id: Optional[Union[str, int]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List available time entry activities from Redmine.

    Returns activity types that can be used when creating or updating time
    entries (e.g., Development, Design, Testing).

    When called without ``project_id``, returns all global activity types.

    When called with ``project_id``, returns project-specific activities via
    ``GET /projects/:id.json?include=time_entry_activities`` (Redmine 3.4.0+).
    Project-specific IDs differ from global ones — always use project-scoped
    activities when logging time against a specific project to avoid
    ``"Activity is not included in the list"`` errors.

    Args:
        project_id: Optional project identifier (ID number or string
            identifier). When provided, returns project-specific activities
            instead of global ones.

    Returns:
        Without ``project_id``: a list of activity dicts, each with
        ``id``, ``name``, ``active``, ``is_default``.

        With ``project_id``: a dict with ``project_id`` and ``activities``
        (same structure). If the project has no custom activities,
        ``activities`` is empty and a ``note`` field explains the fallback.

        On failure: a list containing a single dict with an ``"error"`` key.

    Examples:
        >>> await list_time_entry_activities()
        [{"id": 4, "name": "Development", "active": True, "is_default": False}, ...]

        >>> await list_time_entry_activities(project_id="my-project")
        {
            "project_id": "my-project",
            "activities": [{"id": 9, "name": "Development", ...}]
        }
    """
    if project_id is not None:
        try:
            project = _get_redmine_client().project.get(
                project_id, include="time_entry_activities"
            )
            activities = getattr(project, "time_entry_activities", None) or []
            result: Dict[str, Any] = {
                "project_id": project_id,
                "activities": [
                    {
                        "id": getattr(a, "id", None),
                        "name": getattr(a, "name", None),
                        "active": getattr(a, "active", None),
                        "is_default": getattr(a, "is_default", None),
                    }
                    for a in activities
                ],
            }
            if not result["activities"]:
                result["note"] = (
                    "No project-specific activities configured. "
                    "Use list_time_entry_activities for global activities."
                )
            return result
        except Exception as e:
            return [
                _handle_redmine_error(
                    e,
                    f"listing time entry activities for project {project_id}",
                    {"resource_type": "project", "resource_id": project_id},
                )
            ]

    try:
        activities = _get_redmine_client().enumeration.filter(
            resource="time_entry_activities"
        )
        return [
            {
                "id": getattr(a, "id", None),
                "name": getattr(a, "name", None),
                "active": getattr(a, "active", None),
                "is_default": getattr(a, "is_default", None),
            }
            for a in activities
        ]

    except Exception as e:
        return [_handle_redmine_error(e, "listing time entry activities")]


@mcp.tool()
async def import_time_entries(
    entries: Union[List[Dict[str, Any]], str],
    stop_on_error: bool = False,
) -> Dict[str, Any]:
    """Bulk import multiple time entries in a single call.

    **Use this tool (NOT ``manage_time_entry(action="create")`` in a loop) whenever the
    user asks to:**
        - import a timesheet / weekly timesheet / monthly report
        - bulk log, batch log, or log multiple entries at once
        - import several entries, or any list of 2+ time entries
        - backfill time across many issues or dates
        - log the same activity for multiple team members at once
        - log a day's work spanning multiple issues

    **Prefer this tool over calling ``manage_time_entry(action="create")``
    N times** -- it reports partial failures via a
    ``succeeded``/``failed`` summary and supports ``stop_on_error`` for
    transactional-style behaviour. Calling
    ``manage_time_entry(action="create")`` in a loop gives no aggregate
    feedback and cannot continue past per-entry errors gracefully.

    Redmine has no native bulk-import endpoint, so this tool creates each
    entry individually via ``POST /time_entries.json`` under the hood.
    Per-entry errors are captured and returned alongside successes so a
    partial import still yields useful feedback.

    Each entry must be a dict (or JSON object) with the standard
    ``manage_time_entry(action="create")`` fields: ``hours`` (required),
    plus at least one of ``project_id``/``issue_id``. Optional fields:
    ``user_id`` (to log on behalf of a teammate), ``activity_id``,
    ``comments``, ``spent_on``.

    Args:
        entries: List of time entry dicts, OR a JSON array string. Capped
            at 500 entries per call — split larger imports into multiple
            invocations.
            Example: ``[{"hours": 1.5, "issue_id": 123, "comments": "..."}]``
        stop_on_error: When ``True``, abort the import on the first error.
            When ``False`` (default), continue past errors and report all
            successes/failures at the end.

    Returns:
        Dictionary with:
            - ``total``: total number of entries attempted
            - ``succeeded``: count of successfully created entries
            - ``failed``: count of failed entries
            - ``created``: list of created time entry dicts
            - ``errors``: list of ``{"index": i, "entry": {...}, "error": "..."}``
              for failed entries

    Example:
        >>> await import_time_entries([
        ...     {"hours": 2.0, "issue_id": 123, "comments": "Bug fix"},
        ...     {"hours": 1.0, "project_id": "web", "activity_id": 9},
        ... ])
        {"total": 2, "succeeded": 2, "failed": 0, "created": [...], "errors": []}
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    # Parse input: accept either a list or a JSON array string.
    if isinstance(entries, str):
        try:
            parsed = json.loads(entries.strip())
        except Exception as e:
            return {
                "error": (
                    "Invalid entries payload. Expected a list of dicts or "
                    "a JSON array string."
                ),
                "details": str(e),
            }
        entries_list = parsed
    else:
        entries_list = entries

    if not isinstance(entries_list, list):
        return {
            "error": (
                "entries must be a list of time entry dicts, not "
                f"{type(entries_list).__name__}."
            )
        }

    if len(entries_list) > _IMPORT_TIME_ENTRIES_MAX_BATCH:
        return {
            "error": (
                f"Too many entries: {len(entries_list)} exceeds the "
                f"{_IMPORT_TIME_ENTRIES_MAX_BATCH}-per-call batch cap. "
                "Split the import into multiple calls."
            )
        }

    if not entries_list:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "created": [],
            "errors": [],
        }

    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    client = _get_redmine_client()

    for index, entry in enumerate(entries_list):
        # Yield to the event loop between synchronous HTTP calls so other
        # MCP requests (e.g., a status check) aren't starved during a
        # large import.
        if index > 0:
            await asyncio.sleep(0)
        if not isinstance(entry, dict):
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": f"Entry at index {index} is not a dict.",
                }
            )
            if stop_on_error:
                break
            continue

        # Per-entry validation
        hours = entry.get("hours")
        hours_error = (
            _validate_hours(hours) if hours is not None else "hours is required."
        )
        if hours_error is not None:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": hours_error,
                }
            )
            if stop_on_error:
                break
            continue

        if entry.get("project_id") is None and entry.get("issue_id") is None:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": "Either project_id or issue_id is required.",
                }
            )
            if stop_on_error:
                break
            continue

        # Build create params — pass through only whitelisted keys
        allowed_keys = {
            "hours",
            "user_id",
            "project_id",
            "issue_id",
            "activity_id",
            "comments",
            "spent_on",
        }
        params = {k: v for k, v in entry.items() if k in allowed_keys and v is not None}

        # Separate the create from the serialization so a serialization
        # bug doesn't flip a successful create into a reported failure
        # (which would tempt callers to retry and create a duplicate).
        try:
            time_entry = client.time_entry.create(**params)
        except Exception as e:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": _scrub_error_message(str(e)),
                }
            )
            if stop_on_error:
                break
            continue

        try:
            created.append(_time_entry_to_dict(time_entry))
        except Exception as ser_err:
            logger.warning(
                "Serialization failed for time_entry at index %s: %s",
                index,
                ser_err,
            )
            # Record a minimal success marker so the caller knows the
            # entry exists, without marking it as failed.
            created.append(
                {
                    "id": getattr(time_entry, "id", None),
                    "warning": "serialization failed; entry was created",
                }
            )

    return {
        "total": len(entries_list),
        "succeeded": len(created),
        "failed": len(errors),
        "created": created,
        "errors": errors,
    }
