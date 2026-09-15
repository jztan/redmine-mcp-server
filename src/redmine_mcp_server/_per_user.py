"""Per-user legacy auth: resolve a per-request Redmine API key from the
``X-Redmine-API-Key`` HTTP header.

Active only when ``REDMINE_AUTH_MODE=legacy-per-user``. The app never
terminates TLS itself, so it cannot verify transport security; safety is
operator-attested via ``REDMINE_PER_USER_TRUST_PROXY`` (enforced at startup,
see ``assert_startup_attestation``). At request time the only transport check
is a cheap misconfig catch: reject when ``X-Forwarded-Proto`` is present and
equals ``http``.

The raw key value is NEVER logged. Log lines use ``_fingerprint()``.
"""

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Optional

import requests

logger = logging.getLogger("redmine_mcp_server")

HEADER_NAME = "X-Redmine-API-Key"

# Stock Redmine API keys are 40 hex chars; the wider bound tolerates custom
# setups without accepting arbitrary garbage.
# fullmatch anchors implicitly; no ^/$ needed, and avoids the Python $-before-\n
# pitfall where "$" matches before a trailing newline.
_KEY_RE = re.compile(r"[A-Za-z0-9]{20,128}")


class PerUserAuthError(Exception):
    """Raised when a per-user API key cannot be resolved from the request."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _fingerprint(key: str) -> str:
    """Return a redaction-safe identifier for log lines (never the key)."""
    if not key:
        return "...(empty)"
    return "..." + key[-4:]


def _validate_key_format(key: str) -> bool:
    return bool(_KEY_RE.fullmatch(key))


def _extract_key(request) -> Optional[str]:
    """Read the per-user key header, case-insensitive, with an ASGI-scope
    byte-header fallback for request objects whose ``.headers`` lacks ``.get``.
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        getter = getattr(headers, "get", None)
        if callable(getter):
            value = getter(HEADER_NAME)
            if value is None:
                value = getter(HEADER_NAME.lower())
            if value is not None:
                return value
    scope = getattr(request, "scope", None)
    if scope and "headers" in scope:
        target = HEADER_NAME.lower()
        for raw_k, raw_v in scope["headers"]:
            k = raw_k.decode() if isinstance(raw_k, (bytes, bytearray)) else raw_k
            if k.lower() == target:
                return (
                    raw_v.decode() if isinstance(raw_v, (bytes, bytearray)) else raw_v
                )
    return None


def _reject_insecure_transport(request) -> None:
    """Raise if the request demonstrably arrived over plaintext.

    Only a misconfig catch: rejects when ``X-Forwarded-Proto`` is present and
    equals ``http``. Does not attempt to PROVE TLS (impossible here).
    """
    proto = None
    headers = getattr(request, "headers", None)
    if headers is not None and callable(getattr(headers, "get", None)):
        proto = headers.get("X-Forwarded-Proto") or headers.get("x-forwarded-proto")
    if proto is not None and str(proto).strip().lower() == "http":
        raise PerUserAuthError(
            "Per-user auth refused: request arrived over insecure transport "
            "(X-Forwarded-Proto: http). Ensure TLS terminates at your proxy."
        )


def resolve_per_user_key(request) -> str:
    """Return a validated per-user API key or raise PerUserAuthError."""
    if request is None:
        raise PerUserAuthError(
            "Per-user auth requires an HTTP request context but none was found."
        )
    _reject_insecure_transport(request)
    key = _extract_key(request)
    if key is None:
        raise PerUserAuthError(f"Per-user auth: missing {HEADER_NAME} request header.")
    if not _validate_key_format(key):
        raise PerUserAuthError("Per-user auth received a malformed API key.")
    logger.info("per-user key resolved fingerprint=%s", _fingerprint(key))
    return key


# Key validation against Redmine (issue #290). Redmine serves an unknown or
# reset key as the anonymous user on any endpoint anonymous may read, so the
# format check above cannot tell a wrong key from a right one. Each distinct
# key is checked once with GET /users/current.json, which answers 401 for a
# key Redmine does not recognise.
#
# Accepted window: a key reset while its "valid" entry is cached keeps running
# as anonymous until the entry expires (_KEY_VALID_TTL).
_KEY_VALID_TTL = 300.0
_KEY_REJECTED_TTL = 60.0
# Keys arrive in request headers, so the cache is bounded: an unbounded dict
# would let a caller grow memory by sending endless distinct keys.
_KEY_CACHE_MAX = 1024

# digest -> (accepted, expires_at). Keyed by a SHA-256 digest, never the raw
# key; _fingerprint() is only the last 4 chars and would collide.
_key_cache: "OrderedDict[str, tuple[bool, float]]" = OrderedDict()
_key_cache_lock = threading.Lock()


def _clear_key_cache() -> None:
    with _key_cache_lock:
        _key_cache.clear()


def _cache_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _probe_key(key: str) -> int:
    """GET /users/current.json with ``key`` and return the HTTP status.

    The key goes in the X-Redmine-API-Key header only (never Basic auth or the
    query string), with the same TLS/proxy settings and timeout as the Redmine
    client. Redirects are not followed, so the header never leaves for another
    host. Transport errors propagate to the caller.
    """
    from . import _client
    from ._env import get_redmine_timeout

    url = _client.REDMINE_URL.rstrip("/") + "/users/current.json"
    with requests.Session() as session:
        for name, value in _client._build_requests_config().items():
            setattr(session, name, value)
        response = session.get(
            url,
            headers={HEADER_NAME: key},
            timeout=get_redmine_timeout(),
            allow_redirects=False,
        )
        return response.status_code


def validate_key_with_redmine(key: str) -> None:
    """Raise PerUserAuthError if Redmine rejects ``key`` with 401.

    Only 401 rejects. Any other status (403 when the REST API is disabled,
    5xx, redirects) and any transport error let the request through unchanged
    and are not cached, so a Redmine outage never reads as "your key is
    wrong". Runs in the tool's worker thread; the HTTP call is made outside
    the cache lock so one slow response cannot stall other users.
    """
    from . import _client

    if not _client.REDMINE_URL:
        return

    digest = _cache_key(key)
    now = time.monotonic()
    with _key_cache_lock:
        entry = _key_cache.get(digest)
        if entry is not None and entry[1] <= now:
            del _key_cache[digest]
            entry = None
    if entry is not None:
        accepted = entry[0]
        logger.debug(
            "per-user key validation cached fingerprint=%s accepted=%s",
            _fingerprint(key),
            accepted,
        )
    else:
        try:
            status = _probe_key(key)
        except Exception as exc:
            logger.warning(
                "per-user key validation skipped for fingerprint=%s: "
                "Redmine unreachable (%s)",
                _fingerprint(key),
                type(exc).__name__,
            )
            return
        if status == 401:
            accepted = False
        elif 200 <= status < 300:
            accepted = True
        else:
            logger.warning(
                "per-user key validation inconclusive for fingerprint=%s: "
                "GET /users/current.json returned HTTP %s",
                _fingerprint(key),
                status,
            )
            return
        ttl = _KEY_VALID_TTL if accepted else _KEY_REJECTED_TTL
        with _key_cache_lock:
            _key_cache[digest] = (accepted, time.monotonic() + ttl)
            _key_cache.move_to_end(digest)
            while len(_key_cache) > _KEY_CACHE_MAX:
                _key_cache.popitem(last=False)
        logger.debug(
            "per-user key validated fingerprint=%s accepted=%s",
            _fingerprint(key),
            accepted,
        )

    if not accepted:
        logger.warning(
            "per-user key rejected by Redmine fingerprint=%s", _fingerprint(key)
        )
        raise PerUserAuthError(
            "Redmine did not accept this API key (fingerprint "
            f"{_fingerprint(key)}). Check the {HEADER_NAME} header: the key may "
            "be mistyped, or it was reset in Redmine under My account."
        )


def maybe_log_identity(client, key: str) -> None:
    """Opt-in audit: resolve and log the Redmine user id for this request.

    Enabled by REDMINE_PER_USER_AUDIT_IDENTITY=true (off by default). Adds one
    GET /users/current.json round-trip. Never raises and never logs the key.
    """
    from ._env import _is_true_env

    if not _is_true_env("REDMINE_PER_USER_AUDIT_IDENTITY"):
        return
    try:
        user = client.user.get("current")
        logger.info(
            "per-user audit: fingerprint=%s redmine_user_id=%s",
            _fingerprint(key),
            getattr(user, "id", "unknown"),
        )
    except Exception as exc:  # audit must never break the request
        logger.warning(
            "per-user audit: could not resolve identity for fingerprint=%s (%s)",
            _fingerprint(key),
            type(exc).__name__,
        )


def assert_startup_attestation() -> None:
    """Fail closed unless the operator attests the server sits behind TLS.

    Called once at app build time when REDMINE_AUTH_MODE=legacy-per-user.
    """
    from ._env import _is_true_env

    if not _is_true_env("REDMINE_PER_USER_TRUST_PROXY"):
        raise RuntimeError(
            "REDMINE_AUTH_MODE=legacy-per-user requires "
            "REDMINE_PER_USER_TRUST_PROXY=true. This attests that the server "
            "sits behind a TLS-terminating proxy and that the proxy does not "
            "forward client-supplied X-Forwarded-Proto. The server cannot "
            "verify TLS itself."
        )
    logger.warning(
        "legacy-per-user auth is ACTIVE: per-user Redmine API keys travel in "
        "the X-Redmine-API-Key request header. Ensure end-to-end TLS, firewall "
        "the app port, keep headers out of upstream logs, and prefer dedicated "
        "limited-permission Redmine accounts."
    )
