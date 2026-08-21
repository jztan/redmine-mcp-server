"""Input validation helpers used across MCP tools."""

import math
import re
from typing import Any, Optional

# Query parameters that replace, rather than add to, a Redmine query's
# filters. `fields` -- and its `f` alias -- is the list of fields a query
# filters on, and that branch empties the query's filters before rebuilding
# them from the request. `query_id` selects a saved query, which Redmine's
# `retrieve_query` prefers over anything built from the request. Forwarding any
# of them silently discards every other filter and answers HTTP 200 with the
# wrong set. This belongs to Redmine's query builder rather than to any one
# resource, so any tool forwarding a caller-supplied filter dict should reject
# them.
_RESERVED_QUERY_KEYS = frozenset({"fields", "f", "query_id"})


def _reject_reserved_query_keys(filters: Any) -> Optional[str]:
    """Return an error message if ``filters`` carries a reserved query key.

    Rack parses ``f[]`` into ``params[:f]`` and ``fields[]`` into
    ``params[:fields]``, so the bracketed spellings reach the same branch and
    are matched here too. Returns ``None`` when the dict is safe to forward.
    """
    if not isinstance(filters, dict):
        return None
    reserved = sorted(
        key
        for key in filters
        if isinstance(key, str)
        and (key[:-2] if key.endswith("[]") else key) in _RESERVED_QUERY_KEYS
    )
    if not reserved:
        return None
    return (
        f"filters may not contain {', '.join(reserved)}: Redmine reads it as "
        "the query's own filter definition and discards the filters built "
        "from the rest of the request, so every other filter would be lost."
    )


def _is_positive_int(value: Any) -> bool:
    """Return True if ``value`` is a positive integer.

    Rejects booleans (``True`` is a subclass of ``int`` in Python, so a
    plain ``isinstance(x, int)`` would accept ``True`` as ``1`` — which
    lets an attacker silently pass role ID 1 or user ID 1). Rejects
    floats, strings, and non-positive integers.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# Matches Redmine's project identifier rule: must start with a lowercase
# letter or digit, then lowercase letters / digits / hyphens / underscores,
# up to 100 chars total. Restricts the URL-path charset so callers cannot
# smuggle ``/``, ``?``, ``#``, ``..``, whitespace, or uppercase into paths.
_PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


def _is_valid_project_id(value: Any) -> bool:
    """Return True if ``value`` is a usable Redmine project identifier.

    Accepts a positive integer (numeric ID) or a string matching Redmine's
    project-identifier rule (``^[a-z0-9][a-z0-9_-]{0,99}$``). Strings
    containing path-injecting characters (``/``, ``?``, ``#``, ``..``,
    whitespace) or uppercase letters are rejected. Used by tools that
    interpolate ``project_id`` directly into URL paths.
    """
    if _is_positive_int(value):
        return True
    if isinstance(value, str) and _PROJECT_ID_PATTERN.match(value):
        return True
    return False


def _validate_hours(value: Any) -> Optional[str]:
    """Validate a time-entry ``hours`` value.

    Returns None if the value is acceptable (a finite positive number),
    otherwise an error message suitable for returning to the caller.

    Rejects:
    - None, strings, and other non-numeric types
    - Booleans (True is a subclass of int and would otherwise pass)
    - NaN and +/-Infinity
    - Zero and negative values
    """
    # Booleans are instances of int in Python — reject explicitly.
    if isinstance(value, bool):
        return "Hours must be a positive, finite number (got boolean)."
    if not isinstance(value, (int, float)):
        return "Hours must be a positive, finite number."
    if math.isnan(value) or math.isinf(value):
        return "Hours must be a positive, finite number (got NaN or Infinity)."
    if value <= 0:
        return "Hours must be a positive number."
    return None
