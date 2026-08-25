"""Live integration tests for the RedmineUP CRM (PRO) tool family.

One test per REST action the CRM plugin exposes (``accept_api_auth`` in
its controllers), 24 in total, exercised through the MCP tool functions
against a real Redmine with CRM PRO installed:

    contacts           index, show, create, update, destroy
    contacts_projects  create, destroy
    contacts_tags      index
    notes              show, create, update, destroy
    crm_queries        index
    deals              index, show, create, update, destroy, add_product
    deal_statuses      index
    deal_categories    index, create, update, destroy

The module skips itself when ``REDMINE_URL`` is unset or the server has no
CRM plugin (``GET /contacts.json`` is not 200), and ``add_product`` skips
without the Products plugin (``GET /products.json``). Every test creates
what it needs and deletes it again, so the suite can run repeatedly on
both the 6.1 and 7.0 sandboxes.

Sandbox prerequisites (documented in the CRM section of the tool
reference): the API user's role holds the contact, deal, note and product
permissions; the ``contacts``, ``deals`` and ``products`` modules are on
for the test project; at least one deal status exists. Override the
project and status with ``REDMINE_TEST_PROJECT`` (default
``testing-project1``) and ``REDMINE_TEST_DEAL_STATUS_ID`` (default ``1``).
"""

import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._client import (  # noqa: E402
    REDMINE_API_KEY,
    REDMINE_PASSWORD,
    REDMINE_URL,
    REDMINE_USERNAME,
)
from redmine_mcp_server.tools.contacts import (  # noqa: E402
    list_contact_tags,
    manage_contact,
)
from redmine_mcp_server.tools.crm_notes import manage_crm_note  # noqa: E402
from redmine_mcp_server.tools.crm_queries import list_crm_queries  # noqa: E402
from redmine_mcp_server.tools.deals import (  # noqa: E402
    add_deal_product,
    list_deal_statuses,
    manage_deal,
    manage_deal_category,
)
from redmine_mcp_server.tools.products import manage_product  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not REDMINE_URL, reason="REDMINE_URL not configured"),
]

PROJECT = os.environ.get("REDMINE_TEST_PROJECT", "testing-project1")
STATUS_ID = int(os.environ.get("REDMINE_TEST_DEAL_STATUS_ID", "1"))
FLAGS = {
    "REDMINE_CRM_ENABLED": "true",
    "REDMINE_DEALS_ENABLED": "true",
    "REDMINE_PRODUCTS_ENABLED": "true",
    "REDMINE_MCP_READ_ONLY": "false",
}


def _probe(path: str) -> int:
    """HTTP status of a GET against the sandbox, 0 when unreachable."""
    if not REDMINE_URL:
        return 0
    kwargs = {"timeout": 10}
    if REDMINE_API_KEY:
        kwargs["headers"] = {"X-Redmine-API-Key": REDMINE_API_KEY}
    elif REDMINE_USERNAME:
        kwargs["auth"] = (REDMINE_USERNAME, REDMINE_PASSWORD or "")
    try:
        return requests.get(f"{REDMINE_URL}{path}", **kwargs).status_code
    except requests.RequestException:
        return 0


def _ok(result):
    """Assert a tool result is not an error envelope and return it."""
    assert not (isinstance(result, dict) and "error" in result), result
    return result


@pytest.fixture(scope="module")
def crm_available():
    if _probe("/contacts.json?limit=1") != 200:
        pytest.skip("CRM plugin not installed on this Redmine")


@pytest.fixture(scope="module")
def products_available():
    if _probe("/products.json?limit=1") != 200:
        pytest.skip("Products plugin not installed on this Redmine")


@pytest.fixture(autouse=True)
def _flags(monkeypatch, crm_available):
    for key, value in FLAGS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
async def contact():
    created = _ok(
        await manage_contact(
            "create",
            project_id=PROJECT,
            first_name="Integration",
            last_name="Contact",
            fields={"tag_list": "integration-tag"},
        )
    )
    try:
        yield created
    finally:
        await manage_contact("delete", contact_id=created["id"])


@pytest.fixture
async def deal():
    created = _ok(
        await manage_deal(
            "create", project_id=PROJECT, name="Integration deal", status_id=STATUS_ID
        )
    )
    try:
        yield created
    finally:
        await manage_deal("delete", deal_id=created["id"])


@pytest.fixture
async def category():
    created = _ok(
        await manage_deal_category("create", project_id=PROJECT, name="Integration cat")
    )
    try:
        yield created
    finally:
        await manage_deal_category("delete", category_id=created["id"])


@pytest.fixture
async def deal_note(deal):
    created = _ok(
        await manage_crm_note(
            "create",
            source_type="deal",
            source_id=deal["id"],
            project_id=PROJECT,
            content="integration note",
            subject="call",
            type_id=1,
        )
    )
    try:
        yield created
    finally:
        await manage_crm_note("delete", note_id=created["id"])


# --------------------------------------------------------------------------
# contacts: index, show, create, update, destroy
# --------------------------------------------------------------------------


class TestContacts:
    async def test_create_and_destroy(self):
        created = _ok(
            await manage_contact(
                "create", project_id=PROJECT, first_name="Temp", last_name="Person"
            )
        )
        assert created["first_name"] == "Temp"
        gone = _ok(await manage_contact("delete", contact_id=created["id"]))
        assert gone["success"] is True
        after = await manage_contact("get", contact_id=created["id"])
        assert "error" in after

    async def test_index(self, contact):
        listed = _ok(
            await manage_contact("list", project_id=PROJECT, search="Integration")
        )
        assert any(c["id"] == contact["id"] for c in listed)

    async def test_show(self, contact):
        got = _ok(await manage_contact("get", contact_id=contact["id"]))
        assert got["id"] == contact["id"]
        assert "integration-tag" in got["tags"]

    async def test_update(self, contact):
        _ok(
            await manage_contact(
                "update", contact_id=contact["id"], fields={"job_title": "Tester"}
            )
        )
        got = _ok(await manage_contact("get", contact_id=contact["id"]))
        assert got["job_title"] == "Tester"


# --------------------------------------------------------------------------
# contacts_projects: create, destroy
# --------------------------------------------------------------------------


class TestContactProjects:
    async def test_assign_and_remove(self, contact):
        from redmine_mcp_server.tools.projects import list_redmine_projects

        projects = _ok(await list_redmine_projects(limit=50))
        rows = projects["projects"] if isinstance(projects, dict) else projects
        others = [
            p
            for p in rows
            if str(p["id"]) != str(PROJECT) and p["identifier"] != PROJECT
        ]
        if not others:
            pytest.skip("need a second project to test project association")
        other = others[0]["id"]
        _ok(
            await manage_contact(
                "assign_to_project", contact_id=contact["id"], project_id=other
            )
        )
        _ok(
            await manage_contact(
                "remove_from_project", contact_id=contact["id"], project_id=other
            )
        )


# --------------------------------------------------------------------------
# contacts_tags: index
# --------------------------------------------------------------------------


class TestContactTags:
    async def test_index(self, contact):
        tags = _ok(await list_contact_tags())
        names = {t["name"] for t in tags}
        assert "integration-tag" in names
        assert all({"id", "name", "color"} <= set(t) for t in tags)


# --------------------------------------------------------------------------
# notes: show, create, update, destroy
# --------------------------------------------------------------------------


class TestNotes:
    async def test_create_and_destroy(self, deal):
        note = _ok(
            await manage_crm_note(
                "create",
                source_type="deal",
                source_id=deal["id"],
                project_id=PROJECT,
                content="temp",
            )
        )
        assert note["source"] == {
            "id": deal["id"],
            "name": deal["name"],
            "type": "deal",
        }
        gone = _ok(await manage_crm_note("delete", note_id=note["id"]))
        assert gone["success"] is True
        parent = _ok(await manage_deal("get", deal_id=deal["id"], include="notes"))
        assert "notes" not in parent

    async def test_show(self, deal_note):
        got = _ok(await manage_crm_note("get", note_id=deal_note["id"]))
        assert got["note_type"] == "call"
        assert "integration note" in got["content"]
        assert got["created_on"].startswith("20") and "T" in got["created_on"]

    async def test_update(self, deal_note):
        _ok(
            await manage_crm_note(
                "update", note_id=deal_note["id"], content="edited", type_id=2
            )
        )
        got = _ok(await manage_crm_note("get", note_id=deal_note["id"]))
        assert "edited" in got["content"] and got["note_type"] == "meeting"

    async def test_contact_note(self, contact):
        note = _ok(
            await manage_crm_note(
                "create",
                source_type="contact",
                source_id=contact["id"],
                project_id=PROJECT,
                content="on a contact",
            )
        )
        try:
            assert note["source"]["type"] == "contact"
        finally:
            await manage_crm_note("delete", note_id=note["id"])


# --------------------------------------------------------------------------
# crm_queries: index
# --------------------------------------------------------------------------


class TestCrmQueries:
    @pytest.mark.parametrize("object_type", ["contact", "deal"])
    async def test_index(self, object_type):
        queries = _ok(await list_crm_queries(object_type=object_type, limit=5))
        assert isinstance(queries, list)
        for q in queries:
            assert {"id", "name", "is_public", "project_id"} <= set(q)


# --------------------------------------------------------------------------
# deals: index, show, create, update, destroy, add_product
# --------------------------------------------------------------------------


class TestDeals:
    async def test_create_and_destroy(self):
        created = _ok(
            await manage_deal(
                "create",
                project_id=PROJECT,
                name="Temp deal",
                status_id=STATUS_ID,
                price=1234.5,
                currency="USD",
            )
        )
        # The plugin's parsed_price needs a string; a JSON number 500s.
        assert created["price"] == "1234.5"
        gone = _ok(await manage_deal("delete", deal_id=created["id"]))
        assert gone["success"] is True

    async def test_index(self, deal):
        listed = _ok(await manage_deal("list", project_id=PROJECT, status_id="*"))
        assert any(d["id"] == deal["id"] for d in listed)

    async def test_show(self, deal):
        got = _ok(await manage_deal("get", deal_id=deal["id"]))
        assert got["id"] == deal["id"] and got["status"]["id"] == STATUS_ID

    async def test_update(self, deal):
        _ok(
            await manage_deal(
                "update", deal_id=deal["id"], fields={"name": "Renamed", "price": "42"}
            )
        )
        got = _ok(await manage_deal("get", deal_id=deal["id"]))
        assert got["name"] == "Renamed" and float(got["price"]) == 42.0

    async def test_add_product(self, products_available, deal):
        product = _ok(
            await manage_product(
                "create",
                project_id=PROJECT,
                name="Integration widget",
                price="10.5",
                currency="USD",
                status_id=1,
            )
        )
        try:
            _ok(
                await add_deal_product(
                    deal_id=deal["id"], product_id=product["id"], quantity=3
                )
            )
            _ok(
                await add_deal_product(
                    deal_id=deal["id"],
                    description="Consulting",
                    quantity=2,
                    price=100,
                    tax=20,
                    discount=10,
                )
            )
            got = _ok(await manage_deal("get", deal_id=deal["id"], include="lines"))
            assert len(got["lines"]) == 2
            assert got["lines"][0]["product"]["id"] == product["id"]
            assert float(got["lines"][1]["total"]) == 180.0
            # 3 * 10.5 + 2 * 100 * 1.2 * 0.9, recalculated by the plugin
            assert float(got["price"]) == 247.5
        finally:
            _probe_delete(f"/products/{product['id']}.json")


def _probe_delete(path: str) -> None:
    """manage_product has no delete action; remove the product directly."""
    kwargs = {"timeout": 10}
    if REDMINE_API_KEY:
        kwargs["headers"] = {"X-Redmine-API-Key": REDMINE_API_KEY}
    elif REDMINE_USERNAME:
        kwargs["auth"] = (REDMINE_USERNAME, REDMINE_PASSWORD or "")
    try:
        requests.delete(f"{REDMINE_URL}{path}", **kwargs)
    except requests.RequestException:  # pragma: no cover - cleanup only
        pass


# --------------------------------------------------------------------------
# deal_statuses: index (admin-only in the plugin)
# --------------------------------------------------------------------------


class TestDealStatuses:
    async def test_index(self):
        result = _ok(await list_deal_statuses(project_id=PROJECT))
        if result["statuses"] is None:
            assert "administrator" in result["statuses_error"]
        else:
            assert any(s["id"] == STATUS_ID for s in result["statuses"])
            assert {s["status_type"] for s in result["statuses"]} <= {
                "open",
                "won",
                "lost",
                None,
            }
        assert isinstance(result["categories"], list)


# --------------------------------------------------------------------------
# deal_categories: index, create, update, destroy
# --------------------------------------------------------------------------


class TestDealCategories:
    async def test_create_and_destroy_reassigning_deals(self, deal):
        first = _ok(
            await manage_deal_category("create", project_id=PROJECT, name="Cat A")
        )
        second = _ok(
            await manage_deal_category("create", project_id=PROJECT, name="Cat B")
        )
        try:
            _ok(
                await manage_deal(
                    "update", deal_id=deal["id"], fields={"category_id": first["id"]}
                )
            )
            gone = _ok(
                await manage_deal_category(
                    "delete", category_id=first["id"], reassign_to_id=second["id"]
                )
            )
            assert "reassigned" in gone["message"]
            got = _ok(await manage_deal("get", deal_id=deal["id"]))
            assert got["category"]["id"] == second["id"]
        finally:
            await manage_deal_category("delete", category_id=second["id"])

    async def test_index(self, category):
        listed = _ok(await manage_deal_category("list", project_id=PROJECT))
        assert any(c["id"] == category["id"] for c in listed)

    async def test_update(self, category):
        _ok(
            await manage_deal_category(
                "update", category_id=category["id"], name="Integration cat 2"
            )
        )
        listed = _ok(await manage_deal_category("list", project_id=PROJECT))
        assert any(
            c["id"] == category["id"] and c["name"] == "Integration cat 2"
            for c in listed
        )

    async def test_duplicate_name_is_validation_error(self, category):
        dup = await manage_deal_category(
            "create", project_id=PROJECT, name="Integration cat"
        )
        assert "already been taken" in dup["error"]
