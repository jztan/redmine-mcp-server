"""Error handling: redminelib exception → user-friendly dict translation."""

import logging
import re
from typing import Any, Dict, Optional

from redminelib.exceptions import (
    AuthError,
    ConflictError,
    ForbiddenError,
    HTTPProtocolError,
    ResourceNotFoundError,
    ServerError,
    UnknownError,
    ValidationError,
    VersionMismatchError,
)
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ConnectTimeout as RequestsConnectTimeout,
    SSLError as RequestsSSLError,
    Timeout as RequestsTimeout,
)
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError

logger = logging.getLogger("redmine_mcp_server")


# Patterns for secrets that must never appear in returned error messages.
# Logs still see the raw message, but API responses get the redacted version.
_SECRET_SCRUB_PATTERNS = [
    # Redmine REST API key in URL query string: ?key=..., &key=...
    (re.compile(r"([?&]key=)[^&\s\"']+", re.IGNORECASE), r"\1[redacted]"),
    # X-Redmine-API-Key header values
    (re.compile(r"(X-Redmine-API-Key:\s*)\S+", re.IGNORECASE), r"\1[redacted]"),
    # Bearer tokens in Authorization headers or anywhere else
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1[redacted]"),
    # HTTP basic auth embedded in URL: https://user:pass@host
    (re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@"), r"\1[redacted]@"),
    # Authorization: Basic <base64> header (username/password auth mode)
    (
        re.compile(r"(Authorization:\s*Basic\s+)[A-Za-z0-9+/=]+", re.IGNORECASE),
        r"\1[redacted]",
    ),
]


_READ_ONLY_ERROR = {
    "error": "This server is in read-only mode (REDMINE_MCP_READ_ONLY=true). "
    "Write operations are disabled."
}


def _scrub_error_message(message: str) -> str:
    """Redact common secret patterns from an error message.

    Removes API keys, Bearer tokens, and basic-auth credentials that may
    appear when an exception stringifies a URL. Used before any error
    detail is returned to an MCP caller.
    """
    if not message:
        return message
    scrubbed = message
    for pattern, replacement in _SECRET_SCRUB_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    # Also redact the configured API key if it happens to appear verbatim.
    from . import _client  # lazy import to avoid circular

    redmine_api_key = _client.REDMINE_API_KEY
    if redmine_api_key and redmine_api_key in scrubbed:
        scrubbed = scrubbed.replace(redmine_api_key, "[redacted]")
    return scrubbed


def _timeout_budget_hint() -> str:
    """Describe the configured timeout for inclusion in an error message."""
    from ._env import get_redmine_timeout  # lazy import avoids circular

    timeout = get_redmine_timeout()
    if timeout is None:
        return "REDMINE_TIMEOUT is disabled"
    connect, read = timeout
    return f"REDMINE_TIMEOUT: connect {connect:g}s, read {read:g}s"


def _read_timeout_error(redmine_url: str) -> Dict[str, Any]:
    """Build the "did not respond in time" error dict for a read timeout."""
    return {
        "error": (
            f"Redmine at {redmine_url} did not respond in time "
            f"({_timeout_budget_hint()}). The server may be overloaded or "
            "the request too large. Raise or disable the limit with "
            "REDMINE_TIMEOUT."
        )
    }


def _handle_redmine_error(
    e: Exception, operation: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert exceptions to user-friendly error messages with actionable guidance.
    """
    from . import _client  # lazy import to avoid circular

    context = context or {}
    redmine_url = _client.REDMINE_URL or "REDMINE_URL not configured"

    from ._per_user import PerUserAuthError  # lazy import avoids circular

    if isinstance(e, PerUserAuthError):
        return {"error": e.message, "code": "PER_USER_AUTH"}

    # Check SSLError BEFORE ConnectionError (SSLError inherits from ConnectionError)
    if isinstance(e, RequestsSSLError):
        logger.error(f"SSL error during {operation}: {e}")
        return {
            "error": (
                f"SSL/TLS error connecting to {redmine_url}. "
                "Please check: 1) SSL certificate validity, "
                "2) REDMINE_SSL_VERIFY setting, 3) REDMINE_SSL_CERT path"
            )
        }

    # Check Timeout BEFORE ConnectionError: ConnectTimeout inherits from both,
    # so the ConnectionError branch would otherwise swallow it and blame the
    # URL when the real cause is a server that stopped answering (#214).
    if isinstance(e, RequestsTimeout):
        logger.error(f"Timeout during {operation}: {e}")
        if isinstance(e, RequestsConnectTimeout):
            return {
                "error": (
                    f"Timed out connecting to Redmine at {redmine_url} "
                    f"({_timeout_budget_hint()}). Please check: "
                    "1) The host and port are reachable, "
                    "2) No firewall or proxy is dropping the connection"
                )
            }
        return _read_timeout_error(redmine_url)

    # A stalled streaming download (e.g. get_redmine_attachment) does NOT
    # raise ReadTimeout: requests' iter_content() catches urllib3's
    # ReadTimeoutError and re-raises it wrapped in a plain ConnectionError
    # (see requests/models.py). Left unhandled, that would fall into the
    # ConnectionError branch below and blame the URL for a server that
    # started answering and then went silent mid-body (#214). Detect the
    # wrapped urllib3 timeout here so it gets the read-timeout message
    # instead. A genuine ConnectionError (refused, DNS failure) has no such
    # wrapped cause and still falls through unchanged.
    if (
        isinstance(e, RequestsConnectionError)
        and e.args
        and isinstance(e.args[0], Urllib3TimeoutError)
    ):
        logger.error(f"Streaming read timeout during {operation}: {e}")
        return _read_timeout_error(redmine_url)

    # Connection-level errors (from requests library)
    if isinstance(e, RequestsConnectionError):
        logger.error(f"Connection error during {operation}: {e}")
        return {
            "error": (
                f"Cannot connect to Redmine at {redmine_url}. "
                "Please check: 1) URL is correct, 2) Network is accessible, "
                "3) Redmine server is running"
            )
        }

    # HTTP-level errors (from redminelib)
    if isinstance(e, AuthError):
        logger.error(f"Authentication failed during {operation}")
        return {
            "error": (
                "Authentication failed. Please check your credentials: "
                "1) REDMINE_API_KEY is valid, or "
                "2) REDMINE_USERNAME and REDMINE_PASSWORD are correct"
            )
        }

    if isinstance(e, ForbiddenError):
        logger.error(f"Access denied during {operation}")
        return {
            "error": (
                "Access denied. Your Redmine user lacks the required permission "
                "for this action. Contact your Redmine administrator."
            )
        }

    if isinstance(e, ServerError):
        logger.error(f"Redmine server error during {operation}: {e}")
        return {
            "error": (
                "Redmine server returned an internal error (HTTP 500). "
                "Check the Redmine server logs or contact your administrator."
            )
        }

    if isinstance(e, ResourceNotFoundError):
        resource_type = context.get("resource_type", "resource")
        resource_id = context.get("resource_id", "")
        if resource_id:
            return {"error": f"{resource_type.capitalize()} {resource_id} not found."}
        return {"error": f"Requested {resource_type} not found."}

    if isinstance(e, ValidationError):
        logger.warning(f"Validation error during {operation}: {e}")
        return {"error": f"Validation failed: {_scrub_error_message(str(e))}"}

    if isinstance(e, ConflictError):
        resource_type = context.get("resource_type", "resource")
        logger.warning(f"Edit conflict during {operation}: {e}")
        return {
            "error": (
                f"Edit conflict: this {resource_type} changed on the server "
                "since it was read. Re-read it and retry."
            )
        }

    if isinstance(e, VersionMismatchError):
        return {"error": _scrub_error_message(str(e))}

    if isinstance(e, HTTPProtocolError):
        logger.error(f"HTTP protocol error during {operation}: {e}")
        return {
            "error": (
                "HTTP/HTTPS protocol mismatch. Ensure REDMINE_URL uses the correct "
                "protocol (http:// or https://) matching your server configuration."
            )
        }

    if isinstance(e, UnknownError):
        logger.error(f"Unknown HTTP error during {operation}: status={e.status_code}")
        return {"error": f"Redmine returned HTTP {e.status_code}. Check server logs."}

    # Fallback — scrub the raw message before returning it to the caller.
    logger.error(f"Unexpected error during {operation}: {type(e).__name__}: {e}")
    return {
        "error": (
            f"An unexpected error occurred while {operation}: "
            f"{_scrub_error_message(str(e))}"
        )
    }
