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
from typing import Any, Dict, Optional

from redminelib.exceptions import ResourceNotFoundError

from .._client import _get_redmine_client
from .._env import _is_helpdesk_enabled, _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
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
        return _handle_redmine_error(
            e,
            f"sending Helpdesk email reply on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )

    message = response.get("message") if isinstance(response, dict) else None
    message = message if isinstance(message, dict) else {}
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
