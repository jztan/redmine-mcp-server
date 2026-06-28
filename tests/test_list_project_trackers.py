"""Unit tests for the list_project_trackers tool."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import list_project_trackers  # noqa: E402


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_returns_project_trackers(mock_redmine):
    mock_redmine.project.get.return_value = SimpleNamespace(
        trackers=[
            SimpleNamespace(id=1, name="Bug"),
            SimpleNamespace(id=2, name="Feature"),
        ]
    )
    result = await list_project_trackers("my-project")
    assert result == [{"id": 1, "name": "Bug"}, {"id": 2, "name": "Feature"}]
    mock_redmine.project.get.assert_called_once_with("my-project", include="trackers")


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_returns_empty_list_when_no_trackers(mock_redmine):
    mock_redmine.project.get.return_value = SimpleNamespace(trackers=None)
    result = await list_project_trackers(7)
    assert result == []


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_error_is_wrapped_in_list(mock_redmine):
    mock_redmine.project.get.side_effect = Exception("boom")
    result = await list_project_trackers("missing")
    assert isinstance(result, list) and "error" in result[0]
