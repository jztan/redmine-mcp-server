"""RedmineUP CRM (Contacts) plugin tool (REDMINE_CRM_ENABLED gated)."""

import json
from typing import Any, Dict, List, Optional, Union

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _is_crm_enabled
from .._errors import _handle_redmine_error
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _is_valid_project_id
from ..server import mcp

_CRM_DISABLED_ERROR = {
    "error": (
        "Contacts (CRM) support is disabled. "
        "Set REDMINE_CRM_ENABLED=true to enable it. "
        "Requires the RedmineUP CRM plugin."
    )
}

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


def _contact_to_dict(contact: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP CRM API response into a stable dict.

    User-controlled fields are wrapped in ``<insecure-content>`` boundary
    tags. Contact PII (email, phone, address) is returned as-is to the
    caller but never logged via logger.* calls in this module.
    """
    if not isinstance(contact, dict):
        return {}
    raw_assigned = contact.get("assigned_to")
    assigned = raw_assigned if isinstance(raw_assigned, dict) else {}
    raw_address = contact.get("address")
    address = raw_address if isinstance(raw_address, dict) else {}
    return {
        "id": contact.get("id"),
        "first_name": wrap_insecure_content(contact.get("first_name", "")),
        "last_name": wrap_insecure_content(contact.get("last_name", "")),
        "middle_name": wrap_insecure_content(contact.get("middle_name", "")),
        "company": wrap_insecure_content(contact.get("company", "")),
        "job_title": wrap_insecure_content(contact.get("job_title", "")),
        "phone": contact.get("phone"),
        "email": contact.get("email"),
        "website": contact.get("website"),
        "skype_name": contact.get("skype_name"),
        "birthday": contact.get("birthday"),
        "background": wrap_insecure_content(contact.get("background", "")),
        "address": (
            {
                "street1": address.get("street1"),
                "street2": address.get("street2"),
                "city": address.get("city"),
                "region": address.get("region"),
                "country": address.get("country"),
                "postcode": address.get("postcode"),
            }
            if address
            else None
        ),
        "is_company": contact.get("is_company", False),
        "tags": contact.get("tags") or [],
        "visibility": contact.get("visibility"),
        "assigned_to": (
            {
                "id": assigned.get("id"),
                "name": wrap_insecure_content(assigned.get("name", "")),
            }
            if assigned
            else None
        ),
        "created_on": _safe_isoformat(contact.get("created_on")),
        "updated_on": _safe_isoformat(contact.get("updated_on")),
    }


async def _list_contacts_action(
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    limit: int = 100,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _REDMINE_API_PAGE_CAP)
    if project_id is not None and not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    params: Dict[str, Any] = {"limit": limit}
    if project_id is not None:
        params["project_id"] = project_id
    if search is not None:
        params["search"] = search
    if tags is not None:
        params["tags"] = tags
    if assigned_to_id is not None:
        if not _is_positive_int(assigned_to_id):
            return {"error": "assigned_to_id must be a positive integer."}
        params["assigned_to_id"] = assigned_to_id
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/contacts.json"
        payload = client.engine.request("get", url, params=params)
        raw = payload.get("contacts", []) if isinstance(payload, dict) else []
        return [_contact_to_dict(c) for c in raw[:limit]]
    except Exception as e:
        return _handle_redmine_error(
            e, "listing contacts", {"resource_type": "contacts"}
        )


async def _get_contact_action(
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


async def _create_contact_action(
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


async def _update_contact_action(
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


async def _delete_contact_action(
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


async def _assign_contact_to_project_action(
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


async def _remove_contact_from_project_action(
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
    action: str,
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    limit: int = 100,
    contact_id: Optional[int] = None,
    include: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_company: bool = False,
    visibility: int = 0,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP CRM (Contacts) plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``, ``delete``,
    ``assign_to_project``, ``remove_from_project``.

    Requires ``REDMINE_CRM_ENABLED=true`` and the RedmineUP CRM plugin.
    """
    if not _is_crm_enabled():
        return dict(_CRM_DISABLED_ERROR)
    return await _manage_contact_dispatch(
        action,
        project_id=project_id,
        search=search,
        tags=tags,
        assigned_to_id=assigned_to_id,
        limit=limit,
        contact_id=contact_id,
        include=include,
        first_name=first_name,
        last_name=last_name,
        company=company,
        email=email,
        phone=phone,
        is_company=is_company,
        visibility=visibility,
        fields=fields,
    )
