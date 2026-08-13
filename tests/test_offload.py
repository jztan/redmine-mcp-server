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
