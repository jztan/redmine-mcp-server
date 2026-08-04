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

import logging
import os
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp.server.dependencies import get_access_token, get_http_request
from redminelib import Redmine

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
_legacy_client: Optional[Redmine] = None


def _build_legacy_client() -> Redmine:
    """Build a Redmine client using legacy credentials (API key or user/pass).

    Resolves REDMINE_URL / REDMINE_API_KEY / REDMINE_USERNAME / REDMINE_PASSWORD
    and the `Redmine` class via this module's attributes so tests patching
    ``_client.REDMINE_*`` / ``_client.Redmine`` are honored.
    """
    # Read attributes via globals() so tests using patch.object(_client, ...)
    # observe the override at call time.
    g = globals()
    requests_config = _build_requests_config()
    if g["REDMINE_API_KEY"]:
        if requests_config:
            return g["Redmine"](
                g["REDMINE_URL"],
                key=g["REDMINE_API_KEY"],
                requests=requests_config,
            )
        return g["Redmine"](g["REDMINE_URL"], key=g["REDMINE_API_KEY"])
    elif g["REDMINE_USERNAME"] and g["REDMINE_PASSWORD"]:
        if requests_config:
            return g["Redmine"](
                g["REDMINE_URL"],
                username=g["REDMINE_USERNAME"],
                password=g["REDMINE_PASSWORD"],
                requests=requests_config,
            )
        return g["Redmine"](
            g["REDMINE_URL"],
            username=g["REDMINE_USERNAME"],
            password=g["REDMINE_PASSWORD"],
        )
    else:
        raise RuntimeError(
            "No Redmine authentication available. "
            "Set REDMINE_AUTH_MODE=oauth or oauth-proxy, or configure "
            "REDMINE_API_KEY / REDMINE_USERNAME+REDMINE_PASSWORD."
        )


def _get_redmine_client() -> Redmine:
    global _legacy_client

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
        requests_config = _build_requests_config()
        headers = {"Authorization": f"Bearer {access_token.token}"}
        if requests_config:
            return g["Redmine"](
                g["REDMINE_URL"],
                requests={"headers": headers, **requests_config},
            )
        return g["Redmine"](g["REDMINE_URL"], requests={"headers": headers})

    # legacy-per-user mode: per-request key from the X-Redmine-API-Key header.
    if g["REDMINE_AUTH_MODE"] == "legacy-per-user":
        from ._per_user import maybe_log_identity, resolve_per_user_key

        try:
            request = get_http_request()
        except RuntimeError:
            request = None
        key = resolve_per_user_key(request)  # raises PerUserAuthError
        requests_config = _build_requests_config()
        if requests_config:
            client = g["Redmine"](g["REDMINE_URL"], key=key, requests=requests_config)
        else:
            client = g["Redmine"](g["REDMINE_URL"], key=key)
        maybe_log_identity(client, key)
        return client

    # Legacy mode: reuse a cached singleton.
    if g["_legacy_client"] is None:
        g["_legacy_client"] = _build_legacy_client()
    _legacy_client = g["_legacy_client"]
    return g["_legacy_client"]
