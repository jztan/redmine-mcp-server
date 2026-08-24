"""Project management tools: list/manage projects, versions, memberships,
roles, modules, status summaries.
"""

from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field
from redminelib.exceptions import ResourceNotFoundError

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client
from .._custom_fields import _extract_possible_values
from .._decorators import ActionMode, action_dispatch
from .._errors import _handle_redmine_error
from .._offload import in_thread, offloaded
from .._serialization import (
    _custom_fields_to_list,
    _named_ref,
    _pagination_info,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import (
    _is_positive_int,
    _reject_non_scalar_filter_values,
    _reject_reserved_query_keys,
    _reject_unregistered_filter_keys,
)
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


# Query parameters `list_redmine_projects` owns. Each is validated by the
# guards below, so accepting it through `filters` too would give a caller a
# second, unchecked route to the same key. `filters` exists for the keys the
# signature does not name -- `cf_<id>` most of all.
#
# `include_custom_fields` is named here even though it is not a query
# parameter at all: it selects the response shape. The allowlist below would
# refuse it anyway, for not being one of Redmine's filters, but it would say
# "the accepted keys are status, id, name, ..." -- true, and no help to a
# caller whose actual mistake was reaching for `filters` instead of the named
# argument. Owning it puts that guard first and answers the question asked.
_PROJECT_OWNED_QUERY_KEYS = frozenset(
    {"limit", "offset", "include_custom_fields", "include_pagination_info"}
)


# The filter names Redmine's `ProjectQuery` hands to `add_available_filter`
# (`app/models/project_query.rb:66-89` on 6.1). `cf_<id>` and its chained
# spellings are accepted on top of these by
# `_reject_unregistered_filter_keys`, project custom field filters being
# registered per field and so not enumerable from here.
_PROJECT_QUERY_FILTER_NAMES = frozenset(
    {
        "status",
        "id",
        "name",
        "description",
        "parent_id",
        "is_public",
        "created_on",
        "updated_on",
    }
)


@mcp.tool()
@offloaded
def list_redmine_projects(
    include_custom_fields: bool = False,
    limit: Annotated[Optional[int], Field(ge=1, le=1000)] = None,
    offset: Annotated[int, Field(ge=0)] = 0,
    include_pagination_info: bool = False,
    filters: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Lists accessible projects in Redmine.

    Returns ONLY active projects unless ``filters`` says otherwise. Redmine's
    ``ProjectQuery`` starts out with a ``status = 1`` filter already set, so a
    call that passes no ``status`` answers with active projects alone while
    looking like the whole list. Pass ``filters={"status": "1|5"}`` to get
    closed projects alongside active ones. ``status`` takes only the ``=``
    and ``!`` operators, so ``"*"`` is not a way to ask for every status --
    it would be read as a literal value and match nothing.

    ``filters`` narrows the collection server-side. A filter Redmine cannot
    read is not an error there -- it answers 200 with the collection
    unnarrowed -- so check the result against what was asked for.

    With ``include_custom_fields`` this is the only tool that returns project
    custom field *values*, which are a different set from the issue custom
    fields ``list_project_issue_custom_fields`` covers.

    Args:
        include_custom_fields: Add ``custom_fields`` to each project. Costs no
            extra request; opt-in only to keep the default response small.
        limit: Maximum number of projects to return, up to 1000. Omitted by
            default, which returns every visible project -- what this tool has
            always done, and the cheapest way to do it. A supplied limit is
            paged in full however few projects exist, so ``limit=1000`` on a
            seven-project instance costs ten requests to return seven rows:
            ask for a number you want, not a large one meaning "all".
        offset: Projects to skip before collecting results. With no
            ``limit`` a late offset costs what reading from zero costs --
            paging runs ``total_count`` rows *from* ``offset`` rather than up
            to it -- so pair a large ``offset`` with a ``limit``.
        include_pagination_info: Return
            ``{"projects": [...], "pagination": {...}}`` rather than a bare
            list (default: False), with the keys ``list_redmine_issues``
            returns. ``total`` is Redmine's own count for the filtered
            collection and costs no extra request -- except where a
            deployment suppresses API metadata (``nometa``), which truncates
            the list at one page and reports a ``total`` that agrees with it.
        filters: Redmine query filters, for what this signature does not
            name -- most usefully ``{"cf_42": "value"}`` for a project custom
            field. Accepted keys are ``status``, ``id``, ``name``,
            ``description``, ``parent_id``, ``is_public``, ``created_on`` and
            ``updated_on``, plus ``cf_<id>`` and its chained spellings; any
            other key is refused, with an error naming what it objected to.
            Each value is one scalar -- a string, number, date or datetime,
            never a list, a dict, ``None`` or a ``bool`` (write a yes/no
            filter as ``"1"``). An operator rides inside the value as a
            prefix, as in ``{"created_on": ">=2024-01-01"}`` or
            ``{"name": "~api"}``, and alternatives join with ``|``, as in
            ``{"status": "1|5"}``; an operator the filter's type does not
            accept is read as a literal value rather than erroring. A
            ``cf_<id>`` must be a *project* custom field, visible to the
            caller, with "Used as a filter" on.

    Returns:
        A list of dictionaries, each representing a project -- or, with
        ``include_pagination_info``, a dict of ``projects`` and
        ``pagination``. Each project carries ``id``, ``name``,
        ``identifier``, ``description``, ``homepage``, ``parent``,
        ``status``, ``is_public``, ``inherit_members``, ``created_on`` and
        ``updated_on``, which is what Redmine's project index renders.
        ``status`` is Redmine's integer code -- ``1`` active, ``5`` closed.
        ``parent`` is ``{id, name}``, or ``null``: Redmine renders it only
        when the parent exists *and* is visible to the caller, so ``null``
        means top-level **or** a parent this caller cannot see, and the two
        cannot be told apart. A key the payload did not carry is ``null``
        rather than a substituted default. With ``include_custom_fields``,
        each project also carries ``custom_fields``, a list of
        ``{id, name, value}`` entries -- empty if the project has none. On
        failure, a dict with an ``error`` key.
    """
    if limit is not None and not _is_positive_int(limit):
        return {"error": "limit must be a positive integer."}
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {"error": "offset must be a non-negative integer."}

    params: Dict[str, Any] = {}
    # No `limit` key unless the caller asked for one: python-redmine reads a
    # missing limit as the collection's `total_count` and pages to the end,
    # which is what this tool has always returned, so defaulting to a number
    # here would silently truncate existing callers. That is also why
    # `_REDMINE_API_PAGE_CAP` is not applied the way the single-request list
    # tools apply it -- `project.all()` goes through python-redmine's
    # `bulk_request`, which pages past 100 itself, so clamping would truncate a
    # larger `limit` instead of honouring it.
    if limit is not None:
        params["limit"] = limit
    if offset:
        params["offset"] = offset

    if filters is not None:
        if not isinstance(filters, dict):
            return {"error": "filters must be a dict of Redmine query parameters."}
        reserved_error = _reject_reserved_query_keys(filters)
        if reserved_error:
            return {"error": reserved_error}
        owned = sorted(_PROJECT_OWNED_QUERY_KEYS.intersection(filters))
        if owned:
            return {
                "error": (
                    f"filters may not contain {', '.join(owned)}: pass it as "
                    "the named parameter instead, so it is validated."
                )
            }
        # An allowlist, not a longer denylist. Every key here is forwarded
        # into a request python-redmine decodes and Redmine parses, and a key
        # that is not one of Redmine's filters can still carry meaning to
        # another layer of that request rather than being ignored the way an
        # unregistered filter is.
        unregistered_error = _reject_unregistered_filter_keys(
            filters, _PROJECT_QUERY_FILTER_NAMES
        )
        if unregistered_error:
            return {"error": unregistered_error}
        value_error = _reject_non_scalar_filter_values(filters)
        if value_error:
            return {"error": value_error}
        params.update(filters)

    try:
        projects = _get_redmine_client().project.all(**params)
        result: List[Dict[str, Any]] = []
        for project in projects:
            entry = {
                "id": project.id,
                "name": project.name,
                "identifier": project.identifier,
                "description": getattr(project, "description", ""),
                # The rest of what `app/views/projects/index.api.rsb` renders
                # and this serializer used to drop. `None` marks a key the
                # payload did not carry, so an absent value is never returned
                # as a real one -- `is_public` and `inherit_members` above all,
                # where a fabricated `False` reads as a deliberate setting.
                "homepage": getattr(project, "homepage", None),
                "parent": _named_ref(getattr(project, "parent", None)),
                "status": getattr(project, "status", None),
                "is_public": getattr(project, "is_public", None),
                "inherit_members": getattr(project, "inherit_members", None),
                "created_on": _safe_isoformat(getattr(project, "created_on", None)),
                "updated_on": _safe_isoformat(getattr(project, "updated_on", None)),
            }
            if include_custom_fields:
                entry["custom_fields"] = _custom_fields_to_list(project)
            result.append(entry)
        if not include_pagination_info:
            return result
        # Read after the loop, never before: `ResourceSet.total_count` raises
        # `ResultSetTotalCountError` until the set has been evaluated, and
        # iterating it above is what evaluates it. So this costs no request.
        #
        # The total is honest here, unlike the contacts endpoint's. Redmine
        # builds `@project_count` from `@query.result_count` and the rows from
        # `project_scope(:offset, :limit)` -- the same query -- so it measures
        # exactly the collection being paged, filters included. Passing it is
        # right; suppressing it the way a searched contact list has to would
        # throw away a number that does describe this page.
        #
        # One deployment shape defeats that, and it cannot be detected from
        # here. `api_meta` returns nil when `nometa` is in the request or
        # `X-Redmine-Nometa` is set, so the response carries no `total_count`,
        # `limit` or `offset` at all; `bulk_request` then takes its fallback
        # branch, sets `total_count = len(first page)` and stops paging. The
        # list is truncated at one chunk -- which it already was before this
        # tool reported anything -- but `total` now agrees with the truncated
        # count, so the envelope reads as a complete collection. A caller
        # cannot tell that from a genuinely 100-project instance and neither
        # can this code: same row count, same total, same single request. It is
        # documented rather than guarded because a guess would be worse than
        # the caveat. `nometa` cannot arrive through `filters` -- it is not a
        # registered filter name, so the allowlist refuses it.
        #
        # With no `limit` the window is the whole remainder of the collection,
        # so the page delivered *is* its own limit: reporting `len(result)`
        # describes what came back and makes `has_next` come out false, which
        # is correct -- there is nothing left to ask for. Reporting the
        # requested `None` instead would leave the arithmetic undefined.
        pagination = _pagination_info(
            limit=limit if limit is not None else len(result),
            offset=offset,
            count=len(result),
            total=projects.total_count,
        )
        if limit is None and offset:
            # No limit means "everything from `offset`", so there is no page
            # size to step back by. `_pagination_info` derives
            # `previous_offset` from the limit, which here is only the row
            # count -- and for an offset past the end that count is 0, which
            # would point the caller at the offset they are already on. The
            # one meaningful predecessor of an unbounded read is the start.
            pagination["previous_offset"] = 0
        return {"projects": result, "pagination": pagination}
    except Exception as e:
        return _handle_redmine_error(e, "listing projects")


@mcp.tool()
async def list_project_issue_custom_fields(
    project_id: Union[str, int], tracker_id: Optional[Union[str, int]] = None
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List issue custom fields configured for a project.

    Args:
        project_id: Project identifier (ID number or string identifier).
        tracker_id: Optional tracker ID to filter custom fields by applicability.

    Returns:
        A list of custom field metadata dictionaries. On failure, a
        dict with an ``"error"`` key is returned (callers should check
        ``isinstance(result, dict)`` to distinguish failure from an
        empty list).

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
            return {
                "error": (
                    f"Invalid tracker_id '{tracker_id}'. "
                    "Expected an integer tracker ID."
                )
            }

    await _ensure_cleanup_started()

    def _run() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        try:
            project = _get_redmine_client().project.get(
                project_id, include="issue_custom_fields"
            )
            custom_fields = getattr(project, "issue_custom_fields", None) or []

            result: List[Dict[str, Any]] = []
            for custom_field in custom_fields:
                if not _custom_field_applies_to_tracker(
                    custom_field, parsed_tracker_id
                ):
                    continue
                result.append(_custom_field_to_dict(custom_field))

            return result
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing issue custom fields for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    return await in_thread(_run)


@mcp.tool()
async def list_redmine_versions(
    project_id: Union[str, int],
    status_filter: Optional[str] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List versions (roadmap milestones) for a Redmine project.

    Args:
        project_id: The project ID (numeric) or identifier (string).
        status_filter: Optional filter by version status.
            Allowed values: open, locked, closed.
            When None, all versions are returned.

    Returns:
        A list of version dictionaries. On failure, a dict with an
        ``"error"`` key is returned (callers should check
        ``isinstance(result, dict)`` to distinguish failure from an
        empty list).
    """

    # Validate status_filter before making API call
    valid_statuses = {"open", "locked", "closed"}
    if status_filter is not None:
        status_filter = str(status_filter).lower()
        if status_filter not in valid_statuses:
            return {
                "error": (
                    f"Invalid status_filter '{status_filter}'. "
                    f"Allowed values: open, locked, closed"
                )
            }

    await _ensure_cleanup_started()

    def _run() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
            return _handle_redmine_error(
                e,
                f"listing versions for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    return await in_thread(_run)


_VALID_VERSION_STATUSES = {"open", "locked", "closed"}


@offloaded
def _create_redmine_version_action(
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


@offloaded
def _update_redmine_version_action(
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


@offloaded
def _delete_redmine_version_action(
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
@offloaded
def summarize_project_status(project_id: int, days: int = 30) -> Dict[str, Any]:
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
@offloaded
def list_project_members(
    project_id: Union[str, int],
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List members of a Redmine project.

    Returns all users and groups that are members of the specified project,
    along with their assigned roles.

    Args:
        project_id: Project identifier (ID number or string identifier)

    Returns:
        A list of membership dictionaries containing user/group info and roles.
        On failure, a dict with an ``"error"`` key is returned (callers
        should check ``isinstance(result, dict)`` to distinguish failure
        from an empty list).

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
        return _handle_redmine_error(
            e,
            f"listing members for project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


@mcp.tool()
@offloaded
def list_redmine_roles() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
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
@offloaded
def get_project_modules(
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


@offloaded
def _add_project_member_action(
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


@offloaded
def _update_project_member_action(
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


@offloaded
def _remove_project_member_action(
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


@mcp.tool()
@offloaded
def list_project_trackers(
    project_id: Union[str, int],
) -> List[Dict[str, Any]]:
    """List the trackers (issue types) enabled for a specific Redmine project.

    Unlike ``list_redmine_trackers`` (which returns every tracker defined in
    the instance), this returns only the trackers available on the given
    project. Use it to discover valid ``tracker_id`` values before creating
    an issue in that project.

    Args:
        project_id: Project identifier (numeric id or string identifier).

    Returns:
        A list of tracker dicts with ``id`` and ``name``. On failure, a list
        containing a single dict with an ``"error"`` key.

    Examples:
        >>> await list_project_trackers("my-project")
        [{"id": 1, "name": "Bug"}, {"id": 2, "name": "Feature"}]
    """
    try:
        project = _get_redmine_client().project.get(project_id, include="trackers")
        trackers = getattr(project, "trackers", None) or []
        return [
            {"id": getattr(t, "id", None), "name": getattr(t, "name", "")}
            for t in trackers
        ]
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing trackers for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]
