"""
Unit tests for custom field helper functions (redmine_handler.py lines 474-640).

TDD RED phase: All 44 tests written at once against existing implementation.
Reference: tdd-plan-custom-field-helpers.md (validated 2026-02-19)
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime  # noqa: E402

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    _is_true_env,
    _normalize_field_label,
    _parse_create_issue_fields,
    _parse_optional_object_payload,
    _extract_possible_values,
    _extract_missing_required_field_names,
    _load_required_custom_field_defaults,
    _is_missing_custom_field_value,
    _is_allowed_custom_field_value,
    _resolve_required_custom_field_value,
    _coerce_json_safe,
    _coerce_update_custom_fields,
    _upsert_custom_field_entry,
    _custom_fields_to_list,
    _custom_field_trackers_to_list,
    _custom_field_applies_to_tracker,
)

# ── Cycle 1: _is_true_env ───────────────────────────────────────────


class TestIsTrueEnv:
    """Tests for _is_true_env helper (lines 474-476)."""

    @patch.dict(os.environ, {}, clear=False)
    def test_truthy_values(self):
        for val in ("true", "1", "yes", "on"):
            os.environ["TEST_VAR"] = val
            assert _is_true_env("TEST_VAR") is True, f"Expected True for {val!r}"

    @patch.dict(os.environ, {}, clear=False)
    def test_falsy_values(self):
        for val in ("false", "0", "no", ""):
            os.environ["TEST_VAR"] = val
            assert _is_true_env("TEST_VAR") is False, f"Expected False for {val!r}"

    @patch.dict(os.environ, {}, clear=False)
    def test_case_insensitive(self):
        for val in ("TRUE", "True", "YES"):
            os.environ["TEST_VAR"] = val
            assert _is_true_env("TEST_VAR") is True, f"Expected True for {val!r}"

    @patch.dict(os.environ, {}, clear=False)
    def test_whitespace_stripped(self):
        for val in (" true ", " 1 "):
            os.environ["TEST_VAR"] = val
            assert _is_true_env("TEST_VAR") is True, f"Expected True for {val!r}"

    def test_missing_env_var_uses_default(self):
        os.environ.pop("TEST_VAR", None)
        assert _is_true_env("TEST_VAR") is False
        assert _is_true_env("TEST_VAR", "true") is True


# ── Cycle 2: _normalize_field_label ─────────────────────────────────


class TestNormalizeFieldLabel:
    """Tests for _normalize_field_label helper (lines 479-481)."""

    def test_spaces_and_case(self):
        assert _normalize_field_label("Project Category") == "projectcategory"

    def test_special_characters(self):
        assert _normalize_field_label("Field-Name_v2!") == "fieldnamev2"

    def test_already_normalized(self):
        assert _normalize_field_label("projectcategory") == "projectcategory"


# ── Cycle 3: _parse_create_issue_fields ─────────────────────────────


class TestParseCreateIssueFields:
    """Tests for _parse_create_issue_fields (lines 484-523)."""

    def test_none_returns_empty(self):
        assert _parse_create_issue_fields(None) == {}

    def test_dict_returns_shallow_copy(self):
        original = {"tracker_id": 5}
        result = _parse_create_issue_fields(original)
        assert result == {"tracker_id": 5}
        assert result is not original

    def test_non_string_non_dict_raises(self):
        with pytest.raises(ValueError, match="Expected a dict or JSON"):
            _parse_create_issue_fields(12345)

    def test_empty_string_returns_empty(self):
        assert _parse_create_issue_fields("") == {}

    def test_valid_json_object_string(self):
        result = _parse_create_issue_fields('{"tracker_id": 5}')
        assert result == {"tracker_id": 5}

    def test_invalid_json_raises(self):
        """Invalid JSON string raises ValueError with guidance."""
        with pytest.raises(ValueError, match="Invalid fields payload"):
            _parse_create_issue_fields("not valid json")

    def test_json_null_raises(self):
        with pytest.raises(ValueError, match="Parsed value must be an object/dict"):
            _parse_create_issue_fields("null")

    def test_fields_wrapper_unwrapped(self):
        result = _parse_create_issue_fields('{"fields": {"tracker_id": 5}}')
        assert result == {"tracker_id": 5}

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match="Parsed value must be an object/dict"):
            _parse_create_issue_fields("[1, 2, 3]")


# ── Cycle 4: _extract_possible_values ───────────────────────────────


class TestExtractPossibleValues:
    """Tests for _extract_possible_values (lines 526-537)."""

    def test_dict_values(self):
        field = Mock()
        field.possible_values = [{"value": "A"}, {"value": "B"}]
        assert _extract_possible_values(field) == ["A", "B"]

    def test_object_values(self):
        field = Mock()
        field.possible_values = [Mock(value="X"), Mock(value="Y")]
        assert _extract_possible_values(field) == ["X", "Y"]

    def test_plain_string_values(self):
        field = Mock()
        field.possible_values = ["foo", "bar"]
        assert _extract_possible_values(field) == ["foo", "bar"]

    def test_none_value_skipped(self):
        field = Mock()
        field.possible_values = [{"value": None}, {"value": "A"}]
        assert _extract_possible_values(field) == ["A"]

    def test_no_possible_values_attr(self):
        field = Mock(spec=[])
        assert _extract_possible_values(field) == []


# ── Cycle 5: _extract_missing_required_field_names ──────────────────


class TestExtractMissingRequiredFieldNames:
    """Tests for _extract_missing_required_field_names (line 575)."""

    def test_with_validation_failed_prefix(self):
        msg = "Validation failed: Project Category cannot be blank"
        assert _extract_missing_required_field_names(msg) == ["Project Category"]

    def test_without_prefix(self):
        msg = "OS Field cannot be blank"
        assert _extract_missing_required_field_names(msg) == ["OS Field"]

    def test_multiple_fields_with_prefix(self):
        msg = (
            "Validation failed: Field A cannot be blank, "
            "Field B is not included in the list"
        )
        assert _extract_missing_required_field_names(msg) == [
            "Field A",
            "Field B",
        ]


# ── Cycle 6: _load_required_custom_field_defaults ───────────────────


class TestLoadRequiredCustomFieldDefaults:
    """Tests for _load_required_custom_field_defaults (lines 540-563)."""

    @patch(
        "redmine_mcp_server.redmine_handler._DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES",
        {},
    )
    def test_empty_env_returns_builtin_defaults(self):
        os.environ.pop("REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS", None)
        result = _load_required_custom_field_defaults()
        assert result == {}

    @patch(
        "redmine_mcp_server.redmine_handler._DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES",
        {},
    )
    @patch.dict(
        os.environ,
        {"REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS": '{"Project Category": "Any"}'},
        clear=False,
    )
    def test_valid_json_object_merges(self):
        result = _load_required_custom_field_defaults()
        assert result == {"projectcategory": "Any"}

    @patch(
        "redmine_mcp_server.redmine_handler._DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES",
        {},
    )
    @patch.dict(
        os.environ,
        {"REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS": "[1, 2, 3]"},
        clear=False,
    )
    def test_non_dict_json_warns(self):
        result = _load_required_custom_field_defaults()
        assert result == {}

    @patch(
        "redmine_mcp_server.redmine_handler._DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES",
        {},
    )
    @patch.dict(
        os.environ,
        {"REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS": "{bad"},
        clear=False,
    )
    def test_invalid_json_warns(self):
        result = _load_required_custom_field_defaults()
        assert result == {}

    @patch(
        "redmine_mcp_server.redmine_handler._DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES",
        {},
    )
    @patch.dict(
        os.environ,
        {"REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS": '{"A": null, "B": "val"}'},
        clear=False,
    )
    def test_none_values_skipped(self):
        result = _load_required_custom_field_defaults()
        assert result == {"b": "val"}


# ── Cycle 7: _is_missing_custom_field_value ─────────────────────────


class TestIsMissingCustomFieldValue:
    """Tests for _is_missing_custom_field_value (lines 600-608)."""

    def test_none_is_missing(self):
        assert _is_missing_custom_field_value(None) is True

    def test_empty_string_is_missing(self):
        assert _is_missing_custom_field_value("") is True

    def test_whitespace_string_is_missing(self):
        assert _is_missing_custom_field_value("  ") is True

    def test_empty_collections_are_missing(self):
        assert _is_missing_custom_field_value([]) is True
        assert _is_missing_custom_field_value({}) is True
        assert _is_missing_custom_field_value(set()) is True

    def test_non_missing_values(self):
        assert _is_missing_custom_field_value("value") is False
        assert _is_missing_custom_field_value(0) is False
        assert _is_missing_custom_field_value(42) is False
        assert _is_missing_custom_field_value(False) is False


# ── Cycle 8: _is_allowed_custom_field_value ─────────────────────────


class TestIsAllowedCustomFieldValue:
    """Tests for _is_allowed_custom_field_value (lines 611-617)."""

    def test_empty_possible_values_allows_any(self):
        assert _is_allowed_custom_field_value("anything", []) is True

    def test_scalar_in_list(self):
        assert _is_allowed_custom_field_value("A", ["A", "B"]) is True

    def test_scalar_not_in_list(self):
        assert _is_allowed_custom_field_value("C", ["A", "B"]) is False

    def test_list_all_allowed(self):
        assert _is_allowed_custom_field_value(["A", "B"], ["A", "B", "C"]) is True

    def test_list_one_not_allowed(self):
        assert _is_allowed_custom_field_value(["A", "X"], ["A", "B"]) is False


# ── Cycle 9: _resolve_required_custom_field_value ───────────────────


class TestResolveRequiredCustomFieldValue:
    """Tests for _resolve_required_custom_field_value (lines 620-640)."""

    def test_returns_default_value(self):
        mock_field = Mock()
        mock_field.name = "Category"
        mock_field.default_value = "Foo"
        mock_field.possible_values = [{"value": "Foo"}]

        result = _resolve_required_custom_field_value(mock_field, {})
        assert result == "Foo"

    def test_falls_back_to_env_default(self):
        mock_field = Mock()
        mock_field.name = "Category"
        mock_field.default_value = None
        mock_field.possible_values = [{"value": "Any"}]

        result = _resolve_required_custom_field_value(mock_field, {"category": "Any"})
        assert result == "Any"

    def test_returns_none_when_nothing_resolves(self):
        mock_field = Mock()
        mock_field.name = "Field"
        mock_field.default_value = None
        mock_field.possible_values = [{"value": "X"}]

        result = _resolve_required_custom_field_value(mock_field, {})
        assert result is None

    def test_invalid_default_falls_through(self):
        mock_field = Mock()
        mock_field.name = "Field"
        mock_field.default_value = "Invalid"
        mock_field.possible_values = [{"value": "X"}]

        result = _resolve_required_custom_field_value(mock_field, {"field": "X"})
        assert result == "X"


# ── Cycle 10: _parse_optional_object_payload ──────────────────────────


class TestParseOptionalObjectPayload:
    """Tests for _parse_optional_object_payload."""

    def test_none_returns_empty(self):
        assert _parse_optional_object_payload(None, "test") == {}

    def test_dict_returns_shallow_copy(self):
        original = {"key": "value"}
        result = _parse_optional_object_payload(original, "test")
        assert result == original
        assert result is not original

    def test_empty_string_returns_empty(self):
        assert _parse_optional_object_payload("", "test") == {}

    def test_valid_json_string(self):
        result = _parse_optional_object_payload('{"a": 1}', "test")
        assert result == {"a": 1}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid test payload"):
            _parse_optional_object_payload("bad json", "test")

    def test_non_dict_type_raises(self):
        with pytest.raises(ValueError, match="Invalid test payload"):
            _parse_optional_object_payload(12345, "test")

    def test_json_null_raises(self):
        with pytest.raises(ValueError, match="Parsed value must be"):
            _parse_optional_object_payload("null", "test")

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match="Parsed value must be"):
            _parse_optional_object_payload("[1, 2]", "test")

    def test_wrapper_unwrapped(self):
        """{"test": {"a": 1}} is unwrapped when payload_name="test"."""
        result = _parse_optional_object_payload('{"test": {"a": 1}}', "test")
        assert result == {"a": 1}

    def test_payload_name_in_error_message(self):
        """Error messages include the payload_name for context."""
        with pytest.raises(ValueError, match="extra_fields"):
            _parse_optional_object_payload("bad", "extra_fields")


# ── Cycle 11: _coerce_json_safe ───────────────────────────────────────


class TestCoerceJsonSafe:
    """Tests for _coerce_json_safe."""

    def test_none_passthrough(self):
        assert _coerce_json_safe(None) is None

    def test_primitives_passthrough(self):
        assert _coerce_json_safe("hello") == "hello"
        assert _coerce_json_safe(42) == 42
        assert _coerce_json_safe(3.14) == 3.14
        assert _coerce_json_safe(True) is True

    def test_datetime_to_isoformat(self):
        dt = datetime(2025, 6, 15, 10, 30, 0)
        assert _coerce_json_safe(dt) == "2025-06-15T10:30:00"

    def test_list_recursive(self):
        assert _coerce_json_safe([1, "a", None]) == [1, "a", None]

    def test_tuple_to_list(self):
        assert _coerce_json_safe((1, 2)) == [1, 2]

    def test_set_to_list(self):
        result = _coerce_json_safe({1})
        assert isinstance(result, list)
        assert result == [1]

    def test_dict_recursive(self):
        assert _coerce_json_safe({"a": 1}) == {"a": 1}

    def test_dict_non_string_keys(self):
        result = _coerce_json_safe({1: "val"})
        assert result == {"1": "val"}

    def test_custom_object_to_string(self):
        obj = Mock()
        obj.__str__ = Mock(return_value="mock_str")
        result = _coerce_json_safe(obj)
        assert isinstance(result, str)


# ── Cycle 12: _coerce_update_custom_fields ────────────────────────────


class TestCoerceUpdateCustomFields:
    """Tests for _coerce_update_custom_fields."""

    def test_none_returns_empty(self):
        assert _coerce_update_custom_fields(None) == []

    def test_valid_list(self):
        result = _coerce_update_custom_fields([{"id": 1, "value": "x"}])
        assert result == [{"id": 1, "value": "x"}]

    def test_missing_value_key(self):
        result = _coerce_update_custom_fields([{"id": 1}])
        assert result == [{"id": 1, "value": None}]

    def test_not_a_list_raises(self):
        with pytest.raises(ValueError, match="Expected a list"):
            _coerce_update_custom_fields("bad")

    def test_entry_not_dict_raises(self):
        with pytest.raises(ValueError, match="Expected a list"):
            _coerce_update_custom_fields(["bad"])

    def test_entry_missing_id_raises(self):
        with pytest.raises(ValueError, match="Missing required 'id'"):
            _coerce_update_custom_fields([{"value": "x"}])

    def test_empty_list(self):
        assert _coerce_update_custom_fields([]) == []


# ── Cycle 13: _upsert_custom_field_entry ──────────────────────────────


class TestUpsertCustomFieldEntry:
    """Tests for _upsert_custom_field_entry."""

    def test_insert_new(self):
        entries = []
        _upsert_custom_field_entry(entries, 1, "val")
        assert entries == [{"id": 1, "value": "val"}]

    def test_update_existing(self):
        entries = [{"id": 1, "value": "old"}]
        _upsert_custom_field_entry(entries, 1, "new")
        assert entries == [{"id": 1, "value": "new"}]

    def test_preserves_other_entries(self):
        entries = [
            {"id": 1, "value": "a"},
            {"id": 2, "value": "b"},
        ]
        _upsert_custom_field_entry(entries, 1, "updated")
        assert len(entries) == 2
        assert entries[0] == {"id": 1, "value": "updated"}
        assert entries[1] == {"id": 2, "value": "b"}


# ── Cycle 14: _custom_fields_to_list ─────────────────────────────────


class TestCustomFieldsToList:
    """Tests for _custom_fields_to_list."""

    def test_no_attribute(self):
        issue = Mock(spec=[])  # no custom_fields
        assert _custom_fields_to_list(issue) == []

    def test_none_attribute(self):
        issue = Mock()
        issue.custom_fields = None
        assert _custom_fields_to_list(issue) == []

    def test_not_iterable(self):
        issue = Mock()
        issue.custom_fields = 42
        assert _custom_fields_to_list(issue) == []

    def test_object_entries(self):
        cf = Mock()
        cf.id = 6
        cf.name = "Size"
        cf.value = "M"
        issue = Mock()
        issue.custom_fields = [cf]
        result = _custom_fields_to_list(issue)
        assert result == [{"id": 6, "name": "Size", "value": "M"}]

    def test_dict_entries(self):
        issue = Mock()
        issue.custom_fields = [{"id": 6, "name": "Size", "value": "M"}]
        result = _custom_fields_to_list(issue)
        assert result == [{"id": 6, "name": "Size", "value": "M"}]

    def test_empty_list(self):
        issue = Mock()
        issue.custom_fields = []
        assert _custom_fields_to_list(issue) == []


# ── Cycle 15: _custom_field_trackers_to_list ──────────────────────────


class TestCustomFieldTrackersToList:
    """Tests for _custom_field_trackers_to_list."""

    def test_no_trackers_attribute(self):
        cf = Mock(spec=[])
        assert _custom_field_trackers_to_list(cf) == []

    def test_none_trackers(self):
        cf = Mock()
        cf.trackers = None
        assert _custom_field_trackers_to_list(cf) == []

    def test_not_iterable(self):
        cf = Mock()
        cf.trackers = 42
        assert _custom_field_trackers_to_list(cf) == []

    def test_object_trackers(self):
        t = Mock()
        t.id = 5
        t.name = "Bug"
        cf = Mock()
        cf.trackers = [t]
        result = _custom_field_trackers_to_list(cf)
        assert result == [{"id": 5, "name": "Bug"}]

    def test_dict_trackers(self):
        cf = Mock()
        cf.trackers = [{"id": 5, "name": "Bug"}]
        result = _custom_field_trackers_to_list(cf)
        assert result == [{"id": 5, "name": "Bug"}]

    def test_string_id_coerced_to_int(self):
        cf = Mock()
        cf.trackers = [{"id": "5", "name": "Bug"}]
        result = _custom_field_trackers_to_list(cf)
        assert result[0]["id"] == 5

    def test_non_numeric_id_coerced_to_string(self):
        cf = Mock()
        cf.trackers = [{"id": "abc", "name": "Bug"}]
        result = _custom_field_trackers_to_list(cf)
        assert result[0]["id"] == "abc"

    def test_both_none_skipped(self):
        cf = Mock()
        cf.trackers = [{"id": None, "name": None}]
        assert _custom_field_trackers_to_list(cf) == []


# ── Cycle 16: _custom_field_applies_to_tracker ────────────────────────


class TestCustomFieldAppliesToTracker:
    """Tests for _custom_field_applies_to_tracker."""

    def test_none_tracker_id_always_applies(self):
        cf = Mock()
        assert _custom_field_applies_to_tracker(cf, None) is True

    def test_no_tracker_restrictions_applies(self):
        cf = Mock()
        cf.trackers = []
        assert _custom_field_applies_to_tracker(cf, 5) is True

    def test_matching_tracker(self):
        t = Mock()
        t.id = 5
        t.name = "Bug"
        cf = Mock()
        cf.trackers = [t]
        assert _custom_field_applies_to_tracker(cf, 5) is True

    def test_non_matching_tracker(self):
        t = Mock()
        t.id = 7
        t.name = "Feature"
        cf = Mock()
        cf.trackers = [t]
        assert _custom_field_applies_to_tracker(cf, 5) is False
