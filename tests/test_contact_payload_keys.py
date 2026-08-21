"""Contact serializer and list filters, against the CRM API's real payload shape.

The fixtures here mirror what a RedmineUP CRM instance actually returns: emails
as an array of objects, tags under ``tag_list``, an address sub-document with
the plugin's own field names, and ``custom_fields`` / ``author`` / ``projects``
that the serializer used to drop.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.contacts import (  # noqa: E402
    _contact_to_dict,
    manage_contact,
)

CRM_ON = {"REDMINE_CRM_ENABLED": "true"}


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
        result = _contact_to_dict(_api_contact())
        assert result["custom_fields"] == [
            {"id": 447, "name": "Account Owner", "value": "Bob Owner"},
            {"id": 440, "name": "ARR", "value": "147518"},
        ]

    def test_custom_fields_empty_when_absent(self):
        payload = _api_contact()
        del payload["custom_fields"]
        assert _contact_to_dict(payload)["custom_fields"] == []

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
    async def test_contact_attributes_are_not_sent_as_list_filters(
        self, mock_redmine
    ):
        """Only the CRM plugin's Pro build registers these as query filters.

        The Light build registers `tags` and nothing else, and Redmine drops an
        unregistered filter parameter in silence -- `build_from_params` only
        walks `available_filters` and `add_short_filter` returns early -- so the
        caller gets HTTP 200 and the whole collection, indistinguishable from a
        filter that matched everything. Sending them would make the answer wrong
        rather than merely unfiltered, so `list` leaves them off the query.
        """
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="list",
                first_name="Alice",
                last_name="Smith",
                middle_name="Q",
                company="Acme Industries",
                job_title="Education",
                email="alice@example.com",
                phone="+1-555-0100",
                offset=10,
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        for attribute in (
            "first_name",
            "last_name",
            "middle_name",
            "company",
            "job_title",
            "email",
            "phone",
            "author_id",
        ):
            assert attribute not in params
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
    async def test_bad_assigned_to_id_rejected(self, mock_redmine):
        with patch.dict(os.environ, CRM_ON):
            result = await manage_contact(action="list", assigned_to_id=0)
        assert "assigned_to_id" in result["error"]
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
            await manage_contact(
                action="list", limit=5, filters={"cf_42": "Bob Owner"}
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["cf_42"] == "Bob Owner"
        assert params["limit"] == 5

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.REDMINE_URL", "http://localhost:3000")
    @patch("redmine_mcp_server._client.redmine")
    async def test_a_contact_attribute_may_be_passed_through_filters(
        self, mock_redmine
    ):
        """Dropping them as named parameters must not make them unreachable.

        A caller who knows their build registers `company` -- the Pro one does
        -- can still filter on it, through the parameter that says plainly it
        cannot promise the build honours any given key.
        """
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(
                action="list", filters={"company": "Acme Industries"}
            )
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert params["company"] == "Acme Industries"


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
    async def test_is_company_is_not_forwarded_as_a_filter(self, mock_redmine):
        """The plugin's own `is_company` filter answers with the same wrong set
        for every value, so `list` leaves it off the query."""
        mock_redmine.engine.request.return_value = {"contacts": []}
        with patch.dict(os.environ, CRM_ON):
            await manage_contact(action="list", is_company=True)
        params = mock_redmine.engine.request.call_args.kwargs["params"]
        assert "is_company" not in params

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
            _contact_to_dict(_api_contact(custom_fields="oops"))["custom_fields"] == []
        )

    def test_non_dict_custom_field_entries_are_skipped(self):
        payload = _api_contact(
            custom_fields=[None, 5, {"id": 1, "name": "x", "value": "v"}]
        )
        assert _contact_to_dict(payload)["custom_fields"] == [
            {"id": 1, "name": "x", "value": "v"}
        ]

    def test_non_dict_projects_are_dropped_not_faked(self):
        payload = _api_contact(projects=[1, "x", None, {"id": 7, "name": "p"}])
        assert _contact_to_dict(payload)["projects"] == [{"id": 7, "name": "p"}]

    def test_projects_accepts_a_tuple(self):
        payload = _api_contact(projects=({"id": 7, "name": "p"},))
        assert _contact_to_dict(payload)["projects"] == [{"id": 7, "name": "p"}]

    def test_non_dict_author_is_null_not_a_fabricated_ref(self):
        assert _contact_to_dict(_api_contact(author="Carol"))["author"] is None
