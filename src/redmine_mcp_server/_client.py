"""Redmine client factory and connection-level config.

Owns:
  - Module-level REDMINE_URL / REDMINE_API_KEY / REDMINE_USERNAME /
    REDMINE_PASSWORD / REDMINE_AUTH_MODE / SSL config (read once from env).
  - The cached `_legacy_client` singleton and the `redmine` module-level var.
  - `_get_redmine_client()` -- the single entry point used by every MCP tool.

`current_redmine_token` (the OAuth ContextVar) lives in `oauth_middleware.py`
and is lazy-imported inside `_get_redmine_client()` to avoid circular import.

Tests patch this module's attributes directly, e.g.
``patch("redmine_mcp_server._client.REDMINE_API_KEY", "...")`` or
``patch("redmine_mcp_server._client.Redmine")``.
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


# Warn at import time if Redmine config is missing or incomplete.
if not REDMINE_URL:
    logger.warning(
        "REDMINE_URL not set. "
        "Please create a .env file in your working directory with REDMINE_URL defined."
    )
elif REDMINE_AUTH_MODE != "oauth" and not (
    REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)
):
    logger.warning(
        "No Redmine authentication configured. "
        "Please set REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD "
        "in your .env file, or set REDMINE_AUTH_MODE=oauth."
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
            "Set REDMINE_AUTH_MODE=oauth or configure REDMINE_API_KEY / "
            "REDMINE_USERNAME+REDMINE_PASSWORD."
        )


def _get_redmine_client() -> Redmine:
    global _legacy_client

    # Read this module's attributes via globals() so tests patching
    # `_client.redmine`, `_client._legacy_client`, and `_client.Redmine`
    # are observed at call time.
    g = globals()

    if g["redmine"] is not None:
        return g["redmine"]

    from .oauth_middleware import current_redmine_token

    token = current_redmine_token.get()

    if token:
        # OAuth mode: per-request client with Bearer token (cannot be cached)
        requests_config = _build_requests_config()
        headers = {"Authorization": f"Bearer {token}"}
        if requests_config:
            return g["Redmine"](
                g["REDMINE_URL"],
                requests={"headers": headers, **requests_config},
            )
        return g["Redmine"](g["REDMINE_URL"], requests={"headers": headers})

    # Legacy mode: reuse a cached singleton.
    if g["_legacy_client"] is None:
        g["_legacy_client"] = _build_legacy_client()
    _legacy_client = g["_legacy_client"]
    return g["_legacy_client"]
