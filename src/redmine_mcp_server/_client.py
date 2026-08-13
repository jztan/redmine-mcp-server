"""Redmine client factory and connection-level config.

Owns:
  - Module-level REDMINE_URL / REDMINE_API_KEY / REDMINE_USERNAME /
    REDMINE_PASSWORD / REDMINE_AUTH_MODE / SSL config (read once from env).
  - The cached `_legacy_client` singleton and the `redmine` module-level var.
  - `_get_redmine_client()` -- the single entry point used by every MCP tool.

In OAuth mode, the per-request Bearer token is retrieved via FastMCP's
`get_access_token()` dependency (from `fastmcp.server.dependencies`),
which reads the AccessToken injected by RemoteAuthProvider after
RFC 7662 introspection succeeds.

Tests patch this module's attributes directly, e.g.
``patch("redmine_mcp_server._client.REDMINE_API_KEY", "...")`` or
``patch("redmine_mcp_server._client.Redmine")``.
"""

import asyncio
import contextlib
import logging
import os
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp.server.dependencies import get_access_token, get_http_request
from redminelib import Redmine
from redminelib.engines import SyncEngine

from ._env import get_redmine_timeout

logger = logging.getLogger("redmine_mcp_server")

# Load environment variables from .env file before reading Redmine config.
# Search order: current working directory first, then package directory.
_env_paths = [
    Path.cwd() / ".env",  # User's current working directory (highest priority)
    Path(__file__).parent.parent.parent / ".env",  # Package directory (fallback)
]

_env_loaded = False
for _env_path in _env_paths:
    if _env_path.exists():
        load_dotenv(dotenv_path=str(_env_path))
        logger.info(f"Loaded .env from: {_env_path}")
        _env_loaded = True
        break

if not _env_loaded:
    # Try default load_dotenv() behavior as final fallback
    load_dotenv()

# Load Redmine configuration
REDMINE_URL = os.getenv("REDMINE_URL")
REDMINE_USERNAME = os.getenv("REDMINE_USERNAME")
REDMINE_PASSWORD = os.getenv("REDMINE_PASSWORD")
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY")

# Auth mode:
# - "oauth" and "oauth-proxy" use per-request Bearer tokens via FastMCP auth.
# - "legacy" uses REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD (default).
REDMINE_AUTH_MODE = os.getenv("REDMINE_AUTH_MODE", "legacy").lower()

# SSL Configuration (optional)
REDMINE_SSL_VERIFY = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
REDMINE_SSL_CERT = os.getenv("REDMINE_SSL_CERT")
REDMINE_SSL_CLIENT_CERT = os.getenv("REDMINE_SSL_CLIENT_CERT")


def _resolve_ssl_verify() -> Union[bool, str]:
    """Resolve the verify setting: False, a validated CA path, or True."""
    if not REDMINE_SSL_VERIFY:
        return False
    if REDMINE_SSL_CERT:
        cert_path = Path(REDMINE_SSL_CERT).resolve()
        if not cert_path.exists():
            raise FileNotFoundError(
                f"SSL certificate not found: {REDMINE_SSL_CERT} "
                f"(resolved to: {cert_path})"
            )
        if not cert_path.is_file():
            raise ValueError(
                f"SSL certificate path must be a file, not directory: {cert_path}"
            )
        return str(cert_path)
    return True


def _resolve_client_cert() -> Optional[Union[str, tuple]]:
    """Resolve the client certificate for mutual TLS, if configured."""
    if not REDMINE_SSL_CLIENT_CERT:
        return None
    if "," in REDMINE_SSL_CLIENT_CERT:
        cert, key = REDMINE_SSL_CLIENT_CERT.split(",", 1)
        return (cert.strip(), key.strip())
    return REDMINE_SSL_CLIENT_CERT


def _proxies_from_env() -> dict:
    """Read proxy settings from the environment for the Redmine URL.

    Needed because pinning ``trust_env=False`` on the session (see
    ``_build_requests_config``) also switches off requests' own proxy
    env handling, including NO_PROXY.
    """
    from requests.utils import getproxies, should_bypass_proxies

    url = globals()["REDMINE_URL"]
    try:
        if url and should_bypass_proxies(url, no_proxy=None):
            return {}
    except Exception:  # malformed URL: fall through to the env proxies
        pass
    return getproxies()


def _warn_on_conflicting_ssl_env() -> None:
    """Name environment variables that fight an explicit SSL setting.

    Both cases below produced the same "certificate verify failed" symptom in
    issue #197, so say out loud what is present instead of leaving the next
    reporter to guess.
    """
    ca_vars = [v for v in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE") if os.getenv(v)]
    if ca_vars:
        logger.warning(
            "Ignoring CA bundle from the environment (%s) for Redmine "
            "connections: REDMINE_SSL_VERIFY / REDMINE_SSL_CERT takes "
            "precedence.",
            ", ".join(ca_vars),
        )

    proxy_vars = [
        v
        for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
        if (os.getenv(v) or "").lower().startswith("https://")
    ]
    if proxy_vars:
        logger.warning(
            "An HTTPS proxy is configured (%s). Its own certificate is "
            "verified regardless of REDMINE_SSL_VERIFY, and a failure there "
            "is reported against the Redmine host.",
            ", ".join(proxy_vars),
        )


# Build SSL requests config from environment (used by _get_redmine_client)
def _build_requests_config() -> dict:
    requests_config = {}
    verify = _resolve_ssl_verify()
    if verify is False:
        requests_config["verify"] = False
        logger.warning("SSL verification is DISABLED - use only for development!")
    elif verify is not True:
        requests_config["verify"] = verify
        logger.info(f"Using custom SSL certificate: {verify}")

    client_cert = _resolve_client_cert()
    if client_cert is not None:
        requests_config["cert"] = client_cert
        logger.info("Using client certificate for mutual TLS")

    if "verify" in requests_config:
        _warn_on_conflicting_ssl_env()
        # requests fills an unset per-request `verify` from REQUESTS_CA_BUNDLE
        # / CURL_CA_BUNDLE, and that value beats `session.verify`. Since
        # python-redmine never passes a per-request verify, an env CA bundle
        # would silently override an explicit REDMINE_SSL_VERIFY/REDMINE_SSL_CERT
        # choice. Ignoring the environment keeps our decision authoritative;
        # proxies are carried over by hand because trust_env covers those too.
        requests_config["trust_env"] = False
        proxies = _proxies_from_env()
        if proxies:
            requests_config["proxies"] = proxies

    return requests_config


class TimeoutSyncEngine(SyncEngine):
    """SyncEngine that puts REDMINE_TIMEOUT on every request.

    redminelib drops a ``requests={"timeout": ...}`` config on the floor:
    ``SyncEngine.create_session()`` setattr()s it onto a ``requests.Session``,
    which has no ``timeout`` attribute that is read at request time, and
    ``BaseEngine.construct_request_kwargs()`` never builds one. Without this
    class a Redmine that accepts the connection and never answers hangs the
    call forever (issue #214).

    Injecting here rather than monkeypatching ``session.request`` matters:
    ``Redmine.session()`` re-instantiates ``engine.__class__``, and
    ``Redmine.download()`` uses that context manager, so a patched method
    would be silently dropped for attachment downloads. A subclass survives.

    The timeout is read per request, not captured at construction, so the
    cached legacy client picks up an env change without being rebuilt.
    """

    @staticmethod
    def construct_request_kwargs(method, headers, params, data):
        kwargs = SyncEngine.construct_request_kwargs(method, headers, params, data)
        timeout = get_redmine_timeout()
        if timeout is not None:
            kwargs.setdefault("timeout", timeout)
        return kwargs


def _new_client(**kwargs) -> Redmine:
    """Build a Redmine client with this server's connection-level defaults.

    Every client must carry ``engine=TimeoutSyncEngine`` and the SSL/proxy
    config from ``_build_requests_config()``. Routing all construction through
    here keeps that true for auth modes added later; the previous shape
    repeated each branch with and without a ``requests=`` config, so a new
    connection setting could reach half the call sites.

    A caller-supplied ``requests`` dict (the OAuth Authorization header) is
    merged on top of the shared config rather than replacing it.
    """
    g = globals()
    requests_config = _build_requests_config()
    caller_requests = kwargs.pop("requests", None)
    if caller_requests:
        requests_config = {**requests_config, **caller_requests}
    if requests_config:
        kwargs["requests"] = requests_config
    return g["Redmine"](g["REDMINE_URL"], engine=TimeoutSyncEngine, **kwargs)


def httpx_ssl_kwargs(url: Optional[str] = None) -> dict:
    """Return `verify`/`cert` kwargs for an httpx client talking to Redmine.

    httpx defaults to full verification and knows nothing about
    REDMINE_SSL_VERIFY / REDMINE_SSL_CERT, so every httpx call site aimed at
    the configured Redmine server has to pass these explicitly.

    When ``url`` is given, the settings apply only if it points at the
    configured Redmine host, so a relaxed setting never follows a download
    to a third-party host.
    """
    if url is not None and not _is_redmine_host(url):
        return {}

    kwargs: dict = {}
    verify = _resolve_ssl_verify()
    if verify is not True:
        kwargs["verify"] = verify
    client_cert = _resolve_client_cert()
    if client_cert is not None:
        kwargs["cert"] = client_cert
    return kwargs


def _is_redmine_host(url: str) -> bool:
    """Whether `url` points at the same host:port as REDMINE_URL."""
    redmine_url = globals()["REDMINE_URL"]
    if not redmine_url:
        return False
    try:
        target = urlparse(url)
        configured = urlparse(redmine_url)
    except ValueError:
        return False
    return (target.hostname, target.port, target.scheme) == (
        configured.hostname,
        configured.port,
        configured.scheme,
    )


# Warn at import time if Redmine config is missing or incomplete.
if not REDMINE_URL:
    logger.warning(
        "REDMINE_URL not set. "
        "Please create a .env file in your working directory with REDMINE_URL defined."
    )
elif REDMINE_AUTH_MODE not in {"oauth", "oauth-proxy", "legacy-per-user"} and not (
    REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)
):
    logger.warning(
        "No Redmine authentication configured. "
        "Please set REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD "
        "in your .env file, or set REDMINE_AUTH_MODE=oauth or oauth-proxy."
    )

if REDMINE_AUTH_MODE == "legacy-per-user" and REDMINE_API_KEY:
    logger.info(
        "legacy-per-user mode: ignoring REDMINE_API_KEY from env; per-request "
        "X-Redmine-API-Key headers are used instead."
    )


# Test-compatibility hook: existing unit tests patch this module-level variable
# directly. When non-None, _get_redmine_client() returns it immediately.
# In production this stays None and per-request auth is always used.
redmine: Optional[Redmine] = None

# Cached legacy-mode client — avoids recreating Redmine() on every tool call
# when running without OAuth.
#
# Tests patch this module attribute directly, so it stays the authoritative
# override: when it is not None it is returned as is. The automatic cache lives
# in a threading.local() instead, because tools now run in worker threads and
# a requests.Session is not documented as thread-safe (issue #216).
_legacy_client: Optional[Redmine] = None

_legacy_client_local = threading.local()


def _reset_legacy_client_cache() -> None:
    """Drop the per-thread cached legacy client.

    Used by the test suite so a test patching ``_legacy_client`` to None gets a
    freshly built client rather than one cached by an earlier test.
    """
    if hasattr(_legacy_client_local, "client"):
        del _legacy_client_local.client


def _build_legacy_client() -> Redmine:
    """Build a Redmine client using legacy credentials (API key or user/pass).

    Resolves REDMINE_URL / REDMINE_API_KEY / REDMINE_USERNAME / REDMINE_PASSWORD
    and the `Redmine` class via this module's attributes so tests patching
    ``_client.REDMINE_*`` / ``_client.Redmine`` are honored.
    """
    # Read attributes via globals() so tests using patch.object(_client, ...)
    # observe the override at call time.
    g = globals()
    if g["REDMINE_API_KEY"]:
        return _new_client(key=g["REDMINE_API_KEY"])
    elif g["REDMINE_USERNAME"] and g["REDMINE_PASSWORD"]:
        return _new_client(
            username=g["REDMINE_USERNAME"],
            password=g["REDMINE_PASSWORD"],
        )
    else:
        raise RuntimeError(
            "No Redmine authentication available. "
            "Set REDMINE_AUTH_MODE=oauth or oauth-proxy, or configure "
            "REDMINE_API_KEY / REDMINE_USERNAME+REDMINE_PASSWORD."
        )


# When true, _get_redmine_client() skips the event-loop check. Only for
# callers that are provably non-blocking or for tests exercising the client
# factory directly.
_loop_thread_allowed: ContextVar[bool] = ContextVar(
    "_loop_thread_allowed", default=False
)


@contextlib.contextmanager
def allow_loop_thread():
    """Temporarily permit _get_redmine_client() on the event loop thread."""
    token = _loop_thread_allowed.set(True)
    try:
        yield
    finally:
        _loop_thread_allowed.reset(token)


def _reject_event_loop_thread() -> None:
    """Fail loudly if a blocking client is being built on the event loop.

    python-redmine is synchronous, so every call made through this client
    blocks whichever thread it runs on. On the event loop that stalls every
    other request, including the /health probe (issue #216). Tools must go
    through ``@offloaded`` or ``in_thread()``; inside a worker thread there is
    no running loop, so this check is a no-op there.
    """
    if _loop_thread_allowed.get():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "_get_redmine_client() was called on the event loop thread. Blocking "
        "Redmine calls must run inside @offloaded or in_thread() so a hung "
        "server cannot stall other requests. See issue #216."
    )


def _get_redmine_client() -> Redmine:
    _reject_event_loop_thread()

    # Read this module's attributes via globals() so tests patching
    # `_client.redmine`, `_client._legacy_client`, and `_client.Redmine`
    # are observed at call time.
    g = globals()

    if g["redmine"] is not None:
        return g["redmine"]

    # OAuth mode: per-request bearer token from FastMCP's native auth.
    # get_access_token() returns None outside an authenticated request
    # (e.g., legacy mode, or background tasks).
    access_token = get_access_token()
    if access_token is not None and access_token.token:
        # Per-request client with Bearer token (cannot be cached)
        headers = {"Authorization": f"Bearer {access_token.token}"}
        return _new_client(requests={"headers": headers})

    # legacy-per-user mode: per-request key from the X-Redmine-API-Key header.
    if g["REDMINE_AUTH_MODE"] == "legacy-per-user":
        from ._per_user import maybe_log_identity, resolve_per_user_key

        try:
            request = get_http_request()
        except RuntimeError:
            request = None
        key = resolve_per_user_key(request)  # raises PerUserAuthError
        client = _new_client(key=key)
        maybe_log_identity(client, key)
        return client

    # Legacy mode: an explicitly set module attribute wins (tests patch it),
    # otherwise use the per-thread cache.
    if g["_legacy_client"] is not None:
        return g["_legacy_client"]

    client = getattr(_legacy_client_local, "client", None)
    if client is None:
        client = _build_legacy_client()
        _legacy_client_local.client = client
    return client
