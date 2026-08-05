"""
Test cases for the _named_ref helper with dict-shaped refs.

python-redmine only wraps a nested key as a Resource when the parent
resource lists it in its ``_resource_map``; anything else arrives as a
plain dict.  Redmine 7.0 adding ``project`` to the wiki page API
response (Redmine #43569) is the concrete case.  These tests pin the
dict path so it returns the real id/name instead of silently yielding
``{'id': None, 'name': ''}``.
"""

from unittest.mock import Mock

from redmine_mcp_server._serialization import _named_ref  # noqa: E402


class TestNamedRefDictShape:
    """Unit tests for _named_ref against dict-shaped refs."""

    def test_dict_returns_id_and_name(self):
        ref = {"id": 1, "name": "Platform Test"}
        assert _named_ref(ref) == {"id": 1, "name": "Platform Test"}

    def test_dict_missing_name_falls_back_to_empty_string(self):
        assert _named_ref({"id": 7}) == {"id": 7, "name": ""}

    def test_dict_missing_id_returns_none_id(self):
        assert _named_ref({"name": "No Id"}) == {"id": None, "name": "No Id"}


class TestNamedRefExistingShapes:
    """The None and Resource-like paths are unchanged."""

    def test_none_returns_none(self):
        assert _named_ref(None) is None

    def test_resource_like_object_returns_id_and_name(self):
        obj = Mock(id=42)
        obj.name = "Some User"
        assert _named_ref(obj) == {"id": 42, "name": "Some User"}
