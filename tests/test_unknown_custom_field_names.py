"""A key meant as a custom field name that matches none is refused (#370).

``_resolve_named_custom_fields`` used to skip an unmatched key, so it went to
Redmine as a top-level issue attribute and was ignored: a misspelled name was
a write that reported success and changed nothing. Refusing every unmatched
key would break plugin attributes that are passed the same way and do work --
RedmineUP Agile accepts ``agile_data_attributes`` on create -- so only a key
that cannot be an attribute, or one that is a near miss for a field name, is
refused.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._custom_fields import (  # noqa: E402
    _resolve_named_custom_fields,
)
from redmine_mcp_server.tools.issues import update_redmine_issue  # noqa: E402

_FIELDS = [
    SimpleNamespace(id=1, name="Priority Level", possible_values=None),
    SimpleNamespace(id=2, name="Department", possible_values=None),
    SimpleNamespace(id=3, name="severity", possible_values=None),
]


class TestRefused:
    @pytest.mark.parametrize(
        "key,suggestion",
        [
            ("Priorty Levl", "Priority Level"),
            ("Departmnt", "Department"),
            ("severty", "severity"),
        ],
    )
    def test_a_near_miss_names_the_field_it_resembles(self, key, suggestion):
        with pytest.raises(ValueError) as exc:
            _resolve_named_custom_fields({key: "x"}, _FIELDS)
        message = str(exc.value)
        assert f"Unknown custom field '{key}'" in message
        assert f"Did you mean '{suggestion}'?" in message
        assert "Nothing was written" in message

    def test_a_key_that_cannot_be_an_attribute_is_refused_without_a_match(self):
        with pytest.raises(ValueError) as exc:
            _resolve_named_custom_fields({"Budget Code": "x"}, _FIELDS)
        message = str(exc.value)
        assert "Did you mean" not in message
        assert "'Department', 'Priority Level', 'severity'" in message

    def test_a_project_with_no_custom_fields_says_so(self):
        with pytest.raises(ValueError, match="Custom fields on this project: none"):
            _resolve_named_custom_fields({"Budget Code": "x"}, [])


class TestPassedThrough:
    @pytest.mark.parametrize(
        "key",
        ["agile_data_attributes", "some_plugin_flag", "helpdesk_ticket_attributes"],
    )
    def test_a_snake_case_key_unlike_any_field_is_left_alone(self, key):
        payload = _resolve_named_custom_fields({key: {"a": 1}}, _FIELDS)
        assert payload == {key: {"a": 1}}

    @pytest.mark.parametrize("key", ["project_id", "lock_version"])
    def test_redmine_core_attributes_are_never_refused(self, key):
        fields = _FIELDS + [SimpleNamespace(id=9, name="Project", possible_values=None)]
        payload = _resolve_named_custom_fields({key: 4}, fields)
        assert payload == {key: 4}

    def test_a_matching_name_still_maps_to_its_id(self):
        payload = _resolve_named_custom_fields({"priority level": "Low"}, _FIELDS)
        assert payload == {"custom_fields": [{"id": 1, "value": "Low"}]}


@pytest.mark.asyncio
async def test_update_refuses_before_writing():
    client = MagicMock()
    with (
        patch(
            "redmine_mcp_server._custom_fields._resolve_project_issue_custom_fields",
            return_value=_FIELDS,
        ),
        patch(
            "redmine_mcp_server.tools.issues._get_redmine_client", return_value=client
        ),
    ):
        result = await update_redmine_issue(5, {"Priorty Levl": "Low", "notes": "x"})
    assert "Did you mean 'Priority Level'?" in result["error"]
    client.issue.update.assert_not_called()
