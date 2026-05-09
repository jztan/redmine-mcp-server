"""Error handling: redminelib exception → user-friendly dict translation."""

import logging
import re
from typing import Any, Dict, Optional

from redminelib.exceptions import (
    AuthError,
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
    SSLError as RequestsSSLError,
    Timeout as RequestsTimeout,
)

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


def _handle_redmine_error(
    e: Exception, operation: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert exceptions to user-friendly error messages with actionable guidance.
    """
    from . import _client  # lazy import to avoid circular

    context = context or {}
    redmine_url = _client.REDMINE_URL or "REDMINE_URL not configured"

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

    if isinstance(e, RequestsTimeout):
        logger.error(f"Timeout during {operation}: {e}")
        return {
            "error": (
                f"Connection to Redmine at {redmine_url} timed out. "
                "Please check: 1) Network connectivity, 2) Redmine server load"
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
