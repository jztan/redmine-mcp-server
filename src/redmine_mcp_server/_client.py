"""Redmine client factory and connection-level config.

Owns:
  - Module-level REDMINE_URL / REDMINE_API_KEY / REDMINE_USERNAME /
    REDMINE_PASSWORD / REDMINE_AUTH_MODE / SSL config (read once from env).
  - The cached `_legacy_client` singleton and the `redmine` module-level var.
  - `_get_redmine_client()` -- the single entry point used by every MCP tool.

`current_redmine_token` (the OAuth ContextVar) lives in `oauth_middleware.py`
and is lazy-imported inside `_get_redmine_client()` to avoid circular import.

Note: `_get_redmine_client()` and `_build_legacy_client()` resolve module-level
config (REDMINE_API_KEY, REDMINE_USERNAME, etc.) and the `Redmine` class via
`redmine_mcp_server.redmine_handler` module attribute access. This preserves
back-compat with the large existing test suite that patches
`redmine_handler.REDMINE_API_KEY`, `redmine_handler.Redmine`, etc. through
`unittest.mock.patch`. The canonical values are defined here, and
`redmine_handler.py` re-imports them so both modules stay in sync at import
time; tests can monkey-patch the `redmine_handler` bindings to override at
runtime.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
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

# Auth mode: "oauth" uses per-request Bearer tokens via OAuth middleware;
# "legacy" uses REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD (default).
REDMINE_AUTH_MODE = os.getenv("REDMINE_AUTH_MODE", "legacy").lower()

# SSL Configuration (optional)
REDMINE_SSL_VERIFY = os.getenv("REDMINE_SSL_VERIFY", "true").lower() == "true"
REDMINE_SSL_CERT = os.getenv("REDMINE_SSL_CERT")
REDMINE_SSL_CLIENT_CERT = os.getenv("REDMINE_SSL_CLIENT_CERT")


# Build SSL requests config from environment (used by _get_redmine_client)
def _build_requests_config() -> dict:
    requests_config = {}
    if not REDMINE_SSL_VERIFY:
        requests_config["verify"] = False
        logger.warning("SSL verification is DISABLED - use only for development!")
    elif REDMINE_SSL_CERT:
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
        requests_config["verify"] = str(cert_path)
        logger.info(f"Using custom SSL certificate: {cert_path}")
    if REDMINE_SSL_CLIENT_CERT:
        if "," in REDMINE_SSL_CLIENT_CERT:
            cert, key = REDMINE_SSL_CLIENT_CERT.split(",", 1)
            requests_config["cert"] = (cert.strip(), key.strip())
            logger.info("Using client certificate for mutual TLS")
        else:
            requests_config["cert"] = REDMINE_SSL_CLIENT_CERT
            logger.info("Using client certificate for mutual TLS")
    return requests_config


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
    and the `Redmine` class via `redmine_handler` module attribute access so
    that existing tests patching `redmine_handler.REDMINE_*` and
    `redmine_handler.Redmine` continue to work.
    """
    from . import redmine_handler as _rh  # lazy: preserve test patches

    requests_config = _build_requests_config()
    if _rh.REDMINE_API_KEY:
        if requests_config:
            return _rh.Redmine(
                _rh.REDMINE_URL, key=_rh.REDMINE_API_KEY, requests=requests_config
            )
        return _rh.Redmine(_rh.REDMINE_URL, key=_rh.REDMINE_API_KEY)
    elif _rh.REDMINE_USERNAME and _rh.REDMINE_PASSWORD:
        if requests_config:
            return _rh.Redmine(
                _rh.REDMINE_URL,
                username=_rh.REDMINE_USERNAME,
                password=_rh.REDMINE_PASSWORD,
                requests=requests_config,
            )
        return _rh.Redmine(
            _rh.REDMINE_URL,
            username=_rh.REDMINE_USERNAME,
            password=_rh.REDMINE_PASSWORD,
        )
    else:
        raise RuntimeError(
            "No Redmine authentication available. "
            "Set REDMINE_AUTH_MODE=oauth or configure REDMINE_API_KEY / "
            "REDMINE_USERNAME+REDMINE_PASSWORD."
        )


def _get_redmine_client() -> Redmine:
    global _legacy_client

    # Lazy lookup through redmine_handler so tests patching
    # `redmine_handler.redmine`, `redmine_handler._legacy_client`, and
    # `redmine_handler.Redmine` are observed at call time.
    from . import redmine_handler as _rh

    if _rh.redmine is not None:
        return _rh.redmine

    from .oauth_middleware import current_redmine_token

    token = current_redmine_token.get()

    if token:
        # OAuth mode: per-request client with Bearer token (cannot be cached)
        requests_config = _build_requests_config()
        headers = {"Authorization": f"Bearer {token}"}
        if requests_config:
            return _rh.Redmine(
                _rh.REDMINE_URL,
                requests={"headers": headers, **requests_config},
            )
        return _rh.Redmine(_rh.REDMINE_URL, requests={"headers": headers})

    # Legacy mode: reuse a cached singleton.
    # Read/write the cache through `redmine_handler` so existing tests that do
    # `rh._legacy_client = None` to clear the cache are honored. Mirror onto
    # `_client._legacy_client` so back-compat re-imports stay consistent.
    if _rh._legacy_client is None:
        _rh._legacy_client = _build_legacy_client()
    _legacy_client = _rh._legacy_client
    return _rh._legacy_client
