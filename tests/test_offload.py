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
