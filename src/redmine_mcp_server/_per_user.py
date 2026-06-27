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

import logging
import re
from typing import Optional

logger = logging.getLogger("redmine_mcp_server")

HEADER_NAME = "X-Redmine-API-Key"

# Stock Redmine API keys are 40 hex chars; the wider bound tolerates custom
# setups without accepting arbitrary garbage.
_KEY_RE = re.compile(r"^[A-Za-z0-9]{20,128}$")


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


def _validate_key_format(key: Optional[str]) -> bool:
    return bool(_KEY_RE.match(key or ""))


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
