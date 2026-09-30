"""Every branch of _handle_redmine_error returns a machine-readable code."""

from unittest.mock import patch

import pytest
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
    ConnectTimeout,
    ReadTimeout,
    SSLError,
)
from urllib3.exceptions import ReadTimeoutError

from redmine_mcp_server._errors import _READ_ONLY_ERROR, _handle_redmine_error


def _streaming_read_timeout():
    # What requests' iter_content() raises for a stalled download (#214).
    return RequestsConnectionError(ReadTimeoutError(None, "/", "read timed out"))


@pytest.mark.parametrize(
    "exc,code",
    [
        (SSLError("bad cert"), "SSL_ERROR"),
        (ConnectTimeout("connect timed out"), "TIMEOUT"),
        (ReadTimeout("read timed out"), "TIMEOUT"),
        (_streaming_read_timeout(), "TIMEOUT"),
        (RequestsConnectionError("refused"), "CONNECTION_FAILED"),
        (AuthError(), "AUTH_FAILED"),
        (ForbiddenError(), "FORBIDDEN"),
        (ServerError(), "SERVER_ERROR"),
        (UnknownError(502), "SERVER_ERROR"),
        (UnknownError(503), "SERVER_ERROR"),
        (UnknownError(418), "UNKNOWN_ERROR"),
        (ResourceNotFoundError(), "NOT_FOUND"),
        (ValidationError("Subject cannot be blank"), "VALIDATION_FAILED"),
        (ConflictError(), "CONFLICT"),
        (VersionMismatchError("Checklists"), "VERSION_MISMATCH"),
        (HTTPProtocolError(), "PROTOCOL_MISMATCH"),
        (RuntimeError("anything else"), "UNKNOWN_ERROR"),
    ],
)
def test_each_branch_returns_a_code(exc, code):
    result = _handle_redmine_error(exc, "testing")
    assert result["code"] == code
    assert result["error"]


def test_not_found_with_resource_id_has_a_code():
    result = _handle_redmine_error(
        ResourceNotFoundError(),
        "fetching issue",
        {"resource_type": "issue", "resource_id": 7},
    )
    assert result == {"error": "Issue 7 not found.", "code": "NOT_FOUND"}


def test_api_key_login_auth_failure_keeps_its_code():
    from redmine_mcp_server import _client

    with patch.object(_client, "REDMINE_AUTH_MODE", "api-key-login"):
        result = _handle_redmine_error(AuthError(), "testing")
    assert result["code"] == "AUTH_FAILED"


def test_read_only_error_has_a_code():
    assert _READ_ONLY_ERROR["code"] == "READ_ONLY"
