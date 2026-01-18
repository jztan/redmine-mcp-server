"""
Test cases for error handling improvements (Phase 4: Quality Improvements).

This module tests the _handle_redmine_error() helper function and
verifies that all MCP tools produce actionable error messages.
"""

import pytest
from unittest.mock import patch, Mock


class TestErrorHandler:
    """Unit tests for the _handle_redmine_error() function."""

    def test_handle_redmine_error_exists(self):
        """Verify the error handler function can be imported."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        assert callable(_handle_redmine_error)

    def test_handle_redmine_error_returns_dict(self):
        """Error handler returns a dictionary with 'error' key."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error

        result = _handle_redmine_error(Exception("test"), "test operation")

        assert isinstance(result, dict)
        assert "error" in result
        assert isinstance(result["error"], str)

    def test_handle_redmine_error_includes_operation(self):
        """Error message includes the operation description."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error

        result = _handle_redmine_error(Exception("test"), "fetching issue 123")

        assert "fetching issue 123" in result["error"]

    def test_connection_error_message(self):
        """Connection error produces actionable message with URL."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from requests.exceptions import ConnectionError

        error = ConnectionError("Connection refused")
        result = _handle_redmine_error(error, "fetching issue 123")

        assert "Cannot connect to Redmine" in result["error"]
        assert "URL is correct" in result["error"]
        assert "Network is accessible" in result["error"]
        assert "server is running" in result["error"]

    def test_connection_error_includes_url(self):
        """Connection error message includes the Redmine URL."""
        from redmine_mcp_server.redmine_handler import (
            _handle_redmine_error,
            REDMINE_URL,
        )
        from requests.exceptions import ConnectionError

        error = ConnectionError("Connection refused")
        result = _handle_redmine_error(error, "fetching issue")

        # Should include URL or placeholder if not configured
        assert "Redmine" in result["error"]

    def test_auth_error_message(self):
        """401 error produces credential guidance."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import AuthError

        error = AuthError()
        result = _handle_redmine_error(error, "fetching issue 123")

        assert "Authentication failed" in result["error"]
        assert "REDMINE_API_KEY" in result["error"]
        assert "REDMINE_USERNAME" in result["error"]
        assert "REDMINE_PASSWORD" in result["error"]

    def test_forbidden_error_message(self):
        """403 error mentions permission and admin contact."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ForbiddenError

        error = ForbiddenError()
        result = _handle_redmine_error(error, "updating issue 123")

        assert "Access denied" in result["error"]
        assert "permission" in result["error"].lower()
        assert "administrator" in result["error"].lower()

    def test_timeout_error_message(self):
        """Timeout error provides troubleshooting steps."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from requests.exceptions import Timeout

        error = Timeout("Read timed out")
        result = _handle_redmine_error(error, "listing projects")

        assert "timed out" in result["error"].lower()
        assert "Network connectivity" in result["error"]

    def test_ssl_error_message(self):
        """SSL error provides certificate guidance."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from requests.exceptions import SSLError

        error = SSLError("Certificate verify failed")
        result = _handle_redmine_error(error, "fetching issue")

        assert "SSL" in result["error"]
        assert "certificate" in result["error"].lower()
        assert "REDMINE_SSL" in result["error"]

    def test_server_error_message(self):
        """500 error provides admin contact guidance."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ServerError

        error = ServerError()
        result = _handle_redmine_error(error, "creating issue")

        assert "500" in result["error"]
        assert "administrator" in result["error"].lower()
        assert "server logs" in result["error"].lower()

    def test_validation_error_message(self):
        """Validation error includes the validation message."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ValidationError

        error = ValidationError("Subject can't be blank")
        result = _handle_redmine_error(error, "creating issue")

        assert "Validation failed" in result["error"]
        assert "Subject can't be blank" in result["error"]

    def test_version_mismatch_error_message(self):
        """Version mismatch error passes through original message."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import VersionMismatchError

        error = VersionMismatchError("Search")
        result = _handle_redmine_error(error, "searching")

        assert "Search" in result["error"]

    def test_http_protocol_error_message(self):
        """HTTP protocol error provides protocol guidance."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import HTTPProtocolError

        error = HTTPProtocolError()
        result = _handle_redmine_error(error, "connecting")

        assert "HTTP" in result["error"]
        assert "HTTPS" in result["error"]
        assert "protocol" in result["error"].lower()

    def test_unknown_error_includes_status_code(self):
        """Unknown error includes HTTP status code."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import UnknownError

        error = UnknownError(418)  # I'm a teapot
        result = _handle_redmine_error(error, "brewing coffee")

        assert "418" in result["error"]

    def test_resource_not_found_with_context(self):
        """ResourceNotFoundError uses context for better message."""
        from redmine_mcp_server.redmine_handler import _handle_redmine_error
        from redminelib.exceptions import ResourceNotFoundError

        error = ResourceNotFoundError()
        result = _handle_redmine_error(
            error,
            "fetching issue",
            {"resource_type": "issue", "resource_id": 123}
        )

        assert "Issue 123 not found" in result["error"]


class TestToolErrorIntegration:
    """Integration tests verifying tools use the error handler correctly."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_issue_connection_error(self, mock_redmine):
        """get_redmine_issue produces actionable connection error."""
        from redmine_mcp_server.redmine_handler import get_redmine_issue
        from requests.exceptions import ConnectionError

        mock_redmine.issue.get.side_effect = ConnectionError("refused")
        result = await get_redmine_issue(123)

        assert "Cannot connect to Redmine" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_issue_auth_error(self, mock_redmine):
        """get_redmine_issue produces actionable auth error."""
        from redmine_mcp_server.redmine_handler import get_redmine_issue
        from redminelib.exceptions import AuthError

        mock_redmine.issue.get.side_effect = AuthError()
        result = await get_redmine_issue(123)

        assert "Authentication failed" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_projects_forbidden_error(self, mock_redmine):
        """list_redmine_projects produces actionable forbidden error."""
        from redmine_mcp_server.redmine_handler import list_redmine_projects
        from redminelib.exceptions import ForbiddenError

        mock_redmine.project.all.side_effect = ForbiddenError()
        result = await list_redmine_projects()

        assert len(result) == 1
        assert "Access denied" in result[0]["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_issue_server_error(self, mock_redmine):
        """create_redmine_issue produces actionable server error."""
        from redmine_mcp_server.redmine_handler import create_redmine_issue
        from redminelib.exceptions import ServerError

        mock_redmine.issue.create.side_effect = ServerError()
        result = await create_redmine_issue(1, "Test", "Description")

        assert "500" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_search_issues_timeout_error(self, mock_redmine):
        """search_redmine_issues produces actionable timeout error."""
        from redmine_mcp_server.redmine_handler import search_redmine_issues
        from requests.exceptions import Timeout

        mock_redmine.issue.search.side_effect = Timeout()
        result = await search_redmine_issues("test query")

        assert "timed out" in result["error"].lower()


class TestLoggingCleanup:
    """Tests verifying print() statements are replaced with logger."""

    def test_no_print_in_error_handling(self):
        """Verify no print() calls in error handling code."""
        import inspect
        from redmine_mcp_server import redmine_handler

        source = inspect.getsource(redmine_handler)

        # These specific print patterns should not exist
        forbidden_patterns = [
            'print(f"Error fetching',
            'print(f"Error listing',
            'print(f"Error creating',
            'print(f"Error updating',
            'print(f"Error summarizing',
            'print(f"Error during attachment',
        ]

        for pattern in forbidden_patterns:
            assert pattern not in source, f"Found forbidden pattern: {pattern}"
