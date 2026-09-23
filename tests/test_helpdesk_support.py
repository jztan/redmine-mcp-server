"""Unit tests for RedmineUP Helpdesk plugin support (#301)."""

import json
import os
import sys

import pytest
from unittest.mock import patch
from redminelib.exceptions import ResourceNotFoundError, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._env import _is_helpdesk_enabled  # noqa: E402
from redmine_mcp_server.tools.helpdesk import send_helpdesk_email_reply  # noqa: E402

# The JSON response a Helpdesk 4.2.9 / Redmine 6.1.2 install returned for
# POST /helpdesk/email_note.json (reported in #301, personal data replaced).
_SUCCESS_RESPONSE = {
    "message": {
        "journal_id": 164214,
        "content": "MCP test - please ignore",
        "to_address": "customer@example.com",
        "message_date": "2026/09/16",
        "customer": {"id": 50, "name": "Jane Doe"},
    }
}

_ON = {"REDMINE_HELPDESK_ENABLED": "true", "REDMINE_MCP_READ_ONLY": "false"}


class TestIsHelpdeskEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_HELPDESK_ENABLED", None)
            assert _is_helpdesk_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_HELPDESK_ENABLED": "true"}):
            assert _is_helpdesk_enabled() is True


class TestSendHelpdeskEmailReply:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_posts_json_message_and_maps_response(self, mock_redmine):
        mock_redmine.engine.request.return_value = _SUCCESS_RESPONSE
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(
                issue_id=42, content="Thanks, fixed now."
            )

        args, kwargs = mock_redmine.engine.request.call_args
        assert args == ("post", "http://localhost:3000/helpdesk/email_note.json")
        assert kwargs["headers"] == {"Content-Type": "application/json"}
        assert json.loads(kwargs["data"]) == {
            "message": {"issue_id": 42, "content": "Thanks, fixed now."}
        }

        assert result["success"] is True
        assert result["issue_id"] == 42
        assert result["journal_id"] == 164214
        assert result["to_address"] == "customer@example.com"
        assert result["message_date"] == "2026/09/16"
        assert result["customer"]["id"] == 50
        # The customer name is user-controlled, so it is boundary-wrapped.
        assert "Jane Doe" in result["customer"]["name"]
        assert result["customer"]["name"] != "Jane Doe"
        assert result["status_id"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_status_id_is_forwarded(self, mock_redmine):
        mock_redmine.engine.request.return_value = _SUCCESS_RESPONSE
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(
                issue_id=42, content="Waiting on you.", status_id=4
            )
        sent = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert sent["message"]["status_id"] == 4
        assert result["status_id"] == 4

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tolerates_response_without_message(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(issue_id=42, content="Hi")
        assert result["success"] is True
        assert result["journal_id"] is None
        assert result["customer"] is None

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_unknown_issue_surfaces_validation_error(self, mock_redmine):
        # Helpdesk answers 422 with the message below for a missing issue;
        # python-redmine raises it as a ValidationError.
        mock_redmine.engine.request.side_effect = ValidationError(
            "Couldn't find Issue with 'id'=\"999999999\""
        )
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(issue_id=999999999, content="Hi")
        assert "error" in result
        assert "999999999" in json.dumps(result)

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_issue_without_customer_is_named_as_not_a_ticket(self, mock_redmine):
        # Also a 422, told apart from the unknown issue only by its wording.
        mock_redmine.engine.request.side_effect = ValidationError(
            "Issue with ID: 307 should be present and relate to customer"
        )
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(issue_id=307, content="Hi")
        assert "not a Helpdesk ticket" in result["error"]
        assert "update_redmine_issue" in result["error"]
        assert "relate to customer" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_missing_endpoint_is_not_reported_as_missing_issue(
        self, mock_redmine
    ):
        # Without the plugin Redmine answers 404, which must not read as
        # "issue not found" when the issue exists.
        mock_redmine.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(issue_id=307, content="Hi")
        assert "Helpdesk plugin" in result["error"]
        assert "307" not in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_blocked_in_read_only(self, mock_redmine):
        with patch.dict(os.environ, {**_ON, "REDMINE_MCP_READ_ONLY": "true"}):
            result = await send_helpdesk_email_reply(issue_id=42, content="Hi")
        assert "error" in result
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_disabled_when_flag_off(self, mock_redmine):
        with patch.dict(os.environ, {**_ON, "REDMINE_HELPDESK_ENABLED": "false"}):
            result = await send_helpdesk_email_reply(issue_id=42, content="Hi")
        assert "REDMINE_HELPDESK_ENABLED" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"issue_id": 0, "content": "Hi"}, "issue_id"),
            ({"issue_id": True, "content": "Hi"}, "issue_id"),
            ({"issue_id": 42, "content": "   "}, "content"),
            ({"issue_id": 42, "content": ""}, "content"),
            ({"issue_id": 42, "content": "Hi", "status_id": -1}, "status_id"),
        ],
    )
    @patch("redmine_mcp_server._client.redmine")
    async def test_rejects_invalid_arguments(self, mock_redmine, kwargs, message):
        with patch.dict(os.environ, _ON):
            result = await send_helpdesk_email_reply(**kwargs)
        assert message in result["error"]
        mock_redmine.engine.request.assert_not_called()
