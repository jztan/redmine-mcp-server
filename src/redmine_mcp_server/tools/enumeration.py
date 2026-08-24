"""Discovery / enumeration tools.

Read-only helpers that let LLM clients discover valid IDs (trackers,
statuses, priorities, users, queries) before calling create/update tools
that require those IDs.
"""

from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from .._client import _get_redmine_client
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._serialization import (
    _included_list,
    _iter_capped,
    _named_ref,
    _safe_isoformat,
)
from ..server import mcp


@mcp.tool()
@offloaded
def list_redmine_trackers() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
@offloaded
def list_redmine_issue_statuses() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
@offloaded
def list_redmine_issue_priorities() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
@offloaded
def list_redmine_users(
    name: Optional[str] = None,
    group_id: Optional[int] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    offset: Annotated[int, Field(ge=0)] = 0,
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


def _membership_roles_to_list(raw_roles: Any) -> List[Dict[str, Any]]:
    """Serialize the ``roles`` array of one user-show membership entry.

    Redmine renders each role as ``{id, name}`` and merges ``inherited =>
    true`` onto it when the role arrives through a group membership
    (``app/views/users/show.api.rsb``). It omits the key otherwise, so the
    key is mirrored only when present -- a hard-coded ``inherited: false``
    would be a claim Redmine never made, and it is the one field that tells
    "I hold Manager here" apart from "a group I am in does".
    """
    if not isinstance(raw_roles, list):
        return []

    roles: List[Dict[str, Any]] = []
    for role in raw_roles:
        if not isinstance(role, dict):
            continue
        entry: Dict[str, Any] = {
            "id": role.get("id"),
            "name": role.get("name", ""),
        }
        if "inherited" in role:
            entry["inherited"] = role["inherited"]
        roles.append(entry)
    return roles


def _current_user_memberships(user: Any) -> List[Dict[str, Any]]:
    """Serialize the caller's ``include=memberships`` payload.

    Read through ``_included_list``, never ``user.memberships``: for a name
    in ``User._includes`` python-redmine's ``Resource.__getattr__`` pops the
    key from the decoded payload and, finding it absent, calls
    ``refresh(itself=False, include=attr)`` -- a second HTTP request for data
    the first response already carried
    (``redminelib/resources/base.py``). Passing the include on the original
    ``get`` and reading the payload keeps it at one request.

    Deliberately not ``tools.projects._membership_to_dict``, because the two
    payloads are different shapes:

    - That helper reads resource attributes with ``getattr``; these entries
      are decoded payload dicts, on which ``getattr`` would silently yield
      ``{"id": None, "name": ""}``.
    - It emits ``user`` and ``group``. Redmine's user-show renderer emits
      neither -- the user is the caller, implicitly -- so both would come
      back ``None``, indistinguishable from a membership naming no principal.
    - It flattens roles to ``{id, name}`` and so would drop ``inherited``.

    Widening the shared helper to cover all three would change
    ``list_project_members`` output, which has its own callers and belongs in
    its own change.
    """
    memberships: List[Dict[str, Any]] = []
    for membership in _included_list(user, "memberships"):
        if not isinstance(membership, dict):
            continue
        memberships.append(
            {
                "id": membership.get("id"),
                "project": _named_ref(membership.get("project")),
                "roles": _membership_roles_to_list(membership.get("roles")),
            }
        )
    return memberships


@mcp.tool()
@offloaded
def get_current_user(include_memberships: bool = False) -> Dict[str, Any]:
    """Retrieve the currently authenticated user's profile.

    Resolves to ``GET /users/current.json`` under the hood. Works for any
    authenticated user (not admin-only): Redmine's ``UsersController``
    exempts ``show`` from ``require_admin`` and resolves the ``current``
    id behind a bare ``require_login``. Useful when an LLM needs to
    identify "me" — for example, when a user says "log 2h on this issue
    for me", the LLM can call this tool to get the current user's ID.

    With ``include_memberships`` it also answers "which projects am I a
    member of, and with which roles" in that same request. The only other
    way to get that is ``list_project_members`` once per project.

    Args:
        include_memberships: Add ``memberships`` to the response. Costs no
            extra request -- the include rides the same call -- so this is
            opt-in only to keep the default response small.

    Returns:
        A dictionary with ``id``, ``login``, ``firstname``, ``lastname``,
        ``mail``, ``admin`` (bool), ``created_on``, and ``last_login_on``.
        With ``include_memberships``, also ``memberships``: a list of
        ``{id, project: {id, name}, roles: [{id, name}]}`` entries, empty
        when the caller holds none. A role inherited from a group
        membership carries ``inherited: true``; the key is absent
        otherwise, mirroring Redmine. Redmine limits the list to projects
        visible to the caller. On failure, a dict with an ``"error"`` key.

    Example:
        >>> await get_current_user(include_memberships=True)
        {
            "id": 5, "login": "alice", "admin": False,
            "memberships": [
                {
                    "id": 12,
                    "project": {"id": 1, "name": "Website"},
                    "roles": [
                        {"id": 3, "name": "Developer"},
                        {"id": 4, "name": "Manager", "inherited": True}
                    ]
                }
            ]
        }
    """
    try:
        # Only ``memberships`` is exposed, not a free-text ``include``
        # passthrough. python-redmine's ``User._includes`` also accepts
        # ``groups``, but Redmine gates that block on ``User.current.admin?``
        # (``app/views/users/show.api.rsb``), so a non-admin asking for
        # groups gets a 200 with the key simply missing -- byte-identical to
        # "belongs to no groups". The memberships block carries no such
        # check; Redmine only filters it by project visibility.
        if include_memberships:
            user = _get_redmine_client().user.get("current", include="memberships")
        else:
            user = _get_redmine_client().user.get("current")

        result: Dict[str, Any] = {
            "id": getattr(user, "id", None),
            "login": getattr(user, "login", ""),
            "firstname": getattr(user, "firstname", ""),
            "lastname": getattr(user, "lastname", ""),
            "mail": getattr(user, "mail", ""),
            "admin": bool(getattr(user, "admin", False)),
            "created_on": _safe_isoformat(getattr(user, "created_on", None)),
            "last_login_on": _safe_isoformat(getattr(user, "last_login_on", None)),
        }
        if include_memberships:
            result["memberships"] = _current_user_memberships(user)
        return result
    except Exception as e:
        return _handle_redmine_error(e, "fetching current user")


@mcp.tool()
@offloaded
def list_redmine_queries() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
