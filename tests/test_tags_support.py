"""Unit tests for AlphaNodes additional_tags plugin support."""

import os
import sys

import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._env import _is_tags_enabled  # noqa: E402
from redmine_mcp_server.tools.issues import (  # noqa: E402
    _issue_tags_to_list,
    _normalize_tag_list,
    create_redmine_issue,
    get_redmine_issue,
    update_redmine_issue,
)


def _make_minimal_issue(issue_id: int = 1, tags=None) -> Mock:
    """Create a minimal mock issue object accepted by _issue_to_dict.

    When ``tags`` is None the ``tags`` attribute is absent entirely, mirroring
    a Redmine that either lacks the plugin or a caller without the
    ``view_issue_tags`` permission (the plugin then omits the field).
    """
    issue = Mock(
        spec=[
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
            "journals",
            "attachments",
        ]
        + (["tags"] if tags is not None else [])
    )
    issue.id = issue_id
    issue.subject = "Test Issue"
    issue.description = "desc"
    issue.project = None
    issue.status = None
    issue.priority = None
    issue.author = None
    issue.assigned_to = None
    issue.created_on = None
    issue.updated_on = None
    issue.journals = []
    issue.attachments = []
    if tags is not None:
        issue.tags = tags
    return issue


class TestIsTagsEnabled:
    def test_false_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDMINE_TAGS_ENABLED", None)
            assert _is_tags_enabled() is False

    def test_true_when_env_set(self):
        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            assert _is_tags_enabled() is True

    def test_false_when_env_set_to_false(self):
        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "false"}):
            assert _is_tags_enabled() is False


class TestIssueTagsToList:
    def test_maps_saved_tags(self):
        issue = _make_minimal_issue(
            tags=[{"id": 3, "name": "fast-track"}, {"id": 7, "name": "urgent"}]
        )
        assert _issue_tags_to_list(issue) == [
            {"id": 3, "name": "fast-track"},
            {"id": 7, "name": "urgent"},
        ]

    def test_maps_unsaved_tag_without_id(self):
        issue = _make_minimal_issue(tags=[{"name": "draft"}])
        assert _issue_tags_to_list(issue) == [{"id": None, "name": "draft"}]

    def test_empty_when_attribute_absent(self):
        issue = _make_minimal_issue(tags=None)
        assert _issue_tags_to_list(issue) == []

    def test_empty_when_tags_empty(self):
        issue = _make_minimal_issue(tags=[])
        assert _issue_tags_to_list(issue) == []

    def test_handles_object_style_tags(self):
        tag = Mock(spec=["id", "name"])
        tag.id = 9
        tag.name = "backend"
        issue = _make_minimal_issue(tags=[tag])
        assert _issue_tags_to_list(issue) == [{"id": 9, "name": "backend"}]


class TestGetRedmineIssueTags:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_includes_tags_when_enabled(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_minimal_issue(
            1, tags=[{"id": 3, "name": "fast-track"}]
        )

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            result = await get_redmine_issue(1)

        assert result["tags"] == [{"id": 3, "name": "fast-track"}]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_empty_tags_when_enabled_but_none_present(self, mock_redmine):
        # Plugin absent / no view_issue_tags permission: attribute missing.
        mock_redmine.issue.get.return_value = _make_minimal_issue(1, tags=None)

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            result = await get_redmine_issue(1)

        assert result["tags"] == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_no_tags_key_when_disabled(self, mock_redmine):
        mock_redmine.issue.get.return_value = _make_minimal_issue(
            1, tags=[{"id": 3, "name": "fast-track"}]
        )

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "false"}):
            result = await get_redmine_issue(1)

        assert "tags" not in result


class TestNormalizeTagList:
    def test_list_of_names(self):
        assert _normalize_tag_list(["a", " b ", ""]) == ["a", "b"]

    def test_comma_string_is_split(self):
        assert _normalize_tag_list("a, b,c") == ["a", "b", "c"]

    def test_none_clears(self):
        assert _normalize_tag_list(None) == []

    def test_single_name_string(self):
        assert _normalize_tag_list("fast-track") == ["fast-track"]


class TestCreateRedmineIssueTags:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_passed_on_create_when_enabled(self, mock_redmine):
        mock_redmine.issue.create.return_value = _make_minimal_issue(5)

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            result = await create_redmine_issue(
                project_id=1, subject="S", fields={"tag_list": ["a", "b"]}
            )

        assert "error" not in result
        _, kwargs = mock_redmine.issue.create.call_args
        assert kwargs.get("tag_list") == ["a", "b"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_comma_string_split_on_create(self, mock_redmine):
        mock_redmine.issue.create.return_value = _make_minimal_issue(5)

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            await create_redmine_issue(
                project_id=1, subject="S", fields={"tag_list": "a, b"}
            )

        _, kwargs = mock_redmine.issue.create.call_args
        assert kwargs.get("tag_list") == ["a", "b"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_dropped_on_create_when_disabled(self, mock_redmine):
        mock_redmine.issue.create.return_value = _make_minimal_issue(5)

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "false"}):
            await create_redmine_issue(
                project_id=1, subject="S", fields={"tag_list": ["a"]}
            )

        _, kwargs = mock_redmine.issue.create.call_args
        assert "tag_list" not in kwargs


class TestUpdateRedmineIssueTags:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_passed_on_update_when_enabled(self, mock_redmine):
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = _make_minimal_issue(1, tags=[])

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            result = await update_redmine_issue(1, {"tag_list": ["a", "b"]})

        assert "error" not in result
        args, kwargs = mock_redmine.issue.update.call_args
        assert args == (1,)
        assert kwargs.get("tag_list") == ["a", "b"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_only_still_triggers_update(self, mock_redmine):
        # tag_list is the only field: update must still fire (empty clears tags)
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = _make_minimal_issue(1, tags=[])

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "true"}):
            await update_redmine_issue(1, {"tag_list": []})

        mock_redmine.issue.update.assert_called_once()
        _, kwargs = mock_redmine.issue.update.call_args
        assert kwargs.get("tag_list") == []

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_dropped_on_update_when_disabled(self, mock_redmine):
        mock_redmine.issue.update.return_value = True
        mock_redmine.issue.get.return_value = _make_minimal_issue(1)

        with patch.dict(os.environ, {"REDMINE_TAGS_ENABLED": "false"}):
            await update_redmine_issue(1, {"tag_list": ["a"], "subject": "X"})

        _, kwargs = mock_redmine.issue.update.call_args
        assert "tag_list" not in kwargs
        assert kwargs.get("subject") == "X"


class TestTagListSurvivesAutofillRetry:
    """tag_list must be re-applied on the required-custom-field autofill retry.

    When ``REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true`` and the first
    create/update fails on a required custom field, the retry rebuilds its
    kwargs from the field dict — which no longer carries ``tag_list`` (it was
    extracted earlier). Without re-adding it, the retry would succeed but
    silently drop the tags, mirroring the agile ``story_points`` re-apply.
    """

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_reapplied_on_create_retry(self, mock_redmine):
        from redminelib.exceptions import ValidationError

        category_field = Mock()
        category_field.id = 6
        category_field.name = "Project Category"
        category_field.possible_values = [{"value": "Any"}, {"value": "Foo"}]
        category_field.default_value = "Foo"

        mock_project = Mock()
        mock_project.issue_custom_fields = [category_field]
        mock_redmine.project.get.return_value = mock_project

        mock_redmine.issue.create.side_effect = [
            ValidationError("Project Category cannot be blank"),
            _make_minimal_issue(5),
        ]

        env = {
            "REDMINE_TAGS_ENABLED": "true",
            "REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true",
        }
        with patch.dict(os.environ, env):
            result = await create_redmine_issue(
                project_id=41, subject="S", fields={"tag_list": ["a", "b"]}
            )

        assert "error" not in result
        assert mock_redmine.issue.create.call_count == 2
        retry_kwargs = mock_redmine.issue.create.call_args_list[1].kwargs
        assert retry_kwargs.get("tag_list") == ["a", "b"]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    async def test_tag_list_reapplied_on_update_retry(self, mock_redmine):
        from redminelib.exceptions import ValidationError

        location_field = Mock()
        location_field.id = 8
        location_field.name = "Location"
        location_field.possible_values = [{"value": "Any"}, {"value": "Berlin"}]
        location_field.default_value = "Any"

        mock_project = Mock()
        mock_project.issue_custom_fields = [location_field]
        mock_redmine.project.get.return_value = mock_project

        issue_for_project_lookup = Mock()
        issue_for_project_lookup.project = Mock(id=41, name="Flatline")

        mock_redmine.issue.update.side_effect = [
            ValidationError("Location cannot be blank"),
            None,
        ]
        mock_redmine.issue.get.side_effect = [
            issue_for_project_lookup,
            _make_minimal_issue(123, tags=[]),
        ]

        env = {
            "REDMINE_TAGS_ENABLED": "true",
            "REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS": "true",
        }
        with patch.dict(os.environ, env):
            result = await update_redmine_issue(
                123, {"subject": "New", "tag_list": ["a", "b"]}
            )

        assert "error" not in result
        assert mock_redmine.issue.update.call_count == 2
        retry_kwargs = mock_redmine.issue.update.call_args_list[1].kwargs
        assert retry_kwargs.get("tag_list") == ["a", "b"]
