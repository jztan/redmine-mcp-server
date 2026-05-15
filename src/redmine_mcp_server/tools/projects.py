"""Project management tools: list/manage projects, versions, memberships,
roles, modules, status summaries.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Union

from redminelib.exceptions import ResourceNotFoundError

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client
from .._custom_fields import _extract_possible_values
from .._decorators import ActionMode, action_dispatch
from .._errors import _handle_redmine_error
from .._serialization import (
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int
from ..server import mcp


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
                        "name": role.get("name", ""),
                    }
                )
            else:
                result["roles"].append(
                    {
                        "id": getattr(role, "id", None),
                        "name": getattr(role, "name", ""),
                    }
                )
    except TypeError:
        pass  # roles not iterable

    return result


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

    **``is_required`` caveat (#119):** Redmine's
    ``GET /custom_fields.json`` -- the underlying API -- only exposes the
    flag set on the custom field *definition*. Required-ness can also be
    imposed by **workflow rules**, **role-based field permissions**, or
    **tracker-bound required-field settings**, none of which are
    reflected in this field. A custom field with
    ``is_required: false`` here can still cause
    ``create_redmine_issue`` / ``update_redmine_issue`` to reject with
    ``"<field name> cannot be blank"``.

    No general-purpose API exists for the "effective" required state.
    Recovery when the create/update call rejects:

    1. **Name-keyed shortcut (preferred):** pass the rejected field by
       name directly, e.g.
       ``fields={"Department": "Engineering"}``, on either
       ``create_redmine_issue`` or ``update_redmine_issue``. Both tools
       resolve the name to a ``custom_fields`` id; ambiguous names
       raise.
    2. **Explicit id form:** pass
       ``extra_fields={"custom_fields": [{"id": N, "value": "..."}]}``
       using the numeric ID from this tool. Works on either path; use
       when the name lookup is ambiguous or the value type is awkward
       (multi-value fields, complex serializations).
    3. **Autofill:** set
       ``REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true`` to have the
       server retry once with values from each field's ``default_value``
       or the ``REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS`` map.

    ``create_redmine_issue`` and ``update_redmine_issue`` augment their
    validation error envelope with ``missing_required_fields`` and a
    matching ``hint`` when this pattern fires, so a caller hitting the
    error gets recovery context inline.
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


_VALID_VERSION_STATUSES = {"open", "locked", "closed"}


async def _create_redmine_version_action(
    project_id: Optional[Union[str, int]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    due_date: Optional[str] = None,
    sharing: Optional[str] = None,
    wiki_page_title: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if status is not None and status not in _VALID_VERSION_STATUSES:
        return {"error": f"Invalid status '{status}'. Allowed: open, locked, closed"}
    if project_id is None:
        return {"error": "project_id is required for action 'create'"}
    if name is None:
        return {"error": "name is required for action 'create'"}

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


async def _update_redmine_version_action(
    version_id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    due_date: Optional[str] = None,
    sharing: Optional[str] = None,
    wiki_page_title: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if status is not None and status not in _VALID_VERSION_STATUSES:
        return {"error": f"Invalid status '{status}'. Allowed: open, locked, closed"}
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


async def _delete_redmine_version_action(
    version_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if version_id is None:
        return {"error": "version_id is required for action 'delete'"}

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
@action_dispatch(
    {
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
    }
)
async def manage_redmine_version(
    action: Literal["create", "update", "delete"],
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
    return {
        "create": _create_redmine_version_action,
        "update": _update_redmine_version_action,
        "delete": _delete_redmine_version_action,
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


async def _add_project_member_action(
    project_id: Optional[Union[str, int]] = None,
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    role_ids: Optional[List[int]] = None,
    **_: Any,
) -> Dict[str, Any]:
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
    if not isinstance(role_ids, list) or not all(_is_positive_int(r) for r in role_ids):
        return {
            "error": (
                "role_ids must be a list of positive integers. "
                "Use `list_redmine_roles` to discover valid role IDs."
            )
        }

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


async def _update_project_member_action(
    membership_id: Optional[int] = None,
    role_ids: Optional[List[int]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if membership_id is None:
        return {"error": "membership_id is required for action 'update'"}
    if not role_ids:
        return {
            "error": (
                "At least one role_id must be provided. "
                "Use `list_redmine_roles` to discover valid role IDs."
            )
        }
    if not isinstance(role_ids, list) or not all(_is_positive_int(r) for r in role_ids):
        return {
            "error": (
                "role_ids must be a list of positive integers. "
                "Use `list_redmine_roles` to discover valid role IDs."
            )
        }

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


async def _remove_project_member_action(
    membership_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if membership_id is None:
        return {"error": "membership_id is required for action 'remove'"}

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


@mcp.tool()
@action_dispatch(
    {
        "add": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "remove": ActionMode.WRITE,
    }
)
async def manage_project_member(
    action: Literal["add", "update", "remove"],
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
    return {
        "add": _add_project_member_action,
        "update": _update_project_member_action,
        "remove": _remove_project_member_action,
    }
