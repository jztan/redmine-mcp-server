"""Test cases for project custom field values from list_redmine_projects.

See https://github.com/jztan/redmine-mcp-server/issues/230.
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import (  # noqa: E402
    list_redmine_projects,
)

# Redmine hands these back as CustomField resources, not dicts, so the fakes
# below expose them as attributes -- a fake built from plain dicts would pass
# even if the serializer were bypassed entirely.
_EXPECTED = [{"id": 12, "name": "Size", "value": "S"}]


def _custom_field(id, name, value, **extra):
    """A stand-in for a python-redmine CustomField resource.

    ``name`` is assigned rather than passed to the constructor: ``Mock(name=)``
    sets the mock's own name instead of an attribute.
    """
    field = Mock(id=id, value=value, **extra)
    field.name = name
    return field


def _mock_project(project_id=1, custom_fields=None):
    project = Mock()
    project.id = project_id
    project.name = f"Project {project_id}"
    project.identifier = f"proj-{project_id}"
    project.description = ""
    project.created_on = None
    if custom_fields is None:
        # Redmine omits the key when a project has no visible values, so the
        # attribute is absent rather than empty. Mock() would invent it.
        del project.custom_fields
    else:
        project.custom_fields = list(custom_fields)
    return project


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


class TestProjectCustomFieldValues:
    """The values Redmine already sends on GET /projects.json, opt-in."""

    @pytest.mark.asyncio
    async def test_default_keys_are_unchanged(self, mock_redmine):
        """The five existing keys are the contract; the flag only adds one."""
        mock_redmine.project.all.return_value = [
            _mock_project(custom_fields=[_custom_field(12, "Size", "S")])
        ]
        result = await list_redmine_projects()
        assert set(result[0]) == {
            "id",
            "name",
            "identifier",
            "description",
            "created_on",
        }

    @pytest.mark.asyncio
    async def test_values_are_serialized_not_passed_through(self, mock_redmine):
        """Each entry is reduced to id, name and value.

        The resource carries more than that, so returning it unserialized
        would both leak attributes and fail to encode as JSON.
        """
        mock_redmine.project.all.return_value = [
            _mock_project(
                custom_fields=[
                    _custom_field(
                        12, "Size", "S", field_format="list", internal=object()
                    )
                ]
            )
        ]
        result = await list_redmine_projects(include_custom_fields=True)
        assert result[0]["custom_fields"] == _EXPECTED

    @pytest.mark.asyncio
    async def test_project_whose_payload_omits_the_key(self, mock_redmine):
        """Redmine sends no custom_fields key when there are no visible values."""
        mock_redmine.project.all.return_value = [_mock_project()]
        result = await list_redmine_projects(include_custom_fields=True)
        assert result[0]["custom_fields"] == []

    @pytest.mark.asyncio
    async def test_no_per_project_request(self, mock_redmine):
        """The values ride along with the list; nothing is fetched per project.

        Distinct values per project, so a serializer that reused one project's
        entry for every project would fail here too.
        """
        mock_redmine.project.all.return_value = [
            _mock_project(n, custom_fields=[_custom_field(12, "Size", f"S{n}")])
            for n in (1, 2, 3)
        ]
        result = await list_redmine_projects(include_custom_fields=True)
        assert [p["custom_fields"][0]["value"] for p in result] == ["S1", "S2", "S3"]
        mock_redmine.project.get.assert_not_called()
