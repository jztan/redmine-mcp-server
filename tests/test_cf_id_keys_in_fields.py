"""A ``cf_<id>`` key in ``fields`` sets the custom field with that id (#407).

``cf_<id>`` is how Redmine spells a custom field in a query filter and how
this server names one in ``unapplied_fields``, so callers write it into
``fields`` too. It is snake_case, so ``_reject_unmatched_name`` let it
through as a plugin attribute: Redmine ignored it, the issue landed with the
field blank, and the only trace was the key in ``unverified_fields``. The key
is now resolved by id against the project's fields, the way a name is
resolved by name, and an id the project does not enable is refused before
anything is written.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._custom_fields import (  # noqa: E402
    _payload_has_named_candidates,
    _resolve_named_custom_fields,
    _unverified_issue_fields,
)
from redmine_mcp_server.tools.issues import (  # noqa: E402
    create_redmine_issue,
    update_redmine_issue,
)

_FIELDS = [
    SimpleNamespace(id=1, name="Priority Level", possible_values=["Low", "High"]),
    SimpleNamespace(id=2, name="Department", possible_values=None),
    SimpleNamespace(id=3, name="Region", possible_values=None),
    SimpleNamespace(id=4, name="REGION", possible_values=None),
]


class TestResolvedById:
    def test_a_cf_key_maps_to_the_field_with_that_id(self):
        payload = _resolve_named_custom_fields({"cf_2": "Sales"}, _FIELDS)
        assert payload == {"custom_fields": [{"id": 2, "value": "Sales"}]}

    def test_id_and_name_keys_merge_into_one_list(self):
        payload = _resolve_named_custom_fields(
            {"cf_2": "Sales", "priority level": "Low", "subject": "x"}, _FIELDS
        )
        assert payload["subject"] == "x"
        assert {"id": 2, "value": "Sales"} in payload["custom_fields"]
        assert {"id": 1, "value": "Low"} in payload["custom_fields"]

    def test_a_cf_key_replaces_the_same_id_given_in_custom_fields(self):
        payload = _resolve_named_custom_fields(
            {"cf_2": "Sales", "custom_fields": [{"id": 2, "value": "Old"}]}, _FIELDS
        )
        assert payload == {"custom_fields": [{"id": 2, "value": "Sales"}]}

    def test_a_field_with_an_ambiguous_name_is_reachable_by_id(self):
        with pytest.raises(ValueError, match="Ambiguous.*cf_<id>"):
            _resolve_named_custom_fields({"Region": "EU"}, _FIELDS)
        payload = _resolve_named_custom_fields({"cf_4": "EU"}, _FIELDS)
        assert payload == {"custom_fields": [{"id": 4, "value": "EU"}]}

    def test_possible_values_apply_to_an_id_key_as_to_a_name(self):
        with pytest.raises(ValueError, match="Invalid value 'Medium'"):
            _resolve_named_custom_fields({"cf_1": "Medium"}, _FIELDS)

    def test_a_cf_key_counts_as_a_candidate_so_the_project_is_read(self):
        assert _payload_has_named_candidates({"cf_2": "Sales"})

    def test_a_resolved_cf_key_is_no_longer_unverified(self):
        payload = _resolve_named_custom_fields({"cf_2": "Sales"}, _FIELDS)
        assert _unverified_issue_fields(payload) == []


class TestRefused:
    def test_an_id_the_project_does_not_enable_names_the_enabled_ones(self):
        with pytest.raises(ValueError) as exc:
            _resolve_named_custom_fields({"cf_99": "x"}, _FIELDS)
        message = str(exc.value)
        assert "Unknown custom field 'cf_99'" in message
        assert "no issue custom field with id 99 is enabled" in message
        assert "'Department' (cf_2)" in message
        assert "'Priority Level' (cf_1)" in message
        assert "Nothing was written" in message

    def test_a_project_with_no_custom_fields_says_so(self):
        with pytest.raises(ValueError, match="Custom fields on this project: none"):
            _resolve_named_custom_fields({"cf_99": "x"}, [])

    def test_the_shape_is_exact(self):
        # ``cf_`` with no digits or with a suffix is not an id and keeps the
        # snake_case passthrough that plugin attributes rely on.
        for key in ("cf_", "cf_12x", "cf_12_extra"):
            payload = _resolve_named_custom_fields({key: "x"}, _FIELDS)
            assert payload == {key: "x"}

    def test_only_ascii_digits_make_an_id(self):
        # A fullwidth digit is not how Redmine writes an id. The key is not
        # attribute-shaped either, so it is refused as an unknown name rather
        # than read as cf_1.
        with pytest.raises(ValueError, match="Unknown custom field 'cf_\uff11'"):
            _resolve_named_custom_fields({"cf_\uff11": "x"}, _FIELDS)

    def test_the_id_reading_wins_over_a_field_named_like_a_cf_key(self):
        fields = [SimpleNamespace(id=9, name="cf_3", possible_values=None)]
        with pytest.raises(ValueError, match=r"'cf_3' \(cf_9\)"):
            _resolve_named_custom_fields({"cf_3": "x"}, fields)
        payload = _resolve_named_custom_fields({"cf_9": "x"}, fields)
        assert payload == {"custom_fields": [{"id": 9, "value": "x"}]}


def _issue_stub(**overrides):
    base = dict(
        id=42,
        project=SimpleNamespace(id=1, name="Test"),
        tracker=SimpleNamespace(id=1, name="Bug"),
        status=SimpleNamespace(id=1, name="New"),
        priority=SimpleNamespace(id=1, name="Normal"),
        author=SimpleNamespace(id=1, name="Test User"),
        subject="X",
        description="",
        created_on=None,
        updated_on=None,
        custom_fields=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_create_sends_a_cf_key_as_a_custom_field(mock_redmine):
    mock_redmine.project.get.return_value = SimpleNamespace(
        issue_custom_fields=_FIELDS, raw=lambda: {"issue_custom_fields": _FIELDS}
    )
    mock_redmine.issue.create.return_value = _issue_stub()

    result = await create_redmine_issue(
        project_id=1, subject="X", fields={"cf_2": "Sales", "cf_1": "High"}
    )

    assert "error" not in result
    kwargs = mock_redmine.issue.create.call_args.kwargs
    assert {"id": 2, "value": "Sales"} in kwargs["custom_fields"]
    assert {"id": 1, "value": "High"} in kwargs["custom_fields"]
    assert "cf_2" not in kwargs and "cf_1" not in kwargs
    assert "unverified_fields" not in result


@pytest.mark.asyncio
@patch("redmine_mcp_server._client.redmine")
async def test_create_refuses_an_unknown_id_before_writing(mock_redmine):
    mock_redmine.project.get.return_value = SimpleNamespace(
        issue_custom_fields=_FIELDS, raw=lambda: {"issue_custom_fields": _FIELDS}
    )

    result = await create_redmine_issue(project_id=1, subject="X", fields={"cf_99": 1})

    assert "Unknown custom field 'cf_99'" in result["error"]
    mock_redmine.issue.create.assert_not_called()


@pytest.mark.asyncio
async def test_update_refuses_an_unknown_id_before_writing():
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
        result = await update_redmine_issue(5, {"cf_99": "x", "notes": "n"})
    assert "Unknown custom field 'cf_99'" in result["error"]
    client.issue.update.assert_not_called()
