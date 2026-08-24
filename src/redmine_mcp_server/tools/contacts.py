"""RedmineUP CRM (Contacts) plugin tool (REDMINE_CRM_ENABLED gated)."""

import json
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _crm_edition, _is_crm_enabled
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _custom_fields_to_list,
    _named_ref,
    _normalize_tag_list,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import (
    _is_positive_int,
    _is_valid_project_id,
    _reject_reserved_query_keys,
)
from ..server import mcp

_CRM_DISABLED_ERROR = {
    "error": (
        "Contacts (CRM) support is disabled. "
        "Set REDMINE_CRM_ENABLED=true to enable it. "
        "Requires the RedmineUP CRM plugin."
    )
}

# Query parameters this signature owns. Each is validated above, so accepting
# it through `filters` too would give a caller a second, unchecked route to the
# same key -- and a `limit` raised that way is only bytes Redmine renders and
# the local slice discards. `filters` exists for the keys this signature does
# not name, `cf_<id>` above all.
# Only what `_list_contacts_action` validates itself. Everything else a given
# CRM build registers as a filter is reachable through `filters`, which cannot
# promise the build registers it -- see the `filters` note in `manage_contact`.
_CONTACT_OWNED_QUERY_KEYS = frozenset(
    {
        "limit",
        "offset",
        "project_id",
        "search",
        "tags",
        "assigned_to_id",
        "author_id",
        "first_name",
        "last_name",
        "middle_name",
        "company",
        "job_title",
        "email",
        "phone",
    }
)

_CONTACT_WRITABLE_FIELDS = {
    "first_name",
    "last_name",
    "middle_name",
    "company",
    "job_title",
    "phone",
    "email",
    "website",
    "skype_name",
    "birthday",
    "background",
    "address_attributes",
    "tag_list",
    "is_company",
    "assigned_to_id",
    "custom_fields",
    "visibility",
    "project_id",
}


def _contact_channel_to_list(raw: Any, inner_key: str) -> List[str]:
    """Flatten a CRM contact channel to a list of strings.

    The CRM API renders a contact's email and phone entries as arrays of
    objects -- ``emails`` as ``[{"address": ...}]`` and ``phones`` as
    ``[{"number": ...}]`` -- so reading the scalar ``email`` and ``phone`` keys
    returned ``None`` for every contact however many addresses it had. A bare
    string is accepted so a payload using the scalar spelling still reads.

    Only the channel's own key is read. Falling back to the other channel's key
    would report a street address as a phone number, and returning nothing is
    the better failure: a caller can see an empty list, but cannot see that a
    populated one holds the wrong kind of value.
    """
    values: List[str] = []
    for entry in raw if isinstance(raw, (list, tuple)) else [raw]:
        if isinstance(entry, str):
            value: Any = entry
        elif isinstance(entry, dict):
            value = entry.get(inner_key)
        else:
            value = None
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _contact_tag_names(raw: Any) -> List[str]:
    """Tag names from either spelling the payload might use.

    ``tag_list`` holds names, as a list or a comma-separated string. The
    ``tags`` fallback can hold ``[{"id", "name"}]``, the shape the tags plugin
    renders elsewhere in this server, so dict entries are reduced to their name
    before the shared coercion runs -- otherwise ``str()`` would stringify the
    whole dict into a tag name.
    """
    if isinstance(raw, (list, tuple)):
        raw = [entry.get("name") if isinstance(entry, dict) else entry for entry in raw]
    return _normalize_tag_list(raw)


def _contact_to_dict(contact: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP CRM API response into a stable dict.

    User-controlled fields are wrapped in ``<insecure-content>`` boundary
    tags. Contact PII (email, phone, address) is returned as-is to the caller.
    This module makes no logger.* calls, but note that a ``list`` filtered on
    an email, phone or name puts that value in the request query string, which
    a transport-level exception can carry into ``_handle_redmine_error``;
    ``_scrub_error_message`` redacts credentials, not filter values.

    Where the CRM API's own key differs from the one this serializer first
    assumed, both are read: emails and phones arrive as the ``emails`` and
    ``phones`` arrays, tags as ``tag_list``, and the address sub-document uses
    the plugin's own field names rather than a fixed set. Reading only the
    original spelling meant those fields came back empty no matter what the
    contact held. ``author``, ``projects`` and ``custom_fields`` are rendered by
    the API and were dropped entirely.

    ``projects`` is emitted only when the payload carries it -- the CRM API
    renders it on a single contact but not on a collection -- so an absent key
    is not reported as an empty list.
    """
    if not isinstance(contact, dict):
        return {}
    raw_assigned = contact.get("assigned_to")
    assigned = raw_assigned if isinstance(raw_assigned, dict) else {}
    raw_address = contact.get("address")
    address = raw_address if isinstance(raw_address, dict) else {}
    raw_author = contact.get("author")
    author = raw_author if isinstance(raw_author, dict) else {}
    # ``or`` rather than ``get(key, default)``: the default applies only when
    # the key is absent, so a payload sending the array key explicitly null --
    # or empty, as a create echo may -- would never reach the scalar spelling.
    emails = _contact_channel_to_list(
        contact.get("emails") or contact.get("email"), "address"
    )
    phones = _contact_channel_to_list(
        contact.get("phones") or contact.get("phone"), "number"
    )
    raw_tags = contact.get("tag_list") or contact.get("tags")

    # ``custom_fields`` is unconditional here, unlike ``_issue_to_dict`` where
    # it sits behind ``include_custom_fields``: ``manage_contact`` has no
    # output-field selector, so there is no way for a caller to ask for it.
    result: Dict[str, Any] = {
        "id": contact.get("id"),
        "first_name": contact.get("first_name", ""),
        "last_name": contact.get("last_name", ""),
        "middle_name": contact.get("middle_name", ""),
        "company": contact.get("company", ""),
        "job_title": contact.get("job_title", ""),
        "phone": phones[0] if phones else None,
        "phones": phones,
        "email": emails[0] if emails else None,
        "emails": emails,
        "website": contact.get("website"),
        "skype_name": contact.get("skype_name"),
        "birthday": contact.get("birthday"),
        "background": wrap_insecure_content(contact.get("background", "")),
        # Passed through rather than rebuilt from a fixed key set: the plugin
        # names these itself, and a hardcoded list both dropped what it did not
        # know (`full_address`) and reported nulls for keys it never sends.
        "address": dict(address) if address else None,
        "is_company": contact.get("is_company", False),
        "tags": _contact_tag_names(raw_tags),
        "visibility": contact.get("visibility"),
        "assigned_to": _named_ref(assigned) if assigned else None,
        "author": _named_ref(author) if author else None,
        "custom_fields": _custom_fields_to_list(contact),
        "created_on": _safe_isoformat(contact.get("created_on")),
        "updated_on": _safe_isoformat(contact.get("updated_on")),
    }
    if "projects" in contact:
        raw_projects = contact["projects"]
        result["projects"] = (
            [_named_ref(p) for p in raw_projects if isinstance(p, dict)]
            if isinstance(raw_projects, (list, tuple))
            else []
        )
    return result


def _payload_int(value: Any) -> Optional[int]:
    """An integer from a response payload, or ``None`` when it is not one.

    ``bool`` is an ``int`` subclass, so it is excluded explicitly rather than
    counted as a page number.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _contact_pagination_info(
    payload: Dict[str, Any], limit: int, offset: int, count: int
) -> Dict[str, Any]:
    """Pagination metadata for a contact list, in the issue tools' shape.

    The key set is the one ``list_redmine_issues`` returns under
    ``pagination``, so a caller reads both tools the same way.

    ``limit`` and ``offset`` are the window Redmine reports having applied,
    falling back to the requested values when it reports none. Redmine echoes
    both alongside ``total_count``, and a build that served a smaller page than
    was asked for would otherwise get a ``next_offset`` that steps over the
    rows it withheld.

    ``has_next`` prefers measurement over inference. Given a total, the page
    covers rows ``[offset, offset + limit)``, so a further page exists exactly
    when ``offset + limit`` is below the total -- unlike the issue tools, which
    infer it from a full page and so claim one whenever the collection size is
    an exact multiple of the page size. Counting from ``limit`` rather than
    from ``count`` matters when ``search`` is in play, since Redmine narrows
    the returned page without narrowing the total, and the next page still
    starts a whole window along.

    Without a total it falls back to that same inference rather than to
    ``None``. Redmine renders ``total_count`` in the API metadata of a
    collection response, but what a given CRM build renders is the build's own
    business, and ``None`` is falsy: a caller testing ``has_next`` would read
    it as a last page and stop mid-collection. A full page reported as "ask
    again" costs one extra request at worst. ``total`` stays ``None`` either
    way, so an unreported total is never dressed up as a number.
    """
    total = _payload_int(payload.get("total_count"))

    applied_limit = _payload_int(payload.get("limit"))
    if not applied_limit or applied_limit < 1:
        applied_limit = limit
    applied_offset = _payload_int(payload.get("offset"))
    if applied_offset is None or applied_offset < 0:
        applied_offset = offset

    if total is None:
        has_next = count >= applied_limit
    else:
        has_next = applied_offset + applied_limit < total

    return {
        "total": total,
        "limit": applied_limit,
        "offset": applied_offset,
        "count": count,
        "has_next": has_next,
        "has_previous": applied_offset > 0,
        "next_offset": applied_offset + applied_limit if has_next else None,
        "previous_offset": (
            max(0, applied_offset - applied_limit) if applied_offset > 0 else None
        ),
    }


@offloaded
def _list_contacts_action(
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    author_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    include_pagination_info: bool = False,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    middle_name: Optional[str] = None,
    company: Optional[str] = None,
    job_title: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    # The dispatcher hands every `manage_contact` parameter to every action, so
    # `**_` collects the ones that belong to another action. Filters are built
    # from the named parameters below rather than from the collected keyword
    # arguments: `fields` arrives here on every call and Redmine would read it
    # as a filter-field list, wiping the query (_reject_reserved_query_keys).
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _REDMINE_API_PAGE_CAP)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return {"error": "offset must be a non-negative integer."}
    if project_id is not None and not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    params: Dict[str, Any] = {"limit": limit}
    if offset:
        params["offset"] = offset
    if project_id is not None:
        params["project_id"] = project_id
    if search is not None:
        params["search"] = search
    if tags is not None:
        params["tags"] = tags
    # Filters only the CRM plugin's Pro build registers. `assigned_to_id` is
    # absent from Light's `ContactQuery` too, but it is already on the tool and
    # predates this gate, so it is left alone rather than newly refused.
    pro_only = {
        "first_name": first_name,
        "last_name": last_name,
        "middle_name": middle_name,
        "company": company,
        "job_title": job_title,
        "email": email,
        "phone": phone,
        "author_id": author_id,
    }
    requested = sorted(name for name, value in pro_only.items() if value is not None)
    if requested:
        try:
            edition = _crm_edition()
        except RuntimeError as exc:
            return {"error": str(exc)}
        if edition != "pro":
            return {
                "error": (
                    f"{', '.join(requested)}: the CRM plugin's Light build does "
                    "not register these as query filters, and Redmine ignores "
                    "an unregistered filter without erroring -- the list would "
                    "come back unfiltered rather than empty, which is why this "
                    "is refused instead of sent. Set REDMINE_CRM_EDITION=pro if "
                    "this Redmine runs the Pro build, or filter the returned "
                    "contacts locally."
                )
            }

    for name, user_id in (
        ("assigned_to_id", assigned_to_id),
        ("author_id", author_id),
    ):
        if user_id is None:
            continue
        if not _is_positive_int(user_id):
            return {"error": f"{name} must be a positive integer."}
        params[name] = user_id

    # Reaching here means the deployment declared the Pro build. Verified
    # against 4.4.5 PRO by comparing the returned id set with ground truth
    # computed from the payload, rather than only checking that a non-matching
    # value came back empty.
    for name, value in pro_only.items():
        if value is not None and name != "author_id":
            params[name] = value

    if filters is not None:
        if not isinstance(filters, dict):
            return {"error": "filters must be a dict of Redmine query parameters."}
        # `manage_contact` carries create and update attributes in its own
        # `fields` parameter, so a caller reaching for `filters` can hit this
        # by accident.
        reserved_error = _reject_reserved_query_keys(filters)
        if reserved_error:
            return {
                "error": (
                    f"{reserved_error} Pass contact attributes through "
                    "`fields` instead."
                )
            }
        owned = sorted(_CONTACT_OWNED_QUERY_KEYS.intersection(filters))
        if owned:
            return {
                "error": (
                    f"filters may not contain {', '.join(owned)}: pass it as "
                    "the named parameter instead, so it is validated."
                )
            }
        params.update(filters)
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts.json"
        payload = client.engine.request("get", url, params=params)
        envelope = payload if isinstance(payload, dict) else {}
        raw = envelope.get("contacts", [])
        contacts = [_contact_to_dict(c) for c in raw[:limit]]
        if not include_pagination_info:
            return contacts
        return {
            "contacts": contacts,
            "pagination": _contact_pagination_info(
                envelope, limit, offset, len(contacts)
            ),
        }
    except Exception as e:
        return _handle_redmine_error(
            e, "listing contacts", {"resource_type": "contacts"}
        )


@offloaded
def _get_contact_action(
    contact_id: Optional[int] = None,
    include: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts/{contact_id}.json"
        params: Dict[str, Any] = {}
        if include:
            params["include"] = include
        payload = client.engine.request("get", url, params=params)
        contact = payload.get("contact", {}) if isinstance(payload, dict) else {}
        if not contact:
            return {"error": f"Contact {contact_id} not found."}
        return _contact_to_dict(contact)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching contact {contact_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@offloaded
def _create_contact_action(
    project_id: Optional[Union[str, int]] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_company: bool = False,
    visibility: int = 0,
    fields: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id is required and must be a non-empty string "
                "identifier or positive integer."
            )
        }
    if not isinstance(first_name, str) or not first_name.strip():
        return {"error": "first_name must be a non-empty string."}
    if not isinstance(is_company, bool):
        return {"error": "is_company must be a boolean."}
    if visibility not in (0, 1, 2):
        return {"error": "visibility must be 0 (Project), 1 (Public), or 2 (Private)."}
    body: Dict[str, Any] = {
        "project_id": project_id,
        "first_name": first_name,
        "is_company": is_company,
        "visibility": visibility,
    }
    if last_name is not None:
        body["last_name"] = last_name
    if company is not None:
        body["company"] = company
    if email is not None:
        body["email"] = email
    if phone is not None:
        body["phone"] = phone
    if fields:
        for k, v in fields.items():
            if k in _CONTACT_WRITABLE_FIELDS:
                body[k] = v
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts.json"
        payload = client.engine.request(
            "post",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"contact": body}),
        )
        contact = payload.get("contact", {}) if isinstance(payload, dict) else {}
        return _contact_to_dict(contact) if contact else {"success": True}
    except Exception as e:
        return _handle_redmine_error(
            e, "creating contact", {"resource_type": "contact"}
        )


@offloaded
def _update_contact_action(
    contact_id: Optional[int] = None,
    fields: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty dict."}
    filtered = {k: v for k, v in fields.items() if k in _CONTACT_WRITABLE_FIELDS}
    if not filtered:
        return {
            "error": (
                "No writable fields provided. Allowed fields: "
                f"{sorted(_CONTACT_WRITABLE_FIELDS)}"
            )
        }
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts/{contact_id}.json"
        client.engine.request(
            "put",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"contact": filtered}),
        )
        return {
            "success": True,
            "contact_id": contact_id,
            "updated_fields": list(filtered.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating contact {contact_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@offloaded
def _delete_contact_action(
    contact_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts/{contact_id}.json"
        client.engine.request("delete", url)
        return {
            "success": True,
            "contact_id": contact_id,
            "message": f"Contact {contact_id} deleted.",
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"deleting contact {contact_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@offloaded
def _assign_contact_to_project_action(
    contact_id: Optional[int] = None,
    project_id: Optional[Union[str, int]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts/{contact_id}/projects.json"
        client.engine.request(
            "post",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"project": {"id": project_id}}),
        )
        return {
            "success": True,
            "contact_id": contact_id,
            "project_id": project_id,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"assigning contact {contact_id} to project {project_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@offloaded
def _remove_contact_from_project_action(
    contact_id: Optional[int] = None,
    project_id: Optional[Union[str, int]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts/{contact_id}/projects/{project_id}.json"
        client.engine.request("delete", url)
        return {
            "success": True,
            "contact_id": contact_id,
            "project_id": project_id,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"removing contact {contact_id} from project {project_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@action_dispatch(
    {
        "list": ActionMode.READ,
        "get": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
        "assign_to_project": ActionMode.WRITE,
        "remove_from_project": ActionMode.WRITE,
    }
)
async def _manage_contact_dispatch(action: str, **kwargs: Any) -> Any:
    return {
        "list": _list_contacts_action,
        "get": _get_contact_action,
        "create": _create_contact_action,
        "update": _update_contact_action,
        "delete": _delete_contact_action,
        "assign_to_project": _assign_contact_to_project_action,
        "remove_from_project": _remove_contact_from_project_action,
    }


@mcp.tool()
async def manage_contact(
    action: Literal[
        "list",
        "get",
        "create",
        "update",
        "delete",
        "assign_to_project",
        "remove_from_project",
    ],
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    author_id: Optional[int] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 100,
    offset: Annotated[int, Field(ge=0)] = 0,
    include_pagination_info: bool = False,
    contact_id: Optional[int] = None,
    include: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    middle_name: Optional[str] = None,
    company: Optional[str] = None,
    job_title: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_company: bool = False,
    visibility: int = 0,
    fields: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP CRM (Contacts) plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``, ``delete``,
    ``assign_to_project``, ``remove_from_project``.

    Requires ``REDMINE_CRM_ENABLED=true`` and the RedmineUP CRM plugin.

    One flat signature serves every action, so most parameters apply to some
    actions and are ignored by the rest.

    ``search``, ``tags`` and ``assigned_to_id`` narrow a ``list`` on every CRM
    build. The contact attributes narrow one only on the plugin's Pro build,
    which registers them as query filters; the Light build registers ``tags``
    and nothing else, and Redmine drops an unregistered filter parameter
    silently, answering with the unfiltered collection. They are therefore
    refused unless ``REDMINE_CRM_EDITION=pro`` says the Pro build is installed
    -- an explicit error rather than a quietly wrong list.

    Which parameter belongs to which action:

    Args:
        contact_id: The contact to act on. Required by every action except
            ``list`` and ``create``.
        project_id: On ``list``, restrict to contacts in this project. On
            ``create``, the project to file the new contact under (required).
            On ``assign_to_project`` / ``remove_from_project``, the project to
            attach or detach.
        search: ``list`` only. Free-text search over name, company and email.
            Note that Redmine applies it to the page it returns without
            narrowing the reported total, so paging through a search is
            unreliable for more than one page.
        tags: ``list`` only. Comma-separated tag filter.
        assigned_to_id: ``list`` only. Filter by the assigned user's ID.
        author_id: ``list`` only. Filter by the ID of the user who created the
            contact. Needs ``REDMINE_CRM_EDITION=pro``.
        limit: ``list`` only. Contacts per call, capped at 100 by Redmine.
        offset: ``list`` only. Contacts to skip, for paging past the first 100.
        include_pagination_info: ``list`` only. Return
            ``{"contacts": [...], "pagination": {...}}`` rather than a bare
            list (default: False) -- the envelope ``list_redmine_issues``
            returns, with the same keys: ``total``, ``limit``, ``offset``,
            ``count``, ``has_next``, ``has_previous``, ``next_offset``,
            ``previous_offset``. ``total`` is the ``total_count`` Redmine
            reports for the collection, so a truncated read is visible without
            paging until an empty page comes back. ``total``, ``has_next`` and
            ``next_offset`` are ``null`` if the response carried no
            ``total_count``, meaning not reported rather than no further page.
            A ``search`` narrows the page without narrowing the total, so read
            ``count`` for what this call matched and ``total`` as the
            collection it searched.
        include: ``get`` only. Comma-separated related data to request.
        first_name: Required on ``create``. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        last_name: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        middle_name: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        company: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        job_title: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        email: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        phone: ``create`` attribute. Filters a ``list`` where
            ``REDMINE_CRM_EDITION=pro``.
        is_company: ``create`` only -- ``true`` files the record as a company
            rather than a person. This is **not** a list filter: the plugin's
            own ``is_company`` filter returns the same wrong set for every
            value, so filter the ``is_company`` key on the returned contacts
            instead.
        visibility: ``create`` only. ``0`` project, ``1`` public, ``2``
            private.
        fields: ``create`` and ``update`` only. Contact attributes to write.
        filters: ``list`` only. Additional Redmine query parameters, for
            filters this signature does not name -- most usefully
            ``{"cf_42": "value"}`` to filter on a contact custom field. What a
            build registers as a filter is the build's own business, so this
            cannot promise any key works: confirm a narrow filter actually
            narrowed. A contact custom field needs its "Used as a filter"
            setting on, and on the Light edition no contact custom field is
            ever a registered filter. Keys this signature already names are
            rejected -- pass them as the named parameter so they are validated
            -- as are ``fields``, ``f`` and ``query_id``, which Redmine reads
            as the query's own definition and which discard every filter built
            from the rest of the request.

    Returns:
        ``list`` a list of contact dicts -- or, with
        ``include_pagination_info=True``, a dict of ``contacts`` and
        ``pagination`` -- ``get`` / ``create`` one contact dict, the remaining
        actions a status dict, and ``{"error": ...}`` on failure.
    """
    if not _is_crm_enabled():
        return dict(_CRM_DISABLED_ERROR)
    return await _manage_contact_dispatch(
        action,
        project_id=project_id,
        search=search,
        tags=tags,
        assigned_to_id=assigned_to_id,
        author_id=author_id,
        limit=limit,
        offset=offset,
        include_pagination_info=include_pagination_info,
        contact_id=contact_id,
        include=include,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        company=company,
        job_title=job_title,
        email=email,
        phone=phone,
        is_company=is_company,
        visibility=visibility,
        fields=fields,
        filters=filters,
    )
