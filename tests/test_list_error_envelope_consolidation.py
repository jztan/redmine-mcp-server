"""Cross-tool regression: all list/search tools return a dict envelope on error (#117).

Before #117 the error envelope for list-shaped tools was inconsistent:
some tools returned ``[{"error": "..."}]`` (array-wrapped), others
returned ``{"error": "..."}`` (flat dict). An agent had to know which
shape each tool produced to recover. After #117 every list/search
tool returns the flat dict shape on error, and the success path is
the only one that returns a list.

This test fires a controlled exception inside each tool's underlying
client call and asserts the resulting envelope is a dict with an
``error`` key, never an array.
"""

from unittest.mock import Mock, patch

import pytest

from redmine_mcp_server.tools.enumeration import (
    list_redmine_issue_priorities,
    list_redmine_issue_statuses,
    list_redmine_trackers,
    list_redmine_users,
)
from redmine_mcp_server.tools.files import list_files
from redmine_mcp_server.tools.issues import (
    list_redmine_issues,
    list_subtasks,
)
from redmine_mcp_server.tools.projects import (
    list_project_issue_custom_fields,
    list_project_members,
    list_redmine_projects,
    list_redmine_roles,
    list_redmine_versions,
)
from redmine_mcp_server.tools.time_tracking import (
    list_time_entries,
    list_time_entry_activities,
)


def _is_dict_envelope(result) -> bool:
    """Per #117, error returns must be flat dicts (not array-wrapped)."""
    return isinstance(result, dict) and "error" in result


# (callable, kwargs, redmine_attr_to_break)
# `redmine_attr_to_break` is the attribute on the mocked redmine
# client that we make raise -- this exercises the tool's `except`
# block.
_LIST_TOOL_CASES = [
    (list_redmine_projects, {}, "project.all"),
    (list_redmine_issues, {"project_id": 1}, "issue.filter"),
    (list_project_issue_custom_fields, {"project_id": 1}, "project.get"),
    (list_redmine_versions, {"project_id": 1}, "version.filter"),
    (list_project_members, {"project_id": 1}, "project_membership.filter"),
    (list_redmine_roles, {}, "role.all"),
    (list_redmine_trackers, {}, "tracker.all"),
    (list_redmine_issue_statuses, {}, "issue_status.all"),
    (list_redmine_issue_priorities, {}, "enumeration.filter"),
    (list_redmine_users, {}, "user.filter"),
    (list_files, {"project_id": 1}, "file.filter"),
    (list_time_entries, {}, "time_entry.filter"),
    (list_time_entry_activities, {}, "enumeration.filter"),
    (list_subtasks, {"issue_id": 1}, "issue.filter"),
]


def _set_nested(obj, dotted_path, value):
    """Set an attribute reached by a dotted path on a Mock."""
    parts = dotted_path.split(".")
    current = obj
    for part in parts[:-1]:
        current = getattr(current, part)
    setattr(current, parts[-1], value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool, kwargs, attr",
    _LIST_TOOL_CASES,
    ids=lambda v: v.__name__ if callable(v) else str(v),
)
async def test_list_tool_returns_dict_envelope_on_error(tool, kwargs, attr):
    with patch("redmine_mcp_server._client.redmine") as mock_redmine:
        # Force the underlying client call to fail.
        _set_nested(mock_redmine, attr, Mock(side_effect=Exception("boom")))
        result = await tool(**kwargs)

    assert _is_dict_envelope(result), (
        f"{tool.__name__} returned {type(result).__name__}: {result!r}. "
        "Per #117, list/search tools must return a dict envelope on error, "
        "not an array."
    )
