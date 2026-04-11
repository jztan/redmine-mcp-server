"""Unit tests for RedmineUP Agile plugin support."""

import json
import os
import sys

from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _is_agile_enabled,
    _fetch_agile_data,
    _apply_agile_story_points,
)


class TestIsAgileEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_AGILE_ENABLED", None)
            assert _is_agile_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_AGILE_ENABLED": "true"}):
            assert _is_agile_enabled() is True

    def test_false_when_env_set_to_false(self):
        with patch.dict(os.environ, {"REDMINE_AGILE_ENABLED": "false"}):
            assert _is_agile_enabled() is False


class TestFetchAgileData:
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    def test_returns_mapped_fields(self, mock_redmine):
        mock_response = Mock()
        mock_response.json.return_value = {
            "agile_data": {
                "story_points": 8,
                "agile_sprint_id": 3,
                "position": 2,
            }
        }
        mock_redmine.engine.request.return_value = mock_response

        result = _fetch_agile_data(42)

        assert result == {
            "story_points": 8,
            "agile_sprint_id": 3,
            "agile_position": 2,
        }
        mock_redmine.engine.request.assert_called_once_with(
            "get", "http://localhost:3000/issues/42/agile_data.json"
        )

    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    def test_handles_null_fields(self, mock_redmine):
        mock_response = Mock()
        mock_response.json.return_value = {
            "agile_data": {
                "story_points": None,
                "agile_sprint_id": None,
                "position": None,
            }
        }
        mock_redmine.engine.request.return_value = mock_response

        result = _fetch_agile_data(1)

        assert result == {
            "story_points": None,
            "agile_sprint_id": None,
            "agile_position": None,
        }


class TestApplyAgileStoryPoints:
    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    def test_calls_engine_put_with_correct_payload(self, mock_redmine):
        mock_redmine.engine.request.return_value = Mock()

        _apply_agile_story_points(42, 8)

        mock_redmine.engine.request.assert_called_once_with(
            "put",
            "http://localhost:3000/issues/42.json",
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {"issue": {"agile_data_attributes": {"story_points": 8}}}
            ),
        )

    @patch("redmine_mcp_server.redmine_handler.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server.redmine_handler.redmine")
    def test_allows_null_to_clear_story_points(self, mock_redmine):
        mock_redmine.engine.request.return_value = Mock()

        _apply_agile_story_points(42, None)

        mock_redmine.engine.request.assert_called_once_with(
            "put",
            "http://localhost:3000/issues/42.json",
            headers={"Content-Type": "application/json"},
            data=json.dumps(
                {"issue": {"agile_data_attributes": {"story_points": None}}}
            ),
        )
