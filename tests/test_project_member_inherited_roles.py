"""Project membership roles keep Redmine's ``inherited`` flag (#ISSUE).

Redmine's ``app/views/members/index.api.rsb`` and ``show.api.rsb`` merge
``inherited => true`` onto a role whose member role has an ``inherited_from``:
one that comes from a group the user belongs to, or from the parent of a
subproject that inherits members. The key is omitted for a role held
directly. ``_membership_to_dict`` used to flatten every role to ``{id, name}``,
so ``list_project_members`` and ``manage_project_member(action="add" |
"update")`` reported a group-derived Manager role exactly like a direct one,
while ``get_current_user(include_memberships=True)`` kept the flag.

These tests build real python-redmine resources from a payload shaped like
that renderer's output rather than using ``Mock``: a ``Mock`` role answers
``inherited`` with a truthy ``Mock`` whether or not Redmine sent it, so it
cannot tell a mirrored key from an invented one.
"""

from unittest.mock import patch

import pytest
from redminelib import Redmine

from redmine_mcp_server._serialization import _membership_roles_to_list
from redmine_mcp_server.tools.projects import (
    _membership_to_dict,
    list_project_members,
    manage_project_member,
)

# Two memberships as members/index.api.rsb renders them. Alice holds
# Developer directly and Manager through a group; the Dev Team group's own
# membership carries Manager directly.
MEMBERSHIPS_PAYLOAD = [
    {
        "id": 1,
        "project": {"id": 10, "name": "Website"},
        "user": {"id": 5, "name": "Alice A"},
        "roles": [
            {"id": 3, "name": "Developer"},
            {"id": 4, "name": "Manager", "inherited": True},
        ],
    },
    {
        "id": 2,
        "project": {"id": 10, "name": "Website"},
        "group": {"id": 15, "name": "Dev Team"},
        "roles": [{"id": 4, "name": "Manager"}],
    },
]


def _client() -> Redmine:
    return Redmine("https://redmine.example.test", key="unused")


def _membership(payload):
    return _client().project_membership.to_resource(payload)


class TestMembershipToDictInherited:
    def test_inherited_role_keeps_the_flag(self):
        result = _membership_to_dict(_membership(MEMBERSHIPS_PAYLOAD[0]))

        assert result["roles"] == [
            {"id": 3, "name": "Developer"},
            {"id": 4, "name": "Manager", "inherited": True},
        ]

    def test_direct_role_carries_no_inherited_key(self):
        """Redmine omits the key for a direct role; so does the tool.

        A hard-coded ``inherited: False`` would assert something Redmine
        never said.
        """
        result = _membership_to_dict(_membership(MEMBERSHIPS_PAYLOAD[1]))

        assert result["roles"] == [{"id": 4, "name": "Manager"}]
        assert "inherited" not in result["roles"][0]

    def test_role_held_both_ways_is_listed_twice(self):
        """Direct and inherited copies of one role are separate facts."""
        payload = dict(
            MEMBERSHIPS_PAYLOAD[0],
            roles=[
                {"id": 4, "name": "Manager"},
                {"id": 4, "name": "Manager", "inherited": True},
            ],
        )

        result = _membership_to_dict(_membership(payload))

        assert result["roles"] == [
            {"id": 4, "name": "Manager"},
            {"id": 4, "name": "Manager", "inherited": True},
        ]

    def test_the_rest_of_the_row_is_unchanged(self):
        result = _membership_to_dict(_membership(MEMBERSHIPS_PAYLOAD[0]))

        assert result["id"] == 1
        assert result["user"] == {"id": 5, "name": "Alice A"}
        assert result["group"] is None
        assert result["project"] == {"id": 10, "name": "Website"}


class TestMembershipRolesToList:
    def test_payload_dicts(self):
        """The ``get_current_user`` path hands over decoded payload dicts."""
        roles = _membership_roles_to_list(MEMBERSHIPS_PAYLOAD[0]["roles"])

        assert roles == [
            {"id": 3, "name": "Developer"},
            {"id": 4, "name": "Manager", "inherited": True},
        ]

    @pytest.mark.parametrize("value", [None, "Manager", {"id": 4}, 42])
    def test_not_a_role_list(self, value):
        assert _membership_roles_to_list(value) == []


class TestProjectMemberToolsInherited:
    @pytest.mark.asyncio
    async def test_list_project_members(self):
        client = _client()
        memberships = [
            client.project_membership.to_resource(m) for m in MEMBERSHIPS_PAYLOAD
        ]
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.project_membership.filter.return_value = memberships
            result = await list_project_members(project_id=10)

        assert result[0]["roles"][1] == {
            "id": 4,
            "name": "Manager",
            "inherited": True,
        }
        assert "inherited" not in result[0]["roles"][0]
        assert "inherited" not in result[1]["roles"][0]

    @pytest.mark.asyncio
    async def test_update_project_member(self):
        """``update`` re-reads through members/show.api.rsb, same line."""
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.project_membership.get.return_value = _membership(
                MEMBERSHIPS_PAYLOAD[0]
            )
            result = await manage_project_member(
                action="update", membership_id=1, role_ids=[3]
            )

        assert result["roles"] == [
            {"id": 3, "name": "Developer"},
            {"id": 4, "name": "Manager", "inherited": True},
        ]
