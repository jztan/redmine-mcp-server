"""Unit tests for manage_crm_note (RedmineUP CRM notes on contacts and deals)."""

import json
import os
import sys
from unittest.mock import patch

import pytest
from redminelib.exceptions import (
    ForbiddenError,
    ResourceNotFoundError,
    ValidationError,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.crm_notes import (  # noqa: E402
    _is_crm_notes_enabled,
    _note_timestamp,
    _note_to_dict,
    _source_gate,
    manage_crm_note,
)

CRM_ON = {"REDMINE_CRM_ENABLED": "true", "REDMINE_DEALS_ENABLED": "false"}
DEALS_ON = {"REDMINE_CRM_ENABLED": "false", "REDMINE_DEALS_ENABLED": "true"}
BOTH_ON = {"REDMINE_CRM_ENABLED": "true", "REDMINE_DEALS_ENABLED": "true"}
BOTH_OFF = {"REDMINE_CRM_ENABLED": "false", "REDMINE_DEALS_ENABLED": "false"}
RFC822 = "Tue, 25 Aug 2026 11:32:23 +0000"


def _note(note_id=2, source_type="Deal", type_id=1):
    """Shaped like the plugin's app/views/notes/show.api.rsb."""
    return {
        "id": note_id,
        "source": {"id": 5, "name": "note probe", "type": source_type},
        "subject": "call",
        "content": "called them",
        "type_id": type_id,
        "author": {"id": 5, "name": "Sam Ruiz"},
        "created_on": RFC822,
        "updated_on": RFC822,
    }


class TestGating:
    @pytest.mark.parametrize(
        "env,expected",
        [(CRM_ON, True), (DEALS_ON, True), (BOTH_ON, True), (BOTH_OFF, False)],
    )
    def test_enabled_when_either_flag_on(self, env, expected):
        with patch.dict(os.environ, env):
            assert _is_crm_notes_enabled() is expected

    def test_deal_source_needs_deals_flag(self):
        with patch.dict(os.environ, CRM_ON):
            assert "REDMINE_DEALS_ENABLED" in _source_gate("deal")["error"]
            assert _source_gate("contact") is None

    def test_contact_source_needs_crm_flag(self):
        with patch.dict(os.environ, DEALS_ON):
            assert "REDMINE_CRM_ENABLED" in _source_gate("contact")["error"]
            assert _source_gate("deal") is None

    def test_unknown_source_is_error(self):
        with patch.dict(os.environ, BOTH_ON):
            assert "source_type" in _source_gate("issue")["error"]


class TestSerializer:
    def test_rfc822_timestamp_becomes_iso(self):
        assert _note_timestamp(RFC822) == "2026-08-25T11:32:23+00:00"

    def test_unparseable_timestamp_passes_through(self):
        assert _note_timestamp("not a date") == "not a date"
        assert _note_timestamp(None) is None

    def test_note_to_dict(self):
        d = _note_to_dict(_note())
        assert d["id"] == 2
        assert d["source"] == {"id": 5, "name": "note probe", "type": "deal"}
        assert d["subject"] == "call"
        assert "called them" in d["content"] and "<insecure-content-" in d["content"]
        assert d["type_id"] == 1 and d["note_type"] == "call"
        assert d["author"] == {"id": 5, "name": "Sam Ruiz"}
        assert d["created_on"] == "2026-08-25T11:32:23+00:00"

    def test_missing_type_and_source(self):
        d = _note_to_dict({"id": 1, "content": "x"})
        assert d["note_type"] is None and d["source"] is None
        assert d["author"] is None


from redmine_mcp_server.oauth_scopes import (  # noqa: E402
    READ_SCOPES,
    WRITE_SCOPES,
    advertised_scopes,
)

NOTE_WRITE_SCOPES = {"add_notes", "delete_notes", "delete_own_notes"}


class TestScopes:
    @pytest.mark.parametrize("env", [CRM_ON, DEALS_ON, BOTH_ON])
    def test_note_write_scopes_advertised_when_any_flag_on(self, env):
        with patch.dict(os.environ, {**env, "REDMINE_MCP_READ_ONLY": "false"}):
            assert NOTE_WRITE_SCOPES <= set(advertised_scopes())

    def test_not_advertised_when_read_only(self):
        with patch.dict(os.environ, {**BOTH_ON, "REDMINE_MCP_READ_ONLY": "true"}):
            assert not (NOTE_WRITE_SCOPES & set(advertised_scopes()))

    def test_not_advertised_when_both_off(self):
        with patch.dict(os.environ, BOTH_OFF):
            assert not (NOTE_WRITE_SCOPES & set(advertised_scopes()))

    def test_absent_from_core_lists(self):
        assert not (NOTE_WRITE_SCOPES & (set(READ_SCOPES) | set(WRITE_SCOPES)))


def _sent_body(mock_redmine):
    return json.loads(mock_redmine.engine.request.call_args.kwargs["data"])


class TestToolGating:
    @pytest.mark.asyncio
    async def test_both_flags_off(self):
        with patch.dict(os.environ, BOTH_OFF):
            result = await manage_crm_note(action="get", note_id=1)
        assert "REDMINE_CRM_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="list")
        assert "Invalid action" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["create", "update", "delete"])
    async def test_writes_blocked_in_read_only(self, action):
        with patch.dict(os.environ, {**BOTH_ON, "REDMINE_MCP_READ_ONLY": "true"}):
            result = await manage_crm_note(
                action=action,
                note_id=1,
                source_type="deal",
                source_id=1,
                project_id=1,
                content="x",
            )
        assert "read-only" in result["error"].lower()


class TestGet:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_returns_note(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"note": _note()}
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="get", note_id=2)
        assert result["id"] == 2 and result["note_type"] == "call"
        args = mock_redmine.engine.request.call_args
        assert args.args == ("get", "http://localhost:3000/notes/2.json")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_deal_note_with_deals_off_is_gated(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"note": _note(source_type="Deal")}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_crm_note(action="get", note_id=2)
        assert "REDMINE_DEALS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_get_not_found(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="get", note_id=99)
        assert result == {"error": "Note 99 not found."}

    @pytest.mark.asyncio
    async def test_get_requires_note_id(self):
        with patch.dict(os.environ, BOTH_ON):
            assert "note_id" in (await manage_crm_note(action="get"))["error"]


class TestCreate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_posts_expected_body(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"note": _note()}
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(
                action="create",
                source_type="deal",
                source_id=5,
                project_id="sales",
                content="called them",
                subject="call",
                type_id=1,
            )
        assert result["id"] == 2
        args = mock_redmine.engine.request.call_args
        assert args.args == ("post", "http://localhost:3000/notes.json")
        # Without an explicit JSON content type Redmine parses the body as a
        # single "_json" string and NotesController#find_project 404s.
        assert args.kwargs["headers"] == {"Content-Type": "application/json"}
        assert _sent_body(mock_redmine) == {
            "note": {
                "source_type": "deal",
                "source_id": 5,
                "project_id": "sales",
                "content": "called them",
                "subject": "call",
                "type_id": 1,
            }
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_drops_unset_optionals(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"note": _note()}
        with patch.dict(os.environ, BOTH_ON):
            await manage_crm_note(
                action="create",
                source_type="contact",
                source_id=9,
                project_id=1,
                content="hi",
            )
        assert set(_sent_body(mock_redmine)["note"]) == {
            "source_type",
            "source_id",
            "project_id",
            "content",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs,field",
        [
            ({"source_id": 5, "project_id": 1, "content": "x"}, "source_type"),
            ({"source_type": "deal", "project_id": 1, "content": "x"}, "source_id"),
            ({"source_type": "deal", "source_id": 5, "content": "x"}, "project_id"),
            ({"source_type": "deal", "source_id": 5, "project_id": 1}, "content"),
            (
                {
                    "source_type": "deal",
                    "source_id": 5,
                    "project_id": 1,
                    "content": " ",
                },
                "content",
            ),
            (
                {
                    "source_type": "deal",
                    "source_id": 5,
                    "project_id": 1,
                    "content": "x",
                    "type_id": 7,
                },
                "type_id",
            ),
        ],
    )
    async def test_create_validation(self, kwargs, field):
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="create", **kwargs)
        assert field in result["error"]

    @pytest.mark.asyncio
    async def test_create_deal_note_with_deals_off(self):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_crm_note(
                action="create",
                source_type="deal",
                source_id=5,
                project_id=1,
                content="x",
            )
        assert "REDMINE_DEALS_ENABLED" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_unknown_source_maps_404(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ResourceNotFoundError()
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(
                action="create",
                source_type="deal",
                source_id=999,
                project_id="sales",
                content="x",
            )
        assert result == {"error": "Deal 999 not found (or project sales not found)."}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_validation_error_from_redmine(self, mock_redmine):
        mock_redmine.engine.request.side_effect = ValidationError(
            "Content cannot be blank"
        )
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(
                action="create",
                source_type="deal",
                source_id=5,
                project_id=1,
                content="x",
            )
        assert "Content cannot be blank" in result["error"]


class TestUpdate:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_update_fetches_then_puts(self, mock_redmine):
        mock_redmine.engine.request.side_effect = [{"note": _note()}, None]
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="update", note_id=2, content="edited")
        assert result == {"success": True, "note_id": 2, "updated_fields": ["content"]}
        calls = mock_redmine.engine.request.call_args_list
        assert calls[0].args == ("get", "http://localhost:3000/notes/2.json")
        assert calls[1].args == ("put", "http://localhost:3000/notes/2.json")
        assert json.loads(calls[1].kwargs["data"]) == {"note": {"content": "edited"}}
        assert calls[1].kwargs["headers"] == {"Content-Type": "application/json"}

    @pytest.mark.asyncio
    async def test_update_requires_a_field(self):
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="update", note_id=2)
        assert "content" in result["error"] and "subject" in result["error"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_update_gated_by_fetched_source(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "note": _note(source_type="Contact")
        }
        with patch.dict(os.environ, DEALS_ON):
            result = await manage_crm_note(action="update", note_id=2, content="x")
        assert "REDMINE_CRM_ENABLED" in result["error"]
        assert mock_redmine.engine.request.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_update_forbidden_explains_delete_permission(self, mock_redmine):
        mock_redmine.engine.request.side_effect = [{"note": _note()}, ForbiddenError()]
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="update", note_id=2, content="x")
        assert "delete_notes" in result["error"]


class TestDelete:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_delete_fetches_then_deletes(self, mock_redmine):
        mock_redmine.engine.request.side_effect = [{"note": _note()}, None]
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="delete", note_id=2)
        assert result == {"success": True, "note_id": 2, "message": "Note 2 deleted."}
        calls = mock_redmine.engine.request.call_args_list
        assert calls[1].args == ("delete", "http://localhost:3000/notes/2.json")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_delete_forbidden(self, mock_redmine):
        mock_redmine.engine.request.side_effect = [{"note": _note()}, ForbiddenError()]
        with patch.dict(os.environ, BOTH_ON):
            result = await manage_crm_note(action="delete", note_id=2)
        assert "delete_notes" in result["error"]
