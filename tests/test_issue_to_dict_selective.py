"""
Test cases for _issue_to_dict_selective helper function.

This module contains comprehensive tests for the field selection helper
used in the search optimization feature.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _issue_to_dict,
    _issue_to_dict_selective,
)


class TestIssueToDictSelective:
    """Test cases for _issue_to_dict_selective function."""

    @pytest.fixture
    def mock_issue(self):
        """Create a comprehensive mock Redmine issue object."""
        mock_issue = Mock()
        mock_issue.id = 123
        mock_issue.subject = "Test Issue Subject"
        mock_issue.description = "Test issue description"

        # Mock project
        mock_project = Mock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_issue.project = mock_project

        # Mock status
        mock_status = Mock()
        mock_status.id = 2
        mock_status.name = "In Progress"
        mock_issue.status = mock_status

        # Mock priority
        mock_priority = Mock()
        mock_priority.id = 3
        mock_priority.name = "High"
        mock_issue.priority = mock_priority

        # Mock author
        mock_author = Mock()
        mock_author.id = 10
        mock_author.name = "John Doe"
        mock_issue.author = mock_author

        # Mock assigned_to
        mock_assigned = Mock()
        mock_assigned.id = 20
        mock_assigned.name = "Jane Smith"
        mock_issue.assigned_to = mock_assigned

        # Mock timestamps
        mock_issue.created_on = datetime(2024, 1, 15, 10, 30, 0)
        mock_issue.updated_on = datetime(2024, 1, 16, 14, 45, 0)

        return mock_issue

    @pytest.fixture
    def mock_issue_minimal(self):
        """Create a minimal mock issue with only required fields."""
        mock_issue = Mock()
        mock_issue.id = 456
        mock_issue.subject = "Minimal Issue"
        mock_issue.description = None  # Test missing description

        mock_project = Mock()
        mock_project.id = 2
        mock_project.name = "Minimal Project"
        mock_issue.project = mock_project

        mock_status = Mock()
        mock_status.id = 1
        mock_status.name = "New"
        mock_issue.status = mock_status

        mock_priority = Mock()
        mock_priority.id = 2
        mock_priority.name = "Normal"
        mock_issue.priority = mock_priority

        mock_author = Mock()
        mock_author.id = 30
        mock_author.name = "Bob Wilson"
        mock_issue.author = mock_author

        # No assigned_to (None)
        mock_issue.assigned_to = None

        # No timestamps
        mock_issue.created_on = None
        mock_issue.updated_on = None

        return mock_issue

    def test_none_returns_all_fields(self, mock_issue):
        """Test that fields=None returns all fields."""
        result = _issue_to_dict_selective(mock_issue, None)
        expected = _issue_to_dict(mock_issue)

        assert result == expected
        assert len(result) == 10  # All 10 fields
        assert "id" in result
        assert "subject" in result
        assert "description" in result

    def test_asterisk_returns_all_fields(self, mock_issue):
        """Test that fields=["*"] returns all fields."""
        result = _issue_to_dict_selective(mock_issue, ["*"])
        expected = _issue_to_dict(mock_issue)

        assert result == expected
        assert len(result) == 10

    def test_all_keyword_returns_all_fields(self, mock_issue):
        """Test that fields=["all"] returns all fields."""
        result = _issue_to_dict_selective(mock_issue, ["all"])
        expected = _issue_to_dict(mock_issue)

        assert result == expected
        assert len(result) == 10

    def test_single_field_id(self, mock_issue):
        """Test selecting only the id field."""
        result = _issue_to_dict_selective(mock_issue, ["id"])

        assert result == {"id": 123}
        assert len(result) == 1

    def test_single_field_subject(self, mock_issue):
        """Test selecting only the subject field."""
        result = _issue_to_dict_selective(mock_issue, ["subject"])

        assert result == {"subject": "Test Issue Subject"}
        assert len(result) == 1

    def test_single_field_description(self, mock_issue):
        """Test selecting only the description field."""
        result = _issue_to_dict_selective(mock_issue, ["description"])

        assert result == {"description": "Test issue description"}
        assert len(result) == 1

    def test_single_field_project(self, mock_issue):
        """Test selecting only the project field."""
        result = _issue_to_dict_selective(mock_issue, ["project"])

        assert result == {"project": {"id": 1, "name": "Test Project"}}
        assert len(result) == 1
        assert isinstance(result["project"], dict)

    def test_single_field_status(self, mock_issue):
        """Test selecting only the status field."""
        result = _issue_to_dict_selective(mock_issue, ["status"])

        assert result == {"status": {"id": 2, "name": "In Progress"}}
        assert len(result) == 1

    def test_single_field_priority(self, mock_issue):
        """Test selecting only the priority field."""
        result = _issue_to_dict_selective(mock_issue, ["priority"])

        assert result == {"priority": {"id": 3, "name": "High"}}
        assert len(result) == 1

    def test_single_field_author(self, mock_issue):
        """Test selecting only the author field."""
        result = _issue_to_dict_selective(mock_issue, ["author"])

        assert result == {"author": {"id": 10, "name": "John Doe"}}
        assert len(result) == 1

    def test_single_field_assigned_to(self, mock_issue):
        """Test selecting only the assigned_to field."""
        result = _issue_to_dict_selective(mock_issue, ["assigned_to"])

        assert result == {"assigned_to": {"id": 20, "name": "Jane Smith"}}
        assert len(result) == 1

    def test_single_field_created_on(self, mock_issue):
        """Test selecting only the created_on field."""
        result = _issue_to_dict_selective(mock_issue, ["created_on"])

        assert "created_on" in result
        assert result["created_on"] == "2024-01-15T10:30:00"
        assert len(result) == 1

    def test_single_field_updated_on(self, mock_issue):
        """Test selecting only the updated_on field."""
        result = _issue_to_dict_selective(mock_issue, ["updated_on"])

        assert "updated_on" in result
        assert result["updated_on"] == "2024-01-16T14:45:00"
        assert len(result) == 1

    def test_multiple_fields_combination(self, mock_issue):
        """Test selecting multiple fields together."""
        result = _issue_to_dict_selective(mock_issue, ["id", "subject", "status"])

        assert len(result) == 3
        assert result["id"] == 123
        assert result["subject"] == "Test Issue Subject"
        assert result["status"] == {"id": 2, "name": "In Progress"}

    def test_minimal_fields_id_and_subject(self, mock_issue):
        """Test minimal field selection (id and subject only)."""
        result = _issue_to_dict_selective(mock_issue, ["id", "subject"])

        assert len(result) == 2
        assert result == {"id": 123, "subject": "Test Issue Subject"}

    def test_all_fields_explicit_list(self, mock_issue):
        """Test explicitly listing all field names."""
        all_field_names = [
            "id",
            "subject",
            "description",
            "project",
            "status",
            "priority",
            "author",
            "assigned_to",
            "created_on",
            "updated_on",
        ]
        result = _issue_to_dict_selective(mock_issue, all_field_names)
        expected = _issue_to_dict(mock_issue)

        assert result == expected
        assert len(result) == 10

    def test_invalid_field_name_ignored(self, mock_issue):
        """Test that invalid field names are silently ignored."""
        result = _issue_to_dict_selective(
            mock_issue, ["id", "invalid_field", "subject"]
        )

        assert len(result) == 2
        assert result == {"id": 123, "subject": "Test Issue Subject"}
        assert "invalid_field" not in result

    def test_all_invalid_fields_returns_empty(self, mock_issue):
        """Test that all invalid fields returns empty dict."""
        result = _issue_to_dict_selective(
            mock_issue, ["invalid1", "invalid2", "nonexistent"]
        )

        assert result == {}
        assert len(result) == 0

    def test_empty_fields_list_returns_empty(self, mock_issue):
        """Test that empty fields list returns empty dict."""
        result = _issue_to_dict_selective(mock_issue, [])

        assert result == {}
        assert len(result) == 0

    def test_mixed_valid_and_invalid_fields(self, mock_issue):
        """Test mix of valid and invalid field names."""
        result = _issue_to_dict_selective(
            mock_issue, ["id", "bad_field", "subject", "another_bad", "priority"]
        )

        assert len(result) == 3
        assert "id" in result
        assert "subject" in result
        assert "priority" in result
        assert "bad_field" not in result
        assert "another_bad" not in result

    def test_minimal_issue_with_none_assigned_to(self, mock_issue_minimal):
        """Test handling issue with no assigned_to."""
        result = _issue_to_dict_selective(
            mock_issue_minimal, ["id", "subject", "assigned_to"]
        )

        assert len(result) == 3
        assert result["id"] == 456
        assert result["subject"] == "Minimal Issue"
        assert result["assigned_to"] is None

    def test_minimal_issue_with_none_timestamps(self, mock_issue_minimal):
        """Test handling issue with None timestamps."""
        result = _issue_to_dict_selective(
            mock_issue_minimal, ["id", "created_on", "updated_on"]
        )

        assert len(result) == 3
        assert result["id"] == 456
        assert result["created_on"] is None
        assert result["updated_on"] is None

    def test_minimal_issue_with_missing_description(self, mock_issue_minimal):
        """Test handling issue with None description."""
        result = _issue_to_dict_selective(mock_issue_minimal, ["id", "description"])

        assert len(result) == 2
        assert result["id"] == 456
        # When description is None, getattr returns None (not default value)
        assert result["description"] is None

    def test_field_order_preserved(self, mock_issue):
        """Test that field order in result matches input order."""
        fields = ["subject", "id", "priority", "status"]
        result = _issue_to_dict_selective(mock_issue, fields)

        # Dictionary keys maintain insertion order in Python 3.7+
        result_keys = list(result.keys())
        assert result_keys == fields

    def test_duplicate_field_names(self, mock_issue):
        """Test that duplicate field names don't cause issues."""
        result = _issue_to_dict_selective(
            mock_issue, ["id", "subject", "id", "subject"]
        )

        # Should return each field only once
        assert len(result) == 2
        assert result == {"id": 123, "subject": "Test Issue Subject"}

    def test_token_reduction_minimal_fields(self, mock_issue):
        """Test that minimal fields significantly reduce data size."""
        all_fields_result = _issue_to_dict_selective(mock_issue, None)
        minimal_fields_result = _issue_to_dict_selective(mock_issue, ["id", "subject"])

        # Minimal should have fewer keys
        assert len(minimal_fields_result) < len(all_fields_result)
        assert len(minimal_fields_result) == 2
        assert len(all_fields_result) == 10

    def test_case_sensitive_field_names(self, mock_issue):
        """Test that field names are case-sensitive."""
        result = _issue_to_dict_selective(mock_issue, ["ID", "Subject", "PRIORITY"])

        # Case doesn't match, so all should be ignored
        assert result == {}
        assert len(result) == 0

    def test_whitespace_in_field_names(self, mock_issue):
        """Test that whitespace in field names doesn't match."""
        result = _issue_to_dict_selective(mock_issue, [" id", "subject ", " priority "])

        # Whitespace doesn't match exact field names
        assert result == {}

    def test_nested_dict_fields_are_independent(self, mock_issue):
        """Test that nested dicts (project, status) are not modified."""
        result1 = _issue_to_dict_selective(mock_issue, ["project"])
        result2 = _issue_to_dict_selective(mock_issue, ["project"])

        # Modify result1 and check result2 is not affected
        result1["project"]["name"] = "Modified"
        assert result2["project"]["name"] == "Test Project"
