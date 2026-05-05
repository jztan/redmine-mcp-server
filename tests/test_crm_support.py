"""Unit tests for RedmineUP CRM (Contacts) plugin support."""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _is_crm_enabled,
    list_contacts,
    get_contact,
    edit_contact,
    create_contact,
    delete_contact,
    assign_contact_to_project,
    remove_contact_from_project,
)


def _make_contact(contact_id: int = 1, first_name: str = "Alice") -> dict:
    return {
        "id": contact_id,
        "first_name": first_name,
        "last_name": "Smith",
        "email": "alice@example.com",
        "phone": "+1-555-0100",
        "company": "ACME",
        "is_company": False,
        "tags": ["lead"],
        "address": {
            "street1": "1 Main St",
            "city": "Boston",
            "country": "US",
            "postcode": "02101",
        },
        "assigned_to": {"id": 5, "name": "Bob"},
        "visibility": 0,
        "created_on": "2026-04-20T10:00:00Z",
        "updated_on": "2026-04-20T11:00:00Z",
    }


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestIsCrmEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_CRM_ENABLED", None)
            assert _is_crm_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            assert _is_crm_enabled() is True


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------


class TestListContacts:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_list_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "contacts": [_make_contact(1), _make_contact(2, "Bob")]
        }
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await list_contacts()

        assert isinstance(result, list)
        assert len(result) == 2
        # PII (email, phone) returned as-is
        assert result[0]["email"] == "alice@example.com"
        assert result[0]["phone"] == "+1-555-0100"
        # First name is wrapped in insecure-content
        assert "<insecure-content-" in result[0]["first_name"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_filters_passed_to_api(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            await list_contacts(
                project_id="proj",
                search="alice",
                tags="lead",
                assigned_to_id=5,
                limit=50,
            )

        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        params = call_kwargs["params"]
        assert params["project_id"] == "proj"
        assert params["search"] == "alice"
        assert params["tags"] == "lead"
        assert params["assigned_to_id"] == 5
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await list_contacts()
        assert "REDMINE_CRM_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_limit(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await list_contacts(limit=-1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_assigned_to_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await list_contacts(assigned_to_id=0)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_clamps_limit_to_100(self, mock_redmine):
        """Redmine caps `limit` at 100 server-side; values above are clamped."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            await list_contacts(limit=500)

        call_kwargs = mock_redmine.engine.request.call_args.kwargs
        assert call_kwargs["params"]["limit"] == 100

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_slices_oversized_response(self, mock_redmine):
        """Defensive slice: even if Redmine returned more than `limit`, the
        tool truncates to `limit`."""
        many = [_make_contact(i) for i in range(200)]
        mock_redmine.engine.request.return_value = {"contacts": many}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await list_contacts(limit=25)

        assert isinstance(result, list)
        assert len(result) == 25

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await list_contacts(project_id="")
        assert "error" in result
        assert "project_id" in result["error"]


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------


class TestGetContact:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_get_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contact": _make_contact(42)}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await get_contact(contact_id=42)
        assert result["id"] == 42
        assert result["address"]["city"] == "Boston"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_includes_passed(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contact": _make_contact(1)}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            await get_contact(contact_id=1, include="notes,deals")
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["include"] == "notes,deals"

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await get_contact(contact_id=1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await get_contact(contact_id=-1)
        assert "error" in result

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_not_found(self, mock_redmine):
        mock_redmine.engine.request.return_value = {}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await get_contact(contact_id=999)
        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# edit_contact
# ---------------------------------------------------------------------------


class TestEditContact:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_edit_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await edit_contact(
                contact_id=1,
                fields={"first_name": "Carol", "email": "c@x.com"},
            )
        assert result["success"] is True
        assert set(result["updated_fields"]) == {"first_name", "email"}

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_filters_unknown_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await edit_contact(
                contact_id=1,
                fields={"first_name": "X", "evil": "bad"},
            )
        assert result["updated_fields"] == ["first_name"]
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert "evil" not in body["contact"]

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_CRM_ENABLED": "true"},
        ):
            result = await edit_contact(contact_id=1, fields={"email": "x"})
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await edit_contact(contact_id=1, fields={"first_name": "X"})
        assert "REDMINE_CRM_ENABLED" in result["error"]

    @pytest.mark.asyncio
    async def test_no_writable_fields(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await edit_contact(contact_id=1, fields={"unknown": "x"})
        assert "writable fields" in result["error"]


# ---------------------------------------------------------------------------
# create_contact
# ---------------------------------------------------------------------------


class TestCreateContact:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_create_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contact": _make_contact(99)}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await create_contact(
                project_id="proj",
                first_name="Alice",
                last_name="Smith",
                email="alice@x.com",
            )
        assert result["id"] == 99
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert body["contact"]["first_name"] == "Alice"
        assert body["contact"]["project_id"] == "proj"
        assert body["contact"]["visibility"] == 0
        assert body["contact"]["is_company"] is False

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_extra_fields_via_fields_param(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contact": _make_contact(1)}
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            await create_contact(
                project_id="p",
                first_name="A",
                fields={"job_title": "CTO", "tag_list": "vip", "rogue": "x"},
            )
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert body["contact"]["job_title"] == "CTO"
        assert body["contact"]["tag_list"] == "vip"
        assert "rogue" not in body["contact"]

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_CRM_ENABLED": "true"},
        ):
            result = await create_contact(project_id="p", first_name="A")
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await create_contact(project_id="p", first_name="A")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_first_name(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await create_contact(project_id="p", first_name="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_visibility(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await create_contact(project_id="p", first_name="A", visibility=9)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_is_company_type(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await create_contact(
                project_id="p", first_name="A", is_company="yes"
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# delete_contact
# ---------------------------------------------------------------------------


class TestDeleteContact:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_delete_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await delete_contact(contact_id=42)
        assert result["success"] is True
        assert result["contact_id"] == 42
        mock_redmine.engine.request.assert_called_once_with(
            "delete", "http://localhost:3000/contacts/42.json"
        )

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_CRM_ENABLED": "true"},
        ):
            result = await delete_contact(contact_id=1)
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await delete_contact(contact_id=1)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await delete_contact(contact_id=-1)
        assert "error" in result


# ---------------------------------------------------------------------------
# assign_contact_to_project / remove_contact_from_project
# ---------------------------------------------------------------------------


class TestAssignContactToProject:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_assign_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await assign_contact_to_project(
                contact_id=42, project_id="newproj"
            )
        assert result["success"] is True
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert body["project"]["id"] == "newproj"

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_CRM_ENABLED": "true"},
        ):
            result = await assign_contact_to_project(contact_id=1, project_id="p")
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await assign_contact_to_project(contact_id=1, project_id="p")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await assign_contact_to_project(contact_id=1, project_id="")
        assert "error" in result
        assert "project_id" in result["error"]


class TestRemoveContactFromProject:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    async def test_remove_success(self, mock_redmine):
        mock_redmine.engine.request.return_value = True
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await remove_contact_from_project(
                contact_id=42, project_id="oldproj"
            )
        assert result["success"] is True
        mock_redmine.engine.request.assert_called_once_with(
            "delete",
            "http://localhost:3000/contacts/42/projects/oldproj.json",
        )

    @pytest.mark.asyncio
    async def test_blocked_in_read_only_mode(self):
        with patch.dict(
            os.environ,
            {"REDMINE_MCP_READ_ONLY": "true", "REDMINE_CRM_ENABLED": "true"},
        ):
            result = await remove_contact_from_project(contact_id=1, project_id="p")
        assert "read-only" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "false"}):
            result = await remove_contact_from_project(contact_id=1, project_id="p")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await remove_contact_from_project(contact_id=-1, project_id="p")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_empty_project_id(self):
        with patch.dict(os.environ, {"REDMINE_CRM_ENABLED": "true"}):
            result = await remove_contact_from_project(contact_id=1, project_id="")
        assert "error" in result
        assert "project_id" in result["error"]
