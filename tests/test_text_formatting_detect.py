"""Detecting the text formatting over HTTP, and caching it (#440)."""

import asyncio
import base64
from pathlib import Path

import httpx
import pytest

from redmine_mcp_server._client import RequestCredential
from redmine_mcp_server._text_formatting import (
    FormatResult,
    TextFormattingResolver,
    detect_format,
)

FIXTURES = Path(__file__).parent / "fixtures" / "text_formatting"
KEY_CRED = RequestCredential(kind="legacy", api_key="k1")


@pytest.fixture(autouse=True)
def _plain_ssl(monkeypatch):
    """Isolate from SSL settings other tests leave on the _client module."""
    from redmine_mcp_server import _client

    monkeypatch.setattr(_client, "httpx_ssl_kwargs", lambda url=None: {})


def _redmine(page_status=200, issues=({"id": 7},), page=None, seen=None):
    page = page if page is not None else (FIXTURES / "common_mark_6x.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/issues.json"):
            return httpx.Response(200, json={"issues": list(issues)})
        if request.url.path.endswith("/issues/7"):
            if page_status == 302:
                return httpx.Response(302, headers={"Location": "/login"})
            return httpx.Response(page_status, text=page)
        return httpx.Response(200, text=(FIXTURES / "login.html").read_text())

    return httpx.MockTransport(handler)


async def test_detect_success():
    result = await detect_format(KEY_CRED, base_url="https://h", transport=_redmine())
    assert result == "common_mark"


async def test_detect_no_issues():
    transport = _redmine(issues=())
    assert await detect_format(KEY_CRED, base_url="https://h", transport=transport) is None


async def test_detect_401():
    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    assert await detect_format(KEY_CRED, base_url="https://h", transport=transport) is None


async def test_detect_redirect_is_failure():
    seen = []
    transport = _redmine(page_status=302, seen=seen)
    assert await detect_format(KEY_CRED, base_url="https://h", transport=transport) is None
    assert not any(r.url.path == "/login" for r in seen)


async def test_detect_network_error_is_failure():
    def boom(request):
        raise httpx.ConnectError("down")

    transport = httpx.MockTransport(boom)
    assert await detect_format(KEY_CRED, base_url="https://h", transport=transport) is None


async def test_detect_keeps_url_subpath():
    seen = []
    transport = _redmine(seen=seen)
    await detect_format(KEY_CRED, base_url="https://h/redmine/", transport=transport)
    assert [r.url.path for r in seen] == ["/redmine/issues.json", "/redmine/issues/7"]


async def test_detect_sends_api_key():
    seen = []
    await detect_format(KEY_CRED, base_url="https://h", transport=_redmine(seen=seen))
    assert all(r.headers["X-Redmine-API-Key"] == "k1" for r in seen)


async def test_detect_sends_basic_auth():
    seen = []
    cred = RequestCredential(kind="legacy", basic=("u", "p"))
    await detect_format(cred, base_url="https://h", transport=_redmine(seen=seen))
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert all(r.headers["Authorization"] == expected for r in seen)


class _Detector:
    def __init__(self, results, delay=0.0):
        self.results = list(results)
        self.calls = []
        self.delay = delay

    async def __call__(self, cred, *, base_url):
        self.calls.append(cred)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.results.pop(0) if self.results else None


async def test_env_value_skips_detection(monkeypatch):
    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", "textile")

    async def explode(cred, *, base_url):
        raise AssertionError("detector must not run")

    resolver = TextFormattingResolver(detector=explode)
    assert await resolver.resolve(KEY_CRED) == FormatResult("textile", "env")


async def test_success_cached_for_process():
    detector = _Detector(["markdown"])
    resolver = TextFormattingResolver(detector=detector)
    for key in ("a", "b", "c"):
        cred = RequestCredential(kind="per-user", api_key=key)
        assert await resolver.resolve(cred) == FormatResult("markdown", "detected")
    assert len(detector.calls) == 1


async def test_failure_cached_per_credential():
    now = [1000.0]
    detector = _Detector([None, None, None])
    resolver = TextFormattingResolver(detector=detector, clock=lambda: now[0])
    a = RequestCredential(kind="per-user", api_key="a")
    b = RequestCredential(kind="per-user", api_key="b")
    unknown = FormatResult("unknown", "unknown")

    assert await resolver.resolve(a) == unknown
    assert await resolver.resolve(a) == unknown
    assert len(detector.calls) == 1  # A's failure is cached
    now[0] += 31  # past the global backoff that follows any failure
    assert await resolver.resolve(b) == unknown
    assert len(detector.calls) == 2  # B is not blocked by A
    now[0] += 601
    await resolver.resolve(a)
    assert len(detector.calls) == 3  # A retries after the TTL


async def test_no_credential_is_unknown():
    detector = _Detector(["markdown"])
    resolver = TextFormattingResolver(detector=detector)
    assert await resolver.resolve(None) == FormatResult("unknown", "unknown")
    assert detector.calls == []


async def test_concurrent_resolve_detects_once():
    detector = _Detector(["textile"], delay=0.01)
    resolver = TextFormattingResolver(detector=detector)
    results = await asyncio.gather(*(resolver.resolve(KEY_CRED) for _ in range(5)))
    assert len(detector.calls) == 1
    assert set(results) == {FormatResult("textile", "detected")}


async def test_reset_forgets_detection():
    detector = _Detector(["textile", "markdown"])
    resolver = TextFormattingResolver(detector=detector)
    await resolver.resolve(KEY_CRED)
    resolver.reset()
    assert (await resolver.resolve(KEY_CRED)).value == "markdown"


@pytest.mark.parametrize("env", ["textile", "none"])
async def test_current_format_honours_env(monkeypatch, env):
    from redmine_mcp_server._text_formatting import current_format

    monkeypatch.setenv("REDMINE_TEXT_FORMATTING", env)
    assert await current_format() == FormatResult(env, "env")


async def test_suite_never_detects_over_network():
    """The conftest null detector keeps auto mode offline in unit tests."""
    from redmine_mcp_server._text_formatting import current_format

    assert await current_format() == FormatResult("unknown", "unknown")


async def test_detect_bad_ssl_config_is_failure(monkeypatch):
    from redmine_mcp_server import _client

    def missing_cert(url=None):
        raise FileNotFoundError("SSL certificate not found")

    monkeypatch.setattr(_client, "httpx_ssl_kwargs", missing_cert)
    assert await detect_format(KEY_CRED, base_url="https://h", transport=_redmine()) is None


async def test_detection_capped_overall():
    """#440 review: the 5 s cap covers the whole detection, not each phase."""
    detector = _Detector(["textile"], delay=1.0)
    resolver = TextFormattingResolver(detector=detector, timeout=0.05)
    started = asyncio.get_running_loop().time()
    assert await resolver.resolve(KEY_CRED) == FormatResult("unknown", "unknown")
    assert asyncio.get_running_loop().time() - started < 0.5


async def test_failures_do_not_queue_across_credentials():
    """#440 review: many users on a cold, failing start must not serialize."""
    detector = _Detector([], delay=0.05)  # every call fails
    resolver = TextFormattingResolver(detector=detector)
    creds = [RequestCredential(kind="per-user", api_key=str(i)) for i in range(10)]
    started = asyncio.get_running_loop().time()
    results = await asyncio.gather(*(resolver.resolve(c) for c in creds))
    assert set(results) == {FormatResult("unknown", "unknown")}
    assert len(detector.calls) == 1
    assert asyncio.get_running_loop().time() - started < 0.3


async def test_global_backoff_after_failure():
    now = [0.0]
    detector = _Detector([None, "markdown"])
    resolver = TextFormattingResolver(detector=detector, clock=lambda: now[0])
    a = RequestCredential(kind="per-user", api_key="a")
    b = RequestCredential(kind="per-user", api_key="b")
    await resolver.resolve(a)
    assert await resolver.resolve(b) == FormatResult("unknown", "unknown")
    assert len(detector.calls) == 1  # B waits out the backoff
    now[0] += 31
    assert await resolver.resolve(b) == FormatResult("markdown", "detected")


async def test_failure_cache_bounded():
    """#440 review: distinct failing credentials must not grow memory forever."""
    now = [0.0]
    detector = _Detector([])  # always fails
    resolver = TextFormattingResolver(
        detector=detector, clock=lambda: now[0], max_failures=3
    )
    creds = [RequestCredential(kind="per-user", api_key=str(i)) for i in range(5)]
    for cred in creds:
        await resolver.resolve(cred)
        now[0] += 31
    assert len(detector.calls) == 5
    await resolver.resolve(creds[0])  # evicted as oldest, so it detects again
    assert len(detector.calls) == 6
    await resolver.resolve(creds[4])  # still remembered
    assert len(detector.calls) == 6
