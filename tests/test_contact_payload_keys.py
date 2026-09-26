"""Contact serializer and list filters, against the CRM API's real payload shape.

The fixtures here mirror what a RedmineUP CRM instance actually returns: emails
as an array of objects, tags under ``tag_list``, an address sub-document with
the plugin's own field names, and ``custom_fields`` / ``author`` / ``projects``
that the serializer used to drop.
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.contacts import (  # noqa: E402
    _contact_includes_to_dict,
    _contact_to_dict,
    manage_contact,
)

CRM_ON = {"REDMINE_CRM_ENABLED": "true"}
# The Pro-only list filters are refused unless the deployment says so.
CRM_PRO = {"REDMINE_CRM_ENABLED": "true", "REDMINE_CRM_EDITION": "pro"}


def _api_contact(**overrides) -> dict:
    """A contact as the CRM API renders it on ``GET /contacts.json``."""
    contact = {
        "id": 55,
        "first_name": "Acme Industries",
        "last_name": "",
        "middle_name": "",
        "company": "",
        "job_title": "Education",
        "emails": [{"address": "ops@acme.example"}],
        "website": "",
        "skype_name": "",
        "birthday": None,
        "background": "",
        "address": {
            "full_address": "1 Main St, Boston",
            "street": "1 Main St",
            "city": "Boston",
            "region": None,
            "country": "US",
            "postcode": "02101",
        },
        "is_company": True,
        "tag_list": ["strategic"],
        "author": {"id": 54, "name": "Carol Author"},
        "assigned_to": {"id": 12, "name": "Bob Owner"},
        "custom_fields": [
            {"id": 447, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 440, "name": "ARR", "value": "147518"},
        ],
        "created_on": "2026-04-20T10:00:00Z",
        "updated_on": "2026-04-20T11:00:00Z",
    }
    contact.update(overrides)
    return contact


class TestSerializerReadsWhatTheApiSends:
    def test_custom_fields_are_returned(self):
        result = _contact_to_dict(_api_contact(), include_custom_fields=True)
        assert result["custom_fields"] == [
            {"id": 447, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 440, "name": "ARR", "value": "147518"},
        ]

    def test_custom_fields_empty_when_absent(self):
        payload = _api_contact()
        del payload["custom_fields"]
        assert (
            _contact_to_dict(payload, include_custom_fields=True)["custom_fields"] == []
        )

    def test_custom_fields_are_elided_unless_asked_for(self):
        # Present and None, not absent: the key never disappears, so a caller
        # reading it gets no KeyError, and None ("not requested") is a
        # different claim from [] ("this contact has none").
        result = _contact_to_dict(_api_contact())
        assert result["custom_fields"] is None
        assert result["custom_fields_count"] == 2

    def test_an_elided_none_is_distinguishable_from_an_empty_set(self):
        payload = _api_contact(custom_fields=[])
        assert _contact_to_dict(payload)["custom_fields"] is None
        assert _contact_to_dict(payload)["custom_fields_count"] == 0
        asked = _contact_to_dict(payload, include_custom_fields=True)
        assert asked["custom_fields"] == []
        assert "custom_fields_count" not in asked

    def test_author_is_returned(self):
        assert _contact_to_dict(_api_contact())["author"] == {
            "id": 54,
            "name": "Carol Author",
        }

    def test_emails_array_populates_both_keys(self):
        result = _contact_to_dict(_api_contact())
        assert result["emails"] == ["ops@acme.example"]
        assert result["email"] == "ops@acme.example"

    def test_phones_array_populates_both_keys(self):
        result = _contact_to_dict(_api_contact(phones=[{"number": "+1-555-0100"}]))
        assert result["phones"] == ["+1-555-0100"]
        assert result["phone"] == "+1-555-0100"

    def test_every_email_is_kept(self):
        result = _contact_to_dict(
            _api_contact(
                emails=[{"address": "a@x.example"}, {"address": "b@x.example"}]
            )
        )
        assert result["emails"] == ["a@x.example", "b@x.example"]
        assert result["email"] == "a@x.example"

    def test_missing_channel_is_null_not_an_error(self):
        payload = _api_contact()
        del payload["emails"]
        result = _contact_to_dict(payload)
        assert result["email"] is None
        assert result["emails"] == []
        assert result["phone"] is None
        assert result["phones"] == []

    def test_scalar_spelling_still_works(self):
        """A payload using the scalar keys keeps the old output unchanged."""
        payload = _api_contact()
        del payload["emails"]
        payload["email"] = "alice@example.com"
        payload["phone"] = "+1-555-0100"
        result = _contact_to_dict(payload)
        assert result["email"] == "alice@example.com"
        assert result["phone"] == "+1-555-0100"

    def test_tags_come_from_tag_list(self):
        assert _contact_to_dict(_api_contact())["tags"] == ["strategic"]

    def test_tags_falls_back_to_the_tags_key(self):
        payload = _api_contact()
        del payload["tag_list"]
        payload["tags"] = ["lead"]
        assert _contact_to_dict(payload)["tags"] == ["lead"]

    def test_address_keeps_the_fields_the_plugin_sends(self):
        address = _contact_to_dict(_api_contact())["address"]
        assert address["full_address"] == "1 Main St, Boston"
        assert address["street"] == "1 Main St"
        assert address["city"] == "Boston"

    def test_projects_only_appears_when_the_payload_carries_it(self):
        """An absent include is not reported as an empty list."""
        assert "projects" not in _contact_to_dict(_api_contact())
        result = _contact_to_dict(
            _api_contact(projects=[{"id": 76, "name": "Acme Rollout"}])
        )
        assert result["projects"] == [{"id": 76, "name": "Acme Rollout"}]


class TestFallbacksForAnExplicitNull:
    """A key present but null must still fall back to the other spelling.

    ``dict.get(key, default)`` applies the default only when the key is
    absent, so a payload sending ``"emails": null`` alongside a populated
    scalar ``email`` would otherwise report no address at all.
    """

    def test_null_emails_falls_back_to_the_scalar_key(self):
        payload = _api_contact(emails=None, email="alice@example.com")
        result = _contact_to_dict(payload)
        assert result["emails"] == ["alice@example.com"]
        assert result["email"] == "alice@example.com"

    def test_null_phones_falls_back_to_the_scalar_key(self):
        payload = _api_contact(phones=None, phone="+1-555-0100")
        result = _contact_to_dict(payload)
        assert result["phones"] == ["+1-555-0100"]
        assert result["phone"] == "+1-555-0100"

    def test_null_tag_list_falls_back_to_tags(self):
        payload = _api_contact(tag_list=None, tags=["lead"])
        assert _contact_to_dict(payload)["tags"] == ["lead"]


class TestTagCoercion:
    """Tags go through the shared coercion, which accepts either shape."""

    def test_comma_separated_tag_list_is_split(self):
        result = _contact_to_dict(_api_contact(tag_list="strategic, renewal"))
        assert result["tags"] == ["strategic", "renewal"]

    def test_blank_tags_are_dropped_and_names_stripped(self):
        result = _contact_to_dict(_api_contact(tag_list=[" a ", "", "b"]))
        assert result["tags"] == ["a", "b"]

    def test_absent_tags_are_empty(self):
        payload = _api_contact()
        del payload["tag_list"]
        assert _contact_to_dict(payload)["tags"] == []


class TestAssignedTo:
    def test_assigned_to_uses_the_shared_ref_shape(self):
        assert _contact_to_dict(_api_contact())["assigned_to"] == {
            "id": 12,
            "name": "Bob Owner",
        }

    def test_absent_assigned_to_is_null(self):
        payload = _api_contact()
        del payload["assigned_to"]
        assert _contact_to_dict(payload)["assigned_to"] is None


class TestListFilters:
    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_named_filters_reach_redmine(self, mock_redmine):
        """The Pro build registers all seven, verified against 4.4.5 PRO."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_PRO):
            await manage_contact(
                action="list",
                first_name="Alice",
                last_name="Smith",
                middle_name="Q",
                company="Acme Industries",
                job_title="Education",
                email="alice@example.com",
                phone="+1-555-0100",
                author_id=54,
                offset=10,
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Smith"
        assert params["middle_name"] == "Q"
        assert params["company"] == "Acme Industries"
        assert params["job_title"] == "Education"
        assert params["email"] == "alice@example.com"
        assert params["phone"] == "+1-555-0100"
        assert params["author_id"] == 54
        assert params["offset"] == 10

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_portable_filters_still_reach_redmine(self, mock_redmine):
        """`tags` is the one filter every build registers; `search` bypasses the
        filter mechanism entirely (the controller hands it to `live_search`);
        `assigned_to_id` predates this change."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="list", tags="vip", search="acme", assigned_to_id=12
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["tags"] == "vip"
        assert params["search"] == "acme"
        assert params["assigned_to_id"] == 12

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_custom_field_filter_reaches_redmine(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", filters={"cf_42": "Bob Owner"})
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["cf_42"] == "Bob Owner"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_zero_offset_is_not_sent(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list")
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "offset" not in params

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_negative_offset_rejected(self, mock_redmine):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", offset=-1)
        assert "offset" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    @pytest.mark.parametrize("name", ["assigned_to_id", "author_id"])
    async def test_bad_user_id_rejected(self, mock_redmine, name):
        with patch.dict(os.environ, CRM_PRO):
            result = await manage_contact(action="list", **{name: 0})
        assert name in result["error"]
        mock_redmine.engine.request.assert_not_called()


class TestFiltersCannotReachAValidatedParameter:
    """`filters` is for keys the signature does not name.

    Accepting a name it does name would give a caller a second, unchecked
    route to the same parameter — and a `limit` raised that way is only bytes
    Redmine renders and the local slice discards.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad",
        [
            {"limit": 100},
            {"offset": 500},
            {"project_id": "x"},
            {"assigned_to_id": -1},
            {"search": "y"},
            {"tags": "vip"},
            {"first_name": "Bob"},
            {"is_company": "TRUE"},
        ],
    )
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_owned_key_in_filters_is_refused(self, mock_redmine, bad):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", limit=5, filters=bad)
        assert next(iter(bad)) in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_custom_field_filter_is_still_accepted(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", limit=5, filters={"cf_42": "Bob Owner"})
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["cf_42"] == "Bob Owner"
        assert params["limit"] == 5


class TestFiltersThatWouldCorruptTheQuery:
    """Redmine reads `fields`/`f` as the query's filter-field list and clears
    the query's filters when either is present, so neither may go on the wire.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reserved", ["fields", "f", "query_id", "f[]", "fields[]"])
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_reserved_filter_key_is_refused(self, mock_redmine, reserved):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", filters={reserved: "first_name"}
            )
        assert reserved in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_tools_own_fields_parameter_never_reaches_the_wire(
        self, mock_redmine
    ):
        """`fields` carries create/update attributes and the dispatcher hands it
        to every action, so `list` must drop it rather than forward it."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="list",
                fields={"job_title": "Director"},
                filters={"cf_42": "Bob Owner"},
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "fields" not in params
        assert params["cf_42"] == "Bob Owner"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_non_dict_filters_rejected(self, mock_redmine):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", filters="cf_42=x")
        assert "filters" in result["error"]
        mock_redmine.engine.request.assert_not_called()


class TestSerializerEdgeCases:
    """Shapes a decoded plugin payload can carry that a resource never could."""

    def test_empty_channel_array_falls_back_to_the_scalar(self):
        payload = _api_contact(emails=[], email="alice@example.com")
        assert _contact_to_dict(payload)["email"] == "alice@example.com"

    def test_no_cross_channel_contamination(self):
        """A street address must never be reported as a phone number."""
        result = _contact_to_dict(_api_contact(phones=[{"address": "1 Main St"}]))
        assert result["phones"] == []
        assert result["phone"] is None

    def test_channel_values_are_stripped(self):
        result = _contact_to_dict(_api_contact(emails=[{"address": " a@b.example "}]))
        assert result["emails"] == ["a@b.example"]

    def test_dict_tags_are_reduced_to_names(self):
        payload = _api_contact(tag_list=None, tags=[{"id": 3, "name": "lead"}])
        assert _contact_to_dict(payload)["tags"] == ["lead"]

    def test_scalar_custom_fields_are_not_iterated_as_characters(self):
        assert (
            _contact_to_dict(
                _api_contact(custom_fields="oops"), include_custom_fields=True
            )["custom_fields"]
            == []
        )

    def test_non_dict_custom_field_entries_are_skipped(self):
        payload = _api_contact(
            custom_fields=[None, 5, {"id": 1, "name": "x", "value": "v"}]
        )
        assert _contact_to_dict(payload, include_custom_fields=True)[
            "custom_fields"
        ] == [{"id": 1, "name": "x", "value": "v"}]

    def test_non_dict_projects_are_dropped_not_faked(self):
        payload = _api_contact(projects=[1, "x", None, {"id": 7, "name": "p"}])
        assert _contact_to_dict(payload)["projects"] == [{"id": 7, "name": "p"}]

    def test_projects_accepts_a_tuple(self):
        payload = _api_contact(projects=({"id": 7, "name": "p"},))
        assert _contact_to_dict(payload)["projects"] == [{"id": 7, "name": "p"}]

    def test_non_dict_author_is_null_not_a_fabricated_ref(self):
        assert _contact_to_dict(_api_contact(author="Carol"))["author"] is None


class TestTheProOnlyFiltersAreGated:
    """The CRM plugin ships two builds and only one registers these filters.

    Redmine drops an unregistered filter parameter without erroring, so a Light
    install would answer 200 with the whole collection — indistinguishable from
    a filter that matched everything. Refusing the parameter is the only honest
    option, since the build cannot be detected: plugin versions are exposed
    only through `admin/plugins`, which is HTML and admin-only.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"first_name": "Alice"},
            {"last_name": "Smith"},
            {"middle_name": "Q"},
            {"company": "Acme Industries"},
            {"job_title": "Education"},
            {"email": "alice@example.com"},
            {"phone": "+1-555-0100"},
            {"author_id": 54},
            {"is_company": True},
            {"is_company": False},
        ],
    )
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_refused_by_default(self, mock_redmine, kwargs):
        """Default is `light`: the build that registers fewer filters, so an
        unconfigured deployment refuses rather than answers wrongly."""
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", **kwargs)
        assert next(iter(kwargs)) in result["error"]
        assert "REDMINE_CRM_EDITION=pro" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_every_refused_name_is_reported_at_once(self, mock_redmine):
        """A caller passing several should not have to discover them one call
        at a time."""
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", company="Acme Industries", job_title="Education"
            )
        assert "company" in result["error"]
        assert "job_title" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_portable_parameters_are_never_gated(self, mock_redmine):
        """`tags` is registered on both builds and `search` bypasses the filter
        mechanism, so neither depends on the edition. `assigned_to_id` is absent
        from Light's ContactQuery too, but it predates this gate and is left
        alone rather than newly refused."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="list", tags="vip", search="acme", assigned_to_id=12
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["tags"] == "vip"
        assert params["search"] == "acme"
        assert params["assigned_to_id"] == 12

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_filters_dict_is_not_gated(self, mock_redmine):
        """`filters` never promised the build honours a key, so gating it would
        remove the only route left on an undeclared install."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", filters={"cf_42": "Bob Owner"})
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["cf_42"] == "Bob Owner"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_an_unknown_edition_is_an_error_not_a_guess(self, mock_redmine):
        with patch.dict(
            os.environ,
            {**CRM_ON, "REDMINE_CRM_EDITION": "enterprise"},
        ):
            result = await manage_contact(action="list", company="Acme Industries")
        assert "REDMINE_CRM_EDITION" in result["error"]
        assert "enterprise" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_edition_is_read_case_insensitively(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, {**CRM_ON, "REDMINE_CRM_EDITION": "  PRO "}):
            await manage_contact(action="list", company="Acme Industries")
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["company"] == "Acme Industries"


class TestOutputFieldSelection:
    """``include_custom_fields`` on ``list``, the tool's one output selector.

    The CRM API renders every custom field on every contact whether or not it
    carries a value -- ``render_api_custom_values`` is unconditional in the
    plugin's ``contacts/index.api.rsb`` -- so the saving is in what the tool
    returns, not in what it fetches.

    Unlike ``list_redmine_issues`` and ``list_redmine_projects``, whose flags
    were purely additive, this one narrows a response callers already get, so
    the key is elided the way #315 elides a long journal value rather than
    dropped: ``custom_fields`` stays present as ``None`` beside
    ``custom_fields_count``.
    """

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_listed_contact_elides_custom_fields_by_default(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": [_api_contact()]}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list")
        assert result[0]["custom_fields"] is None
        assert result[0]["custom_fields_count"] == 2
        # Everything else the row carried is still there.
        assert result[0]["id"] == 55
        assert result[0]["job_title"] == "Education"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_flag_adds_them_back(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": [_api_contact()]}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_custom_fields=True)
        assert result[0]["custom_fields"] == [
            {"id": 447, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 440, "name": "ARR", "value": "147518"},
        ]
        # The count is the elision's companion, so it goes when the values come.
        assert "custom_fields_count" not in result[0]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_flag_is_not_sent_to_redmine(self, mock_redmine):
        """It selects the response shape; Redmine has no such parameter and
        would ignore it, so sending it would only be noise on the wire."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", include_custom_fields=True)
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "include_custom_fields" not in params

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_flag_costs_no_second_request(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": [_api_contact()]}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", include_custom_fields=True)
        assert mock_redmine.engine.request.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_filters_may_not_carry_it(self, mock_redmine):
        """Through ``filters`` it would reach Redmine as an unregistered key,
        be ignored there, and leave the caller with the rows they asked to do
        without -- so it is refused and named."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", filters={"include_custom_fields": True}
            )
        assert "include_custom_fields" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_single_contact_read_is_unchanged(self, mock_redmine):
        """``get`` carries them always, the way ``get_redmine_issue`` does:
        the collection is where the cost is, and reading one contact in full
        is the answer to wanting one field off it."""
        mock_redmine.engine.request.return_value = {"contact": _api_contact()}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="get", contact_id=55)
        assert result["custom_fields"] == [
            {"id": 447, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 440, "name": "ARR", "value": "147518"},
        ]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_pagination_envelope_still_carries_the_narrowed_rows(
        self, mock_redmine
    ):
        mock_redmine.engine.request.return_value = {
            "contacts": [_api_contact()],
            "total_count": 1,
            "limit": 100,
            "offset": 0,
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", include_pagination_info=True)
        assert result["contacts"][0]["custom_fields"] is None
        assert result["contacts"][0]["custom_fields_count"] == 2
        assert result["pagination"]["total"] == 1


def _contact_with_three_fields() -> dict:
    return _api_contact(
        custom_fields=[
            {"id": 42, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 43, "name": "Region", "value": ""},
            {"id": 44, "name": "Tier", "value": "Gold"},
        ]
    )


class TestCustomFieldSelection:
    """``custom_field_ids`` on ``list``: the fields a lookup needs, not all of
    them or none (#352).

    It narrows ``include_custom_fields`` rather than adding a second shape:
    ``custom_fields`` holds only the named fields with no
    ``custom_fields_count``, since they were requested, and ``[]`` still means
    the contact carries none of them.
    """

    def test_only_the_named_fields_are_returned(self):
        result = _contact_to_dict(
            _contact_with_three_fields(), custom_field_ids=[44, 42]
        )
        # Payload order, not request order.
        assert result["custom_fields"] == [
            {"id": 42, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 44, "name": "Tier", "value": "Gold"},
        ]
        assert "custom_fields_count" not in result

    def test_a_field_with_an_empty_value_is_still_returned(self):
        """Selection is by id, not by whether the field carries a value."""
        result = _contact_to_dict(_contact_with_three_fields(), custom_field_ids=[43])
        assert result["custom_fields"] == [{"id": 43, "name": "Region", "value": ""}]

    def test_an_id_the_contact_does_not_carry_answers_an_empty_list(self):
        result = _contact_to_dict(_contact_with_three_fields(), custom_field_ids=[99])
        assert result["custom_fields"] == []
        assert "custom_fields_count" not in result

    def test_a_contact_with_no_custom_fields(self):
        result = _contact_to_dict(_api_contact(custom_fields=[]), custom_field_ids=[42])
        assert result["custom_fields"] == []
        assert "custom_fields_count" not in result

    def test_the_ids_narrow_even_with_the_flag_on(self):
        result = _contact_to_dict(
            _contact_with_three_fields(),
            include_custom_fields=True,
            custom_field_ids=[42],
        )
        assert [cf["id"] for cf in result["custom_fields"]] == [42]

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_list_returns_only_the_named_fields(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "contacts": [_contact_with_three_fields()]
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", custom_field_ids=[42])
        assert result[0]["custom_fields"] == [
            {"id": 42, "name": "Account Owner", "value": "Bob Owner"}
        ]
        assert "custom_fields_count" not in result[0]
        assert mock_redmine.engine.request.call_count == 1

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_it_is_not_sent_to_redmine(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", custom_field_ids=[42])
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "custom_field_ids" not in params

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_the_pagination_envelope_carries_the_narrowed_rows(
        self, mock_redmine
    ):
        mock_redmine.engine.request.return_value = {
            "contacts": [_contact_with_three_fields()],
            "total_count": 1,
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", custom_field_ids=[44], include_pagination_info=True
            )
        assert [cf["id"] for cf in result["contacts"][0]["custom_fields"]] == [44]
        assert result["pagination"]["total"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad",
        [[], [0], [-3], ["42"], [True], [42, None], [4.2], "42", 42],
    )
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_malformed_ids_are_refused(self, mock_redmine, bad):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", custom_field_ids=bad)
        assert "custom_field_ids" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_filters_may_not_carry_it(self, mock_redmine):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="list", filters={"custom_field_ids": "42"}
            )
        assert "custom_field_ids" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_single_contact_read_still_returns_every_field(self, mock_redmine):
        """``list`` only: ``get`` keeps returning the full set."""
        mock_redmine.engine.request.return_value = {
            "contact": _contact_with_three_fields()
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="get", contact_id=55, custom_field_ids=[42]
            )
        assert [cf["id"] for cf in result["custom_fields"]] == [42, 43, 44]



def _api_contact_with_includes() -> dict:
    """A contact as ``contacts/show.api.rsb`` renders it under
    ``include=notes,contacts,deals,issues`` (redmine_contacts 4.4.5 PRO)."""
    return _api_contact(
        notes=[
            {
                "id": 7,
                "content": "Called about renewal",
                "type_id": 1,
                "author": {"id": 54, "name": "Carol Author"},
                "created_on": "2026-05-01T09:00:00Z",
                "updated_on": "2026-05-01T09:30:00Z",
            }
        ],
        contacts=[{"id": 56, "name": "Alice Example"}],
        deals=[
            {
                "id": 3,
                "price": "1500.0",
                "currency": "USD",
                "price_type": 0,
                "name": "Renewal",
                "project": {"id": 2, "name": "Sales"},
                "status": {"id": 1, "name": "Pending"},
                "background": "Multi-year",
                "created_on": "2026-05-02T09:00:00Z",
                "updated_on": "2026-05-03T09:00:00Z",
            }
        ],
        issues=[
            {
                "id": 101,
                "subject": "Onboarding",
                "status": {"id": 1, "name": "New"},
                "due_date": "2026-06-01",
                "created_on": "2026-05-04T09:00:00Z",
                "updated_on": "2026-05-05T09:00:00Z",
            }
        ],
    )


class TestGetIncludes:
    """``include`` on ``get`` returns what the plugin renders for it (#354).

    ``contacts/show.api.rsb`` honours exactly four includes -- ``notes``,
    ``contacts``, ``deals`` and ``issues`` -- and the serializer used to drop
    all four, so every include came back as the bare contact.
    """

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_every_include_is_returned(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "contact": _api_contact_with_includes()
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="get", contact_id=55, include="notes,contacts,deals,issues"
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["include"] == "notes,contacts,deals,issues"
        note = result["notes"][0]
        assert (note["id"], note["type_id"]) == (7, 1)
        assert note["author"] == {"id": 54, "name": "Carol Author"}
        assert note["created_on"] == "2026-05-01T09:00:00Z"
        assert "Called about renewal" in result["notes"][0]["content"]
        assert result["contacts"] == [{"id": 56, "name": "Alice Example"}]
        assert result["deals"][0]["name"] == "Renewal"
        assert result["deals"][0]["status"] == {"id": 1, "name": "Pending"}
        assert result["deals"][0]["project"] == {"id": 2, "name": "Sales"}
        assert result["issues"] == [
            {
                "id": 101,
                "subject": "Onboarding",
                "status": {"id": 1, "name": "New"},
                "due_date": "2026-06-01",
                "created_on": "2026-05-04T09:00:00Z",
                "updated_on": "2026-05-05T09:00:00Z",
            }
        ]

    def test_free_text_is_wrapped(self):
        result = _contact_to_dict(_api_contact_with_includes())
        includes = _contact_includes_to_dict(_api_contact_with_includes())
        assert includes["notes"][0]["content"].startswith("<insecure-content")
        assert includes["deals"][0]["background"].startswith("<insecure-content")
        # The list serializer is unchanged: includes are a `get` concern.
        assert "notes" not in result

    def test_an_embedded_deal_carries_only_the_keys_rendered(self):
        """Not ``_deal_to_dict``: that would report ``None`` for keys such as
        ``probability`` that the embedded template never sends."""
        deal = _contact_includes_to_dict(_api_contact_with_includes())["deals"][0]
        assert set(deal) == {
            "id",
            "name",
            "price",
            "currency",
            "price_type",
            "project",
            "status",
            "background",
            "created_on",
            "updated_on",
        }

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_an_include_the_payload_lacks_is_absent_not_empty(self, mock_redmine):
        """The plugin omits an array that is empty or not visible to the
        caller, and cannot say which, so neither does the tool."""
        mock_redmine.engine.request.return_value = {"contact": _api_contact()}
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="get", contact_id=55, include="deals")
        assert "deals" not in result
        assert result["id"] == 55

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_non_dict_entries_are_dropped(self, mock_redmine):
        mock_redmine.engine.request.return_value = {
            "contact": _api_contact(contacts=[{"id": 56, "name": "A"}, "junk", None])
        }
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(
                action="get", contact_id=55, include="contacts"
            )
        assert result["contacts"] == [{"id": 56, "name": "A"}]



class TestIsCompanyFilter:
    """``is_company`` on ``list``, spelled so every database adapter reads it
    (#366).

    ``ContactQuery#sql_for_is_company_field`` (redmine_contacts 4.4.5) treats
    a value as true only when it equals the adapter's ``quoted_true``, whose
    spelling varies by adapter and Rails version, and as false otherwise, so
    no fixed literal means true everywhere. ``"0"`` is nobody's true, so it
    means false everywhere, and ``"!0"`` negates it.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag, wire", [(True, "!0"), (False, "0")])
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_sent_as_the_adapter_independent_value(
        self, mock_redmine, flag, wire
    ):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_PRO):
            await manage_contact(action="list", is_company=flag)
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["is_company"] == wire

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_left_out_it_does_not_filter(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list")
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "is_company" not in params

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_it_combines_with_the_other_filters(self, mock_redmine):
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_PRO):
            await manage_contact(
                action="list", is_company=True, company="Acme", filters={"cf_42": "x"}
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["is_company"] == "!0"
        assert params["company"] == "Acme"
        assert params["cf_42"] == "x"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["TRUE", "1", 1, 0])
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_non_boolean_is_refused(self, mock_redmine, bad):
        with patch.dict(os.environ, CRM_PRO):
            result = await manage_contact(action="list", is_company=bad)
        assert "is_company" in result["error"]
        mock_redmine.engine.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag", [None, False, True])
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_create_still_files_a_person_unless_told(self, mock_redmine, flag):
        mock_redmine.engine.request.return_value = {"contact": _api_contact()}
        kwargs = {} if flag is None else {"is_company": flag}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="create", project_id="sales", first_name="Acme", **kwargs
            )
        body = json.loads(mock_redmine.engine.request.call_args.kwargs["data"])
        assert body["contact"]["is_company"] is bool(flag)
