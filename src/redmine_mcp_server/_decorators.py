"""Decorators that codify MCP tool patterns.

`@action_dispatch` enforces the `manage_X(action=...)` shape:
  - validates `action` against the spec
  - applies read-only guard for write actions
  - calls `_ensure_cleanup_started()` for write actions
  - dispatches to the per-action handler

The decorated function receives `(action, **kwargs)` and returns a dict
mapping action name -> async handler. The decorator extracts the handler
matching `action` and calls it with the same `**kwargs`. This keeps each
handler small, single-purpose, and unit-testable in isolation.
"""

import enum
import functools
import inspect
from typing import Any, Awaitable, Callable, Dict

from ._cleanup import _ensure_cleanup_started
from ._env import _is_read_only_mode
from ._errors import _READ_ONLY_ERROR


class ActionMode(enum.Enum):
    READ = "read"
    WRITE = "write"


def action_dispatch(spec: Dict[str, ActionMode]):
    """See module docstring for usage."""

    def decorator(handler_map_fn: Callable[..., Dict[str, Awaitable[Any]]]):
        @functools.wraps(handler_map_fn)
        async def wrapper(action: str, **kwargs: Any) -> Any:
            if action not in spec:
                return {
                    "error": (
                        f"Invalid action '{action}'. "
                        f"Allowed: {', '.join(sorted(spec))}"
                    )
                }
            mode = spec[action]
            if mode is ActionMode.WRITE:
                if _is_read_only_mode():
                    return dict(_READ_ONLY_ERROR)
                await _ensure_cleanup_started()
            handlers = handler_map_fn(action, **kwargs)
            if inspect.isawaitable(handlers):
                handlers = await handlers
            return await handlers[action](**kwargs)

        return wrapper

    return decorator
