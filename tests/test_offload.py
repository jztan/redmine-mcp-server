"""Tests for the event-loop offload helper (issue #216)."""

import asyncio
import contextvars
import threading
import time

import pytest

from redmine_mcp_server._offload import in_thread, offloaded


async def test_in_thread_runs_off_the_main_thread():
    main = threading.current_thread()
    worker = await in_thread(threading.current_thread)
    assert worker is not main


async def test_in_thread_passes_args_and_kwargs():
    def add(a, b, c=0):
        return a + b + c

    assert await in_thread(add, 1, 2, c=3) == 6


async def test_in_thread_propagates_exceptions():
    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        await in_thread(boom)


async def test_in_thread_propagates_contextvars():
    var = contextvars.ContextVar("var", default="unset")
    var.set("set-on-loop")
    assert await in_thread(var.get) == "set-on-loop"


async def test_in_thread_does_not_block_the_loop():
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    await in_thread(time.sleep, 0.5)
    task.cancel()

    assert ticks >= 10, f"loop only ticked {ticks} times during a 0.5s sync call"


async def test_offloaded_preserves_name_docstring_and_signature():
    @offloaded
    def sample(a: int, b: str = "x") -> dict:
        """Sample docstring."""
        return {"a": a, "b": b}

    import inspect

    assert sample.__name__ == "sample"
    assert sample.__doc__ == "Sample docstring."
    params = list(inspect.signature(sample).parameters)
    assert params == ["a", "b"]
    assert await sample(1) == {"a": 1, "b": "x"}


async def test_offloaded_runs_off_the_main_thread():
    @offloaded
    def where():
        return threading.current_thread()

    assert await where() is not threading.current_thread()


def test_offloaded_rejects_a_coroutine_function():
    with pytest.raises(TypeError, match="already a coroutine function"):

        @offloaded
        async def already_async():
            return None


async def test_legacy_client_cache_is_per_thread():
    from unittest.mock import patch

    from redmine_mcp_server import _client

    _client._reset_legacy_client_cache()
    with (
        patch.object(_client, "redmine", None),
        patch.object(_client, "_legacy_client", None),
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy"),
        patch.object(_client, "REDMINE_API_KEY", "key"),
        patch.object(_client, "REDMINE_URL", "https://redmine.example.com"),
    ):
        # The barrier forces the two hops to overlap. Without it the first can
        # finish before the second is submitted, both land on the same pooled
        # worker thread, and returning the cached client there is correct.
        barrier = threading.Barrier(2, timeout=5)

        def build_client():
            barrier.wait()
            return _client._get_redmine_client()

        first, second = await asyncio.gather(
            in_thread(build_client),
            in_thread(build_client),
        )

    assert first is not None and second is not None
    assert first is not second, "each worker thread must get its own client"


async def test_explicitly_patched_legacy_client_still_wins():
    from unittest.mock import Mock, patch

    from redmine_mcp_server import _client

    _client._reset_legacy_client_cache()
    sentinel = Mock(name="patched-client")
    with (
        patch.object(_client, "redmine", None),
        patch.object(_client, "_legacy_client", sentinel),
        patch.object(_client, "REDMINE_AUTH_MODE", "legacy"),
    ):
        got = await in_thread(_client._get_redmine_client)

    assert got is sentinel


async def test_tool_does_not_block_the_event_loop():
    """A hung Redmine call must not stall the loop (issue #216)."""
    from unittest.mock import Mock, patch

    from redmine_mcp_server.tools.gantt import get_gantt_chart

    client = Mock()

    def slow_filter(**kwargs):
        time.sleep(0.5)
        return []

    client.issue.filter.side_effect = slow_filter
    client.version.filter.return_value = []

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    with patch("redmine_mcp_server._client.redmine", client):
        task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        result = await get_gantt_chart(project_id=1)
        task.cancel()

    assert result["total_count"] == 0
    assert ticks >= 10, f"loop only ticked {ticks} times during a hung tool call"


def test_no_blocking_client_call_runs_on_the_event_loop():
    """Every _get_redmine_client() call must sit in a synchronous scope.

    A synchronous scope is either an @offloaded function or a `def _run()`
    closure passed to in_thread(), both of which execute in a worker thread.
    A call whose innermost enclosing function is `async def` runs on the event
    loop and reintroduces issue #216.

    This is a static check on purpose: it covers tools no test exercises, and
    it names the offender instead of failing as a timeout somewhere else.
    """
    import ast
    import pathlib
    import re

    import redmine_mcp_server

    blocking = re.compile(
        r"_get_redmine_client\(|_map_named_custom_fields|"
        r"_augment_fields_with_required"
    )
    package = pathlib.Path(redmine_mcp_server.__file__).parent

    offenders = []
    for path in sorted(package.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if not blocking.search(line):
                continue
            # Skip imports and the continuation lines of a multi-line import.
            if stripped.startswith(("from ", "import ", "#")) or stripped.endswith(","):
                continue
            innermost = None
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.lineno <= lineno <= node.end_lineno:
                    if innermost is None or node.lineno > innermost.lineno:
                        innermost = node
            if innermost is not None and isinstance(innermost, ast.AsyncFunctionDef):
                offenders.append(
                    f"{path.relative_to(package)}:{lineno} in {innermost.name}"
                )

    assert not offenders, (
        "blocking Redmine calls still run on the event loop: "
        + ", ".join(offenders)
        + ". Wrap the synchronous section with @offloaded or in_thread()."
    )


async def test_get_redmine_client_refuses_the_event_loop():
    from redmine_mcp_server import _client

    with pytest.raises(RuntimeError, match="event loop thread"):
        _client._get_redmine_client()


async def test_get_redmine_client_is_allowed_in_a_worker():
    from unittest.mock import Mock, patch

    from redmine_mcp_server import _client

    sentinel = Mock(name="client")
    with patch.object(_client, "redmine", sentinel):
        assert await in_thread(_client._get_redmine_client) is sentinel


async def test_allow_loop_thread_escape_hatch():
    from unittest.mock import Mock, patch

    from redmine_mcp_server import _client

    sentinel = Mock(name="client")
    with patch.object(_client, "redmine", sentinel):
        with _client.allow_loop_thread():
            assert _client._get_redmine_client() is sentinel


async def test_oauth_token_resolves_inside_the_worker():
    """The Bearer token must survive the hop to the worker thread."""
    from unittest.mock import Mock, patch

    from redmine_mcp_server import _client

    token = Mock()
    token.token = "test-bearer-token"
    captured = {}

    def fake_new_client(**kwargs):
        captured.update(kwargs)
        return Mock(name="oauth-client")

    # Read the token out of a ContextVar the way FastMCP's real
    # get_access_token() does. If the context did not reach the worker this
    # returns the default None and no Authorization header is built, which is
    # exactly the silent OAuth breakage this test exists to catch.
    current_token = contextvars.ContextVar("current_token", default=None)
    current_token.set(token)

    with (
        patch.object(_client, "redmine", None),
        patch.object(_client, "_legacy_client", None),
        patch.object(_client, "get_access_token", current_token.get),
        patch.object(_client, "_new_client", fake_new_client),
    ):
        await in_thread(_client._get_redmine_client)

    assert captured["requests"]["headers"]["Authorization"] == (
        "Bearer test-bearer-token"
    )
