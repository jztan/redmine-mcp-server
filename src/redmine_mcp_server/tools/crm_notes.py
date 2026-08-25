"""RedmineUP CRM notes tool: the activity log on contacts and deals.

Notes hang off a polymorphic ``source`` (``Contact`` or ``Deal``), so the
tool is available when either ``REDMINE_CRM_ENABLED`` or
``REDMINE_DEALS_ENABLED`` is on, and each call is additionally gated on
the flag that matches the note's source. ``get``, ``update`` and ``delete``
fetch the note first so a bare ``note_id`` cannot bypass that gate.

Plugin facts this module relies on (redmine_contacts 4.4.7):

* ``POST /notes.json`` needs ``note.project_id`` (404 without it),
  ``source_type`` (``deal``/``contact``, any case), ``source_id`` and
  ``content`` (422 "Content cannot be blank"). It has no ``authorize``
  filter of its own.
* ``PUT``/``DELETE /notes/<id>.json`` both require ``delete_notes``, or
  ``delete_own_notes`` for the author (the plugin reuses the delete
  permission for editing). Both answer 204 with no body.
* Timestamps come back RFC 822 (``Tue, 25 Aug 2026 11:32:23 +0000``).
"""

import json
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Literal, Optional, Union

from redminelib.exceptions import ForbiddenError

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _is_crm_enabled, _is_deals_enabled
from .._errors import _handle_redmine_error
from .._offload import offloaded
from .._plugin_visibility import plugin_tag
from .._serialization import _named_ref, _safe_isoformat, wrap_insecure_content
from .._validation import _is_positive_int, _is_valid_project_id
from ..server import mcp
from .contacts import _CRM_DISABLED_ERROR
from .deals import _DEALS_DISABLED_ERROR

# Note.note_types in the plugin.
_NOTE_TYPES = {0: "email", 1: "call", 2: "meeting"}
_NOTE_SOURCE_TYPES = ("contact", "deal")

_CRM_NOTES_DISABLED_ERROR = {
    "error": (
        "CRM notes support is disabled. Set REDMINE_CRM_ENABLED=true "
        "(contact notes) or REDMINE_DEALS_ENABLED=true (deal notes). "
        "Requires the RedmineUP CRM plugin."
    )
}


def _is_crm_notes_enabled() -> bool:
    return _is_crm_enabled() or _is_deals_enabled()


def _source_gate(source_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """Error dict when ``source_type`` is unknown or its plugin flag is off."""
    if source_type not in _NOTE_SOURCE_TYPES:
        return {"error": "source_type must be 'contact' or 'deal'."}
    if source_type == "deal" and not _is_deals_enabled():
        return dict(_DEALS_DISABLED_ERROR)
    if source_type == "contact" and not _is_crm_enabled():
        return dict(_CRM_DISABLED_ERROR)
    return None


def _note_timestamp(value: Any) -> Optional[str]:
    """ISO-8601 for the plugin's RFC 822 strings; other values pass through."""
    if isinstance(value, str):
        try:
            return parsedate_to_datetime(value).isoformat()
        except (TypeError, ValueError, IndexError):
            return value
    return _safe_isoformat(value)


def _note_to_dict(note: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize app/views/notes/show.api.rsb.

    ``content`` is free text and is wrapped in boundary tags; ``subject`` is
    label-shaped and returned verbatim, like deal ``name`` (#109). The
    source ``type`` is lower-cased to match the ``source_type`` input.
    """
    if not isinstance(note, dict):
        return {}
    src = note.get("source")
    source = None
    if isinstance(src, dict):
        raw_type = src.get("type")
        source = {
            "id": src.get("id"),
            "name": src.get("name"),
            "type": raw_type.lower() if isinstance(raw_type, str) else None,
        }
    type_id = note.get("type_id")
    return {
        "id": note.get("id"),
        "source": source,
        "subject": note.get("subject"),
        "content": wrap_insecure_content(note.get("content", "")),
        "type_id": type_id,
        "note_type": _NOTE_TYPES.get(type_id),
        "author": _named_ref(note.get("author")),
        "created_on": _note_timestamp(note.get("created_on")),
        "updated_on": _note_timestamp(note.get("updated_on")),
    }


_NOTE_FORBIDDEN_HINT = (
    "Access denied. The CRM plugin requires the delete_notes permission "
    "(or delete_own_notes for the note's author) for both editing and "
    "deleting notes."
)


def _fetch_note(client: Any, note_id: int) -> Dict[str, Any]:
    from .. import _client

    url = f"{_client.REDMINE_URL}/notes/{note_id}.json"
    payload = client.engine.request("get", url)
    return payload.get("note", {}) if isinstance(payload, dict) else {}


def _validate_type_id(type_id: Any) -> Optional[Dict[str, Any]]:
    if type_id is not None and type_id not in _NOTE_TYPES:
        return {"error": "type_id must be 0 (email), 1 (call) or 2 (meeting)."}
    return None


@offloaded
def _get_note_action(note_id: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    if not _is_positive_int(note_id):
        return {"error": "note_id must be a positive integer."}
    try:
        note = _fetch_note(_get_redmine_client(), note_id)
        if not note:
            return {"error": f"Note {note_id} not found."}
        serialized = _note_to_dict(note)
        gate = _source_gate((serialized.get("source") or {}).get("type"))
        if gate:
            return gate
        return serialized
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching note {note_id}",
            {"resource_type": "note", "resource_id": note_id},
        )


@offloaded
def _create_note_action(
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    project_id: Optional[Union[str, int]] = None,
    content: Optional[str] = None,
    subject: Optional[str] = None,
    type_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    gate = _source_gate(source_type)
    if gate:
        return gate
    if not _is_positive_int(source_id):
        return {"error": "source_id must be a positive integer."}
    if project_id is None or not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id is required on create (the plugin resolves the "
                "note's project from it) and must be a non-empty identifier "
                "or positive integer."
            )
        }
    if not isinstance(content, str) or not content.strip():
        return {"error": "content is required and must be non-empty."}
    bad_type = _validate_type_id(type_id)
    if bad_type:
        return bad_type
    body: Dict[str, Any] = {
        "source_type": source_type,
        "source_id": source_id,
        "project_id": project_id,
        "content": content,
    }
    if subject is not None:
        body["subject"] = subject
    if type_id is not None:
        body["type_id"] = type_id
    from .. import _client

    try:
        client = _get_redmine_client()
        payload = client.engine.request(
            "post",
            f"{_client.REDMINE_URL}/notes.json",
            data=json.dumps({"note": body}),
            headers={"Content-Type": "application/json"},
        )
        note = payload.get("note", {}) if isinstance(payload, dict) else {}
        return _note_to_dict(note) if note else {"error": "Redmine returned no note."}
    except Exception as e:
        result = _handle_redmine_error(
            e,
            "creating note",
            {"resource_type": source_type, "resource_id": source_id},
        )
        if result.get("error", "").endswith("not found."):
            result["error"] = (
                f"{source_type.capitalize()} {source_id} not found "
                f"(or project {project_id} not found)."
            )
        return result


@offloaded
def _update_note_action(
    note_id: Optional[int] = None,
    content: Optional[str] = None,
    subject: Optional[str] = None,
    type_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(note_id):
        return {"error": "note_id must be a positive integer."}
    if content is None and subject is None and type_id is None:
        return {"error": "update needs at least one of content, subject, type_id."}
    if content is not None and not content.strip():
        return {"error": "content must be non-empty when given."}
    bad_type = _validate_type_id(type_id)
    if bad_type:
        return bad_type
    body: Dict[str, Any] = {}
    if content is not None:
        body["content"] = content
    if subject is not None:
        body["subject"] = subject
    if type_id is not None:
        body["type_id"] = type_id
    from .. import _client

    try:
        client = _get_redmine_client()
        existing = _note_to_dict(_fetch_note(client, note_id))
        if not existing:
            return {"error": f"Note {note_id} not found."}
        gate = _source_gate((existing.get("source") or {}).get("type"))
        if gate:
            return gate
        client.engine.request(
            "put",
            f"{_client.REDMINE_URL}/notes/{note_id}.json",
            data=json.dumps({"note": body}),
            headers={"Content-Type": "application/json"},
        )
        return {"success": True, "note_id": note_id, "updated_fields": list(body)}
    except ForbiddenError:
        return {"error": _NOTE_FORBIDDEN_HINT}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating note {note_id}",
            {"resource_type": "note", "resource_id": note_id},
        )


@offloaded
def _delete_note_action(note_id: Optional[int] = None, **_: Any) -> Dict[str, Any]:
    if not _is_positive_int(note_id):
        return {"error": "note_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        existing = _note_to_dict(_fetch_note(client, note_id))
        if not existing:
            return {"error": f"Note {note_id} not found."}
        gate = _source_gate((existing.get("source") or {}).get("type"))
        if gate:
            return gate
        client.engine.request("delete", f"{_client.REDMINE_URL}/notes/{note_id}.json")
        return {
            "success": True,
            "note_id": note_id,
            "message": f"Note {note_id} deleted.",
        }
    except ForbiddenError:
        return {"error": _NOTE_FORBIDDEN_HINT}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"deleting note {note_id}",
            {"resource_type": "note", "resource_id": note_id},
        )


@action_dispatch(
    {
        "get": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
        "delete": ActionMode.WRITE,
    }
)
async def _manage_crm_note_dispatch(action: str, **kwargs: Any) -> Any:
    return {
        "get": _get_note_action,
        "create": _create_note_action,
        "update": _update_note_action,
        "delete": _delete_note_action,
    }


@mcp.tool(tags={plugin_tag("crm-shared")})
async def manage_crm_note(
    action: Literal["get", "create", "update", "delete"],
    note_id: Optional[int] = None,
    source_type: Optional[Literal["contact", "deal"]] = None,
    source_id: Optional[int] = None,
    project_id: Optional[Union[str, int]] = None,
    content: Optional[str] = None,
    subject: Optional[str] = None,
    type_id: Optional[int] = None,
) -> Dict[str, Any]:
    """RedmineUP CRM notes on contacts and deals. Combined CRUD-by-action.

    Notes are the CRM's activity log ("called them", "sent proposal").
    Available when ``REDMINE_CRM_ENABLED`` or ``REDMINE_DEALS_ENABLED`` is
    set; a note on a deal additionally needs deals enabled and a note on a
    contact needs CRM enabled. There is no list action: read a parent's
    notes with ``manage_deal(action="get", include="notes")``.

    Args:
        action: ``get``, ``create``, ``update`` or ``delete``.
        note_id: Required by every action except ``create``.
        source_type: ``create`` only, required: ``contact`` or ``deal``.
        source_id: ``create`` only, required: the contact or deal id.
        project_id: ``create`` only, required: the project the source
            belongs to (the plugin resolves the note's project from it).
        content: Required on ``create``; optional on ``update``.
        subject: Optional short title, ``create`` and ``update``.
        type_id: Optional note type, ``create`` and ``update``: 0 email,
            1 call, 2 meeting.

    Returns:
        ``get`` / ``create``: ``{id, source {id, name, type}, subject,
        content, type_id, note_type, author, created_on, updated_on}``.
        ``update``: ``{success, note_id, updated_fields}``. ``delete``:
        ``{success, note_id, message}``. ``{"error": ...}`` on failure.
        Editing and deleting both require the plugin's ``delete_notes``
        permission (or ``delete_own_notes`` for the author).
    """
    if not _is_crm_notes_enabled():
        return dict(_CRM_NOTES_DISABLED_ERROR)
    return await _manage_crm_note_dispatch(
        action,
        note_id=note_id,
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
        content=content,
        subject=subject,
        type_id=type_id,
    )
