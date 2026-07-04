import pytest
from unittest.mock import AsyncMock, patch

from redmine_mcp_server.apps import triage_board

_STATUSES = [
    {"id": 1, "name": "New", "is_closed": False},
    {"id": 2, "name": "In Progress", "is_closed": False},
    {"id": 5, "name": "Closed", "is_closed": True},
]


def _issue(**kw):
    base = {
        "id": 42,
        "subject": "Fix login",
        "status": {"id": 1, "name": "New"},
        "assigned_to": {"id": 7, "name": "Alice"},
        "priority": {"id": 2, "name": "Normal"},
        "tracker": {"id": 3, "name": "Bug"},
        "project": {"id": 9, "name": "Web"},
    }
    base.update(kw)
    return base


def _patch(statuses, issues_resp):
    return (
        patch.object(
            triage_board,
            "list_redmine_issue_statuses",
            AsyncMock(return_value=statuses),
        ),
        patch.object(
            triage_board, "list_redmine_issues", AsyncMock(return_value=issues_resp)
        ),
    )


@pytest.mark.asyncio
async def test_build_board_payload_shape():
    resp = {"issues": [_issue()], "pagination": {"has_next": False}}
    ps, pi = _patch(_STATUSES, resp)
    with ps, pi:
        payload = await triage_board._build_board_payload(9)
    assert payload["project"] == {"id": 9, "name": "Web"}
    assert payload["statuses"] == _STATUSES
    assert payload["issues"] == [
        {
            "id": 42,
            "subject": "Fix login",
            "status_id": 1,
            "assigned_to": "Alice",
            "priority": "Normal",
            "tracker": "Bug",
        }
    ]
    assert payload["truncated"] is False
    assert isinstance(payload["generated_at"], str) and payload["generated_at"]


@pytest.mark.asyncio
async def test_build_board_payload_truncated_flag():
    resp = {"issues": [_issue()], "pagination": {"has_next": True}}
    ps, pi = _patch(_STATUSES, resp)
    with ps, pi:
        payload = await triage_board._build_board_payload(9)
    assert payload["truncated"] is True


@pytest.mark.asyncio
async def test_build_board_payload_empty_project_name_fallback():
    resp = {"issues": [], "pagination": {}}
    ps, pi = _patch(_STATUSES, resp)
    with ps, pi:
        payload = await triage_board._build_board_payload("my-proj")
    assert payload["project"] == {"id": "my-proj", "name": "my-proj"}
    assert payload["issues"] == []


@pytest.mark.asyncio
async def test_build_board_payload_passes_through_statuses_error():
    ps, pi = _patch({"error": "boom"}, {"issues": []})
    with ps, pi:
        payload = await triage_board._build_board_payload(9)
    assert payload == {"error": "boom"}


@pytest.mark.asyncio
async def test_build_board_payload_passes_through_issues_error():
    ps, pi = _patch(_STATUSES, {"error": "no access"})
    with ps, pi:
        payload = await triage_board._build_board_payload(9)
    assert payload == {"error": "no access"}


# Importing the package registers the resource + tools on the shared mcp.
from redmine_mcp_server import apps  # noqa: E402,F401
from redmine_mcp_server.server import mcp  # noqa: E402


@pytest.mark.asyncio
async def test_ui_resource_registered():
    res = await mcp.get_resource("ui://redmine/triage-board.html")
    assert res.mime_type == "text/html;profile=mcp-app"
    body = await res.read()
    assert isinstance(body, str) and body.strip()


@pytest.mark.asyncio
async def test_show_triage_board_meta_points_at_ui():
    tool = await mcp.get_tool("show_triage_board")
    ui = tool.meta["ui"]
    assert ui["resourceUri"] == "ui://redmine/triage-board.html"
    assert ui["visibility"] == ["model"]
    assert ui.get("csp", {}) == {}  # no external domains declared


@pytest.mark.asyncio
async def test_backend_tool_is_app_only():
    tool = await mcp.get_tool("get_triage_board_data")
    ui = tool.meta["ui"]
    assert ui["visibility"] == ["app"]
    assert "resourceUri" not in ui


@pytest.mark.asyncio
async def test_html_speaks_extapps_protocol():
    res = await mcp.get_resource("ui://redmine/triage-board.html")
    html = await res.read()
    for token in [
        "ui/initialize",
        "ui/notifications/initialized",
        "ui/notifications/tool-result",
        "ui/notifications/tool-input",
        "ui/notifications/size-changed",
        "get_triage_board_data",
        "2026-01-26",
        "postMessage",
    ]:
        assert token in html, token


@pytest.mark.asyncio
async def test_html_never_uses_innerhtml():
    res = await mcp.get_resource("ui://redmine/triage-board.html")
    html = await res.read()
    # Issue data is user-controlled; rendering must avoid innerHTML entirely.
    assert "innerHTML" not in html
