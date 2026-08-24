"""``get_current_user(include_memberships=True)`` returns the caller's
project memberships in one request (#ISSUE).

Before this, nothing exposed "which projects do I hold, with which roles":
``get_current_user`` hand-built eight profile keys and ``list_project_members``
answers one project per call.

Two things these tests pin down:

- The include rides the original ``user.get("current")`` call. python-redmine
  lists ``memberships`` in ``User._includes``, so reading
  ``user.memberships`` without the include makes ``Resource.__getattr__``
  call ``refresh(itself=False, include=...)`` -- a second HTTP request for
  data the first response could have carried.
- The default response is unchanged, key for key.

These tests avoid ``Mock`` for the user object. A ``Mock`` answers every
attribute access, so a serializer reading keys Redmine never sent looks
correct under it, and a lazy ``.memberships`` read would silently succeed.
``FakeUser`` raises ``ResourceAttrError`` for absent attributes exactly as
python-redmine does, and records any lazy read instead of satisfying it.
"""

import os
import sys

import pytest
from redminelib.exceptions import AuthError, ForbiddenError, ResourceAttrError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.enumeration import get_current_user  # noqa: E402

# The eight keys the tool has always returned, in order. The default response
# must stay exactly this -- existing callers index into it.
PROFILE_KEYS = [
    "id",
    "login",
    "firstname",
    "lastname",
    "mail",
    "admin",
    "created_on",
    "last_login_on",
]

PROFILE_PAYLOAD = {
    "id": 5,
    "login": "alice",
    "firstname": "Alice",
    "lastname": "A",
    "mail": "alice@example.com",
    "admin": False,
    "created_on": None,
    "last_login_on": None,
}

# One membership as Redmine's app/views/users/show.api.rsb renders it: id,
# project as {id, name}, roles as {id, name} with inherited => true merged on
# when the role arrives through a group membership. No user/group key -- the
# user is the caller.
MEMBERSHIPS_PAYLOAD = [
    {
        "id": 12,
        "project": {"id": 1, "name": "Website"},
        "roles": [
            {"id": 3, "name": "Developer"},
            {"id": 4, "name": "Manager", "inherited": True},
        ],
    },
    {
        "id": 19,
        "project": {"id": 7, "name": "Infrastructure"},
        "roles": [{"id": 5, "name": "Reporter"}],
    },
]


class FakeUser:
    """A python-redmine ``User`` as ``user.get("current", ...)`` returns one.

    ``raw()`` is python-redmine's accessor for the decoded payload, which is
    where an ``include=`` collection lands. Attributes absent from the payload
    raise ``ResourceAttrError`` (an ``AttributeError`` subclass, so a 3-arg
    ``getattr`` falls back to its default), matching python-redmine under its
    default ``raise_attr_exception=True``.

    Reading ``memberships`` or ``groups`` as an attribute is recorded in
    ``lazy_reads`` and answered with an empty list rather than the payload:
    python-redmine would issue a second HTTP request there, so a non-empty
    ``lazy_reads`` is the regression itself.
    """

    def __init__(self, payload):
        self.__dict__["_payload"] = dict(payload)
        self.__dict__["lazy_reads"] = []

    def raw(self):
        return self.__dict__["_payload"]

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        if attr in ("memberships", "groups"):
            self.__dict__["lazy_reads"].append(attr)
            return []
        payload = self.__dict__["_payload"]
        if attr in payload:
            return payload[attr]
        raise ResourceAttrError()


class FakeClient:
    """Records every ``user.get`` call so the include can be asserted on."""

    def __init__(self, user=None, error=None):
        self.user = self
        self.calls = []
        self._user_obj = user
        self._error = error

    def get(self, resource_id, **kwargs):
        self.calls.append((resource_id, kwargs))
        if self._error is not None:
            raise self._error
        return self._user_obj


@pytest.fixture
def client_factory(monkeypatch):
    def _install(user=None, error=None):
        fake = FakeClient(user=user, error=error)
        monkeypatch.setattr("redmine_mcp_server._client.redmine", fake)
        return fake

    return _install


class TestIncludeRidesTheSameRequest:
    """The anti-regression for the second-request bug."""

    @pytest.mark.asyncio
    async def test_include_is_passed_to_the_client_call(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        fake = client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert fake.calls == [("current", {"include": "memberships"})]
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_memberships_are_read_from_the_payload_not_the_attribute(
        self, client_factory
    ):
        """Reading ``user.memberships`` is what costs the extra round trip."""
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert user.lazy_reads == []
        assert [m["id"] for m in result["memberships"]] == [12, 19]

    @pytest.mark.asyncio
    async def test_only_one_request_is_made(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        fake = client_factory(user=user)

        await get_current_user(include_memberships=True)

        assert len(fake.calls) == 1


class TestMembershipSerialization:
    """Redmine's own keys, nothing renamed and nothing added."""

    @pytest.mark.asyncio
    async def test_uses_redmine_keys(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert result["memberships"] == [
            {
                "id": 12,
                "project": {"id": 1, "name": "Website"},
                "roles": [
                    {"id": 3, "name": "Developer"},
                    {"id": 4, "name": "Manager", "inherited": True},
                ],
            },
            {
                "id": 19,
                "project": {"id": 7, "name": "Infrastructure"},
                "roles": [{"id": 5, "name": "Reporter"}],
            },
        ]

    @pytest.mark.asyncio
    async def test_inherited_is_preserved_on_the_role(self, client_factory):
        """Redmine merges ``inherited`` onto the role, not the membership.

        It is what separates "I hold Manager here" from "a group I am in
        does", so it cannot be dropped.
        """
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)
        roles = result["memberships"][0]["roles"]

        assert roles[1]["inherited"] is True
        assert "inherited" not in result["memberships"][0]

    @pytest.mark.asyncio
    async def test_a_direct_role_carries_no_inherited_key(self, client_factory):
        """Redmine omits the key for a direct role; ``false`` would be
        a claim it never made."""
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert result["memberships"][0]["roles"][0] == {
            "id": 3,
            "name": "Developer",
        }
        assert "inherited" not in result["memberships"][1]["roles"][0]

    @pytest.mark.asyncio
    async def test_no_user_or_group_key_is_emitted(self, client_factory):
        """The user is the caller, implicitly. ``list_project_members``
        emits ``user``/``group``; the user-show renderer emits neither, and
        a ``None`` there would read as a membership naming no principal."""
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        for membership in result["memberships"]:
            assert set(membership) == {"id", "project", "roles"}

    @pytest.mark.asyncio
    async def test_membership_with_no_roles(self, client_factory):
        user = FakeUser(
            {
                **PROFILE_PAYLOAD,
                "memberships": [
                    {"id": 3, "project": {"id": 2, "name": "Docs"}, "roles": []}
                ],
            }
        )
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert result["memberships"] == [
            {"id": 3, "project": {"id": 2, "name": "Docs"}, "roles": []}
        ]

    @pytest.mark.asyncio
    async def test_profile_keys_are_still_present_alongside(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert list(result) == PROFILE_KEYS + ["memberships"]


class TestNoMemberships:
    @pytest.mark.asyncio
    async def test_empty_list_when_the_user_holds_none(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": []})
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert result["memberships"] == []
        assert user.lazy_reads == []

    @pytest.mark.asyncio
    async def test_key_absent_from_the_payload_reads_as_empty(self, client_factory):
        """Redmine omits the array when ``@memberships`` is blank. Reporting
        that as empty is honest; re-fetching to find out is the bug."""
        user = FakeUser(dict(PROFILE_PAYLOAD))
        client_factory(user=user)

        result = await get_current_user(include_memberships=True)

        assert result["memberships"] == []
        assert user.lazy_reads == []


class TestDefaultResponseUnchanged:
    """The flag defaults off and the old response is byte-identical."""

    @pytest.mark.asyncio
    async def test_default_returns_exactly_the_eight_profile_keys(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        result = await get_current_user()

        assert list(result) == PROFILE_KEYS
        assert result == PROFILE_PAYLOAD
        assert "memberships" not in result

    @pytest.mark.asyncio
    async def test_default_sends_no_include(self, client_factory):
        """No include means no query parameter, as before this change."""
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        fake = client_factory(user=user)

        await get_current_user()

        assert fake.calls == [("current", {})]

    @pytest.mark.asyncio
    async def test_default_never_touches_the_lazy_attribute(self, client_factory):
        user = FakeUser({**PROFILE_PAYLOAD, "memberships": MEMBERSHIPS_PAYLOAD})
        client_factory(user=user)

        await get_current_user()

        assert user.lazy_reads == []


class TestGroupsAreNotOffered:
    @pytest.mark.asyncio
    async def test_no_free_text_include_parameter(self, client_factory):
        """python-redmine accepts ``groups`` too, but Redmine gates that
        block on ``User.current.admin?``, so a non-admin gets a 200 with the
        key missing -- indistinguishable from "belongs to no groups". The
        tool exposes memberships specifically rather than passing an
        arbitrary include through."""
        import inspect

        params = inspect.signature(get_current_user).parameters

        assert "include" not in params
        assert "include_memberships" in params
        assert params["include_memberships"].default is False


class TestErrorEnvelope:
    @pytest.mark.asyncio
    async def test_auth_error_with_memberships(self, client_factory):
        client_factory(error=AuthError())

        result = await get_current_user(include_memberships=True)

        assert isinstance(result, dict)
        assert "error" in result
        assert "memberships" not in result

    @pytest.mark.asyncio
    async def test_forbidden_error_without_memberships(self, client_factory):
        client_factory(error=ForbiddenError())

        result = await get_current_user()

        assert isinstance(result, dict)
        assert "error" in result
