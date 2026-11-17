"""Warn when one caller sends many notification emails across issues (#469).

The hints from ``_notifications.py`` help with several calls on one issue.
They do not help when a task touches many issues: twenty issues with one
change each are twenty emails, each call looks fine on its own, and a
counter per issue stays at 1 the whole time.

``NotificationBudgetMiddleware`` counts the notifications of each caller in
a time window. From the budget on, the result of every further mailing call
carries a short note with the total and the issues touched, so the model can
stop and ask. It warns only: no call is refused.

The note goes into the result twice, because clients differ in what they
hand to the model: as ``notification_warning`` in the structured content,
and in the text content.

Off unless ``REDMINE_MCP_NOTIFY_BUDGET`` is set to a positive number.
``REDMINE_MCP_NOTIFY_WINDOW_MIN`` sets the window, 30 minutes by default.

What it counts is an estimate of what Redmine is asked to send, not of what
arrives:

- ``notification_count`` estimates each call from its arguments.
- Notifications can be switched off in Redmine, each user can narrow what
  they receive, and a plugin can mute a user's writes. The server sees none
  of that, so the note says "may have sent".

Counted per caller, as ``_caller.staged_upload_owner`` names them, because
the OAuth and api-key-login modes share one server across users. Where a
caller should be identifiable and is not (an OAuth token without ``sub``),
the call is not counted: a shared counter would show one user the issues
another one touched. That is logged once, since it switches the warning off
for those callers. In ``legacy`` mode everyone is the one configured
account, so all clients of the server share one count. The count lives in
memory, so it is lost on restart and not shared between worker processes.
"""

import json
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic_core import to_json

from ._caller import identity_expected, staged_upload_owner
from ._notifications import issue_fields, notification_count
from ._tool_error_middleware import _error_envelope

logger = logging.getLogger("redmine_mcp_server")

# Issues named in the note before it says "and N more".
MAX_ISSUES_IN_NOTE = 10
# Where the note sits in a tool's structured result.
NOTE_KEY = "notification_warning"
# Tools whose result names the issue they made; their ``issue_id`` argument,
# if any, is the source and not the issue that mails.
_NEW_ISSUE_TOOLS = frozenset({"create_redmine_issue", "copy_issue"})

_Entry = Tuple[float, int, Tuple[int, ...]]


def _as_id(value: Any) -> Optional[int]:
    """An issue id from an argument, which a client may send as a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _payload(structured: Any) -> Optional[dict]:
    """The tool's own result dict inside the structured content, if any."""
    if not isinstance(structured, dict):
        return None
    inner = structured.get("result")
    # A tool whose return type is not a plain dict is wrapped under "result"
    # (see ``build_error_tool_result``); a list there has no place for a key.
    if set(structured) == {"result"}:
        return inner if isinstance(inner, dict) else None
    return structured


def _issue_ids(tool_name: str, arguments: dict, structured: Any) -> Tuple[int, ...]:
    """The issues a call may have mailed about."""
    values: List[Any] = [issue_fields(arguments).get("parent_issue_id")]
    if tool_name in _NEW_ISSUE_TOOLS:
        values.append((_payload(structured) or {}).get("id"))
    else:
        values += [arguments.get("issue_id"), arguments.get("issue_to_id")]
    return tuple(issue for issue in map(_as_id, values) if issue is not None)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class NotificationBudgetMiddleware(Middleware):
    def __init__(self, budget: int, window_minutes: int = 30, clock=time.monotonic):
        self._budget = budget
        self._window_minutes = window_minutes
        self._clock = clock
        self._sent: Dict[Optional[str], Deque[_Entry]] = {}
        self._warned_unidentified = False

    async def on_call_tool(self, context, call_next):
        result = await call_next(context)
        message = context.message
        arguments = message.arguments or {}
        count = notification_count(message.name, arguments)
        if count == 0 or result.is_error:
            return result
        if _error_envelope(result.structured_content) is not None:
            return result
        owner = staged_upload_owner()
        if owner is None and identity_expected():
            self._warn_unidentified()
            return result

        entries = self._record(
            owner,
            count,
            _issue_ids(message.name, arguments, result.structured_content),
        )
        total = sum(entry[1] for entry in entries)
        if total < self._budget:
            return result
        return self._with_note(result, self._note(total, entries))

    def _warn_unidentified(self) -> None:
        if self._warned_unidentified:
            return
        self._warned_unidentified = True
        logger.warning(
            "REDMINE_MCP_NOTIFY_BUDGET is set, but this caller cannot be "
            "identified (an OAuth token without 'sub'), so its calls are not "
            "counted. See docs/oauth-setup.md for how to emit 'sub'."
        )

    def _record(
        self, owner: Optional[str], count: int, issues: Tuple[int, ...]
    ) -> Deque[_Entry]:
        now = self._clock()
        cutoff = now - self._window_minutes * 60
        # Drop what has left the window, for every caller, so an owner that
        # never comes back does not stay in memory.
        for key in list(self._sent):
            entries = self._sent[key]
            while entries and entries[0][0] <= cutoff:
                entries.popleft()
            if not entries:
                del self._sent[key]
        entries = self._sent.setdefault(owner, deque())
        entries.append((now, count, issues))
        return entries

    def _note(self, total: int, entries: Deque[_Entry]) -> str:
        issues = sorted({issue for entry in entries for issue in entry[2]})
        named = ", ".join(f"#{issue}" for issue in issues[:MAX_ISSUES_IN_NOTE])
        if len(issues) > MAX_ISSUES_IN_NOTE:
            named += f" and {len(issues) - MAX_ISSUES_IN_NOTE} more"
        where = f", across {_plural(len(issues), 'issue')} ({named})" if issues else ""
        return (
            f"Email: {_plural(total, 'notification')} may have been sent in the "
            f"last {_plural(self._window_minutes, 'minute')}{where}. Check with "
            "the user before changing more."
        )

    @staticmethod
    def _with_note(result: ToolResult, note: str) -> ToolResult:
        """A copy of the result that carries the note.

        The note becomes the first key of the tool's result dict, and the
        text block that mirrors that dict is written again to match. Where
        there is no such dict or no such block, the note is one more text
        block. The result object itself is not changed.
        """
        structured = result.structured_content
        content = list(result.content)
        payload = _payload(structured)
        mirrored = False
        if payload is not None:
            noted = {NOTE_KEY: note, **payload}
            if len(content) == 1 and isinstance(content[0], TextContent):
                try:
                    mirrored = json.loads(content[0].text) == payload
                except ValueError:
                    mirrored = False
            if mirrored:
                content = [TextContent(type="text", text=to_json(noted).decode())]
            structured = noted if structured is payload else {"result": noted}
        if not mirrored:
            content.append(TextContent(type="text", text=note))
        return ToolResult(
            content=content, structured_content=structured, meta=result.meta
        )
