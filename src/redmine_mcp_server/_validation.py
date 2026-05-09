"""Input validation helpers used across MCP tools."""

import math
import re
from typing import Any, Optional


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
