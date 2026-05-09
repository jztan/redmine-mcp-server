"""Serialization and pagination helpers used across MCP tools."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Default cap on list_* tool results. Unbounded iteration over resource
# sets can OOM the server on large projects. Applies when the tool has
# no explicit limit parameter.
_DEFAULT_LIST_RESULT_CAP = 500

# Redmine's REST API caps the `limit` query parameter at 100 per request.
# Tools that issue a single HTTP call (no pagination loop) cannot exceed
# this regardless of what the caller asks for.
_REDMINE_API_PAGE_CAP = 100


def wrap_insecure_content(content: Any) -> Any:
    """Wrap user-controlled content in boundary tags to prevent prompt injection.

    Wraps non-empty string content in unique boundary tags so that LLM
    consumers can distinguish trusted tool output from untrusted user data.

    Args:
        content: The content to wrap. Non-string or empty values are
                 returned unchanged.

    Returns:
        Wrapped string with boundary tags, or original value if not a
        non-empty string.
    """
    if not isinstance(content, str) or not content:
        return content
    boundary = uuid.uuid4().hex[:16]
    return (
        f"<insecure-content-{boundary}>\n{content}\n" f"</insecure-content-{boundary}>"
    )


def _iter_capped(resources: Any, cap: int = _DEFAULT_LIST_RESULT_CAP) -> List[Any]:
    """Materialize up to ``cap`` items from a python-redmine lazy resource set.

    python-redmine's resource sets are lazy and iterate fresh on demand,
    so `list(resource_set)` can OOM on very large projects. This helper
    draws at most ``cap`` items and returns a plain list.
    """
    out: List[Any] = []
    try:
        iterator = iter(resources)
    except TypeError:
        return out
    for i, item in enumerate(iterator):
        if i >= cap:
            break
        out.append(item)
    return out


def _named_ref(obj: Any) -> Optional[Dict[str, Any]]:
    """Serialize a Redmine object with `id` + `name` to a dict.

    Used for author/user/group/version/project refs that appear inside
    larger tool-output dicts. The ``name`` field is wrapped in
    ``<insecure-content>`` boundary tags because display names are user-
    controlled (a malicious user can set their name to a prompt-injection
    payload).

    Returns ``None`` when ``obj`` is ``None``.
    """
    if obj is None:
        return None
    return {
        "id": getattr(obj, "id", None),
        "name": wrap_insecure_content(getattr(obj, "name", "")),
    }


def _safe_isoformat(val: Any) -> Optional[str]:
    """Return an ISO-8601 string for a date/datetime value.

    Some Redmine fields arrive as pre-formatted strings instead of
    ``datetime`` objects.  Calling ``.isoformat()`` on those strings
    raises ``AttributeError``, so this helper passes strings through
    unchanged and only calls ``.isoformat()`` on real date/datetime
    instances.
    """
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return val.isoformat()


def _coerce_json_safe(value: Any) -> Any:
    """Convert arbitrary values into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_coerce_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _coerce_json_safe(item) for key, item in value.items()}
    return str(value)
