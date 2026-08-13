"""Run blocking python-redmine work off the asyncio event loop.

python-redmine is synchronous, and its laziness makes the blocking surface
wider than it looks: ``BaseResourceSet.__iter__`` issues the HTTP request on
first iteration rather than at ``.filter()``, and ``BaseResource.__getattr__``
calls ``refresh()`` when an included field is missing. A tool that only wrapped
its client call would still block the loop while iterating results or
serializing them.

So the rule is: a tool's entire synchronous section moves in one hop.

``@offloaded`` is the preferred form because it moves a whole function body by
construction. ``in_thread()`` is for tools that must stay coroutines because
they await something (an httpx upload, ``_ensure_cleanup_started()``); those
wrap their synchronous remainder in a nested closure.

Both use ``asyncio.to_thread``, which copies the current context into the
worker. That propagation is load-bearing: FastMCP's ``get_access_token()`` and
``get_http_request()`` read contextvars, so OAuth, oauth-proxy, and
legacy-per-user auth all resolve inside the worker.

See issue #216.
"""

import asyncio
import functools
import inspect
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


async def in_thread(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable in a worker thread.

    Exceptions propagate to the caller unchanged, so an existing
    ``try``/``except`` around the call site keeps working.
    """
    return await asyncio.to_thread(func, *args, **kwargs)


def offloaded(fn: Callable[..., T]) -> Callable[..., Awaitable[T]]:
    """Turn a synchronous function into a coroutine function run in a thread.

    Applied under ``@mcp.tool()`` so FastMCP registers the coroutine wrapper.
    ``functools.wraps`` keeps the name, docstring, and signature, so the
    generated tool schema and any ``await tool(...)`` in the tests are
    unchanged.
    """
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            f"@offloaded got {fn.__name__}, which is already a coroutine "
            "function. Drop the 'async' keyword, or use in_thread() for the "
            "synchronous section if the function must stay a coroutine."
        )

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        return await asyncio.to_thread(fn, *args, **kwargs)

    return wrapper
