"""RedmineUP Helpdesk plugin tool (REDMINE_HELPDESK_ENABLED gated).

``update_redmine_issue``'s ``notes`` creates a plain journal. A Helpdesk
ticket's customer never sees it: the reply email goes out only through the
plugin's own ``POST /helpdesk/email_note`` endpoint, which is what the web
UI's "Send Note" checkbox calls.

The plugin documents the endpoint as XML only, but the JSON variant answers
with the same fields (confirmed on Helpdesk 4.2.9 / Redmine 6.1.2 in #301),
so this uses JSON like every other call the server makes.
"""

import json
from typing import Any, Dict, Literal, Optional

from redminelib.exceptions import (
    ForbiddenError,
    ResourceNotFoundError,
    ValidationError,
)

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import (
    _is_helpdesk_enabled,
    _is_helpdesk_tickets_enabled,
    _is_read_only_mode,
)
from .._errors import (
    _READ_ONLY_ERROR,
    _handle_redmine_error,
    _scrub_error_message,
)
from .._offload import offloaded
from .._serialization import wrap_insecure_content
from .._validation import _is_positive_int
from .._plugin_visibility import plugin_tag
from ..server import mcp

_HELPDESK_DISABLED_ERROR = {
    "error": (
        "Helpdesk support is disabled. "
        "Set REDMINE_HELPDESK_ENABLED=true to enable it. "
        "Requires the RedmineUP Helpdesk plugin."
    )
}

# What Helpdesk 4.2.9 says, in a 422, for an issue with no customer attached.
_NO_CUSTOMER_MARKER = "relate to customer"


def _send_email_note_api(payload: Dict[str, Any]) -> Any:
    """POST a reply to the Helpdesk ``email_note`` endpoint.

    Raises on any HTTP error (caller is responsible for catching).
    """
    # Lazy lookup so tests patching `_client.REDMINE_URL` are honored.
    from .. import _client

    client = _get_redmine_client()
    url = f"{_client.REDMINE_URL}/helpdesk/email_note.json"
    return client.engine.request(
        "post",
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps({"message": payload}),
    )


@mcp.tool(tags={plugin_tag("helpdesk")})
@offloaded
def send_helpdesk_email_reply(
    issue_id: int,
    content: str,
    status_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Email a reply to the customer of a Helpdesk ticket.

    Unlike ``update_redmine_issue(notes=...)``, which only adds an internal
    journal, this sends ``content`` as an outgoing email to the ticket's
    requester and records it on the ticket. The email cannot be recalled
    once sent, so confirm the wording before calling.

    Works only on a Helpdesk ticket, meaning an issue with a customer
    attached. The plugin's endpoint checks no project role or permission
    (per a reading of its 4.2.9 controller in #301), so any authenticated
    Redmine user can send through it.

    Requires the RedmineUP Helpdesk plugin and
    ``REDMINE_HELPDESK_ENABLED=true``. This is a write operation and is
    blocked when ``REDMINE_MCP_READ_ONLY=true``.

    Args:
        issue_id: The Helpdesk ticket (issue) to reply on.
        content: The email body (required, non-blank).
        status_id: Optional status to set on the ticket once the reply is
            sent, e.g. to move it to "Waiting for customer".

    Returns:
        A success dict with ``journal_id`` of the recorded reply,
        ``to_address`` (the recipient), ``message_date`` and ``customer``
        (``{id, name}``), or an error dict on failure.
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    if not _is_helpdesk_enabled():
        return dict(_HELPDESK_DISABLED_ERROR)

    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}

    if not isinstance(content, str) or not content.strip():
        return {"error": "content is required and cannot be blank."}

    if status_id is not None and not _is_positive_int(status_id):
        return {"error": "status_id must be a positive integer."}

    payload: Dict[str, Any] = {"issue_id": issue_id, "content": content}
    if status_id is not None:
        payload["status_id"] = status_id

    try:
        response = _send_email_note_api(payload)
    except ResourceNotFoundError:
        # The plugin answers 422 for an unknown issue, so a 404 means the
        # endpoint itself is missing. The generic handler would report the
        # issue as not found, which sends the caller after the wrong thing.
        return {
            "error": (
                "Redmine has no /helpdesk/email_note endpoint. Check that the "
                "RedmineUP Helpdesk plugin is installed and enabled."
            )
        }
    except Exception as e:
        # An issue with no Helpdesk customer answers 422 like an unknown one
        # does (#301), and only the plugin's wording tells them apart. If that
        # wording changes, the plugin's own message still goes through below.
        if isinstance(e, ValidationError) and _NO_CUSTOMER_MARKER in str(e):
            return {
                "error": (
                    f"Issue {issue_id} is not a Helpdesk ticket: it has no "
                    "customer to email. Use update_redmine_issue to add an "
                    "internal note instead. Helpdesk said: "
                    f"{_scrub_error_message(str(e))}"
                )
            }
        return _handle_redmine_error(
            e,
            f"sending Helpdesk email reply on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )

    message = response.get("message") if isinstance(response, dict) else None
    message = message if isinstance(message, dict) else {}
    # Helpdesk 4.3 names the customer ``contact``; 4.2 called it ``customer``
    # (#384). The result keeps ``customer`` for either.
    customer = message.get("contact")
    if not isinstance(customer, dict):
        customer = message.get("customer")
    return {
        "success": True,
        "issue_id": issue_id,
        "journal_id": message.get("journal_id"),
        "to_address": message.get("to_address"),
        "message_date": message.get("message_date"),
        "customer": (
            {
                "id": customer.get("id"),
                "name": wrap_insecure_content(customer.get("name")),
            }
            if isinstance(customer, dict)
            else None
        ),
        "status_id": status_id,
    }


_HELPDESK_TICKETS_DISABLED_ERROR = {
    "error": (
        "Helpdesk ticket support is disabled. "
        "Set REDMINE_HELPDESK_TICKETS_ENABLED=true to enable it. "
        "Requires the RedmineUP Helpdesk and CRM plugins."
    )
}

# Returned as sent: ids, dates, flags and the plugin's own metrics.
_TICKET_PLAIN_FIELDS = (
    "source",
    "is_incoming",
    "ticket_date",
    "reaction_time",
    "first_response_time",
    "resolve_time",
    "last_agent_response_at",
    "last_customer_response_at",
    "vote",
)
# Customer-controlled: the message body, the vote comment, and the address
# and message-id fields the plugin copies from inbound email headers
# (mail_handler_patch.rb), where an attacker chooses the text.
_TICKET_WRAPPED_FIELDS = (
    "from_address",
    "to_address",
    "cc_address",
    "message_id",
    "content",
    "vote_comment",
)


class _Refusal(Exception):
    """A check failed before anything was written; ``message`` is for the caller."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    # Lazy lookup so tests patching `_client.REDMINE_URL` are honored.
    from .. import _client

    client = _get_redmine_client()
    return client.engine.request(
        "get", f"{_client.REDMINE_URL}{path}", params=params or {}
    )


def _fetch_visible_issue(issue_id: int) -> Dict[str, Any]:
    """Read the issue first: the plugin's own lookup ignores issue visibility.

    HelpdeskTicketsController#find_issue is an unscoped ``Issue.find`` and
    ``authorize`` checks only the project permission, so without this a
    caller could read a private issue's description through the ticket.
    """
    try:
        payload = _api_get(f"/issues/{issue_id}.json")
    except ResourceNotFoundError:
        raise _Refusal(f"Issue {issue_id} not found or not visible to you.")
    except ForbiddenError:
        raise _Refusal(f"Reading issue {issue_id} needs view_issues on its project.")
    issue = payload.get("issue") if isinstance(payload, dict) else None
    if not isinstance(issue, dict):
        raise _Refusal(f"Issue {issue_id} not found or not visible to you.")
    return issue


def _fetch_ticket(issue_id: int) -> Dict[str, Any]:
    """Read the Helpdesk ticket, refusing an issue that is not one.

    Called only after :func:`_fetch_visible_issue`, so a 404 here means the
    endpoint is missing, not the issue. A plain issue answers 200 with an
    unsaved, made-up ticket that has no ``contact``; a real ticket always
    has one (the plugin validates its presence).
    """
    try:
        payload = _api_get(f"/helpdesk_tickets/{issue_id}.json")
    except ResourceNotFoundError:
        raise _Refusal(
            "Redmine has no /helpdesk_tickets endpoint. Check that the "
            "RedmineUP Helpdesk plugin is installed and enabled."
        )
    except ForbiddenError:
        raise _Refusal(
            f"Reading Helpdesk ticket {issue_id} needs view_helpdesk_tickets "
            "and the Helpdesk module enabled on the issue's project."
        )
    ticket = payload.get("helpdesk_ticket") if isinstance(payload, dict) else None
    if not isinstance(ticket, dict) or not isinstance(ticket.get("contact"), dict):
        raise _Refusal(f"Issue {issue_id} is not a Helpdesk ticket.")
    return ticket


def _contact_ref(contact: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(contact, dict):
        return None
    return {
        "id": contact.get("id"),
        "name": wrap_insecure_content(contact.get("name")),
    }


def _ticket_to_dict(issue_id: int, ticket: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "issue_id": issue_id,
        "contact": _contact_ref(ticket.get("contact")),
    }
    for key in _TICKET_PLAIN_FIELDS:
        result[key] = ticket.get(key)
    for key in _TICKET_WRAPPED_FIELDS:
        result[key] = wrap_insecure_content(ticket.get(key))
    return result


@offloaded
def _get_ticket_action(issue_id: Any, **_: Any) -> Dict[str, Any]:
    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}
    try:
        _fetch_visible_issue(issue_id)
        ticket = _fetch_ticket(issue_id)
    except _Refusal as refusal:
        return {"error": refusal.message}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"reading Helpdesk ticket {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )
    return _ticket_to_dict(issue_id, ticket)


@action_dispatch({"get": ActionMode.READ})
async def _manage_helpdesk_ticket_dispatch(action: str, **kwargs: Any) -> Any:
    return {"get": _get_ticket_action}


@mcp.tool(tags={plugin_tag("helpdesk_tickets")})
async def manage_helpdesk_ticket(
    action: Literal["get", "set_contact"],
    issue_id: int,
    contact_id: Optional[int] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a RedmineUP Helpdesk ticket, or change its customer contact.

    Actions: ``get`` (read-only) and ``set_contact``.

    ``get`` returns the Helpdesk data ``get_redmine_issue`` does not carry:
    the ticket's ``contact`` (``{id, name}``), ``from_address`` (where
    replies go), ``to_address``, ``cc_address``, ``message_id``, ``source``,
    ``is_incoming``, ``ticket_date``, the response-time metrics, ``vote``,
    ``vote_comment`` and ``content`` (the customer's original message).
    Customer-controlled text is wrapped in boundary tags.

    ``set_contact`` moves the ticket to another existing contact, given
    either ``contact_id`` or ``email`` (exactly one). The contact must
    already exist, be linked to the issue's project and have an email
    address; the tool never creates a contact and never turns a plain issue
    into a ticket. Replies then go to the contact's primary email. Redmine
    keeps no history of the change, so the result's ``previous_contact`` is
    the only record of who it was.

    Args:
        action: ``get`` or ``set_contact``.
        issue_id: The Helpdesk ticket's issue id.
        contact_id: ``set_contact``: the contact to assign.
        email: ``set_contact``: an email address of the contact to assign,
            matched exactly (case-insensitive) within the issue's project.

    Returns:
        The ticket as described above (``set_contact`` adds
        ``previous_contact``), or ``{"error": ...}``.
    """
    if not _is_helpdesk_tickets_enabled():
        return dict(_HELPDESK_TICKETS_DISABLED_ERROR)
    return await _manage_helpdesk_ticket_dispatch(
        action, issue_id=issue_id, contact_id=contact_id, email=email
    )
