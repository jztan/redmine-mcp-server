"""Discovery / enumeration tools.

Read-only helpers that let LLM clients discover valid IDs (trackers,
statuses, priorities, users, queries) before calling create/update tools
that require those IDs.
"""

from typing import Any, Dict, List, Optional, Union

from .._client import _get_redmine_client
from .._errors import _handle_redmine_error
from .._serialization import _iter_capped, _safe_isoformat
from ..server import mcp


@mcp.tool()
async def list_redmine_trackers() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all trackers (issue types) defined in the Redmine instance.

    Trackers classify issues (e.g., Bug, Feature, Support). Use this tool
    to discover valid ``tracker_id`` values before calling
    ``create_redmine_issue`` or ``update_redmine_issue``.

    Returns:
        A list of tracker dictionaries with ``id``, ``name``, and
        ``description``. On failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_trackers()
        [
            {"id": 1, "name": "Bug", "description": ""},
            {"id": 2, "name": "Feature", "description": ""},
            {"id": 3, "name": "Support", "description": ""}
        ]
    """
    try:
        trackers = _get_redmine_client().tracker.all()
        return [
            {
                "id": getattr(t, "id", None),
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", ""),
            }
            for t in trackers
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing trackers")


@mcp.tool()
async def list_redmine_issue_statuses() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all issue statuses defined in the Redmine instance.

    Use this tool to discover valid ``status_id`` values before calling
    ``update_redmine_issue``. You can also pass a status name via the
    ``status_name`` field in ``update_redmine_issue``, which internally
    resolves the ID.

    Returns:
        A list of status dictionaries with ``id``, ``name``, and
        ``is_closed`` (whether this status counts as "closed"). On
        failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_issue_statuses()
        [
            {"id": 1, "name": "New", "is_closed": False},
            {"id": 2, "name": "In Progress", "is_closed": False},
            {"id": 5, "name": "Closed", "is_closed": True}
        ]
    """
    try:
        statuses = _get_redmine_client().issue_status.all()
        return [
            {
                "id": getattr(s, "id", None),
                "name": getattr(s, "name", ""),
                "is_closed": bool(getattr(s, "is_closed", False)),
            }
            for s in statuses
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing issue statuses")


@mcp.tool()
async def list_redmine_issue_priorities() -> (
    Union[List[Dict[str, Any]], Dict[str, Any]]
):
    """List all issue priority levels defined in the Redmine instance.

    Use this tool to discover valid ``priority_id`` values before calling
    ``create_redmine_issue`` or ``update_redmine_issue``.

    Returns:
        A list of priority dictionaries with ``id``, ``name``,
        ``active``, and ``is_default``. On failure, a dict with an
        ``"error"`` key.

    Example:
        >>> await list_redmine_issue_priorities()
        [
            {"id": 1, "name": "Low", "active": True, "is_default": False},
            {"id": 2, "name": "Normal", "active": True, "is_default": True},
            {"id": 3, "name": "High", "active": True, "is_default": False}
        ]
    """
    try:
        priorities = _get_redmine_client().enumeration.filter(
            resource="issue_priorities"
        )
        return [
            {
                "id": getattr(p, "id", None),
                "name": getattr(p, "name", ""),
                "active": getattr(p, "active", None),
                "is_default": getattr(p, "is_default", None),
            }
            for p in priorities
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing issue priorities")


@mcp.tool()
async def list_redmine_users(
    name: Optional[str] = None,
    group_id: Optional[int] = None,
    limit: int = 25,
    offset: int = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List Redmine users with optional filtering.

    Admin permission is required to list all users. Non-admin users may
    receive a 403. Use this tool to discover valid user IDs (e.g., for
    assignment, watchers, or time-entry authoring).

    Args:
        name: Optional case-insensitive substring to filter by (matches
            against login, firstname, lastname, and email).
        group_id: Optional group ID to filter users who belong to a
            specific group.
        limit: Maximum users to return (default 25, max 100).
        offset: Pagination offset. Default 0.

    Returns:
        A list of user dictionaries with ``id``, ``login``, ``firstname``,
        ``lastname``, ``mail`` (if visible), and ``created_on``. On
        failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_users(name="alice")
        [{"id": 5, "login": "alice", "firstname": "Alice", ...}]
    """
    try:
        params: Dict[str, Any] = {"limit": max(1, min(limit, 100)), "offset": offset}
        if name:
            params["name"] = name
        if group_id is not None:
            params["group_id"] = group_id

        users = _get_redmine_client().user.filter(**params)
        return [
            {
                "id": getattr(u, "id", None),
                "login": getattr(u, "login", ""),
                "firstname": getattr(u, "firstname", ""),
                "lastname": getattr(u, "lastname", ""),
                "mail": getattr(u, "mail", ""),
                "created_on": _safe_isoformat(getattr(u, "created_on", None)),
            }
            for u in users
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing users")


@mcp.tool()
async def get_current_user() -> Dict[str, Any]:
    """Retrieve the currently authenticated user's profile.

    Resolves to ``GET /my/account.json`` under the hood. Works for any
    authenticated user (not admin-only). Useful when an LLM needs to
    identify "me" — for example, when a user says "log 2h on this issue
    for me", the LLM can call this tool to get the current user's ID.

    Returns:
        A dictionary with ``id``, ``login``, ``firstname``, ``lastname``,
        ``mail``, ``admin`` (bool), ``created_on``, and ``last_login_on``.
        On failure, a dict with an ``"error"`` key.

    Example:
        >>> await get_current_user()
        {"id": 5, "login": "alice", "firstname": "Alice", ..., "admin": False}
    """
    try:
        user = _get_redmine_client().user.get("current")
        return {
            "id": getattr(user, "id", None),
            "login": getattr(user, "login", ""),
            "firstname": getattr(user, "firstname", ""),
            "lastname": getattr(user, "lastname", ""),
            "mail": getattr(user, "mail", ""),
            "admin": bool(getattr(user, "admin", False)),
            "created_on": _safe_isoformat(getattr(user, "created_on", None)),
            "last_login_on": _safe_isoformat(getattr(user, "last_login_on", None)),
        }
    except Exception as e:
        return _handle_redmine_error(e, "fetching current user")


@mcp.tool()
async def list_redmine_queries() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all saved custom queries visible to the current user.

    Custom queries are saved issue filters (defined via the Redmine web
    UI). Once discovered, the ``id`` can be passed to
    ``list_redmine_issues`` via a ``query_id`` filter to run the query.

    Note: This tool only READS queries. Redmine's REST API does not
    support creating, updating, or deleting saved queries.

    Returns:
        A list of query dictionaries with ``id``, ``name``,
        ``is_public``, and ``project_id`` (may be ``None`` for
        cross-project queries). On failure, a dict with an ``"error"``
        key.

    Example:
        >>> await list_redmine_queries()
        [
            {"id": 1, "name": "Open bugs", "is_public": True, "project_id": 10},
            {"id": 2, "name": "My tasks", "is_public": False, "project_id": None}
        ]
    """
    try:
        queries = _get_redmine_client().query.all()
        return [
            {
                "id": getattr(q, "id", None),
                "name": getattr(q, "name", ""),
                "is_public": bool(getattr(q, "is_public", False)),
                "project_id": getattr(q, "project_id", None),
            }
            for q in _iter_capped(queries)
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing saved queries")
