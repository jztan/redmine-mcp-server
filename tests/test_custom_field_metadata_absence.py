"""Custom field metadata must never be invented (#232).

``list_project_issue_custom_fields`` reads
``GET /projects/{id}.json?include=issue_custom_fields``, which Redmine renders
as exactly ``id`` and ``name`` per field. Every other key it advertises has to
come back ``null``, because a plausible-looking default -- ``is_required:
false``, ``possible_values: []`` -- is byte-identical to a real answer and a
caller cannot tell it apart.

These tests deliberately avoid ``Mock``. A ``Mock`` answers every attribute
access, so a serializer reading attributes Redmine never sent looks correct
under it; that is why the fabricated defaults survived. The fakes here raise
``ResourceAttrError`` for absent attributes, exactly as python-redmine does.
"""

import os
import sys

import pytest
from redminelib.exceptions import ResourceAttrError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.projects import (  # noqa: E402
    _custom_field_to_dict,
    list_project_issue_custom_fields,
)

# The six keys the project include can never populate.
UNKNOWABLE_KEYS = (
    "field_format",
    "is_required",
    "multiple",
    "default_value",
    "possible_values",
    "trackers",
)


class _Field:
    """Base for the include fakes: carries only what the include carries."""

    def __init__(self, field_id, name):
        self.id = field_id
        self.name = name


class IncludeField(_Field):
    """A custom field as python-redmine builds it from the project include.

    Carries ``id`` and ``name``; every other attribute raises
    ``ResourceAttrError`` (an ``AttributeError`` subclass), which is what
    python-redmine does for an attribute absent from the response.
    """

    def __getattr__(self, attr):
        raise ResourceAttrError()


class RelaxedIncludeField(_Field):
    """The same payload under a ``raise_attr_exception=False`` client.

    python-redmine then returns ``None`` for a missing attribute instead of
    raising. ``None`` is the honest answer either way -- what must not happen
    is it being coerced to ``False`` or ``[]``.
    """

    def __getattr__(self, attr):
        return None


class AdminField:
    """A custom field as ``GET /custom_fields.json`` renders it.

    Not reachable through this tool today, but the serializer must pass real
    metadata through untouched if a payload ever carries it -- a future
    Redmine (redmine.org #43407) or a plugin.
    """

    def __init__(self, field_id, name, trackers):
        self.id = field_id
        self.name = name
        self.field_format = "list"
        self.is_required = True
        self.multiple = True
        self.default_value = "M"
        self.possible_values = [{"value": "S"}, {"value": "M"}, {"value": "L"}]
        self.trackers = trackers


class Tracker:
    def __init__(self, tracker_id, name):
        self.id = tracker_id
        self.name = name


class FakeProject:
    def __init__(self, custom_fields):
        self.issue_custom_fields = custom_fields


class TestSerializerNeverInvents:
    """The serializer reports absence as absence."""

    @pytest.mark.parametrize("field_cls", [IncludeField, RelaxedIncludeField])
    def test_every_unknowable_key_is_null(self, field_cls):
        """Absence answers null under both client configurations.

        The regression this guards: ``false`` and ``[]`` are byte-identical
        to real answers, so a caller cannot tell an invented default from a
        value Redmine actually sent. ``is None`` covers all of them at once.
        """
        result = _custom_field_to_dict(field_cls(6, "Size"))

        assert result["id"] == 6
        assert result["name"] == "Size"
        for key in UNKNOWABLE_KEYS:
            assert result[key] is None, f"{key} was invented"

    def test_required_field_does_not_report_false(self):
        """Acceptance test: a field marked Required must not come back false.

        The project include cannot say the field is required, so the only
        correct answer is ``null``. ``false`` would be a claim Redmine never
        made, and the caller acts on it -- omits the field, and the create
        rejects with "cannot be blank".
        """
        result = _custom_field_to_dict(IncludeField(2, "Department"))

        assert result["is_required"] is None
        assert result["is_required"] is not False

    def test_real_metadata_passes_through(self):
        result = _custom_field_to_dict(AdminField(6, "Size", [Tracker(5, "Bug")]))

        assert result["field_format"] == "list"
        assert result["is_required"] is True
        assert result["multiple"] is True
        assert result["default_value"] == "M"
        assert result["possible_values"] == ["S", "M", "L"]
        assert result["trackers"] == [{"id": 5, "name": "Bug"}]

    def test_genuinely_empty_bindings_stay_an_empty_list(self):
        """An empty list is data; only absence is null."""
        result = _custom_field_to_dict(AdminField(6, "Size", []))

        assert result["trackers"] == []


class TestTrackerFilterHonesty:
    """``tracker_id`` refuses rather than returning an unfiltered list."""

    @pytest.fixture
    def client(self, monkeypatch):
        class FakeClient:
            def __init__(self):
                self.project = self

            def get(self, project_id, **kwargs):
                return self.project_obj

        fake = FakeClient()
        monkeypatch.setattr("redmine_mcp_server._client.redmine", fake)
        return fake

    @pytest.mark.asyncio
    async def test_errors_when_bindings_are_not_readable(self, client):
        """The filter cannot work, so say so instead of answering wrongly.

        Before this fix an unreadable binding was read as "applies to every
        tracker", so the tool returned every field in the project and the
        caller had no way to know its filter had been dropped.
        """
        client.project_obj = FakeProject(
            [IncludeField(10, "Size"), IncludeField(11, "Department")]
        )

        result = await list_project_issue_custom_fields(project_id=41, tracker_id=5)

        assert isinstance(result, dict)
        assert result["code"] == "TRACKER_BINDINGS_UNREADABLE"
        assert "tracker_id" in result["error"]
        # The error describes this response; the standing Redmine explanation
        # belongs in the hint, so it cannot become a false claim on a
        # deployment where bindings really are readable.
        assert "Omit tracker_id" in result["hint"]
        assert "admin-only" in result["hint"]

    @pytest.mark.asyncio
    async def test_without_tracker_id_the_list_is_returned(self, client):
        client.project_obj = FakeProject([IncludeField(10, "Size")])

        result = await list_project_issue_custom_fields(project_id=41)

        assert isinstance(result, list)
        assert [field["id"] for field in result] == [10]

    @pytest.mark.asyncio
    async def test_filters_when_bindings_are_readable(self, client):
        bug = Tracker(5, "Bug")
        feature = Tracker(7, "Feature")
        client.project_obj = FakeProject(
            [
                AdminField(10, "Bug-only", [bug]),
                AdminField(11, "Feature-only", [feature]),
            ]
        )

        result = await list_project_issue_custom_fields(project_id=41, tracker_id=5)

        assert [field["id"] for field in result] == [10]

    @pytest.mark.asyncio
    async def test_field_bound_to_no_tracker_is_excluded(self, client):
        """Redmine intersects; an unbound field applies to no tracker.

        ``Issue#available_custom_fields`` is ``project.all_issue_custom_fields
        & tracker.custom_fields``, so a field with no trackers selected
        reaches no issue. It must not be reported as applying to tracker 5.
        """
        client.project_obj = FakeProject(
            [
                AdminField(10, "Bug-only", [Tracker(5, "Bug")]),
                AdminField(12, "Unbound", []),
            ]
        )

        result = await list_project_issue_custom_fields(project_id=41, tracker_id=5)

        assert [field["id"] for field in result] == [10]

    @pytest.mark.asyncio
    async def test_empty_project_does_not_error_on_tracker_id(self, client):
        """Nothing to filter is not a failure to filter."""
        client.project_obj = FakeProject([])

        result = await list_project_issue_custom_fields(project_id=41, tracker_id=5)

        assert result == []
